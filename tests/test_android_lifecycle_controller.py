import json
from pathlib import Path

import pytest
from scripts.android_lifecycle_check import NAMESPACE, PACKAGE, Controller, DeliveryDeferred, main


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


def test_scheduler_dispatch_requires_guard_and_targets_only_prepared_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = Controller(Path("evidence"), dispatch_ready=True)
    marker = {"system_job": {"namespace": NAMESPACE, "id": 7}}
    calls = []
    monkeypatch.setattr(controller, "shell", lambda *args: calls.append(args) or "Running job")
    with pytest.raises(RuntimeError, match="guard"):
        controller.dispatch_ready_job(marker, "process")
    assert calls == []
    controller.guarded = True
    controller.dispatch_ready_job(marker, "process")
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
