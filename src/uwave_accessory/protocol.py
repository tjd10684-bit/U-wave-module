"""Legacy U-WAVE-R packet codec.

Implements the PC <-> U-WAVE-R packet formats in the U-WAVEPAK User's Manual
(99MAL216A), appendix 6.1. Pure value types and functions: no I/O, threads,
clocks, vendor libraries or host-application imports.

Packets are ASCII, numeric fields are zero-padded, and every packet ends with
CR (0x0D). Field widths in characters:

    DT measurement   code 2 | version 1 | group 2   | channel 2 | sign 1 | data 11 | unit 1 | CR = 21
    ST status        code 2 | version 1 | group 2   | channel 2 | device ID 10 | status 2   | CR = 20
    TI transmitter   code 2 | version 1 | state 1   | channel 2 | group 2 | device ID 10 | band 2 | mode 1 | CR = 22
    RI receiver      code 2 | version 1 | group 2   | device ID 10 | band 2 | lack level 1 | duplicate 1
                     | 15 x noise level 3 | dummy 3 | CR = 68
    DR data request  code 2 | version 1 | channel 2 | group 2   | clear 1 | search 1       | CR = 10
    IR info request  code 2 | version 1 | destination 1 | channel 2 | group 2 | search 1    | CR = 10

DR and IR put the channel before the group, unlike DT and ST; TI puts the
channel before the group too. DT carries neither a device ID nor a sample
time, so its group/channel is an address, not a transmitter identity. TI's
device ID is the transmitter's identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum
from typing import Literal

API_VERSION = "1"
CR = b"\r"
MAX_PACKET_LENGTH = 68  # RI, the longest documented packet
UNKNOWN_DEVICE_ID = "FFFFFFFFFF"
ALL_CHANNELS = "FF"

FACTORY_DEFAULT = "FF"
BAND_IDS = range(11, 26)

Unit = Literal["mm", "in"]
_UNIT_CODES: dict[str, Unit | None] = {"M": "mm", "I": "in", "0": None}
_DIGITS = frozenset("0123456789")
_MAX_DEVICE_ID = 1_999_999_999
_PACKET_LENGTHS = {"DT": 21, "ST": 20, "TI": 22, "RI": 68}


class PacketError(ValueError):
    """Bytes that are not a supported, well-formed packet. Never a reading."""


class Search(IntEnum):
    SPECIFIC = 0
    ASCENDING = 1
    DESCENDING = 2


class StatusCode(IntEnum):
    LOW_BATTERY = 0
    INSTRUMENT_NOT_RESPONDING = 1
    UNREGISTERED_TRANSMITTER = 2
    DATA_OMITTED = 3
    TRANSMITTER_DISCONNECTED = 4
    NO_DATA = 5
    REQUEST_ERROR = 50
    END_OF_SEARCH = 51
    DATA_CANCELLED = 99


class TransmitterState(IntEnum):
    NOT_REGISTERED = 0
    DISCONNECTED = 1  # registered, but not connected
    CONNECTED = 2
    EDITING = 3
    EDITING_SOURCE = 4
    EDITING_DESTINATION = 5


class MeasurementMode(IntEnum):
    BUTTON_DRIVEN = 0
    EVENT_DRIVEN = 1  # the only mode whose readings DR can request


class Destination(IntEnum):
    RECEIVER = 0
    TRANSMITTER = 1


_STATUS_DESCRIPTIONS = {
    StatusCode.LOW_BATTERY: "transmitter battery is low",
    StatusCode.INSTRUMENT_NOT_RESPONDING: "instrument is not responding to its transmitter",
    StatusCode.UNREGISTERED_TRANSMITTER: "an unregistered transmitter was detected",
    StatusCode.DATA_OMITTED: "measurement omissions exceeded the receiver's alert level",
    StatusCode.TRANSMITTER_DISCONNECTED: "transmitter is disconnected from the receiver",
    StatusCode.NO_DATA: "receiver holds no data for this transmitter",
    StatusCode.REQUEST_ERROR: "receiver rejected the request (format, range, group or unregistered channel)",
    StatusCode.END_OF_SEARCH: "search found no transmitter",
    StatusCode.DATA_CANCELLED: "transmitter sent a data cancel",
}


@dataclass(frozen=True)
class MeasurementPacket:
    """DT: a reading stored or forwarded by the receiver, exactly as transmitted."""

    group: int
    channel: int
    value: Decimal
    unit: Unit | None  # None: the transmitter reported "no unit"

    def __post_init__(self) -> None:
        _check_range(self.group, "group")
        _check_range(self.channel, "channel")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValueError("value must be a finite Decimal")
        if self.unit not in _UNIT_CODES.values():
            raise ValueError(f"unsupported unit {self.unit!r}")

    def encode(self) -> bytes:
        digits = format(abs(self.value), "f").zfill(11)
        if len(digits) > 11:
            raise ValueError(f"{self.value} does not fit the 11-character data field")
        sign = "-" if self.value < 0 else "+"
        unit = next(code for code, unit in _UNIT_CODES.items() if unit == self.unit)
        return f"DT{API_VERSION}{self.group:02d}{self.channel:02d}{sign}{digits}{unit}\r".encode("ascii")


@dataclass(frozen=True)
class StatusPacket:
    """ST: receiver/transmitter state or a failed request's answer. Never a reading."""

    group: int
    channel: int | None  # None: "FF", not a specific transmitter
    device_id: str | None  # None: "FFFFFFFFFF", unknown
    code: int

    def __post_init__(self) -> None:
        _check_range(self.group, "group")
        if self.channel is not None:
            _check_range(self.channel, "channel")
        if self.device_id is not None and not is_device_id(self.device_id):
            raise ValueError(f"invalid device ID {self.device_id!r}")
        _check_range(self.code, "status code")

    @property
    def description(self) -> str:
        try:
            return _STATUS_DESCRIPTIONS[StatusCode(self.code)]
        except ValueError:
            return f"unknown status code {self.code:02d}"

    def encode(self) -> bytes:
        channel = ALL_CHANNELS if self.channel is None else f"{self.channel:02d}"
        device_id = self.device_id or UNKNOWN_DEVICE_ID
        return f"ST{API_VERSION}{self.group:02d}{channel}{device_id}{self.code:02d}\r".encode("ascii")


