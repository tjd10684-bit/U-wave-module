# Simulated Gauge example module

A complete Open ERP measurement module that needs no hardware. In its setup
window you link Open ERP assets to numbered "gauges" and enter the reading each
gauge returns. Capture in Inspection then returns that reading.

Use it to try capture, or copy it as the starting point for a real device
module: replace `capture` with your device I/O and the setup window with your
device's connection and linking screen.

## Try it while developing

From this folder, with the SDK on the path:

```powershell
$env:PYTHONPATH = "..\..\python\src"
python -m open_erp_module.host_check . -- python simulated_gauge.py
python -m open_erp_module.host_check . --setup --asset A1 --asset A2 --data-dir .\check-data -- python simulated_gauge.py
python -m open_erp_module.host_check . --capture A1 --data-dir .\check-data -- python simulated_gauge.py
```

The second command opens the setup window; link `A1`, Save, and the third
command captures from it. `--data-dir` keeps the links between runs.
`host_check` warns that `simulated-gauge.exe` is missing because the `--`
command replaces it until you build.

## Build the package

```powershell
.\build.ps1 -Python C:\path\to\python.exe   # a Python with PyInstaller installed
```

This builds `build\dist\simulated-gauge\` (the program and `module.toml`),
runs `host_check` on it and writes `build\simulated-gauge-1.0.0.zip`. Add that
zip in Open ERP under **Settings > Measurement Devices > Add Module...**, then
choose **Open Setup...** to link assets.

The readings are made up. The units you choose in setup are the units the
gauge reports, so choosing `in` for an asset Inspection measures in `mm`
shows Open ERP's unit-mismatch protection.
