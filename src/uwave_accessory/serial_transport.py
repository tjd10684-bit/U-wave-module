"""Virtual COM transport for a U-WAVE-R on the vendor's VCP driver.

Needs the optional pyserial dependency: pip install "uwave-accessory[serial]".
Port settings follow the manual: 57600 baud, 8 data bits, no parity, 1 stop
bit, RTS/CTS flow control. Only one program can hold the port, so U-WAVEPAK
must be closed while this transport is open. The direct USB driver route is
not implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .receiver import ReceiverError

BAUD_RATE = 57600
WRITE_TIMEOUT = 2.0


class TransportError(ReceiverError):
    """The port could not be opened, read or written."""


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str


def list_ports() -> list[PortInfo]:
    """Return the PC's serial ports in natural order (COM3 before COM10)."""
    from serial.tools import list_ports as tools

    ports = [PortInfo(port.device, port.description or port.device) for port in tools.comports()]
    return sorted(ports, key=lambda port: [
        int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", port.device)
    ])


class SerialTransport:
    """A receiver Transport over an open pyserial port."""

    def __init__(self, port):
        self._port = port

    @classmethod
    def open(cls, device: str) -> SerialTransport:
        try:
            import serial
        except ImportError:
            raise TransportError(
                'COM ports need pyserial: pip install "uwave-accessory[serial]".'
            ) from None
        try:
            port = serial.Serial(
                device, BAUD_RATE, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, rtscts=True, timeout=0, write_timeout=WRITE_TIMEOUT,
            )
        except (OSError, ValueError) as error:
            raise TransportError(
                f"Could not open {device}: {error}. Close U-WAVEPAK or any other program using the port."
            ) from error
        return cls(port)

    @property
    def device(self) -> str:
        return self._port.name

    def write(self, data: bytes) -> None:
        try:
            self._port.write(data)
            self._port.flush()
        except OSError as error:
            raise TransportError(f"Could not write to {self.device}: {error}.") from error

    def read(self, timeout: float) -> bytes:
        try:
            waiting = self._port.in_waiting
            if waiting:
                return self._port.read(waiting)
            if timeout <= 0:
                return b""
            self._port.timeout = timeout
            first = self._port.read(1)
            if not first:
                return b""
            waiting = self._port.in_waiting
            return first + (self._port.read(waiting) if waiting else b"")
        except OSError as error:
            raise TransportError(f"Could not read from {self.device}: {error}.") from error

    def close(self) -> None:
        self._port.close()

    def __enter__(self) -> SerialTransport:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
