# Proposed accessory architecture

This is a design boundary, not an existing API or final implementation plan.
Use the smallest interface that satisfies the initial integration, and revise it
with evidence from the host and hardware.

## Preserve two input paths

```text
Existing HID/keyboard input ----------------------------> Inspection

Pedal / hotkey / capture action
        -> host capture coordinator
        -> selected manufacturer accessory
        -> transport(s) and assigned instruments
        -> identified, validated readings
        -> Inspection
```

Basic HID operation must not depend on optional manufacturer packages, drivers,
Bluetooth access, or the native accessory being enabled.

## Responsibilities

| Host / Inspection | Manufacturer accessory |
| --- | --- |
| Inspection step and required equipment roles | Discovery and connection through the vendor's supported interfaces |
| Equipment assignments and capture action | Resolve configured identities to current transport addresses |
| Complete-pair policy and operator feedback | Protocol decoding, status interpretation, and connection errors |
| Calculations, tolerance decisions, persistence | Readings with source identity, units, and known timing/status |
| Capture lifecycle and prevention of partial submissions | Advertise real acquisition capabilities and execute supported requests |

The exact ownership of the capture coordinator can be settled during host API
design. Do not duplicate tolerance logic or inspection calculations in every
transport implementation.

## Minimum information to discuss for the contract

This is a checklist, not a mandate to create these classes or fields verbatim:

- Accessory identity and capabilities.
- A stable instrument/transmitter identity plus its current connection address.
- A capture identifier to associate asynchronous results with the active request.
- Numeric reading, explicit units, and the instrument role it fulfills.
- Connection/measurement status, including errors that must block acceptance.
- Host receipt time and, only when the device actually provides it, device sample
  time. Host receipt time must not be presented as physical measurement time.
- Whether the result came from push input, a latest-value request, or a truly
  supported fresh-trigger operation.

Treat numeric precision and unit conversion deliberately when defining the API.
Do not silently infer inches versus millimeters from the value or input field.

## Identity and routing

An equipment record should refer to an intended source, not simply "the first
reading received." Resolve and confirm that source when connecting.

For legacy U-WAVE, requests address receiver/group/channel information, while
the transmitter's Device ID identifies the physical transmitter. A channel can
be reassigned and must not be mistaken for a permanent identity.

Bluetooth bridge rows also map to channels and can change after registration
edits. COM numbers can differ on another PC. Validate bindings at setup and after
reconnection rather than hard-code a workstation's enumeration.

For a two-instrument capture:

1. Determine the required equipment roles from the active inspection step.
2. Resolve both identities and verify the needed capabilities.
3. Acquire the intended readings without using arrival order as identity.
4. Reject missing, mismatched, malformed, disconnected, or otherwise invalid
   results; show the operator which source failed.
5. Deliver one complete capture to the host, mapping the correct readings to its
   required inputs.

An accessory may receive results out of order. That must not change their roles.
A delayed result from an expired request must not become the next measurement.

## Cached data, timing, and reconnection

The two documented Mitutoyo event-driven paths retain latest readings. They do
not promise synchronized physical sampling on the pedal event.

- An unchanged instrument may not send another value. A long time since receipt
  does not alone prove the measurement is invalid.
- Conversely, a cached value does not prove the instrument is still connected or
  was measured for the current part.
- Do not fabricate a fresh timestamp, use zero for missing data, or silently
  reuse a reading from a previous part.
- Establish a supported initial-reading and reconnection policy before accepting
  data. Invalidate assumptions after disconnect, mode changes, or source rebinding.
- Define what the operator must hold stable during capture and what guarantees
  the hardware cannot provide.
- Choose timeout and stale-data policies explicitly; they remain open decisions.

Do not describe a capture as "simultaneous" unless the hardware and tests justify
that term.

## Pedal and duplicate-input handling

The proposed PC pedal invokes the same explicit capture action as an on-screen
button or hotkey. It should not just send Enter into whatever window has focus.

Guard against held switches, repeated key events, concurrent captures, and late
responses so one physical action cannot silently record multiple results.

When native acquisition is active, avoid a second path typing the same values into
the host. For Bluetooth this may mean leaving U-WAVEPAK-BW running but disabling
its direct keyboard output; verify the precise settings during integration.
The legacy collector must not compete with U-WAVEPAK Data I/F for its receiver.

## Portability and optional installation

- Keep vendor-specific drivers and dependencies optional.
- Do not choose a package framework or dependency stack until the host extension
  and distribution requirements are understood.
- Keep connection settings, IDs, and other site-specific information outside
  committed examples.
- Provide synthetic protocol fixtures and simulated acquisition so most software
  development can happen without the physical instruments.
- Obtain vendor permission where redistribution requires it; do not bundle vendor
  installers, DLLs, or manuals merely because they can be downloaded.
