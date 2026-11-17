"""Test a module against the Open ERP module protocol, without Open ERP.

    python -m open_erp_module.host_check MODULE_FOLDER [options] [-- COMMAND ...]

Starts the module the way Open ERP does, runs the handshake, asks for its linked assets, optionally
opens its setup window and takes a capture, checks that an unknown method is refused, then shuts it
down. Each step prints PASS or FAIL; the exit code is 0 only when every step passes.

After ``--``, give a command to run instead of the manifest's program, for example
``-- python my_module.py`` while developing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from uuid import uuid4

from .manifest import ManifestProblem, load, packaged_program_problem
from .runtime import PROTOCOL_VERSION

INITIALIZE_SECONDS, REQUEST_SECONDS, SHUTDOWN_SECONDS, EXIT_SECONDS = 15.0, 5.0, 3.0, 2.0
_EOF = object()


class CheckFailed(Exception):
    pass


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not valid JSON")


class ModuleSession:
    """A module process and a minimal JSON-RPC client for it."""

    def __init__(self, command: list[str], cwd: Path, *, verbose: bool):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags,
        )
        self.verbose = verbose
        self.incoming: queue.Queue = queue.Queue()
        self.problems: list[str] = []
        self.notifications: list[dict] = []
        self.stderr_tail: list[str] = []
        self.next_id = 1
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        for raw in self.process.stdout:
            text = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not text.strip():
                continue
            try:
                message = json.loads(text, parse_constant=_reject_constant)
            except ValueError:
                self.problems.append(f"stdout carried something that is not a protocol message: {text[:200]!r}")
                continue
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                self.problems.append(f"stdout carried a message that is not JSON-RPC 2.0: {text[:200]!r}")
                continue
            self.incoming.put(message)
        self.incoming.put(_EOF)

    def _read_stderr(self) -> None:
        for raw in self.process.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            self.stderr_tail = (self.stderr_tail + [line])[-20:]
            if self.verbose:
                print(f"    module: {line}", file=sys.stderr)

    def send(self, message: dict) -> None:
        try:
            self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
            self.process.stdin.flush()
        except OSError as error:
            raise CheckFailed(f"could not write to the module: {error}") from error

    def request(self, method: str, params: Any = None, timeout: float | None = REQUEST_SECONDS) -> dict:
        request_id = self.next_id
        self.next_id += 1
        message: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise CheckFailed(f"no answer to {method} within {timeout:g} seconds")
            try:
                reply = self.incoming.get(timeout=remaining)
            except queue.Empty:
                continue
            if reply is _EOF:
                code = self.process.poll()
                raise CheckFailed(f"the module stopped while answering {method} (exit code {code})")
            if "method" in reply:
                if "id" in reply:
                    self.problems.append(f"the module sent a request ({reply['method']}); Open ERP does not answer those")
                else:
                    self.notifications.append(reply)
                continue
            if reply.get("id") != request_id:
                self.problems.append(f"an answer arrived for unknown id {reply.get('id')!r}")
                continue
            if ("result" in reply) == ("error" in reply):
                raise CheckFailed(f"the answer to {method} needs exactly one of result or error")
            if "error" in reply:
                error = reply["error"]
                if not isinstance(error, dict) or type(error.get("code")) is not int or not isinstance(
                    error.get("message"), str
                ):
                    raise CheckFailed(f"the error answer to {method} needs an integer code and a text message")
            return reply

    def close(self) -> int | None:
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            return self.process.wait(EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            return None


class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def passed(self, step: str, detail: str = "") -> None:
        print(f"PASS  {step}{': ' + detail if detail else ''}")

    def failed(self, step: str, detail: str) -> None:
        self.failures += 1
        print(f"FAIL  {step}: {detail}")

    def warn(self, step: str, detail: str) -> None:
        print(f"WARN  {step}: {detail}")


def _aware_time(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise CheckFailed(f"{name} must be an ISO 8601 time")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise CheckFailed(f"{name} is not an ISO 8601 time: {value!r}") from error
    if parsed.tzinfo is None:
        raise CheckFailed(f"{name} must include a timezone")
    return parsed


def check_reading(result: Any, request: dict, mode: str) -> str:
    if not isinstance(result, dict):
        raise CheckFailed("the capture result must be an object")
    for name in ("capture_id", "asset_id"):
        if result.get(name) != request[name]:
            raise CheckFailed(f"{name} must echo the request ({request[name]!r}), got {result.get(name)!r}")
    value = result.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CheckFailed(f"value must be a finite number, got {value!r}")
    if result.get("units") not in ("mm", "in"):
        raise CheckFailed(f"units must be mm or in, got {result.get('units')!r}")
    source = result.get("source_id")
    if not isinstance(source, str) or not source.strip():
        raise CheckFailed("source_id must be nonempty text")
    received = _aware_time(result.get("received_at"), "received_at")
    requested = datetime.fromisoformat(request["requested_at"])
    if received < requested:
        raise CheckFailed("received_at is before the request was made")
    if received > datetime.now(timezone.utc):
        raise CheckFailed("received_at is in the future")
    if result.get("sampled_at") is not None:
        _aware_time(result["sampled_at"], "sampled_at")
    if result.get("acquisition_mode") != mode:
        raise CheckFailed(f"acquisition_mode must repeat the declared {mode!r}")
    note = "" if result["units"] == request["units"] else f" (Open ERP will reject: {request['units']} was requested)"
    return f"{value:g} {result['units']} from {source}{note}"


def run_checks(options: argparse.Namespace, command: list[str]) -> int:
    check = Checker()
    folder = options.folder.resolve()
    try:
        manifest = load(folder)
    except ManifestProblem as error:
        check.failed("module.toml", str(error))
        return 1
    check.passed("module.toml", f"{manifest.name} {manifest.version} ({manifest.module_id})")
    problem = packaged_program_problem(manifest, folder)
    if problem:
        (check.warn if command else check.failed)("package", problem)
    if not command:
        command = [str(manifest.program_path(folder)), *manifest.args]
    data_dir = Path(options.data_dir).resolve() if options.data_dir else Path(tempfile.mkdtemp(prefix="module-check-"))
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        session = ModuleSession(command, folder, verbose=options.verbose)
    except OSError as error:
        check.failed("start", f"could not start {command[0]}: {error}")
        return 1
    mode = "latest"
    try:
        started = time.monotonic()
        reply = session.request("initialize", {
            "protocol_version": PROTOCOL_VERSION, "host": {"name": "host_check", "version": ""},
            "module_id": manifest.module_id, "data_dir": str(data_dir),
        }, timeout=INITIALIZE_SECONDS)
        result = reply.get("result")
        if "error" in reply:
            raise CheckFailed(f"initialize failed: {reply['error']['message']}")
        module = result.get("module") if isinstance(result, dict) else None
        if not isinstance(result, dict) or result.get("protocol_version") != PROTOCOL_VERSION:
            raise CheckFailed(f"protocol_version must be {PROTOCOL_VERSION}")
        if not isinstance(module, dict) or module.get("id") != manifest.module_id:
            raise CheckFailed(f"module.id must be {manifest.module_id!r} (from module.toml)")
        mode = result.get("acquisition_mode")
        if mode not in ("latest", "fresh"):
            raise CheckFailed("acquisition_mode must be 'latest' or 'fresh'")
        check.passed("initialize", f"{mode} capture, answered in {time.monotonic() - started:.1f} s")
        if module.get("version") != manifest.version:
            check.warn("initialize", f"the program reports version {module.get('version')!r}; module.toml says {manifest.version!r}")

        def linked() -> list[str]:
            answer = session.request("linked_assets")
            assets = answer.get("result", {}).get("asset_ids") if isinstance(answer.get("result"), dict) else None
            if "error" in answer:
                raise CheckFailed(answer["error"]["message"])
            if not isinstance(assets, list) or not all(isinstance(item, str) and item.strip() for item in assets):
                raise CheckFailed("asset_ids must be a list of nonempty text values")
            return assets

        assets = linked()
        check.passed("linked_assets", ", ".join(assets) or "none linked")

        if options.setup:
            equipment = [
                {"asset_id": asset, "tag": f"CHECK-{index}", "name": f"Check asset {index}", "category": "Check"}
                for index, asset in enumerate(options.asset or ["host-check-asset"], start=1)
            ]
            print("....  open_setup: waiting for the module's setup window to close")
            answer = session.request("open_setup", {"equipment": equipment}, timeout=None)
            if "error" in answer:
                check.failed("open_setup", answer["error"]["message"])
            else:
                assets = linked()
                check.passed("open_setup", f"linked after setup: {', '.join(assets) or 'none'}")

        if options.capture:
            request = {
                "capture_id": f"check-{uuid4()}", "asset_id": options.capture, "units": options.units,
                "input_name": "measurement", "requested_at": datetime.now(timezone.utc).isoformat(),
                "timeout_seconds": REQUEST_SECONDS,
            }
            answer = session.request("capture", request, timeout=REQUEST_SECONDS + 1)
            if "error" in answer:
                check.failed("capture", f"the module refused: {answer['error']['message']}")
            else:
                try:
                    check.passed("capture", check_reading(answer["result"], request, mode))
                except CheckFailed as error:
                    check.failed("capture", str(error))

        answer = session.request("host_check.unknown_method")
        if answer.get("error", {}).get("code") == -32601:
            check.passed("unknown method", "refused with -32601")
        else:
            check.failed("unknown method", "unknown requests must be answered with error -32601")

        answer = session.request("shutdown", timeout=SHUTDOWN_SECONDS)
        if "error" in answer:
            check.failed("shutdown", answer["error"]["message"])
        else:
            check.passed("shutdown")
    except CheckFailed as error:
        check.failed("protocol", str(error))
    finally:
        code = session.close()
        if code is None:
            check.failed("exit", f"still running {EXIT_SECONDS:g} s after stdin closed; it was killed")
        else:
            check.passed("exit", f"exit code {code}")
        for note in session.notifications:
            if note.get("method") == "status":
                print(f"      status: {note.get('params')}")
        for problem in dict.fromkeys(session.problems):
            check.failed("stdout", problem)
        if check.failures and session.stderr_tail and not options.verbose:
            print("      last stderr lines:")
            for line in session.stderr_tail:
                print(f"        {line}")
        if not options.data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)
    print("All checks passed." if not check.failures else f"{check.failures} check(s) failed.")
    return 0 if not check.failures else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(
        prog="python -m open_erp_module.host_check", description=__doc__.splitlines()[0],
        epilog="After --, give a command to run instead of the manifest's program.",
    )
    parser.add_argument("folder", type=Path, help="module folder containing module.toml")
    parser.add_argument("--capture", metavar="ASSET_ID", help="take one reading for this asset id")
    parser.add_argument("--units", choices=("mm", "in"), default="mm", help="units to request (default mm)")
    parser.add_argument("--setup", action="store_true", help="open the module's setup window")
    parser.add_argument("--asset", action="append", metavar="ASSET_ID", help="asset offered to setup (repeatable)")
    parser.add_argument("--data-dir", help="settings folder to use (default: a temporary folder)")
    parser.add_argument("-v", "--verbose", action="store_true", help="show the module's stderr as it runs")
    return run_checks(parser.parse_args(argv), command)


if __name__ == "__main__":
    raise SystemExit(main())
