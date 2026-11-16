"""Visual setup: link the ERP's assets to U-WAVE transmitters.

Transmitters registered in the U-WAVE-R are listed on the left and the assets
the host passes in are listed on the right. Drag one onto the other, or click
one and then the other, to link them. Select a link and press Delete (or
Unlink) to remove it. Links are saved per PC by links.ConfigStore.

To tell identical instruments apart, Read Values shows each transmitter's
latest value once per click and highlights the ones that changed since the last
click. Identify (for the selected asset) and Link All (for every unlinked asset
in turn) automate it: the operator changes the asked-for instrument's reading,
or presses its DATA button, and the one transmitter that responds is linked.
Values come from the receiver's memory, so reading them does not wake the
transmitters.

configure(parent, equipment) matches the host contract's configure callback.
Try it without hardware: python -m uwave_accessory.setup_window --demo
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import logging
import math
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk
from typing import Callable, Iterable, Protocol

from .links import AccessoryConfig, ConfigError, ConfigStore, LinkState, check_link
from .protocol import (
    MeasurementMode, MeasurementPacket, Packet, ReceiverInfo, StatusCode, TransmitterInfo, TransmitterState,
)
from .receiver import (
    LatestReading, ReceiverClient, ReceiverError, ResponseTimeout, StatusReported, TransmitterChanged, Transport,
    find_receiver,
)
from .serial_transport import PortInfo, SerialTransport, TransportError, list_ports

logger = logging.getLogger(__name__)

TITLE = "Measurement Devices"
REQUEST_TIMEOUT = 1.0
IDENTIFY_SECONDS = 30  # how long Identify waits for the operator before giving up on an asset
IDENTIFY_INTERVAL = 1.0  # seconds between value requests while identifying
DEMO_PORT = "Simulator"

CARD_HEIGHT, CARD_GAP, MARGIN, HEADER, MIN_CANVAS_WIDTH = 64, 12, 24, 44, 720
GREEN, AMBER, RED, GRAY, BLUE = "#2e7d32", "#e65100", "#c62828", "#757575", "#1565c0"
CANVAS_BG, CARD_FILL, GHOST_FILL, MOVED_FILL, CARD_OUTLINE, TEXT, MUTED, PROMPT_BG = (
    "#f4f6f8", "#ffffff", "#eceff1", "#fff3c4", "#b0bec5", "#212121", "#546e7a", "#e3f2fd",
)

# Windows opens a COM port exclusively, so scans, value reads and identification,
# including those of a window that is closing, take turns.
_PORT_LOCK = threading.Lock()
_NO_DATA = "no data"
_LISTEN_SLICE = 0.05  # seconds; how quickly identification notices a new target or a stop

_READING_PROBLEMS = {
    StatusCode.LOW_BATTERY: "Low battery",
    StatusCode.INSTRUMENT_NOT_RESPONDING: "Gauge not responding",
    StatusCode.TRANSMITTER_DISCONNECTED: "Not connected",
    StatusCode.NO_DATA: "No data yet",
    StatusCode.REQUEST_ERROR: "Request rejected",
}
DEFAULT_HINT = (
    "Drag a transmitter onto an asset, or click one and then the other, to link them. "
    "Not sure which instrument is which? Click Link All and change each reading when asked. "
    "Select a link and press Delete to remove it."
)

_STATE_STYLE = {
    LinkState.READY: ("Ready", GREEN),
    LinkState.MOVED: ("Ready (channel changed)", GREEN),
    LinkState.DISCONNECTED: ("Transmitter not connected", AMBER),
    LinkState.BUTTON_DRIVEN: ("Set Event driven in U-WAVEPAK", AMBER),
    LinkState.EDITING: ("Being edited in U-WAVEPAK", AMBER),
    LinkState.NOT_FOUND: ("Transmitter not found", RED),
    LinkState.NOT_SCANNED: ("Not checked: scan the receiver", GRAY),
}
_EDITING = (TransmitterState.EDITING, TransmitterState.EDITING_SOURCE, TransmitterState.EDITING_DESTINATION)


class EquipmentLike(Protocol):
    """The host contract's Equipment; used_by (feature labels) is optional."""

    asset_id: str
    tag: str
    name: str
    category: str


@dataclass(frozen=True)
class Asset:
    asset_id: str
    tag: str
    name: str
    category: str
    used_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    receiver: ReceiverInfo
    transmitters: list[TransmitterInfo]


def scan_receiver(
    open_transport: Callable[[str], Transport], port: str, group: int | None, timeout: float = REQUEST_TIMEOUT,
) -> ScanResult:
    """Open the port, find the receiver (detecting its group if None), list its transmitters, close."""
    transport = open_transport(port)
    try:
        if group is None:
            receiver = find_receiver(transport, timeout)
        else:
            receiver = ReceiverClient(transport, group).receiver_info(timeout)
        return ScanResult(receiver, ReceiverClient(transport, receiver.group).list_transmitters(timeout))
    finally:
        _close(transport)


def read_latest_values(
    open_transport: Callable[[str], Transport], port: str, group: int, channels: dict[str, int],
    timeout: float = REQUEST_TIMEOUT, cancel: threading.Event | None = None,
) -> dict[str, LatestReading | ReceiverError]:
    """Open the port, request each transmitter's latest stored value, close.

    channels maps transmitter Device ID to channel. A failed request is returned in
    place of its reading so one silent transmitter does not hide the others. Values
    stay in the receiver. Stops early, omitting the rest, once cancel is set.
    """
    transport = open_transport(port)
    try:
        client = ReceiverClient(transport, group)
        results: dict[str, LatestReading | ReceiverError] = {}
        for device_id, channel in channels.items():
            if cancel is not None and cancel.is_set():
                break
            try:
                results[device_id] = client.request_latest(channel, timeout)
            except ReceiverError as error:
                results[device_id] = error
        return results
    finally:
        _close(transport)


def _close(transport: Transport) -> None:
    close = getattr(transport, "close", None)
    if close is not None:
        close()


def watch_for_responses(
    open_transport: Callable[[str], Transport], port: str, group: int, event_channels: dict[str, int],
    button_channels: dict[int, str], results: queue.Queue, stop: threading.Event, wake: threading.Event,
    interval: float, timeout: float = REQUEST_TIMEOUT,
) -> None:
    """Hold the port and report, every interval, values and DATA presses until stop is set.

    event_channels maps Device ID to channel for Event driven transmitters, whose
    latest values are requested each round; button_channels maps channel to Device ID
    for Button driven transmitters, whose DATA presses the receiver forwards. Each
    round puts (asked, values by Device ID, [(Device ID, reading) per press]) on
    results, where asked is the time.perf_counter() at which its values were requested.
    Setting wake ends the current round early. A failure that ends the watch is put
    on results instead.
    """
    presses: list[tuple[str, LatestReading]] = []

    def collect(packet: Packet, received_at: datetime) -> None:
        # Only Button driven channels are never requested, so a late request reply cannot pass for a press.
        if isinstance(packet, MeasurementPacket) and packet.group == group and packet.channel in button_channels:
            presses.append((button_channels[packet.channel], LatestReading(packet, received_at)))

    try:
        with _PORT_LOCK:
            if stop.is_set():
                return
            transport = open_transport(port)
            try:
                client = ReceiverClient(transport, group, on_unsolicited=collect)
                wait = 0.0
                while not stop.is_set():
                    end = time.monotonic() + wait
                    while True:  # in slices, so that a new target or a stop is noticed at once
                        client.listen(min(max(end - time.monotonic(), 0.0), _LISTEN_SLICE))
                        if stop.is_set():
                            return
                        if wake.is_set() or time.monotonic() >= end:
                            break
                    wake.clear()
                    asked = time.perf_counter()
                    values: dict[str, LatestReading | ReceiverError] = {}
                    for device_id, channel in event_channels.items():
                        if stop.is_set():
                            return
                        try:
                            values[device_id] = client.request_latest(channel, timeout)
                        except TransportError:
                            raise
                        except ReceiverError as error:
                            values[device_id] = error
                    client.listen(0)  # a press that arrived with the last reply belongs to this round
                    results.put((asked, values, presses[:]))
                    presses.clear()
                    wait = interval
            finally:
                _close(transport)
    except ReceiverError as error:
        results.put(error)
    except Exception as error:  # a worker exception would otherwise leave identification waiting forever
        logger.exception("U-WAVE identification failed")
        results.put(error)


