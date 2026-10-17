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
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

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
                "SELECT state,updated_at,enabled,first_day,day,failures,retry_at "
                "FROM daily_automation WHERE id=1"
            ).fetchone()
        return {
            "generation": generation,
            "pending_pages": pending,
            "state": row[0],
            "updated_at": row[1],
            "enabled": bool(row[2]),
            "first_day": row[3],
            "day": row[4],
            "failures": row[5],
            "retry_at": row[6],
        }

    def wait_ack(
        self, marker: dict, *, seconds: int = 200, on_wait: Callable[[], None] | None = None
    ) -> dict:
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
            else:
                if on_wait is not None and latest["pending_pages"] > 0:
                    on_wait()
            time.sleep(2)
        error = (
            DeliveryDeferred
            if latest is not None and latest["pending_pages"] > 0 and errors == 0
            else RuntimeError
        )
        raise error(
            f"Same scheduled acquisition not acknowledged: {latest}; observation_errors={errors}"
        )

    def work_database_snapshot(self) -> Path:
        if not self.guarded:
            raise RuntimeError("WorkManager observation requires the disposable-emulator guard")
        folder = self.output / "scheduler-snapshot"
        folder.mkdir(exist_ok=True)
        path = folder / "work.sqlite3"
        for name in ("no_backup/androidx.work.workdb", "databases/androidx.work.workdb"):
            value = self.adb("exec-out", "run-as", PACKAGE, "cat", name, required=False)
            if value:
                path.write_bytes(value)
                wal = self.adb("exec-out", "run-as", PACKAGE, "cat", name + "-wal", required=False)
                if wal:
                    Path(str(path) + "-wal").write_bytes(wal)
                else:
                    Path(str(path) + "-wal").unlink(missing_ok=True)
                return path
        raise RuntimeError("WorkManager database could not be observed")

    def current_system_job(self, marker: dict) -> dict:
        work_id = marker.get("work_id")
        try:
            valid_id = isinstance(work_id, str) and str(UUID(work_id)) == work_id
        except ValueError:
            valid_id = False
        if not valid_id:
            raise RuntimeError("Invalid original WorkRequest identity")
        path = self.work_database_snapshot()
        # Query an observational copy, never a second device writer. A boot
        # reconciliation may assign another OS job ID to the same WorkSpec.
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1) as connection:
            row = connection.execute(
                "SELECT generation,state,worker_class_name FROM WorkSpec WHERE id=?", (work_id,)
            ).fetchone()
            if row is None or row[2] != "jp.stockai.app.DailyWorker":
                raise RuntimeError("Original daily WorkRequest could not be verified")
            generation, state = row[:2]
            if type(generation) is not int or generation < 0 or state not in range(6):
                raise RuntimeError("Invalid WorkRequest generation or state")
            jobs = connection.execute(
                "SELECT system_id FROM SystemIdInfo WHERE work_spec_id=? AND generation=?",
                (work_id, generation),
            ).fetchall()
        if len(jobs) > 1 or (jobs and (type(jobs[0][0]) is not int or jobs[0][0] < 0)):
            raise RuntimeError("Ambiguous or invalid current scheduler identity")
        return {
            "work_id": work_id,
            "generation": generation,
            "work_state": state,
            "namespace": NAMESPACE,
            "id": jobs[0][0] if jobs else None,
        }

    def dispatch_ready_job(self, marker: dict, phase: str) -> dict:
        if not self.guarded:
            raise RuntimeError("Scheduler commands require the disposable-emulator guard")
        job = marker["system_job"]
        if job["namespace"] != NAMESPACE or type(job["id"]) is not int or job["id"] < 0:
            raise RuntimeError("Invalid prepared scheduler identity")
        observations = []
        outcome = {
            "scheduler_attempted": False,
            "scheduler_dispatched": False,
            "scheduler_observations": observations,
        }

        def observed(action: str, dispatched: bool = False) -> dict:
            outcome.update(scheduler_action=action, scheduler_dispatched=dispatched)
            self.scheduler_evidence(marker, phase, outcome)
            return outcome

        for _ in range(2):
            current = self.current_system_job(marker)
            if current["work_id"] != marker.get("work_id") or current["namespace"] != NAMESPACE:
                raise RuntimeError("Current scheduler identity is not the original work")
            observations.append(current)
            observed("identity-read")
            if current["work_state"] in (3, 5):
                raise RuntimeError("Original WorkRequest terminated without a successful ACK")
            if current["work_state"] != 0 or current["id"] is None:
                return observed("await-original-work")
            # -s preserves every constraint. Never force, enqueue replacement
            # work, change device policy, or invoke the core from instrumentation.
            try:
                outcome["scheduler_attempted"] = True
                self.scheduler_evidence(marker, phase, outcome)
                result = self.shell(
                    "cmd",
                    "jobscheduler",
                    "run",
                    "-s",
                    "-u",
                    "0",
                    "-n",
                    NAMESPACE,
                    PACKAGE,
                    str(current["id"]),
                )
            except RuntimeError as error:
                if "Could not find job" in str(error):
                    continue  # Re-read the same UUID, not an arbitrary pending job.
                if any(
                    text in str(error)
                    for text in (
                        "not satisfy",
                        "unsatisfied",
                        "functional constraints",
                    )
                ):
                    return observed("constraints-pending")
                raise
            (self.output / f"{phase}-scheduler-dispatch.txt").write_text(result, encoding="utf-8")
            if "Running job" not in result or "[FORCED]" in result:
                raise RuntimeError("Original work was not dispatched with constraints satisfied")
            return observed("satisfied-dispatch", True)
        return observed("job-missing-after-observation")

    def scheduler_evidence(self, marker: dict, phase: str, outcome: dict) -> None:
        (self.output / f"{phase}-scheduler-identity.txt").write_text(
            json.dumps({"prepared": marker["system_job"], **outcome}, indent=2), encoding="utf-8"
        )

    def original_retry_observer(
        self, marker: dict, phase: str, outcome: dict
    ) -> Callable[[], None]:
        if not self.guarded:
            raise RuntimeError("Retry observation requires the disposable-emulator guard")
        initial = (outcome.get("scheduler_observations") or [{}])[-1]
        initial_identity = (initial.get("generation"), initial.get("id"))
        seen_running = initial.get("work_state") == 1
        next_poll = time.monotonic() + 10
        # A command already sent (even refused) cannot authorize another here.
        # The existing disappearing-job race is handled inside dispatch_ready_job.
        attempted = bool(outcome.get("scheduler_attempted", outcome["scheduler_dispatched"]))

        def observe() -> None:
            nonlocal next_poll, attempted, seen_running
            now = time.monotonic()
            if attempted or now < next_poll:
                return
            next_poll = now + 10
            current = self.current_system_job(marker)
            if current["work_id"] != marker["work_id"] or current["namespace"] != NAMESPACE:
                raise RuntimeError("Original retry identity changed")
            seen_running |= current["work_state"] == 1
            eligible = (
                current["work_state"] == 0
                and current["id"] is not None
                and (seen_running or (current["generation"], current["id"]) != initial_identity)
            )
            native_state = None
            if eligible:
                native_state = self.shell(
                    "cmd",
                    "jobscheduler",
                    "get-job-state",
                    "-u",
                    "0",
                    "-n",
                    NAMESPACE,
                    PACKAGE,
                    str(current["id"]),
                    required=False,
                )
            observation = {**current, "native_job_state": native_state}
            records = outcome.setdefault("scheduler_retry_observations", [])
            if not records or records[-1] != observation:
                records.append(observation)
            self.scheduler_evidence(marker, phase, outcome)
            if current["work_state"] in (3, 5):
                raise RuntimeError("Original WorkRequest failed or was cancelled")
            # Backoff must finish naturally. Pending/active/unknown or any
            # extra readiness flag cannot authorize the phase's one dispatch.
            if eligible and native_state.split() == ["ready"]:
                attempted = True
                retry = self.dispatch_ready_job(marker, phase + "-retry")
                outcome["scheduler_retry_dispatch"] = retry
                outcome["scheduler_attempted"] = retry["scheduler_attempted"]
                outcome["scheduler_dispatched"] |= retry["scheduler_dispatched"]
                outcome["scheduler_action"] = (
                    "satisfied-retry-dispatch"
                    if retry["scheduler_dispatched"]
                    else "await-original-retry"
                )
                self.scheduler_evidence(marker, phase, outcome)

        return observe

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
            scheduler = self.dispatch_ready_job(prepared, phase)
            observed = self.wait_ack(
                prepared, on_wait=self.original_retry_observer(prepared, phase, scheduler)
            )
            delivery = (
                "screen-wake-and-scheduler-satisfied"
                if scheduler["scheduler_dispatched"]
                else "screen-wake-and-scheduler-observed"
            )
            return {**observed, "delivery": delivery, **scheduler}

    def stopped(self) -> bool:
        result = self.shell("dumpsys", "package", PACKAGE)
        matched = re.search(r"User 0:.*\bstopped=(true|false)", result)
        if not matched:
            raise RuntimeError("Package stopped flag could not be observed")
        return matched[1] == "true"

    def diagnostics(self, name: str) -> None:
        if not self.guarded:
            raise RuntimeError("Diagnostics require the disposable-emulator guard")
        for service in ("power", "jobscheduler", "activity"):
            value = self.shell("dumpsys", service, required=False)
            (self.output / f"{name}-{service}.txt").write_text(value, encoding="utf-8")
        # WorkManager metadata and fatal stacks from this disposable fixture;
        # no broad logcat or provider/account payloads are collected.
        value = self.shell(
            "logcat",
            "-d",
            "-v",
            "threadtime",
            "-s",
            "WM-WorkerWrapper:D",
            "WM-SystemJobService:D",
            "WM-Processor:D",
            "AndroidRuntime:E",
            "*:S",
            required=False,
        )
        (self.output / f"{name}-worker-logcat.txt").write_text(value, encoding="utf-8")
        try:
            prepared = self.marker()
            observation = {
                "phase": prepared["phase"],
                "native": self.snapshot(prepared["targets"][-1]["id"]),
                "original_work": self.current_system_job(prepared),
            }
        except (
            KeyError,
            ValueError,
            sqlite3.Error,
            OSError,
            RuntimeError,
            IndexError,
            TypeError,
        ) as error:
            observation = {"observation_error_type": type(error).__name__}
        (self.output / f"{name}-original-work.txt").write_text(
            json.dumps(observation, indent=2), encoding="utf-8"
        )

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
                    "prepared_generation": prepared["generation"],
                    "original_work_id": prepared["work_id"],
                    "original_system_job": prepared["system_job"],
                    **observed,
                    "verified_pid": verified["verified_pid"],
                    "preserved_targets": len(verified["targets"]),
                    "notification_permission": "denied",
                    "activity_destroyed": verified["activity_destroyed"],
                    "research_recovery": verified["research_recovery"],
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
        "--dispatch-ready",
        action="store_true",
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
