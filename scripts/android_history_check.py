"""Actual full SQLite owner/Java baseline on a disposable GitHub API35 emulator."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

from mobile.python import market, models, runtime
from scripts.android_lifecycle_check import PACKAGE, RUNNER, Controller
from scripts.mobile_native_history_fixture import (
    FORMAT,
    MOBILE_TABLES,
    ROOT,
    SOURCE_FILES,
    digest,
    isolated,
    table_snapshot,
)


def validate_fixture(folder: Path) -> dict:
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    payload = folder / "input.b64"
    if (
        report.get("format") != FORMAT
        or report.get("synthetic_only") is not True
        or report.get("status") != "passed"
        or report.get("symbols") != 5000
        or report.get("sessions") != 520
        or report.get("models") != 0
        or not 90_000_000 <= report.get("characters", 0) <= 128 * 1024 * 1024
        or set(report.get("source_sha256", {})) != set(SOURCE_FILES)
        or set(report.get("mobile", {}).get("tables", {})) != MOBILE_TABLES
        or payload.stat().st_size != report["characters"]
        or digest(payload) != report.get("payload_sha256")
    ):
        raise ValueError("Invalid synthetic full-history fixture")
    for name, expected in report["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Native fixture source changed")
    return report


def renderer_diagnostics(output: str) -> str:
    stages = (
        "reading-input|posting-input|decoding-input|interpreter|packages|archive|state|"
        "request|export|export-archive|export-chunks|staging-output"
    )
    selected = [line for line in output.splitlines() if "CONSOLE" not in line and (
        re.search(
            rf"StockAIComputeStage[^:]*: phase=({stages}) java_used=\d+ "
            r"available=\d+ low_memory=(true|false)$", line
        ) or re.search(
            r"(?:lmkd|lowmemorykiller)\s*[:(]|"
            r"(?:ActivityManager|chromium|libc|crash_dump64).*"
            r"(?:sandboxed_process|low memory|lowmemory|out of memory|Out of memory|"
            r"allocation failure|Fatal signal)", line
        )
    )]
    return "\n".join(selected[-500:])


def validate_native_evidence(evidence: dict, characters: int) -> None:
    portable = evidence.get("portable_backup", {})
    if not isinstance(portable, dict):
        raise ValueError("Invalid native portable-backup evidence")
    if (
        evidence.get("synthetic_only") is not True
        or evidence.get("phase") != "verified"
        or evidence.get("characters") != characters
        or not 0 < evidence.get("max_java_heap_bytes", 0) <= 192 * 1024 * 1024
        or portable.get("format") != "STOCKAIB1"
        or portable.get("status") != "restored"
        or not 90_000_000 <= portable.get("characters", 0) <= 128 * 1024 * 1024
        or not 90_000_000 <= portable.get("envelope_bytes", 0) <= 128 * 1024 * 1024
        or portable.get("native_preview_payload_absent") is not True
        or portable.get("profile_recovered") is not True
    ):
        raise ValueError("Native full-history/portable-backup evidence is incomplete")


class HistoryController(Controller):
    def stream(self, arguments: list[str], *, source=None, destination=None) -> None:
        if not self.guarded:
            raise RuntimeError("Disposable emulator guard is required")
        result = subprocess.run(
            self.command + arguments,
            stdin=source,
            stdout=destination if destination is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError("Native fixture stream failed")

    def run_history(self, fixture: Path, apks: Path) -> dict:
        # Validate all bytes before installing or writing anything to a device.
        original = validate_fixture(fixture)
        paths = {
            "application": apks / "debug/app-debug.apk",
            "tests": apks / "androidTest/debug/app-debug-androidTest.apk",
        }
        with zipfile.ZipFile(paths["application"]) as archive:
            build = json.loads(archive.read("assets/public/python/build-info.json"))
        if not os.environ.get("GITHUB_SHA") or build["source_commit"] != os.environ["GITHUB_SHA"]:
            raise ValueError("APK does not belong to this workflow source")
        self.guard()
        self.report = {
            "synthetic_only": True,
            "scope": (
                "Real full SQLite native owner/Java restore, profile/recreation "
                "and compatible portable backup"
            ),
            "source_commit": build["source_commit"],
            "input_sha256": original["payload_sha256"],
            "apk_sha256": {key: digest(path) for key, path in paths.items()},
            "status": "running",
        }
        for path in paths.values():
            self.adb("install", "-r", "-t", str(path), timeout=120)
        # Do not launch an Activity or create a second default interpreter.
        self.shell("run-as", PACKAGE, "mkdir", "-p", "files")
        with (fixture / "input.b64").open("rb") as source:
            self.stream(
                ["shell", f"run-as {PACKAGE} sh -c 'cat > files/native-history-input.b64'"],
                source=source,
            )
        observed = self.shell("run-as", PACKAGE, "sha256sum", "files/native-history-input.b64")
        if observed.split()[0] != original["payload_sha256"]:
            raise ValueError("Device fixture transfer changed")
        output = self.adb(
            "shell",
            "am",
            "instrument",
            "-w",
            "-r",
            "-e",
            "class",
            "jp.stockai.app.FullHistoryCapacityTest",
            "-e",
            "stockai.history.confirm",
            "fresh-emulator-only",
            "-e",
            "stockai.history.characters",
            str(original["characters"]),
            "-e",
            "stockai.history.sha256",
            original["payload_sha256"],
            RUNNER,
            timeout=720,
        ).decode(errors="replace")
        (self.output / "instrumentation.txt").write_text(output, encoding="utf-8")
        if "OK (1 test)" not in output or "FAILURES!!!" in output:
            raise RuntimeError("Full-history native instrumentation did not pass")
        evidence = json.loads(
            self.adb("exec-out", "run-as", PACKAGE, "cat", "files/native-history-proof.json")
        )
        validate_native_evidence(evidence, original["characters"])
        exported = self.output / "export.b64"
        with exported.open("xb") as destination:
            self.stream(
                ["exec-out", "run-as", PACKAGE, "cat", "files/native-history-export.b64"],
                destination=destination,
            )
        if not 90_000_000 <= exported.stat().st_size <= 128 * 1024 * 1024:
            raise ValueError("Invalid native export size")
        runtime.STATE = self.output / "restored"
        runtime.initialize(exported.read_text(encoding="ascii"))
        actual = table_snapshot(runtime.STATE / "mobile.sqlite3")
        if actual != original["mobile"]:
            raise ValueError("Mobile table schema/typed cells changed across the native owner")
        if market.status(runtime.STATE / "mobile.sqlite3")["completed_days"] != 520:
            raise ValueError("Native history is incomplete")
        if (
            models.status(runtime.STATE / "mobile.sqlite3", runtime._app.state.store)[
                "imported_bundle_count"
            ]
            != 0
        ):
            raise ValueError("Unexpected native fixture model")
        profile = asyncio.run(runtime.request("GET", "/api/v1/mobile/portfolio"))
        if profile["status"] != 200 or profile["body"] != evidence["portfolio"]:
            raise ValueError("Committed native portfolio did not survive export/restore")
        if digest(fixture / "input.b64") != original["payload_sha256"]:
            raise ValueError("Source fixture changed")
        self.report.update(
            status="passed",
            native=evidence,
            mobile=actual,
            export_sha256=digest(exported),
            source_unchanged=True,
        )
        return self.report

    def collect(self) -> None:
        if not self.guarded:
            return
        events = self.adb(
            "logcat", "-d", "-v", "raw", "-s", "StockAIHistoryCapacity:I", "*:S", required=False
        ).decode(errors="replace")
        (self.output / "events.txt").write_text(events, encoding="utf-8")
        crash = self.adb("logcat", "-b", "crash", "-d", "-v", "brief", required=False)
        lines = [
            line
            for line in crash.decode(errors="replace").splitlines()
            if re.search(
                r"OutOfMemoryError|Fatal signal|at jp\.stockai\.app\.|at org\.json\."
                r"|at java\.lang\.(?:String|AbstractStringBuilder)|at java\.io\.StringWriter",
                line,
            )
        ]
        (self.output / "capacity-stack.txt").write_text("\n".join(lines), encoding="utf-8")
        # Fixed stage enums/aggregate memory and emulator-only renderer/LMK
        # events; never retain general WebView console or application payloads.
        renderer = self.adb("logcat", "-d", "-v", "brief", required=False).decode(errors="replace")
        (self.output / "renderer-memory.txt").write_text(
            renderer_diagnostics(renderer), encoding="utf-8"
        )
        try:
            self.report["latest_native_phase"] = json.loads(
                self.adb("exec-out", "run-as", PACKAGE, "cat", "files/native-history-proof.json")
            )
        except (ValueError, RuntimeError, subprocess.TimeoutExpired, OSError):
            self.report["latest_native_phase"] = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--apks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        raise ValueError("Run from the repository root")
    output = isolated(args.output)
    if output.exists():
        raise ValueError("Use a fresh native evidence folder")
    controller = HistoryController(output)
    try:
        controller.run_history(isolated(args.fixture), isolated(args.apks))
    except Exception as error:
        controller.report.update(status="failed", error_type=type(error).__name__, code=str(error))
        raise
    finally:
        try:
            controller.collect()
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as error:
            controller.report["diagnostic_error_type"] = type(error).__name__
        (output / "report.json").write_text(
            json.dumps(controller.report, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