@dataclass(frozen=True)
class DataRequest:
    """DR: ask the receiver for event-driven transmitters' stored readings."""

    group: int
    channel: int | None  # None: "FF", every transmitter that has data
    clear_after_output: bool = False
    search: Search = Search.SPECIFIC

    def __post_init__(self) -> None:
        _check_range(self.group, "group")
        if self.channel is not None:
            _check_range(self.channel, "channel")
        if not isinstance(self.clear_after_output, bool):
            raise ValueError("clear_after_output must be a bool")
        Search(self.search)

    def encode(self) -> bytes:
        channel = ALL_CHANNELS if self.channel is None else f"{self.channel:02d}"
        flags = f"{int(self.clear_after_output)}{int(self.search)}"
        return f"DR{API_VERSION}{channel}{self.group:02d}{flags}\r".encode("ascii")

    @classmethod
    def decode(cls, packet: bytes) -> DataRequest:
        text = _ascii(packet)
        if (
            len(text) != 10 or not text.startswith("DR" + API_VERSION) or not text.endswith("\r")
            or text[7] not in "01" or text[8] not in "012"
        ):
            raise PacketError(f"invalid DR packet {packet!r}")
        channel = None if text[3:5] == ALL_CHANNELS else _number(text[3:5], "channel")
        return cls(_number(text[5:7], "group"), channel, text[7] == "1", Search(int(text[8])))


@dataclass(frozen=True)
class TransmitterInfo:
    """TI: a transmitter registration held by the receiver. Never a reading.

    The receiver sends TI in reply to IR, and also unprompted whenever a
    transmitter's state changes.
    """

    state: TransmitterState
    channel: int | None  # None: "FF", factory default
    group: int | None  # None: "FF", factory default
    device_id: str
    band_id: int
    mode: MeasurementMode

    def __post_init__(self) -> None:
        TransmitterState(self.state)
        MeasurementMode(self.mode)
        for value, name in ((self.channel, "channel"), (self.group, "group")):
            if value is not None:
                _check_range(value, name)
        if not is_device_id(self.device_id):
            raise ValueError(f"invalid device ID {self.device_id!r}")
        _check_band(self.band_id)

    def encode(self) -> bytes:
        return (
            f"TI{API_VERSION}{int(self.state)}{_optional(self.channel)}{_optional(self.group)}"
            f"{self.device_id}{self.band_id:02d}{int(self.mode)}\r"
        ).encode("ascii")


