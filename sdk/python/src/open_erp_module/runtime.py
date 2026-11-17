"""The JSON-RPC stdio loop that connects a :class:`Module` to Open ERP.

Threads:

* a reader thread reads stdin and handles ``cancel`` notifications immediately;
* one worker thread runs ``initialize``, ``linked_assets``, ``capture`` and ``shutdown`` in order,
  so those methods never run at the same time as each other;
* the main thread runs ``open_setup``, so a module can use Tk (or another UI toolkit) there.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import queue
import sys
import threading
from typing import Any, BinaryIO

PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 1024 * 1024
MODULE_ERROR = 1000
NOT_INITIALIZED = -32002
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700, -32600, -32601, -32602, -32603,
)
UNITS = ("mm", "in")
ACQUISITION_MODES = ("latest", "fresh")

logger = logging.getLogger("open_erp_module")


class ModuleError(Exception):
    """Raise from a module method to fail the request; Open ERP shows ``message`` to the operator."""

    def __init__(self, message: str, code: int = MODULE_ERROR):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class Context:
    """What Open ERP tells the module at start-up."""

    module_id: str
    data_dir: Path
    host_name: str
    host_version: str


@dataclass(frozen=True)
class Equipment:
    asset_id: str
    tag: str
    name: str
    category: str


@dataclass(frozen=True)
class CaptureRequest:
    capture_id: str
    asset_id: str
    units: str
    input_name: str
    requested_at: datetime
    timeout_seconds: float
    cancelled: threading.Event = field(default_factory=threading.Event, compare=False, repr=False)
    """Set when Open ERP gives up on this capture; long waits should check it."""


@dataclass(frozen=True)
class Reading:
    """One reading. Open ERP's ids, mode and (if omitted) the receipt time are filled in for you."""

    value: float
    units: str
    source_id: str
    received_at: datetime | None = None
    sampled_at: datetime | None = None


class Module:
    """Base class for a measurement module. Override what your device supports."""

    module_id: str = ""
    name: str = ""
    version: str = ""
    acquisition_mode: str = "latest"

    _host: _Host | None = None

    def initialize(self, context: Context) -> None:
        """Load settings from ``context.data_dir``; answer within 15 seconds."""

    def linked_assets(self) -> Iterable[str]:
        """Open ERP asset ids this module can capture from right now."""
        return ()

    def capture(self, request: CaptureRequest) -> Reading:
        """Take one reading for ``request.asset_id``. Raise :class:`ModuleError` to fail it."""
        raise ModuleError(f"{self.name or 'This module'} cannot capture readings.")

    def cancel(self, capture_id: str) -> None:
        """Called on the reader thread when Open ERP gives up on a capture; return quickly."""

    def open_setup(self, equipment: list[Equipment]) -> None:
        """Show the setup window on the main thread and return when it closes."""
        raise ModuleError(f"{self.name or 'This module'} has no setup window.")

    def shutdown(self) -> None:
        """Close device connections. Called once, when Open ERP stops the module."""

    @property
    def has_setup(self) -> bool:
        return type(self).open_setup is not Module.open_setup

    def report_status(self, state: str, message: str = "") -> None:
        """Show a short status with the module in Open ERP: ``ready``, ``warning`` or ``error``."""
        if state not in ("ready", "warning", "error"):
            raise ValueError("state must be ready, warning or error")
        if self._host is not None:
            self._host.notify("status", {"state": state, "message": message})

    def assets_changed(self) -> None:
        """Tell Open ERP to ask :meth:`linked_assets` again (for links changed outside setup)."""
        if self._host is not None:
            self._host.notify("assets_changed")


_STOP = object()


def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO 8601 time")
    return datetime.fromisoformat(value)


