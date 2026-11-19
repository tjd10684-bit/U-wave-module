"""Open ERP helper module for Mitutoyo U-WAVE receiver ports."""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk

from open_erp_module import CaptureRequest, Context, Equipment, Module, ModuleError, Reading
from uwave_accessory.links import AccessoryConfig, ConfigError, ConfigStore, check_link
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
    version = "0.2.0"
    acquisition_mode = "latest"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: ConfigStore | None = None
        self._config = AccessoryConfig()
        self._simulator = demo_receiver()

    def initialize(self, context: Context) -> None:
        self._store = ConfigStore(context.data_dir / "links.json")
        try:
            config = self._store.load()
        except ConfigError as error:
            raise ModuleError(f"Could not load U-WAVE settings: {error}", _ERROR) from error
        with self._lock:
            self._config = config
        if config.links and config.receivers:
            self.report_status("ready", f"{len(config.links)} transmitter link(s) loaded.")
        else:
            self.report_status("warning", "Open Setup to choose a receiver and link its transmitters to assets.")

    def linked_assets(self) -> list[str]:
        with self._lock:
            return list(self._config.links)

    def capture(self, request: CaptureRequest) -> Reading:
        with self._lock:
            config = self._config
            link = config.links.get(request.asset_id)
        if link is None:
            raise ModuleError("This asset is not linked to a U-WAVE transmitter. Open Setup to link it.", _ERROR)
        if not config.receivers:
            raise ModuleError("Choose the U-WAVE receiver port in Open Setup before capturing.", _ERROR)
        port = config.port_for_link(link)
        if port is None:
            raise ModuleError("Rescan and save in Open Setup to assign this transmitter to a receiver.", _ERROR)
        if port not in config.receivers:
            raise ModuleError(f"The linked receiver {port} is not enabled. Enable it in Open Setup.", _ERROR)
        group = config.receivers[port]
        if group is None:
            group = link.group
        if group is None:
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
            client = ReceiverClient(transport, group)
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
            raise ModuleError(
                f"U-WAVE capture failed on {port} for {link.asset_label or request.asset_id}: {error}", _ERROR,
            ) from error
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
            if DEMO_PORT in window.settings.receivers:
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
            port_selected(window.selected_port)
            window.run()
            if window.saved:
                try:
                    config = self._store.load()
                except ConfigError as error:
                    raise ModuleError(f"Could not reload U-WAVE settings: {error}", _ERROR) from error
                with self._lock:
                    self._config = config
                if config.links and config.receivers:
                    self.report_status("ready", f"{len(config.links)} transmitter link(s) configured.")
                else:
                    self.report_status("warning", "Enable a receiver and link its transmitters in Open Setup.")
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
