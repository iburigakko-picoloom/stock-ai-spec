from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from stock_ai.decision import DecisionEngineConfig
from stock_ai.domain import Prediction
from stock_ai.features import V0_MANIFEST
from stock_ai.ml.advanced import AdvancedResearchConfig
from stock_ai.ml.evaluation_audit import (
    audit_candidate_campaigns,
    audit_training_labels,
    rank_ic,
    validate_development_oof,
    write_audit_receipt,
)
from stock_ai.ml.selection import freeze_development_features, write_development_feature_selection
from stock_ai.operations import (
    OperationalConflictError,
    OperationalIntegrityError,
    OperationalStore,
)
from stock_ai.operations.api import create_app
from stock_ai.operations.automation import AutomationStage, DailyAutomation, StageResult
from stock_ai.operations.cloud import cloud_projection, sync_private_results
from stock_ai.operations.daily import (
    RESEARCH_CRITERIA,
    CompanyResearchRecord,
    OwnerAdoptionReview,
    PredictionSnapshot,
    ResearchFinding,
    canonical_json,
    export_prediction_snapshot,
)
from tests.conftest import AS_OF, candidate, decision_engine, portfolio, prediction
from tests.test_research_selection import _campaign_fixtures, _run_fixture


def daily_snapshot() -> PredictionSnapshot:
    original = prediction("A", 0.1).model_dump()
    original.update(
        schema_version=2, active_horizons=(5, 20), risk_horizon=20, expected_return_1d=None
    )
    value = Prediction.model_validate(original)
    return PredictionSnapshot.create(
        as_of=AS_OF,
        generated_at=AS_OF + timedelta(minutes=1),
        data_as_of=AS_OF - timedelta(hours=20),
        selection_id="selection",
        model_version=value.model_version,
        feature_version=value.feature_version,
        data_snapshot_id=value.data_snapshot_id,
        candidate_symbols=("A",),
        holding_symbols=(),
        predictions=(value,),
        large_loss_threshold=-0.08,
        downside_quantile_alpha=0.1,
        blocking_reasons=("historical revision vintages incomplete",),
    )


def research_for(snapshot: PredictionSnapshot) -> CompanyResearchRecord:
    return CompanyResearchRecord.create(
        prediction_snapshot_id=snapshot.snapshot_id,
        symbol="A",
        reviewed_at=AS_OF + timedelta(minutes=5),
        conclusion="defer",
        findings=tuple(
            ResearchFinding(criterion=criterion, assessment="defer", note="未調査")
            for criterion in RESEARCH_CRITERIA
        ),
    )


def test_missing_one_day_never_becomes_zero_or_five_day() -> None:
    snapshot = daily_snapshot()
    assert snapshot.predictions[0].expected_return_1d is None
    assert (
        Prediction.model_validate_json(prediction("A", 0.1).model_dump_json()).schema_version == 1
    )
    raw = snapshot.predictions[0].model_dump()
    for invalid in (
        {"expected_return_1d": 0.0},
        {"risk_horizon": 5},
        {"active_horizons": (1, 5, 20)},
    ):
        with pytest.raises(ValidationError):
            Prediction.model_validate({**raw, **invalid})
    engine = decision_engine()
    item = candidate("A", 0.1).model_copy(update={"prediction": snapshot.predictions[0]})
    with pytest.raises(ValueError, match="20d decision policy"):
        engine.propose(
            portfolio=portfolio(),
            candidates=(item,),
            generated_at=AS_OF,
            model_bundle_version=prediction("A", 0.1).model_version,
        )
    engine.config = DecisionEngineConfig.daily()
    result = engine._signal_utility(item, 100)
    changed = item.model_copy(
        update={"prediction": item.prediction.model_copy(update={"expected_return_5d": -0.99})}
    )
    assert engine._signal_utility(changed, 100) == result
    with pytest.raises(ValueError, match="nonnegative"):
        DecisionEngineConfig(horizon_weights=(Decimal("-1"), Decimal("1"), Decimal("1")))


