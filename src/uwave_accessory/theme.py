"""Open ERP's light and dark look for the setup window, and which of the two to use.

A current Open ERP sends its exact colours with ``open_setup`` and the window uses them (``palette_from_host``).
When the host sends none, the window falls back to the mode the operator picked in Open ERP's preferences file,
which this module only reads, and then to the Windows light or dark setting.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk

AUTO, LIGHT, DARK = "auto", "light", "dark"
MODES = (LIGHT, DARK)
OPEN_ERP_DEFAULT = DARK  # what Open ERP shows until the operator picks a mode

# Colour roles the setup window uses for text and lines; Palette.color turns one into a colour.
TEXT, MUTED, READY, CAUTION, ERROR, NEUTRAL, ACCENT = "text", "muted", "ready", "caution", "error", "neutral", "accent"
ROLES = (TEXT, MUTED, READY, CAUTION, ERROR, NEUTRAL, ACCENT)


@dataclass(frozen=True)
class Palette:
    mode: str
    # Window chrome, using the values Open ERP's own palettes have for the same parts.
    bg: str
    field: str
    readonly_field: str
    border: str
    button: str
    button_active: str
    select_bg: str
    select_fg: str
    disabled_fg: str
    # Text and line colours by role.
    text: str
    muted: str
    ready: str
    caution: str
    error: str
    neutral: str
    accent: str
    # Highlights only this module draws; a host cannot send them.
    moved_fill: str
    prompt_bg: str
    # The link canvas is built from the window's own surfaces, so it follows whatever palette the window has.
    canvas_bg: str = dataclasses.field(init=False)
    card_fill: str = dataclasses.field(init=False)
    ghost_fill: str = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "canvas_bg", self.bg)
        object.__setattr__(self, "card_fill", self.field)
        object.__setattr__(self, "ghost_fill", self.readonly_field)

    def color(self, role: str) -> str:
        if role not in ROLES:
            raise KeyError(role)
        return getattr(self, role)


PALETTES = {
    LIGHT: Palette(
        mode=LIGHT, bg="#f0f0f0", field="#ffffff", readonly_field="#ececec", border="#a8a8a8", button="#e1e1e1",
        button_active="#d3dce8", select_bg="#3a6ea5", select_fg="#ffffff", disabled_fg="#9a9a9a",
        text="#1e1e1e", muted="#666666", ready="#28623a", caution="#7a4b00", error="#aa3333", neutral="#666666",
        accent="#245b75", moved_fill="#fff3c4", prompt_bg="#dce6f2",
    ),
    DARK: Palette(
        mode=DARK, bg="#202124", field="#2b2d31", readonly_field="#26282c", border="#4a4d52", button="#34373c",
        button_active="#41464d", select_bg="#3a6ea5", select_fg="#ffffff", disabled_fg="#6f737a",
        text="#e6e6e6", muted="#9aa0a6", ready="#7ee2a8", caution="#e3b341", error="#ff7b72", neutral="#a0a0a0",
        accent="#79c0ff", moved_fill="#3d3512", prompt_bg="#243447",
    ),
}

# The colour roles a host sends with open_setup (the SDK's PROTOCOL.md) and the palette part each one sets.
HOST_ROLES = {
    "background": "bg", "field": "field", "field_readonly": "readonly_field", "border": "border",
    "button": "button", "button_active": "button_active", "text": "text", "text_muted": "muted",
    "text_disabled": "disabled_fg", "selection": "select_bg", "selection_text": "select_fg",
    "ready": "ready", "caution": "caution", "error": "error", "neutral": "neutral", "accent": "accent",
}
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def palette_from_host(mode: str, colors: Mapping[str, str]) -> Palette:
    """The palette for a theme Open ERP sent: its colours where it sent them, this module's own for the rest.

    Raises ValueError for a mode that is not light or dark.
    """
    if mode not in MODES:
        raise ValueError(f"Theme mode must be one of {', '.join(MODES)}, not {mode!r}.")
    sent = {
        HOST_ROLES[role]: color.lower() for role, color in colors.items()
        if role in HOST_ROLES and isinstance(color, str) and _HEX_COLOR.fullmatch(color)
    }
    return dataclasses.replace(PALETTES[mode], **sent)


def open_erp_config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "Open ERP" if appdata else Path.home() / ".config" / "open-erp"


def saved_mode(config_dir: Path) -> str | None:
    """The mode the operator picked in Open ERP on this workstation; None when there is no valid choice."""
    try:
        data = json.loads((config_dir / "preferences.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    mode = data.get("theme") if isinstance(data, dict) else None
    return mode if mode in MODES else None


def system_mode() -> str | None:
    """The Windows apps light or dark setting; None where it cannot be read."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            light, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except (ImportError, OSError):
        return None
    return LIGHT if light else DARK


