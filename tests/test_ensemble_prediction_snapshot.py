"""Unit-safe research snapshots, consultation and immutable archive regressions."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

import pytest

from stock_ai.domain.models import ResearchEnsemblePrediction, ReturnOnlyPrediction
from stock_ai.operations.chatgpt_manual import (
    ExternalAiPermission,
    input_package,
    manual_prompt,
    review_answer,
)
from stock_ai.operations.daily import (
    PredictionSnapshot,
    canonical_json,
    content_id,
    export_prediction_snapshot,
    prediction_score,
)
from stock_ai.operations.personal import compare_personal
from stock_ai.operations.store import OperationalStore
from tests.conftest import AS_OF
from tests.test_personal_comparison import scenario


def research_snapshot(*, rank_only=True, risk=False):
    original = scenario()[1]["forecast"]
    rows = tuple(ResearchEnsemblePrediction(
        symbol=p.symbol, as_of=p.as_of, model_version=p.model_version,
        feature_version=p.feature_version, data_snapshot_id=p.data_snapshot_id,
        rank_score_5d=.1 if p.symbol == "1001" else .4,
        rank_score_20d=.7 if p.symbol == "1001" else -.2,
        expected_return_5d=None if rank_only else p.expected_return_5d,
        expected_return_20d=None if rank_only else p.expected_return_20d,
        risk_horizon=20 if risk else None,
        downside_quantile=-.1 if risk else None,
    ) for p in original.predictions)
    return PredictionSnapshot.create(**{
        **original.model_dump(exclude={"snapshot_id", "predictions"}),
        "schema_version": "daily-prediction-snapshot-v2", "predictions": rows,
        "risk_horizon": 20 if risk else None,
        "large_loss_threshold": None, "downside_quantile_alpha": .1 if risk else None,
    })


def permission():
    return ExternalAiPermission(
        service="manual_chatgpt", checked_at=AS_OF, personal_analysis_only=True,
        training_disabled=True, private_input=True, private_output=True,
        data_entitlement_confirmed=True,
    )


@pytest.mark.parametrize("rank_only,risk", [(True, False), (False, False), (True, True)])
def test_research_ensemble_snapshot_preserves_missing_and_optional_heads(rank_only, risk):
    snapshot = research_snapshot(rank_only=rank_only, risk=risk)
    assert not snapshot.risk_available and snapshot.mode == "research"
    assert snapshot.adoption_review_id is None
    restored = PredictionSnapshot.model_validate_json(snapshot.model_dump_json())
    assert restored == snapshot
    for p in restored.predictions:
        assert isinstance(p, ResearchEnsemblePrediction)
        assert p.uncertainty is None and p.large_loss_probability is None
        assert (p.expected_return_20d is None) == rank_only
        assert (p.downside_quantile is not None) == risk
        assert p.rank_unit == "rank_score" and p.return_unit == "fractional_return"


def test_candidate_top20_uses_ranking_even_when_returns_disagree_and_keeps_all_holdings():
    source = research_snapshot(rank_only=False)
    template = source.predictions[0]
    rows = tuple(template.model_copy(update={
        "symbol": f"S{i:02}", "expected_return_20d": -i / 100,
        "rank_score_20d": i / 25,
    }) for i in range(25))
    snapshot = PredictionSnapshot.create(**{
        **source.model_dump(exclude={"snapshot_id", "predictions"}), "predictions": rows,
        "candidate_symbols": tuple(p.symbol for p in rows), "holding_symbols": ("S00", "S01"),
    })
    symbols = snapshot.research_symbols()
    assert symbols[:20] == tuple(f"S{i:02}" for i in range(24, 4, -1))
    assert symbols[20:] == ("S00", "S01")
    assert prediction_score(rows[0], 5) == rows[0].rank_score_5d


@pytest.mark.parametrize("change", [
    {"mode": "owner_approved", "adoption_review_id": "1" * 64},
    {"mode": "paper"}, {"adoption_review_id": "1" * 64},
    {"schema_version": "daily-prediction-snapshot-v1"},
    {"large_loss_threshold": -.08}, {"downside_quantile_alpha": .1}, {"risk_horizon": 20},
])
def test_research_outputs_cannot_claim_adoption_or_invent_risk_definitions(change):
    source = research_snapshot()
    with pytest.raises(ValueError):
        PredictionSnapshot.create(**{**source.model_dump(exclude={"snapshot_id"}), **change})


@pytest.mark.parametrize("change", [
    {"rank_score_5d": None}, {"rank_score_20d": None},
    {"rank_score_20d": float("nan")}, {"expected_return_5d": float("inf")},
    {"large_loss_probability": 1.1}, {"uncertainty": {}},
    {"risk_horizon": 20}, {"expected_return_1d": 0.},
])
def test_invalid_or_fabricated_research_prediction_is_rejected(change):
    values = research_snapshot().predictions[0].model_dump()
    with pytest.raises(ValueError):
        ResearchEnsemblePrediction.model_validate({**values, **change})


def test_missing_head_for_only_one_symbol_and_mixed_old_new_predictions_are_rejected():
    source = research_snapshot()
    rows = list(source.predictions)
    rows[0] = rows[0].model_copy(update={"expected_return_5d": .1})
    with pytest.raises(ValueError, match="availability"):
        PredictionSnapshot.create(**{
            **source.model_dump(exclude={"snapshot_id", "predictions"}), "predictions": rows,
        })
    rows = list(source.predictions)
    rows[0] = scenario()[1]["forecast"].predictions[0]
    with pytest.raises(ValueError, match="unadopted"):
        PredictionSnapshot.create(**{
            **source.model_dump(exclude={"snapshot_id", "predictions"}), "predictions": rows,
        })


def test_new_exports_keep_null_returns_and_label_rank_scores_separately():
    source = research_snapshot()
    assert json.loads(export_prediction_snapshot(source))["predictions"][0][
        "expected_return_20d"] is None
    records = list(csv.DictReader(io.StringIO(export_prediction_snapshot(source, format="csv"))))
    assert all(row["return_20d"] == "" and row["rank_unit"] == "rank_score" for row in records)
    assert all(row["rank_score_20d"] for row in records)
    markdown = export_prediction_snapshot(source, format="markdown")
    assert "20日順位score" in markdown and "期待リターン率ではありません" in markdown
    assert "未提供" in markdown and "None" not in markdown


def test_old_snapshot_identity_and_exports_do_not_gain_new_default_fields():
    original = scenario()[1]["forecast"]
    data = original.model_dump(mode="json")
    assert original.schema_version == "daily-prediction-snapshot-v1"
    assert not any("rank_score_20d" in row for row in data["predictions"])
    assert original.snapshot_id == content_id({k: v for k, v in data.items() if k != "snapshot_id"})
    assert PredictionSnapshot.model_validate_json(canonical_json(data)) == original
    assert "rank_score_20d" not in export_prediction_snapshot(original, format="csv")
    assert "順位score" not in export_prediction_snapshot(original, format="markdown")
    # Old schema3 has the same return/risk null semantics and identity too.
    rows = tuple(ReturnOnlyPrediction(**{key: getattr(row, key) for key in (
        "symbol", "as_of", "expected_return_5d", "expected_return_20d", "model_version",
        "feature_version", "data_snapshot_id",
    )}) for row in original.predictions)
    old = PredictionSnapshot.create(**{
        **original.model_dump(exclude={"snapshot_id", "predictions"}), "predictions": rows,
        "risk_horizon": None, "large_loss_threshold": None, "downside_quantile_alpha": None,
    })
    assert PredictionSnapshot.model_validate_json(old.model_dump_json()) == old
    assert "rank_score_20d" not in export_prediction_snapshot(old)


def test_rank_only_consultation_and_share_validation_preserve_every_ledger():
    request, inputs = scenario()
    inputs["forecast"] = research_snapshot()
    before = {k: v.model_dump_json() for k, v in inputs.items() if k != "executions"}
    comparison = compare_personal(request, **inputs)
    assert comparison.proposal is None
    assert [b.code for b in comparison.blocking_reasons] == ["FORECAST_RISK_UNAVAILABLE"]
    now = AS_OF + timedelta(minutes=3)
    package = input_package(comparison, inputs["ledger"], inputs["forecast"], now=now,
                            permission=permission())
    for row in package["securities"]:
        assert row["forecast_5d"]["value"] is None and row["forecast_20d"]["value"] is None
        assert row["ranking_20d"]["unit"] == "rank_score"
    assert "リターン予測は未提供" in manual_prompt(package)
    answer = dict(
        schema_version="chatgpt-target-shares-v1", input_snapshot_id=package["input_snapshot_id"],
        evidence_as_of=now.isoformat(), unknowns=["Synthetic research only"],
        targets=[dict(symbol=t["symbol"], account=t["account"], target_shares=t["current_shares"],
                      reason="Synthetic hold", sources=[]) for t in package["required_targets"]],
    )
    checked = review_answer(json.dumps(answer), package, comparison, inputs["ledger"],
                            inputs["forecast"], now=now, permission=permission())
    assert not checked["applied_to_ledger"] and not checked["order_submitted"]
    assert all(row["share_difference"] == 0 for row in checked["lines"])
    assert before == {k: v.model_dump_json() for k, v in inputs.items() if k != "executions"}


def test_new_snapshot_is_saved_and_reopened_without_changing_cash_holdings_or_history(tmp_path):
    _request, inputs = scenario()
    original = inputs["ledger"]
    path = tmp_path / "state.sqlite3"
    store = OperationalStore(path)
    store.append_portfolio(original, created_at=AS_OF)
    snapshot = research_snapshot()
    store.append_prediction_snapshot(snapshot)
    reopened = OperationalStore(path)
    assert reopened.latest_prediction_snapshot() == snapshot
    assert reopened.latest_portfolio() == original
    assert reopened.executions() == ()
    reopened.verify_integrity()
