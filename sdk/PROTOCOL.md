# Open ERP measurement module protocol, version 1

A measurement module lets Open ERP capture readings from one brand of measuring
device. The module is a **separate helper program**. Open ERP starts it, talks
to it over its standard input and output, and stops it when Open ERP closes.
Device communication lives entirely inside the module, so a module and Open ERP
update independently and a module can be written in any language.

This document is the contract. The Python library in [`python/`](python/) and
the example in [`examples/simulated-gauge/`](examples/simulated-gauge/)
implement it, and `host_check` tests a module against it.

## Module folder and package

A module is a folder containing `module.toml` (UTF-8 without a byte order mark)
and the helper program:

```toml
id = "simulated-gauge"          # 1-64 of a-z 0-9 . _ - ; starts/ends with a letter or digit
name = "Simulated Gauge"        # shown to the operator
version = "1.0.0"               # letters, digits, . + -
publisher = "Open ERP"          # shown when the module is added
protocol = 1                    # this document's version
kind = "measurement"
description = "Pretends to be a gauge, for trying out capture."   # optional

[run]
program = "simulated-gauge.exe" # relative to the module folder
args = []                       # optional
```

Distribute a module as a `.zip` with `module.toml` at the top level and the
program inside the zip. Operators add it in **Settings > Measurement Devices >
Add Module...**. Open ERP refuses packages with unsafe paths (`..`, drive
letters, reserved Windows names), symbolic links, encrypted entries, more than
20,000 files or more than 1 GB uncompressed. Adding a newer package with the
same `id` replaces the old program and keeps the module's settings.

Open ERP keeps modules per Windows user:

| Folder | Contents |
| --- | --- |
| `%LOCALAPPDATA%\Open ERP\modules\<id>\` | The unpacked module (replaced on update) |
| `%LOCALAPPDATA%\Open ERP\module-data\<id>\` | The module's own settings (kept on update and removal) |
| `%LOCALAPPDATA%\Open ERP\module-logs\<id>.log` | Everything the program wrote to stderr |

Store settings only in the data folder Open ERP passes to `initialize`; the
module folder is replaced on every update.

## Process rules

- Open ERP starts the program with the module folder as its working directory,
  no console window and all three standard streams redirected. Build a console
  program (for PyInstaller, do not use `--windowed`/`--noconsole`); Open ERP
  hides the console. A console program can still open its own windows.
- **stdout carries protocol messages only.** Anything else is a protocol error
  and Open ERP stops the module. Write logs and diagnostics to **stderr**.
- When stdin reaches end of file, exit promptly. Open ERP closes stdin when it
  stops the module and kills the program if it is still running 2 seconds later.
- Several different modules can run side by side. Open ERP sends each capture
  to the one module that links the requested asset.

## Framing

Messages are [JSON-RPC 2.0](https://www.jsonrpc.org/specification) objects,
one per line: UTF-8 JSON followed by LF (a CR before the LF is tolerated). A
line may be at most 1 MiB. Batches are not used. `NaN` and `Infinity` are not
valid JSON. Ignore fields and notifications you do not recognize, so later
Open ERP versions can add them. Answer unknown requests with error `-32601`.

Open ERP sends requests with integer ids. Answer every request exactly once.
Open ERP ignores a response that arrives after it stopped waiting (for example
for a cancelled capture). Open ERP does not answer requests from the module.

## Methods Open ERP calls

### `initialize` (request; 15 s)

The first message. Open the device connection here or later, but answer within
15 seconds.

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
  "protocol_version": 1,
  "host": {"name": "Open ERP", "version": "0.2.11"},
  "module_id": "simulated-gauge",
  "data_dir": "C:\\Users\\me\\AppData\\Local\\Open ERP\\module-data\\simulated-gauge"}}
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "protocol_version": 1,
  "module": {"id": "simulated-gauge", "name": "Simulated Gauge", "version": "1.0.0"},
  "acquisition_mode": "latest",
  "capabilities": {"setup": true}}}
```

`acquisition_mode` is `latest` when a capture returns the device's most recent
reading (typical for gauge-initiated transmitters), or `fresh` only when the
device verifiably takes a new reading on request. Open ERP rejects a reply
whose `protocol_version` differs from its own (shown as **Needs update**) or
whose `module.id` differs from `module.toml`.

