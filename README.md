# U-WAVE accessory for Open ERP

An optional measurement-data collection accessory for Open ERP's inspection
workflow.

**Status: experimental accessory groundwork, 2026-11-16.** The legacy receiver
protocol, virtual-COM transport, simulated receiver, visual asset-linking window
and automated tests are implemented. They have not been validated on physical
hardware. The ERP capture provider, automatic loading and installer are not yet
implemented.

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
five-second host timeout. The protocol client can request a channel's latest
stored value, but it does not yet deliver captures into the ERP.

## Install and try the visual demo

Use Python 3.12 or newer with Tkinter. From a checkout on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[serial,test]"
.\.venv\Scripts\python.exe -m pytest tests -q -rs
.\.venv\Scripts\python.exe -m uwave_accessory.setup_window --demo
```

The base package has no third-party runtime dependencies. The `serial` extra
adds pyserial; the `test` extra includes pytest and pyserial for loopback tests.
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

The standalone hardware window has no ERP assets. The host must call
`uwave_accessory.setup_window.configure(parent, equipment)` with its asset list.
The requested part-specific list includes unsaved assignments, deduplicated by
asset UUID; optional `used_by` balloon labels are displayed. Supplying this list
and registering a real capture provider remain host-integration work. Do not
mistake a saved visual link for a verified measurement connection.

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
| [tests](tests) | Protocol, request, loopback transport, mapping and GUI regression tests |

## Read in this order

| Document | Purpose |
| --- | --- |
| [HOST_CONTRACT.md](HOST_CONTRACT.md) | Agreed initial host API, single-instrument scope, mapping ownership and capture safeguards |
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

Hardware selection, accessory packaging, licensing and distribution remain open.
The initial host registration seam is Python; an external helper/installer is
not supplied. The contract does not establish working U-WAVE hardware support.
