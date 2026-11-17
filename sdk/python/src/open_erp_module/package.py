"""Build an Open ERP module package (.zip) from a module folder.

    python -m open_erp_module.package MODULE_FOLDER [-o OUTPUT.zip]

The folder must contain ``module.toml`` and the program it names. Everything in the folder except
``__pycache__`` goes into the package, with ``module.toml`` at the top level.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import zipfile

from .manifest import MANIFEST_NAME, ManifestProblem, load, packaged_program_problem, reserved

MAX_FILES = 20_000
MAX_BYTES = 1024 ** 3


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def build_package(folder: Path, output: Path | None = None) -> Path:
    folder = folder.resolve()
    manifest = load(folder)
    problem = packaged_program_problem(manifest, folder)
    if problem:
        raise ManifestProblem(problem)
    output = (output or Path.cwd() / f"{manifest.module_id}-{manifest.version}.zip").resolve()
    partial = output.with_name(output.name + ".partial")
    files: list[tuple[Path, str]] = []
    total = 0
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if "__pycache__" in relative.parts or path in (output, partial):
            continue
        if _is_link(path):
            raise ManifestProblem(f"{relative} is a link; packages cannot contain links.")
        if path.is_dir():
            continue
        for part in relative.parts:
            if reserved(part) or part.endswith((".", " ")) or any(ord(character) < 32 for character in part):
                raise ManifestProblem(f"{relative} has a name Windows cannot store safely.")
        total += path.stat().st_size
        files.append((path, relative.as_posix()))
    if len(files) > MAX_FILES or total > MAX_BYTES:
        raise ManifestProblem("The module is too large: packages are limited to 20,000 files and 1 GB.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(folder / MANIFEST_NAME, MANIFEST_NAME)
        for path, name in files:
            if name != MANIFEST_NAME:
                archive.write(path, name)
    os.replace(partial, output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m open_erp_module.package", description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="module folder containing module.toml and the program")
    parser.add_argument("-o", "--output", type=Path, help="package file to write (default: <id>-<version>.zip)")
    options = parser.parse_args(argv)
    try:
        package = build_package(options.folder, options.output)
    except (ManifestProblem, OSError) as error:
        print(f"Cannot package {options.folder}: {error}", file=sys.stderr)
        return 1
    print(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
