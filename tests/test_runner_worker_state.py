from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_ai.ml.campaign import (
    CampaignBatchStatus,
    create_campaign_manifest,
    write_campaign_manifest,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process identity")


def _powershell() -> Path:
    return (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


def _quote(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _probe(
    resolver_body: str,
    *,
    child_pid: int = 1234,
    started_at: str = "2026-09-05T00:00:00Z",
) -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[1]
    helper = project_root / "runner" / "worker-state.ps1"
    script = f"""
. {_quote(helper)}
$batch = [pscustomobject]@{{
    child_pid = {child_pid}
    started_at = '{started_at}'
}}
$resolver = {{
    param([int]$RequestedPid)
    {resolver_body}
}}
$state = Get-WorkerProcessState -Batch $batch -ProcessResolver $resolver
$effective = Get-EffectiveWorkerStatus -StoredStatus 'RUNNING' -WorkerState $state
$alive = ConvertTo-WorkerAlive -WorkerState $state
[pscustomobject]@{{
    state = $state
    effective_status = $effective
    worker_alive = $alive
}} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [
            str(_powershell()),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _pause_boundary(first_status: str, second_status: str) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[1]
    helper = project_root / "runner" / "worker-state.ps1"
    script = f"""
. {_quote(helper)}
$batches = @(
    [pscustomobject]@{{ batch_id = 'first'; stored_status = '{first_status}' }},
    [pscustomobject]@{{ batch_id = 'second'; stored_status = '{second_status}' }}
)
Get-PauseBoundaryState -Batches $batches -BatchId 'first'
"""
    return subprocess.run(
        [
            str(_powershell()),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_winerror_87_is_unknown_and_never_interrupted() -> None:
    observed = _probe(
        "throw (New-Object System.ComponentModel.Win32Exception 87)"
    )

    assert observed == {
        "state": "UNKNOWN",
        "effective_status": "UNKNOWN",
        "worker_alive": None,
    }


def test_access_denied_is_unknown_and_never_interrupted() -> None:
    observed = _probe("throw (New-Object System.UnauthorizedAccessException 'denied')")

    assert observed == {
        "state": "UNKNOWN",
        "effective_status": "UNKNOWN",
        "worker_alive": None,
    }


def test_explicitly_absent_pid_is_dead() -> None:
    observed = _probe("return $null")

    assert observed == {
        "state": "DEAD",
        "effective_status": "INTERRUPTED",
        "worker_alive": False,
    }


def test_pid_reuse_is_dead_when_start_time_does_not_match() -> None:
    observed = _probe(
        "return [pscustomobject]@{ "
        "ProcessName = 'python'; "
        "StartTime = [datetime]'2026-09-05T00:10:00Z' "
        "}"
    )

    assert observed == {
        "state": "DEAD",
        "effective_status": "INTERRUPTED",
        "worker_alive": False,
    }


def test_matching_python_pid_and_start_time_is_alive() -> None:
    observed = _probe(
        "return [pscustomobject]@{ "
        "ProcessName = 'python'; "
        "StartTime = [datetime]'2026-09-05T00:00:00Z' "
        "}"
    )

    assert observed == {
        "state": "ALIVE",
        "effective_status": "RUNNING",
        "worker_alive": True,
    }


def test_pause_boundary_waits_until_target_succeeds() -> None:
    observed = _pause_boundary("RUNNING", "PENDING")

    assert observed.returncode == 0, observed.stderr
    assert observed.stdout.strip() == "CONTINUE"


def test_pause_boundary_holds_before_all_pending_tail() -> None:
    observed = _pause_boundary("SUCCEEDED", "PENDING")

    assert observed.returncode == 0, observed.stderr
    assert observed.stdout.strip() == "PAUSE"


def test_pause_boundary_fails_closed_if_tail_already_started() -> None:
    observed = _pause_boundary("SUCCEEDED", "RUNNING")

    assert observed.returncode != 0
    assert "boundary was crossed" in observed.stderr


def test_real_missing_pid_is_dead() -> None:
    project_root = Path(__file__).resolve().parents[1]
    helper = project_root / "runner" / "worker-state.ps1"
    script = f"""
. {_quote(helper)}
$batch = [pscustomobject]@{{
    child_pid = 2147483647
    started_at = '2026-09-05T00:00:00Z'
}}
Get-WorkerProcessState -Batch $batch
"""
    result = subprocess.run(
        [
            str(_powershell()),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "DEAD"


def test_research_runner_status_avoids_windows_os_kill_and_is_read_only(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    build_id = "a" * 64
    build_directory = tmp_path / "builds" / build_id
    build_directory.mkdir(parents=True)
    build_path = (build_directory / f"{build_id}.json").resolve()
    build_payload: dict[str, object] = {
        "build_id": build_id,
        "manifest_path": str(build_path),
        "dataset_snapshot_id": "b" * 64,
        "v2_snapshot_id": "c" * 64,
    }
    build_payload["metadata_hash"] = hashlib.sha256(
        json.dumps(
            build_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    build_path.write_text(json.dumps(build_payload), encoding="utf-8")
    code_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    campaign = create_campaign_manifest(
        build_id=build_id,
        build_manifest_path=build_path,
        code_commit=code_commit,
        report_root=tmp_path / "reports",
        experiment_registry=tmp_path / "experiments.jsonl",
        horizons=(1,),
        model_families=("lightgbm",),
        common_config={
            "target_family": "return",
            "seeds": (17,),
            "tuning_trials": 1,
            "tuning_timeout_seconds": 10,
            "estimator_count": 5,
            "initial_train_periods": 20,
            "validation_periods": 5,
            "step_periods": 5,
            "holdout_periods": 120,
            "run_ablations": True,
            "run_diagnostics": True,
            "max_materialized_oof_rows": 10_000,
            "max_model_fits": 100,
            "feature_names": ("return_1d",),
        },
        checkpoint_root=tmp_path / "checkpoints",
        now=datetime(2026, 9, 5, tzinfo=UTC),
    )
    campaign.batches[0].status = CampaignBatchStatus.RUNNING
    campaign.batches[0].child_pid = 2147483647
    campaign.batches[0].started_at = datetime(2026, 9, 5, tzinfo=UTC)
    manifest_path = tmp_path / "campaign.json"
    write_campaign_manifest(campaign, manifest_path)
    manifest_before = manifest_path.read_bytes()

    result = subprocess.run(
        [
            str(_powershell()),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(project_root / "runner" / "research-runner.ps1"),
            "-Action",
            "status",
            "-Manifest",
            str(manifest_path),
            "-Json",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    batch = payload["batches"][0]
    assert batch["stored_status"] == "RUNNING"
    assert batch["worker_state"] == "DEAD"
    assert batch["effective_status"] == "INTERRUPTED"
    assert manifest_path.read_bytes() == manifest_before


def test_goal3_phase_task_show_is_read_only_and_keeps_progress_entrypoint() -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["JQUANTS_API_KEY"] = "test-placeholder-never-print"

    result = subprocess.run(
        [
            str(_powershell()),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(project_root / "runner" / "register-goal3-phase-runner-task.ps1"),
            "-Action",
            "show",
        ],
        cwd=project_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "1d screen -> fixed decision -> 5d full ablation" in result.stdout
    assert "goal3-phase-runner.ps1 -Action status" in result.stdout
    assert "current_worker_action" in result.stdout
    assert ": none; waits on existing runner lock" in result.stdout
    assert "locked_holdout_accessed" in result.stdout
    assert ": False" in result.stdout
    assert "test-placeholder-never-print" not in result.stdout + result.stderr


def _phase_status_for_completed_one_day(
    tmp_path: Path,
    *,
    decision: str | None = None,
    decision_campaign_id: str = "one-day-campaign",
    all_gates_passed: bool | None = None,
) -> subprocess.CompletedProcess[str]:
    boundary_path = tmp_path / "boundary.json"
    one_day_path = tmp_path / "one-day.json"
    core_latch = tmp_path / "legacy-core.json"
    decision_path = tmp_path / "decision.json"
    five_day_path = tmp_path / "five-day.json"
    twenty_day_path = tmp_path / "twenty-day.json"
    one_day_ablation_path = tmp_path / "one-day-ablation.json"
    core_latch.mkdir()
    boundary_path.write_text(
        json.dumps({"batches": [{"batch_id": "h1-lightgbm-s17", "status": "SUCCEEDED"}]}),
        encoding="utf-8",
    )
    report_ids = [f"report-{index}" for index in range(6)]
    one_day_path.write_text(
        json.dumps(
            {
                "campaign_id": "one-day-campaign",
                "build_id": "build-id",
                "code_commit": "code-commit",
                "batches": [
                    {"status": "SUCCEEDED", "report_id": report_id}
                    for report_id in report_ids
                ],
            }
        ),
        encoding="utf-8",
    )
    if decision is not None:
        all_pass = (
            decision == "KEEP_FOR_FULL_ABLATION"
            if all_gates_passed is None
            else all_gates_passed
        )
        decision_path.write_text(
            json.dumps(
                {
                    "schema_version": "goal3-one-day-screen-decision-v1",
                    "criteria_version": "D080",
                    "one_day_campaign_id": decision_campaign_id,
                    "build_id": "build-id",
                    "code_commit": "code-commit",
                    "screen_report_ids": report_ids,
                    "gates": {
                        "stable_across_seeds_and_folds": all_pass,
                        "non_redundant_with_h5_h20": all_pass,
                        "improves_development_oof_stack": all_pass,
                        "improves_realistic_cost": all_pass,
                        "non_worsening_turnover_downside_large_loss": all_pass,
                    },
                    "decision": decision,
                    "locked_holdout_accessed": False,
                }
            ),
            encoding="utf-8",
        )
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            str(_powershell()),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(project_root / "runner" / "goal3-phase-runner.ps1"),
            "-Action",
            "status",
            "-BoundaryManifest",
            str(boundary_path),
            "-OneDayScreenManifest",
            str(one_day_path),
            "-CoreScreenManifest",
            str(core_latch),
            "-OneDayDecisionArtifact",
            str(decision_path),
            "-FiveDayAblationManifest",
            str(five_day_path),
            "-TwentyDayAblationManifest",
            str(twenty_day_path),
            "-OneDayAblationManifest",
            str(one_day_ablation_path),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_phase_waits_for_fixed_one_day_decision_before_core_ablation(tmp_path: Path) -> None:
    result = _phase_status_for_completed_one_day(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["phase"] == "ONE_DAY_EVALUATION_READY"
    assert payload["legacy_core_screen_latch"] == "ARMED"
    assert payload["locked_holdout_accessed"] is False


@pytest.mark.parametrize(
    "decision",
    ["KEEP_FOR_FULL_ABLATION", "EXCLUDE_FROM_FULL_ABLATION_AND_FINAL"],
)
def test_phase_skips_core_screen_and_queues_five_day_full_ablation(
    tmp_path: Path, decision: str
) -> None:
    result = _phase_status_for_completed_one_day(tmp_path, decision=decision)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["phase"] == "FIVE_DAY_ABLATION_QUEUED"
    assert payload["active_manifest"] is None
    assert payload["one_day_decision"]["decision"] == decision


def test_phase_rejects_decision_for_different_screen_campaign(tmp_path: Path) -> None:
    result = _phase_status_for_completed_one_day(
        tmp_path,
        decision="EXCLUDE_FROM_FULL_ABLATION_AND_FINAL",
        decision_campaign_id="wrong-campaign",
    )

    assert result.returncode != 0
    assert "one-day screen decision campaign mismatch" in result.stderr


def test_phase_rejects_keep_decision_when_any_fixed_gate_fails(tmp_path: Path) -> None:
    result = _phase_status_for_completed_one_day(
        tmp_path,
        decision="KEEP_FOR_FULL_ABLATION",
        all_gates_passed=False,
    )

    assert result.returncode != 0
    assert "contradicts fixed D080 gates" in result.stderr