def test_original_predictions_research_and_backup_round_trip(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "daily.sqlite3")
    snapshot = daily_snapshot()
    assert store.append_prediction_snapshot(snapshot)
    assert not store.append_prediction_snapshot(snapshot)
    research = research_for(snapshot)
    assert store.append_company_research(research)
    assert not store.append_company_research(research)
    assert store.prediction_snapshot(snapshot.snapshot_id) == snapshot
    assert store.latest_prediction_snapshot() == snapshot
    assert store.company_research(snapshot.snapshot_id) == (research,)
    counts = store.verify_integrity()
    assert counts["prediction_snapshots"] == counts["company_research"] == 1
    backup = store.backup(tmp_path / "backup.sqlite3")
    restored = OperationalStore.restore_backup(
        backup, tmp_path / "restored.sqlite3", confirm_replace=True
    )
    assert OperationalStore(restored).prediction_snapshot(snapshot.snapshot_id) == snapshot
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE prediction_snapshots SET payload='{}'")
    with pytest.raises(OperationalIntegrityError, match="hash mismatch"):
        store.verify_integrity()


def test_daily_import_preview_confirm_and_idempotence(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "ops.sqlite3"), base_url="http://127.0.0.1")
    snapshot = daily_snapshot()
    body = {"jsonText": export_prediction_snapshot(snapshot)}
    preview = client.post("/api/v1/daily/import/preview", json=body)
    assert preview.status_code == 200
    assert client.get("/api/v1/daily/latest").json()["snapshot"] is None
    confirm = {**body, "confirmationHash": preview.json()["confirmation_hash"]}
    assert client.post("/api/v1/daily/import/confirm", json=confirm).status_code == 428
    headers = {"X-Stock-AI-Intent": "manual-record"}
    assert client.post("/api/v1/daily/import/confirm", json=confirm, headers=headers).json()[
        "inserted"
    ]
    assert not client.post("/api/v1/daily/import/confirm", json=confirm, headers=headers).json()[
        "inserted"
    ]
    assert (
        client.post(
            "/api/v1/daily/import/confirm",
            json={**confirm, "confirmationHash": "x"},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        client.get("/api/v1/daily/latest").json()["snapshot"]["predictions"][0][
            "expected_return_1d"
        ]
        is None
    )
    for format in ("json", "csv", "markdown"):
        response = client.get(f"/api/v1/daily/{snapshot.snapshot_id}/export?format={format}")
        assert response.status_code == 200 and snapshot.snapshot_id in response.text


def test_unlinked_or_incomplete_research_cannot_overwrite_predictions(tmp_path: Path) -> None:
    snapshot = daily_snapshot()
    store = OperationalStore(tmp_path / "ops.sqlite3")
    with pytest.raises(OperationalConflictError, match="must exist first"):
        store.append_company_research(research_for(snapshot))
    with pytest.raises(ValidationError):
        ResearchFinding(criterion=RESEARCH_CRITERIA[0], assessment="support", note="no evidence")
    raw = snapshot.model_dump(mode="json")
    raw["predictions"][0]["expected_return_20d"] = 0.9
    with pytest.raises(ValidationError, match="identity mismatch"):
        PredictionSnapshot.model_validate(raw)
    assert "未提供" in export_prediction_snapshot(snapshot, format="markdown")
    with pytest.raises(ValueError):
        export_prediction_snapshot(snapshot, format="xlsx")


def test_daily_only_workflow_does_not_require_morning_jobs(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "daily.sqlite3")
    automation = DailyAutomation(store, daily_only=True)
    stages = (
        AutomationStage.DATA_SYNC,
        AutomationStage.CANDIDATE_SELECTION,
        AutomationStage.PREDICTION,
    )
    handlers = {
        stage: lambda _: StageResult(artifact_id="daily", data_as_of=AS_OF) for stage in stages
    }
    now = datetime.now(AS_OF.tzinfo)
    jobs = automation.run(business_date=AS_OF.date(), now=now, stages=stages, handlers=handlers)
    assert all(job.status.value == "SUCCEEDED" for job in jobs)
    assert store.daily_status(AS_OF.date()).morning_data_as_of is None
    replay = automation.run(business_date=AS_OF.date(), now=now, stages=stages, handlers={})
    assert [job.run_id for job in replay] == [job.run_id for job in jobs]


def test_rank_ic_hand_values_and_unavailable_sections() -> None:
    assert rank_ic([1, 2, 3], [3, 4, 5]) == pytest.approx(1)
    assert rank_ic([1, 2, 3], [5, 4, 3]) == pytest.approx(-1)
    assert rank_ic([1, 1, 3], [1, 2, 3]) == pytest.approx(np.sqrt(3) / 2)
    assert rank_ic([1, 1, 1], [1, 2, 3]) is None
    assert rank_ic([1, 2, np.nan], [1, 2, 3]) is None
    with pytest.raises(ValueError):
        rank_ic([1], [1, 2])


def test_label_audit_closed_boundary_receipt_and_date_groups() -> None:
    row = dict(
        prediction_date="train",
        label_start=AS_OF - timedelta(days=20),
        label_end=AS_OF - timedelta(seconds=1),
        label_available_at=AS_OF - timedelta(seconds=1),
    )
    validation = pd.DataFrame(
        [dict(prediction_date="valid", label_start=AS_OF, label_end=AS_OF + timedelta(days=20))]
    )
    assert audit_training_labels(pd.DataFrame([row]), validation, cutoff=AS_OF) == ()
    changed = {**row, "label_end": AS_OF, "label_available_at": AS_OF, "prediction_date": "valid"}
    assert set(audit_training_labels(pd.DataFrame([changed]), validation, cutoff=AS_OF)) == {
        "IMMATURE_TRAINING_LABEL",
        "SPLIT_DATE_GROUP",
        "OVERLAPPING_LABEL_INTERVAL",
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        audit_training_labels(pd.DataFrame([row]), validation, cutoff=AS_OF.replace(tzinfo=None))


@pytest.mark.parametrize("score_development", [False, True])
def test_candidate_audit_authenticates_complete_matrix_and_retains_failures(
    tmp_path: Path, score_development: bool
) -> None:
    ablation, candidate_path = _campaign_fixtures(tmp_path)
    features = freeze_development_features(ablation_campaign_paths=(ablation,))
    feature_path = write_development_feature_selection(features, tmp_path / "features")
    result = audit_candidate_campaigns(
        feature_selection_path=feature_path,
        candidate_campaign_paths=(candidate_path,),
        score_development=score_development,
    )
    assert result["status"] == "PASS" and len(result["runs"]) == 27
    assert not result["locked_holdout_opened_by_audit"]
    if score_development:
        assert result["schema_version"] == "daily-evaluation-audit-v2"
        for run in result["runs"]:
            metrics = run["development_metrics"]
            assert metrics["report_id"] == run["report_id"]
            assert set(metrics["scores"]) == {"regression", "ranking", "quantile", "large_loss"}
            assert not metrics["scores"]["quantile"]["crossing_check_available"]
            assert not metrics["adoption_eligible"]
    path = write_audit_receipt(result, tmp_path / "audit")
    assert json.loads(path.read_text())["status"] == "PASS"
    duplicate = audit_candidate_campaigns(
        feature_selection_path=feature_path,
        candidate_campaign_paths=(candidate_path, candidate_path),
    )
    assert duplicate["status"] == "FAIL" and duplicate["problems"]


def test_oof_rejects_duplicate_and_holdout_rows() -> None:
    run = _run_fixture(
        config=AdvancedResearchConfig(horizons=(5,), model_families=("lightgbm",), seeds=(17,)),
        feature_names=V0_MANIFEST.feature_names,
        run_ablations=False,
        code_commit="test",
    )
    frame = run.oof_predictions
    validate_development_oof(frame, run.report)
    with pytest.raises(ValueError, match="duplicate"):
        validate_development_oof(pd.concat([frame, frame.iloc[:1]]), run.report)
    changed = frame.copy()
    changed.loc[0, "label_end"] = pd.Timestamp(run.report.locked_holdout_start)
    with pytest.raises(ValueError, match="holdout"):
        validate_development_oof(changed, run.report)
    changed = frame.copy()
    changed.loc[0, "prediction"] = np.nan
    with pytest.raises(ValueError, match="missing"):
        validate_development_oof(changed, run.report)


def test_owner_review_is_explicit_and_has_no_sixty_day_auto_promotion(tmp_path: Path) -> None:
    original = daily_snapshot()
    store = OperationalStore(tmp_path / "review.sqlite3")
    review = OwnerAdoptionReview.create(
        selection_id="a" * 64,
        holdout_report_id="b" * 64,
        evaluator_receipt_id="c" * 64,
        decision_policy_hash="d" * 64,
        reviewed_at=AS_OF,
        decision="adopt",
        unresolved_gates=(),
        acknowledged_limitations=("single vintage",),
        note="本人の評価結果確認",
    )
    approved = PredictionSnapshot.create(
        **{
            **original.model_dump(exclude={"snapshot_id", "predictions"}),
            "predictions": original.predictions,
            "selection_id": "a" * 64,
            "mode": "owner_approved",
            "adoption_review_id": review.review_id,
            "blocking_reasons": (),
        }
    )
    with pytest.raises(OperationalIntegrityError, match="saved owner"):
        store.append_prediction_snapshot(approved)
    with pytest.raises(ValueError, match="authenticated evaluator/holdout"):
        store.append_adoption_review(review)
    paper = OwnerAdoptionReview.create(
        **{**review.model_dump(exclude={"review_id"}), "decision": "continue_paper"}
    )
    assert store.append_adoption_review(paper)
    assert not store.append_adoption_review(paper)
    assert store.adoption_review(paper.review_id) == paper
    with pytest.raises(OperationalIntegrityError, match="saved owner"):
        store.append_prediction_snapshot(approved)
    assert store.verify_integrity()["adoption_reviews"] == 1
    with pytest.raises(ValidationError, match="prevent adoption"):
        OwnerAdoptionReview.create(
            **{**review.model_dump(exclude={"review_id"}), "unresolved_gates": ("cost evaluation",)}
        )


def test_private_projection_and_sync_readback_do_not_send_accounts_or_secrets() -> None:
    snapshot = daily_snapshot()
    payload = cloud_projection(snapshot, (research_for(snapshot),), training_completed=18)
    assert payload["forecasts"][0]["expected_return_1d"] is None
    assert "account" not in canonical_json(payload)
    stored: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "stock-ai-private-daily.manato0618.chatgpt.site"
        if request.method == "POST":
            body = json.loads(request.content)
            stored.update(body)
            return httpx.Response(200, json={"snapshot_id": body["snapshot_id"], "verified": True})
        return httpx.Response(200, json={**stored, "received_at": AS_OF.isoformat()})

    result = sync_private_results(
        payload, bearer_token="secret-for-test", transport=httpx.MockTransport(handler)
    )
    assert result["snapshot_id"] == hashlib.sha256(stored["payload_json"].encode()).hexdigest()
    with pytest.raises(ValueError, match="private Site origin"):
        sync_private_results(payload, bearer_token="secret", origin="https://public.example")
    with pytest.raises(RuntimeError, match="local records were retained") as error:
        sync_private_results(
            payload,
            bearer_token="secret-for-test",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(302, headers={"Location": "https://elsewhere.example"})
            ),
        )
    assert "secret-for-test" not in str(error.value)
