"""Open ERP helper module for Mitutoyo U-WAVE-R receivers."""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk

from open_erp_module import CaptureRequest, Context, Equipment, Module, ModuleError, Reading
from uwave_accessory.links import ConfigError, ConfigStore, Link, check_link
from uwave_accessory.receiver import ReceiverClient, ReceiverError
from uwave_accessory.serial_transport import PortInfo, SerialTransport, TransportError
from uwave_accessory.setup_window import (
    DEMO_PORT, PORT_LOCK, DemoInstruments, SetupWindow, available_ports, demo_receiver,
)

logger = logging.getLogger("uwave-module")
_ERROR = 1001


class UWaveModule(Module):
    module_id = "mitutoyo-u-wave"
    name = "Mitutoyo U-WAVE"
    version = "0.1.1"
    acquisition_mode = "latest"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: ConfigStore | None = None
        self._links: dict[str, Link] = {}
        self._port: str | None = None
        self._simulator = demo_receiver()

    def initialize(self, context: Context) -> None:
        self._store = ConfigStore(context.data_dir / "links.json")
        try:
            config = self._store.load()
        except ConfigError as error:
            raise ModuleError(f"Could not load U-WAVE settings: {error}", _ERROR) from error
        with self._lock:
            self._links = dict(config.links)
            self._port = config.port
        if self._links and self._port:
            self.report_status("ready", f"{len(self._links)} transmitter link(s) loaded.")
        else:
            self.report_status("warning", "Open Setup to choose a receiver and link its transmitters to assets.")

    def linked_assets(self) -> list[str]:
        with self._lock:
            return list(self._links)

    def capture(self, request: CaptureRequest) -> Reading:
        with self._lock:
            link = self._links.get(request.asset_id)
            port = self._port
        if link is None:
            raise ModuleError("This asset is not linked to a U-WAVE transmitter. Open Setup to link it.", _ERROR)
        if not port:
            raise ModuleError("Choose the U-WAVE receiver port in Open Setup before capturing.", _ERROR)
        if link.group is None:
            raise ModuleError("The saved transmitter link has no receiver group. Rescan and save it in Open Setup.", _ERROR)
        if request.cancelled.is_set():
            raise ModuleError("The U-WAVE capture was cancelled.", _ERROR)

        deadline = time.monotonic() + request.timeout_seconds
        if not PORT_LOCK.acquire(timeout=self._remaining(deadline)):
            raise ModuleError("The U-WAVE receiver is busy with setup. Finish there and capture again.", _ERROR)
        transport = None
        try:
            if request.cancelled.is_set():
                raise ModuleError("The U-WAVE capture was cancelled.", _ERROR)
            transport = self._open_transport(port)
            client = ReceiverClient(transport, link.group)
            transmitter = client.find_transmitter(link.device_id, self._remaining(deadline))
            checked = check_link(link, [transmitter])
            if not checked.usable:
                raise ModuleError(f"U-WAVE link for {link.asset_label or request.asset_id}: {checked.message}", _ERROR)
            if transmitter.channel is None:
                raise ModuleError(f"U-WAVE transmitter {link.device_id} has no assigned channel.", _ERROR)
            if request.cancelled.is_set():
                raise ModuleError("The U-WAVE capture was cancelled.", _ERROR)
            reading = client.request_latest(transmitter.channel, self._remaining(deadline))
        except ReceiverError as error:
            raise ModuleError(f"U-WAVE capture failed for {link.asset_label or request.asset_id}: {error}", _ERROR) from error
        finally:
            try:
                if transport is not None:
                    close = getattr(transport, "close", None)
                    if close is not None:
                        close()
            finally:
                PORT_LOCK.release()

        if reading.packet.unit not in ("mm", "in"):
            raise ModuleError(
                f"U-WAVE transmitter {link.device_id} did not report units. Set mm or in in the instrument.",
                _ERROR,
            )
        return Reading(
            value=float(reading.packet.value),
            units=reading.packet.unit,
            source_id=f"uwave-r:transmitter:{link.device_id}",
            received_at=reading.received_at,
        )

    def open_setup(self, equipment: list[Equipment]) -> None:
        if self._store is None:
            raise ModuleError("Open ERP must initialize the U-WAVE module before setup.", _ERROR)
        root = tk.Tk()
        root.withdraw()
        demo: DemoInstruments | None = None
        window: SetupWindow | None = None

        def port_selected(port: str | None) -> None:
            nonlocal demo
            if window is None:
                return
            if port == DEMO_PORT:
                if demo is None or not demo.winfo_exists():
                    demo = DemoInstruments(window, self._simulator)
                else:
                    demo.lift()
            elif demo is not None and demo.winfo_exists():
                demo.destroy()
                demo = None

        try:
            window = SetupWindow(
                root,
                equipment,
                store=self._store,
                open_transport=self._open_transport,
                list_ports=self._list_ports,
                default_port=DEMO_PORT,
                title="Mitutoyo U-WAVE Setup",
                on_port_selected=port_selected,
            )
            port_selected(window.settings.port)
            window.run()
            if window.saved:
                try:
                    config = self._store.load()
                except ConfigError as error:
                    raise ModuleError(f"Could not reload U-WAVE settings: {error}", _ERROR) from error
                with self._lock:
                    self._links = dict(config.links)
                    self._port = config.port
                if self._links:
                    self.report_status("ready", f"{len(self._links)} transmitter link(s) configured.")
                else:
                    self.report_status("warning", "No U-WAVE transmitters are linked to assets.")
        finally:
            root.destroy()

    def _open_transport(self, port: str):
        return self._simulator if port == DEMO_PORT else SerialTransport.open(port)

    @staticmethod
    def _list_ports() -> list[PortInfo]:
        try:
            ports = available_ports()
        except TransportError as error:
            logger.warning("Physical U-WAVE ports are unavailable: %s", error)
            ports = []
        return [*ports, PortInfo(DEMO_PORT, "Simulator (demo)")]

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModuleError("U-WAVE capture timed out before a reading was received.", _ERROR)
        return remaining


if __name__ == "__main__":
    from open_erp_module import run

    raise SystemExit(run(UWaveModule()))
