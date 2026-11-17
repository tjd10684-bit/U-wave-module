"""Check ``module.toml`` against the rules in PROTOCOL.md before packaging or testing a module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tomllib

from .runtime import PROTOCOL_VERSION

MANIFEST_NAME = "module.toml"
_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,39}$")
RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{n}" for n in range(1, 10)} | {f"lpt{n}" for n in range(1, 10)}
)


class ManifestProblem(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    module_id: str
    name: str
    version: str
    publisher: str
    protocol: int
    kind: str
    program: str
    args: tuple[str, ...]
    description: str

    def program_path(self, folder: Path) -> Path:
        program = Path(self.program)
        return program if program.is_absolute() else folder / program


def _text(table: dict, key: str, limit: int, *, required: bool = True) -> str:
    value = table.get(key, "")
    if not isinstance(value, str):
        raise ManifestProblem(f"{key} must be text.")
    value = value.strip()
    if required and not value:
        raise ManifestProblem(f"{key} is required.")
    if len(value) > limit or any(ord(character) < 32 for character in value):
        raise ManifestProblem(f"{key} must be at most {limit} printable characters.")
    return value


def reserved(name: str) -> bool:
    return name.split(".", 1)[0].lower() in RESERVED_NAMES


def parse(text: str) -> Manifest:
    if text.startswith("\ufeff"):
        raise ManifestProblem("module.toml starts with a byte order mark; save it as UTF-8 without a BOM.")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ManifestProblem(f"module.toml is not valid TOML: {error}") from error
    module_id = data.get("id")
    if not isinstance(module_id, str) or not _ID.match(module_id) or reserved(module_id):
        raise ManifestProblem(
            "id must be 1-64 lowercase letters, digits, '.', '_' or '-', start and end with a letter "
            "or digit, and not be a reserved Windows name."
        )
    protocol = data.get("protocol")
    if type(protocol) is not int or protocol < 1:
        raise ManifestProblem("protocol must be a positive whole number.")
    if protocol != PROTOCOL_VERSION:
        raise ManifestProblem(f"protocol is {protocol}; this SDK implements protocol {PROTOCOL_VERSION}.")
    kind = _text(data, "kind", 40)
    if kind != "measurement":
        raise ManifestProblem("kind must be \"measurement\".")
    version = _text(data, "version", 40)
    if not _VERSION.match(version):
        raise ManifestProblem("version may use letters, digits, '.', '+' and '-' only.")
    run = data.get("run")
    if not isinstance(run, dict):
        raise ManifestProblem("A [run] table naming the program is required.")
    program = _text(run, "program", 260)
    args = run.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ManifestProblem("run.args must be a list of text values.")
    return Manifest(
        module_id=module_id, name=_text(data, "name", 80), version=version, publisher=_text(data, "publisher", 80),
        protocol=protocol, kind=kind, program=program, args=tuple(args),
        description=_text(data, "description", 500, required=False),
    )


def load(folder: Path) -> Manifest:
    path = folder / MANIFEST_NAME
    try:
        return parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ManifestProblem(f"{path} is missing.") from error
    except (OSError, UnicodeDecodeError) as error:
        raise ManifestProblem(f"{path} could not be read: {error}") from error


def packaged_program_problem(manifest: Manifest, folder: Path) -> str:
    """Why this manifest's program cannot ship in a package, or an empty string."""
    windows, posix = PureWindowsPath(manifest.program), PurePosixPath(manifest.program)
    if windows.anchor or posix.anchor:
        return "run.program must be a path inside the module folder for a package, not an absolute path."
    if ".." in windows.parts:
        return "run.program must not contain '..'."
    if not (folder / manifest.program).is_file():
        return f"run.program {manifest.program!r} is not in {folder}."
    return ""
