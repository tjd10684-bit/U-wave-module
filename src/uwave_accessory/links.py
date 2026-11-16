"""Asset-to-transmitter links: the accessory-owned mapping in the host contract.

A link joins an ERP asset UUID to a transmitter's device ID, which is the
transmitter's identity. The channel and group are only the address where it
was last seen: U-WAVEPAK can move a transmitter to another channel, so every
use must revalidate the link against a fresh scan (see check_link). Links are
one-to-one. They are stored per PC, because transmitter registrations live in
that PC's receiver.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .protocol import MeasurementMode, TransmitterInfo, TransmitterState, is_device_id

SCHEMA_VERSION = 1


class ConfigError(RuntimeError):
    """The saved settings file cannot be read; it is left untouched."""


@dataclass(frozen=True)
class Link:
    asset_id: str
    asset_label: str  # the asset tag when linked, for display only
    device_id: str
    channel: int | None  # last seen address, not identity
    group: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, str) or not self.asset_id.strip():
            raise ValueError("asset_id must be a non-empty string")
        if not isinstance(self.asset_label, str):
            raise ValueError("asset_label must be a string")
        if not is_device_id(self.device_id):
            raise ValueError(f"invalid device ID {self.device_id!r}")
        for value, name in ((self.channel, "channel"), (self.group, "group")):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 99):
                raise ValueError(f"{name} must be 0-99 or null, got {value!r}")


@dataclass
class AccessoryConfig:
    port: str | None = None
    group: int | None = None  # None: detect the receiver's group on each scan
    links: dict[str, Link] = field(default_factory=dict)  # keyed by asset_id

    def link_for_device(self, device_id: str) -> Link | None:
        return next((link for link in self.links.values() if link.device_id == device_id), None)

    def link(self, asset_id: str, asset_label: str, transmitter: TransmitterInfo) -> list[Link]:
        """Link an asset to a transmitter, replacing either side's old link; return the replaced links."""
        new = Link(asset_id, asset_label, transmitter.device_id, transmitter.channel, transmitter.group)
        replaced = [
            link for link in self.links.values()
            if link.asset_id == asset_id or link.device_id == transmitter.device_id
        ]
        for link in replaced:
            del self.links[link.asset_id]
        self.links[asset_id] = new
        return [link for link in replaced if link != new]

    def unlink(self, asset_id: str) -> Link | None:
        return self.links.pop(asset_id, None)

    def update_addresses(self, transmitters: Iterable[TransmitterInfo]) -> None:
        """Record where linked transmitters were last seen."""
        by_device = {transmitter.device_id: transmitter for transmitter in transmitters}
        for asset_id, link in list(self.links.items()):
            found = by_device.get(link.device_id)
            if found is not None and (found.channel, found.group) != (link.channel, link.group):
                self.links[asset_id] = Link(link.asset_id, link.asset_label, link.device_id, found.channel, found.group)


class LinkState(Enum):
    READY = "ready"
    MOVED = "moved"
    DISCONNECTED = "disconnected"
    BUTTON_DRIVEN = "button driven"
    EDITING = "editing"
    NOT_FOUND = "not found"
    NOT_SCANNED = "not scanned"


@dataclass(frozen=True)
class LinkCheck:
    state: LinkState
    message: str
    transmitter: TransmitterInfo | None = None

    @property
    def usable(self) -> bool:
        return self.state in (LinkState.READY, LinkState.MOVED)


def check_link(link: Link, transmitters: Iterable[TransmitterInfo] | None) -> LinkCheck:
    """Judge a link against the latest scan; transmitters=None means no scan yet."""
    if transmitters is None:
        return LinkCheck(LinkState.NOT_SCANNED, "Scan the receiver to check this link.")
    found = next((item for item in transmitters if item.device_id == link.device_id), None)
    if found is None:
        return LinkCheck(LinkState.NOT_FOUND, f"Transmitter {link.device_id} is not registered in this receiver.")
    if found.state in (TransmitterState.EDITING, TransmitterState.EDITING_SOURCE, TransmitterState.EDITING_DESTINATION):
        return LinkCheck(LinkState.EDITING, "Transmitter is being edited in U-WAVEPAK; finish there and rescan.", found)
    if found.state != TransmitterState.CONNECTED:
        return LinkCheck(LinkState.DISCONNECTED, "Transmitter is not connected; wake the instrument and rescan.", found)
    if found.mode != MeasurementMode.EVENT_DRIVEN:
        return LinkCheck(
            LinkState.BUTTON_DRIVEN, "Transmitter is button driven; set Event driven in U-WAVEPAK Setup.", found,
        )
    if link.channel is not None and found.channel != link.channel:
        return LinkCheck(LinkState.MOVED, f"Ready; moved from channel {link.channel:02d} to {found.channel:02d}.", found)
    return LinkCheck(LinkState.READY, "Ready.", found)


def default_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "UWaveAccessory" if base else Path.home() / ".uwave-accessory"
    return root / "links.json"


class ConfigStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else default_path()

    def load(self) -> AccessoryConfig:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return AccessoryConfig()
        except OSError as error:
            raise ConfigError(f"Could not read {self.path}: {error}") from error
        try:
            data = json.loads(text)
            if data.get("schema") != SCHEMA_VERSION:
                raise ValueError(f"unsupported schema {data.get('schema')!r}")
            receiver = data.get("receiver", {})
            port, group = receiver.get("port"), receiver.get("group")
            if port is not None and not isinstance(port, str):
                raise ValueError("receiver port must be a string")
            if group is not None and (isinstance(group, bool) or not isinstance(group, int) or not 0 <= group <= 99):
                raise ValueError("receiver group must be 0-99 or null")
            config = AccessoryConfig(port, group)
            for item in data.get("links", []):
                link = Link(**item)
                if link.asset_id in config.links or config.link_for_device(link.device_id):
                    raise ValueError(f"duplicate link for asset {link.asset_id} or device {link.device_id}")
                config.links[link.asset_id] = link
        except (AttributeError, TypeError, ValueError) as error:
            raise ConfigError(f"{self.path} is not a valid U-WAVE settings file: {error}") from error
        return config

    def save(self, config: AccessoryConfig) -> None:
        data = {
            "schema": SCHEMA_VERSION,
            "receiver": {"port": config.port, "group": config.group},
            "links": [asdict(link) for link in sorted(config.links.values(), key=lambda link: link.asset_label)],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=self.path.name, suffix=".tmp", delete=False,
            ) as handle:
                json.dump(data, handle, indent=2)
            os.replace(handle.name, self.path)
        except OSError as error:
            try:
                os.unlink(handle.name)
            except (NameError, OSError):
                pass
            raise ConfigError(f"Could not save {self.path}: {error}") from error
