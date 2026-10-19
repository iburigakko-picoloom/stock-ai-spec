from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from mobile.python import (
    decision_market,
    decisions,
    forecasts,
    market,
    membership,
    models,
    personal,
)
from mobile.python.model_bundle import ModelBundle, encoded

from stock_ai.data.contracts import DatasetName
from stock_ai.data.production import _source_frame_id
from stock_ai.domain import UserDecision, UserDecisionLine
from stock_ai.operations.api import create_app
from stock_ai.operations.daily import canonical_json, content_id
from stock_ai.operations.manual_portfolio import ManualPortfolio
from stock_ai.operations.models import PipelineState
from stock_ai.operations.store import OperationalConflictError, OperationalIntegrityError
from tests.test_mobile_bundles import CUTOFF, SELECTION, fixture_bundle, fixture_pin
from tests.test_mobile_personal import profile, settings
from tests.test_mobile_runtime import device as device_fixture
from tests.test_mobile_universe import daily

NOW = CUTOFF + timedelta(minutes=20)
SETUP = datetime.fromisoformat("2026-02-02T10:00:00Z")
RECEIVED = "2026-02-02T09:00:00Z"


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    device = device_fixture.__wrapped__(tmp_path, monkeypatch)
    path, store = device.STATE / "mobile.sqlite3", device._app.state.store
    days = [CUTOFF.date() - timedelta(days=i) for i in range(28, 0, -1)]
    days = [day for day in days if day.weekday() < 5]
    assert len(days) == 20
    for day in days:
        payload = daily(day, 2)
        payload["received_at"] = RECEIVED
        for name in ("security_master", "daily_prices"):
            held = copy.deepcopy(payload["datasets"][name][0])
            held["Code"] = "72030"
            payload["datasets"][name].append(held)
        for price in payload["datasets"]["daily_prices"]:
            price.update(O=1000, H=1001, L=999, C=1000, AdjO=1000,
                         AdjH=1001, AdjL=999, AdjC=1000, Va=10000000)
        market.ingest(path, payload)
    value = profile(held=True).model_dump(mode="json")
    value["investment_budget_yen"] = "300000"
    value["accounts"][0]["available_cash_yen"] = "1000000"
    value["holdings"][0].update(shares=137, average_acquisition_price_yen="900")
    saved = personal.save_portfolio(store, ManualPortfolio.model_validate(value), None, SETUP)
    extra = settings(saved["revision_id"]).model_copy(update={
        "research_decision_policy": "daily-decision-engine-v3-bounded",
    })
    personal.save_settings(store, extra, None, SETUP)
    preview = personal.preview_initial(store, path, SETUP, persist=True)
    assert not preview["blocking_reasons"]
    personal.confirm_initial(store, path, preview["preview_id"], True, SETUP)
    member_payload = daily(CUTOFF.date(), 2)
    datasets = {name: member_payload["datasets"][name]
                for name in ("security_master", "trading_calendar")}
    member = {"purpose": "membership", "status": 200, "date": str(CUTOFF.date()),
              "acquisitionId": "11111111-1111-4111-8111-111111111111",
              "received_at": "2026-02-03T02:00:00Z", "datasets": datasets,
              "source_pages": [{"dataset": name, "page": 0, "row_count": len(rows),
                                "received_at": "2026-02-03T02:00:00Z", "sha256": "0" * 64}
                               for name, rows in datasets.items()]}
    membership.ingest(path, member, CUTOFF)
    bundle_data = fixture_bundle().model_dump(mode="json", exclude={"bundle_id"})
    bundle_data["calibration"]["residual_rmse"] = .002
    for head in bundle_data["heads"]:
        model = json.loads(head["content"])
        if head["task"] == "quantile":
            model["trees"] = [{"leaf": -.005}]
        elif head["task"] == "regression" and head["horizon"] == 20:
            model["trees"] = [{"feature": 0, "threshold": 0, "operator": "<",
                               "missing_left": True, "left": {"leaf": -.04},
                               "right": {"leaf": .04}}]
        head["content"] = canonical_json(model)
        head["sha256"] = hashlib.sha256(head["content"].encode()).hexdigest()
    bundle = ModelBundle.create(**bundle_data)
    policy = {"approved_models": [], "approved_bundles": [fixture_pin(bundle)]}
    monkeypatch.setattr(models, "policy", lambda: policy)
    monkeypatch.setattr(models, "bundled_selection", lambda: SELECTION)
    monkeypatch.setattr(forecasts, "bundled_selection", lambda: SELECTION)
    models.import_bundle(path, encoded(bundle), SETUP)
    master = market.SQLiteSource(path).point_in_time(DatasetName.SECURITY_MASTER, CUTOFF)
    source_ids = [(name.value, _source_frame_id(name, master) if name is DatasetName.SECURITY_MASTER
                   else "4" * 64) for name in DatasetName]
    def selected_inputs(*args, decision_symbols):
        assert "7203" in decision_symbols
        return {"as_of": CUTOFF.isoformat(), "latest_source_received_at": RECEIVED,
                "source_snapshot_ids": source_ids, "revision_policy": "synthetic-test-only"}
    monkeypatch.setattr(forecasts.market, "feature_inputs", selected_inputs)
    monkeypatch.setattr(forecasts, "calculate", lambda *args: {
        "as_of": CUTOFF.isoformat(), "features": {str(horizon): [
            {"symbol": symbol, "available_at": CUTOFF.isoformat(), "f1": factor}
            for symbol, factor in (("1000", 1), ("1001", 1), ("7203", -1))
        ] for horizon in (5, 20)},
    })
    numerical = forecasts.generate(path, store, NOW)
    assert numerical["phase"] == "published"
    return device, path, store, numerical, policy


