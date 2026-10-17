import json
import sqlite3
from pathlib import Path

import pytest
from scripts.android_lifecycle_check import NAMESPACE, PACKAGE, Controller, DeliveryDeferred, main

WORK_ID = "e71b412b-e7e1-42dc-9308-17c6573f93dd"


def marker(job=5):
    return {"work_id": WORK_ID, "system_job": {"namespace": NAMESPACE, "id": job}}


def work_snapshot(
    tmp_path,
    monkeypatch,
    controller,
    *,
    state=0,
    worker="jp.stockai.app.DailyWorker",
    generation=2,
    mappings=((1, 5), (2, 7)),
):
    path = tmp_path / "work.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE WorkSpec(id TEXT,generation INTEGER,state INTEGER,"
            "worker_class_name TEXT);"
            "CREATE TABLE SystemIdInfo(work_spec_id TEXT,generation INTEGER,system_id INTEGER);"
        )
        connection.execute(
            "INSERT INTO WorkSpec VALUES(?,?,?,?)", (WORK_ID, generation, state, worker)
        )
        connection.executemany(
            "INSERT INTO SystemIdInfo VALUES(?,?,?)",
            [(WORK_ID, revision, job) for revision, job in mappings],
        )
        connection.execute("INSERT INTO SystemIdInfo VALUES('different-work',2,5)")
    monkeypatch.setattr(controller, "work_database_snapshot", lambda: path)
    return path


def test_non_ci_execution_never_invokes_adb_even_for_diagnostics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("sys.argv", ["android_lifecycle_check.py"])
    monkeypatch.setattr(Controller, "adb", lambda *a, **k: pytest.fail("adb outside CI"))
    monkeypatch.setattr(
        Controller, "diagnostics", lambda *a, **k: pytest.fail("device observation")
    )
    with pytest.raises(RuntimeError, match="restricted to GitHub CI"):
        main()
    report = json.loads(Path(".demo-artifacts/android-lifecycle/lifecycle-report.json").read_text())
    assert report["status"] == "failed"


