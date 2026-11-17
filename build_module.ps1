<#
.SYNOPSIS
Builds the installable Mitutoyo U-WAVE measurement module package.

.PARAMETER Python
A Python 3.12+ with PyInstaller and pyserial installed.
#>
param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$module = Join-Path $root "module"
$sdk = (Resolve-Path (Join-Path $root "sdk\python\src")).Path
$source = (Resolve-Path (Join-Path $root "src")).Path
$build = Join-Path $module "build"
$dist = Join-Path $build "dist"
$folder = Join-Path $dist "mitutoyo-u-wave"

& $Python -m PyInstaller --noconfirm --clean --name mitutoyo-u-wave --paths $sdk --paths $source `
    --collect-all serial --distpath $dist --workpath (Join-Path $build "work") --specpath $build `
    (Join-Path $module "uwave_module.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Copy-Item (Join-Path $module "module.toml") $folder
$env:PYTHONPATH = "$sdk;$source"
& $Python -m open_erp_module.host_check $folder
if ($LASTEXITCODE -ne 0) { throw "The built module failed host_check." }
& $Python -m open_erp_module.package $folder -o (Join-Path $build "mitutoyo-u-wave-0.1.0.zip")
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