def test_frozen_market_uses_original_prices_receipts_and_held_metadata(ready):
    _, path, _, numerical, _ = ready
    result = decision_market.prepare(path, numerical)
    assert result["proof"]["reference_price_date"] == "2026-02-02"
    assert result["proof"]["historical_metadata_symbols"] == ["7203"]
    assert result["evidence"]["market"]["prices"] == dict.fromkeys(("1000", "1001", "7203"), "1000")
    assert result["evidence"]["observed_at"] == "2026-02-03T02:00:00Z"
    assert dict(result["evidence"]["average_daily_trading_values"])["7203"] == "10000000"
    corrected = daily(CUTOFF.date() - timedelta(days=1), 2)
    corrected["received_at"] = "2026-02-03T02:31:00Z"
    market.ingest(path, corrected)
    assert decision_market.prepare(path, numerical) == result
    # Even a newly stored correction with a pre-cutoff receipt cannot replace
    # the exact original metadata observations of this already frozen forecast.
    corrected["received_at"] = "2026-02-03T02:01:00Z"
    market.ingest(path, corrected)
    assert decision_market.prepare(path, numerical) == result


@pytest.mark.parametrize("dataset", ["daily_prices", "security_master"])
def test_invalid_frozen_market_blob_blocks_without_archive_or_fallback(ready, dataset):
    _, path, store, _, _ = ready
    with sqlite3.connect(path) as db:
        db.execute("UPDATE market_batches SET raw=? WHERE dataset=?", (b"invalid", dataset))
    result = decisions.generate(path, store, NOW)
    assert result["blocking_reasons"] == ["FROZEN_MARKET_SOURCE_INVALID"]
    assert result["phase"] == "blocked" and result["comparison"] is None
    assert store.latest_proposal(CUTOFF.date()) is None


def test_numerical_to_archived_personal_quantities_preserves_balances_and_forecast(ready):
    device, path, store, numerical, _ = ready
    ledger, snapshot = store.latest_portfolio(), store.latest_prediction_snapshot()
    result = decisions.generate(path, store, NOW)
    assert result["phase"] == "published" and result["outcome"] == "proposal"
    proposal = store.proposal(result["comparison"]["proposal"]["proposal_id"])
    assert proposal.is_research_only and not proposal.is_order_instruction
    assert {line.symbol: line.recommended_shares for line in proposal.lines} == {
        "1000": 100, "1001": 100, "7203": 37,
    }
    assert next(x for x in proposal.lines if x.symbol == "7203").estimated_tax_effect == Decimal(
        2000
    )
    assert store.latest_portfolio() == ledger and store.latest_prediction_snapshot() == snapshot
    app = create_app(store.path, clock=lambda: NOW)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/v1/today")
        assert response.status_code == 200, response.text
        today = response.json()
        assert today["proposal"]["proposalId"] == proposal.proposal_id
        assert today["proposal"]["isResearchOnly"]
        assert not today["isStale"]
    device.initialize(device.export_state())
    assert decisions.latest(path) == result
    assert device._app.state.store.proposal(proposal.proposal_id) == proposal
    assert numerical["snapshot"] == snapshot.model_dump(mode="json")


