# Project handoff

Updated 2026-11-16 after implementing and testing the accessory groundwork.
Start with [README.md](README.md), then use this document to resume without the
original chat or workstation.

## What the owner wants

- An optional U-WAVE data-collection accessory that can fit into Open ERP's
  inspection module.
- Preserve existing HID/keyboard-style input for users who need nothing more.
- Reuse the host's existing indirect-measurement feature rather than put
  inspection calculations into every manufacturer accessory.
- Associate capture with the equipment required by the current inspection step:
  one instrument for a direct measurement, or an identified pair where needed.
- One foot-pedal action for a multi-gauge capture, without trusting the order of
  wireless arrivals.
- Accommodate a Bluetooth-equipped caliper as well as the original U-WAVE-R path,
  if the exact hardware and software combination is verified.
- Use separate accessories for other manufacturers' data-collection protocols.
- Continue development from multiple machines and sessions using this repository
  as the durable context, not machine-local chat history.

The initial design discussion deferred implementation; subsequent work authorized
the host-neutral Python package and visual setup window. The
[version 1 contract](HOST_CONTRACT.md) narrows the initial workflow to one
instrument per characteristic, including separate A/B actions on that same
instrument. Two-instrument correction and Bluetooth remain future work.

## Current implementation and next handoff

- The package parses DT/ST/TI/RI packets, encodes DR/IR requests and provides
  single-channel latest-value requests and transmitter discovery.
- A pyserial transport implements the documented legacy virtual-COM route.
  Manufacturer drivers remain external; the direct USB route is not implemented.
- The setup GUI accepts assets supplied by the ERP on the right, scans registered
  transmitters on the left, and supports dragging or click-then-click linking.
- One-to-one links use asset UUID and transmitter Device ID. Group/channel are
  last-seen addresses, not identities. Settings are local to the Windows user
  at `%LOCALAPPDATA%\UWaveAccessory\links.json`, not shared ERP inventory.
- A simulator, serial loopback tests and Tkinter tests exercise software without
  physical equipment. The demo has sample assets and uses a separate settings
  file in the user's temporary folder.
- The ERP capture provider and startup loading are not implemented here.
  The host must pass this part's eligible assigned assets (including unsaved
  choices), deduplicated by UUID, with optional `used_by` balloon labels.
  An empty part list must stay empty, not expand to the full shop inventory.
  Detailed private host changes were handed to the owning session and are not
  copied into this repository.

