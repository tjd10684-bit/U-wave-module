"""Deterministic in-memory U-WAVE-R for tests and development without hardware.

Speaks the wire format for specific-channel DR requests and IR requests and
answers with DT, ST, TI or RI as documented. It does not model radio timing,
button-driven output, editing states or all-channel DR searches. IR searches
include their starting channel, an assumption still to be confirmed on
hardware. Extend it only with behavior confirmed against the manual or hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .protocol import (
    BAND_IDS, DataRequest, Destination, InfoRequest, MeasurementMode, MeasurementPacket, PacketFramer,
    ReceiverInfo, Search, StatusCode, StatusPacket, TransmitterInfo, TransmitterState, Unit,
)


class ManualClock:
    """A monotonic clock that moves only when advanced, including by simulated waits."""

    def __init__(self, start: float = 0.0):
        self.time = start

    def __call__(self) -> float:
        return self.time

    def advance(self, seconds: float) -> None:
        self.time += seconds


@dataclass
class SimulatedTransmitter:
    device_id: str
    value: Decimal | None = None  # None: the receiver holds no data for it
    unit: Unit | None = "mm"
    connected: bool = True
    mode: MeasurementMode = MeasurementMode.EVENT_DRIVEN


class SimulatedReceiver:
    """A Transport whose replies follow the receiver's documented DR and IR behavior."""

    def __init__(
        self, group: int = 0, *, device_id: str = "0000000001", band_id: int = BAND_IDS[0],
        clock: ManualClock | None = None, chunk_size: int | None = None,
    ):
        self.group = group
        self.device_id = device_id
        self.band_id = band_id
        self.clock = clock
        self.chunk_size = chunk_size
        self.responding = True
        self.transmitters: dict[int, SimulatedTransmitter] = {}
        self.requests: list[DataRequest | InfoRequest] = []
        self._framer = PacketFramer()
        self._output = bytearray()
        self._held = bytearray()
        self._interleaved = bytearray()

    def register(
        self, channel: int, device_id: str, value: str | None = None, unit: Unit | None = "mm", *,
        connected: bool = True, mode: MeasurementMode = MeasurementMode.EVENT_DRIVEN,
    ) -> SimulatedTransmitter:
        transmitter = SimulatedTransmitter(
            device_id, None if value is None else Decimal(value), unit, connected, mode,
        )
        self.transmitters[channel] = transmitter
        return transmitter

    def inject(self, data: bytes) -> None:
        """Make raw bytes readable now: stale replies, unsolicited packets or noise."""
        self._output += data

    def interleave(self, data: bytes) -> None:
        """Emit raw bytes after the next request arrives, ahead of its reply."""
        self._interleaved += data

    def release_held(self) -> None:
        """Deliver replies withheld while not responding, i.e. late replies."""
        self._output += self._held
        self._held.clear()

    def write(self, data: bytes) -> None:
        for raw in self._framer.feed(data):
            request = InfoRequest.decode(raw) if raw.startswith(b"IR") else DataRequest.decode(raw)
            self.requests.append(request)
            self._output += self._interleaved
            self._interleaved.clear()
            reply = self._info_reply(request) if isinstance(request, InfoRequest) else self._reply(request)
            (self._output if self.responding else self._held).extend(reply)

    def read(self, timeout: float) -> bytes:
        if not self._output:
            if self.clock is not None and timeout > 0:
                self.clock.advance(timeout)
            return b""
        size = self.chunk_size or len(self._output)
        data = bytes(self._output[:size])
        del self._output[:size]
        return data

    def _reply(self, request: DataRequest) -> bytes:
        if request.channel is None or request.search != Search.SPECIFIC:
            raise NotImplementedError("The simulator answers specific-channel requests only.")
        transmitter = self.transmitters.get(request.channel)
        if request.group != self.group or transmitter is None:
            return StatusPacket(request.group, request.channel, None, StatusCode.REQUEST_ERROR).encode()
        if not transmitter.connected:
            code = StatusCode.TRANSMITTER_DISCONNECTED
        elif transmitter.value is None:
            code = StatusCode.NO_DATA
        else:
            packet = MeasurementPacket(self.group, request.channel, transmitter.value, transmitter.unit)
            if request.clear_after_output:
                transmitter.value = None
            return packet.encode()
        return StatusPacket(self.group, request.channel, transmitter.device_id, code).encode()

    def transmitter_info(self, channel: int) -> TransmitterInfo:
        transmitter = self.transmitters[channel]
        state = TransmitterState.CONNECTED if transmitter.connected else TransmitterState.DISCONNECTED
        return TransmitterInfo(state, channel, self.group, transmitter.device_id, self.band_id, transmitter.mode)

    def _info_reply(self, request: InfoRequest) -> bytes:
        if request.group != self.group:
            return StatusPacket(request.group, request.channel, None, StatusCode.REQUEST_ERROR).encode()
        if request.destination == Destination.RECEIVER:
            return ReceiverInfo(self.group, self.device_id, self.band_id, 0, False, (0,) * len(BAND_IDS)).encode()
        if request.search == Search.SPECIFIC:
            channels, failure = [request.channel], StatusCode.REQUEST_ERROR
        elif request.search == Search.ASCENDING:
            channels, failure = range(request.channel, 100), StatusCode.END_OF_SEARCH
        else:
            channels, failure = range(request.channel, -1, -1), StatusCode.END_OF_SEARCH
        for channel in channels:
            if channel in self.transmitters:
                return self.transmitter_info(channel).encode()
        return StatusPacket(request.group, request.channel, None, failure).encode()