### `linked_assets` (request; 5 s)

The Open ERP assets this module can capture from right now.

```json
{"jsonrpc": "2.0", "id": 2, "method": "linked_assets"}
{"jsonrpc": "2.0", "id": 2, "result": {"asset_ids": ["5b0f3c9e-...", "a17d..."]}}
```

Asset ids are Open ERP's opaque asset identifiers (supplied by `open_setup`).
The module owns the mapping from assets to its devices. Open ERP asks after
start, after setup closes and after an `assets_changed` notification. An asset
linked by two modules cannot be captured until one module unlinks it.

### `capture` (request)

Take one reading for one asset.

```json
{"jsonrpc": "2.0", "id": 7, "method": "capture", "params": {
  "capture_id": "c0ffee-...", "asset_id": "5b0f3c9e-...", "units": "mm",
  "input_name": "measurement", "requested_at": "2026-11-20T14:03:11.250000+00:00",
  "timeout_seconds": 5.0}}
```

```json
{"jsonrpc": "2.0", "id": 7, "result": {
  "capture_id": "c0ffee-...", "asset_id": "5b0f3c9e-...",
  "value": 12.704, "units": "mm", "source_id": "uwave:R1:G00:CH03",
  "received_at": "2026-11-20T14:03:11.410000+00:00",
  "acquisition_mode": "latest", "sampled_at": null}}
```

- Echo `capture_id` and `asset_id` exactly. Find the device through the
  module's own asset link, never "whichever device answered first".
- `units` (`mm` or `in`) is what the operator expects. Return the units the
  device actually reported; never convert silently. Open ERP rejects a mismatch.
- `input_name` is `measurement`, `a` or `b` (two separate captures for an
  indirect pair). Each request is exactly one reading.
- `value` is a finite JSON number. `source_id` is a stable, nonempty,
  transport-qualified identity of the physical source; the same transmitter
  must report the same id for A and B.
- `received_at` is the timezone-aware time the PC received this request's
  device response. `sampled_at` is the device's own sample time, or `null`.
  `acquisition_mode` repeats the declared mode.
- Open ERP waits `timeout_seconds`, then cancels.

To fail a capture, return a JSON-RPC error. Open ERP shows its `message` to the
operator as written, so make it specific. Use codes 1000-1999.

```json
{"jsonrpc": "2.0", "id": 7, "error": {"code": 1001, "message": "Transmitter 02 is out of range."}}
```

### `cancel` (notification)

```json
{"jsonrpc": "2.0", "method": "cancel", "params": {"capture_id": "c0ffee-..."}}
```

Open ERP has given up on that capture (timeout, the operator moved on, or setup
opened). Release any pending state for it, and never hand a late device reply
for it to a later capture. You may still answer the request; the answer is
ignored.

### `open_setup` (request; no time limit)

Show the module's setup window, where the operator connects devices and links
them to Open ERP assets. Answer `{}` when the window closes.

```json
{"jsonrpc": "2.0", "id": 9, "method": "open_setup", "params": {"equipment": [
  {"asset_id": "5b0f3c9e-...", "tag": "MIC-014", "name": "0-1 in Micrometer", "category": "Micrometer"}]}}
{"jsonrpc": "2.0", "id": 9, "result": {}}
```

`equipment` lists the Open ERP assets the operator may link. An asset missing
from the list may only be filtered out, so do not delete its link. Open ERP
lets the module bring its window to the front and asks `linked_assets` when
setup returns. Captures may arrive while setup is open.

### `shutdown` (request; 3 s)

Close device connections, answer `{}`, then exit. Open ERP then closes stdin.

## Notifications the module may send

| Method | Params | Effect |
| --- | --- | --- |
| `status` | `{"state": "ready" \| "warning" \| "error", "message": "Receiver unplugged."}` | Shown with the module in Measurement Devices (up to 300 characters); an empty message clears it |
| `assets_changed` | none | Open ERP asks `linked_assets` again |

## Error codes

| Code | Meaning |
| --- | --- |
| 1000-1999 | Module-defined; the message is shown to the operator |
| -32601 | Unknown method |
| -32602 | Invalid params |
| -32603 | Internal error in the module |

## Compatibility

`protocol` changes only for incompatible changes. New optional fields, methods
and notifications are added within version 1, and both sides ignore what they
do not understand.
