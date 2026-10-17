"""Synthetic connector evidence only; never substitutes fixtures for market history."""

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.ml.market_nav import (
    ActionCoverage,
    ForecastReceipt,
    MarketReceipt,
    MarketStrategyRequest,
    PinnedEvidence,
    evaluate_market_strategy,
    profile_market_rows,
    write_market_strategy,
)
from tests.test_daily_strategy import scenario


@pytest.fixture
def connected(tmp_path, monkeypatch):
    strategy = scenario(bps=20)
    strategy = strategy.model_copy(update={
        "accounting": strategy.accounting.model_copy(update={"data_mode": "historical_research"})
    })
    snapshot = strategy.observations[0].forecasts.data_snapshot_id
    features = SimpleNamespace(locked_holdout_start="2026-08-01", feature_selection_id="TEST",
                               data_snapshot_id=snapshot)
    monkeypatch.setattr("stock_ai.ml.market_nav.load_development_feature_selection",
                        lambda _: features)
    rows = [dict(trading_date=s.trading_date.isoformat(), symbol=p.symbol,
                 symbol_status="standard_equity_code", raw_close=str(p.close_price),
                 bar_state="reported_trade", adjustment_requires_event_evidence=False)
            for s in strategy.accounting.sessions for p in s.prices]
    start, end = strategy.accounting.calendar_dates[0], strategy.accounting.calendar_dates[-1]
    market = tmp_path / "market.json"
    market.write_text(json.dumps(dict(
        schema_version="daily-market-projection-v1", price_basis="unadjusted",
        request=dict(start=start.isoformat(), end=end.isoformat()),
        feature_selection_id="TEST", data_snapshot_id_declared_by_features=snapshot,
        locked_holdout_start=features.locked_holdout_start, holdout_rows_read=False, rows=rows,
    )), encoding="utf-8")
    evidence = tmp_path / "TEST_ONLY_reviewed_evidence.txt"
    evidence.write_text("SYNTHETIC TEST ONLY: reviewed execution/PIT/cost/no-event evidence")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    forecast_receipts = []
    for index, observation in enumerate(strategy.observations):
        path = tmp_path / f"forecast-{index}.json"
        path.write_text(json.dumps({"day": observation.forecasts.model_dump(mode="json")}),
                        encoding="utf-8")
        forecast_receipts.append(ForecastReceipt(
            path=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            as_of=observation.forecasts.as_of,
        ))
    request = MarketStrategyRequest(
        feature_selection_path=tmp_path / "features.json", strategy=strategy,
        market_receipts=(MarketReceipt(path=market, sha256=hashlib.sha256(
            market.read_bytes()).hexdigest(), start=start, end=end),),
        evidence_sources=(PinnedEvidence(path=evidence, sha256=digest),),
        forecast_receipts=tuple(forecast_receipts),
        decision_evidence_sha256=digest, execution_evidence_sha256=digest,
        cost_evidence_sha256=digest,
        action_coverage=(ActionCoverage(
            symbol="A", start_at=strategy.accounting.initial_as_of,
            end_at=strategy.accounting.sessions[-1].close_at, evidence_sha256=digest,
            scope="splits_dividends_cash_conversions_and_other_rights_reviewed", event_ids=(),
        ),),
    )
    return request


def replace_market(plan, **changes):
    ref = plan.market_receipts[0]
    content = json.loads(ref.path.read_bytes())
    content.update(changes)
    ref.path.write_text(json.dumps(content), encoding="utf-8")
    ref = ref.model_copy(update={"sha256": hashlib.sha256(ref.path.read_bytes()).hexdigest()})
    return plan.model_copy(update={"market_receipts": (ref,)})


def test_connection_runs_pretax_costs_and_hold_and_pins_result(connected, tmp_path):
    before = connected.model_dump_json()
    result = evaluate_market_strategy(connected)
    assert result["status"] == "COMPLETE" and result["elapsed_seconds"] > 0
    assert result["no_order_sent"] and result["holdout_scored"] is False
    comparison = result["comparison"]
    assert comparison["decisions_complete"]
    assert any(float(d["trading_cost"]) > 0 for d in comparison["strategy"]["days"])
    assert all(float(d["nav"]) == 300000 for d in comparison["hold"]["days"])
    assert connected.model_dump_json() == before
    path = write_market_strategy(connected, tmp_path / "out")
    assert json.loads(path.read_bytes())["tax_mode"] == "pre_tax"
    assert len(path.stem) == 64


@pytest.mark.parametrize("field,code", [
    ("decision_evidence_sha256", "DECISION_POINT_IN_TIME_EVIDENCE"),
    ("execution_evidence_sha256", "EXECUTION_SETTLEMENT_EVIDENCE"),
    ("cost_evidence_sha256", "COST_POLICY_EVIDENCE"),
])
def test_missing_evidence_returns_no_comparison(connected, field, code):
    result = evaluate_market_strategy(connected.model_copy(update={field: None}))
    assert result["status"] == "BLOCKED" and code in result["blockers"]
    assert result["comparison"] is None


def test_unit_factor_and_no_events_never_establish_corporate_coverage(connected):
    result = evaluate_market_strategy(connected.model_copy(update={"action_coverage": ()}))
    assert result["blockers"] == ["A:CORPORATE_ACTION_COVERAGE"]
    assert result["comparison"] is None
    coverage = connected.action_coverage[0].model_copy(update={
        "end_at": connected.strategy.accounting.sessions[-1].close_at - timedelta(seconds=1)
    })
    assert evaluate_market_strategy(connected.model_copy(update={
        "action_coverage": (coverage,)
    }))["status"] == "BLOCKED"


