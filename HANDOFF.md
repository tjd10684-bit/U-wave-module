# Project handoff

Updated 2026-11-19: **0.2.0 is prepared for release** from `main` as a normal
release; the published record is added above this entry. Before release, a code
review of the multiple-receiver change led to two setup-window fixes: links are
judged against their own receiver, so a link on a receiver that failed to scan or
is not in use shows **Not checked** (grey) instead of "Transmitter not found" (red),
and a transmitter registered on several receivers is labelled as such; Read Values
no longer reports a normal "No data yet" reply as a failure. Full suite: **131
passed, no skips**. Capture behavior is unchanged.

Updated 2026-11-18: tester **0.2.0** adds multiple enabled
receiver ports, per-port groups and port-bound asset links. Scan Receivers and
Read Values cover all enabled receivers; partial failures are explicit.
Capture still reads one selected asset, opening only its bound port and
revalidating Device ID. Identify/Link All stay scoped to the selected receiver.
Schema 1 loads without modification; Save writes schema 2. Keep the pre-upgrade
settings backup for rollback to 0.1.1.

Validation this session: **60 focused tests passed, no skips** across links,
module and setup-window tests; `pip check` and frozen-helper `host_check` passed.
The packaged helper repeatedly captured from USB U-WAVE-R and Bluetooth through
U-WAVEPAK-BW 1.0.5 in the same process, without changing settings between captures.
A disconnected Bluetooth instrument was explicitly rejected until awakened.
The owner installed the tested package in Open ERP 0.2.12 and reported both
readings in setup; the installed executable hash and saved two-port routing were
verified. Shop identities, readings, backups and logs remain outside this repo.
Pre-commit full-suite validation also passed: **130 tests, no skips** using
`python -m pytest tests -q -rs`. That locally tested package was not published;
the released 0.2.0 is rebuilt from a clean clone.

Updated 2026-11-18: tester release **v0.1.1** (a normal release, marked latest) is published at
<https://github.com/tjd10684-bit/U-wave-module/releases/tag/v0.1.1> with
`mitutoyo-u-wave-0.1.1.zip` (10,931,899 bytes, SHA256
`2267f7e096af56b6f8c6c83213b607194725bf20933d63c89c794589d30dd0d0`) and an LF-terminated
`SHA256SUMS.txt`. It was built with `build_module.ps1` from a clean clone of commit `10f26a6`
(the `v0.1.1` tag) in a fresh virtual environment that installed the SDK from the public `v1.1.0`
tag: 117 tests passed and `host_check` passed on the frozen helper. The zip holds only
`module.toml`, `mitutoyo-u-wave.exe` and its `_internal` runtime; the only text hit for the owner's
name is the public `update_repository` value. Verified live with Open ERP's own update code: with
0.1.0 installed, 0.1.1 is found, downloaded, checksum-verified and accepted by `verify_package`;
with 0.1.1 installed there is no update; the anonymous `releases/latest` API returns v0.1.1 and an
independently downloaded zip matches the published checksum. Not tested: a real in-app update click
(needs a later 0.1.2) or physical receiver/transmitter.

Updated 2026-11-18: version **0.1.1** is the first build that can be updated by Open ERP itself. The
module opts in and its releases must meet a few rules.

- Opt-in is `update_repository = "tjd10684-bit/U-wave-module"` in `module/module.toml`. The shipped
  v0.1.0 does not have the line, so testers replace it by hand once with 0.1.1; from then on the
  module updates itself. A version bump touches `module/module.toml`, `module/uwave_module.py`
  (`version`), the hardcoded zip name in `build_module.ps1`, the README and this file.
- Open ERP only offers an update from the repository's **latest** release, so an update release must
  be a normal release. A draft or **pre-release** is ignored, which is why v0.1.0 (a pre-release)
  never triggers one. Tag it `v<major>.<minor>.<patch>` and attach `mitutoyo-u-wave-<version>.zip`
  and `SHA256SUMS.txt`. The packaged `module.toml` must keep the same id, publisher and
  `update_repository`, and its version must equal the tag.
