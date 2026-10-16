from __future__ import annotations

import copy
import json
import sqlite3
from datetime import timedelta

import pytest
from mobile.python import forecasts, market, models, personal

from stock_ai.operations.daily import PredictionSnapshot, canonical_json, content_id
from stock_ai.operations.store import OperationalConflictError
from tests.test_mobile_bundles import CUTOFF, IMPORTED, SELECTION, fixture_bundle, fixture_pin
from tests.test_mobile_market import payload as history_payload
from tests.test_mobile_personal import NOW as LEDGER_TIME
from tests.test_mobile_personal import setup
from tests.test_mobile_runtime import device as device_fixture

NOW = CUTOFF + timedelta(minutes=20)


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    device = device_fixture.__wrapped__(tmp_path, monkeypatch)
    store, _ = setup(device, held=True)
    path = device.STATE / "mobile.sqlite3"
    market.ingest(path, history_payload())
    preview = personal.preview_initial(store, path, LEDGER_TIME, persist=True)
    personal.confirm_initial(store, path, preview["preview_id"], True, LEDGER_TIME)
    bundle = fixture_bundle()
    current = {"approved_models": [], "approved_bundles": [fixture_pin(bundle)]}
    monkeypatch.setattr(models, "policy", lambda: current)
    monkeypatch.setattr(models, "bundled_selection", lambda: SELECTION)
    monkeypatch.setattr(forecasts, "bundled_selection", lambda: SELECTION)
    models.import_bundle(path, canonical_json(bundle.model_dump(mode="json")), IMPORTED)
    # Explicit provider/feature doubles isolate the new publication contract.
    # Feature formula/PC/WASM parity and real source validation have separate gates.
    selection = {"as_of": CUTOFF.isoformat(), "policy": "synthetic-fixture",
                 "new_candidates": [{"symbol": "1000", "company_name": "Synthetic fixture"}],
                 "decision_symbols": ["1000", "7203"], "held_only": ["7203"],
                 "blocking_reasons": [], "membership_verified": True,
                 "membership_received_at": "2026-02-03T02:15:00Z",
                 "latest_source_date": "2026-02-02"}
    features = {"as_of": CUTOFF.isoformat(), "features": {
        str(h): [{"symbol": symbol, "available_at": CUTOFF.isoformat(), "f1": 1.0}
                 for symbol in ("1000", "7203")] for h in (5, 20)
    }}
    inputs = {"as_of": CUTOFF.isoformat(), "latest_source_received_at": "2026-02-03T01:00:00Z",
              "source_snapshot_ids": [(name.value, "4" * 64) for name in market.DatasetName],
              "revision_policy": "synthetic-fixture-conservative"}
    monkeypatch.setattr(forecasts.universe, "select", lambda *a, **kw: copy.deepcopy(selection))
    monkeypatch.setattr(forecasts.market, "feature_inputs", lambda *a: copy.deepcopy(inputs))
    monkeypatch.setattr(forecasts, "calculate", lambda *a: copy.deepcopy(features))
    return device, store, path, selection, features, current


def test_calibrated_forecast_covers_all_holdings_and_survives_exact_backup(ready):
    device, store, path, _, _, _ = ready
    before = store.latest_portfolio()
    result = forecasts.generate(path, store, NOW)
    assert result["phase"] == "published" and result["outcome"] == "forecast"
    snapshot = store.latest_prediction_snapshot()
    assert snapshot.candidate_symbols == ("1000",) and snapshot.holding_symbols == ("7203",)
    assert snapshot.research_symbols() == ("1000", "7203")
    assert all(x.uncertainty.standard_error == .02 for x in snapshot.predictions)
    assert all(x.expected_return_1d is None and x.expected_return_20d == .04
               and x.expected_return_5d == .01 for x in snapshot.predictions)
    assert snapshot.data_as_of < snapshot.as_of < snapshot.generated_at
    assert snapshot.mode == "research" and snapshot.adoption_review_id is None
    assert store.latest_portfolio() == before
    assert not models.status(path, store)["model_adopted"]
    assert "available_cash_yen" not in canonical_json(result)
    assert "preprocessor" not in canonical_json(result)
    encoded = device.export_state()
    device.initialize(encoded)
    assert forecasts.latest(path) == result
    assert device._app.state.store.latest_prediction_snapshot() == snapshot


