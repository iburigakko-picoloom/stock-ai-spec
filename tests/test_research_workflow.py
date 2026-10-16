from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stock_ai.operations import OperationalConflictError, OperationalStore
from stock_ai.operations.api import create_app
from stock_ai.operations.chatgpt_research import ResearchConfiguration
from tests.conftest import AS_OF
from tests.test_chatgpt_research import response_for
from tests.test_daily_readiness import daily_snapshot

CONFIG = ResearchConfiguration(model="account-selected-model", effort="high")
START = AS_OF + timedelta(minutes=5)


def started(tmp_path: Path):
    store = OperationalStore(tmp_path / "research.sqlite")
    snapshot = daily_snapshot()
    store.append_prediction_snapshot(snapshot)
    view = store.begin_research(
        snapshot.snapshot_id,
        "A",
        CONFIG,
        company_name="試験株式会社",
        now=START,
    )
    return store, snapshot, view


def complete_phase(store, claim, minute):
    return store.finish_research(
        claim["attempt"]["attempt_id"],
        now=START + timedelta(minutes=minute + 1),
        response=response_for(search=claim["attempt"]["phase"] == "independent"),
        started_at=START + timedelta(minutes=minute, seconds=1),
        completed_at=START + timedelta(minutes=minute, seconds=30),
    )


def test_durable_claim_prevents_duplicate_calls_and_receipts_are_atomic(tmp_path: Path) -> None:
    store, snapshot, view = started(tmp_path)
    run_id = view["run"]["run_id"]
    first = store.claim_research(run_id, now=START + timedelta(minutes=1))
    assert first["state"] == "ready"
    repeated = store.claim_research(run_id, now=START + timedelta(minutes=1))
    assert repeated["state"] == "running"
    assert repeated["attempt"] == first["attempt"]
    assert "request_json" not in repeated
    result = complete_phase(store, first, 1)
    assert len(result["passes"]) == 1 and result["record"] is None
    assert complete_phase(store, first, 1) == result
    reopened = OperationalStore(store.path)
    second = reopened.claim_research(run_id, now=START + timedelta(minutes=3))
    assert second["attempt"]["phase"] == "comparison"
    assert result["passes"][0]["text"] in second["request_json"]
    final = complete_phase(reopened, second, 3)
    assert len(final["attempts"]) == 2 and final["record"] is not None
    assert reopened.claim_research(run_id, now=START + timedelta(minutes=5))["state"] == "completed"
    assert reopened.prediction_snapshot(snapshot.snapshot_id) == snapshot
    assert reopened.verify_integrity()["chatgpt_research_attempts"] == 2
    backup = reopened.backup(tmp_path / "backup.sqlite")
    restored = OperationalStore.restore_backup(
        backup, tmp_path / "restore.sqlite", confirm_replace=True
    )
    assert OperationalStore(restored).research_runs(snapshot.snapshot_id) == (final,)


def test_interrupted_comparison_requires_explicit_retry_and_keeps_independent_result(
    tmp_path: Path,
) -> None:
    store, snapshot, view = started(tmp_path)
    run_id = view["run"]["run_id"]
    first = store.claim_research(run_id, now=START + timedelta(minutes=1))
    complete_phase(store, first, 1)
    second = store.claim_research(run_id, now=START + timedelta(minutes=3))
    failed = store.finish_research(
        second["attempt"]["attempt_id"],
        now=START + timedelta(minutes=4),
        error_code="PROCESS_INTERRUPTED",
        interrupted=True,
    )
    assert len(failed["passes"]) == 1
    assert store.claim_research(run_id, now=START + timedelta(minutes=5))["state"] == "blocked"
    retry = store.claim_research(run_id, now=START + timedelta(minutes=5), retry=True)
    assert retry["attempt"]["phase"] == "comparison"
    assert retry["attempt"]["attempt_id"] != second["attempt"]["attempt_id"]
    final = complete_phase(store, retry, 5)
    assert len(final["passes"]) == 2 and len(final["attempts"]) == 3
    assert final["record"]["independent"]["pass_id"] == failed["passes"][0]["pass_id"]
    assert store.prediction_snapshot(snapshot.snapshot_id) == snapshot


def test_missing_search_becomes_failed_attempt_without_a_completed_research_record(tmp_path: Path):
    store, snapshot, view = started(tmp_path)
    claim = store.claim_research(view["run"]["run_id"], now=START + timedelta(minutes=1))
    failed = store.finish_research(
        claim["attempt"]["attempt_id"],
        now=START + timedelta(minutes=2),
        response=response_for(search=False),
        started_at=START + timedelta(minutes=1),
        completed_at=START + timedelta(minutes=2),
    )
    assert failed["attempts"][0]["error_code"] == "INVALID_RESEARCH_RESPONSE"
    assert failed["passes"] == [] and failed["record"] is None
    assert store.chatgpt_research(snapshot.snapshot_id) == ()


def test_same_configuration_reuses_context_and_rerun_preserves_prior_results(tmp_path: Path):
    store, snapshot, view = started(tmp_path)
    run_id = view["run"]["run_id"]
    reused = store.begin_research(
        snapshot.snapshot_id,
        "A",
        CONFIG,
        company_name="試験株式会社",
        now=START + timedelta(hours=1),
    )
    assert reused == view
    for minute in (1, 3):
        complete_phase(
            store, store.claim_research(run_id, now=START + timedelta(minutes=minute)), minute
        )
    rerun = store.begin_research(
        snapshot.snapshot_id,
        "A",
        CONFIG,
        company_name="試験株式会社",
        now=START + timedelta(minutes=10),
        rerun_previous_id=run_id,
    )
    assert rerun["run"]["context"]["revision"] == 2
    assert rerun["passes"] == []
    assert len(store.chatgpt_research(snapshot.snapshot_id)) == 1
    with pytest.raises(OperationalConflictError, match="changed"):
        store.begin_research(
            snapshot.snapshot_id,
            "A",
            CONFIG,
            company_name="試験株式会社",
            now=START + timedelta(minutes=11),
            rerun_previous_id=run_id,
        )


