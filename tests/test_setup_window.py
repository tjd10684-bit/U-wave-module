import gc
import threading
import time
from types import SimpleNamespace
import tkinter as tk
import weakref

import pytest

from uwave_accessory import setup_window
from uwave_accessory.links import AccessoryConfig, ConfigStore, Link
from uwave_accessory.protocol import MeasurementMode
from uwave_accessory.serial_transport import PortInfo, TransportError
from uwave_accessory.setup_window import SetupWindow
from uwave_accessory.simulation import SimulatedReceiver

EQUIPMENT = (
    SimpleNamespace(asset_id="a1", tag="CAL-001", name="Caliper", category="Caliper"),
    SimpleNamespace(asset_id="a2", tag="MIC-002", name="Micrometer", category="Micrometer", used_by=("2", "5")),
    SimpleNamespace(asset_id="a1", tag="CAL-001", name="Caliper", category="Caliper"),
)
TX1, TX2 = ("tx", "0000100001"), ("tx", "0000100002")


@pytest.fixture(scope="module")
def tk_root():
    # One interpreter, like the host: a discarded Tk root can be freed by a collection on a scan thread, which Tcl forbids.
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk is unavailable: {error}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def root(tk_root):
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()
    # Without a mainloop, a scan thread that collects a closed window's Tk variables stalls about 1 s per variable.
    gc.collect()


@pytest.fixture
def receiver():
    receiver = SimulatedReceiver(group=7)
    receiver.register(1, "0000100001", "1.000")
    receiver.register(2, "0000100002", "2.000", mode=MeasurementMode.BUTTON_DRIVEN)
    return receiver


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "links.json")


def open_window(root, receiver, store, **options):
    window = SetupWindow(
        root, EQUIPMENT, store=store, open_transport=options.pop("open_transport", lambda _port: receiver),
        list_ports=lambda: [PortInfo("SIM", "simulator")], default_port="SIM", **options,
    )
    wait_for(root, lambda: not window.scanning and window._startup_id is None)
    return window