The next task is **hardware verification**, not production inspection. No
physical receiver or instrument was exercised by this implementation session.
Use the [README commands](README.md#install-and-try-the-visual-demo) to recreate
the environment; do not copy this machine's virtual environment or settings.

## Evidence from the initial setup session

The following are observations, not a formal acceptance test:

- A Windows workstation had U-WAVEPAK v1.022B installed.
- The U-WAVE-R was accessible through the direct USB route.
- A real transmitter was connected in Button driven mode. The owner reported
  measurement packets updating in the Setup receive area.
- An accidental all-zero registration was removed, leaving the intended
  transmitter connected.
- The documented Data I/F-to-text-application procedure was explained. No
  repeatable, recorded end-to-end ERP acceptance test was performed.
- The workstation's virtual COM device reported a driver error while direct USB
  worked. The new serial transport still needs its driver installation verified;
  this is not evidence that the direct USB route is broken.
- The owner reports a separate caliper with a U-WAVE Bluetooth module. Its model
  and software version were not identified or tested in this session.

Do not carry device identities, COM numbers, or radio settings from that
workstation into a new installation. Discover and confirm them locally.

## Agreed direction versus proposals

**Direction agreed with the owner**

- Optional manufacturer accessories; no loss of the basic HID path.
- U-WAVE first, with a common inspection-facing boundary that could admit other
  collection systems.
- Equipment-aware capture, not blind dependence on input arrival order.
- Public-safe documentation in this repository.
- A visual accessory-owned linking window using direct receiver queries rather
  than scraping U-WAVEPAK or reading its undocumented backup format.
- Python 3.12+, optional pyserial, local settings and a hardware-free demo.

**Design proposals, not yet implemented or finalized**

- A production-ready capture provider satisfying the agreed structured-reading
  contract rather than emitting keystrokes.
- Multi-instrument capture; it is not the version 1 same-instrument A/B workflow.
- A programmable PC-connected pedal invoking a capture action.
- One Mitutoyo accessory containing separate USB-receiver and Bluetooth backends.
- Capability declarations for push input, requested cached values, and any
  genuinely supported fresh-trigger behavior.

## Important corrections to avoid repeating

1. The instruments do not need USB cables to the PC. The legacy receiver uses
   USB; its instruments communicate wirelessly through their transmitters.
2. Legacy U-WAVEPAK and U-WAVEPAK-BW are different paths. For native legacy
   acquisition, the collector would use the receiver driver/protocol rather than
   automate the U-WAVEPAK GUI. For the documented Bluetooth route, U-WAVEPAK-BW
   remains running as a virtual-COM bridge.
3. A foot switch connected to a transmitter is not the same as a PC-side capture
   trigger. It does not by itself establish an ordered two-instrument transaction.
4. Requesting data in Event driven mode retrieves cached values. It does not
   remotely press DATA on both instruments at exactly the same moment.
5. Ordering returned channels is not enough: a missing channel can be omitted by
   the legacy all-channel request. Validate the expected set of instruments.
6. Same-brand Bluetooth does not mean compatibility with U-WAVE-R.
7. The Bluetooth manual contains a USB-ITPAK mixed-system limitation. It does not
   establish that a custom collector will or will not work with both routes.
8. An indicator mounted on a height gauge does not establish the correct formula.
   Verify zeroing, sign, reference offset, units, and the host calculation.

## Resume on another machine

1. Clone this repository through the developer's normal authenticated Git
   workflow. No local path or credential is required by these notes.
2. Create a fresh Python environment and run the test/demo commands in
   [README.md](README.md). Check for skips: GUI tests require Tkinter.
3. Obtain a separately authorized checkout of the private host application.
   Inspect its current inspection input, equipment assignment, calculation,
   persistence, packaging, and extension mechanisms. Do not copy private source
   or private implementation details into this public repository.
4. Inventory the actual transmitter, receiver, instrument, and pedal models.
   Record sensitive identities and site configuration outside the public repo.
5. Obtain the vendor software/drivers from the official sources in
   [REFERENCES.md](REFERENCES.md); follow the vendor's licensing and installation
   requirements. Do not copy an unrelated application's Python environment or
   local research tooling from the earlier session.
6. Establish the vendor-tool baseline, then close legacy U-WAVEPAK and Data I/F.
   Verify that the receiver has a working VCP driver and select that port in the
   standalone window. Do not pick a COM port just because it is first in the list.
7. Prefer the receiver's known Group ID for the first scan. Compare receiver and
   transmitter identities, channels, modes and connected/disconnected states
   against U-WAVEPAK's recorded setup. Rescan after reconnecting.
8. Confirm ascending IR searches include the requested starting channel; verify
   the Auto group's wrong-group ST 50 behavior and end-of-search ST 51. The scan
   uses one second per request, not one second for the whole scan.
9. Exercise latest-value requests separately before connecting a capture provider.
   Verify unchanged readings, missing data, status, units, reconnects and late
   replies. A PC response timestamp is not the physical measurement time.
10. Perform the relevant [validation checks](VALIDATION_PLAN.md). Do not enable
    production capture until request correlation, reconnection and source
    verification are sound. Bluetooth/mixed operation needs separate work.

At each handoff, update the supported model/version matrix, decisions, unresolved
questions, and exact verified development commands in the repository. Keep local
serial numbers, COM assignments, operator data, and logs out of committed examples.

## Open decisions

- Actual height gauge, indicator, Bluetooth module, connection units, and
  compatible event-driven behavior.
- Whether the existing indirect calculation matches the physical fine-correction
  arrangement.
- Capture provider, startup registration/loader and frozen-app distribution.
  The initial API is in-process Python; a helper process remains a later option.
- Installer format, supported hardware/OS matrix, license and driver
  redistribution policy. Python and the initial VCP transport are implemented.
- Precise Bluetooth virtual-COM command compatibility; the setup guide documents
  higher-level access but is not a complete command specification.
- The host timeout is five seconds; the setup scan uses one second per request.
  Validate those limits and establish stable-reading/reconnection policy.
- Request correlation: draining buffered input cannot identify an old reply that
  arrives after the next request begins. IR search replies also cannot be
  distinguished from some unsolicited TI changes. These are unresolved limits,
  not guarantees supplied by the simulator.
- Future multi-instrument sampling relationship and transport-qualified source
  identity when more than one receiver/transport is supported.
- Pedal model, trigger binding, duplicate-trigger handling, and supported
  application-focus behavior.
- Whether mixed Bluetooth and U-WAVE-R operation is supported on the target PCs.
