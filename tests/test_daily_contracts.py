"""Fault injection at the daily import, provenance, and private sync boundaries."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from stock_ai.domain import Prediction
from stock_ai.ml.evaluation_audit import audit_training_labels
from stock_ai.operations.api import create_app
from stock_ai.operations.cloud import cloud_projection, sync_private_results
from stock_ai.operations.daily import (
    QUOTE_SESSION_LABEL,
    RESEARCH_CRITERIA,
    CompanyResearchRecord,
    PredictionSnapshot,
    ResearchFinding,
    ResearchSource,
    canonical_json,
    export_prediction_snapshot,
    validate_research_link,
)
from tests.conftest import AS_OF
from tests.test_daily_readiness import daily_snapshot, research_for


def test_legacy_label_archives_keep_original_content_and_identity() -> None:
    source = daily_snapshot()
    legacy = PredictionSnapshot.create(
        **{**source.model_dump(exclude={"snapshot_id"}), "label_definition": QUOTE_SESSION_LABEL}
    )
    original = canonical_json(legacy.model_dump(mode="json"))
    restored = PredictionSnapshot.model_validate_json(original)
    assert restored.snapshot_id == legacy.snapshot_id
    assert export_prediction_snapshot(restored).strip() == original
    markdown = export_prediction_snapshot(restored, format="markdown")
    assert "新しい判断入力には使用できません" in markdown


@pytest.mark.parametrize("legacy", [False, True])
def test_stock_view_distinguishes_label_semantics_without_changing_archive(tmp_path, legacy):
    app = create_app(tmp_path / "operations.sqlite3")
    original = daily_snapshot()
    snapshot = PredictionSnapshot.create(**{
        **original.model_dump(exclude={"snapshot_id"}),
        **({"label_definition": QUOTE_SESSION_LABEL} if legacy else {}),
    })
    app.state.store.append_prediction_snapshot(snapshot)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get(f"/api/v1/stocks/A?businessDate={AS_OF.date().isoformat()}")
    assert response.status_code == 200
    view = response.json()["forecast"]
    assert view["labelDefinition"] == snapshot.label_definition
    assert view["labelDefinitionSupported"] is (not legacy)
    assert view["researchEligible"] is (not legacy)
    assert app.state.store.prediction_snapshot(snapshot.snapshot_id) == snapshot


@pytest.mark.parametrize(
    "change",
    [
        {"data_as_of": AS_OF + timedelta(seconds=1)},
        {"generated_at": AS_OF - timedelta(seconds=1)},
        {"active_horizons": (20, 5)},
        {"candidate_symbols": ("A", "A")},
        {"holding_symbols": ("missing",)},
        {"candidate_symbols": ("",)},
        {"model_version": "another-model"},
        {"feature_version": "another-feature"},
        {"data_snapshot_id": "another-data"},
        {"mode": "owner_approved", "adoption_review_id": "a" * 64},
        {"adoption_review_id": "a" * 64},
        {"large_loss_threshold": float("nan")},
        {"downside_quantile_alpha": 0.5},
    ],
)
def test_snapshot_rejects_unusable_or_incoherent_originals(change: dict[str, object]) -> None:
    snapshot = daily_snapshot()
    values = snapshot.model_dump(exclude={"snapshot_id"})
    with pytest.raises(ValueError):
        PredictionSnapshot.create(**{**values, **change})


def test_snapshot_keeps_all_holdings_beyond_candidate_limit() -> None:
    base = daily_snapshot()
    predictions = tuple(
        base.predictions[0].model_copy(
            update={"symbol": f"S{i:02}", "expected_return_20d": i / 100}
        )
        for i in range(25)
    )
    snapshot = PredictionSnapshot.create(
        **{
            **base.model_dump(exclude={"snapshot_id", "predictions"}),
            "predictions": predictions,
            "candidate_symbols": tuple(item.symbol for item in predictions),
            "holding_symbols": ("S00", "S01"),
        }
    )
    assert len(snapshot.research_symbols()) == 22
    assert set(snapshot.holding_symbols) <= set(snapshot.research_symbols())
    assert "S02" not in snapshot.research_symbols()


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_daily_output_cannot_contain_nonfinite_returns(value: float) -> None:
    raw = daily_snapshot().predictions[0].model_dump()
    with pytest.raises(ValidationError):
        Prediction.model_validate({**raw, "expected_return_20d": value})


def test_research_cannot_claim_support_without_complete_time_valid_sources() -> None:
    snapshot = daily_snapshot()
    original = research_for(snapshot)
    values = original.model_dump(exclude={"research_id"})
    with pytest.raises(ValidationError, match="incomplete"):
        CompanyResearchRecord.create(**{**values, "conclusion": "support"})
    with pytest.raises(ValidationError, match="seven ordered"):
        CompanyResearchRecord.create(**{**values, "findings": original.findings[::-1]})
    with pytest.raises(ValidationError, match="unknown"):
        ResearchFinding(criterion="sentiment", assessment="defer", note="unknown")
    with pytest.raises(ValidationError, match="before publication"):
        ResearchSource(
            title="fixture",
            url="https://example.com/report",
            published_at=AS_OF,
            checked_at=AS_OF - timedelta(seconds=1),
        )
    source = ResearchSource(
        title="fixture",
        url="https://example.com/report",
        published_at=AS_OF,
        checked_at=AS_OF + timedelta(hours=1),
    )
    with pytest.raises(ValidationError, match="precedes source"):
        CompanyResearchRecord.create(
            **{
                **values,
                "findings": (
                    ResearchFinding(
                        criterion=RESEARCH_CRITERIA[0],
                        assessment="support",
                        note="fact",
                        sources=(source,),
                    ),
                    *original.findings[1:],
                ),
            }
        )
    for change, error in [
        ({"prediction_snapshot_id": "a" * 64}, "another"),
        ({"symbol": "unselected"}, "top-20"),
        ({"reviewed_at": AS_OF}, "predates"),
    ]:
        record = CompanyResearchRecord.create(**{**values, **change})
        with pytest.raises(ValueError, match=error):
            validate_research_link(record, snapshot)


@pytest.mark.parametrize("invalid", ["[]", "{}", "null", "not-json"])
def test_import_rejects_invalid_schema_without_creating_a_forecast(
    tmp_path: Path, invalid: str
) -> None:
    client = TestClient(create_app(tmp_path / "daily.sqlite3"), base_url="http://127.0.0.1")
    assert (
        client.post("/api/v1/daily/import/preview", json={"jsonText": invalid}).status_code == 422
    )
    assert client.get("/api/v1/daily/latest").json()["snapshot"] is None
    assert client.get("/api/v1/daily/absent/export").status_code == 404


def test_import_links_research_and_exports_same_snapshot(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "daily.sqlite3"), base_url="http://127.0.0.1")
    snapshot = daily_snapshot()
    research = research_for(snapshot)
    body = {"jsonText": research.model_dump_json()}
    assert client.post("/api/v1/daily/import/preview", json=body).status_code == 422
    for record in (snapshot, research):
        body = {"jsonText": record.model_dump_json()}
        preview = client.post("/api/v1/daily/import/preview", json=body)
        assert preview.status_code == 200
        confirmed = client.post(
            "/api/v1/daily/import/confirm",
            json={**body, "confirmationHash": preview.json()["confirmation_hash"]},
            headers={"X-Stock-AI-Intent": "manual-record"},
        )
        assert confirmed.status_code == 200
    latest = client.get("/api/v1/daily/latest").json()
    assert latest["research"][0]["prediction_snapshot_id"] == snapshot.snapshot_id
    for format in ("json", "csv", "markdown"):
        exported = client.get(
            f"/api/v1/daily/{snapshot.snapshot_id}/export", params={"format": format}
        )
        assert exported.status_code == 200
        assert snapshot.snapshot_id in exported.text
    assert client.get(f"/api/v1/daily/{snapshot.snapshot_id}/export?format=xlsx").status_code == 422


@pytest.mark.parametrize(
    "fault", ["post-failure", "post-identity", "readback-mismatch", "readback-failure"]
)
def test_private_sync_refuses_unverified_delivery(fault: str) -> None:
    payload = cloud_projection(daily_snapshot(), (), training_completed=18)
    stored: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            stored.update(json.loads(request.content))
            if fault == "post-failure":
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={"snapshot_id": stored["snapshot_id"], "verified": fault != "post-identity"},
            )
        if fault == "readback-failure":
            return httpx.Response(401)
        return httpx.Response(
            200, json={**stored, "payload_json": "modified", "received_at": "now"}
        )

    with pytest.raises(RuntimeError, match="original local records were retained"):
        sync_private_results(
            payload, bearer_token="fixture-secret", transport=httpx.MockTransport(handler)
        )
    assert daily_snapshot().snapshot_id == payload["source_snapshot_id"]


@pytest.mark.parametrize("bad_field", ["label_start", "label_end", "label_available_at"])
def test_label_audit_rejects_ambiguous_timezones(bad_field: str) -> None:
    row = {
        "prediction_date": "training",
        "label_start": AS_OF - timedelta(days=21),
        "label_end": AS_OF - timedelta(days=1),
        "label_available_at": AS_OF - timedelta(hours=1),
    }
    row[bad_field] = AS_OF.replace(tzinfo=None)
    valid = pd.DataFrame(
        [
            {
                "prediction_date": "validation",
                "label_start": AS_OF,
                "label_end": AS_OF + timedelta(days=20),
            }
        ]
    )
    with pytest.raises(ValueError, match="aware"):
        audit_training_labels(pd.DataFrame([row]), valid, cutoff=AS_OF)
