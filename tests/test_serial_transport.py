import time
from types import SimpleNamespace

import pytest

serial = pytest.importorskip("serial")
import serial.tools.list_ports  # noqa: E402

from uwave_accessory.serial_transport import PortInfo, SerialTransport, TransportError, list_ports  # noqa: E402


@pytest.fixture
def loop():
    transport = SerialTransport(serial.serial_for_url("loop://", timeout=0))
    yield transport
    transport.close()


def test_read_returns_waiting_bytes_and_times_out_empty(loop):
    assert loop.read(0) == b""
    loop.write(b"DR1031200\r")
    assert loop.read(0) == b"DR1031200\r"
    started = time.monotonic()
    assert loop.read(0.05) == b""
    assert time.monotonic() - started >= 0.03


def test_open_failure_tells_the_operator_to_free_the_port():
    with pytest.raises(TransportError, match="Close U-WAVEPAK"):
        SerialTransport.open("UWAVE-NO-SUCH-PORT")


def test_ports_are_listed_in_natural_order(monkeypatch):
    monkeypatch.setattr(serial.tools.list_ports, "comports", lambda: [
        SimpleNamespace(device="COM10", description="USB Serial"), SimpleNamespace(device="COM3", description=""),
    ])
    assert list_ports() == [PortInfo("COM3", "COM3"), PortInfo("COM10", "USB Serial")]