def test_identical_freeze_reuses_original_numbers_and_generation_time(ready, monkeypatch):
    _, store, path, _, _, _ = ready
    original = forecasts.generate(path, store, NOW)
    monkeypatch.setattr(forecasts, "predict", lambda *a: pytest.fail("model dispatched twice"))
    assert forecasts.generate(path, store, NOW + timedelta(minutes=1)) == original
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM mobile_forecast_runs").fetchone()[0] == 1


def test_missing_held_forecast_preserves_partial_output_and_blocks_publication(ready):
    _, store, path, _, features, _ = ready
    features["features"]["5"] = features["features"]["5"][:1]
    result = forecasts.generate(path, store, NOW)
    assert result["snapshot"] is None and store.latest_prediction_snapshot() is None
    assert result["blocking_reasons"] == ["HELD_FORECAST_MISSING:7203"]
    assert result["outputs"][0]["values"] == [["1000", .01]]
    assert result["scope"]["holding_symbols"] == ["7203"]


def test_unmodeled_new_candidate_is_explicitly_preserved_as_excluded_not_a_fake_prediction(ready):
    _, store, path, selection, _, _ = ready
    selection["new_candidates"].append({"symbol": "2000", "company_name": "New fixture"})
    selection["decision_symbols"].append("2000")
    result = forecasts.generate(path, store, NOW)
    assert result["excluded_candidates"] == [
        {"symbol": "2000", "reason": "FEATURE_HISTORY_UNAVAILABLE"}
    ]
    assert len(result["scope"]["universe"]["new_candidates"]) == 2
    assert store.latest_prediction_snapshot().candidate_symbols == ("1000",)
    assert store.latest_prediction_snapshot().holding_symbols == ("7203",)


def test_lost_publication_retries_the_saved_receipt(ready, monkeypatch):
    _, store, path, _, _, _ = ready
    original = store.append_prediction_snapshot
    def fail(*a, **kw):
        raise ValueError("synthetic publication interruption")
    monkeypatch.setattr(store, "append_prediction_snapshot", fail)
    with pytest.raises(ValueError, match="interruption"):
        forecasts.generate(path, store, NOW)
    assert forecasts.latest(path)["phase"] == "computed"
    assert store.latest_prediction_snapshot() is None
    monkeypatch.setattr(store, "append_prediction_snapshot", original)
    monkeypatch.setattr(forecasts, "predict", lambda *a: pytest.fail("computed output resent"))
    result = forecasts.generate(path, store, NOW + timedelta(minutes=1))
    assert result["phase"] == "published"
    assert result["snapshot"]["generated_at"] == PredictionSnapshot.model_validate(
        result["snapshot"]
    ).generated_at.isoformat()
    assert store.latest_prediction_snapshot().generated_at == NOW


def test_publication_marker_is_reconciled_after_restart(ready, monkeypatch):
    device, store, path, _, _, _ = ready
    original = store.append_prediction_snapshot
    def save_then_interrupt(*a, **kw):
        original(*a, **kw)
        raise ValueError("synthetic marker interruption")
    monkeypatch.setattr(store, "append_prediction_snapshot", save_then_interrupt)
    with pytest.raises(ValueError):
        forecasts.generate(path, store, NOW)
    assert forecasts.latest(path)["phase"] == "computed"
    snapshot = store.latest_prediction_snapshot()
    device.initialize(device.export_state())
    assert forecasts.latest(path)["phase"] == "published"
    assert device._app.state.store.latest_prediction_snapshot() == snapshot


