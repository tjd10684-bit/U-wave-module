# Project handoff

Prepared from the setup and design discussion ending 2026-11-15.
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

The owner explicitly deferred implementation during the design discussion and
then requested this documentation bundle. This handoff does not authorize a
specific unresolved hardware purchase, packaging choice, or host API design.

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
  worked. A future serial implementation must verify its own driver installation;
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

**Design proposals, not yet implemented or finalized**

- Structured readings instead of simulated keystrokes for the native accessory.
- A capture coordinator that collects and validates the requested pair before
  handing it to Inspection.
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
2. Read these documents before selecting libraries or writing device code.
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
6. Choose one transport for an initial proof of concept. Legacy U-WAVE-R is a
   reasonable candidate because its basic connection was observed, but no
   transport or programming language has been committed to.
7. Agree the minimum host/accessory contract and capture behavior. Validate it
   with simulated devices before relying on hardware.
8. Perform the relevant [validation checks](VALIDATION_PLAN.md), then expand to
   Bluetooth and mixed capture only with separate evidence.

At each handoff, update the supported model/version matrix, decisions, unresolved
questions, and exact verified development commands in the repository. Keep local
serial numbers, COM assignments, operator data, and logs out of committed examples.

## Open decisions

- Actual height gauge, indicator, Bluetooth module, connection units, and
  compatible event-driven behavior.
- Whether the existing indirect calculation matches the physical fine-correction
  arrangement.
- Host extension API and whether acquisition runs in-process or in a helper.
- Programming language, package/installer format, supported OS versions, license,
  and driver redistribution policy.
- Legacy direct USB versus virtual COM for the first implementation.
- Precise Bluetooth virtual-COM command compatibility; the setup guide documents
  higher-level access but is not a complete command specification.
- Timeout, stable-reading policy, reconnection behavior, user feedback, and
  whether a requested pair must have a defined sampling relationship.
- Pedal model, trigger binding, duplicate-trigger handling, and supported
  application-focus behavior.
- Whether mixed Bluetooth and U-WAVE-R operation is supported on the target PCs.
