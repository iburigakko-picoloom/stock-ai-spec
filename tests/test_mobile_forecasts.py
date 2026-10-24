from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import sqlite3
import struct
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
    def selected_inputs(*args, decision_symbols):
        assert sorted(decision_symbols) == sorted(selection["decision_symbols"])
        return copy.deepcopy(inputs)
    monkeypatch.setattr(forecasts.market, "feature_inputs", selected_inputs)
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


def test_preselection_dispatch_and_proof_ignore_nonsemantic_cache_hit_metrics(ready, monkeypatch):
    _, store, path, selected, _, _ = ready
    selected["policy"] = "jquants-scalecat-topix500-v1"
    original = forecasts.market.feature_inputs
    calls = []
    def prepared(*args, decision_symbols, preselected):
        assert preselected is True
        result = original(*args, decision_symbols=decision_symbols)
        calls.append(True)
        result["input_cache"] = {"mode": "cold" if len(calls) == 1 else "warm",
                                 "code_version": "a" * 64, "cache_schema_version": "test",
                                 "common_population": "full_historical_eligible_market"}
        return result
    monkeypatch.setattr(forecasts.market, "feature_inputs", prepared)
    first = forecasts.generate(path, store, NOW)
    assert first["data_proof"]["input_preparation"]["code_version"] == "a" * 64
    assert forecasts.generate(path, store, NOW + timedelta(seconds=1)) == first


@pytest.mark.parametrize("omit_holding", [False, True])
def test_forecast_authenticates_the_calculation_domain_including_holdings(
    ready, monkeypatch, omit_holding,
):
    _, store, path, _, _, _ = ready
    original = forecasts.market.feature_inputs
    def scoped_inputs(*args, decision_symbols):
        value = original(*args, decision_symbols=decision_symbols)
        value["decision_symbols"] = ["1000"] if omit_holding else sorted(decision_symbols)
        return value
    monkeypatch.setattr(forecasts.market, "feature_inputs", scoped_inputs)
    before = store.latest_portfolio()
    if omit_holding:
        with pytest.raises(ValueError, match="Feature calculation domain mismatch"):
            forecasts.generate(path, store, NOW)
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*) FROM mobile_forecast_runs").fetchone()[0] == 0
    else:
        result = forecasts.generate(path, store, NOW)
        assert result["data_proof"]["feature_calculation_symbols"] == ["1000", "7203"]
        assert forecasts.latest(path) == result
    assert store.latest_portfolio() == before


def test_old_history_outside_the_current_decision_scope_is_preserved_without_blocking(ready):
    _, store, path, _, features, _ = ready
    before = store.latest_portfolio()
    for horizon in ("5", "20"):
        features["features"][horizon].append({
            "symbol": "9999", "available_at": (CUTOFF - timedelta(days=30)).isoformat(),
            "f1": 1.0,
        })
    result = forecasts.generate(path, store, NOW)
    snapshot = store.latest_prediction_snapshot()
    assert result["phase"] == "published"
    assert snapshot.research_symbols() == ("1000", "7203")
    assert snapshot.holding_symbols == ("7203",)
    assert all({symbol for symbol, _ in output["values"]} == {"1000", "7203"}
               for output in result["outputs"])
    assert result["data_proof"]["feature_values_sha256"] == content_id(features["features"])
    assert store.latest_portfolio() == before


@pytest.mark.parametrize(("symbol", "stamp"), [
    ("1000", CUTOFF - timedelta(microseconds=1)),
    ("7203", CUTOFF - timedelta(days=1)),
    ("9999", CUTOFF + timedelta(microseconds=1)),
    ("9999", CUTOFF.replace(tzinfo=None)),
])
def test_selected_stale_and_any_future_or_unzoned_features_cannot_publish(ready, symbol, stamp):
    _, store, path, _, features, _ = ready
    before = store.latest_portfolio()
    rows = features["features"]["20"]
    if symbol == "9999":
        rows.append({"symbol": symbol, "available_at": stamp.isoformat(), "f1": 1.0})
    else:
        next(row for row in rows if row["symbol"] == symbol)["available_at"] = stamp.isoformat()
    with pytest.raises(ValueError, match="Feature provenance mismatch"):
        forecasts.generate(path, store, NOW)
    assert store.latest_prediction_snapshot() is None
    assert forecasts.latest(path) is None
    assert store.latest_portfolio() == before


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


