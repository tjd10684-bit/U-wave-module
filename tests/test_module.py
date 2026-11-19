from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from open_erp_module import CaptureRequest, Context, Module, ModuleError
from uwave_accessory.links import AccessoryConfig, ConfigStore, Link
from uwave_accessory.protocol import MeasurementMode
from uwave_accessory.setup_window import DEMO_PORT, PORT_LOCK
from uwave_accessory.serial_transport import TransportError
from uwave_accessory.simulation import SimulatedReceiver
from uwave_accessory.theme import PALETTES, Palette
from module.uwave_module import UWaveModule


ASSET = "asset-1"
DEVICE = "0000100001"


@pytest.fixture
def uwave_module(tmp_path):
    module = UWaveModule()
    store = ConfigStore(tmp_path / "links.json")
    settings = store.load()
    settings.receivers[DEMO_PORT] = 7
    settings.links[ASSET] = Link(ASSET, "MIC-014", DEVICE, 1, 7)
    store.save(settings)
    module.initialize(Context("mitutoyo-u-wave", tmp_path, "Open ERP", "test"))
    return module


def request(asset_id=ASSET, *, timeout=5.0, cancelled=False):
    result = CaptureRequest(
        capture_id="capture-1",
        asset_id=asset_id,
        units="mm",
        input_name="measurement",
        requested_at=datetime.now(timezone.utc),
        timeout_seconds=timeout,
    )
    if cancelled:
        result.cancelled.set()
    return result


def test_capture_resolves_saved_asset_link_to_latest_transmitter_value(uwave_module):
    result = uwave_module.capture(request())
    assert result.value == 12.345
    assert result.units == "mm"
    assert result.source_id == f"uwave-r:transmitter:{DEVICE}"
    assert result.received_at.tzinfo is not None
    assert uwave_module._simulator.requests[-1].channel == 1


def test_capture_follows_transmitter_identity_after_channel_change(uwave_module):
    receiver = uwave_module._simulator
    del receiver.transmitters[1]
    receiver.register(3, DEVICE, "8.765")

    result = uwave_module.capture(request())

    assert result.value == 8.765
    assert receiver.requests[-1].channel == 3


def test_capture_refuses_unlinked_assets(uwave_module):
    with pytest.raises(ModuleError, match="not linked"):
        uwave_module.capture(request("other-asset"))


def test_capture_refuses_button_driven_transmitter(uwave_module):
    uwave_module._simulator.transmitters[1].mode = MeasurementMode.BUTTON_DRIVEN

    with pytest.raises(ModuleError, match="Event driven"):
        uwave_module.capture(request())


def test_capture_refuses_transmitter_without_supported_units(uwave_module):
    uwave_module._simulator.transmitters[1].unit = None

    with pytest.raises(ModuleError, match="did not report units"):
        uwave_module.capture(request())


def test_capture_honors_cancel_before_opening_receiver(uwave_module):
    before = len(uwave_module._simulator.requests)
    with pytest.raises(ModuleError, match="cancelled"):
        uwave_module.capture(request(cancelled=True))
    assert len(uwave_module._simulator.requests) == before


@pytest.mark.parametrize("refused", [False, True])
def test_capture_closes_port_before_releasing_it_to_setup(uwave_module, monkeypatch, refused):
    closed_under_lock = []
    receiver = uwave_module._simulator
    if refused:
        receiver.transmitters[1].mode = MeasurementMode.BUTTON_DRIVEN

    class Transport:
        write = receiver.write
        read = receiver.read

        def close(self):
            acquired = PORT_LOCK.acquire(blocking=False)
            if acquired:
                PORT_LOCK.release()
            closed_under_lock.append(not acquired)

    monkeypatch.setattr(uwave_module, "_open_transport", lambda _port: Transport())
    if refused:
        with pytest.raises(ModuleError, match="Event driven"):
            uwave_module.capture(request())
    else:
        uwave_module.capture(request())
    assert closed_under_lock == [True]