def test_same_scope_never_recomputes_or_retimes_a_saved_share_proposal(ready, monkeypatch):
    _, path, store, _, _ = ready
    first = decisions.generate(path, store, NOW)
    monkeypatch.setattr(decisions, "compare_stored_personal",
                        lambda *a, **k: pytest.fail("recomputed"))
    assert decisions.generate(path, store, NOW + timedelta(minutes=1)) == first


def test_publication_rechecks_settings_inside_the_archive_transaction(ready, monkeypatch):
    _, path, store, _, _ = ready
    original = store.archive_proposal
    saved = personal.read_settings(store)
    def change_then_archive(*args, **kwargs):
        extra = personal.ManualPersonalSettings.model_validate(saved["settings"])
        personal.save_settings(store, extra, saved["revision_id"], NOW)
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "archive_proposal", change_then_archive)
    with pytest.raises(OperationalConflictError, match="inputs changed"):
        decisions.generate(path, store, NOW)
    assert decisions.latest(path)["phase"] == "computed"
    assert store.latest_proposal(CUTOFF.date()) is None


@pytest.mark.parametrize("after_archive", [False, True])
def test_interrupted_publication_restores_original_receipt_without_recomputing(
    ready, monkeypatch, after_archive,
):
    device, path, store, _, _ = ready
    original = store.archive_proposal
    def interrupt(*args, **kwargs):
        if after_archive:
            original(*args, **kwargs)
        raise RuntimeError("synthetic interruption")
    monkeypatch.setattr(store, "archive_proposal", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        decisions.generate(path, store, NOW)
    first = decisions.latest(path)
    assert first["phase"] == "computed"
    assert (store.latest_proposal(CUTOFF.date()) is not None) == after_archive
    device.initialize(device.export_state())
    store = device._app.state.store
    assert decisions.latest(path)["phase"] == ("published" if after_archive else "computed")
    monkeypatch.setattr(decisions, "compare_stored_personal",
                        lambda *a, **k: pytest.fail("recomputed after interruption"))
    result = decisions.generate(path, store, NOW + timedelta(minutes=1))
    assert result == {**first, "phase": "published"}
    assert store.daily_status(CUTOFF.date()).updated_at == NOW


def test_block_then_reselect_cached_result_preserves_saved_user_progress(ready, monkeypatch):
    _, path, store, numerical, policy = ready
    first = decisions.generate(path, store, NOW)
    status = store.daily_status(CUTOFF.date())
    proposal = store.proposal(status.proposal_id)
    decision = UserDecision(
        decision_id="synthetic-manual-decision", proposal_id=proposal.proposal_id, version=1,
        saved_at=NOW + timedelta(seconds=1), confirms_manual_order_only=True,
        lines=tuple(UserDecisionLine(proposal_line_id=line.line_id,
                                    selected_target_shares=line.recommended_shares)
                    for line in proposal.lines),
    )
    store.save_decision(decision)
    progressed = status.model_copy(update={"pipeline_state": PipelineState.USER_DECISION_SAVED})
    store.set_daily_status(progressed)
    assert decisions.generate(path, store, NOW + timedelta(seconds=1)) == first
    assert store.daily_status(CUTOFF.date()) == progressed
    pins = policy["approved_bundles"]
    policy["approved_bundles"] = []
    assert forecasts.generate(path, store, NOW + timedelta(minutes=1))["outcome"] == "blocked"
    blocked = decisions.generate(path, store, NOW + timedelta(minutes=1))
    assert blocked["outcome"] == "blocked" and not decisions.view(path, store)["is_active"]
    assert store.latest_prediction_snapshot() is None
    policy["approved_bundles"] = pins
    assert forecasts.generate(path, store, NOW + timedelta(minutes=2)) == numerical
    monkeypatch.setattr(decisions, "compare_stored_personal",
                        lambda *a, **k: pytest.fail("recomputed"))
    assert decisions.generate(path, store, NOW + timedelta(minutes=2)) == first
    assert decisions.view(path, store)["is_active"]
    assert store.daily_status(CUTOFF.date()).proposal_id == status.proposal_id
    assert store.daily_status(CUTOFF.date()).pipeline_state is PipelineState.USER_DECISION_SAVED
    assert store.latest_decision(proposal.proposal_id) == decision
    assert store.proposal(status.proposal_id).generated_at == NOW


def test_changed_settings_hide_old_proposal_and_reject_direct_review(ready):
    _, path, store, _, _ = ready
    result = decisions.generate(path, store, NOW)
    proposal_id = result["comparison"]["proposal"]["proposal_id"]
    saved = personal.read_settings(store)
    personal.save_settings(store, personal.ManualPersonalSettings.model_validate(saved["settings"]),
                           saved["revision_id"], NOW + timedelta(minutes=1))
    assert not decisions.view(path, store)["is_active"]
    app = create_app(store.path, clock=lambda: NOW)
    with TestClient(app, base_url="http://localhost") as client:
        today = client.get("/api/v1/today").json()
        assert today["proposal"] is None and today["isStale"]
        assert client.get("/api/v1/proposals/" + proposal_id).status_code == 409


def cash_ready(ready):
    device, path, store, _, _ = ready
    manual = store.latest_manual_portfolio()
    instant = SETUP + timedelta(minutes=1)
    saved = personal.save_portfolio(store, manual.portfolio.model_copy(update={
        "holdings": (), "holdings_status": "none",
    }), manual.export.revision_id, instant)
    prior_settings = personal.read_settings(store)
    personal.save_settings(store, settings(saved["revision_id"]).model_copy(update={
        "research_decision_policy": "daily-decision-engine-v3-bounded",
    }), prior_settings["revision_id"], instant)
    ledger = store.latest_portfolio().model_copy(update={
        "portfolio_id": "synthetic-cash-only", "positions": (), "as_of": instant,
    })
    store.append_portfolio(ledger, created_at=instant)
    latest_day = CUTOFF.date() - timedelta(days=1)
    correction = daily(latest_day, 2)
    correction["received_at"] = "2026-02-03T02:01:00Z"
    for value in correction["valuations"]:
        value["MktCap"] = 1
    market.ingest(path, correction)
    numeric = forecasts.generate(path, store, NOW)
    assert numeric["outcome"] == "cash_only" and numeric["snapshot"] is None
    return device, path, store, ledger


def test_cash_only_is_complete_without_dummy_forecast_proposal_or_ledger_change(ready, monkeypatch):
    device, path, store, ledger = cash_ready(ready)
    monkeypatch.setattr(decisions, "compare_stored_personal",
                        lambda *a, **k: pytest.fail("cash scored"))
    first = decisions.generate(path, store, NOW)
    assert first["outcome"] == "cash_only" and first["phase"] == "published"
    assert first["comparison"] is None and first["frozen_inputs"]["forecast"] is None
    assert decisions.view(path, store)["is_active"]
    assert store.latest_proposal(CUTOFF.date()) is None
    assert store.latest_prediction_snapshot() is None
    assert store.latest_portfolio() == ledger
    app = create_app(store.path, clock=lambda: NOW)
    with TestClient(app, base_url="http://localhost") as client:
        today = client.get("/api/v1/today").json()
        assert today["pipelineState"] == "CASH_ONLY" and not today["isStale"]
        assert today["proposal"] is None
    device.initialize(device.export_state())
    store = device._app.state.store
    assert decisions.generate(path, store, NOW + timedelta(minutes=1)) == first
    assert store.daily_status(CUTOFF.date()).updated_at == NOW
    assert store.latest_portfolio() == ledger


@pytest.mark.parametrize("key,payload", [
    ("mobile-numerical-active", '{"snapshot_id":null}'),
    ("mobile-cash-receipt:" + "a" * 64, '{"receipt_id":"wrong"}'),
    ("mobile-cash-active:2026-02-03", "a" * 64),
])
def test_malformed_publication_references_fail_integrity_verification(ready, key, payload):
    _, _, store, _, _ = ready
    store.set_metadata(key, payload)
    with pytest.raises(OperationalIntegrityError):
        store.verify_integrity()


def test_rehashed_publication_status_cannot_disagree_with_original_proposal(ready):
    _, path, store, _, _ = ready
    decisions.generate(path, store, NOW)
    with sqlite3.connect(path) as db:
        identity, payload = db.execute("SELECT run_id,payload FROM mobile_decision_runs").fetchone()
        value = json.loads(payload)
        value["publication_status"]["proposal_id"] = "wrong"
        value["run_id"] = content_id({k: v for k, v in value.items() if k != "run_id"})
        db.execute("UPDATE mobile_decision_runs SET run_id=?,payload=?,content_hash=? "
                   "WHERE run_id=?",
                   (value["run_id"], canonical_json(value), content_id(value), identity))
        db.execute("UPDATE mobile_decision_selections SET run_id=? WHERE run_id=?",
                   (value["run_id"], identity))
    with pytest.raises(ValueError, match="publication identity changed"):
        decisions.latest(path, store)