def test_uncommitted_selection_never_uses_old_snapshot_after_restart(ready, monkeypatch):
    device, store, path, _, features, _ = ready
    first = forecasts.generate(path, store, NOW)
    snapshot = store.latest_prediction_snapshot()
    features["features"]["5"][0]["f1"] = 2.0
    def interrupt(*args, **kwargs):
        raise ValueError("synthetic interruption")
    monkeypatch.setattr(store, "append_prediction_snapshot", interrupt)
    with pytest.raises(ValueError, match="interruption"):
        forecasts.generate(path, store, NOW + timedelta(minutes=1))
    assert forecasts.latest(path)["run_id"] != first["run_id"]
    device.initialize(device.export_state())
    assert forecasts.latest(path)["phase"] == "computed"
    assert device._app.state.store.latest_prediction_snapshot() is None
    assert device._app.state.store.prediction_snapshot(snapshot.snapshot_id) == snapshot


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
    assert store.prediction_snapshot(saved.snapshot_id) == saved
    assert store.latest_prediction_snapshot() is None  # No active fallback after a failed run.
    manual = store.latest_manual_portfolio()
    personal.save_portfolio(store, manual.portfolio, manual.export.revision_id, NOW)
    later = forecasts.generate(path, store, NOW)
    assert later["blocking_reasons"] == ["PERSONAL_INPUT_AFTER_ALPHA_CUTOFF"]
    assert store.prediction_snapshot(first["snapshot"]["snapshot_id"]) == saved
    assert store.latest_prediction_snapshot() is None


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
        db.execute("UPDATE mobile_forecast_selections SET run_id=? WHERE run_id=?",
                   (value["run_id"], identity))
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


