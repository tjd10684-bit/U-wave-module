"""Write THIRD-PARTY-NOTICES.txt for the U-WAVE module package from the build environment.

The module is a frozen program (PyInstaller) that bundles Python, Tcl/Tk (for its setup window),
pyserial and the Open ERP module SDK. Their licences ask that the notices travel with the program, so
build_module.ps1 writes this file into the package next to LICENSE. Nothing is typed by hand: the text
comes from the metadata of the packages installed in the build environment, and a component without
licence text is reported so the build stops.

Usage:  python generate_notices.py <output file>
"""

from __future__ import annotations

import importlib.metadata as metadata
import platform
import re
import sys
from pathlib import Path

RULE = "=" * 78
ROOT = Path(__file__).resolve().parent
LICENSE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice)")
MIN_LICENSE_CHARS = 200
# Distributions the frozen module bundles besides Python itself.
BUNDLED = ("pyserial", "open-erp-module")
# pyserial's wheel carries no licence text, so the project's own LICENSE.txt, copied unchanged from the
# upstream source tag, is used for exactly that version. A different version must have its text checked
# and this entry updated (or the package must ship its own).
VENDORED_LICENSES = {"pyserial": ("3.5", "licenses/pyserial-3.5-LICENSE.txt")}


def license_files(distribution: metadata.Distribution) -> list[tuple[str, str]]:
    """(file name, text) for every licence file in the distribution's .dist-info folder."""
    texts = []
    for file in sorted(distribution.files or [], key=str):
        if file.parts and file.parts[0].endswith(".dist-info") and LICENSE_FILE.match(file.name):
            text = Path(distribution.locate_file(file)).read_text(encoding="utf-8", errors="replace")
            texts.append((file.name, text.replace("\r\n", "\n").strip("\n")))
    return texts


def license_summary(meta) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    first = text.splitlines()[0] if text else ""
    if first and len(first) <= 120:
        return first
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return "; ".join(classifiers) or first[:120] or "(not stated)"


def home_page(meta) -> str:
    url = meta.get("Home-page")
    if url:
        return url
    for entry in meta.get_all("Project-URL") or []:
        return entry.split(",", 1)[-1].strip()
    return ""


def section(title: str, license_name: str, url: str, note: str, texts: list[tuple[str, str]]) -> str:
    lines = [RULE, title, f"License: {license_name}"]
    if url:
        lines.append(f"Home page: {url}")
    if note:
        lines += ["", note]
    for name, text in texts:
        lines += ["", f"--- {name} ---", "", text]
    return "\n".join(lines)


def runtime_sections(problems: list[str]) -> list[str]:
    """Python itself, Tcl/Tk, the PyInstaller bootloader and the Microsoft C++ runtime."""
    sections = []
    base = Path(sys.base_prefix)
    python_license = base / "LICENSE.txt"
    if python_license.is_file():
        text = python_license.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip("\n")
        sections.append(section(f"Python {platform.python_version()}", "Python Software Foundation License",
                                "https://www.python.org/", "", [("LICENSE.txt", text)]))
    else:
        problems.append("Python: LICENSE.txt was not found in the Python installation.")
    tk_license = next(iter(sorted(base.rglob("license.terms"))), None)
    if tk_license is not None:
        text = tk_license.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip("\n")
        sections.append(section("Tcl/Tk (the toolkit behind the setup window)", "Tcl/Tk License (BSD-style)",
                                "https://www.tcl-lang.org/", "", [("license.terms", text)]))
    else:
        problems.append("Tcl/Tk: license.terms was not found in the Python installation.")
    try:
        pyinstaller = metadata.distribution("pyinstaller")
    except metadata.PackageNotFoundError:
        problems.append("PyInstaller: not installed, so its bootloader licence could not be included.")
    else:
        texts = license_files(pyinstaller)
        if texts:
            sections.append(section(
                f"PyInstaller {pyinstaller.version} (the bootloader inside mitutoyo-u-wave.exe)",
                "GPL-2.0-or-later with a special exception for programs built with PyInstaller",
                "https://pyinstaller.org/",
                "The bootloader is GPL-2.0-or-later with a special exception that lets it be used in any "
                "program,\nwhatever that program's licence. See the text below.", texts))
        else:
            problems.append("PyInstaller: no licence text was found.")
    sections.append(section(
        "Microsoft Visual C++ Runtime (VCRUNTIME140.dll, MSVCP140.dll and related files)",
        "Microsoft redistribution terms", "https://visualstudio.microsoft.com/",
        "These runtime libraries are redistributed unmodified under the redistribution terms Microsoft "
        "publishes for\nthe Visual C++ Redistributable.", []))
    return sections


def build_notices() -> tuple[str, list[str]]:
    """The full notices text and a list of problems (empty when every component has its licence text)."""
    problems: list[str] = []
    sections = runtime_sections(problems)
    for name in BUNDLED:
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name}: not installed in the build environment.")
            continue
        meta = distribution.metadata
        texts = license_files(distribution)
        vendored = VENDORED_LICENSES.get(name)
        if not texts and vendored and distribution.version == vendored[0]:
            text = (ROOT / vendored[1]).read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n")
            texts = [(f"LICENSE.txt (from the {name} {vendored[0]} source)", text)]
        if sum(len(text) for _, text in texts) < MIN_LICENSE_CHARS:
            problems.append(f"{meta['Name']} {distribution.version}: no full licence text was found.")
        sections.append(section(f"{meta['Name']} {distribution.version}", license_summary(meta), home_page(meta),
                                "", texts))
    header = "\n".join([
        "THIRD-PARTY NOTICES FOR THE U-WAVE MODULE",
        "",
        "The U-WAVE module is Copyright (C) 2026 TD Manufacturing and is licensed under the GNU Affero",
        "General Public License, version 3 or (at your option) any later version. See the LICENSE file in",
        "this folder. Its source code is at https://github.com/tjd10684-bit/U-wave-module (each release's",
        "source archive is on its releases page).",
        "",
        "The module includes the following software written by others. Each component remains under its",
        "own licence, reproduced below. This file was generated from the build environment by",
        "generate_notices.py.",
        "",
    ])
    return header + "\n" + "\n\n".join(sections) + "\n", problems


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print(__doc__)
        return 2
    text, problems = build_notices()
    output = Path(arguments[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {output} ({len(text):,} characters).")
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