def test_pinned_evidence_tamper_fails(connected):
    connected.evidence_sources[0].path.write_text("changed")
    with pytest.raises(ValueError, match="evidence bytes changed"):
        evaluate_market_strategy(connected)


def test_missing_and_modified_saved_predictions_rejected(connected):
    result = evaluate_market_strategy(connected.model_copy(update={"forecast_receipts": ()}))
    assert result["comparison"] is None and "SAVED_FORECAST_RECEIPTS" in result["blockers"]
    ref = connected.forecast_receipts[0]
    value = json.loads(ref.path.read_bytes())
    value["day"]["predictions"][0]["expected_return_20d"] = "0.999"
    ref.path.write_text(json.dumps(value), encoding="utf-8")
    changed = ref.model_copy(update={"sha256": hashlib.sha256(ref.path.read_bytes()).hexdigest()})
    with pytest.raises(ValueError, match="differ from the saved predictions"):
        evaluate_market_strategy(connected.model_copy(update={
            "forecast_receipts": (changed, *connected.forecast_receipts[1:])
        }))


@pytest.mark.parametrize("change", [
    {"price_basis": "adjusted"}, {"feature_selection_id": "other"},
    {"data_snapshot_id_declared_by_features": "other"}, {"holdout_rows_read": True},
    {"request": {"start": "2000-01-01", "end": "2000-01-01"}},
])
def test_rehashed_wrong_market_identity_rejected(connected, change):
    with pytest.raises(ValueError, match="identity, raw price basis or window"):
        evaluate_market_strategy(replace_market(connected, **change))


def test_raw_close_mismatch_and_duplicate_keys_rejected(connected):
    content = json.loads(connected.market_receipts[0].path.read_bytes())
    content["rows"][0]["raw_close"] = "999"
    changed = replace_market(connected, rows=content["rows"])
    with pytest.raises(ValueError, match="NAV close differs"):
        evaluate_market_strategy(changed)
    content["rows"].append(content["rows"][0])
    with pytest.raises(ValueError, match="duplicate market key"):
        evaluate_market_strategy(replace_market(connected, rows=content["rows"]))


def test_unresolved_adjustment_and_contradictory_no_trade_never_fill(connected):
    content = json.loads(connected.market_receipts[0].path.read_bytes())
    content["rows"][0].update(adjustment_requires_event_evidence=True, adjustment_factor=0.5)
    result = evaluate_market_strategy(replace_market(connected, rows=content["rows"]))
    assert result["comparison"] is None
    assert any("UNRESOLVED_ADJUSTMENT" in reason for reason in result["blockers"])
    content["rows"][0]["bar_state"] = "reported_no_trade"
    with pytest.raises(ValueError, match="contradicts an untraded"):
        evaluate_market_strategy(replace_market(connected, rows=content["rows"]))


def test_holdout_guard_precedes_market_file_open(connected):
    ref = connected.market_receipts[0]
    ref.path.unlink()
    from datetime import date

    ref = ref.model_copy(update={"end": date(2026, 8, 1)})
    with pytest.raises(ValueError, match="locked holdout"):
        evaluate_market_strategy(connected.model_copy(update={"market_receipts": (ref,)}))


def test_profile_preserves_unknown_status_and_nonstandard_codes():
    rows = [dict(trading_date="2025-01-01", symbol="A", symbol_status="standard_equity_code",
                 bar_state="reported_no_trade", adjustment_requires_event_evidence=False),
            dict(trading_date="2025-01-01", symbol=None, symbol_status="nonstandard_provider_code",
                 bar_state="reported_trade", adjustment_requires_event_evidence=True)]
    result = profile_market_rows(rows)
    assert result["counts"] == dict(rows=2, reported_no_trade=1, nonstandard_code_rows=1,
                                    reported_trade=1, adjustment_rows=1)
    assert result["symbols"] == ["A"]


def test_future_candidate_is_not_required_before_its_first_decision(connected):
    strategy = connected.strategy
    observations = tuple(o.model_copy(update={"candidate_symbols": () if i < 2 else ("A",)})
                         for i, o in enumerate(strategy.observations))
    sessions = tuple(s.model_copy(update={
        "prices": tuple(p for p in s.prices if i == 2 or p.symbol != "A")
    }) for i, s in enumerate(strategy.accounting.sessions))
    strategy = strategy.model_copy(update={
        "observations": observations,
        "accounting": strategy.accounting.model_copy(update={"sessions": sessions}),
    })
    result = evaluate_market_strategy(connected.model_copy(update={"strategy": strategy}))
    assert result["status"] == "COMPLETE"
    assert result["comparison"]["strategy"]["days"][0]["positions"] == []


def test_cli_blocked_receipt_and_exit_code(connected, tmp_path):
    request = connected.model_copy(update={"action_coverage": ()})
    path = tmp_path / "input.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(app, ["research", "evaluate-market-strategy", "--input",
                                     str(path), "--output-root", str(tmp_path / "reports")])
    assert result.exit_code == 2 and '"status": "BLOCKED"' in result.stdout
    assert len(list((tmp_path / "reports").glob("*.json"))) == 1