def received_history_ready(tmp_path, monkeypatch, *, funded=False):
    """Shared PC/WASM fixture: actual received history, synthetic model config only."""
    from mobile.python import membership
    from mobile.python.model_bundle import ModelBundle, encoded
    from scripts.mobile_capacity_check import make_payload

    from stock_ai.operations.daily import OwnerAdoptionReview
    from stock_ai.operations.manual_portfolio import ManualPortfolio
    from stock_ai.operations.manual_settings import ManualPersonalSettings
    from tests.test_mobile_features import frozen_selection, timely_history
    from tests.test_mobile_personal import profile, settings

    device = device_fixture.__wrapped__(tmp_path, monkeypatch)
    path, store = device.STATE / "mobile.sqlite3", device._app.state.store
    cutoff = timely_history(path, sessions=270, symbols=24)
    saved_at, now = cutoff - timedelta(minutes=15), cutoff + timedelta(minutes=1)
    value = profile(held=True).model_dump(mode="json")
    value["holdings"][0]["symbol"] = "1023"  # Outside the tied top20, still required.
    if funded:
        value["investment_budget_yen"] = "2000000"
        value["accounts"][0]["available_cash_yen"] = "2000000"
    saved = personal.save_portfolio(store, ManualPortfolio.model_validate(value), None, saved_at)
    extra = settings(saved["revision_id"]).model_dump(mode="json")
    extra["tax_year"] = cutoff.year
    extra["tax_assumptions"]["effective_from"] = f"{cutoff.year}-01-01"
    extra["research_decision_policy"] = "daily-decision-engine-v3-bounded"
    personal.save_settings(store, ManualPersonalSettings.model_validate(extra), None, saved_at)
    preview = personal.preview_initial(store, path, saved_at, persist=True)
    assert not preview["blocking_reasons"]
    personal.confirm_initial(store, path, preview["preview_id"], True, saved_at)

    observed = make_payload(cutoff.date(), 270, 24, random.Random(20261017),
                            initial_receipt=cutoff - timedelta(minutes=20))
    names = {"security_master", "trading_calendar"}
    observed.update(purpose="membership", status=200,
                    datasets={name: observed["datasets"][name] for name in names},
                    source_pages=[p for p in observed["source_pages"] if p["dataset"] in names])
    observed.pop("valuations")
    membership.ingest(path, observed, cutoff)

    selection = frozen_selection()
    data = fixture_bundle().model_dump(mode="json", exclude={"bundle_id"})
    data.update(created_at=(cutoff - timedelta(minutes=15)).isoformat(),
                trained_at=(cutoff - timedelta(days=25)).isoformat(),
                training_data_cutoff=(cutoff - timedelta(days=30)).isoformat(),
                feature_selection_id=selection["feature_selection_id"],
                feature_manifest_hash=selection["feature_manifest_hash"])
    data["adoption_review"] = OwnerAdoptionReview.create(**{
        **{k: v for k, v in data["adoption_review"].items() if k != "review_id"},
        "reviewed_at": cutoff - timedelta(minutes=20),
        "unresolved_gates": tuple(data["adoption_review"]["unresolved_gates"]),
        "acknowledged_limitations": tuple(data["adoption_review"]["acknowledged_limitations"]),
    }).model_dump(mode="json")
    data["calibration"].update(
        latest_label_available_at=(cutoff - timedelta(days=2)).isoformat(),
        fitted_at=(cutoff - timedelta(days=1)).isoformat(),
    )
    if funded:
        data["calibration"]["residual_rmse"] = .002
    feature = "price.return_5d"
    assert all(feature in horizon["feature_names"] for horizon in selection["horizons"])
    for head in data["heads"]:
        model = json.loads(head["content"])
        model["preprocessor"] = {"retained": [feature], "lower": {feature: None},
                                 "upper": {feature: None}, "median": {feature: 0.0}}
        if head["task"] == "large_loss":
            model["trees"] = [{"feature": 0, "threshold": 0., "operator": "<",
                               "missing_left": True, "left": {"leaf": -2.},
                               "right": {"leaf": -3.}}]
        elif funded and head["task"] == "quantile":
            model["trees"] = [{"leaf": -.005}]
        head["content"] = canonical_json(model)
        head["sha256"] = hashlib.sha256(head["content"].encode()).hexdigest()
    bundle = ModelBundle.create(**data)
    policy = {"approved_models": [], "approved_bundles": [fixture_pin(bundle)]}
    # Only the synthetic model/selection configuration is supplied. Do not
    # replace universe, receipt loading, feature calculation or prediction.
    monkeypatch.setattr(models, "policy", lambda: policy)
    monkeypatch.setattr(models, "bundled_selection", lambda: selection)
    monkeypatch.setattr(forecasts, "bundled_selection", lambda: selection)
    models.import_bundle(path, encoded(bundle), cutoff - timedelta(minutes=10))
    return device, path, store, cutoff, now, selection, policy


