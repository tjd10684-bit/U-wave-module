from __future__ import annotations

import json
from pathlib import Path
import sys
import zipfile

import pytest

from open_erp_module import host_check
from open_erp_module.manifest import ManifestProblem
from open_erp_module.package import build_package

TESTS = Path(__file__).parent
SAMPLE = TESTS / "sample_module.py"
SDK_SOURCE = TESTS.parent / "src"
SIMULATED_GAUGE = TESTS.parents[1] / "examples" / "simulated-gauge"

MANIFEST = """\
id = "sample-gauge"
name = "Sample Gauge"
version = "1.0.0"
publisher = "Tests"
protocol = 1
kind = "measurement"

[run]
program = "{program}"
"""


def module_folder(tmp_path: Path, program: str = "sample-gauge.exe") -> Path:
    folder = tmp_path / "sample-gauge"
    folder.mkdir()
    (folder / "module.toml").write_text(MANIFEST.format(program=program), encoding="utf-8")
    return folder


@pytest.fixture
def sdk_on_path(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(SDK_SOURCE))


def test_host_check_passes_a_working_module(tmp_path, sdk_on_path, capsys):
    folder = module_folder(tmp_path)

    code = host_check.main([str(folder), "--capture", "A1", "--", sys.executable, str(SAMPLE)])

    output = capsys.readouterr().out
    assert code == 0, output
    assert "WARN  package: run.program 'sample-gauge.exe' is not in" in output
    assert "PASS  capture: 2.5 mm from sample:1" in output
    assert "status: {'state': 'ready', 'message': 'Sample ready'}" in output
    assert "FAIL" not in output


def test_host_check_fails_a_module_that_writes_raw_text_to_stdout(tmp_path, sdk_on_path, capsys):
    folder = module_folder(tmp_path)

    code = host_check.main([str(folder), "--", sys.executable, str(SAMPLE), "--noisy"])

    output = capsys.readouterr().out
    assert code == 1
    assert "FAIL  stdout: stdout carried something that is not a protocol message: 'debug: starting'" in output


def test_host_check_reports_a_refused_capture(tmp_path, sdk_on_path, capsys):
    folder = module_folder(tmp_path)

    code = host_check.main([str(folder), "--capture", "B7", "--", sys.executable, str(SAMPLE)])

    assert code == 1
    assert "FAIL  capture: the module refused: This asset is not linked." in capsys.readouterr().out


def test_simulated_gauge_example_captures_a_linked_asset(tmp_path, sdk_on_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    (data / "links.json").write_text(json.dumps({"links": {"A1": {"gauge": 2, "value": 12.5, "units": "mm"}}}))

    code = host_check.main([
        str(SIMULATED_GAUGE), "--capture", "A1", "--data-dir", str(data),
        "--", sys.executable, str(SIMULATED_GAUGE / "simulated_gauge.py"),
    ])

    output = capsys.readouterr().out
    assert code == 0, output
    assert "PASS  linked_assets: A1" in output
    assert "PASS  capture: 12.5 mm from simulated:gauge-2" in output


def test_host_check_explains_a_manifest_saved_with_a_byte_order_mark(tmp_path, capsys):
    folder = module_folder(tmp_path)
    (folder / "module.toml").write_text(MANIFEST.format(program="sample-gauge.exe"), encoding="utf-8-sig")

    assert host_check.main([str(folder)]) == 1
    assert "FAIL  module.toml: module.toml starts with a byte order mark" in capsys.readouterr().out


def test_package_puts_the_manifest_first_and_leaves_out_caches(tmp_path):
    folder = module_folder(tmp_path, program="bin/sample-gauge.exe")
    (folder / "bin").mkdir()
    (folder / "bin" / "sample-gauge.exe").write_bytes(b"MZ")
    (folder / "bin" / "__pycache__").mkdir()
    (folder / "bin" / "__pycache__" / "cached.pyc").write_bytes(b"")
    (folder / "README.txt").write_text("Read me")

    package = build_package(folder, tmp_path / "out" / "sample.zip")

    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    assert names[0] == "module.toml"
    assert sorted(names) == ["README.txt", "bin/sample-gauge.exe", "module.toml"]
    assert [path.name for path in (tmp_path / "out").iterdir()] == ["sample.zip"]


def test_package_built_inside_the_module_folder_leaves_out_the_previous_package(tmp_path, monkeypatch):
    folder = module_folder(tmp_path)
    (folder / "sample-gauge.exe").write_bytes(b"MZ")
    monkeypatch.chdir(folder)

    build_package(folder)
    package = build_package(folder)

    assert package == folder / "sample-gauge-1.0.0.zip"
    with zipfile.ZipFile(package) as archive:
        assert sorted(archive.namelist()) == ["module.toml", "sample-gauge.exe"]


def test_package_needs_the_program_inside_the_folder(tmp_path):
    folder = module_folder(tmp_path)

    with pytest.raises(ManifestProblem, match="not in"):
        build_package(folder, tmp_path / "sample.zip")
    assert not (tmp_path / "sample.zip").exists()
