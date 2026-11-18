# U-WAVE accessory for Open ERP

An optional measurement-data collection accessory for Open ERP's inspection
workflow.

**Status: experimental U-WAVE helper module, 2026-11-17.** The legacy receiver
protocol, virtual-COM transport, simulated receiver, visual asset-linking window
and Open ERP helper package are implemented and tested against the simulator.
They have not been validated on physical hardware. The module uses Open ERP's
separate helper-program contract (see the
[module SDK](https://github.com/tjd10684-bit/Open-ERP-Module-SDK), a separate repository).

## Goal

Keep ordinary HID/keyboard-style gauge input working as it does today. The goal
is an optional data-collection accessory for instrument identification and
software-requested readings; multi-gauge capture remains a future extension.

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
`module\build\mitutoyo-u-wave-0.1.0.zip`. In an Open ERP build containing the
measurement-module host, choose **Settings > Measurement Devices... > Add
Module...** and select that zip. Select **Mitutoyo U-WAVE**, choose
**Open Setup...**, select **Simulator (demo)**, then use the existing visual
linking interface to link a transmitter to an eligible asset and save. The demo
instrument window lets you change readings or press DATA; Capture (Ctrl+M)
returns the linked simulated transmitter's latest value.

The module stores its settings in Open ERP's per-user
`%LOCALAPPDATA%\Open ERP\module-data\mitutoyo-u-wave\links.json`. The standalone
hardware window's `%LOCALAPPDATA%\UWaveAccessory\links.json` is separate and is not
automatically migrated.

## Download a tester build

Experimental tester builds are published on this repository's
[Releases page](https://github.com/tjd10684-bit/U-wave-module/releases) as
`mitutoyo-u-wave-<version>.zip` with a `SHA256SUMS.txt` file. They need an Open ERP
build that has the measurement-module host (0.2.11 or later). Check the download,
then in Open ERP choose **Settings > Measurement Devices... > Add Module...** and
select the zip:

```powershell
Get-FileHash .\mitutoyo-u-wave-0.1.0.zip -Algorithm SHA256   # compare with SHA256SUMS.txt
```

Only install modules from publishers you trust: the package is not code-signed, so
Open ERP asks you to confirm the publisher. The simulator was tested; a physical
receiver and transmitter have not been, so treat results as a preview and report
what you see.

## On the hardware computer

Start without `--demo` to inspect the actual receiver:

```powershell
.\.venv\Scripts\python.exe -m uwave_accessory.setup_window
```

This route requires the manufacturer's working **virtual COM driver**. Direct
USB support in U-WAVEPAK alone is not sufficient. Close legacy U-WAVEPAK Setup,
Data I/F and any other port owner before scanning. Select the receiver's actual
COM port, then its known Group ID (or Auto), and **Scan Receiver**. The scan opens
and closes the port; it does not automate or read the U-WAVEPAK window, modify
registrations, change modes or reset the hardware. Read Values also opens and
closes the port; Identify and Link All keep it open until they finish. Whether
the receiver forwards a Button driven DATA press over the virtual COM port, which
Identify relies on for those transmitters, is still to be confirmed.

The standalone hardware window has no ERP assets. In the helper module,
**Open Setup...** receives the assets supplied by Open ERP and uses this same
visual linking interface. Capture re-identifies a linked transmitter by Device
ID and follows its current channel before requesting a reading. The simulated
path and module integration are tested; real receiver/transmitter behavior is
not yet verified. Do not mistake a saved visual link for a verified hardware
connection.

Start with the checks in [HANDOFF.md](HANDOFF.md) and
[VALIDATION_PLAN.md](VALIDATION_PLAN.md). Bluetooth, mixed receivers, paired
capture and guaranteed fresh/simultaneous measurements are not supported here.

## Package layout

| Module | Responsibility |
| --- | --- |
| [protocol.py](src/uwave_accessory/protocol.py) | ASCII packet framing and DT/ST/TI/RI decoding; DR/IR requests |
| [receiver.py](src/uwave_accessory/receiver.py) | Receiver/group discovery, transmitter listing, single-channel latest-value requests and listening for unsolicited packets |
| [serial_transport.py](src/uwave_accessory/serial_transport.py) | Optional pyserial connection, 57600 baud, 8N1, RTS/CTS |
| [links.py](src/uwave_accessory/links.py) | Asset UUID to transmitter Device ID links, scan checks and atomic JSON storage |
| [setup_window.py](src/uwave_accessory/setup_window.py) | Tkinter visual setup, value reading, automated identification and the demo launcher |
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

The second route does not pair with the U-WAVE-R receiver. Mixed operation is
unverified and must be tested. In both documented event-driven routes, a request
retrieves a latest stored reading; it is not a promise of a fresh, simultaneous
measurement at the instant the pedal is pressed.

## Scope and publication

This public repository contains original accessory code, synthetic fixtures and
the agreed interface documentation. It does not contain private ERP source or
internal integration patches, real device identities, shop settings, credentials,
or copies of manufacturer manuals/software.

Hardware selection, licensing and driver distribution remain open. Open ERP
installs measurement modules as separate helper programs under
[the SDK's `PROTOCOL.md`](https://github.com/tjd10684-bit/Open-ERP-Module-SDK/blob/main/PROTOCOL.md);
the U-WAVE helper package is experimental.
The contract and simulator tests do not establish working physical U-WAVE
hardware support.