@pytest.mark.parametrize("funded", [False, True])
def test_received_history_to_forecast_manual_review_and_restore_without_feature_doubles(
    tmp_path, monkeypatch, funded,
):
    """Synthetic integration; real source/feature/inference code, no model adoption."""
    from mobile.python import decisions, manual_chatgpt
    from scripts.sqlite_evidence import table_snapshot

    from stock_ai.operations.chatgpt_manual import ExternalAiPermission

    device, path, store, cutoff, now, _, _ = received_history_ready(
        tmp_path, monkeypatch, funded=funded,
    )

    ledger = store.latest_portfolio()
    numerical = forecasts.generate(path, store, now)
    assert numerical["phase"] == "published", numerical["blocking_reasons"]
    snapshot = store.latest_prediction_snapshot()
    assert len(snapshot.predictions) == len(snapshot.candidate_symbols) == 24
    assert snapshot.holding_symbols == ("1023",)
    assert snapshot.mode == "research" and snapshot.adoption_review_id is None
    assert not models.status(path, store)["model_adopted"]
    assert len(numerical["data_proof"]["source_snapshot_ids"]) == 5
    assert numerical["scope"]["universe"]["membership_verified"]
    assert snapshot.data_as_of < snapshot.as_of == cutoff
    inputs = market.feature_inputs(path, now, True)
    daily = inputs["daily"].sort_values(["symbol", "trading_date"])
    # Independent raw-price arithmetic checks the feature actually consumed
    # by the risk tree, rather than comparing one inference call with itself.
    expected = {}
    for symbol, frame in daily.groupby("symbol"):
        prices = frame.close.to_numpy()
        five_day_return = prices[-1] / prices[-6] - 1
        expected[symbol] = 1 / (1 + math.exp(2 if five_day_return < 0 else 3))
    assert len(set(expected.values())) == 2
    for prediction in snapshot.predictions:
        assert prediction.expected_return_5d == .01 and prediction.expected_return_20d == .04
        assert prediction.large_loss_probability == pytest.approx(expected[prediction.symbol])
    assert forecasts.generate(path, store, now + timedelta(seconds=1)) == numerical

    comparison = decisions.generate(path, store, now)
    assert comparison["phase"] == "published", comparison["blocking_reasons"]
    if funded:
        proposal = comparison["comparison"]["proposal"]
        assert any(x["share_difference"] and sum(float(x["transaction_cost"][field]) for field in
                   ("commission", "spread", "slippage", "market_impact")) > 0
                   for x in proposal["lines"])
    permission = ExternalAiPermission(
        service="manual_chatgpt", checked_at=now, personal_analysis_only=True,
        training_disabled=True, private_input=True, private_output=True,
        data_entitlement_confirmed=True,
    )
    exported = manual_chatgpt.export(path, store, permission.model_dump(mode="json"), now)
    package = json.loads(exported["prompt"].split("\n入力:\n")[1])
    targets = package["required_targets"]
    assert len(targets) == 21 and any(x["symbol"] == "1023" for x in targets)
    answer = dict(schema_version="chatgpt-target-shares-v1",
                  input_snapshot_id=package["input_snapshot_id"], evidence_as_of=now.isoformat(),
                  targets=[dict(symbol=x["symbol"], account=x["account"],
                                target_shares=(next(p["recommended_shares"] for p in
                                              comparison["comparison"]["proposal"]["lines"]
                                              if p["symbol"] == x["symbol"])
                                               if funded else x["current_shares"]),
                                reason="合成試験の目標株数検証",
                                sources=[]) for x in targets], unknowns=["合成データのみ"])
    original = json.dumps(answer, ensure_ascii=False)
    reply = manual_chatgpt.import_answer(path, store, {
        "input_record_id": exported["input_record_id"], "answer_json": original,
    }, now)
    assert not reply["review"]["applied_to_ledger"]
    if funded:
        assert float(reply["review"]["estimated_cost_yen"]) > 0
        assert any(x["share_difference"] for x in reply["review"]["lines"])
    assert store.latest_portfolio() == ledger and store.latest_prediction_snapshot() == snapshot
    assert not store.executions()
    store.verify_integrity()
    reference = {name: table_snapshot(device.STATE / name)
                 for name in ("operations.sqlite3", "mobile.sqlite3")}
    # Export initializes only the existing compaction cursor. All source rows
    # already use the current codec; authorize exactly (1,0,0), not arbitrary
    # table changes or a reference taken after a potentially destructive export.
    cursor = reference["mobile.sqlite3"]["tables"]["market_compaction"]
    assert cursor == {"rows": 0, "typed_cells_sha256": hashlib.sha256(b"").hexdigest()}
    typed_row = b"R" + b"".join(b"I" + struct.pack(">Q", 1) + x for x in (b"1", b"0", b"0"))
    cursor.update(rows=1, typed_cells_sha256=hashlib.sha256(typed_row).hexdigest())
    capsule = device.export_state()
    assert reference == {name: table_snapshot(device.STATE / name) for name in reference}
    device.initialize(capsule)
    restored = device._app.state.store
    assert reference == {name: table_snapshot(device.STATE / name) for name in reference}
    assert forecasts.latest(path) == numerical and decisions.latest(path) == comparison
    assert restored.latest_portfolio() == ledger
    assert restored.latest_prediction_snapshot() == snapshot
    assert manual_chatgpt.status(path, restored, now)["selected_input"] == (
        exported["input_record_id"]
    )
    assert manual_chatgpt.import_answer(path, restored, {
        "input_record_id": exported["input_record_id"], "answer_json": original,
    }, now + timedelta(seconds=1)) == reply


