# U-WAVE accessory for Open ERP

An optional measurement-data collection accessory for Open ERP's inspection
workflow.

**Status: experimental U-WAVE helper module 0.2.1, released 2026-11-19.** Setup can scan
and read multiple receiver ports; Capture routes the selected asset to its
receiver. The setup window matches Open ERP's light or dark look. USB U-WAVE-R and the U-WAVEPAK-BW Bluetooth bridge have been exercised
together on one Windows 11 workstation, including captures through the packaged
helper. See [validation evidence and limits](VALIDATION_PLAN.md).
The module uses Open ERP's
separate helper-program contract (see the
[module SDK](https://github.com/tjd10684-bit/Open-ERP-Module-SDK), a separate repository).

## Goal

Keep ordinary HID/keyboard-style gauge input working as it does today. The goal
is an optional data-collection accessory for instrument identification and
software-requested readings; paired/synchronized capture remains a future extension.

U-WAVE is intended to be the first accessory. Other manufacturers should be
supported by separate accessories behind a common inspection interface, rather
than by adding vendor-specific logic throughout Inspection.

The longer-term motivating use case is a height gauge with an indicator mounted
as a fine correction. One pedal action would collect the intended pair. That
workflow, calculation, sign, reference offset and units remain to be confirmed;
the current implementation does not perform it.

**Initial host scope, agreed 2026-11-16:** one instrument per characteristic;
indirect A and B are separate readings from that same instrument. Two-instrument
capture is deferred. See [the version 1 host contract](HOST_CONTRACT.md) for
module-owned asset/transmitter setup, Capture/Ctrl+M versus HID input, and the
five-second host timeout.

## Install and try the visual demo

Use Python 3.12 or newer with Tkinter. From a checkout on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[serial,test]"
.\.venv\Scripts\python.exe -m pytest tests -q -rs
.\.venv\Scripts\python.exe -m uwave_accessory.setup_window --demo
```

The base package has no third-party runtime dependencies. The `serial` extra
adds pyserial; the `test` extra includes pytest, pyserial and the
[Open ERP module SDK](https://github.com/tjd10684-bit/Open-ERP-Module-SDK),
which pip installs from its pinned GitHub tag, so Git must be installed.
The equivalent installed launcher is `.\.venv\Scripts\uwave-setup.exe --demo`.

The demo needs neither the ERP nor a receiver. It uses synthetic equipment and
transmitter identities:

1. Transmitter cards appear on the **left**, assets on the **right**.
2. Drag a card onto the other side, or click a transmitter and then an asset.
3. Links are one-to-one. Relinking replaces the earlier link; moving a
   transmitter from an asset outside the current list requires confirmation.
4. Select a link/card and use **Unlink** or Delete to remove its link.
5. **Save** persists settings; **Cancel** offers Save/Discard/Cancel when changed.
6. Disconnected, missing, unscanned and button-driven transmitters have visible
   warnings. A new scan invalidates old availability, including if it fails.
7. **Read Values** shows each Event driven transmitter's latest value on its
   card (once after a scan, then once per click). Change an instrument, click
   it again, and the transmitters whose values changed are highlighted and
   listed below the canvas.
8. **Identify** links the selected asset to the instrument that responds:
   change that instrument's reading (Event driven) or press its transmitter's
   DATA button (Button driven) within 30 seconds. **Link All** asks for each
   listed asset without a link in turn; **Skip** and **Stop** are in the prompt
   bar. When several instruments respond, or one already linked to another
   asset, nothing is linked and it asks again. Unlink and Save work as usual.
9. The demo also opens a **Demo instruments** window whose buttons change a
   simulated reading or press a simulated DATA button.

The window matches Open ERP's light or dark look. When Open ERP sends its
colors with the setup request (module 0.2.1 with SDK 1.2 and an Open ERP newer
than 0.2.12), they
are used exactly. Otherwise the mode comes from the choice saved in Open ERP's
per-workstation preferences, then Open ERP's default (dark) if it has run on
this PC, then the Windows light/dark setting, then light. Preview a mode with
`--theme light` or `--theme dark` on the demo command; the default is `auto`.

Reading values does not wake the transmitters: the receiver answers from the
latest value it has stored. Event driven mode itself is what uses more
transmitter battery than Button driven mode.

Saved demo links use `uwave-accessory-demo.json` in the user's temporary folder.
Real settings use `%LOCALAPPDATA%\UWaveAccessory\links.json` (per Windows user
on this workstation); `--settings PATH` selects another location. Do not commit
shop settings or real device identities.

## Build and try the Open ERP module

The installable helper includes the visual asset/transmitter setup and offers a
**Simulator (demo)** port, so it can be tried without a receiver. From this
checkout, use Python 3.12 or newer with Tkinter. The `module` extra installs
pyserial and the pinned Open ERP module SDK (Git required):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[module]" pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_module.ps1 -Python .\.venv\Scripts\python.exe
```

The package is written to
`module\build\mitutoyo-u-wave-0.2.1.zip`. In an Open ERP build containing the
measurement-module host, choose **Settings > Measurement Devices... > Add
Module...** and select that zip. Select **Mitutoyo U-WAVE**, choose
**Open Setup...**, select **Simulator (demo)** and enable **Use this receiver**, then use the existing visual
linking interface to link a transmitter to an eligible asset and save. The demo
instrument window lets you change readings or press DATA; Capture (Ctrl+M)
returns the linked simulated transmitter's latest value.

The module stores its settings in Open ERP's per-user
`%LOCALAPPDATA%\Open ERP\module-data\mitutoyo-u-wave\links.json`. The standalone
hardware window's `%LOCALAPPDATA%\UWaveAccessory\links.json` is separate and is not
automatically migrated.

Settings schema 2 stores the enabled receiver ports/groups and each link's port.
Schema 1 settings load without being rewritten; a successful scan binds legacy
links to the receiver where each Device ID is found, and **Save** writes schema 2.
Back up settings before upgrading: older modules cannot read schema 2, so a
downgrade also requires restoring the pre-upgrade settings file. An unresolved
legacy link cannot be captured with several receivers enabled until it is scanned
and saved. Disabling a receiver preserves its links but blocks captures from it.
In setup, a link whose receiver failed to scan or is not in use is shown as
**Not checked** rather than missing, and a transmitter registered on several
receivers is flagged and cannot be linked or captured until it is on only one.

## Download a tester build

Experimental tester builds are published on this repository's
[Releases page](https://github.com/tjd10684-bit/U-wave-module/releases) as
`mitutoyo-u-wave-<version>.zip` with a `SHA256SUMS.txt` file. They need an Open ERP
build that has the measurement-module host (0.2.11 or later). Check the download,
then in Open ERP choose **Settings > Measurement Devices... > Add Module...** and
select the zip:

The latest release is 0.2.1, which adds the light/dark setup window to 0.2.0.
Open ERP 0.2.12 or later offers it automatically to installations of 0.1.1 or
0.2.0 (0.1.0 must be replaced by hand). The update keeps your links. Coming from
0.1.1, the settings are rewritten as schema 2 only when you click **Save** in
setup, so copy `links.json` first if you might go back to 0.1.1.

```powershell
Get-FileHash .\mitutoyo-u-wave-0.2.1.zip -Algorithm SHA256   # compare with SHA256SUMS.txt
```

Only install modules from publishers you trust: the package is not code-signed, so
Open ERP asks you to confirm the publisher. Hardware evidence is limited to the
configuration and checks in the validation plan; treat results as a preview,
not a blanket hardware-compatibility or production-inspection guarantee.

### Updates

Open ERP can offer a newer module version itself once the installed module declares
`update_repository = "tjd10684-bit/U-wave-module"` in its `module.toml`. It checks this
repository's latest release during its normal update check (and **Help > Check for
Updates...**), always asks before downloading, and verifies the zip against that release's
`SHA256SUMS.txt`. A build that predates the `update_repository` line, including v0.1.0, must be
replaced by hand once. Update releases must be normal releases tagged `v<major>.<minor>.<patch>`;
draft and pre-releases are ignored.

## On the hardware computer

Start without `--demo` to inspect the actual receiver:

```powershell
.\.venv\Scripts\python.exe -m uwave_accessory.setup_window
```

This route requires the manufacturer's working **virtual COM driver**. Direct
USB support in U-WAVEPAK alone is not sufficient. Close legacy U-WAVEPAK Setup,
Data I/F and any other port owner before scanning. Select the receiver's actual
COM port, its known Group ID (or Auto), and check **Use this receiver**.
Repeat for each receiver, including BW's displayed virtual COM port when using
Bluetooth. **Keep U-WAVEPAK-BW running**; it is the bridge, not a competing
legacy USB port owner. Disable **Simulator** if it is not part of the test.

Selecting a port edits that receiver's settings; it does not disable the others.
**Scan Receivers** discovers all enabled ports; **Read Values** reads their
connected Event driven transmitters in one action. Port labels distinguish
equal channel numbers. Requests are sequential latest-value reads, not simultaneous
physical samples. A failed port is reported without hiding healthy ports, and
duplicate Device IDs across ports are flagged rather than silently routed.

Scans and reads open and close each port; they do not modify vendor registrations,
modes or radio settings. **Identify** and **Link All** operate only on the
selected receiver and hold that port until they finish. Whether
the receiver forwards a Button driven DATA press over the virtual COM port, which
Identify relies on for those transmitters, is still to be confirmed.

The standalone hardware window has no ERP assets. In the helper module,
**Open Setup...** receives the assets supplied by Open ERP and uses this same
visual linking interface. Capture re-identifies a linked transmitter by Device
ID on its saved receiver port and follows its current channel before requesting
a reading. Other receivers need not be online for that capture. Each ERP Capture
still returns one reading for the selected asset; the host workflow is unchanged.
Do not mistake a saved visual link for a verified hardware connection.

Start with the checks in [HANDOFF.md](HANDOFF.md) and
[VALIDATION_PLAN.md](VALIDATION_PLAN.md). Bluetooth requires the BW bridge;
native BLE, paired capture and guaranteed fresh/simultaneous measurements are
not implemented.

## Package layout

| Module | Responsibility |
| --- | --- |
| [protocol.py](src/uwave_accessory/protocol.py) | ASCII packet framing and DT/ST/TI/RI decoding; DR/IR requests |
| [receiver.py](src/uwave_accessory/receiver.py) | Receiver/group discovery, transmitter listing, single-channel latest-value requests and listening for unsolicited packets |
| [serial_transport.py](src/uwave_accessory/serial_transport.py) | Optional pyserial connection, 57600 baud, 8N1, RTS/CTS |
| [links.py](src/uwave_accessory/links.py) | Asset UUID to transmitter Device ID links, scan checks and atomic JSON storage |
| [setup_window.py](src/uwave_accessory/setup_window.py) | Tkinter visual setup, value reading, automated identification and the demo launcher |
| [theme.py](src/uwave_accessory/theme.py) | Light/dark palettes, the host-sent palette, mode detection and Tk/title-bar styling |
| [simulation.py](src/uwave_accessory/simulation.py) | Synthetic receiver, simulated DATA presses and controllable test responses |
| [module/](module/) | Open ERP helper entry point, manifest and module build output |
| [tests](tests) | Protocol, request, loopback transport, mapping and GUI regression tests |

## Read in this order

| Document | Purpose |
| --- | --- |
| [HOST_CONTRACT.md](HOST_CONTRACT.md) | Agreed initial host API, single-instrument scope, mapping ownership and capture safeguards |
| [Open-ERP-Module-SDK](https://github.com/tjd10684-bit/Open-ERP-Module-SDK) | Measurement module SDK (separate repository): the helper-program protocol, Python library, `host_check` and an example module |
| [HANDOFF.md](HANDOFF.md) | Session context, agreed direction, evidence, unknowns, and how to resume on another machine |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Proposed host/accessory boundary and acquisition guarantees |
| [PROTOCOL_NOTES.md](PROTOCOL_NOTES.md) | Distinct USB-receiver and Bluetooth routes, ordering, cached readings, and pedal limitations |
| [VALIDATION_PLAN.md](VALIDATION_PLAN.md) | Focused software and hardware acceptance checks before claiming support |
| [REFERENCES.md](REFERENCES.md) | Manufacturer documentation, section references, and evidence limits |

## Two possible Mitutoyo connection routes

```text
Gauge -> U-WAVE transmitter -> wireless -> U-WAVE-R -> USB -> collector
Gauge -> U-WAVE Bluetooth module -> PC Bluetooth -> U-WAVEPAK-BW -> virtual COM -> collector
```

The second route does not pair with the U-WAVE-R receiver. Both routes can be
enabled since 0.2.0; validate each installation and its reconnection behavior.
In both documented event-driven routes, a request
retrieves a latest stored reading; it is not a promise of a fresh, simultaneous
measurement at the instant the pedal is pressed.

## Scope and publication

This public repository contains original accessory code, synthetic fixtures and
the agreed interface documentation. It does not contain private ERP source or
internal integration patches, real device identities, shop settings, credentials,
or copies of manufacturer manuals/software.

Hardware selection and driver distribution remain open. Open ERP
installs measurement modules as separate helper programs under
[the SDK's `PROTOCOL.md`](https://github.com/tjd10684-bit/Open-ERP-Module-SDK/blob/main/PROTOCOL.md);
the U-WAVE helper package is experimental.
The contract and simulator tests do not establish working physical U-WAVE
hardware support.

## License

Copyright (C) 2026 TD Manufacturing.

The U-WAVE module is free software: you can redistribute it and modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License or (at your option) any
later version. It is distributed in the hope that it will be useful, but
**without any warranty**; without even the implied warranty of merchantability
or fitness for a particular purpose. See [LICENSE](LICENSE) for the full text.

- **Source code.** This repository is the complete source. Each release's source
  archive is on its [releases page](https://github.com/tjd10684-bit/U-wave-module/releases),
  next to the installable package.
- **What is inside the package.** `mitutoyo-u-wave-<version>.zip` carries
  `LICENSE` and `THIRD-PARTY-NOTICES.txt` (Python, Tcl/Tk, pyserial, the Open ERP
  module SDK, the PyInstaller bootloader and the Microsoft C++ runtime, each under
  its own licence). `build_module.ps1` writes the notices from the build
  environment with `generate_notices.py`, and stops if a bundled component has no
  licence text.
- **The SDK is MIT.** The [Open ERP module SDK](https://github.com/tjd10684-bit/Open-ERP-Module-SDK)
  that this module is written against is MIT licensed, so other manufacturers'
  modules may use any licence. Open ERP and this module run as separate programs
  and talk over JSON-RPC.
- **Mitutoyo software is not included.** U-WAVEPAK and its drivers are Mitutoyo's
  and are installed separately under Mitutoyo's own terms.
