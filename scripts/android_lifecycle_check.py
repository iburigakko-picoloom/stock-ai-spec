"""Exercise real scheduled workers on a disposable GitHub Android emulator only.

No fake transport is installed in the application. The test APK seeds synthetic
native receipts; the unchanged worker must commit/acknowledge them after OS loss.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

PACKAGE = "jp.stockai.app.debug"
RUNNER = PACKAGE + ".test/androidx.test.runner.AndroidJUnitRunner"
CASE = "jp.stockai.app.DailyLifecycleTest"
DATABASE = "databases/stockai-device.sqlite3"
NAMESPACE = "androidx.work.systemjobscheduler"


class DeliveryDeferred(RuntimeError):
    """A readable pending receipt was not delivered within the observation window."""


class Controller:
    def __init__(self, output: Path, *, dispatch_ready: bool = False) -> None:
        workspace = Path.cwd().resolve()
        self.output = output.resolve()
        if not self.output.is_relative_to(workspace) or self.output == workspace:
            raise ValueError("Evidence must remain in this workspace")
        self.output.mkdir(parents=True, exist_ok=True)
        self.command = ["adb"]
        self.guarded = False
        self.dispatch_ready = dispatch_ready
        self.report: dict = {
            "synthetic_only": True,
            "delivery_policy": (
                "screen-wake-then-scheduler-satisfied" if dispatch_ready else "unforced"
            ),
            "phases": [],
            "status": "running",
        }

    def adb(self, *args: str, timeout: int = 40, required: bool = True) -> bytes:
        result = subprocess.run(self.command + list(args), capture_output=True, timeout=timeout)
        if required and result.returncode:
            # No credentials or provider payloads are passed to this controller.
            raise RuntimeError(f"adb {args[:3]} failed: {result.stderr.decode(errors='replace')}")
        return result.stdout if result.returncode == 0 else b""

    def shell(self, *args: str, **kwargs) -> str:
        return self.adb("shell", *args, **kwargs).decode(errors="replace").strip()

    def guard(self) -> None:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("This destructive fixture reset is restricted to GitHub CI")
        temporary = os.environ.get("RUNNER_TEMP")
        if not temporary or os.environ.get("ANDROID_AVD_HOME") != str(
            Path(temporary) / "stockai-avd"
        ):
            raise RuntimeError("Refusing an emulator outside the workflow's disposable AVD")
        serial = self.adb("get-serialno").decode().strip()
        if not re.fullmatch(r"emulator-\d+", serial):
            raise RuntimeError("Refusing any non-emulator device")
        self.command += ["-s", serial]
        if self.shell("getprop", "ro.kernel.qemu") != "1":
            raise RuntimeError("Emulator identity not established")
        if self.shell("am", "get-current-user") != "0":
            raise RuntimeError("Only the isolated emulator's primary user is supported")
        if self.shell("getprop", "ro.build.version.sdk") != "35":
            raise RuntimeError("This lifecycle acceptance run targets the isolated API35 emulator")
        self.guarded = True
        self.report.update(serial=serial, sdk=self.shell("getprop", "ro.build.version.sdk"))

    def pid(self) -> str:
        return self.shell("pidof", PACKAGE, required=False)

    def marker(self) -> dict:
        return json.loads(
            self.adb("exec-out", "run-as", PACKAGE, "cat", "files/lifecycle-proof.json")
        )

    def ensure_process(self) -> None:
        if not self.pid():
            # Explicit bootstrap is outside the loss/ACK observation window.
            # no-restart instrumentation requires an already running process.
            self.shell(
                "am", "start", "-W", "-n", PACKAGE + "/jp.stockai.app.MainActivity", timeout=60
            )
            self.shell("input", "keyevent", "KEYCODE_HOME")
            end = time.monotonic() + 15
            while not self.pid() and time.monotonic() < end:
                time.sleep(0.2)
            if not self.pid():
                raise RuntimeError("Could not create the instrumentation host process")

    def instrument(self, method: str, phase: str) -> None:
        self.ensure_process()
        # Ordinary instrumentation force-stops its target when it finishes.
        # API31+ no-restart preserves the pending jobs for the OS-loss test.
        result = self.shell(
            "am",
            "instrument",
            "-w",
            "--no-restart",
            "-e",
            "class",
            CASE + "#" + method,
            "-e",
            "stockai.lifecycle.confirm",
            "fresh-emulator-only",
            "-e",
            "stockai.lifecycle.phase",
            phase,
            RUNNER,
            timeout=260,
        )
        (self.output / f"{phase}-{method}.txt").write_text(result, encoding="utf-8")
        if (
            "OK (1 test)" not in result
            or "FAILURES!!!" in result
            or "INSTRUMENTATION_FAILED" in result
        ):
            raise RuntimeError(f"Lifecycle instrumentation failed: {phase}/{method}")

    def snapshot(self, acquisition: str) -> dict:
        folder = self.output / "snapshot"
        folder.mkdir(exist_ok=True)
        path = folder / "native.sqlite3"
        for suffix in ("", "-wal"):
            value = self.adb(
                "exec-out", "run-as", PACKAGE, "cat", DATABASE + suffix, required=not suffix
            )
            target = Path(str(path) + suffix)
            if value:
                target.write_bytes(value)
            elif suffix:
                target.unlink(missing_ok=True)
        # This is an observational copy. Never open the device's DB through a
        # second writer, decrypt its state, or treat a failed observation as stop.
        with sqlite3.connect(path, timeout=1) as connection:
            generation = connection.execute("SELECT generation FROM state WHERE id=1").fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM market_download_pages WHERE id=?", (acquisition,)
            ).fetchone()[0]
            row = connection.execute(
                "SELECT state,updated_at FROM daily_automation WHERE id=1"
            ).fetchone()
        return {
            "generation": generation,
            "pending_pages": pending,
            "state": row[0],
            "updated_at": row[1],
        }

    def wait_ack(self, marker: dict, *, seconds: int = 200) -> dict:
        target = marker["targets"][-1]
        deadline = time.monotonic() + seconds
        errors = 0
        latest = None
        while time.monotonic() < deadline:
            try:
                latest = self.snapshot(target["id"])
                if latest["pending_pages"] == 0 and latest["generation"] > marker["generation"]:
                    latest["observed_pid"] = self.pid()
                    return latest
            except (sqlite3.Error, OSError, RuntimeError, IndexError, TypeError):
                errors += 1
            time.sleep(2)
        error = (
            DeliveryDeferred
            if latest is not None and latest["pending_pages"] > 0 and errors == 0
            else RuntimeError
        )
        raise error(
            f"Same scheduled acquisition not acknowledged: {latest}; observation_errors={errors}"
        )

    def dispatch_ready_job(self, marker: dict, phase: str) -> None:
        if not self.guarded:
            raise RuntimeError("Scheduler commands require the disposable-emulator guard")
        job = marker["system_job"]
        if job["namespace"] != NAMESPACE or type(job["id"]) is not int or job["id"] < 0:
            raise RuntimeError("Invalid prepared scheduler identity")
        # -s preserves every constraint. Do not use -f, change device policy,
        # enqueue replacement work or call the worker/core from instrumentation.
        result = self.shell(
            "cmd", "jobscheduler", "run", "-s", "-u", "0", "-n", NAMESPACE,
            PACKAGE, str(job["id"]),
        )
        (self.output / f"{phase}-scheduler-dispatch.txt").write_text(result, encoding="utf-8")
        if "Running job" not in result or "[FORCED]" in result:
            raise RuntimeError("The prepared job was not dispatched with constraints satisfied")

    def observe_delivery(self, prepared: dict, phase: str) -> dict:
        if not self.dispatch_ready:
            return {**self.wait_ack(prepared), "delivery": "unforced"}
        try:
            return {**self.wait_ack(prepared, seconds=90), "delivery": "unforced"}
        except DeliveryDeferred:
            self.diagnostics(phase + "-deferred")
            # API35 can leave an overdue TIMING_DELAY unsatisfied while asleep.
            # Allow ordinary alarm delivery by waking the display briefly, then
            # restore sleep before observing ACK. This is explicit intervention,
            # not proof of natural wake-up; no clock/power policy is changed.
            self.shell("input", "keyevent", "KEYCODE_WAKEUP")
            time.sleep(2)
            self.shell("input", "keyevent", "KEYCODE_SLEEP")
            try:
                return {**self.wait_ack(prepared, seconds=3), "delivery": "screen-wake"}
            except DeliveryDeferred:
                pass
            self.dispatch_ready_job(prepared, phase)
            return {**self.wait_ack(prepared), "delivery": "screen-wake-and-scheduler-satisfied"}

    def stopped(self) -> bool:
        result = self.shell("dumpsys", "package", PACKAGE)
        matched = re.search(r"User 0:.*\bstopped=(true|false)", result)
        if not matched:
            raise RuntimeError("Package stopped flag could not be observed")
        return matched[1] == "true"

    def diagnostics(self, name: str) -> None:
        for service in ("power", "jobscheduler", "activity"):
            value = self.shell("dumpsys", service, required=False)
            (self.output / f"{name}-{service}.txt").write_text(value, encoding="utf-8")

    def execute(self) -> None:
        self.guard()
        self.adb(
            "install", "-r", "web/android/app/build/outputs/apk/debug/app-debug.apk", timeout=90
        )
        self.adb(
            "install",
            "-r",
            "web/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk",
            timeout=90,
        )
        if self.shell("pm", "clear", "--user", "0", PACKAGE) != "Success":
            raise RuntimeError("Could not reset the disposable fixture application")
        self.shell("input", "keyevent", "KEYCODE_WAKEUP")
        self.shell("wm", "dismiss-keyguard")
        for phase in ("process", "reboot", "force-stop"):
            self.instrument("prepare", phase)
            prepared = self.marker()
            target = prepared["targets"][-1]
            before = self.snapshot(target["id"])
            if before["pending_pages"] == 0 or self.stopped():
                raise RuntimeError("Preparation did not leave a live, pending acquisition")
            self.shell("input", "keyevent", "KEYCODE_SLEEP")
            boot_before = self.shell("cat", "/proc/sys/kernel/random/boot_id")
            if phase == "process":
                self.shell("am", "kill", "--user", "0", PACKAGE)
                deadline = time.monotonic() + 10
                while self.pid() and time.monotonic() < deadline:
                    time.sleep(0.2)
                if self.pid() or self.stopped():
                    raise RuntimeError("Process loss was not established without force-stop")
            elif phase == "reboot":
                self.adb("reboot")
                self.adb("wait-for-device", timeout=150)
                deadline = time.monotonic() + 150
                while self.shell("getprop", "sys.boot_completed", required=False) != "1":
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Emulator did not finish reboot")
                    time.sleep(2)
                if boot_before == self.shell("cat", "/proc/sys/kernel/random/boot_id"):
                    raise RuntimeError("Kernel reboot was not established")
                self.shell("input", "keyevent", "KEYCODE_WAKEUP")
                self.shell("wm", "dismiss-keyguard")
                self.shell("input", "keyevent", "KEYCODE_SLEEP")
            else:
                self.shell("am", "force-stop", "--user", "0", PACKAGE)
                # Observe beyond the requested 60s delay without opening the
                # app, injecting instrumentation, or forcing a scheduler run.
                for _ in range(35):
                    time.sleep(2)
                    if self.pid():
                        raise RuntimeError("Force-stopped application unexpectedly restarted")
                paused = self.snapshot(target["id"])
                if (
                    self.pid()
                    or not self.stopped()
                    or paused["pending_pages"] != before["pending_pages"]
                    or paused["generation"] != before["generation"]
                ):
                    raise RuntimeError("Force-stop did not preserve pending state until reopening")
                self.shell(
                    "am", "start", "-W", "-n", PACKAGE + "/jp.stockai.app.MainActivity", timeout=60
                )
                self.shell("input", "keyevent", "KEYCODE_SLEEP")
            observed = self.observe_delivery(prepared, phase)
            power = self.shell("dumpsys", "power")
            if not re.search(r"mWakefulness=(Asleep|Dozing)", power):
                raise RuntimeError("Display was not asleep during the accepted observation")
            self.diagnostics(phase)
            # Verification begins only after observing a native ACK and a new
            # durable generation. It cannot be the cause of worker dispatch.
            self.instrument("verify", phase)
            verified = self.marker()
            if verified["stage"] != "verified":
                raise RuntimeError("Shared receipt verification did not finish")
            self.report["phases"].append(
                {
                    "phase": phase,
                    "prepared_pid": prepared["pid"],
                    **observed,
                    "verified_pid": verified["verified_pid"],
                    "preserved_targets": len(verified["targets"]),
                    "notification_permission": "denied",
                    "activity_destroyed": verified["activity_destroyed"],
                }
            )
            self.write_report()
        self.report["status"] = "passed"
        self.write_report()

    def write_report(self) -> None:
        (self.output / "lifecycle-report.json").write_text(
            json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".demo-artifacts/android-lifecycle"))
    parser.add_argument(
        "--dispatch-ready", action="store_true",
        help=(
            "After an unforced observation, briefly wake/sleep the display, then ask "
            "JobScheduler to run the existing job with all constraints satisfied; "
            "this does not prove natural wake-up or delivery timing"
        ),
    )
    args = parser.parse_args()
    controller = Controller(args.output, dispatch_ready=args.dispatch_ready)
    try:
        controller.execute()
    except Exception:
        controller.report["status"] = "failed"
        controller.write_report()
        if controller.guarded:
            controller.diagnostics("failure")
        raise


if __name__ == "__main__":
    main()