def wait_for(root, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    root.update()
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the window"
        time.sleep(0.01)
        root.update()


def point(window, key):
    x1, y1, x2, y2 = window.canvas.coords(window._card_rects[key][0])
    return SimpleNamespace(x=(x1 + x2) / 2, y=(y1 + y2) / 2)


def click(window, at):
    window._on_press(at)
    window._on_release(at)


def drag(window, start, end):
    window._on_press(start)
    window._on_motion(SimpleNamespace(x=(start.x + end.x) / 2, y=(start.y + end.y) / 2))
    window._on_motion(end)
    window._on_release(end)


def link_midpoint(window, asset_id):
    line = next(item for item, key in window._hit.items() if key == ("link", asset_id))
    x1, y1, x2, y2 = (window.canvas.coords(line)[index] for index in (0, 1, -2, -1))
    return SimpleNamespace(x=(x1 + x2) / 2, y=(y1 + y2) / 2)


def test_scan_lists_transmitters_left_and_each_asset_once_right(root, receiver, store):
    window = open_window(root, receiver, store)
    assert [info.channel for info in window.transmitters] == [1, 2]
    assert {TX1, TX2, ("asset", "a1"), ("asset", "a2")} <= set(window._card_rects)
    assert [asset.asset_id for asset in window.assets] == ["a1", "a2"]
    assert window.assets[1].used_by == ("2", "5")
    assert window._ports[TX1][0] < window._ports[("asset", "a1")][0]
    assert "Used by 2, 5" in window._asset_text(window.assets[1])[1]
    assert "group 07 (detected)" in window.status_var.get()
    window.destroy()


def test_drag_links_either_way_and_delete_unlinks(root, receiver, store):
    window = open_window(root, receiver, store)
    drag(window, point(window, TX1), point(window, ("asset", "a1")))
    drag(window, point(window, ("asset", "a2")), point(window, TX2))
    assert window.settings.links == {
        "a1": Link("a1", "CAL-001", "0000100001", 1, 7), "a2": Link("a2", "MIC-002", "0000100002", 2, 7),
    }
    assert "Event driven" in window.hint_var.get()
    click(window, SimpleNamespace(x=2, y=2))
    click(window, link_midpoint(window, "a1"))
    assert str(window.unlink_button["state"]) == "normal"
    window.unlink_selected()
    assert set(window.settings.links) == {"a2"}
    assert window.dirty
    window.destroy()


def test_click_one_then_the_other_links_and_relinking_replaces(root, receiver, store):
    window = open_window(root, receiver, store)
    click(window, point(window, TX1))
    click(window, point(window, ("asset", "a2")))
    click(window, point(window, TX1))
    click(window, point(window, ("asset", "a1")))
    assert window.settings.links == {"a1": Link("a1", "CAL-001", "0000100001", 1, 7)}
    assert "Replaced: MIC-002" in window.hint_var.get()
    window.destroy()


def test_saved_link_to_a_missing_transmitter_stays_visible_as_not_found(root, receiver, store):
    window = open_window(root, receiver, store)
    assert window.link("0000100001", "a1")
    assert window.save() and not window.winfo_exists()
    del receiver.transmitters[1]
    window = open_window(root, receiver, store)
    assert TX1 in window._card_rects
    assert window._card_rects[TX1][0] in window._hit
    assert window._asset_text(window.assets[0])[2] == "CH 01 · Transmitter not found"
    assert window.settings.links["a1"].device_id == "0000100001"
    window.destroy()


@pytest.mark.parametrize("confirm", [False, True])
def test_taking_a_transmitter_from_an_asset_outside_the_list_asks_first(root, receiver, store, monkeypatch, confirm):
    config = AccessoryConfig("SIM")
    config.links["other"] = Link("other", "GAGE-9", "0000100001", 1, 7)
    store.save(config)
    window = open_window(root, receiver, store)
    monkeypatch.setattr(setup_window.messagebox, "askyesno", lambda *args, **kwargs: confirm)
    assert window.link("0000100001", "a1") is confirm
    assert set(window.settings.links) == ({"a1"} if confirm else {"other"})
    window.destroy()


def test_closing_without_saving_discards_changes(root, receiver, store, monkeypatch):
    window = open_window(root, receiver, store)
    window.link("0000100001", "a1")
    monkeypatch.setattr(setup_window.messagebox, "askyesnocancel", lambda *args, **kwargs: False)
    window.cancel()
    assert not window.winfo_exists()
    assert store.load().links == {}


def test_scan_failure_is_reported_and_lists_nothing(root, receiver, store):
    def busy(port):
        raise TransportError(f"Could not open {port}: access denied.")

    window = open_window(root, receiver, store, open_transport=busy)
    assert window.transmitters is None
    assert window.status_var.get() == "Scan failed: Could not open SIM: access denied."
    window.destroy()


def test_rescan_invalidates_old_availability_even_when_it_fails(root, receiver, store, monkeypatch):
    window = open_window(root, receiver, store)
    window.link("0000100001", "a1")
    saved_links = dict(window.settings.links)
    release = threading.Event()

    def unplugged(*_args):
        assert release.wait(5), "test did not release the scan"
        raise TransportError("Receiver unplugged.")

    monkeypatch.setattr(setup_window, "scan_receiver", unplugged)
    try:
        window.scan()
        assert window.transmitters is None and window.receiver is None
        assert "Not checked" in window._asset_text(window.assets[0])[2]
        assert not window.link("0000100001", "a2")
    finally:
        release.set()
        wait_for(root, lambda: not window.scanning)
    assert "Receiver unplugged" in window.status_var.get()
    assert window.transmitters is None and window.receiver is None
    assert window.settings.links == saved_links
    assert "Not checked" in window._asset_text(window.assets[0])[2]
    window.destroy()


def test_closing_during_scan_does_not_leave_the_worker_owning_tk(root, receiver, store, monkeypatch):
    window = open_window(root, receiver, store)
    result = setup_window.ScanResult(window.receiver, window.transmitters)
    release, started = threading.Event(), threading.Event()
    workers = []

    def delayed(*_args):
        workers.append(threading.current_thread())
        started.set()
        assert release.wait(5), "test did not release the scan"
        return result

    monkeypatch.setattr(setup_window, "scan_receiver", delayed)
    try:
        window.scan()
        assert started.wait(2)
        reference = weakref.ref(window)
        window.destroy()
        del window
        gc.collect()
        assert reference() is None
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=5)
            assert not worker.is_alive()


def test_destroy_releases_tcl_fonts_and_traces(root, receiver, store):
    fonts = set(root.tk.splitlist(root.tk.call("font", "names")))
    window = open_window(root, receiver, store)
    filter_var = window.filter_var
    window.destroy()
    window.destroy()
    assert set(root.tk.splitlist(root.tk.call("font", "names"))) == fonts
    assert filter_var.trace_info() == []