@dataclass(frozen=True)
class ReceiverInfo:
    """RI: the receiver's own settings, in reply to IR for the receiver."""

    group: int | None  # None: "FF", factory default
    device_id: str
    band_id: int
    data_lack_level: int
    duplicate_detected: bool  # another receiver with the same group and band exists
    noise_levels: tuple[int, ...]  # band IDs 11-25 in order, 0-255 each

    def __post_init__(self) -> None:
        if self.group is not None:
            _check_range(self.group, "group")
        if not is_device_id(self.device_id):
            raise ValueError(f"invalid device ID {self.device_id!r}")
        _check_band(self.band_id)
        if isinstance(self.data_lack_level, bool) or self.data_lack_level not in range(10):
            raise ValueError(f"data lack check level must be 0-9, got {self.data_lack_level!r}")
        if not isinstance(self.duplicate_detected, bool):
            raise ValueError("duplicate_detected must be a bool")
        if len(self.noise_levels) != len(BAND_IDS) or not all(
            isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 255
            for level in self.noise_levels
        ):
            raise ValueError("noise_levels must be 15 integers from 0 to 255")

    def encode(self) -> bytes:
        noise = "".join(f"{level:03d}" for level in self.noise_levels)
        return (
            f"RI{API_VERSION}{_optional(self.group)}{self.device_id}{self.band_id:02d}"
            f"{self.data_lack_level}{int(self.duplicate_detected)}{noise}000\r"
        ).encode("ascii")


@dataclass(frozen=True)
class InfoRequest:
    """IR: ask for the receiver's settings or a transmitter registration.

    For transmitters, ASCENDING/DESCENDING asks for the nearest registered
    channel from the given one; the receiver answers ST 51 when none is left.
    """

    destination: Destination
    channel: int
    group: int
    search: Search = Search.SPECIFIC

    def __post_init__(self) -> None:
        Destination(self.destination)
        _check_range(self.channel, "channel")
        _check_range(self.group, "group")
        Search(self.search)
        if self.destination == Destination.RECEIVER and self.search != Search.SPECIFIC:
            raise ValueError("search applies to transmitter requests only")

    def encode(self) -> bytes:
        return (
            f"IR{API_VERSION}{int(self.destination)}{self.channel:02d}{self.group:02d}{int(self.search)}\r"
        ).encode("ascii")

    @classmethod
    def decode(cls, packet: bytes) -> InfoRequest:
        text = _ascii(packet)
        if (
            len(text) != 10 or not text.startswith("IR" + API_VERSION) or not text.endswith("\r")
            or text[3] not in "01" or text[8] not in "012"
        ):
            raise PacketError(f"invalid IR packet {packet!r}")
        try:
            return cls(
                Destination(int(text[3])), _number(text[4:6], "channel"), _number(text[6:8], "group"),
                Search(int(text[8])),
            )
        except PacketError:
            raise
        except ValueError as error:
            raise PacketError(f"invalid IR packet {packet!r}: {error}") from None


Packet = MeasurementPacket | StatusPacket | TransmitterInfo | ReceiverInfo


def parse_packet(packet: bytes) -> Packet:
    """Parse one CR-terminated packet received from the U-WAVE-R."""
    text = _ascii(packet)
    if not text.endswith("\r"):
        raise PacketError(f"unterminated packet {packet!r}")
    code = text[:2]
    expected = _PACKET_LENGTHS.get(code)
    if expected is None:
        raise PacketError(f"unsupported packet code {code!r} in {packet!r}")
    if len(text) != expected:
        raise PacketError(f"{code} packet must be {expected} bytes, got {len(text)}: {packet!r}")
    if text[2] != API_VERSION:
        raise PacketError(f"unsupported U-WAVE API version {text[2]!r} in {packet!r}")
    try:
        return _PARSERS[code](text, packet)
    except PacketError:
        raise
    except ValueError as error:
        raise PacketError(f"invalid {code} packet {packet!r}: {error}") from None