def test_personal_input_change_is_checked_inside_the_snapshot_write_transaction(ready, monkeypatch):
    _, store, path, _, _, _ = ready
    original = store.append_prediction_snapshot
    manual = store.latest_manual_portfolio()
    def change_then_save(*a, **kw):
        personal.save_portfolio(store, manual.portfolio, manual.export.revision_id, NOW)
        return original(*a, **kw)
    monkeypatch.setattr(store, "append_prediction_snapshot", change_then_save)
    with pytest.raises(OperationalConflictError, match="inputs changed"):
        forecasts.generate(path, store, NOW)
    assert store.latest_prediction_snapshot() is None
    assert forecasts.latest(path)["phase"] == "computed"


def test_later_missing_approval_or_personal_input_never_overwrites_prior_prediction(ready):
    _, store, path, _, _, current = ready
    first = forecasts.generate(path, store, NOW)
    saved = store.latest_prediction_snapshot()
    current["approved_bundles"] = []
    assert forecasts.generate(path, store, NOW)["blocking_reasons"] == [
        "CALIBRATED_MODEL_BUNDLE_UNAVAILABLE"
    ]
    assert store.latest_prediction_snapshot() == saved
    manual = store.latest_manual_portfolio()
    personal.save_portfolio(store, manual.portfolio, manual.export.revision_id, NOW)
    later = forecasts.generate(path, store, NOW)
    assert later["blocking_reasons"] == ["PERSONAL_INPUT_AFTER_ALPHA_CUTOFF"]
    assert store.latest_prediction_snapshot().snapshot_id == first["snapshot"]["snapshot_id"]


def test_rehashed_output_disagreement_with_the_original_snapshot_is_rejected(ready):
    _, store, path, _, _, _ = ready
    forecasts.generate(path, store, NOW)
    with sqlite3.connect(path) as db:
        identity, payload = db.execute("SELECT run_id,payload FROM mobile_forecast_runs").fetchone()
        value = json.loads(payload)
        value["outputs"][0]["values"][0][1] += 1
        value["run_id"] = content_id({k: v for k, v in value.items() if k != "run_id"})
        db.execute("UPDATE mobile_forecast_runs SET run_id=?,payload=?,content_hash=? "
                   "WHERE run_id=?",
                   (value["run_id"], canonical_json(value), content_id(value), identity))
    with pytest.raises(ValueError, match="preserved numerical output"):
        forecasts.latest(path)


def test_open_cutoff_does_not_create_fake_predictions(ready):
    _, store, path, _, _, _ = ready
    assert forecasts.generate(path, store, CUTOFF - timedelta(microseconds=1))[
        "blocking_reasons"
    ] == ["ALPHA_CUTOFF_OPEN"]
    assert store.latest_prediction_snapshot() is None


def test_empty_equity_universe_is_cash_only_without_fabricated_forecast(ready, monkeypatch):
    _, store, path, selection, _, _ = ready
    manual = store.latest_manual_portfolio()
    empty = manual.portfolio.model_copy(update={"holdings": (), "holdings_status": "none"})
    personal.save_portfolio(store, empty, manual.export.revision_id,
                            LEDGER_TIME + timedelta(days=1))
    original = store.latest_portfolio()
    cash = original.model_copy(update={"portfolio_id": "synthetic-cash-only",
                                      "positions": (), "as_of": LEDGER_TIME + timedelta(days=1)})
    store.append_portfolio(cash, created_at=LEDGER_TIME + timedelta(days=1))
    selection["new_candidates"] = []
    selection["decision_symbols"] = []
    monkeypatch.setattr(forecasts, "predict", lambda *a: pytest.fail("empty universe inferred"))
    result = forecasts.generate(path, store, NOW)
    assert result["outcome"] == "cash_only" and not result["blocking_reasons"]
    assert result["snapshot"] is None and store.latest_prediction_snapshot() is None
    assert store.latest_portfolio() == cash