- A real end-to-end test needs two published normal releases (for example 0.1.1 installed by hand,
  then 0.1.2 published). The packages are not code-signed; the checksum comes from the same release.
- Contract details are in the SDK's `PROTOCOL.md` ("Automatic updates") and the Open ERP
  `HANDOFF.md`.

Updated 2026-11-18: tester release **v0.1.0** (pre-release) of the `mitutoyo-u-wave`
module is published at
<https://github.com/tjd10684-bit/U-wave-module/releases/tag/v0.1.0> with
`mitutoyo-u-wave-0.1.0.zip` (10,932,344 bytes, SHA256
`c6a17bd87857b1632afbe917f48e29136f473ff2f7025506778469873ae618e0`) and `SHA256SUMS.txt`.
It was built with `build_module.ps1` from a clean clone of commit `075e1d6` in a fresh
virtual environment that installed the SDK from the public `v1.0.0` tag (117 tests
passed and the SDK `host_check` passed on the frozen helper). The `v0.1.0` tag points at
`fd53a2a`, which differs from the built commit only in README/HANDOFF text. The zip holds only
`module.toml`, `mitutoyo-u-wave.exe` and its `_internal` runtime; a scan found no
private paths or identities. Not tested: physical receiver/transmitter or VCP driver.
Rebuilding changes the zip bytes (timestamps), so publish the exact file you hash.

