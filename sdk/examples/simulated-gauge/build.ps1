<#
.SYNOPSIS
Builds simulated-gauge-<version>.zip, a module package Open ERP can add.

.PARAMETER Python
A Python 3.11+ with PyInstaller installed (pip install pyinstaller).
#>
param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$sdk = (Resolve-Path "$here\..\..\python\src").Path
$build = Join-Path $here "build"
$module = Join-Path $build "dist\simulated-gauge"

# A console program: Open ERP hides the console and talks to it over stdin/stdout.
& $Python -m PyInstaller --noconfirm --clean --name simulated-gauge --paths $sdk `
    --distpath (Join-Path $build "dist") --workpath (Join-Path $build "work") --specpath $build `
    (Join-Path $here "simulated_gauge.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Copy-Item (Join-Path $here "module.toml") $module

$env:PYTHONPATH = $sdk
& $Python -m open_erp_module.host_check $module
if ($LASTEXITCODE -ne 0) { throw "The built module failed host_check." }
& $Python -m open_erp_module.package $module -o (Join-Path $build "simulated-gauge-1.0.0.zip")
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
