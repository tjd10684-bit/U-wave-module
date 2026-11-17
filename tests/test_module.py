from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from open_erp_module import CaptureRequest, Context, ModuleError
from uwave_accessory.links import ConfigStore, Link
from uwave_accessory.protocol import MeasurementMode
from uwave_accessory.setup_window import DEMO_PORT, PORT_LOCK
from module.uwave_module import UWaveModule


ASSET = "asset-1"
DEVICE = "0000100001"


@pytest.fixture
def uwave_module(tmp_path):
    module = UWaveModule()
    store = ConfigStore(tmp_path / "links.json")
    settings = store.load()
    settings.port = DEMO_PORT
    settings.group = 7
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
