# Open ERP measurement module SDK

Build a **measurement module**: a separate helper program that connects one
brand of measuring device to Open ERP. Open ERP starts the module, asks it for
readings over its standard input and output, and stops it when Open ERP
closes. All device communication stays inside the module, so modules and Open
ERP are updated independently, and you can write a module in any language.

| Path | What it is |
| --- | --- |
| [`PROTOCOL.md`](PROTOCOL.md) | The contract between Open ERP and a module (version 1) |
| [`python/`](python/) | `open_erp_module`, a Python library that implements the protocol, plus `host_check` and `package` tools |
| [`examples/simulated-gauge/`](examples/simulated-gauge/) | A complete module that needs no hardware; start here |

## Write a module in Python

Subclass `Module`, override what your device supports and call `run`:

```python
from open_erp_module import Module, ModuleError, Reading, run

class MyGauge(Module):
    module_id = "my-gauge"            # must match id in module.toml
    name = "My Gauge"
    version = "1.0.0"
    acquisition_mode = "latest"       # or "fresh" if every capture triggers a new measurement

    def initialize(self, context):    # load settings from context.data_dir
        ...

    def linked_assets(self):          # Open ERP asset ids you can capture from
        return [...]

    def capture(self, request):       # one reading for request.asset_id, in the units sent
        if request.cancelled.is_set():
            raise ModuleError("Cancelled.")
        return Reading(value=12.345, units="mm", source_id="my-gauge:port-3:channel-1")

    def open_setup(self, equipment):  # optional: your setup window (runs on the main thread)
        ...

if __name__ == "__main__":
    raise SystemExit(run(MyGauge()))
```

The library handles the protocol: framing, threading, cancellation, input
validation, the reading's ids and timestamps, and keeping stray `print()`
output off the protocol stream. Raise `ModuleError("message")` to refuse a
request; Open ERP shows the message to the operator. Use `report_status` to
show a short status in Open ERP and `assets_changed` when links change outside
setup.

## Test and package it

The library has no dependencies beyond Python 3.11+. From `python/`,
`pip install -e .` installs it with the `open-erp-module-check` and
`open-erp-module-package` commands; `python -m open_erp_module.host_check`
and `python -m open_erp_module.package` work too.

```powershell
# Run the module against the protocol checks while developing:
python -m open_erp_module.host_check my-gauge -- python my_gauge.py
python -m open_erp_module.host_check my-gauge --setup --asset A1 --data-dir .\data -- python my_gauge.py
python -m open_erp_module.host_check my-gauge --capture A1 --data-dir .\data -- python my_gauge.py

# Build a console program (PyInstaller: no --windowed), copy module.toml beside it, then:
python -m open_erp_module.host_check dist\my-gauge
python -m open_erp_module.package dist\my-gauge -o my-gauge-1.0.0.zip
```

Operators add the zip in Open ERP under **Settings > Measurement Devices > Add
Module...**. The [simulated gauge](examples/simulated-gauge/) has a complete
`build.ps1`.

## Library tests

```powershell
cd python
python -m pytest
```