@dataclass(eq=False)
class _Identify:
    """An Identify or Link All run: which assets to identify and how far it has got."""

    targets: list[str]  # asset IDs, in order
    guided: bool  # Link All: move on to the next asset rather than stop
    results: queue.Queue
    stop: threading.Event
    wake: threading.Event  # set when a new target is asked for, to start a fresh round
    event_devices: frozenset[str]
    button_devices: frozenset[str]
    index: int = 0
    # Answers count only after values requested since the current target was asked for are in.
    # perf_counter: time.monotonic() ticks only every 15.6 ms on Windows before Python 3.13.
    prompted_at: float = field(default_factory=time.perf_counter)
    deadline: float | None = None  # time.monotonic(); None until those starting values are in
    target_link: object = None  # the current target's link when it was asked for
    linked: list[str] = field(default_factory=list)
    confirmed: list[str] = field(default_factory=list)
    by_hand: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def target(self) -> str:
        return self.targets[self.index]


def available_ports() -> list[PortInfo]:
    try:
        return list_ports()
    except ImportError:
        raise TransportError('COM ports need pyserial: pip install "uwave-accessory[serial]".') from None


def configure(parent: tk.Misc, equipment: Iterable[EquipmentLike]) -> None:
    """Host contract configure callback: open the setup window and return when it closes."""
    SetupWindow(parent, equipment).run()


