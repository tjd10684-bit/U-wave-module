from decimal import Decimal

import pytest

from uwave_accessory.protocol import (
    DataRequest, Destination, InfoRequest, MeasurementMode, MeasurementPacket, PacketError, PacketFramer,
    ReceiverInfo, Search, StatusPacket, TransmitterInfo, TransmitterState, parse_packet,
)

DT = b"DT10703+0000012.340M\r"
ST = b"ST10703000001234504\r"
TI = b"TI1203070000012345151\r"
RI = b"RI10700000543211531" + b"012" * 14 + b"255" + b"000\r"
NOISE = (12,) * 14 + (255,)


@pytest.mark.parametrize(("wire", "packet"), [
    (DT, MeasurementPacket(7, 3, Decimal("12.340"), "mm")),
    (b"DT10012-000000.1250I\r", MeasurementPacket(0, 12, Decimal("-0.1250"), "in")),
    (b"DT10012+000000000000\r", MeasurementPacket(0, 12, Decimal("0"), None)),
    (ST, StatusPacket(7, 3, "0000012345", 4)),
    (b"ST107FFFFFFFFFFFF42\r", StatusPacket(7, None, None, 42)),
    (TI, TransmitterInfo(
        TransmitterState.CONNECTED, 3, 7, "0000012345", 15, MeasurementMode.EVENT_DRIVEN,
    )),
    (b"TI10FFFF1999999999250\r", TransmitterInfo(
        TransmitterState.NOT_REGISTERED, None, None, "1999999999", 25, MeasurementMode.BUTTON_DRIVEN,
    )),
    (RI, ReceiverInfo(7, "0000054321", 15, 3, True, NOISE)),
])
def test_packets_parse_and_encode_exactly(wire, packet):
    assert parse_packet(wire) == packet
    assert packet.encode() == wire


def test_measurement_digits_and_status_meaning_are_preserved():
    assert str(parse_packet(DT).value) == "12.340"
    assert parse_packet(ST).description == "transmitter is disconnected from the receiver"
    assert parse_packet(b"ST107FFFFFFFFFFFF42\r").description == "unknown status code 42"
    with pytest.raises(ValueError, match="11-character"):
        MeasurementPacket(0, 0, Decimal("123456789012"), "mm").encode()


@pytest.mark.parametrize("wire", [
    DT[:-1],
    b"DT10703+000012.340M\r",
    b"DT20703+0000012.340M\r",
    b"DT10703*0000012.340M\r",
    b"DT10703+00000l2.340M\r",
    b"DT10703+000001.2.34M\r",
    b"DT10703+0000012.340X\r",
    b"DT1A703+0000012.340M\r",
    b"DT10703+0000012.340\xb5\r",
    b"ST10703200000000004\r",
    b"XX1203070000012345151\r",
    b"TI1603070000012345151\r",
    b"TI1203070000012345101\r",
    b"TI1203070000012345152\r",
    b"TI12030700000123451\r",
    b"TI12030A0000012345151\r",
    RI[:18] + b"2" + RI[19:],
    RI[:19] + b"256" + RI[22:],
    RI[:-1],
])
def test_malformed_or_unsupported_packets_are_rejected(wire):
    with pytest.raises(PacketError):
        parse_packet(wire)


def test_framer_reassembles_split_and_joined_reads_without_mixing_packets():
    framer = PacketFramer()
    stream = DT + ST
    packets = []
    for index in range(len(stream)):
        packets += framer.feed(stream[index:index + 1])
    assert packets == [DT, ST]
    assert framer.feed(DT + ST[:5]) == [DT]
    assert framer.reset() == ST[:5]


def test_framer_surfaces_unterminated_noise_then_resynchronizes():
    packets = PacketFramer().feed(b"x" * 70 + b"\r" + DT)
    assert packets[-1] == DT
    for noise in packets[:-1]:
        with pytest.raises(PacketError):
            parse_packet(noise)


@pytest.mark.parametrize(("request_", "wire"), [
    (DataRequest(group=12, channel=3), b"DR1031200\r"),
    (DataRequest(group=0, channel=None, clear_after_output=True, search=Search.DESCENDING), b"DR1FF0012\r"),
])
def test_data_request_puts_channel_before_group(request_, wire):
    assert request_.encode() == wire
    assert DataRequest.decode(wire) == request_


@pytest.mark.parametrize(("request_", "wire"), [
    (InfoRequest(Destination.TRANSMITTER, 5, 7, Search.ASCENDING), b"IR1105071\r"),
    (InfoRequest(Destination.RECEIVER, 0, 7), b"IR1000070\r"),
])
def test_info_request_puts_destination_then_channel_then_group(request_, wire):
    assert request_.encode() == wire
    assert InfoRequest.decode(wire) == request_


@pytest.mark.parametrize("wire", [b"IR1200070\r", b"IR1000071\r", b"IR1000073\r", b"DR1000070\r"])
def test_info_request_decode_rejects_invalid_requests(wire):
    with pytest.raises(PacketError):
        InfoRequest.decode(wire)


@pytest.mark.parametrize("arguments", [
    {"group": 100, "channel": 0},
    {"group": 0, "channel": -1},
    {"group": True, "channel": 0},
    {"group": 0, "channel": 0, "clear_after_output": 1},
    {"group": 0, "channel": 0, "search": 3},
])
def test_data_request_rejects_out_of_range_fields(arguments):
    with pytest.raises(ValueError):
        DataRequest(**arguments)