def test_capture_times_out_while_setup_owns_the_port(uwave_module):
    with ThreadPoolExecutor(max_workers=1) as worker:
        with PORT_LOCK:
            pending = worker.submit(uwave_module.capture, request(timeout=0.03))
            with pytest.raises(ModuleError, match="busy"):
                pending.result(timeout=0.5)
    assert uwave_module._simulator.requests == []


def test_simulator_port_remains_available_without_serial_driver(monkeypatch):
    from module import uwave_module as module_file

    def missing_driver():
        raise module_file.TransportError("COM support needs pyserial.")

    monkeypatch.setattr(module_file, "available_ports", missing_driver)
    assert module_file.UWaveModule._list_ports() == [
        module_file.PortInfo(DEMO_PORT, "Simulator (demo)"),
    ]


def test_setup_theme_is_the_hosts_colours_when_it_sent_them():
    module = UWaveModule()
    module.host_theme = SimpleNamespace(mode="dark", colors={"background": "#101010", "accent": "#abcdef"})

    palette = module._setup_theme()

    assert isinstance(palette, Palette)
    assert (palette.mode, palette.bg, palette.accent) == ("dark", "#101010", "#abcdef")
    assert palette.text == PALETTES["dark"].text


@pytest.mark.parametrize("host_theme", [None, SimpleNamespace(mode="sepia", colors={})])
def test_setup_theme_looks_up_the_workstations_mode_without_a_usable_host_theme(host_theme):
    module = UWaveModule()
    module.host_theme = host_theme

    assert module._setup_theme() == "auto"


def test_setup_theme_works_with_an_sdk_that_has_no_host_theme(monkeypatch):
    monkeypatch.delattr(Module, "host_theme", raising=False)  # SDK 1.1 and older do not have it
    module = UWaveModule()

    assert not hasattr(module, "host_theme")
    assert module._setup_theme() == "auto"


def test_capture_routes_each_asset_to_its_port_despite_shared_group_and_channel(tmp_path, monkeypatch):
    first, second = SimulatedReceiver(group=7), SimulatedReceiver(group=7)
    first.register(1, DEVICE, "1.234", "mm")
    second.register(1, "0000200001", "0.5678", "in")
    store = ConfigStore(tmp_path / "links.json")
    store.save(AccessoryConfig({"COM5": None, "COM6": 7}, {
        ASSET: Link(ASSET, "MIC-1", DEVICE, 1, 7, "COM5"),
        "asset-2": Link("asset-2", "CAL-2", "0000200001", 1, 7, "COM6"),
    }))
    module = UWaveModule()
    module.initialize(Context("mitutoyo-u-wave", tmp_path, "Open ERP", "test"))
    opened = []
    receivers = {"COM5": first, "COM6": second}

    def open_port(port):
        opened.append(port)
        if port not in receivers:
            raise TransportError(f"{port} unplugged")
        return receivers[port]

    monkeypatch.setattr(module, "_open_transport", open_port)
    assert module.capture(request()).value == 1.234
    assert module.capture(request("asset-2")).value == 0.5678
    assert opened == ["COM5", "COM6"]
    del receivers["COM5"]
    assert module.capture(request("asset-2")).units == "in"
    with pytest.raises(ModuleError, match="COM5.*unplugged"):
        module.capture(request())
    assert module.capture(request("asset-2")).value == 0.5678
    receivers["COM6"] = first
    with pytest.raises(ModuleError, match="not registered"):
        module.capture(request("asset-2"))


@pytest.mark.parametrize(("port", "message"), [(None, "Rescan"), ("COM9", "not enabled")])
def test_capture_refuses_unresolved_or_disabled_receiver(tmp_path, monkeypatch, port, message):
    store = ConfigStore(tmp_path / "links.json")
    store.save(AccessoryConfig({"COM5": 7, "COM6": 7}, {
        ASSET: Link(ASSET, "MIC-1", DEVICE, 1, 7, port),
    }))
    module = UWaveModule()
    module.initialize(Context("mitutoyo-u-wave", tmp_path, "Open ERP", "test"))
    monkeypatch.setattr(module, "_open_transport", lambda _port: pytest.fail("must not open an arbitrary receiver"))
    with pytest.raises(ModuleError, match=message):
        module.capture(request())