def _parse_measurement(text: str, packet: bytes) -> MeasurementPacket:
    group, channel = _number(text[3:5], "group"), _number(text[5:7], "channel")
    sign, digits, unit = text[7], text[8:19], text[19]
    if sign not in "+-":
        raise PacketError(f"invalid sign {sign!r} in {packet!r}")
    if not set(digits) <= _DIGITS | {"."} or digits.count(".") > 1:
        raise PacketError(f"invalid measurement data {digits!r} in {packet!r}")
    if unit not in _UNIT_CODES:
        raise PacketError(f"unknown unit code {unit!r} in {packet!r}")
    return MeasurementPacket(group, channel, Decimal(sign + digits), _UNIT_CODES[unit])


def _parse_status(text: str, packet: bytes) -> StatusPacket:
    channel = None if text[5:7] == ALL_CHANNELS else _number(text[5:7], "channel")
    device_id = text[7:17]
    if device_id == UNKNOWN_DEVICE_ID:
        device_id = None
    elif not is_device_id(device_id):
        raise PacketError(f"invalid device ID {device_id!r} in {packet!r}")
    return StatusPacket(_number(text[3:5], "group"), channel, device_id, _number(text[17:19], "status code"))


def _parse_transmitter_info(text: str, packet: bytes) -> TransmitterInfo:
    if text[3] not in "012345" or text[20] not in "01":
        raise PacketError(f"invalid TI state or mode in {packet!r}")
    return TransmitterInfo(
        TransmitterState(int(text[3])), _optional_number(text[4:6], "channel"),
        _optional_number(text[6:8], "group"), _device_id(text[8:18], packet),
        _number(text[18:20], "band ID"), MeasurementMode(int(text[20])),
    )


def _parse_receiver_info(text: str, packet: bytes) -> ReceiverInfo:
    if text[18] not in "01":
        raise PacketError(f"invalid RI duplicate flag in {packet!r}")
    noise = tuple(_number(text[index:index + 3], "noise level") for index in range(19, 64, 3))
    _number(text[64:67], "dummy")
    return ReceiverInfo(
        _optional_number(text[3:5], "group"), _device_id(text[5:15], packet), _number(text[15:17], "band ID"),
        _number(text[17], "data lack check level"), text[18] == "1", noise,
    )


_PARSERS = {
    "DT": _parse_measurement, "ST": _parse_status, "TI": _parse_transmitter_info, "RI": _parse_receiver_info,
}


class PacketFramer:
    """Reassemble CR-terminated packets from arbitrarily split or joined reads."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        """Return completed packets in order.

        A run with no CR where one must already have appeared is returned as-is, so
        parsing rejects it and framing resynchronizes at the next CR.
        """
        self._buffer += data
        packets = []
        while True:
            end = self._buffer.find(CR, 0, MAX_PACKET_LENGTH)
            if end != -1:
                size = end + 1
            elif len(self._buffer) >= MAX_PACKET_LENGTH:
                size = MAX_PACKET_LENGTH
            else:
                return packets
            packets.append(bytes(self._buffer[:size]))
            del self._buffer[:size]

    def reset(self) -> bytes:
        """Discard and return any partial packet."""
        partial = bytes(self._buffer)
        self._buffer.clear()
        return partial


def _ascii(packet: bytes) -> str:
    try:
        return packet.decode("ascii")
    except UnicodeDecodeError:
        raise PacketError(f"non-ASCII packet {packet!r}") from None


def _number(field: str, name: str) -> int:
    if not field or not set(field) <= _DIGITS:
        raise PacketError(f"invalid {name} {field!r}")
    return int(field)


def _optional_number(field: str, name: str) -> int | None:
    return None if field == FACTORY_DEFAULT else _number(field, name)


def _optional(value: int | None) -> str:
    return FACTORY_DEFAULT if value is None else f"{value:02d}"


def _device_id(field: str, packet: bytes) -> str:
    if not is_device_id(field):
        raise PacketError(f"invalid device ID {field!r} in {packet!r}")
    return field


def is_device_id(field: str) -> bool:
    return isinstance(field, str) and len(field) == 10 and set(field) <= _DIGITS and int(field) <= _MAX_DEVICE_ID


def _check_band(value: int) -> None:
    if isinstance(value, bool) or value not in BAND_IDS:
        raise ValueError(f"band ID must be from 11 to 25, got {value!r}")


def _check_range(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 99:
        raise ValueError(f"{name} must be an integer from 0 to 99, got {value!r}")
