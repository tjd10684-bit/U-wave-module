# Validation plan

No tests below have been implemented or passed merely by being listed here.
Record results by exact supported hardware/software combination when work starts.

## Stage 1: establish the host contract

Use an authorized private host checkout without copying its internals into this
repository.

- Confirm direct and indirect input behavior, equipment assignment, calculation,
  units, and persistence before changing them.
- Keep ordinary HID/keyboard entry usable with the accessory absent or disabled.
- Exercise the smallest proposed accessory contract with simulated readings.
- Keep acceptance, failure, and cancellation visible in the inspection workflow.

The first implementation should preserve the host's existing intended behavior;
the correct height/indicator formula is a separate requirement to confirm.

## Stage 2: focused software cases without hardware

Use synthetic identities and packets only.

| Case | Required outcome |
| --- | --- |
| Two responses arrive in reversed order | Correct equipment-to-role assignment and exactly one complete capture |
| Only one required channel responds | Zero accepted complete captures; explicit missing-source error |
| Unexpected channel or changed source binding | Do not substitute it for a required instrument |
| Duplicate response or repeated pedal event | No duplicate accepted measurement |
| Response arrives after timeout/cancellation | It must not populate a later capture |
| Disconnected, no-data, battery, or other status packet | Parsed as status; blocking/warning policy is explicit, never interpreted as a reading |
| Fragmented/concatenated transport reads | Complete packets parsed without mixing boundaries |
| Malformed packet or unknown unit | Explicit validation failure, not a default value |
| Mixed units | Explicit approved conversion or rejection; never silent arithmetic |
| Accessory unavailable | Clear error for native capture; basic HID path still works |
| Two transports use the same channel number | Transport/source identity prevents cross-routing |

Add tests for implemented behavior, not for hypothetical abstractions that are
not needed by the initial integration.

## Stage 3: single legacy receiver on real hardware

1. Verify the direct USB or VCP driver chosen for the implementation.
2. Establish the normal vendor-tool baseline before native acquisition.
3. Close software competing for that receiver.
4. Read configuration and verify the intended source identity/channel.
5. Exercise the chosen measurement mode and compare received values and units to
   the instrument display at multiple known positions.
6. Test repeated collection with the instrument unchanged, then with a changed
   reading. Record how clear-after-output and mode changes affect availability.
7. Disconnect/reconnect and test restart, power interruption, and sleep recovery.
   No pre-disconnection cached value may be silently represented as a new sample.
8. Confirm native collection does not also create duplicate keyboard input.

Do not change Group ID, Band ID, initialization state, or unrelated instruments
just to make an isolated test pass.

## Stage 4: paired capture and pedal

- Verify the physical reference, sign, offset, and units against known dimensions.
- Associate each physical instrument with its required host role.
- Hold the measurement arrangement stable while validating the latest-value
  collection approach.
- Verify that one ordinary pedal action produces exactly one completed capture
  only when both required readings are valid.
- Test missing instrument, wrong instrument, repeated press, held pedal,
  cancellation, and out-of-order responses.
- Confirm that application focus changes cannot send measurements to an
  unintended document or submit the wrong inspection step.
- Confirm error feedback identifies the failed instrument and leaves the
  inspection record uncommitted.

Before implementation, agree a timeout and the acceptable age/sampling
relationship of the pair. Do not invent a numerical freshness guarantee the
hardware cannot measure. An unchanged reading and an unreachable instrument are
different situations even if neither has just produced a new value.

## Stage 5: Bluetooth and mixed operation

- Record exact TCB/TMB model, connection unit, BW version, Bluetooth adapter, and
  OS used. Keep unit-specific serials and local COM values outside public results.
- Verify the virtual-COM request protocol, channel mapping, and required bridge
  startup order.
- Verify Event driven updates, unchanged readings, and first data after reconnect.
- Keep BW running while preventing duplicate direct keyboard output.
- Independently test legacy/Bluetooth coexistence before claiming mixed support.
- Capture a pair spanning both transports, with one route delayed or unavailable,
  and apply the same completeness and identity checks.

## Supported-configuration record

When evidence exists, maintain a small table containing:

- Instrument/transmitter/receiver model families and relevant firmware.
- OS, vendor driver/application versions, and selected transport.
- Requested-value and push-input capabilities actually demonstrated.
- Known limitations, reproducible verification procedure, and date.
- The software revision and tests associated with the result.

Use model families, not real equipment identities or operator/customer data.
Documentation-only preparation does not constitute hardware validation.
