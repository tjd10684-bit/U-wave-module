from datetime import datetime, timezone
from decimal import Decimal
import gc
import queue
import threading
import time
from types import SimpleNamespace
import tkinter as tk
import weakref

import pytest

from uwave_accessory import setup_window
from uwave_accessory.links import AccessoryConfig, ConfigStore, Link
from uwave_accessory.protocol import DataRequest, MeasurementMode, MeasurementPacket
from uwave_accessory.receiver import LatestReading
from uwave_accessory.serial_transport import PortInfo, TransportError
from uwave_accessory.setup_window import SetupWindow
from uwave_accessory.simulation import SimulatedReceiver
from uwave_accessory.theme import palette_from_host
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
        list_ports=options.pop("list_ports", lambda: [PortInfo("SIM", "simulator")]), default_port="SIM",
        theme=options.pop("theme", "light"), **options,  # not "auto": that would read this PC's Open ERP choice
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


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_window_is_dressed_in_the_palette_of_its_mode(root, receiver, store, mode):
    window = open_window(root, receiver, store, theme=mode)
    palette = setup_window.PALETTES[mode]

    assert window.palette is palette
    assert window.cget("background") == palette.bg
    assert window.canvas.cget("background") == palette.canvas_bg
    assert window.canvas.itemcget(window._card_rects[TX1][0], "fill") == palette.card_fill
    window.destroy()


def test_window_uses_the_palette_the_host_sent(root, receiver, store):
    palette = palette_from_host("dark", {"background": "#101010", "field": "#181818"})
    window = open_window(root, receiver, store, theme=palette)

    assert window.palette is palette
    assert window.canvas.cget("background") == "#101010"
    assert window.canvas.itemcget(window._card_rects[TX1][0], "fill") == "#181818"
    window.destroy()