def test_api_requires_intent_restricts_targets_and_keeps_numeric_output_read_only(tmp_path: Path):
    store, snapshot, _ = started(tmp_path)
    current = START + timedelta(minutes=10)
    client = TestClient(create_app(store.path, clock=lambda: current), base_url="http://127.0.0.1")
    endpoint = f"/api/v1/research/{snapshot.snapshot_id}/A/start"
    body = {"configuration": CONFIG.model_dump(mode="json")}
    assert client.post(endpoint, json=body).status_code == 428
    headers = {"X-Stock-AI-Intent": "manual-record"}
    assert (
        client.post(endpoint, json={**body, "balance": 10000}, headers=headers).status_code == 422
    )
    assert (
        client.post(endpoint.replace("/A/", "/B/"), json=body, headers=headers).status_code == 422
    )
    response = client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 200
    run_id = response.json()["run"]["run_id"]
    claim = client.post(f"/api/v1/research/{run_id}/claim", json={}, headers=headers).json()
    assert "expected_return" not in claim["request_json"]
    detail = client.get("/api/v1/stocks/A").json()
    assert detail["positions"] == [] and detail["proposalLines"] == []
    assert detail["forecast"]["prediction"] == snapshot.predictions[0].model_dump(mode="json")
    assert detail["forecast"]["researchEligible"] is True
    assert detail["researchRuns"][0]["attempts"][0]["status"] == "running"
    assert client.get("/api/v1/daily/latest").json()["chatgpt_research"] == []
    assert store.prediction_snapshot(snapshot.snapshot_id) == snapshot


def test_future_receipts_and_conflicting_outcomes_cannot_replace_started_attempt(tmp_path: Path):
    store, _, view = started(tmp_path)
    claim = store.claim_research(view["run"]["run_id"], now=START + timedelta(minutes=1))
    with pytest.raises(ValueError, match="receipt times"):
        store.finish_research(
            claim["attempt"]["attempt_id"],
            now=START + timedelta(minutes=2),
            response=response_for(),
            started_at=START,
            completed_at=START + timedelta(minutes=30),
        )
    assert (
        store.claim_research(view["run"]["run_id"], now=START + timedelta(minutes=2))["state"]
        == "running"
    )
    complete_phase(store, claim, 1)
    different = response_for()
    different["id"] = "a-different-provider-response"
    with pytest.raises(OperationalConflictError, match="terminal"):
        store.finish_research(
            claim["attempt"]["attempt_id"],
            now=START + timedelta(minutes=3),
            response=different,
            started_at=START + timedelta(minutes=1, seconds=1),
            completed_at=START + timedelta(minutes=1, seconds=30),
        )


def test_schema4_backup_keeps_saved_research_passes_and_adds_empty_job_tables(tmp_path: Path):
    store, snapshot, _ = started(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE chatgpt_research_attempts")
        db.execute("DROP TABLE chatgpt_research_runs")
        db.execute("PRAGMA user_version=4")
    restored = OperationalStore.restore_backup(
        store.path, tmp_path / "restore.sqlite", confirm_replace=True
    )
    migrated = OperationalStore(restored)
    assert migrated.research_runs(snapshot.snapshot_id) == ()
    assert migrated.verify_integrity()["chatgpt_research_attempts"] == 0


def test_embedded_mobile_dispatch_and_exact_backup_preserve_completed_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mobile.python import runtime

    current = [START]
    monkeypatch.setattr(runtime, "STATE", tmp_path / "device")
    monkeypatch.setattr(
        runtime, "create_app", lambda path: create_app(path, clock=lambda: current[0])
    )
    runtime.initialize()
    snapshot = daily_snapshot()
    runtime._app.state.store.append_prediction_snapshot(snapshot)

    def request(path, body):
        reply = asyncio.run(runtime.request("POST", path, json.dumps(body)))
        assert reply["status"] == 200, reply
        return reply["body"]

    view = request(
        f"/api/v1/research/{snapshot.snapshot_id}/A/start",
        {
            "configuration": CONFIG.model_dump(mode="json"),
        },
    )
    run_id = view["run"]["run_id"]
    for minute in (1, 3):
        current[0] = START + timedelta(minutes=minute)
        claim = request(f"/api/v1/research/{run_id}/claim", {})
        started_at = datetime.fromisoformat(claim["attempt"]["started_at"])
        current[0] += timedelta(seconds=30)
        view = request(
            f"/api/v1/research/{claim['attempt']['attempt_id']}/receipt",
            {
                "response": response_for(search=minute == 1),
                "started_at": (started_at + timedelta(seconds=1)).isoformat(),
                "completed_at": (started_at + timedelta(seconds=20)).isoformat(),
            },
        )
    assert view["record"]["affects_numerical_proposal"] is False
    encoded = runtime.export_state()
    runtime.initialize(encoded)
    restored = asyncio.run(runtime.request("GET", "/api/v1/stocks/A"))
    assert restored["body"]["chatgptResearch"][0] == view["record"]
    assert restored["body"]["forecast"]["prediction"] == snapshot.predictions[0].model_dump(
        mode="json"
    )
