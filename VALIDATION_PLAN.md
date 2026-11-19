# Validation plan

Updated 2026-11-18. Automated tests exercise the implemented software with
synthetic devices, serial loopback and Tkinter. A case listed below is not
automatically covered. Basic USB plus BW-bridge operation has now been exercised
on one workstation; this is not a general production qualification.

Multi-receiver 0.2.0 focused result: **60 passed, no skips** using
`python -m pytest tests\test_links.py tests\test_module.py tests\test_setup_window.py -q -rs`.
The frozen helper passed SDK `host_check` and repeated real-hardware Capture
requests for assets on both receiver ports within one process. A disconnected
Bluetooth instrument was rejected, then captured after being awakened. The
owner also confirmed both readings in the installed setup window; saved routing
and installed executable identity were checked. Pre-commit full-suite validation
then passed: **130 tests, no skips**, using `python -m pytest tests -q -rs`.

Release 0.2.0 software result (2026-11-19): after the pre-release review fixes
(per-receiver link status, "No data yet" not reported as a failure) the full
suite passed **131 tests, no skips** on Windows with Python 3.12.10. The fixes
change only setup-window display; the hardware checks above were not repeated.

Run the complete accessory suite from the checkout:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -rs
```

Install with the README's `.[serial,test]` extra. Check reported skips: a machine
without Tkinter/display access cannot verify the GUI, and missing pyserial skips
loopback tests. No passing software test establishes physical freshness or radio
timing.

Pre-commit software result (2026-11-16): **92 passed, no skips** on Windows with
Python 3.12.10, pytest 9.2.0 and pyserial 3.5. `python -m pip check` found no
broken requirements, and the installed `uwave-setup --help` launcher succeeded.
This result covers synthetic/loopback/GUI tests only, not a physical receiver.

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
The version 1 contract is now defined, but the U-WAVE capture provider and
part-specific host asset handoff are not implemented/verified by this repository.
Its setup callback only displays the equipment it is given.

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

### Implemented software coverage

| Area | Evidence and limits |
| --- | --- |
| [Packet codec](tests/test_protocol.py) | Literal DT/ST/TI/RI fixtures, DR/IR field ordering, malformed/unit rejection, fragmented and concatenated stream reads |
| [Receiver client](tests/test_receiver.py) | Requested-channel routing, ST failures, TI changes, discovery, wrong-group errors and timeouts; late data drained before the next request; unsolicited packets passed to a listener, malformed ones skipped |
| [Serial transport](tests/test_serial_transport.py) | Synthetic loopback reads/timeouts, unavailable-port errors and port ordering; no vendor driver exercised |
| [Links](tests/test_links.py) | One-to-one mapping, Device ID rather than channel identity, schema 1 migration, multi-receiver persistence, unresolved-route refusal and invalid-file rejection |
| [Module capture](tests/test_module.py) | Selected-asset routing when ports share group/channel, unavailable unrelated receiver, wrong transmitter refusal, disabled/unresolved receiver errors and existing capture safeguards |
| [Setup GUI](tests/test_setup_window.py) | Left/right asset layout, deduplication, optional balloon labels, drag/click linking, unlinking, missing-source cards, save/discard, failed rescans and closing while scanning; Read Values change reporting; Identify and Link All by simulated reading change or DATA press, ambiguous or linked-elsewhere responders, answers queued before an asset was asked for, Skip, hand links, timeouts and closing mid-identify |
| [Look and feel](tests/test_theme.py) | Every text colour at least 4.5:1 on every surface in light and dark; mode choice (explicit, saved Open ERP preference with or without a byte order mark, Open ERP's default, Windows, light); the host's colours reproduce the built-in palette, missing or malformed colours fall back; windows open in both modes, with a host palette and with `auto`; the module passes the host theme and tolerates an SDK without one |

Multi-receiver GUI cases also cover enabling/reading both ports, saving routes,
partial failure without stale successful values, duplicate Device IDs across
ports, selected-port identification and retaining links when disabling a receiver.

Still open: replies arriving after a new request begins, physical sample age,
real connection/reconnection guarantees, host capture cancellation/pedal flow,
multi-instrument completeness, approved unit conversion and mixed-transport
stress/reconnection behavior.
The simulator assumes inclusive IR searches; it cannot prove that behavior.

## Stage 3: single legacy receiver on real hardware

1. Verify the VCP driver required by the implemented serial transport. Direct USB
   working in U-WAVEPAK is not sufficient; direct-USB binding is not implemented.
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

### First hardware-session checklist

- Run the software suite and demo first using a fresh checkout/environment.
- Record model families, firmware, OS and driver/vendor application versions.
  Keep actual serials, COM assignments and logs out of the public repository.
- Scan with the known group first. Compare all registered identities/channels,
  including disconnected registrations and the first/last occupied channels.
- Verify ascending IR search inclusivity, ST 51 search termination, wrong-group
  ST 50 correlation and the Auto group scan.
- Measure response latency against the current one-second discovery timeout;
  test a disconnected port, an occupied port and a device changing state mid-scan.
- Check that cancelling/closing setup releases its port after the scan exits
  and that failed rescans never leave earlier availability marked ready.
- Read Values: compare displayed values and units with the instruments; time the
  DR requests with several Event driven transmitters connected.
- Identify/Link All: confirm the receiver forwards a Button driven DATA press to
  the PC over the VCP as a DT packet, and whether a DATA press in Event driven mode
  sends anything. Check noisy or drifting instruments (no change threshold is
  applied) and that the port, held for the whole session, is released on Stop
  and on closing the window.
- Look and feel: open setup with Open ERP in light and in dark mode and compare
  fonts, field and button colours and the title bar. Until the host sends its
  theme, switch Open ERP's mode, reopen setup and confirm the window follows it.
- Do not use the low-level client's buffer drain as proof of late-response
  isolation. Establish and test a safe correlation/recovery strategy before
  connecting captures to real inspection records.

Do not change Group ID, Band ID, initialization state, or unrelated instruments
just to make an isolated test pass.

## Stage 4: paired capture and pedal

This is future two-instrument scope. Version 1 indirect capture uses two actions
on the same instrument; this repository does not yet implement its host provider.

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
- Verify selected-asset captures on each route while the other is unavailable.
- A single Capture returning a pair spanning both transports remains future
  scope; apply completeness and identity checks when that workflow is approved.

## Supported-configuration record

| Configuration exercised on 2026-11-18 | Evidence | Still unverified |
| --- | --- | --- |
| Windows 11 Pro x64; USB U-WAVE-R with Mitutoyo VCP 2.12.28; Bluetooth U-WAVE through U-WAVEPAK-BW 1.0.5; Event driven; module 0.2.0 | Discovery, setup Read Values, repeated one-asset captures on both ports through the packaged helper, exact asset/source/unit response checks | Exact Bluetooth model/firmware matrix, restart/sleep recovery, sustained load, late replies, physical freshness, synchronized or paired capture, full ERP inspection/pedal acceptance |

When evidence exists, maintain a small table containing:

- Instrument/transmitter/receiver model families and relevant firmware.
- OS, vendor driver/application versions, and selected transport.
- Requested-value and push-input capabilities actually demonstrated.
- Known limitations, reproducible verification procedure, and date.
- The software revision and tests associated with the result.

Use model families, not real equipment identities or operator/customer data.
Documentation, synthetic tests and a working demo do not constitute hardware
validation.