def test_auto_follows_the_mode_open_erp_saved_on_this_workstation(root, receiver, store, tmp_path, monkeypatch):
    (tmp_path / "Open ERP").mkdir()
    (tmp_path / "Open ERP" / "preferences.json").write_text('{"theme": "dark"}', encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    window = open_window(root, receiver, store, theme="auto")

    assert window.palette.mode == "dark"
    window.destroy()


def test_port_selection_notifies_module_about_selected_port(root, receiver, store):
    selected = []
    window = open_window(root, receiver, store, on_port_selected=selected.append)

    window._port_changed()

    assert selected == ["SIM"]
    window.destroy()


def test_drag_links_either_way_and_delete_unlinks(root, receiver, store):
    window = open_window(root, receiver, store)
    drag(window, point(window, TX1), point(window, ("asset", "a1")))
    drag(window, point(window, ("asset", "a2")), point(window, TX2))
    assert window.settings.links == {
        "a1": Link("a1", "CAL-001", "0000100001", 1, 7, "SIM"),
        "a2": Link("a2", "MIC-002", "0000100002", 2, 7, "SIM"),
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
    assert window.settings.links == {"a1": Link("a1", "CAL-001", "0000100001", 1, 7, "SIM")}
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
    config = AccessoryConfig({"SIM": None})
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
    assert "Scan failed: SIM: Could not open SIM: access denied." in window.status_var.get()
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


def card_fill(window, key):
    return window.canvas.itemcget(window._card_rects[key][0], "fill")


def test_read_values_shows_what_changed_since_the_last_click(root, receiver, store):
    receiver.register(3, "0000100003")  # Event driven, but the receiver holds no value for it yet
    window = open_window(root, receiver, store)
    wait_for(root, lambda: not window._reading)  # a scan reads the starting values
    tx1, tx2, tx3 = window.transmitters
    assert window._value_text(tx1) == ("1.000 mm", setup_window.TEXT)
    assert window._value_text(tx2) is None  # Button driven: the receiver keeps no value
    assert window._value_text(tx3) == ("No data yet", setup_window.CAUTION)
    assert window.live_var.get().startswith("Values read at")
    assert "Unavailable" not in window.live_var.get()  # "no data yet" is a state, not a failure
    assert window.link("0000100001", "a1")

    receiver.transmitters[1].value = Decimal("1.250")
    receiver.transmitters[3].value = Decimal("3.000")
    window.read_values()
    assert str(window.read_button["text"]) == "Reading..."
    wait_for(root, lambda: not window._reading)
    assert window._moved == {"0000100001", "0000100003"}
    assert window.live_var.get() == (
        "Changed since the last read: CH 01 (CAL-001) 1.000 mm → 1.250 mm; CH 03 No data yet → 3.000 mm"
    )
    assert window._value_text(tx1) == ("1.250 mm", setup_window.ACCENT)
    assert card_fill(window, TX1) == card_fill(window, ("asset", "a1")) == window.palette.moved_fill
    assert card_fill(window, TX2) == card_fill(window, ("asset", "a2")) == window.palette.card_fill

    requests = len(receiver.requests)
    time.sleep(0.2)
    root.update()
    assert len(receiver.requests) == requests  # values are read only when asked
    window.read_values()
    wait_for(root, lambda: not window._reading)
    assert window._moved == set() and card_fill(window, TX1) == window.palette.card_fill
    assert window.live_var.get().startswith("No values changed since the last read")
    assert {request.channel for request in receiver.requests if isinstance(request, DataRequest)} == {1, 3}
    window.destroy()


def test_rescan_waits_for_an_in_flight_value_request_and_drops_its_result(root, receiver, store, monkeypatch):
    window = open_window(root, receiver, store)
    wait_for(root, lambda: not window._reading)
    real_read, real_scan = setup_window.read_latest_values, setup_window.scan_receiver
    started, release, scans = threading.Event(), threading.Event(), []
    stale = LatestReading(MeasurementPacket(7, 1, Decimal("9.999"), "mm"), datetime.now(timezone.utc))

    def slow_read(*_args, **_kwargs):
        started.set()
        assert release.wait(5), "test did not release the value request"
        return {"0000100001": stale}

    def recorded_scan(*args):
        scans.append(args)
        return real_scan(*args)

    monkeypatch.setattr(setup_window, "read_latest_values", slow_read)
    monkeypatch.setattr(setup_window, "scan_receiver", recorded_scan)
    window.read_values()
    assert started.wait(2)
    monkeypatch.setattr(setup_window, "read_latest_values", real_read)
    try:
        window.scan()
        time.sleep(0.2)
        root.update()
        assert window.scanning and not scans  # the port is still in use by the value request
    finally:
        release.set()
    wait_for(root, lambda: not window.scanning and not window._reading and window.readings)
    assert len(scans) == 1
    assert window.readings["0000100001"].packet.value == Decimal("1.000")
    window.destroy()


def identify_thread():
    return next((thread for thread in threading.enumerate() if thread.name == "uwave-identify"), None)


def test_identify_links_the_selected_asset_to_the_instrument_whose_reading_changes(root, receiver, store):
    window = open_window(root, receiver, store, identify_interval=0.02)
    wait_for(root, lambda: not window._reading)
    assert str(window.identify_button["state"]) == "disabled"
    click(window, point(window, ("asset", "a2")))
    window.identify()
    wait_for(root, lambda: window._identify.deadline is not None)
    assert window.identify_bar.grid_info() and not window.skip_button.winfo_manager()
    assert window.identify_var.get().startswith(
        "Identify MIC-002: change its instrument's reading, or press its DATA button. Leave the other"
    )
    worker = identify_thread()

    receiver.transmitters[1].value = Decimal("1.005")
    wait_for(root, lambda: window._identify is None)
    assert window.settings.links == {"a2": Link("a2", "MIC-002", "0000100001", 1, 7, "SIM")}
    assert window.live_var.get() == "Linked MIC-002 to CH 01. Click Save to keep it."
    assert window._moved == {"0000100001"} and not window.identify_bar.grid_info()
    worker.join(timeout=5)
    assert not worker.is_alive()
    window.destroy()


def test_link_all_identifies_each_unlinked_asset_in_turn(root, receiver, store):
    window = open_window(root, receiver, store, identify_interval=0.02)
    wait_for(root, lambda: not window._reading)
    window.link_all()
    wait_for(root, lambda: window._identify.deadline is not None)
    assert window.identify_var.get().startswith("Identify CAL-001 (1 of 2):")
    assert window.skip_button.winfo_manager() == "pack"
    assert window._selected is None and window._card_rects[("asset", "a1")][1:] == (window.palette.accent, 3)

    receiver.press_data(2)
    wait_for(root, lambda: window._identify.index == 1)
    assert window.live_var.get() == "Linked CAL-001 to CH 02."
    assert window._value_text(window.transmitters[1]) == ("2.000 mm", setup_window.ACCENT)

    wait_for(root, lambda: window._identify.deadline is not None)  # MIC-002's starting values are in
    assert window.identify_var.get().startswith("Identify MIC-002 (2 of 2): change")
    receiver.transmitters[1].value = Decimal("0.995")
    wait_for(root, lambda: window._identify is None)
    assert window.settings.links == {
        "a1": Link("a1", "CAL-001", "0000100002", 2, 7, "SIM"),
        "a2": Link("a2", "MIC-002", "0000100001", 1, 7, "SIM"),
    }
    assert window.live_var.get() == (
        "Link All finished. Linked CAL-001 to CH 02 and MIC-002 to CH 01. Click Save to keep them."
    )
    assert str(window.link_all_button["state"]) == "disabled"  # nothing left to link
    window.destroy()


def reading(channel, value):
    return LatestReading(MeasurementPacket(7, channel, Decimal(value), "mm"), datetime.now(timezone.utc))


def put_round(session, values, *presses):
    session.results.put((time.perf_counter(), values, list(presses)))


def test_identify_links_nothing_while_the_answer_is_ambiguous(root, receiver, store, monkeypatch):
    monkeypatch.setattr(setup_window, "watch_for_responses", lambda *args: None)  # the test supplies the rounds
    receiver.register(3, "0000100003", "3.000")
    window = open_window(root, receiver, store)
    wait_for(root, lambda: not window._reading)
    window.link("0000100003", "a1")
    click(window, point(window, ("asset", "a2")))
    window.identify()
    session = window._identify

    def round_(tx1, tx3, *presses):
        put_round(session, {"0000100001": reading(1, tx1), "0000100003": reading(3, tx3)}, *presses)
        wait_for(root, session.results.empty)

    round_("1.000", "3.000", ("0000100002", reading(2, "2.000")))  # pressed before Identify started
    assert window.settings.links.keys() == {"a1"} and window._identify is session
    round_("1.005", "3.005")
    assert window.live_var.get().startswith("CH 01 and CH 03 (CAL-001) responded at once.")
    round_("1.005", "3.010")
    assert window.live_var.get().startswith("CH 03 responded, but it is already linked to CAL-001.")
    assert window.settings.links.keys() == {"a1"} and window._identify is session
    round_("1.005", "3.010", ("0000100002", reading(2, "2.000")))
    assert window._identify is None
    assert window.settings.links["a2"].device_id == "0000100002"
    window.destroy()


def test_identify_gives_up_and_link_all_skips_when_nothing_responds(root, receiver, store, monkeypatch):
    monkeypatch.setattr(setup_window, "watch_for_responses", lambda *args: None)
    window = open_window(root, receiver, store, identify_seconds=0.1)
    wait_for(root, lambda: not window._reading)
    click(window, point(window, ("asset", "a1")))
    window.identify()
    put_round(window._identify, {"0000100001": reading(1, "1.000")})
    wait_for(root, lambda: window._identify is None)
    assert window.live_var.get().startswith("Nothing responded within 0.1 s.")

    window.link_all()
    put_round(window._identify, {"0000100001": reading(1, "1.000")})
    wait_for(root, lambda: window._identify is not None and window._identify.index == 1)
    put_round(window._identify, {"0000100001": reading(1, "1.000")})
    wait_for(root, lambda: window._identify is None)
    assert window.live_var.get() == "Link All finished. Skipped CAL-001 and MIC-002. Nothing was linked."
    assert window.settings.links == {}
    window.destroy()


def test_answers_queued_before_an_asset_was_asked_for_link_nothing(root, receiver, store, monkeypatch):
    monkeypatch.setattr(setup_window, "watch_for_responses", lambda *args: None)
    window = open_window(root, receiver, store)
    wait_for(root, lambda: not window._reading)
    window.link_all()
    session = window._identify
    put_round(session, {"0000100001": reading(1, "1.000")})
    wait_for(root, lambda: session.deadline is not None)

    # Both rounds wait in the queue, as during a drag: only the first answers CAL-001's prompt.
    put_round(session, {"0000100001": reading(1, "1.005")})
    put_round(session, {"0000100001": reading(1, "1.005")}, ("0000100002", reading(2, "2.000")))
    wait_for(root, session.results.empty)
    assert window.settings.links.keys() == {"a1"} and session.target == "a2" and session.deadline is None
    assert window.identify_var.get() == "Identify MIC-002 (2 of 2): reading the current values…"
    assert session.wake.is_set()  # the worker starts a fresh round for MIC-002 at once

    put_round(session, {"0000100001": reading(1, "1.005")}, ("0000100002", reading(2, "2.000")))
    wait_for(root, lambda: session.deadline is not None)
    assert window.settings.links.keys() == {"a1"}  # pressed before MIC-002's prompt asked for it
    put_round(session, {"0000100001": reading(1, "1.005")}, ("0000100002", reading(2, "2.000")))
    wait_for(root, lambda: window._identify is None)
    assert window.settings.links["a2"].device_id == "0000100002"
    window.destroy()


def test_skipping_or_linking_by_hand_drops_answers_already_queued(root, receiver, store, monkeypatch):
    monkeypatch.setattr(setup_window, "watch_for_responses", lambda *args: None)
    window = open_window(root, receiver, store)
    wait_for(root, lambda: not window._reading)
    window.link_all()
    session = window._identify
    press = ("0000100002", reading(2, "2.000"))
    put_round(session, {"0000100001": reading(1, "1.000")}, press)
    window.skip_identify()  # before the starting values were in
    wait_for(root, session.results.empty)
    assert session.target == "a2" and session.deadline is None and not window.settings.links
    put_round(session, {"0000100001": reading(1, "1.000")}, press)
    wait_for(root, lambda: session.deadline is not None)
    assert not window.settings.links

    put_round(session, {"0000100001": reading(1, "1.000")}, press)
    window.link("0000100001", "a2")
    wait_for(root, lambda: window._identify is None)
    assert window.settings.links["a2"].device_id == "0000100001"
    assert window.live_var.get() == (
        "Link All finished. MIC-002 was linked by hand. Skipped CAL-001. Click Save to keep it."
    )
    window.destroy()


def test_identification_rounds_include_a_press_that_arrives_with_a_value_reply(receiver):
    class PressAfterFirstReply:
        pressed = False

        def write(self, data):
            receiver.write(data)
            if not self.pressed:
                self.pressed = True
                receiver.press_data(2)

        def read(self, timeout):
            return receiver.read(timeout)

    results, stop = queue.Queue(), threading.Event()
    worker = threading.Thread(target=setup_window.watch_for_responses, args=(
        lambda _port: PressAfterFirstReply(), "SIM", 7, {"0000100001": 1}, {2: "0000100002"}, results, stop,
        threading.Event(), 0.02,
    ))
    worker.start()
    try:
        _asked, values, presses = results.get(timeout=5)
    finally:
        stop.set()
        worker.join(timeout=5)
    assert values["0000100001"].packet.value == Decimal("1.000")
    assert [device_id for device_id, _ in presses] == ["0000100002"]


def test_closing_during_identify_stops_the_worker_and_frees_the_port(root, receiver, store):
    window = open_window(root, receiver, store, identify_interval=0.02)
    wait_for(root, lambda: not window._reading)
    window.link_all()
    wait_for(root, lambda: window._identify.deadline is not None)
    worker = identify_thread()
    window.destroy()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert setup_window.PORT_LOCK.acquire(timeout=1)
    setup_window.PORT_LOCK.release()


def test_enabling_two_receivers_reads_both_and_saves_port_bound_links(root, receiver, store):
    second = SimulatedReceiver(group=7)
    second.register(1, "0000200001", "0.5000", "in")
    receivers = {"SIM": receiver, "BLE": second}
    window = open_window(root, receiver, store, open_transport=receivers.__getitem__,
                         list_ports=lambda: [PortInfo(port, port) for port in receivers])
    wait_for(root, lambda: not window._reading)
    window.link("0000100001", "a1")
    window.port_var.set("BLE")
    window._port_changed()
    assert window.settings.receivers == {"SIM": None}
    window.enabled_var.set(True)
    window._receiver_toggled()
    wait_for(root, lambda: not window.scanning and not window._reading)
    assert window.settings.receivers == {"SIM": None, "BLE": None}
    assert window.readings["0000100001"].packet.value == Decimal("1.000")
    assert window.readings["0000200001"].packet.value == Decimal("0.5000")
    assert window.link("0000200001", "a2")
    receiver.transmitters[1].value = Decimal("1.250")
    second.transmitters[1].value = Decimal("0.7500")
    window.read_values()
    wait_for(root, lambda: not window._reading)
    assert window._moved == {"0000100001", "0000200001"}
    assert "SIM CH 01" in window.live_var.get() and "BLE CH 01" in window.live_var.get()
    assert "SIM" in window._asset_text(window.assets[0])[2]
    assert "BLE" in window._asset_text(window.assets[1])[2]
    assert window.save()
    saved = store.load()
    assert saved.receivers == {"SIM": None, "BLE": None}
    assert saved.links["a1"].port == "SIM"
    assert saved.links["a2"].port == "BLE"


def test_failed_receiver_does_not_hide_healthy_receiver_or_reuse_stale_values(root, receiver, store):
    second = SimulatedReceiver(group=7)
    second.register(1, "0000200001", "0.5000", "in")
    receivers = {"SIM": receiver, "BLE": second}
    store.save(AccessoryConfig({"SIM": None, "BLE": None}, {
        "a1": Link("a1", "CAL-001", "0000100001", 1, 7, "SIM"),
    }))

    def open_port(port):
        if port not in receivers:
            raise TransportError(f"{port} unplugged")
        return receivers[port]

    window = open_window(root, receiver, store, open_transport=open_port)
    wait_for(root, lambda: not window._reading)
    del receivers["SIM"]
    window.read_values()
    wait_for(root, lambda: not window._reading)
    assert isinstance(window.readings["0000100001"], TransportError)
    assert window.readings["0000200001"].packet.value == Decimal("0.5000")
    assert "SIM unplugged" in window.live_var.get()
    window.scan()
    wait_for(root, lambda: not window.scanning and not window._reading)
    assert set(window.readings) == {"0000200001"}
    assert "SIM unplugged" in window.status_var.get()
    assert window.settings.links["a1"].port == "SIM"
    assert window._asset_text(window.assets[0])[2:4] == (
        "SIM · CH 01 · Not checked: receiver scan failed", setup_window.NEUTRAL,
    )
    assert str(window.read_button["state"]) == "normal"
    assert str(window.identify_button["state"]) == "disabled"
    window.destroy()


def test_duplicate_device_ids_across_receivers_are_not_silently_routed(root, receiver, store):
    store.save(AccessoryConfig({"SIM": None, "OTHER": None}, {
        "a1": Link("a1", "CAL-001", "0000100001", 1, 7, "SIM"),
    }))
    window = open_window(root, receiver, store)
    assert window.transmitters == []
    assert "registered on multiple receivers" in window.status_var.get()
    assert window._asset_text(window.assets[0])[2:4] == (
        "SIM · CH 01 · Registered on several receivers", setup_window.ERROR,
    )
    assert not window.link("0000100001", "a1")
    assert not any(isinstance(item, DataRequest) for item in receiver.requests)
    window.destroy()


def test_link_on_a_receiver_not_in_use_is_unchecked_rather_than_missing(root, receiver, store):
    store.save(AccessoryConfig({"SIM": None}, {"a1": Link("a1", "CAL-001", "0000900001", 1, 7, "USB")}))
    window = open_window(root, receiver, store)
    assert window._asset_text(window.assets[0])[2:4] == (
        "CH 01 · Not checked: USB not in use", setup_window.NEUTRAL,
    )
    click(window, point(window, ("tx", "0000900001")))
    assert "Receiver USB is not in use" in window.hint_var.get()
    assert window.settings.links["a1"].port == "USB"
    window.destroy()


def test_identify_uses_selected_receiver_when_channels_overlap(root, receiver, store):
    second = SimulatedReceiver(group=7)
    second.register(1, "0000200001", "0.5000", "in")
    receivers = {"SIM": receiver, "BLE": second}
    store.save(AccessoryConfig({"SIM": None, "BLE": None}))
    window = open_window(root, receiver, store, open_transport=receivers.__getitem__, identify_interval=0.02,
                         list_ports=lambda: [PortInfo(port, port) for port in receivers])
    wait_for(root, lambda: not window._reading)
    window.port_var.set("BLE")
    window._port_changed()
    click(window, point(window, ("asset", "a2")))
    window.identify()
    wait_for(root, lambda: window._identify.deadline is not None)
    assert window._identify.event_devices == {"0000200001"}
    assert "Receiver: BLE" in window.identify_var.get()
    second.transmitters[1].value = Decimal("0.7500")
    wait_for(root, lambda: window._identify is None)
    assert window.settings.links["a2"].port == "BLE"
    assert window.settings.links["a2"].device_id == "0000200001"
    window.destroy()


def test_disabling_receiver_keeps_links_but_does_not_reenable_it_on_reopen(root, receiver, store):
    window = open_window(root, receiver, store)
    wait_for(root, lambda: not window._reading)
    window.link("0000100001", "a1")
    window.enabled_var.set(False)
    window._receiver_toggled()
    assert window.transmitters is None and not window.readings
    assert str(window.read_button["state"]) == "disabled"
    assert window.save()
    window = open_window(root, receiver, store)
    assert window.settings.receivers == {}
    assert window.settings.links["a1"].port == "SIM"
    assert window.transmitters is None
    assert not window.enabled_var.get()
    window.destroy()
