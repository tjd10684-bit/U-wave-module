# Measurement accessory host contract, version 1

Agreed 2026-11-16. This describes the initial ERP-facing contract, not working
U-WAVE hardware support. It supersedes earlier proposals for simultaneous or
two-instrument captures in this repository. Those remain future work.

Separately installed measurement modules now run as helper programs under the
contract in [`sdk/PROTOCOL.md`](sdk/PROTOCOL.md). Open ERP's module host
registers the provider described below on their behalf, so the operator
workflow and the host's reading-acceptance rules here apply to module readings
too.

## Initial scope and operator workflow

- One selected Metrology asset per characteristic. Indirect inputs A and B use
  that same instrument in two separate capture actions, with repositioning
  between them. The host retains its existing absolute-difference calculation.
- The accessory owns the editable asset-UUID-to-transmitter mapping. Moving a
  transmitter requires updating that mapping; the host never treats transmitter
  identity as permanent asset identity.
- The accessory supplies a setup window for the host's **Measurement Devices**
  settings action. The host supplies eligible equipment choices (asset UUID,
  readable tag, name and category); the accessory manages connection settings,
  discovery, mapping verification and source rebinding.
- With a registered provider, **Capture (Ctrl+M)** is the default each app
  session. The input mode is not saved. A pedal may send a complete Ctrl+M
  press/release to the active Inspection view, not an arbitrary Enter.
- **Gauge button** mode retains ordinary HID/keyboard entry. No native request
  is made in that mode. With no provider registered, the host exposes no native
  capture controls and ordinary entry continues to work.
- Direct capture evaluates one value. Indirect capture obtains A, then B, and
  evaluates only the complete pair. GO/NO-GO remains a manual decision.
- The timeout is five seconds per request. A failed/timed-out B discards A too;
  start the pair again. Holding Ctrl+M must not capture the next input.
- Native Capture fields do not accept HID entry or Enter submissions. Disable
  vendor keyboard output while native collection is in use, to avoid typing
  into unrelated controls or applications. The ERP cannot control a vendor's
  global keyboard-output setting.

## Provider registration

The initial integration seam is in-process Python. The shared
`qms_common.measurement_accessory` API exposes `register_accessory(provider,
configure)` and `unregister_accessory(provider)`. Register on the UI thread
before constructing the host's Inspection screens and menus. Only one selected
provider is registered at a time; it may internally manage multiple transmitters
and transport routes.

Provider declarations:

| Member | Required meaning |
| --- | --- |
| `api_version` | `1`; incompatible versions are rejected |
| `accessory_id` | Nonempty identity of the accessory implementation |
| `name` | Nonempty operator-facing name |
| `acquisition_mode` | `latest` or `fresh`; advertise only a verified capability |
| `capture(request)` | Return `concurrent.futures.Future[Reading]` promptly |
| `cancel(capture_id)` | Return promptly; discard the request and its late responses |

`configure(parent, equipment)` opens the accessory-owned setup window on the UI
thread and returns when setup closes. Equipment is a tuple of `Equipment`
records with `asset_id`, `tag`, `name` and `category`. Do not modify the host's
asset inventory. The host cancels captures and discards partial pairs before
opening setup.

The accessory now implements `uwave_accessory.setup_window.configure(parent,
equipment)` without importing the ERP. It lists the supplied assets on the
right and receiver-discovered transmitters on the left. For part-specific setup,
the requested host integration supplies each eligible assigned asset once,
including unsaved assignments. Optional `used_by` balloon labels are displayed;
equipment without that field remains accepted. This part-filtered handoff is an
integration requirement, not a claim that every host checkout implements it.
The general settings path may supply the full eligible inventory; an explicitly
empty part list must not be replaced with that inventory.

Do transport I/O off the UI thread. Complete the future with a `Reading`, or
raise `AccessoryError` through the future for connection/protocol failures.
Never call Tk controls from a worker. Cancellation must release the accessory's
own pending-request state even if the underlying I/O cannot be interrupted.

