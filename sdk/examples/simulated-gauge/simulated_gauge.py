"""Simulated Gauge: an Open ERP measurement module that needs no hardware.

Link Open ERP assets to simulated gauges in the setup window and enter the reading each gauge
returns. Use it to try capture, or as a starting point for a real device module.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from open_erp_module import Equipment, Module, ModuleError, Reading, run

logger = logging.getLogger("simulated-gauge")


def _valid(link: object) -> bool:
    return (
        isinstance(link, dict) and isinstance(link.get("gauge"), int) and link.get("units") in ("mm", "in")
        and isinstance(link.get("value"), (int, float)) and math.isfinite(link["value"])
    )


class SimulatedGauge(Module):
    module_id = "simulated-gauge"
    name = "Simulated Gauge"
    version = "1.0.0"
    acquisition_mode = "latest"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.links: dict[str, dict] = {}
        self.settings: Path | None = None

    def initialize(self, context) -> None:
        self.settings = context.data_dir / "links.json"
        try:
            # utf-8-sig: Notepad and Windows PowerShell 5.1 save UTF-8 with a byte order mark.
            data = json.loads(self.settings.read_text(encoding="utf-8-sig"))
            self.links = {asset: link for asset, link in data.get("links", {}).items() if _valid(link)}
        except FileNotFoundError:
            self.links = {}
        except (OSError, ValueError, AttributeError) as error:
            logger.error("Could not read %s: %s", self.settings, error)
            self.report_status("warning", "Saved links could not be read; link the assets again in setup.")
            return
        logger.info("Loaded %d link(s) from %s", len(self.links), self.settings)
        self.report_status("ready", "Simulated readings; no hardware is used.")

    def save(self) -> None:
        temporary = self.settings.with_suffix(".tmp")
        temporary.write_text(json.dumps({"links": self.links}, indent=2), encoding="utf-8")
        os.replace(temporary, self.settings)

    def linked_assets(self) -> list[str]:
        with self.lock:
            return list(self.links)

    def capture(self, request) -> Reading:
        with self.lock:
            link = self.links.get(request.asset_id)
        if link is None:
            raise ModuleError("This asset is not linked in Simulated Gauge. Link it in the module's setup.", 1001)
        return Reading(value=link["value"], units=link["units"], source_id=f"simulated:gauge-{link['gauge']}")

    def open_setup(self, equipment: list[Equipment]) -> None:
        with self.lock:
            links = {asset: dict(link) for asset, link in self.links.items()}
        window = SetupWindow(equipment, links)
        if window.run():
            with self.lock:
                self.links = window.links
                self.save()
            logger.info("Saved %d link(s)", len(window.links))


class SetupWindow:
    """Link assets to gauge numbers and choose the reading each gauge returns."""

    def __init__(self, equipment: list[Equipment], links: dict[str, dict]) -> None:
        self.links = links
        self.saved = False
        self.equipment = {item.asset_id: item for item in equipment}
        self.root = tk.Tk()
        self.root.title("Simulated Gauge Setup")
        self.root.geometry("720x420")
        self.root.minsize(560, 320)
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text="Select an asset, choose a gauge number and the reading it returns, then Link.").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 8)
        )
        columns = ("tag", "name", "category", "gauge", "reading")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for column, heading, width in zip(columns, ("Tag", "Name", "Category", "Gauge", "Reading"), (90, 220, 130, 70, 110)):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, stretch=column == "name")
        self.tree.grid(row=1, column=0, sticky=tk.NSEW)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.load_selected())

        editor = ttk.Frame(frame)
        editor.grid(row=2, column=0, sticky=tk.W, pady=8)
        self.gauge = tk.StringVar(self.root, value="1")
        self.value = tk.StringVar(self.root, value="1.000")
        self.units = tk.StringVar(self.root, value="mm")
        ttk.Label(editor, text="Gauge").pack(side=tk.LEFT)
        ttk.Spinbox(editor, from_=1, to=99, width=4, textvariable=self.gauge).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(editor, text="Reading").pack(side=tk.LEFT)
        ttk.Entry(editor, width=10, textvariable=self.value).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Combobox(editor, values=("mm", "in"), width=4, state="readonly", textvariable=self.units).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        ttk.Button(editor, text="Link", command=self.link).pack(side=tk.LEFT)
        ttk.Button(editor, text="Unlink", command=self.unlink).pack(side=tk.LEFT, padx=6)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, sticky=tk.EW)
        ttk.Button(buttons, text="Cancel", command=self.root.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Save", command=self.save).pack(side=tk.RIGHT, padx=6)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        # Links for assets Open ERP did not offer this time are kept; they may only be filtered out.
        for asset_id in [*self.equipment, *(asset for asset in self.links if asset not in self.equipment)]:
            item = self.equipment.get(asset_id, Equipment(asset_id, "", "(not offered by Open ERP)", ""))
            link = self.links.get(asset_id)
            reading = f"{link['value']:g} {link['units']}" if link else ""
            self.tree.insert("", tk.END, iid=asset_id, values=(
                item.tag, item.name, item.category, link["gauge"] if link else "", reading,
            ))

    def selected(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def load_selected(self) -> None:
        link = self.links.get(self.selected() or "")
        if link:
            self.gauge.set(str(link["gauge"]))
            self.value.set(f"{link['value']:g}")
            self.units.set(link["units"])

    def link(self) -> None:
        asset_id = self.selected()
        if asset_id is None:
            messagebox.showinfo("Simulated Gauge", "Select an asset first.", parent=self.root)
            return
        try:
            gauge, value = int(self.gauge.get()), float(self.value.get())
            if gauge < 1 or not math.isfinite(value):
                raise ValueError
        except ValueError:
            messagebox.showerror("Simulated Gauge", "Enter a gauge number and a reading.", parent=self.root)
            return
        self.links[asset_id] = {"gauge": gauge, "value": value, "units": self.units.get()}
        self.refresh()
        self.tree.selection_set(asset_id)

    def unlink(self) -> None:
        asset_id = self.selected()
        if asset_id in self.links:
            del self.links[asset_id]
            self.refresh()

    def save(self) -> None:
        self.saved = True
        self.root.destroy()

    def run(self) -> bool:
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.root.mainloop()
        return self.saved


if __name__ == "__main__":
    raise SystemExit(run(SimulatedGauge()))