def _aware(value: datetime, name: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.isoformat()


class _InvalidParams(ValueError):
    pass


class _Host:
    def __init__(self, module: Module, reader: BinaryIO, writer: BinaryIO):
        self.module = module
        self.reader, self.writer = reader, writer
        self.write_lock = threading.Lock()
        self.work: queue.SimpleQueue = queue.SimpleQueue()
        self.main: queue.SimpleQueue = queue.SimpleQueue()
        self.captures: dict[str, CaptureRequest] = {}
        self.captures_lock = threading.Lock()
        self.initialized = False
        self.shut_down = False
        self.connected = True

    # Sending ---------------------------------------------------------------------------------

    def send(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        with self.write_lock:
            if not self.connected:
                return
            try:
                self.writer.write(data + b"\n")
                self.writer.flush()
            except (OSError, ValueError):
                self.connected = False

    def notify(self, method: str, params: Any = None) -> None:
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)

    def reply(self, request_id: Any, result: Any) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def error(self, request_id: Any, code: int, message: str) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    # Reading ---------------------------------------------------------------------------------

    def read_loop(self) -> None:
        try:
            while True:
                raw = self.reader.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw.rstrip(b"\r\n")) > MAX_LINE_BYTES:
                    logger.error("Open ERP sent a line longer than %d bytes; stopping.", MAX_LINE_BYTES)
                    break
                if raw.strip():
                    self.dispatch(raw)
        except (OSError, ValueError) as error:
            logger.error("Reading from Open ERP failed: %s", error)
        self.work.put(_STOP)

    def dispatch(self, raw: bytes) -> None:
        try:
            message = json.loads(raw.decode("utf-8"))
        except ValueError:
            self.error(None, PARSE_ERROR, "The message is not valid JSON.")
            return
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(
            message.get("method", ""), str
        ):
            self.error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST,
                       "Expected a JSON-RPC 2.0 message.")
            return
        method = message.get("method")
        if method is None:
            return  # Open ERP sends no responses we wait for.
        params = message.get("params")
        if "id" not in message:
            if method == "cancel" and isinstance(params, dict):
                self.cancel(params.get("capture_id"))
            return
        request_id = message["id"]
        if method == "open_setup":
            self.main.put((request_id, method, params))
            return
        if method == "capture" and isinstance(params, dict):
            try:
                params = self.capture_request(params)
            except (KeyError, TypeError, ValueError) as error:
                self.error(request_id, INVALID_PARAMS, f"Invalid capture request: {error}")
                return
            with self.captures_lock:
                self.captures[params.capture_id] = params
        self.work.put((request_id, method, params))

    @staticmethod
    def capture_request(params: dict) -> CaptureRequest:
        texts = {name: params[name] for name in ("capture_id", "asset_id", "units", "input_name")}
        for name, value in texts.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be text")
        timeout = params.get("timeout_seconds", 5.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout_seconds must be a number")
        return CaptureRequest(
            **texts, requested_at=_time(params.get("requested_at"), "requested_at"), timeout_seconds=float(timeout),
        )

    def cancel(self, capture_id: Any) -> None:
        with self.captures_lock:
            request = self.captures.pop(capture_id, None) if isinstance(capture_id, str) else None
        if request is None:
            return
        request.cancelled.set()
        try:
            self.module.cancel(capture_id)
        except Exception:  # noqa: BLE001 - a module bug must not stop the reader.
            logger.exception("cancel(%s) failed", capture_id)

    # Handling --------------------------------------------------------------------------------

    def handle(self, request_id: Any, method: str, params: Any) -> None:
        try:
            if self.shut_down and method != "shutdown":
                raise ModuleError("The module is shutting down.")
            if method == "initialize":
                result = self.initialize(params)
            elif method == "shutdown":
                self.stop_module()
                result = {}
            elif not self.initialized:
                raise ModuleError("Open ERP must call initialize first.", NOT_INITIALIZED)
            elif method == "linked_assets":
                result = {"asset_ids": self.linked_assets()}
            elif method == "capture":
                if not isinstance(params, CaptureRequest):
                    raise _InvalidParams("capture needs an object of parameters")
                result = self.capture(params)
            elif method == "open_setup":
                result = self.open_setup(params)
            else:
                self.error(request_id, METHOD_NOT_FOUND, f"{self.module.name or 'This module'} does not handle {method}.")
                return
        except ModuleError as error:
            self.error(request_id, error.code, error.message)
        except _InvalidParams as error:
            self.error(request_id, INVALID_PARAMS, str(error))
        except Exception as error:  # noqa: BLE001 - reported to Open ERP, details to the log.
            logger.exception("%s failed", method)
            self.error(request_id, INTERNAL_ERROR, f"{self.module.name or 'The module'} failed: {error}")
        else:
            self.reply(request_id, result)
        finally:
            if isinstance(params, CaptureRequest):
                with self.captures_lock:
                    self.captures.pop(params.capture_id, None)

    def initialize(self, params: Any) -> dict:
        if not isinstance(params, dict):
            raise _InvalidParams("initialize needs an object of parameters")
        module = self.module
        host = params.get("host") if isinstance(params.get("host"), dict) else {}
        if params.get("protocol_version") != PROTOCOL_VERSION:
            logger.warning("Open ERP speaks protocol %r; this module speaks %d.",
                           params.get("protocol_version"), PROTOCOL_VERSION)
        if params.get("module_id") != module.module_id:
            logger.warning("Open ERP started this program as %r; it is %r.", params.get("module_id"), module.module_id)
        data_dir = params.get("data_dir")
        if not isinstance(data_dir, str) or not data_dir:
            raise _InvalidParams("data_dir must be text")
        if not self.initialized:
            module.initialize(Context(
                module_id=module.module_id, data_dir=Path(data_dir),
                host_name=str(host.get("name", "")), host_version=str(host.get("version", "")),
            ))
            self.initialized = True
        return {
            "protocol_version": PROTOCOL_VERSION,
            "module": {"id": module.module_id, "name": module.name, "version": module.version},
            "acquisition_mode": module.acquisition_mode,
            "capabilities": {"setup": module.has_setup},
        }

    def linked_assets(self) -> list[str]:
        assets = self.module.linked_assets()
        if isinstance(assets, str):
            raise TypeError("linked_assets must return asset ids, not one string")
        assets = list(dict.fromkeys(assets))
        if not all(isinstance(item, str) and item.strip() for item in assets):
            raise TypeError("linked_assets must return nonempty text asset ids")
        return assets

    def capture(self, request: CaptureRequest) -> dict:
        reading = self.module.capture(request)
        if request.cancelled.is_set():
            raise ModuleError("The capture was cancelled.")
        if not isinstance(reading, Reading):
            raise TypeError("capture must return a Reading")
        value = reading.value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("the reading value must be a finite number")
        if reading.units not in UNITS:
            raise ValueError(f"the reading units must be one of {', '.join(UNITS)}")
        if not isinstance(reading.source_id, str) or not reading.source_id.strip():
            raise ValueError("the reading needs a nonempty source_id")
        received_at = reading.received_at or datetime.now(timezone.utc)
        return {
            "capture_id": request.capture_id, "asset_id": request.asset_id, "value": float(value),
            "units": reading.units, "source_id": reading.source_id,
            "received_at": _aware(received_at, "received_at"),
            "acquisition_mode": self.module.acquisition_mode,
            "sampled_at": None if reading.sampled_at is None else _aware(reading.sampled_at, "sampled_at"),
        }

    def open_setup(self, params: Any) -> dict:
        items = params.get("equipment") if isinstance(params, dict) else None
        if not isinstance(items, list):
            raise _InvalidParams("open_setup needs an equipment list")
        equipment = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("asset_id"), str):
                raise _InvalidParams("each equipment item needs an asset_id")
            equipment.append(Equipment(
                item["asset_id"], str(item.get("tag", "")), str(item.get("name", "")), str(item.get("category", "")),
            ))
        self.module.open_setup(equipment)
        return {}

    def stop_module(self) -> None:
        if self.shut_down:
            return
        self.shut_down = True
        try:
            self.module.shutdown()
        except Exception:  # noqa: BLE001 - exiting anyway.
            logger.exception("shutdown failed")

    # Threads ---------------------------------------------------------------------------------

    def work_loop(self) -> None:
        while True:
            job = self.work.get()
            if job is _STOP:
                break
            self.handle(*job)
        self.stop_module()
        self.main.put(_STOP)

    def serve(self) -> int:
        self.module._host = self
        threading.Thread(target=self.read_loop, name="open-erp-reader", daemon=True).start()
        threading.Thread(target=self.work_loop, name="open-erp-worker", daemon=True).start()
        try:
            while True:
                job = self.main.get()
                if job is _STOP:
                    return 0
                self.handle(*job)
        finally:
            self.module._host = None