This in-process hook is the host's internal seam. A separately installed module
does not import Open ERP: it is a helper program that speaks
[`sdk/PROTOCOL.md`](sdk/PROTOCOL.md), and Open ERP's module host adapts it to
this hook. No driver or vendor DLL is supplied by this contract. The experimental
U-WAVE helper wraps the accessory's protocol/discovery client and setup window;
physical hardware behavior remains unverified.

## Capture request

The host constructs a `CaptureRequest`:

| Field | Meaning |
| --- | --- |
| `capture_id` | Unique opaque request ID; echo exactly |
| `asset_id` | Operator-selected Metrology asset UUID; resolve using current mapping |
| `units` | Explicit `mm` or `in`; never infer from the numeric value |
| `input_name` | `measurement`, `a` or `b`; each requests one reading |
| `requested_at` | Timezone-aware PC request time |
| `timeout_seconds` | `5.0` |

Resolve and verify the source for that asset, not the first channel that
responds. Report missing/ambiguous mappings, disconnected sources and unsupported
capture modes explicitly. Receiver/group/channel and COM port are addresses,
not permanent instrument identities. Revalidate mapping after reconnect or
rebinding.

## Reading response

Return one `Reading` per request:

| Field | Meaning |
| --- | --- |
| `capture_id`, `asset_id` | Exact requested identities |
| `value` | Finite numeric value, not a string, bool, missing-value zero, NaN or infinity |
| `units` | Actual transmitted units, `mm` or `in`; no silent conversion |
| `source_id` | Stable, nonempty, transport-qualified source identity; never arrival order |
| `received_at` | Timezone-aware PC receipt time of this request's transport response |
| `acquisition_mode` | Same `latest`/`fresh` declaration as the provider |
| `status` | `ok` for a usable reading; any other status blocks acceptance |
| `message` | Operator-readable explanation for errors |
| `sampled_at` | Optional timezone-aware device sample time, only if actually supplied |

A status-only response may have `value=None`; it must have non-`ok` status.
Never parse status packets as numbers. Qualify source identities so equal
channel numbers on different transports cannot collide. A and B must report
the same source as well as the same asset.

`received_at` describes the transport response, not the physical measurement.
The host rejects a receipt timestamp preceding the request or in the future.
Do not stamp an old software-cache entry with a new receipt time. Legacy
event-driven requests can legitimately return the receiver's latest cached
physical measurement; the accessory must declare `latest` and verify the
connection/status according to hardware capabilities. It must not claim a fresh
or synchronized sample. An unchanged numeric value is allowed and is not, on
its own, proof of stale data.

The accessory must correlate responses to the correct request. Do not assign a
timed-out packet to a newer request merely because the newer one is waiting.
Protocol parsing, stream fragmentation, resynchronization and reconnect policy
belong to the accessory. Codec and simulated stream behavior have tests; the
current client's pre-request drain does not prevent an old reply arriving after
the drain. That correlation gap and reconnection behavior require resolution
before claiming a working host capture provider.

## Host acceptance and persistence

The host validates response shape, capture/asset identities, source, status,
finite value, units, timing and acquisition declaration. It rejects late,
cancelled and mismatched responses, ignores repeat actions while waiting, and
discards captures if the job, part, characteristic, selected asset, input mode
or visible Inspection context changes. Input from another application or hidden
inspection tab cannot trigger Ctrl+M capture.

Native partial captures are not auto-saved or recovered from session drafts.
Errors identify the affected asset/source; no partial or failed capture is
submitted as a measurement. A completed numeric reading still goes through the
host's normal tolerance decision and applicable asset/calibration checks.

Persistence is unchanged: the measured value, selected asset UUID and existing
calibration evidence. No transmitter binding or capture metadata is added to
Metrology or the job workbook. In Process results remain temporary.

## Validation boundary

Host-side simulations cover the software contract, timeout/cancellation,
duplicate keypresses, separate A/B actions, and unchanged recording behavior.
They do not validate Mitutoyo protocol parsing, physical freshness, driver
compatibility, mixed transports or a two-instrument correction formula. Those
remain accessory/hardware work under the validation plan.