class SetupWindow(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, equipment: Iterable[EquipmentLike], *,
        store: ConfigStore | None = None,
        open_transport: Callable[[str], Transport] = SerialTransport.open,
        list_ports: Callable[[], list[PortInfo]] = available_ports,
        default_port: str | None = None,
        title: str = TITLE,
        identify_seconds: float = IDENTIFY_SECONDS,
        identify_interval: float = IDENTIFY_INTERVAL,
    ):
        super().__init__(parent)
        self.title(title)
        self.store = store or ConfigStore()
        self.open_transport = open_transport
        self.list_ports = list_ports
        self.identify_seconds = identify_seconds
        self.identify_interval = identify_interval
        self.assets = _assets(equipment)
        self.saved = False
        self.dirty = False
        self.scanning = False
        self.transmitters: list[TransmitterInfo] | None = None  # None: not scanned yet
        self.receiver: ReceiverInfo | None = None
        self.readings: dict[str, LatestReading | ReceiverError] = {}  # latest value request by device ID
        self.pressed: dict[str, LatestReading] = {}  # latest DATA press by device ID (Button driven)
        self._known: dict[str, LatestReading | ReceiverError] = {}  # last value or "no data" by device ID
        self._moved: set[str] = set()  # device IDs that responded in the latest read
        self._results: queue.Queue = queue.Queue()
        self._poll_id: str | None = None
        self._startup_id: str | None = None
        self._reading = False
        self._reading_results: queue.Queue | None = None
        self._reading_poll_id: str | None = None
        self._reading_cancel: threading.Event | None = None
        self._identify: _Identify | None = None
        self._identify_poll_id: str | None = None
        self._selected: tuple[str, str] | None = None
        self._drag: dict | None = None
        self._hit: dict[int, tuple[str, str]] = {}
        self._card_rects: dict[tuple[str, str], tuple[int, str, int]] = {}
        self._ports: dict[tuple[str, str], tuple[float, float]] = {}
        self._port_labels: dict[str, str] = {}
        self._drawn_width = 0
        self._load_error: str | None = None
        try:
            self.settings = self.store.load()
        except ConfigError as error:
            self._load_error = str(error)
            self.settings = AccessoryConfig()
        if self.settings.port is None and default_port is not None:
            self.settings.port = default_port

        base = tkfont.nametofont("TkDefaultFont")
        size = base.cget("size")
        self._font = base.copy()
        self._bold = base.copy()
        self._bold.configure(weight="bold")
        self._heading = base.copy()
        self._heading.configure(weight="bold", size=size + 1 if size > 0 else size - 1)
        self._value = base.copy()
        self._value.configure(weight="bold", size=size + 2 if size > 0 else size - 3)

        if parent.winfo_viewable():
            self.transient(parent.winfo_toplevel())
        self.geometry(f"{min(1000, self.winfo_screenwidth() - 80)}x{min(640, self.winfo_screenheight() - 120)}")
        self.minsize(760, 460)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_toolbar()
        self._build_canvas()
        self._build_identify_bar()
        self._build_footer()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _event: self.cancel())
        self.bind("<MouseWheel>", self._on_wheel)

        self.refresh_ports()
        self._set_hint(DEFAULT_HINT)
        self.redraw()
        if self._load_error:
            self._set_status(f"{self._load_error}. Saving will replace it.", error=True)
        elif self.settings.port in self._port_labels.values():
            self._startup_id = self.after_idle(self.scan)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(12, 10, 12, 6))
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, text="Receiver port:").pack(side="left")
        self.port_var = tk.StringVar(self)
        self.port_combo = ttk.Combobox(bar, textvariable=self.port_var, state="readonly", width=32)
        self.port_combo.pack(side="left", padx=(4, 2))
        self.port_combo.bind("<<ComboboxSelected>>", self._port_changed)
        ttk.Button(bar, text="Refresh", command=self.refresh_ports).pack(side="left", padx=(2, 12))
        ttk.Label(bar, text="Group:").pack(side="left")
        group = self.settings.group
        self.group_var = tk.StringVar(self, "Auto" if group is None else f"{group:02d}")
        self.group_combo = ttk.Combobox(
            bar, textvariable=self.group_var, state="readonly", width=6,
            values=["Auto", *(f"{value:02d}" for value in range(100))],
        )
        self.group_combo.pack(side="left", padx=(4, 12))
        self.group_combo.bind("<<ComboboxSelected>>", self._group_changed)
        self.scan_button = ttk.Button(bar, text="Scan Receiver", command=self.scan)
        self.scan_button.pack(side="left")
        self.read_button = ttk.Button(bar, text="Read Values", command=self.read_values, state="disabled")
        self.read_button.pack(side="left", padx=(6, 0))
        self.filter_var = tk.StringVar(self)
        self._filter_trace: str | None = self.filter_var.trace_add("write", lambda *_args: self.redraw())
        ttk.Entry(bar, textvariable=self.filter_var, width=22).pack(side="right")
        ttk.Label(bar, text="Filter assets:").pack(side="right", padx=(12, 4))

    def _build_canvas(self) -> None:
        body = ttk.Frame(self, padding=(12, 0))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            body, background=CANVAS_BG, highlightthickness=1, highlightbackground=CARD_OUTLINE,
            yscrollincrement=20,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Delete>", lambda _event: self.unlink_selected())

    def _build_identify_bar(self) -> None:
        """The prompt shown while identifying; hidden otherwise."""
        bar = tk.Frame(self, background=PROMPT_BG, padx=12, pady=8, highlightthickness=1,
                       highlightbackground=BLUE)
        ttk.Button(bar, text="Stop", command=self.stop_identify).pack(side="right")
        self.skip_button = ttk.Button(bar, text="Skip", command=self.skip_identify)
        self.identify_var = tk.StringVar(self)
        self.identify_label = tk.Label(
            bar, textvariable=self.identify_var, background=PROMPT_BG, foreground=TEXT, font=self._bold,
            anchor="w", justify="left",
        )
        self.identify_label.pack(side="left", fill="x", expand=True)
        bar.bind("<Configure>", lambda event: self.identify_label.configure(wraplength=max(event.width - 220, 200)))
        bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        bar.grid_remove()
        self.identify_bar = bar

    def _build_footer(self) -> None:
        info = ttk.Frame(self, padding=(12, 6, 12, 0))
        info.grid(row=3, column=0, sticky="ew")
        self.live_var = tk.StringVar(self)
        self.live_label = ttk.Label(info, textvariable=self.live_var, wraplength=940, foreground=BLUE)
        self.live_label.pack(anchor="w", pady=(0, 2))
        self.hint_var = tk.StringVar(self)
        self.hint_label = ttk.Label(info, textvariable=self.hint_var, wraplength=940)
        self.hint_label.pack(anchor="w")
        self.status_var = tk.StringVar(self)
        self.status_label = ttk.Label(info, textvariable=self.status_var, wraplength=940, foreground=MUTED)
        self.status_label.pack(anchor="w", pady=(2, 0))
        buttons = ttk.Frame(self, padding=12)
        buttons.grid(row=4, column=0, sticky="ew")
        self.unlink_button = ttk.Button(buttons, text="Unlink", command=self.unlink_selected, state="disabled")
        self.unlink_button.pack(side="left")
        self.identify_button = ttk.Button(buttons, text="Identify", command=self.identify, state="disabled")
        self.identify_button.pack(side="left", padx=(8, 0))
        self.link_all_button = ttk.Button(buttons, text="Link All", command=self.link_all, state="disabled")
        self.link_all_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right", padx=8)

    # Receiver ---------------------------------------------------------------

    def refresh_ports(self) -> None:
        try:
            ports = self.list_ports()
        except ReceiverError as error:
            ports = []
            self._set_status(str(error), error=True)
        else:
            if not ports:
                self._set_status("No COM ports found. Connect the U-WAVE-R and check its VCP driver.", error=True)
        self._port_labels = {
            (port.device if port.description in ("", port.device) else f"{port.device}: {port.description}"):
            port.device for port in ports
        }
        if self.settings.port and self.settings.port not in self._port_labels.values():
            self._port_labels[f"{self.settings.port}: not present"] = self.settings.port
        self.port_combo.configure(values=list(self._port_labels))
        self.port_var.set(next(
            (label for label, device in self._port_labels.items() if device == self.settings.port), "",
        ))

    def _port_changed(self, _event=None) -> None:
        port = self._port_labels.get(self.port_var.get())
        if port and port != self.settings.port:
            self.settings.port = port
            self._settings_changed()

    def _group_changed(self, _event=None) -> None:
        value = self.group_var.get()
        group = None if value == "Auto" else int(value)
        if group != self.settings.group:
            self.settings.group = group
            self._settings_changed()

    def _settings_changed(self) -> None:
        self.dirty = True
        self.transmitters = self.receiver = None
        self.redraw()
        self.scan()

    def scan(self) -> None:
        self._startup_id = None
        if self.scanning:
            return
        self._end_identify("")
        self._stop_readings()
        port, group = self.settings.port, self.settings.group
        if not port:
            self._set_status("Choose the receiver's COM port, then scan.", error=True)
            return
        self.scanning = True
        self.transmitters = self.receiver = None
        self._select(None)
        self.scan_button.configure(state="disabled", text="Scanning...")
        self._set_status(f"Scanning {port}... U-WAVEPAK must be closed.")
        threading.Thread(
            target=self._scan_worker, args=(self.open_transport, self._results, port, group),
            name="uwave-scan", daemon=True,
        ).start()
        self._poll_id = self.after(50, self._poll_scan)

    @staticmethod
    def _scan_worker(
        open_transport: Callable[[str], Transport], results: queue.Queue, port: str, group: int | None,
    ) -> None:
        try:
            with _PORT_LOCK:
                result = scan_receiver(open_transport, port, group)
        except ReceiverError as error:
            result = error
        except Exception as error:  # a worker exception would otherwise leave the window "Scanning" forever
            logger.exception("U-WAVE receiver scan failed")
            result = error
        results.put(((port, group), result))

    def _poll_scan(self) -> None:
        try:
            requested, result = self._results.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(50, self._poll_scan)
            return
        self._poll_id = None
        self.scanning = False
        self.scan_button.configure(state="normal", text="Scan Receiver")
        if requested != (self.settings.port, self.settings.group):
            self.scan()
            return
        if isinstance(result, Exception):
            self._set_status(f"Scan failed: {result}", error=True)
            self._update_buttons()
            return
        self.receiver, self.transmitters = result.receiver, result.transmitters
        before = dict(self.settings.links)
        self.settings.update_addresses(self.transmitters)
        self.dirty |= self.settings.links != before
        self.redraw()
        self._set_status(self._summary())
        self.read_values()

    # Values and identification ---------------------------------------------

    def read_values(self) -> None:
        """Request each Event driven transmitter's latest value once and show which changed since the last read.

        The receiver answers from its memory, so this does not wake the transmitters.
        """
        if not self._can_use_receiver():
            return
        channels = _event_channels(self.transmitters)
        if not channels:
            self._set_live(
                "No connected transmitter is Event driven, so the receiver keeps no values to read. "
                "Select an asset and click Identify, then press its DATA button.",
            )
            return
        self._reading = True
        self._reading_cancel = cancel = threading.Event()
        self._reading_results = results = queue.Queue()
        threading.Thread(
            target=self._reading_worker,
            args=(self.open_transport, results, self.settings.port, self.receiver.group, channels, cancel),
            name="uwave-readings", daemon=True,
        ).start()
        self._reading_poll_id = self.after(50, self._poll_readings)
        self._update_buttons()

    @staticmethod
    def _reading_worker(
        open_transport: Callable[[str], Transport], results: queue.Queue, port: str, group: int,
        channels: dict[str, int], cancel: threading.Event,
    ) -> None:
        try:
            with _PORT_LOCK:
                result = {} if cancel.is_set() else read_latest_values(
                    open_transport, port, group, channels, cancel=cancel,
                )
        except ReceiverError as error:
            result = error
        except Exception as error:  # a worker exception would otherwise leave the window "Reading" forever
            logger.exception("U-WAVE value request failed")
            result = error
        results.put(result)

    def _poll_readings(self) -> None:
        if self._drag is not None:  # a redraw now would erase the drag line
            self._reading_poll_id = self.after(50, self._poll_readings)
            return
        try:
            result = self._reading_results.get_nowait()
        except queue.Empty:
            self._reading_poll_id = self.after(50, self._poll_readings)
            return
        self._reading_poll_id = None
        self._reading = False
        self._reading_cancel = self._reading_results = None
        if isinstance(result, Exception):
            self._moved = set()
            self._set_live(f"Reading values failed: {result}", error=True)
            self.redraw()
            return
        first = not self._known
        changed = self._take_values(result)
        self._moved = set(changed)
        if changed:
            self._set_live("Changed since the last read: " + self._changes_text(changed))
        elif first:
            self._set_live(
                f"Values read at {datetime.now():%H:%M:%S}. Change an instrument's reading, then click "
                "Read Values again to see which transmitter it is, or select an asset and click Identify.",
            )
        else:
            self._set_live(f"No values changed since the last read ({datetime.now():%H:%M:%S}).")
        self.redraw()

    def _take_values(self, values: dict[str, LatestReading | ReceiverError]) -> dict[str, object]:
        """Store requested values; return the previous value of each transmitter whose value changed.

        A failed request keeps the transmitter's last known value to compare the next one
        with. "No data yet" followed by a value is a change.
        """
        self.readings.update(values)
        changed = {}
        for device_id, result in values.items():
            key = _value_key(result)
            if key is None:
                continue
            before = self._known.get(device_id)
            if isinstance(result, LatestReading) and before is not None and _value_key(before) != key:
                changed[device_id] = before
            self._known[device_id] = result
        return changed

    def _changes_text(self, changed: dict[str, object]) -> str:
        return "; ".join(
            f"{self._channel_label(info.device_id)} {_result_text(changed[info.device_id])} → "
            f"{_result_text(self.readings[info.device_id])}"
            for info in self.transmitters or () if info.device_id in changed
        )

    def _stop_readings(self) -> None:
        if self._reading_poll_id is not None:
            self.after_cancel(self._reading_poll_id)
            self._reading_poll_id = None
        if self._reading_cancel is not None:
            self._reading_cancel.set()
        # The worker's result goes to the abandoned queue; the next scan waits for it to release the port.
        self._reading = False
        self._reading_cancel = self._reading_results = None
        self.readings, self.pressed, self._known, self._moved = {}, {}, {}, set()
        self._set_live("")

    def identify(self) -> None:
        """Link the selected asset to the transmitter whose reading changes or whose DATA button is pressed."""
        asset_id = self._selected_asset()
        if asset_id is None:
            self._set_hint("Select an asset first, then click Identify.", warning=True)
            return
        self._start_identify([asset_id], guided=False)

    def link_all(self) -> None:
        """Identify each listed asset without a link in turn."""
        targets = [asset.asset_id for asset in self._visible_assets() if asset.asset_id not in self.settings.links]
        if not targets:
            self._set_live("Every listed asset is already linked.")
            return
        self._start_identify(targets, guided=True)

    def _start_identify(self, targets: list[str], *, guided: bool) -> None:
        if not self._can_use_receiver():
            return
        event_channels = _event_channels(self.transmitters)
        button_channels = {
            info.channel: info.device_id for info in self.transmitters
            if info.state == TransmitterState.CONNECTED and info.mode == MeasurementMode.BUTTON_DRIVEN
            and info.channel is not None
        }
        if not event_channels and not button_channels:
            self._set_live("Identify needs a connected transmitter. Turn the transmitters on, then scan.", error=True)
            return
        session = _Identify(
            targets, guided, queue.Queue(), threading.Event(), threading.Event(), frozenset(event_channels),
            frozenset(button_channels.values()), target_link=self.settings.links.get(targets[0]),
        )
        self._identify = session
        self._moved = set()
        threading.Thread(
            target=watch_for_responses,
            args=(
                self.open_transport, self.settings.port, self.receiver.group, event_channels, button_channels,
                session.results, session.stop, session.wake, self.identify_interval,
            ),
            name="uwave-identify", daemon=True,
        ).start()
        self._identify_poll_id = self.after(50, self._poll_identify)
        if guided:
            self.skip_button.pack(side="right", padx=(0, 8), before=self.identify_label)
        else:
            self.skip_button.pack_forget()
        self.identify_bar.grid()
        self._set_live("")
        self._prompt(session)
        self.redraw()

    def stop_identify(self) -> None:
        session = self._identify
        if session is not None:
            self._end_identify(self._identify_summary(session, "Stopped."))

    def skip_identify(self) -> None:
        session = self._identify
        if session is not None:
            session.skipped.append(self._asset_tag(session.target))
            self._next_target(session)

    def _poll_identify(self) -> None:
        session = self._identify
        self._identify_poll_id = None
        if session is None:
            return
        if self._drag is None:  # a link or redraw now would erase the drag line
            self._check_linked_by_hand(session)
            while session is self._identify:
                try:
                    message = session.results.get_nowait()
                except queue.Empty:
                    break
                if isinstance(message, Exception):
                    self._end_identify(f"Identify stopped: {message}", error=True)
                    return
                self._identify_round(session, *message)
            if session is self._identify:
                self._check_deadline(session)
        if session is self._identify:
            self._identify_poll_id = self.after(50, self._poll_identify)

    def _check_linked_by_hand(self, session: _Identify) -> None:
        current = self.settings.links.get(session.target)
        if current == session.target_link:
            return
        session.target_link = current
        if current is not None:
            tag = self._asset_tag(session.target)
            session.by_hand.append(tag)
            self._set_live(f"{tag} was linked by hand.")
            self._next_target(session)

    def _identify_round(
        self, session: _Identify, asked: float, values: dict[str, LatestReading | ReceiverError],
        presses: list[tuple[str, LatestReading]],
    ) -> None:
        changed = self._take_values(values)
        if session.deadline is None:
            # The operator has not been asked to act yet, so these presses are not answers.
            if asked > session.prompted_at:  # starting values for the current target
                session.deadline = time.monotonic() + self.identify_seconds
                self._prompt(session)
            self.redraw()
            return
        for device_id, reading in presses:
            self.pressed[device_id] = reading
        responders = set(changed) | {device_id for device_id, _ in presses}
        if not responders:
            if values or presses:
                self.redraw()
            return
        self._moved = responders
        tag = self._asset_tag(session.target)
        if len(responders) > 1:
            labels = [self._channel_label(info.device_id) for info in self.transmitters if info.device_id in responders]
            self._retry(
                session, f"{_join(labels)} responded at once. Leave the other instruments alone and change only "
                f"{tag}'s reading.",
            )
            return
        device_id = next(iter(responders))
        current = self.settings.link_for_device(device_id)
        channel = self._channel_label(device_id, linked=False)
        if current is not None and current.asset_id != session.target:
            self._retry(
                session, f"{channel} responded, but it is already linked to {current.asset_label}. "
                f"Change {tag}'s reading instead, or unlink {current.asset_label} first.",
            )
            return
        if current is not None:
            session.confirmed.append(f"{tag} on {channel}")
            self._select(("link", session.target))
            message = f"{tag} is on {channel}, as linked."
        else:
            self.link(device_id, session.target)
            session.linked.append(f"{tag} to {channel}")
            message = f"Linked {tag} to {channel}."
        self._set_live(message)
        self._next_target(session)

    def _retry(self, session: _Identify, message: str) -> None:
        session.deadline = time.monotonic() + self.identify_seconds
        self._set_live(message, warning=True)
        self._prompt(session)
        self.redraw()

    def _check_deadline(self, session: _Identify) -> None:
        if session.deadline is None:
            return
        remaining = session.deadline - time.monotonic()
        if remaining > 0:
            self._prompt(session, remaining)
            return
        tag = self._asset_tag(session.target)
        if not session.guided:
            self._end_identify(
                f"Nothing responded within {self.identify_seconds:g} s. Check that {tag}'s transmitter is on "
                "and connected, then try again.", warning=True,
            )
            return
        session.skipped.append(tag)
        self._set_live(
            f"Nothing responded for {tag} within {self.identify_seconds:g} s, so it was skipped.", warning=True,
        )
        self._next_target(session)

    def _next_target(self, session: _Identify) -> None:
        session.index += 1
        while session.index < len(session.targets) and session.target in self.settings.links:
            session.index += 1  # linked by hand meanwhile
        if session.index >= len(session.targets):
            self._end_identify(self._identify_summary(session, "Link All finished." if session.guided else ""))
            return
        session.prompted_at = time.perf_counter()
        session.deadline = None  # it starts once values requested from now on are in
        session.target_link = None
        session.wake.set()
        self._prompt(session)
        self.redraw()

    def _end_identify(self, message: str, *, error: bool = False, warning: bool = False) -> None:
        session, self._identify = self._identify, None
        if session is None:
            return
        session.stop.set()
        if self._identify_poll_id is not None:
            self.after_cancel(self._identify_poll_id)
            self._identify_poll_id = None
        self.identify_bar.grid_remove()
        self.identify_var.set("")
        self._set_live(message, error=error, warning=warning)
        self.redraw()

    def _prompt(self, session: _Identify, remaining: float | None = None) -> None:
        tag = self._asset_tag(session.target)
        count = f" ({session.index + 1} of {len(session.targets)})" if session.guided else ""
        if session.deadline is None:
            text = f"Identify {tag}{count}: reading the current values…"
        else:
            if remaining is None:
                remaining = session.deadline - time.monotonic()
            if session.event_devices and session.button_devices:
                action = "change its instrument's reading, or press its DATA button"
            elif session.event_devices:
                action = "change its instrument's reading"
            else:
                action = "press its transmitter's DATA button"
            text = (
                f"Identify {tag}{count}: {action}. Leave the other instruments alone. "
                f"{max(math.ceil(remaining), 0)} s left."
            )
        if self.identify_var.get() != text:
            self.identify_var.set(text)

    def _identify_summary(self, session: _Identify, prefix: str) -> str:
        parts = [prefix] if prefix else []
        if session.linked:
            parts.append(f"Linked {_join(session.linked)}.")
        if session.confirmed:
            parts.append(f"Confirmed {_join(session.confirmed)}.")
        if session.by_hand:
            parts.append(f"{_join(session.by_hand)} {'was' if len(session.by_hand) == 1 else 'were'} linked by hand.")
        if session.skipped:
            parts.append(f"Skipped {_join(session.skipped)}.")
        if not (session.linked or session.confirmed or session.by_hand):
            parts.append("Nothing was linked.")
        if session.linked or session.by_hand:
            parts.append(f"Click Save to keep {'it' if len(session.linked) + len(session.by_hand) == 1 else 'them'}.")
        return " ".join(parts)

    def _can_use_receiver(self) -> bool:
        return (
            not self.scanning and not self._reading and self._identify is None and bool(self.transmitters)
            and self.receiver is not None and self.settings.port is not None
        )

    def _update_buttons(self) -> None:
        ready = self._can_use_receiver()
        self.read_button.configure(
            state="normal" if ready else "disabled", text="Reading..." if self._reading else "Read Values",
        )
        self.identify_button.configure(state="normal" if ready and self._selected_asset() else "disabled")
        self.link_all_button.configure(state="normal" if ready and any(
            asset.asset_id not in self.settings.links for asset in self._visible_assets()
        ) else "disabled")
        self.unlink_button.configure(state="normal" if self._selected_link_asset() else "disabled")

    def _selected_asset(self) -> str | None:
        key = self._selected
        if key is None or key[0] not in ("asset", "link"):
            return None
        return key[1] if any(asset.asset_id == key[1] for asset in self.assets) else None

    def _asset_tag(self, asset_id: str) -> str:
        asset = next((item for item in self.assets if item.asset_id == asset_id), None)
        return (asset.tag or asset.asset_id) if asset else asset_id

    def _channel_label(self, device_id: str, *, linked: bool = True) -> str:
        info = next((item for item in self.transmitters or () if item.device_id == device_id), None)
        label = f"CH {info.channel:02d}" if info is not None and info.channel is not None else f"ID {device_id}"
        link = self.settings.link_for_device(device_id) if linked else None
        return f"{label} ({link.asset_label})" if link else label

    def _summary(self) -> str:
        parts = []
        if self.receiver is not None:
            detected = " (detected)" if self.settings.group is None else ""
            parts.append(f"Receiver {self.receiver.device_id}, group {self.receiver.group:02d}{detected}")
            if self.receiver.duplicate_detected:
                parts.append("another receiver nearby uses the same group and band")
        if self.transmitters is not None:
            parts.append(f"{len(self.transmitters)} transmitter{'s' * (len(self.transmitters) != 1)}")
        linked = sum(asset.asset_id in self.settings.links for asset in self.assets)
        parts.append(f"{linked} of {len(self.assets)} assets linked")
        return " · ".join(parts)

    # Linking ----------------------------------------------------------------

    def link(self, device_id: str, asset_id: str) -> bool:
        info = next((item for item in self.transmitters or () if item.device_id == device_id), None)
        asset = next((item for item in self.assets if item.asset_id == asset_id), None)
        if info is None or asset is None:
            self._select(None)
            self._set_hint("Scan the receiver, then link a transmitter it lists.", warning=True)
            return False
        current = self.settings.link_for_device(device_id)
        if current is not None and current.asset_id == asset_id:
            self._select(("link", asset_id))
            return True
        if current is not None and all(item.asset_id != current.asset_id for item in self.assets) and not (
            messagebox.askyesno(
                TITLE, f"Channel {info.channel:02d} is linked to {current.asset_label}, which is not in this list."
                f"\n\nMove the link to {asset.tag}?", parent=self, default="no",
            )
        ):
            return False
        replaced = self.settings.link(asset_id, asset.tag, info)
        self.dirty = True
        check = check_link(self.settings.links[asset_id], self.transmitters)
        message = f"Linked {asset.tag} to channel {info.channel:02d} (transmitter {info.device_id})."
        if replaced:
            message += " Replaced: " + ", ".join(
                f"{link.asset_label} on transmitter {link.device_id}" for link in replaced
            ) + "."
        if not check.usable:
            message += " " + check.message
        self._selected = ("link", asset_id)
        self.redraw()
        self._set_hint(message, warning=not check.usable)
        self._set_status(self._summary())
        return True

    def unlink_selected(self) -> None:
        key = self._selected
        asset_id = self._selected_link_asset()
        if asset_id is None:
            return
        link = self.settings.unlink(asset_id)
        self.dirty = True
        self._selected = None if key and key[0] == "link" else key
        self.redraw()
        self._set_hint(f"Unlinked {link.asset_label} from transmitter {link.device_id}.")
        self._set_status(self._summary())

    def _selected_link_asset(self) -> str | None:
        key = self._selected
        if key is None:
            return None
        if key[0] == "tx":
            link = self.settings.link_for_device(key[1])
            return link.asset_id if link else None
        return key[1] if key[1] in self.settings.links else None

    def _select(self, key: tuple[str, str] | None) -> None:
        self._selected = key
        self.redraw()
        if key is None:
            self._set_hint(DEFAULT_HINT)
            return
        kind, ident = key
        if kind == "tx":
            info = next((item for item in self.transmitters or () if item.device_id == ident), None)
            if info is None:
                self._set_hint(f"Transmitter {ident} was not found in the latest scan.", warning=True)
            else:
                self._set_hint(f"Channel {info.channel:02d} selected: click an asset to link it.")
            return
        asset = next((item for item in self.assets if item.asset_id == ident), None)
        link = self.settings.links.get(ident)
        label = asset.tag if asset else ident
        if link is None:
            self._set_hint(
                f"{label} selected: click a transmitter to link it, or click Identify to find it by changing its "
                "reading." if kind == "asset" else DEFAULT_HINT,
            )
            return
        check = check_link(link, self.transmitters)
        prefix = f"{label} selected: click a transmitter to relink it. " if kind == "asset" else f"{label}: "
        self._set_hint(prefix + check.message + " Press Delete or Unlink to remove the link.", warning=not check.usable)

    # Save and close ---------------------------------------------------------

    def save(self) -> bool:
        if self._load_error and not messagebox.askyesno(
            TITLE, f"{self._load_error}\n\nReplace it with these settings?", parent=self, default="no",
        ):
            return False
        try:
            self.store.save(self.settings)
        except ConfigError as error:
            messagebox.showerror(TITLE, str(error), parent=self)
            return False
        self.saved = True
        self.dirty = False
        self.destroy()
        return True

    def cancel(self) -> None:
        if self.dirty:
            answer = messagebox.askyesnocancel(TITLE, "Save the device link changes?", parent=self)
            if answer is None:
                return
            if answer:
                self.save()
                return
        self.destroy()

    def destroy(self) -> None:
        for after_id in (self._poll_id, self._startup_id, self._reading_poll_id, self._identify_poll_id):
            if after_id is not None:
                self.after_cancel(after_id)
        self._poll_id = self._startup_id = self._reading_poll_id = self._identify_poll_id = None
        if self._reading_cancel is not None:
            self._reading_cancel.set()
        if self._identify is not None:
            self._identify.stop.set()
            self._identify = None
        # Tcl owns the trace callback and the font copies; left behind, they keep this window alive in the host.
        if self._filter_trace is not None:
            self.filter_var.trace_remove("write", self._filter_trace)
            self._filter_trace = None
        for font in (self._font, self._bold, self._heading, self._value):
            if font.delete_font:
                font.delete_font = False
                self.tk.call("font", "delete", font.name)
        super().destroy()

    def run(self) -> bool:
        self.wait_visibility()
        self.grab_set()
        self.canvas.focus_set()
        self.wait_window()
        return self.saved

    # Drawing ----------------------------------------------------------------

    def redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self._hit.clear()
        self._card_rects.clear()
        self._ports.clear()
        width = max(canvas.winfo_width(), MIN_CANVAS_WIDTH)
        card_width = min(330, int((width - 2 * MARGIN) * 0.38))
        left, right = MARGIN, width - MARGIN - card_width
        visible = self._visible_assets()
        canvas.create_text(left, 14, anchor="nw", text="U-WAVE transmitters", font=self._heading, fill=TEXT)
        canvas.create_text(
            right, 14, anchor="nw", text=f"Assets from the ERP ({len(visible)})", font=self._heading, fill=TEXT,
        )

        y_left = HEADER
        rows = self._transmitter_rows(visible)
        if not rows:
            empty = (
                "Choose the receiver's port and scan to list its transmitters." if self.transmitters is None
                else "No transmitters are registered in this receiver. Register them in U-WAVEPAK Setup."
            )
            canvas.create_text(left, y_left, anchor="nw", width=card_width, text=empty, fill=MUTED, font=self._font)
        for key, info, link in rows:
            self._draw_card(
                key, left, y_left, card_width, *self._transmitter_text(info, link, visible),
                value=self._value_text(info), highlight=info is not None and info.device_id in self._moved,
            )
            y_left += CARD_HEIGHT + CARD_GAP

        y_right = HEADER
        if not visible:
            empty = (
                "No assets match the filter." if self.assets
                else "The ERP passed no assets. Assign equipment to the part first."
            )
            canvas.create_text(right, y_right, anchor="nw", width=card_width, text=empty, fill=MUTED, font=self._font)
        target = self._identify.target if self._identify is not None and self._identify.deadline is not None else None
        for asset in visible:
            link = self.settings.links.get(asset.asset_id)
            self._draw_card(
                ("asset", asset.asset_id), right, y_right, card_width, *self._asset_text(asset),
                highlight=link is not None and link.device_id in self._moved, outlined=asset.asset_id == target,
            )
            y_right += CARD_HEIGHT + CARD_GAP

        for asset in visible:
            link = self.settings.links.get(asset.asset_id)
            start = link and self._ports.get(("tx", link.device_id))
            if not start:
                continue
            (x1, y1), (x2, y2) = start, self._ports[("asset", asset.asset_id)]
            check = check_link(link, self.transmitters)
            selected = self._selected == ("link", asset.asset_id)
            middle = (x1 + x2) / 2
            options = {"dash": (6, 4)} if check.state in (LinkState.NOT_FOUND, LinkState.NOT_SCANNED) else {}
            line = canvas.create_line(
                x1, y1, middle, y1, middle, y2, x2, y2, smooth=True, splinesteps=24,
                width=6 if selected else 3, fill=_STATE_STYLE[check.state][1], capstyle="round", **options,
            )
            canvas.tag_lower(line)
            self._hit[line] = ("link", asset.asset_id)

        canvas.configure(scrollregion=(0, 0, width, max(y_left, y_right) + MARGIN))
        self._update_buttons()

    def _visible_assets(self) -> list[Asset]:
        text = self.filter_var.get().strip().lower()
        if not text:
            return list(self.assets)
        return [
            asset for asset in self.assets
            if text in " ".join((asset.tag, asset.name, asset.category, *asset.used_by)).lower()
        ]

    def _transmitter_rows(self, visible: list[Asset]):
        found = {info.device_id for info in self.transmitters or ()}
        rows = [(("tx", info.device_id), info, None) for info in self.transmitters or ()]
        for asset in visible:
            link = self.settings.links.get(asset.asset_id)
            if link is not None and link.device_id not in found:
                rows.append((("tx", link.device_id), None, link))
        return rows

    def _transmitter_text(self, info: TransmitterInfo | None, ghost_link, visible: list[Asset]):
        if info is None:
            channel = "--" if ghost_link.channel is None else f"{ghost_link.channel:02d}"
            status = (
                ("Not scanned yet", GRAY) if self.transmitters is None else ("Not found in this receiver", RED)
            )
            return f"ID {ghost_link.device_id}", f"Linked to {ghost_link.asset_label} · last on CH {channel}", *status, True
        link = self.settings.link_for_device(info.device_id)
        if link is None:
            linked = "Not linked"
        elif any(asset.asset_id == link.asset_id for asset in visible):
            linked = f"Linked to {link.asset_label}"
        else:
            linked = f"Linked to {link.asset_label} (not in this list)"
        if info.state == TransmitterState.CONNECTED and info.mode == MeasurementMode.EVENT_DRIVEN:
            status = ("Connected · Event driven", GREEN)
        elif info.state == TransmitterState.CONNECTED:
            status = ("Connected · Button driven: set Event driven", AMBER)
        elif info.state == TransmitterState.DISCONNECTED:
            status = ("Registered · not connected", GRAY)
        elif info.state in _EDITING:
            status = ("Being edited in U-WAVEPAK", AMBER)
        else:
            status = ("Not registered", RED)
        return f"CH {info.channel:02d}    ID {info.device_id}", linked, *status, False

    def _value_text(self, info: TransmitterInfo | None) -> tuple[str, str] | None:
        """The value to show and its colour, or None where there is none to show."""
        if info is None or info.state != TransmitterState.CONNECTED:
            return None
        moved = info.device_id in self._moved
        if info.mode == MeasurementMode.BUTTON_DRIVEN:  # the value of the latest DATA press, if one was seen
            pressed = self.pressed.get(info.device_id)
            return (_format_value(pressed.packet), BLUE if moved else TEXT) if pressed else None
        result = self.readings.get(info.device_id)
        if result is None:
            return None
        if isinstance(result, LatestReading):
            return _format_value(result.packet), BLUE if moved else TEXT
        return _reading_problem(result), AMBER

    def _asset_text(self, asset: Asset):
        used_by = f"Used by {', '.join(asset.used_by)}" if asset.used_by else ""
        subtitle = " · ".join(part for part in (asset.name, asset.category, used_by) if part)
        link = self.settings.links.get(asset.asset_id)
        if link is None:
            return asset.tag or asset.asset_id, subtitle, "Not linked", GRAY, False
        check = check_link(link, self.transmitters)
        label, color = _STATE_STYLE[check.state]
        channel = check.transmitter.channel if check.transmitter else link.channel
        prefix = "" if channel is None else f"CH {channel:02d} · "
        return asset.tag or asset.asset_id, subtitle, prefix + label, color, False

    def _draw_card(
        self, key, x, y, width, title, subtitle, status, color, ghost, *,
        value: tuple[str, str] | None = None, highlight: bool = False, outlined: bool = False,
    ) -> None:
        canvas = self.canvas
        selected = self._selected == key
        outline, line_width = (BLUE, 3) if selected or outlined else (CARD_OUTLINE, 1)
        rect = canvas.create_rectangle(
            x, y, x + width, y + CARD_HEIGHT, fill=MOVED_FILL if highlight else GHOST_FILL if ghost else CARD_FILL,
            outline=outline, width=line_width, **({"dash": (4, 3)} if ghost else {}),
        )
        text_width = title_width = width - 30
        items = [rect]
        if value is not None:
            value_text, value_color = value
            value_width = min(self._value.measure(value_text), text_width // 2)
            items.append(canvas.create_text(
                x + width - 16, y + 6, anchor="ne", text=_fit(value_text, self._value, value_width),
                font=self._value, fill=value_color,
            ))
            title_width -= value_width + 12
        items += [
            canvas.create_text(x + 12, y + 8, anchor="nw", text=_fit(title, self._bold, title_width),
                               font=self._bold, fill=TEXT),
            canvas.create_text(x + 12, y + 26, anchor="nw", text=_fit(subtitle, self._font, text_width),
                               font=self._font, fill=MUTED),
            canvas.create_oval(x + 12, y + 48, x + 20, y + 56, fill=color, outline=""),
            canvas.create_text(x + 26, y + 44, anchor="nw", text=_fit(status, self._font, text_width - 14),
                               font=self._font, fill=color),
        ]
        port_x, port_y = (x + width if key[0] == "tx" else x), y + CARD_HEIGHT / 2
        items.append(canvas.create_oval(
            port_x - 6, port_y - 6, port_x + 6, port_y + 6, fill=CARD_FILL, outline=BLUE if selected else MUTED,
            width=2,
        ))
        for item in items:
            self._hit[item] = key
        self._card_rects[key] = (rect, outline, line_width)
        self._ports[key] = (port_x, port_y)

    # Mouse ------------------------------------------------------------------

    def _item_at(self, x: float, y: float, kinds=("tx", "asset", "link")) -> tuple[str, str] | None:
        for item in reversed(self.canvas.find_overlapping(x - 3, y - 3, x + 3, y + 3)):
            key = self._hit.get(item)
            if key is not None and key[0] in kinds:
                return key
        return None

    def _point(self, event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _on_press(self, event) -> None:
        self.canvas.focus_set()
        x, y = self._point(event)
        self._drag = {"key": self._item_at(x, y), "start": (x, y), "moved": False, "line": None, "target": None}

    def _on_motion(self, event) -> None:
        drag = self._drag
        if drag is None or drag["key"] is None or drag["key"][0] == "link":
            return
        x, y = self._point(event)
        if not drag["moved"]:
            start_x, start_y = drag["start"]
            if abs(x - start_x) + abs(y - start_y) < 6:
                return
            drag["moved"] = True
        port_x, port_y = self._ports.get(drag["key"], (None, None))
        if port_x is None:
            return
        if drag["line"] is None:
            drag["line"] = self.canvas.create_line(port_x, port_y, x, y, fill=BLUE, width=2, dash=(6, 4))
        else:
            self.canvas.coords(drag["line"], port_x, port_y, x, y)
        target = self._item_at(x, y, ("asset",) if drag["key"][0] == "tx" else ("tx",))
        if target != drag["target"]:
            self._highlight(drag["target"], False)
            self._highlight(target, True)
            drag["target"] = target

    def _on_release(self, event) -> None:
        drag, self._drag = self._drag, None
        if drag is None:
            return
        if drag["line"] is not None:
            self.canvas.delete(drag["line"])
        key = drag["key"]
        if drag["moved"]:
            self._highlight(drag["target"], False)
            target = self._item_at(*self._point(event), ("asset",) if key[0] == "tx" else ("tx",))
            if target is not None:
                self._link_keys(key, target)
            return
        selected = self._selected
        if key and selected and {key[0], selected[0]} == {"tx", "asset"}:
            self._link_keys(selected, key)
        else:
            self._select(None if key == selected else key)

    def _highlight(self, key, on: bool) -> None:
        if key in self._card_rects:
            rect, outline, line_width = self._card_rects[key]
            self.canvas.itemconfigure(rect, outline=BLUE if on else outline, width=3 if on else line_width)

    def _link_keys(self, first, second) -> None:
        transmitter, asset = (first, second) if first[0] == "tx" else (second, first)
        self.link(transmitter[1], asset[1])

    def _on_resize(self, event) -> None:
        if event.width != self._drawn_width:
            self._drawn_width = event.width
            self.redraw()

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _set_hint(self, text: str, *, warning: bool = False) -> None:
        self.hint_var.set(text)
        self.hint_label.configure(foreground=AMBER if warning else TEXT)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_var.set(text)
        self.status_label.configure(foreground=RED if error else MUTED)

    def _set_live(self, text: str, *, error: bool = False, warning: bool = False) -> None:
        self.live_var.set(text)
        self.live_label.configure(foreground=RED if error else AMBER if warning else BLUE)


def _event_channels(transmitters: Iterable[TransmitterInfo]) -> dict[str, int]:
    """Device ID to channel for the transmitters whose latest value the receiver keeps (Event driven only)."""
    return {
        info.device_id: info.channel for info in transmitters
        if info.state == TransmitterState.CONNECTED and info.mode == MeasurementMode.EVENT_DRIVEN
        and info.channel is not None
    }


def _value_key(result) -> object:
    """What a value request result says about the instrument's reading; None when it says nothing."""
    if isinstance(result, LatestReading):
        return result.packet.value, result.packet.unit
    if isinstance(result, StatusReported) and result.packet.code == StatusCode.NO_DATA:
        return _NO_DATA
    return None


def _result_text(result) -> str:
    return _format_value(result.packet) if isinstance(result, LatestReading) else _reading_problem(result)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _format_value(packet: MeasurementPacket) -> str:
    text = format(packet.value, "f")
    return f"{text} {packet.unit}" if packet.unit else text


def _reading_problem(error: Exception) -> str:
    if isinstance(error, StatusReported):
        return _READING_PROBLEMS.get(error.packet.code, f"Status {error.packet.code:02d}")
    if isinstance(error, ResponseTimeout):
        return "No reply"
    if isinstance(error, TransmitterChanged):
        return "Changed: rescan"
    return "Read failed"


def _assets(equipment: Iterable[EquipmentLike]) -> list[Asset]:
    assets: dict[str, Asset] = {}
    for item in equipment:
        asset_id = str(item.asset_id or "").strip()
        if asset_id and asset_id not in assets:
            assets[asset_id] = Asset(
                asset_id, str(item.tag or ""), str(item.name or ""), str(item.category or ""),
                tuple(str(label) for label in getattr(item, "used_by", ()) or ()),
            )
    return list(assets.values())


def _fit(text: str, font: tkfont.Font, width: int) -> str:
    if font.measure(text) <= width:
        return text
    while text and font.measure(text + "…") > width:
        text = text[:-1]
    return text + "…"


DEMO_ASSETS = (
    Asset("demo-asset-0001", "CAL-001", "6 in digital caliper", "Caliper", ("1", "4")),
    Asset("demo-asset-0002", "MIC-002", "0-1 in outside micrometer", "Micrometer", ("2",)),
    Asset("demo-asset-0003", "IND-003", "Dial test indicator", "Indicator", ("3",)),
    Asset("demo-asset-0004", "HGT-004", "12 in height gauge", "Height Gauge", ("5", "6")),
)


def demo_receiver():
    from .simulation import SimulatedReceiver

    receiver = SimulatedReceiver(group=7, device_id="0000000001")
    receiver.register(1, "0000100001", "12.345")
    receiver.register(2, "0000100002", "0.5000", "in")
    receiver.register(5, "0000100005", connected=False)
    receiver.register(8, "0000100008", "25.000", mode=MeasurementMode.BUTTON_DRIVEN)
    return receiver


class DemoInstruments(tk.Toplevel):
    """The operator's hands in the demo: change a simulated instrument's reading or press its DATA button.

    A child of the setup window, so the setup window's grab still lets it be clicked.
    """

    def __init__(self, parent: tk.Misc, receiver):
        super().__init__(parent)
        self.title("Demo instruments")
        self.resizable(False, False)
        self.transient(parent)
        self.geometry("-24+80")
        self.receiver = receiver
        self._turns: dict[int, int] = {}
        self._values: dict[int, tk.StringVar] = {}
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Simulated instruments", font="TkHeadingFont").grid(
            row=0, column=0, columnspan=3, sticky="w",
        )
        ttk.Label(frame, text="Try Read Values or Identify, then use these.", foreground=MUTED).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 8),
        )
        for row, (channel, transmitter) in enumerate(sorted(receiver.transmitters.items()), start=2):
            ttk.Label(frame, text=f"CH {channel:02d}").grid(row=row, column=0, sticky="w", pady=2)
            self._values[channel] = tk.StringVar(self)
            ttk.Label(frame, textvariable=self._values[channel], width=16).grid(row=row, column=1, padx=8)
            if not transmitter.connected:
                ttk.Label(frame, text="Not connected", foreground=MUTED).grid(row=row, column=2, sticky="w")
            elif transmitter.mode == MeasurementMode.EVENT_DRIVEN:
                ttk.Button(frame, text="Change reading", command=lambda c=channel: self.change(c)).grid(
                    row=row, column=2, sticky="ew",
                )
            else:
                ttk.Button(frame, text="Press DATA", command=lambda c=channel: self.press(c)).grid(
                    row=row, column=2, sticky="ew",
                )
            self._show(channel)

    def change(self, channel: int) -> None:
        """Turn the instrument a little, back and forth on alternate clicks."""
        transmitter = self.receiver.transmitters[channel]
        turn = self._turns[channel] = self._turns.get(channel, 0) + 1
        step = Decimal(5).scaleb(transmitter.value.as_tuple().exponent)
        transmitter.value += step if turn % 2 else -step
        self._show(channel)

    def press(self, channel: int) -> None:
        self.receiver.press_data(channel)
        self._show(channel, "sent ")

    def _show(self, channel: int, prefix: str = "") -> None:
        transmitter = self.receiver.transmitters[channel]
        if transmitter.value is None:
            self._values[channel].set("")
        else:
            value = format(transmitter.value, "f")
            self._values[channel].set(f"{prefix}{value} {transmitter.unit or ''}".rstrip())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Link ERP assets to U-WAVE transmitters.")
    parser.add_argument("--demo", action="store_true", help="use a simulated receiver and sample assets")
    parser.add_argument("--settings", type=Path, help="links file (default: per-user app data; demo: temp folder)")
    args = parser.parse_args(argv)
    root = tk.Tk()
    root.withdraw()
    try:
        if args.demo:
            receiver = demo_receiver()
            window = SetupWindow(
                root, DEMO_ASSETS,
                store=ConfigStore(args.settings or Path(tempfile.gettempdir()) / "uwave-accessory-demo.json"),
                open_transport=lambda _port: receiver,
                list_ports=lambda: [PortInfo(DEMO_PORT, "simulated U-WAVE-R")],
                default_port=DEMO_PORT, title=f"{TITLE} (demo)",
            )
            DemoInstruments(window, receiver)
        else:
            window = SetupWindow(root, (), store=ConfigStore(args.settings))
        window.run()
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
