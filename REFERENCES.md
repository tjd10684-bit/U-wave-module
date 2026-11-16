# References and evidence

Reference review date: 2026-11-15.

These documents contain original summaries, not reproductions of the vendor
manuals. Download the originals from Mitutoyo and follow their terms. Source
availability, supported versions, and download conditions can change.

## 1. Legacy U-WAVEPAK manual

- Title: *U-WAVEPAK User's Manual*
- Manual number: **99MAL216A10**
- Edition reviewed: **10th edition, 2020, v1.022A/v1.022B**
- [Manufacturer-hosted English PDF](https://manual.mitutoyo.co.jp/download/pdf?id=78247&type=inc)
- [Manufacturer software/manual download page](https://www2.mitutoyo.co.jp/eng/contact/products/u-wave/thanks2.cgi?action=comp)

The supplied English manual was read during the setup session. The public
manufacturer-hosted link above was found for the same manual identifier.

| Topic | Printed section / page |
| --- | --- |
| Keyboard emulation overview | 1.1 |
| Receiver power and LED status | 1.4 |
| Group, channel, band, measurement modes, Device ID | 1.7.1-1.7.5 |
| Driver installation and VCP parameters | 2.1.2 |
| Driver selection, Setup versus Data I/F | 3.1.1 |
| Direct Data I/F launch | 3.1.3 |
| Registration and connected status | 4.1.2, 4.2.2 |
| Change measurement mode | 4.4.2.1 |
| Backup and sending settings | 4.4.9, 4.5.1 |
| Data I/F and output formatting | 5.1-5.3 |
| Packet framing and measurement/status formats | 6.1.1-6.1.2 |
| Information request | 6.1.3.1, printed 6-8 |
| Measurement request and omission/error behavior | 6.1.3.2, printed 6-9 to 6-10 |
| Destructive initialization | 6.2 |
| Sleep/hibernate restriction | 6.3.3 |

Some internal references in this edition say Chapter 7 while the actual appendix
is Chapter 6. Use the table of contents and section headings, not those stale
cross-references.

The legacy manual lists operating systems through Windows 10. Do not treat that
edition as proof of official Windows 11 support for the legacy stack.

## 2. Bluetooth U-WAVEPAK-BW manual

- Title: *U-WAVEPAK-BW Setup Manual*
- [Manufacturer-hosted English PDF, 99MAL128A4](https://mitutoyo.eu/application/files/7417/5267/2586/99MAL128A4_U-WAVEPAK-BW_Setupmanual.pdf)
- Reviewed length: 27 PDF pages.

| Topic | PDF page |
| --- | --- |
| Installation and virtual-COM driver | 4-6 |
| Direct keyboard input and application requests | 14 |
| Button/Event driven behavior, latest-value cache, battery use | 15 |
| Higher-level application connection, COM/channel/group mapping | 23 |
| USB-ITPAK mixed-system warning | 23 |

This guide documents the application bridge but does not by itself establish
every command or serial parameter that a custom collector should use.

## 3. Bluetooth software and supported module families

- [Official U-WAVEPAK-BW download/product information](https://www.mitutoyo.co.jp/downloads/software-drivers/u-wavepak-bw/)

The page is in Japanese. At review time it listed TCB/TMB model families,
Windows 10/11 64-bit, Bluetooth 4.0-compatible communication, up to seven
connections, and an included required virtual-COM driver. It listed v1.0.5 with
an August 2024 update. Recheck the current release rather than hard-code that
version into a future installer.

## 4. Foot-switch connection cables

- [Official U-WAVE Connection Unit/Cable product page](https://www.mitutoyo.com/products/small-tool-instruments-and-data-management/data-management-spc/u-wave/u-wave-connection-unit-cable/)

The manufacturer's indexed product information lists foot-switch-port cable
variants including the 02AZE140 family. Direct page retrieval was restricted in
the research environment. Confirm model/connector compatibility and current
availability with the manufacturer or supplier before ordering.

This establishes an instrument-side foot-switch option, not a guarantee of
ordered or simultaneous multi-instrument acquisition.

## Evidence boundaries

- Legacy receiver/transmitter communication was observed during the session.
- Native requests and discovery now have an implementation and synthetic tests;
  they have not been tested with the physical receiver. Pedal-controlled host
  acquisition, Bluetooth integration and mixed transport capture remain future work.
- The owner described the desired host workflow. Private host source is not
  included, quoted, or documented here; inspect it separately with authorization.
- The documents distinguish manufacturer-documented behavior from proposed
  architecture. Avoid turning a proposal into a supported-feature claim.
- Only manufacturer reference links are supplied. No vendor executables, drivers,
  DLLs, manual PDFs, or extracted manual text are included in this bundle.