def detect_mode(
    preference: str = AUTO, *, config_dir: Path | None = None, read_system: Callable[[], str | None] = system_mode,
) -> str:
    """Light or dark: the preference when it names one, else Open ERP's mode, else the Windows one."""
    if preference in MODES:
        return preference
    if preference != AUTO:
        raise ValueError(f"Theme must be one of {', '.join((AUTO, *MODES))}, not {preference!r}.")
    folder = config_dir or open_erp_config_dir()
    mode = saved_mode(folder)
    if mode is not None:
        return mode
    if folder.is_dir():  # Open ERP has run here but nobody picked a mode, so it shows its default
        return OPEN_ERP_DEFAULT
    return read_system() or LIGHT


def apply(window: tk.Toplevel, palette: Palette) -> None:
    """Dress a window and the widgets in its interpreter in the palette; do it before building the widgets."""
    window.configure(background=palette.bg)
    _style_ttk(window, palette)
    _color_title_bar(window, palette.mode == DARK)


def _style_ttk(window: tk.Misc, palette: Palette) -> None:
    # The native Windows theme ignores colours, so, like Open ERP, build on the plain clam theme.
    style = ttk.Style(window)
    style.theme_use("clam")
    p = palette
    style.configure(
        ".", background=p.bg, foreground=p.text, bordercolor=p.border, troughcolor=p.readonly_field,
        lightcolor=p.bg, darkcolor=p.bg, focuscolor=p.select_bg, selectbackground=p.select_bg,
        selectforeground=p.select_fg, fieldbackground=p.field, insertcolor=p.text,
    )
    style.map(".", foreground=[("disabled", p.disabled_fg)])
    style.configure("TButton", background=p.button, lightcolor=p.button, darkcolor=p.button, padding=(8, 3))
    style.map(
        "TButton", background=[("disabled", p.bg), ("pressed", p.button_active), ("active", p.button_active)],
        lightcolor=[("pressed", p.button_active), ("active", p.button_active)],
        darkcolor=[("pressed", p.button_active), ("active", p.button_active)],
    )
    for name in ("TEntry", "TCombobox"):
        style.configure(name, fieldbackground=p.field, lightcolor=p.field, darkcolor=p.field, padding=2)
        style.map(
            name, fieldbackground=[("readonly", p.field), ("disabled", p.readonly_field)],
            foreground=[("disabled", p.disabled_fg)], selectbackground=[("readonly", p.field)],
            selectforeground=[("readonly", p.text)],
        )
    style.configure("TCombobox", background=p.button, arrowcolor=p.text)
    style.map("TCombobox", background=[("active", p.button_active)], arrowcolor=[("disabled", p.disabled_fg)])
    style.configure(
        "TCheckbutton", indicatorbackground=p.field, indicatorforeground=p.text, upperbordercolor=p.border,
        lowerbordercolor=p.border,
    )
    style.map(
        "TCheckbutton", background=[("active", p.bg)], indicatorbackground=[("disabled", p.readonly_field)],
        indicatorforeground=[("disabled", p.disabled_fg)],
    )
    style.configure(
        "TScrollbar", background=p.button, arrowcolor=p.text, lightcolor=p.button, darkcolor=p.button,
    )
    style.map("TScrollbar", background=[("active", p.button_active)])
    # The drop-down list of a combobox is a classic Listbox that only the option database can colour.
    window.option_add("*TCombobox*Listbox.background", p.field)
    window.option_add("*TCombobox*Listbox.foreground", p.text)
    window.option_add("*TCombobox*Listbox.selectBackground", p.select_bg)
    window.option_add("*TCombobox*Listbox.selectForeground", p.select_fg)


def _color_title_bar(window: tk.Toplevel, dark: bool) -> None:
    """Switch the Windows title bar between its dark and light look; other platforms keep theirs."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    user32, dwm = ctypes.WinDLL("user32"), ctypes.WinDLL("dwmapi")
    user32.GetParent.argtypes, user32.GetParent.restype = [wintypes.HWND], wintypes.HWND
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, *([ctypes.c_int] * 4), wintypes.UINT]
    dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    def paint(event=None) -> None:
        if event is not None and event.widget is not window:
            return
        try:
            hwnd = user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1 if dark else 0)
            # 20 is the documented attribute; 19 is what Windows 10 builds before 20H1 know it as.
            if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)) != 0:
                dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
        except (OSError, tk.TclError):
            pass  # a cosmetic extra; the window works with the default title bar

    window.bind("<Map>", paint, add="+")
