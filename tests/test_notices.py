"""The generator behind THIRD-PARTY-NOTICES.txt in the module package (generate_notices.py)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("generate_notices", ROOT / "generate_notices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_modules_licence_is_the_agpl_text():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text and "Version 3, 19 November 2007" in text


def test_every_bundled_component_has_a_notice_with_its_licence_text(generator):
    text, problems = generator.build_notices()
    assert problems == []
    for component in ("Python ", "Tcl/Tk", "pyserial", "open-erp-module", "Microsoft Visual C++ Runtime"):
        assert component in text
    assert "Copyright (C) 2026 TD Manufacturing" in text
    assert "\r" not in text and text.endswith("\n")


def test_a_missing_licence_text_is_reported_so_the_build_fails(generator, monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "license_files", lambda distribution: [])
    monkeypatch.setattr(generator, "VENDORED_LICENSES", {})
    problems = generator.build_notices()[1]
    assert any(problem.startswith("pyserial") for problem in problems)
    output = tmp_path / "notices.txt"
    assert generator.main([str(output)]) == 1
    assert output.is_file()
    assert generator.main([]) == 2


def test_pyserials_licence_comes_from_the_vendored_copy_only_for_its_own_version(generator, monkeypatch):
    import importlib.metadata as metadata

    text, problems = generator.build_notices()
    assert problems == []
    assert "Neither the name of the copyright holder" in text  # pyserial's BSD-3-Clause text
    # The wheel for another version must not silently reuse text that was checked for 3.5.
    monkeypatch.setattr(generator, "VENDORED_LICENSES", {"pyserial": ("0.0.0", "licenses/pyserial-3.5-LICENSE.txt")})
    monkeypatch.setattr(generator, "license_files", lambda d: [] if d.metadata["Name"] == "pyserial" else [("L", "x" * 300)])
    assert any(problem.startswith("pyserial") for problem in generator.build_notices()[1])
    assert metadata.distribution("pyserial").version == "3.5"
