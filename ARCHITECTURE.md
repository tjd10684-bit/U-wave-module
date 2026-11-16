# Accessory architecture and boundaries

The initial API is described in [HOST_CONTRACT.md](HOST_CONTRACT.md).
The host-neutral package implements protocol, VCP transport, discovery and the
visual setup window; the ERP capture provider is still missing. Broader
multi-instrument behavior below is a design boundary, not implemented support.

## Implemented setup path

```text
Host-supplied assets -> visual linking window <- IR/RI/TI receiver discovery
                                  |           <- DR latest values, forwarded DATA presses
                      local asset UUID -> Device ID links
```

The setup window does not query or change the ERP database. It displays the
supplied equipment, with optional balloon labels, and records one-to-one links.
The host remains responsible for supplying the current part's eligible assets.
Discovery runs off the Tk thread and closes the COM port after scanning. Each
scan invalidates previous availability; failure leaves links unverified.

To help the operator tell instruments apart, Read Values requests each Event
driven transmitter's latest value once per click; it opens and closes the port
like a scan. Identify and Link All hold the port in a worker thread, requesting
those values about once a second and listening for DATA presses that the
receiver forwards from Button driven transmitters. The first values read for
each asset are its baseline: a single transmitter whose value then changes, or
whose DATA button is pressed, is linked to it. Several responders, or one linked
elsewhere, link nothing. Answers that may belong to an earlier asset (received
before the current asset's baseline) are discarded. Scans, value reads and
identification take turns on the port through one process-wide lock, because
Windows opens a COM port exclusively. DR requests are answered from the
receiver's stored values, so reading does not wake transmitters.

Saved addresses can follow a Device ID to another channel. A capture provider
must revalidate the source and mode at acquisition time; a saved link or a green
setup card is not a substitute for live capture validation.

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

The version 1 contract leaves capture coordination with the host and mapping
with the accessory. Do not duplicate tolerance logic or inspection calculations
in transport implementations.

## Minimum information to discuss for the contract

The version 1 contract settles the initial fields; this checklist also guides
later extensions:

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

For a future two-instrument capture (not the initial same-instrument A/B flow):

1. Determine the required equipment roles from the active inspection step.
2. Resolve both identities and verify the needed capabilities.
3. Acquire the intended readings without using arrival order as identity.
4. Reject missing, mismatched, malformed, disconnected, or otherwise invalid
   results; show the operator which source failed.
5. Deliver one complete capture to the host, mapping the correct readings to its
   required inputs.

An accessory may receive results out of order. That must not change their roles.
A delayed result from an expired request must not become the next measurement.
The current request client cannot guarantee this: it drains buffered responses
before writing, but legacy packets contain no request ID. A reply arriving after
the drain can be mistaken for the new reply. Resolve that before production
capture integration.

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
- The host timeout is five seconds; setup discovery uses one second per request.
  Hardware response limits and stale-data policy still need validation.

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
- The development package uses setuptools and optional pyserial. Frozen-app
  loading and installer/driver distribution remain separate decisions.
- Keep connection settings, IDs, and other site-specific information outside
  committed examples.
- Provide synthetic protocol fixtures and simulated acquisition so most software
  development can happen without the physical instruments.
- Obtain vendor permission where redistribution requires it; do not bundle vendor
  installers, DLLs, or manuals merely because they can be downloaded.
