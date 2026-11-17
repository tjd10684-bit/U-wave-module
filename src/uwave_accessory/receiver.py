"""Talk to a legacy U-WAVE-R: latest readings, receiver settings and transmitter discovery.

Host-neutral and synchronous: run it on one worker thread, never a GUI thread.
The byte transport (virtual COM or the direct USB driver) is supplied by the
caller; see serial_transport for the virtual COM route.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import time
from typing import Callable, Iterable, Protocol, TypeVar

from .protocol import (
    ALL_CHANNELS, DataRequest, Destination, InfoRequest, MeasurementPacket, Packet, PacketError, PacketFramer,
    ReceiverInfo, Search, StatusCode, StatusPacket, TransmitterInfo, TransmitterState, is_device_id, parse_packet,
)

logger = logging.getLogger(__name__)
_STALE_OUTPUT_LIMIT = 64 * 1024
T = TypeVar("T")


class _EndOfSearch:
    pass


_END_OF_SEARCH = _EndOfSearch()


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...

    def read(self, timeout: float) -> bytes:
        """Return bytes received within timeout seconds, or b"" if none. A zero timeout must not block."""
        ...


class ReceiverError(RuntimeError):
    """The request failed; nothing from it may be accepted as a reading."""


class ResponseTimeout(ReceiverError):
    pass


class MalformedResponse(ReceiverError):
    pass


class StatusReported(ReceiverError):
    def __init__(self, packet: StatusPacket):
        channel = ALL_CHANNELS if packet.channel is None else f"{packet.channel:02d}"
        super().__init__(
            f"Group {packet.group:02d} channel {channel}: {packet.description} (status {packet.code:02d})."
        )
        self.packet = packet


class TransmitterChanged(ReceiverError):
    """The receiver reported a state change for the requested transmitter mid-request."""

    def __init__(self, info: TransmitterInfo):
        super().__init__(
            f"Channel {info.channel:02d}: transmitter {info.device_id} changed state "
            f"({info.state.name.replace('_', ' ').lower()}) during the request."
        )
        self.info = info


@dataclass(frozen=True)
class LatestReading:
    """The receiver's stored reading for one channel at the time of the request.

    received_at is when the PC received the response. The legacy protocol does not
    report when the instrument measured, so the physical sample may be older.
    """

    packet: MeasurementPacket
    received_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReceiverClient:
    """Requests to one receiver group.

    Packets that are not the reply to a request go to on_unsolicited: DATA presses
    the receiver forwards from Button driven transmitters, state changes, other
    channels' packets and late replies. Without it they are logged and dropped.
    """

    def __init__(
        self,
        transport: Transport,
        group: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utc_now,
        on_unsolicited: Callable[[Packet, datetime], None] | None = None,
    ):
        self.group = group
        self._transport = transport
        self._clock = clock
        self._now = now
        self._on_unsolicited = on_unsolicited
        self._framer = PacketFramer()
        self._unread: deque[tuple[bytes, datetime]] = deque()

    def request_latest(
        self, channel: int, timeout: float, *, clear_after_output: bool = False,
    ) -> LatestReading:
        """Return the requested channel's DT reply; raise ReceiverError for anything else.

        Well-formed packets for other channels are ignored. Any status or
        transmitter-state packet for this channel, including notifications such as
        low battery, fails the request. A specific channel is required because
        all-channel requests silently omit disconnected or empty transmitters.
        """
        if channel is None:
            raise ValueError("request_latest needs a specific channel, not all channels")
        request = DataRequest(self.group, channel, clear_after_output)

        def accept(packet: Packet, received_at: datetime) -> LatestReading | None:
            if isinstance(packet, ReceiverInfo) or packet.group != self.group or packet.channel != channel:
                return None
            if isinstance(packet, StatusPacket):
                raise StatusReported(packet)
            if isinstance(packet, TransmitterInfo):
                raise TransmitterChanged(packet)
            return LatestReading(packet, received_at)

        return self._exchange(request.encode(), timeout, f"Group {self.group:02d} channel {channel:02d}", accept)

    def receiver_info(self, timeout: float) -> ReceiverInfo:
        """Return the receiver's settings; ST 50 here usually means the group ID is wrong."""
        request = InfoRequest(Destination.RECEIVER, 0, self.group)

        def accept(packet: Packet, _received_at: datetime) -> ReceiverInfo | None:
            if isinstance(packet, ReceiverInfo):
                if packet.group != self.group:
                    reported = "FF" if packet.group is None else f"{packet.group:02d}"
                    raise MalformedResponse(f"Receiver answered group {self.group:02d} as group {reported}.")
                return packet
            self._raise_request_error(packet, request)
            return None

        return self._exchange(request.encode(), timeout, f"Receiver group {self.group:02d}", accept)

    def list_transmitters(self, timeout: float) -> list[TransmitterInfo]:
        """Return every transmitter registered in this receiver, in channel order.

        Walks the channels with IR upward searches until the receiver reports the
        end of the search. Each request gets its own timeout. Assumes, pending
        hardware confirmation, that a search includes its starting channel. The
        receiver also sends TI unprompted when a transmitter changes state; one
        that arrives mid-scan for a higher channel is indistinguishable from the
        reply, so rescan if transmitters were changing.
        """
        found: list[TransmitterInfo] = []
        start = 0
        while start <= 99:
            result = self._search_transmitter(start, timeout)
            if isinstance(result, _EndOfSearch):
                break
            found.append(result)
            start = result.channel + 1
        return found

    def find_transmitter(self, device_id: str, timeout: float) -> TransmitterInfo:
        """Find a registered transmitter by identity within one total timeout."""
        if not is_device_id(device_id):
            raise ValueError(f"invalid device ID {device_id!r}")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not (
            math.isfinite(timeout) and timeout > 0
        ):
            raise ValueError("timeout must be a positive number of seconds")
        deadline = self._clock() + timeout
        start = 0
        while start <= 99:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise ResponseTimeout(f"Transmitter search for {device_id}: timed out after {timeout:g} seconds.")
            result = self._search_transmitter(start, remaining, f"Transmitter search for {device_id}")
            if isinstance(result, _EndOfSearch):
                break
            if result.device_id == device_id:
                return result
            start = result.channel + 1
        raise ReceiverError(f"Transmitter {device_id} is not registered in receiver group {self.group:02d}.")

    def _search_transmitter(
        self, start: int, timeout: float, label: str | None = None,
    ) -> TransmitterInfo | _EndOfSearch:
        request = InfoRequest(Destination.TRANSMITTER, start, self.group, Search.ASCENDING)

        def accept(packet: Packet, _received_at: datetime, start: int = start) -> TransmitterInfo | _EndOfSearch | None:
            if (
                isinstance(packet, TransmitterInfo) and packet.channel is not None
                and packet.channel >= start and packet.state != TransmitterState.NOT_REGISTERED
            ):
                return packet
            if (
                isinstance(packet, StatusPacket) and packet.code == StatusCode.END_OF_SEARCH
                and packet.group == self.group and packet.channel == start
            ):
                return _END_OF_SEARCH
            self._raise_request_error(packet, request)
            return None

        label = label or f"Transmitter search from channel {start:02d}"
        return self._exchange(request.encode(), timeout, label, accept)

    def listen(self, duration: float) -> None:
        """Receive for duration seconds without a request, passing every packet to on_unsolicited.

        listen(0) passes on whatever has already arrived. Malformed packets are
        logged and skipped: there is no request for them to fail.
        """
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not (
            math.isfinite(duration) and duration >= 0
        ):
            raise ValueError("duration must be a non-negative number of seconds")
        deadline = self._clock() + duration
        drained = 0
        while True:
            remaining = max(deadline - self._clock(), 0.0)
            data = self._transport.read(remaining)
            self._receive(data)
            while self._unread:
                self._pass_on_raw(*self._unread.popleft())
            if remaining <= 0:
                drained += len(data)
                if not data or drained > _STALE_OUTPUT_LIMIT:  # a continuously sending device must not hold it
                    return

    def _pass_on(self, packet: Packet, received_at: datetime) -> None:
        if self._on_unsolicited is None:
            logger.info("Ignored U-WAVE-R packet: %r", packet)
        else:
            self._on_unsolicited(packet, received_at)

    def _pass_on_raw(self, raw: bytes, received_at: datetime) -> None:
        try:
            packet = parse_packet(raw)
        except PacketError as error:
            logger.warning("Skipped malformed U-WAVE-R output %r: %s", raw, error)
        else:
            self._pass_on(packet, received_at)

    def _raise_request_error(self, packet: Packet, request: InfoRequest) -> None:
        if (
            isinstance(packet, StatusPacket) and packet.code == StatusCode.REQUEST_ERROR
            and packet.group == request.group and packet.channel == request.channel
        ):
            raise StatusReported(packet)

    def _exchange(
        self, request: bytes, timeout: float, label: str,
        accept: Callable[[Packet, datetime], T | None],
    ) -> T:
        """Send one request and return the first packet accept() takes as its reply.

        accept returns None to ignore a packet, or raises to fail the request.
        Malformed packets always fail it.
        """
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not (
            math.isfinite(timeout) and timeout > 0
        ):
            raise ValueError("timeout must be a positive number of seconds")
        self._discard_stale_output()
        deadline = self._clock() + timeout
        self._transport.write(request)
        while True:
            while self._unread:
                raw, received_at = self._unread.popleft()
                try:
                    packet = parse_packet(raw)
                except PacketError as error:
                    raise MalformedResponse(f"{label}: {error}.") from error
                result = accept(packet, received_at)
                if result is not None:
                    return result
                self._pass_on(packet, received_at)
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise ResponseTimeout(f"{label}: no reply within {timeout:g} seconds.")
            self._receive(self._transport.read(remaining))

    def _receive(self, data: bytes) -> None:
        received_at = self._now()
        self._unread.extend((raw, received_at) for raw in self._framer.feed(data))

    def _discard_stale_output(self) -> None:
        """Pass on late replies and unsolicited packets, and drop partial bytes, before a new request.

        None of them can answer the new request. The legacy protocol has no request ID.
        A late reply that arrives after this drain but before the new reply is
        indistinguishable from it; response latency and any settle policy must be
        established on hardware.
        """
        discarded = 0
        while data := self._transport.read(0):
            discarded += len(data)
            if discarded > _STALE_OUTPUT_LIMIT:
                raise ReceiverError("Receiver output did not go quiet; check for a continuously sending device.")
            self._receive(data)
        while self._unread:
            self._pass_on_raw(*self._unread.popleft())
        partial = self._framer.reset()
        if partial:
            logger.info("Discarded partial U-WAVE-R packet: %r", partial)


def find_receiver(
    transport: Transport, timeout: float, *, groups: Iterable[int] = range(100),
    clock: Callable[[], float] = time.monotonic,
) -> ReceiverInfo:
    """Find the receiver's group ID by asking each group until the receiver answers.

    The receiver rejects requests for any other group with ST 50. A timeout is
    not retried: it means nothing is answering on this transport.
    """
    for group in groups:
        try:
            return ReceiverClient(transport, group, clock=clock).receiver_info(timeout)
        except StatusReported as error:
            if error.packet.code != StatusCode.REQUEST_ERROR:
                raise
    raise ReceiverError("The receiver accepted no group ID; check its group ID in U-WAVEPAK Setup.")
