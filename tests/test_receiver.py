from datetime import datetime, timezone
from decimal import Decimal

import pytest

from uwave_accessory.protocol import (
    DataRequest, MeasurementMode, MeasurementPacket, StatusCode, StatusPacket, TransmitterInfo, TransmitterState,
)
from uwave_accessory.receiver import (
    MalformedResponse, ReceiverClient, ResponseTimeout, StatusReported, TransmitterChanged, find_receiver,
)
from uwave_accessory.simulation import ManualClock, SimulatedReceiver

RECEIVED_AT = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def receiver():
    receiver = SimulatedReceiver(group=7, clock=ManualClock())
    receiver.register(3, "0000012345", "12.340")
    return receiver


def client_for(receiver):
    return ReceiverClient(receiver, 7, clock=receiver.clock, now=lambda: RECEIVED_AT)


@pytest.mark.parametrize("chunk_size", [None, 1, 4])
def test_reading_is_reassembled_from_any_read_boundaries(receiver, chunk_size):
    receiver.chunk_size = chunk_size
    reading = client_for(receiver).request_latest(3, timeout=5)
    assert reading.packet == MeasurementPacket(7, 3, Decimal("12.340"), "mm")
    assert reading.received_at == RECEIVED_AT
    assert receiver.requests == [DataRequest(7, 3)]


@pytest.mark.parametrize(("problem", "code"), [
    ("disconnected", StatusCode.TRANSMITTER_DISCONNECTED),
    ("no data", StatusCode.NO_DATA),
    ("unregistered", StatusCode.REQUEST_ERROR),
])
def test_status_replies_fail_the_request_instead_of_becoming_readings(receiver, problem, code):
    if problem == "disconnected":
        receiver.transmitters[3].connected = False
    elif problem == "no data":
        receiver.transmitters[3].value = None
    else:
        del receiver.transmitters[3]
    with pytest.raises(StatusReported) as raised:
        client_for(receiver).request_latest(3, timeout=5)
    assert raised.value.packet.code == code


def test_packets_for_other_channels_are_ignored_while_waiting(receiver):
    receiver.interleave(
        MeasurementPacket(7, 4, Decimal("99"), "mm").encode()
        + StatusPacket(7, 4, "0000000001", StatusCode.LOW_BATTERY).encode()
        + StatusPacket(7, None, None, StatusCode.UNREGISTERED_TRANSMITTER).encode()
    )
    assert client_for(receiver).request_latest(3, timeout=5).packet.value == Decimal("12.340")


def test_any_status_for_the_requested_channel_blocks_even_if_a_reading_follows(receiver):
    receiver.interleave(StatusPacket(7, 3, "0000012345", StatusCode.LOW_BATTERY).encode())
    with pytest.raises(StatusReported, match="battery"):
        client_for(receiver).request_latest(3, timeout=5)


def test_stale_output_and_partial_packets_are_discarded_before_requesting(receiver):
    receiver.inject(MeasurementPacket(7, 3, Decimal("1.000"), "mm").encode() + b"DT1070")
    assert client_for(receiver).request_latest(3, timeout=5).packet.value == Decimal("12.340")


def test_timeout_then_late_reply_cannot_satisfy_the_next_request(receiver):
    client = client_for(receiver)
    receiver.responding = False
    with pytest.raises(ResponseTimeout, match="5 seconds"):
        client.request_latest(3, timeout=5)
    assert receiver.clock() == 5
    receiver.responding = True
    receiver.release_held()
    receiver.transmitters[3].value = Decimal("12.500")
    assert client.request_latest(3, timeout=5).packet.value == Decimal("12.500")


