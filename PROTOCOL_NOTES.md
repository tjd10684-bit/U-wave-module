# Mitutoyo protocol and operating notes

Original summaries of the references listed in [REFERENCES.md](REFERENCES.md).
These notes are not a replacement for the manufacturer manuals, and do not
establish compatibility with unidentified hardware.

## 1. Legacy U-WAVE-R path

```text
Instrument -> U-WAVE-T -> proprietary wireless link -> U-WAVE-R -> USB -> PC
```

The receiver, not each instrument, is cabled to the PC. U-WAVEPAK Setup registers
transmitters and configures Group ID, Channel, Band ID, and measurement mode.
Registered settings survive power removal.

The existing Data I/F application converts incoming data into keyboard input to
the active Windows application. It is not an ordered multi-gauge transaction
manager. A native collector would use the receiver's documented interface and
would not operate alongside Data I/F on the same receiver.

### Drivers and addressing

The manual offers direct USB and virtual COM routes. For the virtual COM route it
specifies:

| Parameter | Value |
| --- | --- |
| Baud rate | 57600 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | RTS/CTS |

These parameters are documented for the legacy receiver, not established here
for the Bluetooth software bridge.

Group IDs run from 00 to 99; each transmitter on a receiver needs a distinct
channel from 00 to 99. Receiver and transmitter need matching radio Group/Band
settings. Device ID identifies the physical device; it is not interchangeable
with the request's channel field.

### Measurement modes

| Mode | Instrument / receiver behavior | Implication |
| --- | --- | --- |
| Button driven | Pressing DATA sends a reading; the receiver forwards it to the PC | Suitable for the existing keyboard-input route |
| Event driven | Changes are sent to the receiver, which stores readings for a PC request | Supports software-requested latest-value collection, not guaranteed fresh simultaneous sampling |

For the legacy transmitter, a short DATA press is under 2 seconds. Holding for
2 to less than 5 seconds sends a cancel command in Button driven mode. A hold of
5 to less than 10 seconds runs a receiver scan. Do not turn a pedal trigger into
an assumed long DATA press.

### Documented messages worth implementing first

The legacy manual uses ASCII packets terminated by carriage return. Its Appendix
is Chapter 6, although some internal cross-references incorrectly say Chapter 7.

| Message | Purpose | Manual section |
| --- | --- | --- |
| `IR` | Request receiver/transmitter information and discover channel bindings | 6.1.3.1 |
| `RI` / `TI` | Receiver/transmitter information, including identity or connection state | 6.1.2.3 / 6.1.2.4 |
| `DR` | Request stored measurement data for Event driven transmitters | 6.1.3.2 |
| `DT` | Measurement with group, channel, signed numeric value, and unit | 6.1.2.1 |
| `ST` | Status/error response, not a numeric measurement | 6.1.2.2 |

The documented `DR` fields are packet code, API version, channel, group,
clear-after-output flag, search method, and CR terminator (10 bytes total).
Consult the table before encoding messages; do not infer field order from UI
columns.

A specific-channel request uses a channel from 00 to 99. The special channel
`FF` requests all channels with available data and supports ascending or
descending channel order.

**Important: available data is not the same as all expected instruments.** The
manual documents omission of disconnected/no-data channels during searches.
Do not treat the first and second response as the intended A/B pair without
checking their identities and completeness.

Legacy `DT` units are `M` for millimeters, `I` for inches, and `0` for no unit.
Status messages include low transmitter battery (`00`), instrument not
responding (`01`), omitted measurements (`03`), disconnected transmitter (`04`),
no data (`05`), bad request (`50`), end of search (`51`), and cancel (`99`).
Interpret status in context; never feed a status packet into a numeric input.

Decide clear-after-output behavior only after testing stable unchanged readings.
Clearing a latest-value buffer without another instrument change can leave no
new data for the next request.

## 2. Bluetooth U-WAVE-TCB/TMB path

```text
Instrument -> U-WAVE-TCB/TMB -> PC Bluetooth -> U-WAVEPAK-BW
           -> Mitutoyo virtual COM bridge -> collector
```

These Bluetooth modules do not use the U-WAVE-R receiver. The documented Windows
integration uses U-WAVEPAK-BW, which must be started before the higher-level
application. It remains running as the bridge.

The vendor download page lists Windows 10/11 64-bit, Bluetooth 4.0-compatible
communication, and up to seven connected TCB/TMB modules. Confirm the exact
module, software, adapter, and OS versions before claiming support.

### Data requests and mapping

The BW manual states:

- Button driven mode sends a value when DATA is pressed.
- In Event driven mode, changed readings are transmitted on a 0.5-second cadence.
- BW retains the latest received value and supplies it in response to a request
  from higher-level software.
- Event driven mode consumes more battery than Button driven mode.
- The higher-level application's COM port must match BW's displayed COM port.
- A BW list row number maps to Channel ID by subtracting one: row 1 is channel 00.
- Group and Band settings must match the higher-level application's settings.

The setup guide establishes that application-requested collection exists. It is
not a complete specification of the virtual-COM command implementation. Verify
the applicable vendor command reference and actual behavior; do not assume every
legacy command, status, serial parameter, or timing guarantee applies unchanged.

The manual also warns that a reconnection does not itself send a measurement.
Confirm reception after reconnecting before accepting data.

### Mixed-system limitation

Page 23 explicitly states that USB-ITPAK cannot be used together with both
U-WAVEPAK-BW and legacy U-WAVEPAK/U-WAVE-R, and gives uninstall guidance for that
USB-ITPAK use case.

This is not proof that a custom Open ERP collector can or cannot use both
connections. Test driver coexistence, COM-port behavior, independent routing,
reconnect behavior, and acquisition under load before enabling mixed operation.
Do not uninstall functioning software just to explore this hypothesis.

## 3. Foot-switch options

Mitutoyo offers U-WAVE connecting cables with foot-switch ports, including the
02AZE140 family. The suffix and compatibility depend on the instrument connector.
No specific cable or pedal has been selected for this project.

- A transmitter-side pedal provides hands-free input for that instrument.
- Triggering two transmitters together does not establish their wireless arrival
  order, identity, or a synchronized sample.
- The proposed PC-side pedal invokes collection software, which selects and
  validates the intended instruments.
- A generic USB keyboard pedal does not by itself add data-request capability to
  U-WAVEPAK or Open ERP.

Choose a pedal only after deciding the software trigger behavior and confirming
the actual devices. Avoid improvised wiring or unverified splitter assumptions.

## 4. Useful operator baseline

For the original keyboard-input workflow:

1. Connect the receiver before starting U-WAVEPAK.
2. Use Setup to verify the intended transmitter is connected (`S = c`) and in
   Button driven mode. Do not recreate registrations each time.
3. Exit Setup, then start Data I/F.
4. Configure the desired data format and trailing control key in Data I/F, not
   Setup's Environment dialog.
5. Focus a disposable text document and press DATA briefly for a baseline check.
6. Stop and exit Data I/F, then exit the application before unplugging the receiver.

Keyboard output follows focus. Status suppression for a clean text document is
not an appropriate policy for a native integration: acquisition errors must be
handled and surfaced there.

Avoid sleep/hibernate while collecting; the legacy manual warns that receiver
USB power is interrupted. Preserve working settings and use the documented
backup mechanisms before changing configuration. Factory reset is destructive
and is not a normal reconnect step.