Updated 2026-11-18: the measurement module SDK moved from this repository's
`sdk/` folder to its own repository,
[Open-ERP-Module-SDK](https://github.com/tjd10684-bit/Open-ERP-Module-SDK)
(history kept). This project installs it from the pinned `v1.1.0` tag (since 0.1.1; earlier builds
used `v1.0.0`) through the `module` and `test` extras.

Updated 2026-11-17: the experimental U-WAVE helper module is built against the
Open ERP contract (the module SDK above). Physical hardware remains untested.
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
instrument. Two-instrument correction remains future work; Bluetooth via BW's
virtual COM bridge is now included in the limited hardware validation above.

## Current implementation and next handoff

- The package parses DT/ST/TI/RI packets, encodes DR/IR requests and provides
  single-channel latest-value requests and transmitter discovery.
- A pyserial transport implements the documented legacy virtual-COM route.
  Manufacturer drivers remain external; the direct USB route is not implemented.
- The setup GUI accepts assets supplied by the ERP on the right, scans registered
  transmitters on the left, and supports dragging or click-then-click linking.
- To tell identical instruments apart, **Read Values** shows each Event driven
  transmitter's latest value once per click and highlights what changed.
  **Identify** and **Link All** link an asset to the single transmitter whose
  reading changes or whose DATA button is pressed when that asset is asked for.
  Answers from before the asset's baseline values, several responders, or one
  linked elsewhere link nothing. The receiver client passes unsolicited packets
  (forwarded DATA presses) to a callback and can listen without a request.
  Values come from the receiver's store, so reading does not wake transmitters.
- One-to-one links use asset UUID and transmitter Device ID with a saved receiver
  port. Group/channel are last-seen addresses, not identities. A scan updates
  routes only for unambiguous Device IDs. Settings are local to the Windows user
  at `%LOCALAPPDATA%\UWaveAccessory\links.json`, not shared ERP inventory.
- A simulator, serial loopback tests and Tkinter tests exercise software without
  physical equipment. The demo has sample assets and uses a separate settings
  file in the user's temporary folder.
- Open ERP installs measurement modules as separate helper programs that speak
  [the SDK's `PROTOCOL.md`](https://github.com/tjd10684-bit/Open-ERP-Module-SDK/blob/main/PROTOCOL.md).
  `module/uwave_module.py` reuses this
  package's protocol, serial transport, links, simulator and setup window. The
  module offers a Simulator port and uses its host-provided data directory;
  standalone settings are separate and are not migrated automatically.
- The helper re-identifies the saved transmitter by Device ID within the
  capture deadline, follows its current channel, checks the acquisition mode,
  and returns the reported units and a stable transmitter source ID.
  `build_module.ps1` produces `module/build/mitutoyo-u-wave-0.2.0.zip`.
  The built module passed `host_check`, Open ERP's real module-manager install,
  setup-window launch, and simulator capture checks.
  The host supplies the asset list; the module does not query the ERP database.
  The helper contract currently supplies tags, names and categories, but not the
  optional `used_by` balloon labels supported by the standalone setup window.
  Detailed private host changes were handed to the owning session and are not
  copied into this repository.

### Local 0.1.0 build verification

- All **130 tests passed** (`python -m pytest tests sdk/python/tests -q`) before
  the SDK moved. Since the move, `python -m pytest tests -q` runs this
  project's 117 tests; the SDK's 13 run in its own repository.
- Rebuilt the module after fixing capture's setup-lock timeout and ensuring
  transport closure happens before releasing the receiver lock. SDK
  `host_check` passed against the frozen helper.
- An isolated PyInstaller-frozen host harness installed the package, captured
  **12.345 mm** and **0.5000 in** from the simulator, rejected mismatched units,
  updated the module while preserving links, and stopped both helpers cleanly.
  The source host also opened and closed the visual setup window. The full
  interactive packaged-host workflow remains a manual check.
- Released package: `mitutoyo-u-wave-0.1.0.zip`, 10,932,344 bytes, SHA256
  `c6a17bd87857b1632afbe917f48e29136f473ff2f7025506778469873ae618e0`, published
  with the v0.1.0 release (see the top of this file). Earlier local builds differ
  because builds are not byte-reproducible. The bundle contains the public
  module/SDK, not private ERP source.

The next task is **extended hardware verification**, not production inspection:
reconnects, power interruption, late replies and sustained mixed operation remain
open beyond the basic two-route checks recorded above.
Use the [module build instructions](README.md#build-and-try-the-open-erp-module)
to build a tester package; do not copy this machine's virtual environment or
settings.

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
   Keep U-WAVEPAK-BW running for Bluetooth. Verify each receiver's VCP driver,
   select its port and check Use this receiver in setup. Do not pick a COM port
   just because it is first in the list.
7. Prefer the receiver's known Group ID for the first scan. Compare receiver and
   transmitter identities, channels, modes and connected/disconnected states
   against U-WAVEPAK's recorded setup. Rescan after reconnecting.
8. Confirm ascending IR searches include the requested starting channel; verify
   the Auto group's wrong-group ST 50 behavior and end-of-search ST 51. The scan
   uses one second per request, not one second for the whole scan.
9. Exercise latest-value requests separately before connecting a capture provider.
   Verify unchanged readings, missing data, status, units, reconnects and late
   replies. A PC response timestamp is not the physical measurement time.
   Then try Read Values, Identify and Link All: confirm a Button driven DATA
   press reaches the PC over the VCP, and how noisy instruments behave (no change
   threshold is applied).
10. Perform the relevant [validation checks](VALIDATION_PLAN.md). Do not enable
    production capture until request correlation, reconnection and source
    verification are sound. Mixed-operation stress and reconnect checks remain.

At each handoff, update the supported model/version matrix, decisions, unresolved
questions, and exact verified development commands in the repository. Keep local
serial numbers, COM assignments, operator data, and logs out of committed examples.

## Open decisions

- Actual height gauge, indicator, Bluetooth module, connection units, and
  compatible event-driven behavior.
- Whether the existing indirect calculation matches the physical fine-correction
  arrangement.
- Physical validation of the U-WAVE-R/VCP route, including request timing,
  transmitter re-registration, channel changes, reconnects and forwarded DATA
  presses.
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
- Future paired-capture sampling relationship. Current routing is by saved
  receiver port and verified transmitter Device ID, not channel alone.
- Pedal model, trigger binding, duplicate-trigger handling, and supported
  application-focus behavior.
- Whether the basic mixed Bluetooth/U-WAVE-R results extend to other target PCs,
  adapters and firmware, and whether reconnect/load behavior is reliable.