def serve(module: Module, reader: BinaryIO, writer: BinaryIO) -> int:
    """Serve Open ERP over the given binary streams until the input ends; returns the exit code."""
    if not module.module_id or not module.name or not module.version:
        raise ValueError("Set module_id, name and version on the module class.")
    if module.acquisition_mode not in ACQUISITION_MODES:
        raise ValueError("acquisition_mode must be 'latest' or 'fresh'.")
    return _Host(module, reader, writer).serve()


def run(module: Module) -> int:
    """Serve Open ERP over this process's stdin and stdout; returns the exit code."""
    stderr = sys.stderr
    if sys.stdin is None or sys.stdout is None:
        if stderr is not None:
            print("Open ERP modules must be built as console programs (stdin/stdout are missing).", file=stderr)
        return 2
    if sys.stdin.isatty():
        print(
            f"{module.name or 'This program'} is an Open ERP measurement module. Add its package in Open ERP: "
            "Settings > Measurement Devices > Add Module...", file=stderr or sys.stdout,
        )
        return 2
    reader, writer = sys.stdin.buffer, sys.stdout.buffer
    # Keep stray print() calls off the protocol stream; they go to the module log instead.
    sys.stdout = stderr if stderr is not None else open(os.devnull, "w")  # noqa: SIM115
    if stderr is not None and not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return serve(module, reader, writer)