@pytest.mark.parametrize("chunk_size", [None, 4])
def test_unsolicited_packets_reach_the_listener_and_malformed_ones_are_skipped(receiver, chunk_size):
    receiver.chunk_size = chunk_size
    receiver.register(5, "0000055555", "7.50", mode=MeasurementMode.BUTTON_DRIVEN)
    heard = []
    client = ReceiverClient(
        receiver, 7, clock=receiver.clock, now=lambda: RECEIVED_AT,
        on_unsolicited=lambda packet, received_at: heard.append((packet, received_at)),
    )
    receiver.inject(MeasurementPacket(7, 3, Decimal("1.000"), "mm").encode())
    receiver.interleave(MeasurementPacket(7, 4, Decimal("99"), "mm").encode())
    assert client.request_latest(3, timeout=5).packet.value == Decimal("12.340")
    receiver.press_data(5)
    receiver.inject(b"DT1070X+0000012.340M\r")
    client.listen(0)
    assert receiver.clock() == 0
    assert heard == [
        (MeasurementPacket(7, 3, Decimal("1.000"), "mm"), RECEIVED_AT),
        (MeasurementPacket(7, 4, Decimal("99"), "mm"), RECEIVED_AT),
        (MeasurementPacket(7, 5, Decimal("7.50"), "mm"), RECEIVED_AT),
    ]
    client.listen(2)
    assert receiver.clock() == 2 and len(heard) == 3


@pytest.mark.parametrize("raw", [b"DT1070X+0000012.340M\r", b"XX1203070000012345151\r"])
def test_malformed_or_unsupported_reply_fails_explicitly(receiver, raw):
    receiver.interleave(raw)
    with pytest.raises(MalformedResponse):
        client_for(receiver).request_latest(3, timeout=5)


def test_transmitter_state_change_for_the_requested_channel_fails_the_request(receiver):
    receiver.interleave(TransmitterInfo(
        TransmitterState.DISCONNECTED, 3, 7, "0000012345", 11, MeasurementMode.EVENT_DRIVEN,
    ).encode())
    with pytest.raises(TransmitterChanged, match="disconnected"):
        client_for(receiver).request_latest(3, timeout=5)


def test_all_channel_requests_are_refused(receiver):
    with pytest.raises(ValueError, match="specific channel"):
        client_for(receiver).request_latest(None, timeout=5)
    assert receiver.requests == []


@pytest.mark.parametrize("chunk_size", [None, 1])
def test_scan_lists_every_registered_transmitter_in_channel_order(receiver, chunk_size):
    receiver.chunk_size = chunk_size
    receiver.register(0, "0000000100")
    receiver.register(42, "0000000142", connected=False, mode=MeasurementMode.BUTTON_DRIVEN)
    receiver.register(99, "0000000199")
    receiver.interleave(StatusPacket(7, 3, "0000012345", StatusCode.LOW_BATTERY).encode())
    found = client_for(receiver).list_transmitters(timeout=1)
    assert found == [receiver.transmitter_info(channel) for channel in (0, 3, 42, 99)]
    assert found[2].state == TransmitterState.DISCONNECTED
    assert found[2].mode == MeasurementMode.BUTTON_DRIVEN
    assert [request.channel for request in receiver.requests] == [0, 1, 4, 43]


def test_scan_of_an_empty_receiver_ends_on_end_of_search():
    receiver = SimulatedReceiver(group=7, clock=ManualClock())
    assert client_for(receiver).list_transmitters(timeout=1) == []


def test_receiver_info_and_wrong_group(receiver):
    assert client_for(receiver).receiver_info(timeout=1).group == 7
    with pytest.raises(StatusReported) as raised:
        ReceiverClient(receiver, 8, clock=receiver.clock).list_transmitters(timeout=1)
    assert raised.value.packet.code == StatusCode.REQUEST_ERROR


def test_find_receiver_tries_groups_until_one_is_accepted(receiver):
    assert find_receiver(receiver, 1, clock=receiver.clock).group == 7
    assert [request.group for request in receiver.requests] == list(range(8))


def test_find_receiver_stops_when_nothing_answers(receiver):
    receiver.responding = False
    with pytest.raises(ResponseTimeout):
        find_receiver(receiver, 1, clock=receiver.clock)
    assert len(receiver.requests) == 1