def test_diagnostics_observe_original_completion_without_dispatch_or_instrumentation(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    calls = []

    def shell(*args, **kwargs):
        calls.append(args)
        assert args[0] in ("dumpsys", "logcat")
        return "fixture metadata"

    monkeypatch.setattr(controller, "shell", shell)
    with pytest.raises(RuntimeError, match="guard"):
        controller.diagnostics("failure")
    assert calls == []
    controller.guarded = True
    prepared = {**marker(), "phase": "reboot", "targets": [{"id": "fixture-acquisition"}]}
    monkeypatch.setattr(controller, "marker", lambda: prepared)
    monkeypatch.setattr(
        controller,
        "snapshot",
        lambda acquisition: {
            "pending_pages": 1,
            "enabled": True,
            "state": "queued",
            "first_day": "2026-10-15",
        },
    )
    work_snapshot(tmp_path, monkeypatch, controller, state=2, mappings=())
    controller.diagnostics("failure")
    observation = json.loads((controller.output / "failure-original-work.txt").read_text())
    assert observation["original_work"]["work_id"] == WORK_ID
    assert observation["original_work"]["work_state"] == 2
    assert observation["native"]["pending_pages"] == 1
    assert calls[-1] == (
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
    )


def test_diagnostic_observation_failure_cannot_report_success_or_expose_details(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    controller.guarded = True
    monkeypatch.setattr(controller, "shell", lambda *a, **k: "")

    def unreadable():
        raise RuntimeError("details must not enter metadata")

    monkeypatch.setattr(controller, "marker", unreadable)
    controller.diagnostics("failure")
    observation = json.loads((controller.output / "failure-original-work.txt").read_text())
    assert observation == {"observation_error_type": "RuntimeError"}
    assert controller.report["status"] == "running"


@pytest.mark.parametrize(
    "serial,qemu,sdk",
    [
        ("physical-device", "1", "35"),
        ("emulator-5554", "0", "35"),
        ("emulator-5554", "1", "34"),
    ],
)
def test_wrong_device_or_platform_is_rejected_before_install_or_clear(
    tmp_path,
    monkeypatch,
    serial,
    qemu,
    sdk,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("ANDROID_AVD_HOME", str(tmp_path / "stockai-avd"))
    controller = Controller(Path("evidence"))
    observed = []

    def adb(*args, **kwargs):
        observed.append(args)
        assert args == ("get-serialno",)
        return serial.encode()

    def shell(*args, **kwargs):
        observed.append(args)
        return {
            ("getprop", "ro.kernel.qemu"): qemu,
            ("am", "get-current-user"): "0",
            ("getprop", "ro.build.version.sdk"): sdk,
        }[args]

    monkeypatch.setattr(controller, "adb", adb)
    monkeypatch.setattr(controller, "shell", shell)
    with pytest.raises(RuntimeError):
        controller.execute()
    assert not controller.guarded
    assert all(call[0] not in ("install", "pm", "reboot") for call in observed)


def test_scheduler_dispatch_requires_guard_and_targets_only_original_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    prepared = marker(7)
    calls = []
    monkeypatch.setattr(controller, "shell", lambda *args: calls.append(args) or "Running job")
    with pytest.raises(RuntimeError, match="guard"):
        controller.dispatch_ready_job(prepared, "process")
    assert calls == []
    controller.guarded = True
    monkeypatch.setattr(
        controller,
        "current_system_job",
        lambda value: {
            "work_id": WORK_ID,
            "work_state": 0,
            "namespace": NAMESPACE,
            "id": 7,
        },
    )
    controller.dispatch_ready_job(prepared, "process")
    assert calls == [("cmd", "jobscheduler", "run", "-s", "-u", "0", "-n", NAMESPACE, PACKAGE, "7")]


@pytest.mark.parametrize("dispatch_ready,error", [(False, DeliveryDeferred), (True, RuntimeError)])
def test_unforced_mode_or_bad_observation_cannot_trigger_scheduler(
    tmp_path, monkeypatch, dispatch_ready, error
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=dispatch_ready)

    def wait(*args, **kwargs):
        raise error("no accepted observation")

    monkeypatch.setattr(controller, "wait_ack", wait)
    monkeypatch.setattr(controller, "dispatch_ready_job", lambda *a: pytest.fail("new dispatch"))
    with pytest.raises(error):
        controller.observe_delivery({}, "process")


def test_reboot_mapping_uses_original_uuid_and_current_generation_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    path = work_snapshot(tmp_path, monkeypatch, controller)
    before = path.read_bytes()
    calls = []
    monkeypatch.setattr(controller, "shell", lambda *a: calls.append(a) or "Running job")
    result = controller.dispatch_ready_job(marker(), "reboot")
    assert result["scheduler_dispatched"] is True
    assert result["scheduler_observations"] == [
        {"work_id": WORK_ID, "generation": 2, "work_state": 0, "namespace": NAMESPACE, "id": 7}
    ]
    assert calls == [("cmd", "jobscheduler", "run", "-s", "-u", "0", "-n", NAMESPACE, PACKAGE, "7")]
    assert path.read_bytes() == before
    saved = json.loads((controller.output / "reboot-scheduler-identity.txt").read_text())
    assert saved["prepared"]["id"] == 5 and saved["scheduler_dispatched"] is True


@pytest.mark.parametrize("state", [0, 1, 2, 4])
def test_absent_mapping_or_running_work_is_observed_without_other_job_dispatch(
    tmp_path, monkeypatch, state
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    work_snapshot(tmp_path, monkeypatch, controller, state=state, mappings=())
    monkeypatch.setattr(controller, "shell", lambda *a: pytest.fail("unrelated job dispatch"))
    result = controller.dispatch_ready_job(marker(), "reboot")
    assert result["scheduler_dispatched"] is False
    assert result["scheduler_observations"][0]["work_id"] == WORK_ID


@pytest.mark.parametrize("state", [3, 5])
def test_terminal_unsuccessful_original_work_is_not_replaced(tmp_path, monkeypatch, state):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    work_snapshot(tmp_path, monkeypatch, controller, state=state)
    monkeypatch.setattr(controller, "shell", lambda *a: pytest.fail("replacement dispatch"))
    with pytest.raises(RuntimeError, match="terminated"):
        controller.dispatch_ready_job(marker(), "reboot")


def test_wrong_worker_and_ambiguous_generation_mapping_fail_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    path = work_snapshot(tmp_path, monkeypatch, controller, worker="other.Worker")
    monkeypatch.setattr(controller, "shell", lambda *a: pytest.fail("wrong worker"))
    with pytest.raises(RuntimeError, match="verified"):
        controller.dispatch_ready_job(marker(), "reboot")
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE WorkSpec SET worker_class_name='jp.stockai.app.DailyWorker'")
        connection.execute("INSERT INTO SystemIdInfo VALUES(?,2,8)", (WORK_ID,))
    with pytest.raises(RuntimeError, match="Ambiguous"):
        controller.dispatch_ready_job(marker(), "reboot")


def test_job_removed_after_read_reresolves_same_work_without_forcing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    observations = iter(
        [{"work_id": WORK_ID, "work_state": 0, "namespace": NAMESPACE, "id": job} for job in (7, 8)]
    )
    monkeypatch.setattr(controller, "current_system_job", lambda value: next(observations))
    calls = []

    def shell(*args):
        calls.append(args)
        if args[-1] == "7":
            raise RuntimeError("Could not find job 7")
        return "Running job"

    monkeypatch.setattr(controller, "shell", shell)
    result = controller.dispatch_ready_job(marker(), "reboot")
    assert result["scheduler_dispatched"] and [
        row["id"] for row in result["scheduler_observations"]
    ] == [7, 8]
    assert all("-s" in call and "-f" not in call for call in calls)


def test_constraints_refusal_keeps_original_bounded_ack_observation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    work_snapshot(tmp_path, monkeypatch, controller)
    calls = []

    def shell(*args):
        calls.append(args)
        raise RuntimeError("Job has functional constraints but --force not specified")

    monkeypatch.setattr(controller, "shell", shell)
    result = controller.dispatch_ready_job(marker(), "reboot")
    assert result["scheduler_dispatched"] is False and len(calls) == 1


def test_work_database_copy_requires_guard_and_uses_legacy_only_if_needed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        return {
            "databases/androidx.work.workdb": b"database",
            "databases/androidx.work.workdb-wal": b"wal",
        }.get(args[-1], b"")

    monkeypatch.setattr(controller, "adb", adb)
    with pytest.raises(RuntimeError, match="guard"):
        controller.work_database_snapshot()
    assert calls == []
    controller.guarded = True
    path = controller.work_database_snapshot()
    assert path.read_bytes() == b"database" and Path(str(path) + "-wal").read_bytes() == b"wal"
    assert all(call[:4] == ("exec-out", "run-as", PACKAGE, "cat") for call in calls)


@pytest.mark.parametrize("work_id", [None, "not-a-uuid", WORK_ID.upper()])
def test_invalid_original_uuid_is_rejected_before_device_observation(
    tmp_path, monkeypatch, work_id
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    monkeypatch.setattr(controller, "work_database_snapshot", lambda: pytest.fail("bad UUID read"))
    with pytest.raises(RuntimeError, match="identity"):
        controller.current_system_job({"work_id": work_id})


@pytest.mark.parametrize("dispatched", [False, True])
def test_delivery_label_records_actual_intervention_and_preserves_windows(
    tmp_path, monkeypatch, dispatched
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    prepared = marker()
    waits = []

    def wait(value, *, seconds=200, on_wait=None):
        assert value is prepared
        waits.append(seconds)
        if len(waits) < 3:
            assert on_wait is None
            raise DeliveryDeferred("still pending")
        assert callable(on_wait)
        return {"generation": 5, "pending_pages": 0}

    monkeypatch.setattr(controller, "wait_ack", wait)
    monkeypatch.setattr(controller, "diagnostics", lambda *a: None)
    monkeypatch.setattr(controller, "shell", lambda *a: "")
    monkeypatch.setattr("scripts.android_lifecycle_check.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        controller, "dispatch_ready_job", lambda *a: {"scheduler_dispatched": dispatched}
    )
    result = controller.observe_delivery(prepared, "reboot")
    assert waits == [90, 3, 200]
    assert result["delivery"] == (
        "screen-wake-and-scheduler-satisfied"
        if dispatched
        else "screen-wake-and-scheduler-observed"
    )
    assert result["scheduler_dispatched"] is dispatched


def retry_outcome(*, running=True, dispatched=False, job=7):
    return {
        "scheduler_dispatched": dispatched,
        "scheduler_observations": [
            {
                "work_id": WORK_ID,
                "generation": 2,
                "id": job,
                "namespace": NAMESPACE,
                "work_state": 1 if running else 0,
            }
        ],
    }


def test_unforced_policy_keeps_200_seconds_without_retry_observer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=False)
    calls = []

    def wait(value, *, seconds=200, on_wait=None):
        calls.append((seconds, on_wait))
        return {"generation": 8, "pending_pages": 0}

    monkeypatch.setattr(controller, "wait_ack", wait)
    monkeypatch.setattr(controller, "original_retry_observer", lambda *a: pytest.fail("unforced"))
    monkeypatch.setattr(controller, "shell", lambda *a, **k: pytest.fail("unforced"))
    assert controller.observe_delivery(marker(), "reboot")["delivery"] == "unforced"
    assert calls == [(200, None)]


def test_delivery_label_includes_dispatch_during_ack_observation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    outcome = retry_outcome()
    waits = []

    def wait(value, *, seconds=200, on_wait=None):
        waits.append(seconds)
        if on_wait is None:
            raise DeliveryDeferred("pending")
        on_wait()
        return {"generation": 8, "pending_pages": 0}

    def observer(value, phase, scheduler):
        assert value["work_id"] == WORK_ID and scheduler is outcome
        return lambda: scheduler.update(scheduler_dispatched=True)

    monkeypatch.setattr(controller, "wait_ack", wait)
    monkeypatch.setattr(controller, "dispatch_ready_job", lambda *a: outcome)
    monkeypatch.setattr(controller, "original_retry_observer", observer)
    monkeypatch.setattr(controller, "diagnostics", lambda *a: None)
    monkeypatch.setattr(controller, "shell", lambda *a: "")
    monkeypatch.setattr("scripts.android_lifecycle_check.time.sleep", lambda *a: None)
    result = controller.observe_delivery(marker(), "reboot")
    assert waits == [90, 3, 200]
    assert result["delivery"] == "screen-wake-and-scheduler-satisfied"


def test_original_retry_waits_for_backoff_readiness_and_dispatches_only_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    controller.guarded = True
    path = work_snapshot(tmp_path, monkeypatch, controller, mappings=((2, 8),))
    original_bytes = path.read_bytes()
    clock = [0.0]
    monkeypatch.setattr("scripts.android_lifecycle_check.time.monotonic", lambda: clock[0])
    calls = []

    def shell(*args, **kwargs):
        calls.append(args)
        assert args[:2] == ("cmd", "jobscheduler")
        assert args[-2:] == (PACKAGE, "8")
        if args[2] == "get-job-state":
            return "waiting" if clock[0] < 20 else "ready"
        assert args == (
            "cmd",
            "jobscheduler",
            "run",
            "-s",
            "-u",
            "0",
            "-n",
            NAMESPACE,
            PACKAGE,
            "8",
        )
        return "Running job"

    monkeypatch.setattr(controller, "shell", shell)
    outcome = retry_outcome()
    observer = controller.original_retry_observer(marker(), "reboot", outcome)
    observer()
    assert calls == []
    clock[0] = 10
    observer()
    assert not outcome["scheduler_dispatched"]
    clock[0] = 20
    observer()
    clock[0] = 30
    observer()
    assert sum(call[2] == "run" for call in calls) == 1
    assert outcome["scheduler_dispatched"]
    assert path.read_bytes() == original_bytes
    saved = json.loads((controller.output / "reboot-scheduler-identity.txt").read_text())
    assert saved["prepared"]["id"] == 5
    assert saved["scheduler_observations"][0]["id"] == 7
    assert [x["native_job_state"] for x in saved["scheduler_retry_observations"]] == [
        "waiting",
        "ready",
    ]
    assert saved["scheduler_retry_dispatch"]["scheduler_observations"][0]["id"] == 8


@pytest.mark.parametrize("dispatched", [False, True])
def test_retry_cannot_dispatch_again_after_phase_used_its_one_intervention(
    tmp_path,
    monkeypatch,
    dispatched,
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    controller.guarded = True
    clock = [0]
    monkeypatch.setattr("scripts.android_lifecycle_check.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        controller, "current_system_job", lambda *a: pytest.fail("already dispatched")
    )
    monkeypatch.setattr(controller, "shell", lambda *a, **k: pytest.fail("second dispatch"))
    outcome = retry_outcome(dispatched=dispatched)
    outcome["scheduler_attempted"] = True
    observer = controller.original_retry_observer(marker(), "reboot", outcome)
    clock[0] = 100
    observer()
    assert outcome["scheduler_dispatched"] is dispatched
    assert "scheduler_retry_dispatch" not in outcome


@pytest.mark.parametrize(
    "flags",
    [
        "",
        "waiting",
        "active",
        "active ready",
        "pending ready",
        "user-stopped",
        "no-component",
        "ready unknown",
    ],
)
def test_retry_never_dispatches_without_exact_native_ready(tmp_path, monkeypatch, flags):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    controller.guarded = True
    work_snapshot(tmp_path, monkeypatch, controller, mappings=((2, 8),))
    clock = [0]
    monkeypatch.setattr("scripts.android_lifecycle_check.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(controller, "shell", lambda *a, **k: flags)
    monkeypatch.setattr(controller, "dispatch_ready_job", lambda *a: pytest.fail("not ready"))
    outcome = retry_outcome()
    observer = controller.original_retry_observer(marker(), "reboot", outcome)
    clock[0] = 10
    observer()
    assert not outcome["scheduler_dispatched"]


@pytest.mark.parametrize("state", [1, 2, 4])
def test_retry_running_completed_or_blocked_work_remains_observational(
    tmp_path, monkeypatch, state
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    controller.guarded = True
    work_snapshot(tmp_path, monkeypatch, controller, state=state, mappings=((2, 8),))
    clock = [0]
    monkeypatch.setattr("scripts.android_lifecycle_check.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(controller, "shell", lambda *a, **k: pytest.fail("work not enqueued"))
    outcome = retry_outcome()
    observer = controller.original_retry_observer(marker(), "reboot", outcome)
    clock[0] = 10
    observer()
    assert not outcome["scheduler_dispatched"]


@pytest.mark.parametrize("state", [3, 5])
def test_retry_original_terminal_failure_stops_acceptance(tmp_path, monkeypatch, state):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    controller.guarded = True
    work_snapshot(tmp_path, monkeypatch, controller, state=state, mappings=((2, 8),))
    clock = [0]
    monkeypatch.setattr("scripts.android_lifecycle_check.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(controller, "shell", lambda *a, **k: pytest.fail("terminal work"))
    observer = controller.original_retry_observer(marker(), "reboot", retry_outcome())
    clock[0] = 10
    with pytest.raises(RuntimeError, match="failed or was cancelled"):
        observer()


def test_retry_observer_requires_guard_before_workmanager_or_scheduler_access(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    monkeypatch.setattr(controller, "current_system_job", lambda *a: pytest.fail("no guard"))
    with pytest.raises(RuntimeError, match="guard"):
        controller.original_retry_observer(marker(), "reboot", retry_outcome())


def test_wait_callback_never_extends_original_deadline_or_runs_after_ack(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"))
    prepared = {"targets": [{"id": "fixture"}], "generation": 6}
    clock, callbacks = [0], []
    monkeypatch.setattr("scripts.android_lifecycle_check.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "scripts.android_lifecycle_check.time.sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    monkeypatch.setattr(controller, "snapshot", lambda *a: {"generation": 6, "pending_pages": 1})
    with pytest.raises(DeliveryDeferred):
        controller.wait_ack(prepared, seconds=2, on_wait=lambda: callbacks.append(clock[0]))
    assert clock[0] == 2 and callbacks == [0]
    monkeypatch.setattr(controller, "snapshot", lambda *a: {"generation": 7, "pending_pages": 0})
    monkeypatch.setattr(controller, "pid", lambda: "42")
    assert (
        controller.wait_ack(prepared, on_wait=lambda: pytest.fail("already ACK"))["observed_pid"]
        == "42"
    )
