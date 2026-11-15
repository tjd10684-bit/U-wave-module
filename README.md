# U-WAVE accessory for Open ERP

An optional measurement-data collection accessory for Open ERP's inspection
workflow.

**Status: documentation and design handoff only, 2026-11-15.** There is no working
integration, installer, device driver, or automated test suite in this repository
yet. The proposed behavior below is not a claim of implemented functionality.

## Goal

Keep ordinary HID/keyboard-style gauge input working as it does today. Users who
need instrument identification, software-requested readings, or multi-gauge
capture can install a data-collection accessory for their chosen system.

U-WAVE is intended to be the first accessory. Other manufacturers should be
supported by separate accessories behind a common inspection interface, rather
than by adding vendor-specific logic throughout Inspection.

The motivating use case is a height gauge with an indicator mounted as a fine
correction. One pedal action should collect the intended pair and pass identified
readings to the host's indirect-measurement workflow. The calculation, sign,
reference offset, and units must be confirmed for the physical arrangement.

## Read in this order

| Document | Purpose |
| --- | --- |
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

This is a public-safe handoff authorized by the project owner. It contains original
summaries and links, not private ERP source, private code-derived implementation
details, device serial numbers, local machine paths, credentials, or copies of
manufacturer manuals/software.

Hardware selection, package format, programming language, host extension API,
licensing, and distribution are still decisions to make. Do not infer that Open
ERP already exposes the proposed accessory API.
