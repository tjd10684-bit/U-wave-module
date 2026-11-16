"""Visual setup: link the ERP's assets to U-WAVE transmitters.

Transmitters registered in the U-WAVE-R are listed on the left and the assets
the host passes in are listed on the right. Drag one onto the other, or click
one and then the other, to link them. Select a link and press Delete (or
Unlink) to remove it. Links are saved per PC by links.ConfigStore.

configure(parent, equipment) matches the host contract's configure callback.
Try it without hardware: python -m uwave_accessory.setup_window --demo
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk
from typing import Callable, Iterable, Protocol

from .links import AccessoryConfig, ConfigError, ConfigStore, LinkState, check_link
from .protocol import MeasurementMode, ReceiverInfo, TransmitterInfo, TransmitterState
from .receiver import ReceiverClient, ReceiverError, Transport, find_receiver
from .serial_transport import PortInfo, SerialTransport, TransportError, list_ports

logger = logging.getLogger(__name__)

TITLE = "Measurement Devices"
REQUEST_TIMEOUT = 1.0
DEMO_PORT = "Simulator"

CARD_HEIGHT, CARD_GAP, MARGIN, HEADER, MIN_CANVAS_WIDTH = 64, 12, 24, 44, 720
GREEN, AMBER, RED, GRAY, BLUE = "#2e7d32", "#e65100", "#c62828", "#757575", "#1565c0"
CANVAS_BG, CARD_FILL, GHOST_FILL, CARD_OUTLINE, TEXT, MUTED = (
    "#f4f6f8", "#ffffff", "#eceff1", "#b0bec5", "#212121", "#546e7a",
)
DEFAULT_HINT = (
    "Drag a transmitter onto an asset, or click one and then the other, to link them. "
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
        close = getattr(transport, "close", None)
        if close is not None:
            close()


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
    ):
        super().__init__(parent)
        self.title(title)
        self.store = store or ConfigStore()
        self.open_transport = open_transport
        self.list_ports = list_ports
        self.assets = _assets(equipment)
        self.saved = False
        self.dirty = False
        self.scanning = False
        self.transmitters: list[TransmitterInfo] | None = None  # None: not scanned yet
        self.receiver: ReceiverInfo | None = None
        self._results: queue.Queue = queue.Queue()
        self._poll_id: str | None = None
        self._startup_id: str | None = None
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

        if parent.winfo_viewable():
            self.transient(parent.winfo_toplevel())
        self.geometry(f"{min(1000, self.winfo_screenwidth() - 80)}x{min(640, self.winfo_screenheight() - 120)}")
        self.minsize(760, 460)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_toolbar()
        self._build_canvas()
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

    def _build_footer(self) -> None:
        info = ttk.Frame(self, padding=(12, 6, 12, 0))
        info.grid(row=2, column=0, sticky="ew")
        self.hint_var = tk.StringVar(self)
        self.hint_label = ttk.Label(info, textvariable=self.hint_var, wraplength=940)
        self.hint_label.pack(anchor="w")
        self.status_var = tk.StringVar(self)
        self.status_label = ttk.Label(info, textvariable=self.status_var, wraplength=940, foreground=MUTED)
        self.status_label.pack(anchor="w", pady=(2, 0))
        buttons = ttk.Frame(self, padding=12)
        buttons.grid(row=3, column=0, sticky="ew")
        self.unlink_button = ttk.Button(buttons, text="Unlink", command=self.unlink_selected, state="disabled")
        self.unlink_button.pack(side="left")
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
            return
        self.receiver, self.transmitters = result.receiver, result.transmitters
        before = dict(self.settings.links)
        self.settings.update_addresses(self.transmitters)
        self.dirty |= self.settings.links != before
        self.redraw()
        self._set_status(self._summary())

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
            self._set_hint(f"{label} selected: click a transmitter to link it." if kind == "asset" else DEFAULT_HINT)
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
        for after_id in (self._poll_id, self._startup_id):
            if after_id is not None:
                self.after_cancel(after_id)
        self._poll_id = self._startup_id = None
        # Tcl owns the trace callback and the font copies; left behind, they keep this window alive in the host.
        if self._filter_trace is not None:
            self.filter_var.trace_remove("write", self._filter_trace)
            self._filter_trace = None
        for font in (self._font, self._bold, self._heading):
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
            self._draw_card(key, left, y_left, card_width, *self._transmitter_text(info, link, visible))
            y_left += CARD_HEIGHT + CARD_GAP

        y_right = HEADER
        if not visible:
            empty = (
                "No assets match the filter." if self.assets
                else "The ERP passed no assets. Assign equipment to the part first."
            )
            canvas.create_text(right, y_right, anchor="nw", width=card_width, text=empty, fill=MUTED, font=self._font)
        for asset in visible:
            self._draw_card(("asset", asset.asset_id), right, y_right, card_width, *self._asset_text(asset))
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
        self.unlink_button.configure(state="normal" if self._selected_link_asset() else "disabled")

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

    def _draw_card(self, key, x, y, width, title, subtitle, status, color, ghost) -> None:
        canvas = self.canvas
        selected = self._selected == key
        outline, line_width = (BLUE, 3) if selected else (CARD_OUTLINE, 1)
        rect = canvas.create_rectangle(
            x, y, x + width, y + CARD_HEIGHT, fill=GHOST_FILL if ghost else CARD_FILL, outline=outline,
            width=line_width, **({"dash": (4, 3)} if ghost else {}),
        )
        text_width = width - 30
        items = [
            rect,
            canvas.create_text(x + 12, y + 8, anchor="nw", text=_fit(title, self._bold, text_width),
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
        else:
            window = SetupWindow(root, (), store=ConfigStore(args.settings))
        window.run()
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