def test_reference_after_registration_uses_actual_time_and_never_selects_daily(ready, monkeypatch):
    device, store, path, selected, features, _ = ready
    original = forecasts.generate(path, store, NOW)
    active = store.latest_prediction_snapshot()
    manual = store.latest_manual_portfolio()
    personal.save_portfolio(store, manual.portfolio, manual.export.revision_id, NOW)
    reference_time = NOW + timedelta(minutes=1)
    selected["as_of"] = reference_time.isoformat()
    features["as_of"] = reference_time.isoformat()
    for rows in features["features"].values():
        for row in rows:
            row["available_at"] = reference_time.isoformat()
    def reference_inputs(*args, **kwargs):
        assert kwargs["reference_only"] is True
        return {"as_of": reference_time.isoformat(), "latest_source_received_at": NOW.isoformat(),
                "reference_price_date": selected["latest_source_date"],
                "source_snapshot_ids": [(name.value, "4" * 64) for name in market.DatasetName],
                "revision_policy": "synthetic-fixture-conservative"}
    monkeypatch.setattr(forecasts.market, "feature_inputs", reference_inputs)
    value = forecasts.generate(path, store, reference_time, reference_only=True)
    assert value["phase"] == "reference_saved"
    assert value["scope"]["as_of"] == reference_time.isoformat()
    assert value["snapshot"]["data_as_of"] == NOW.isoformat()
    assert forecasts.latest(path) == original
    assert store.prediction_snapshot(active.snapshot_id) == active
    with pytest.raises(ValueError, match="cannot become an active"):
        forecasts._publish(path, store, value)
    assert forecasts.reference_view(path, reference_time)["readOnly"] is True
    assert forecasts.reference_view(path, NOW) is None
    archive = device.export_state()
    device.initialize(archive)
    assert forecasts.latest_reference(path, reference_time) == value
    assert forecasts.reference_view(path, reference_time)["analysisKind"] == (
        "latest_available_reference")
    daily = forecasts.generate(path, device._app.state.store, reference_time)
    assert daily["blocking_reasons"] == ["PERSONAL_INPUT_AFTER_ALPHA_CUTOFF"]
    # A new blocked reference attempt must preserve the last completed reference.
    later = reference_time + timedelta(seconds=1)
    selected["blocking_reasons"] = ["price_session_missing"]
    blocked = forecasts.generate(path, device._app.state.store, later, reference_only=True)
    assert blocked["snapshot"] is None
    assert forecasts.reference_view(path, later)["snapshotId"] == value["snapshot"]["snapshot_id"]


def test_reference_received_history_without_feature_doubles(tmp_path, monkeypatch):
    _device, path, store, _cutoff, now, _, _ = received_history_ready(tmp_path, monkeypatch)
    now += timedelta(hours=7)
    manual = store.latest_manual_portfolio()
    personal.save_portfolio(store, manual.portfolio, manual.export.revision_id, now)
    now += timedelta(seconds=1)
    result = forecasts.generate(path, store, now, reference_only=True)
    assert result["phase"] == "reference_saved", result["blocking_reasons"]
    assert result["scope"]["as_of"] == now.isoformat()
    assert result["scope"]["universe"]["latest_source_date"] < now.date().isoformat()
    assert result["snapshot"]["predictions"]
    assert forecasts.latest(path) is None
    assert store.latest_prediction_snapshot() is None
    assert store.latest_archived_prediction(now) is None
    view = forecasts.reference_view(path, now)
    assert view["priceDate"] == result["scope"]["universe"]["latest_source_date"]
