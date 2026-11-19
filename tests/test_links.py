import json

import pytest

from uwave_accessory.links import (
    AccessoryConfig, ConfigError, ConfigStore, Link, LinkState, check_link,
)
from uwave_accessory.protocol import MeasurementMode, TransmitterInfo, TransmitterState


def transmitter(channel, device_id, state=TransmitterState.CONNECTED, mode=MeasurementMode.EVENT_DRIVEN):
    return TransmitterInfo(state, channel, 7, device_id, 11, mode)


def test_links_are_one_to_one_and_report_what_they_replace():
    config = AccessoryConfig()
    assert config.link("a1", "CAL-1", transmitter(3, "0000000001")) == []
    assert config.link("a2", "CAL-2", transmitter(3, "0000000001")) == [
        Link("a1", "CAL-1", "0000000001", 3, 7),
    ]
    assert config.link("a2", "CAL-2", transmitter(4, "0000000002")) == [
        Link("a2", "CAL-2", "0000000001", 3, 7),
    ]
    assert config.links == {"a2": Link("a2", "CAL-2", "0000000002", 4, 7)}
    assert config.unlink("a2") is not None and config.links == {}


def test_addresses_follow_the_device_id_not_the_channel():
    config = AccessoryConfig()
    config.link("a1", "CAL-1", transmitter(3, "0000000001"))
    config.update_addresses([transmitter(5, "0000000001"), transmitter(3, "0000000009")])
    assert config.links["a1"].channel == 5


@pytest.mark.parametrize(("scan", "state"), [
    (None, LinkState.NOT_SCANNED),
    ([transmitter(3, "0000000009")], LinkState.NOT_FOUND),
    ([transmitter(3, "0000000001", TransmitterState.EDITING_SOURCE)], LinkState.EDITING),
    ([transmitter(3, "0000000001", TransmitterState.DISCONNECTED)], LinkState.DISCONNECTED),
    ([transmitter(3, "0000000001", mode=MeasurementMode.BUTTON_DRIVEN)], LinkState.BUTTON_DRIVEN),
    ([transmitter(8, "0000000001")], LinkState.MOVED),
    ([transmitter(3, "0000000001")], LinkState.READY),
])
def test_link_check_revalidates_against_the_latest_scan(scan, state):
    check = check_link(Link("a1", "CAL-1", "0000000001", 3, 7), scan)
    assert check.state == state
    assert check.usable == (state in (LinkState.READY, LinkState.MOVED))


def test_store_round_trips_and_treats_a_missing_file_as_empty(tmp_path):
    store = ConfigStore(tmp_path / "nested" / "links.json")
    assert store.load() == AccessoryConfig()
    config = AccessoryConfig({"COM5": None, "COM6": 7})
    config.link("a1", "CAL-1", transmitter(3, "0000000001"), "COM6")
    store.save(config)
    assert store.load() == config
    assert list((tmp_path / "nested").iterdir()) == [store.path]


@pytest.mark.parametrize("text", [
    "not json",
    json.dumps({"schema": 3}),
    json.dumps({"schema": 2}),
    json.dumps({"schema": 2, "receivers": [{"port": "COM5"}, {"port": "com5"}]}),
    json.dumps({"schema": 2, "receivers": [{"port": ""}]}),
    json.dumps({"schema": 2, "receivers": [{"port": "COM5", "group": True}]}),
    json.dumps({"schema": 1, "receiver": {"group": 100}}),
    json.dumps({"schema": 1, "links": [{"asset_id": "a1", "asset_label": "", "device_id": "12", "channel": 1, "group": 1}]}),
    json.dumps({"schema": 1, "links": [
        {"asset_id": "a1", "asset_label": "", "device_id": "0000000001", "channel": 1, "group": 1},
        {"asset_id": "a2", "asset_label": "", "device_id": "0000000001", "channel": 2, "group": 1},
    ]}),
])
def test_store_refuses_invalid_files_without_touching_them(tmp_path, text):
    path = tmp_path / "links.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigStore(path).load()
    assert path.read_text(encoding="utf-8") == text


def test_legacy_settings_migrate_without_guessing_a_second_receiver(tmp_path):
    store = ConfigStore(tmp_path / "links.json")
    original = json.dumps({
        "schema": 1, "receiver": {"port": "COM5", "group": None},
        "links": [{"asset_id": "a1", "asset_label": "CAL-1", "device_id": "0000000001", "channel": 3, "group": 7}],
    })
    store.path.write_text(original, encoding="utf-8")
    config = store.load()
    assert store.path.read_text(encoding="utf-8") == original
    assert config.receivers == {"COM5": None}
    assert config.port_for_link(config.links["a1"]) == "COM5"
    config.receivers["COM6"] = None
    assert config.port_for_link(config.links["a1"]) is None
    config.update_addresses([transmitter(5, "0000000001")], "COM6")
    assert config.links["a1"] == Link("a1", "CAL-1", "0000000001", 5, 7, "COM6")
    store.save(config)
    assert json.loads(store.path.read_text(encoding="utf-8"))["schema"] == 2
    assert store.load() == config
