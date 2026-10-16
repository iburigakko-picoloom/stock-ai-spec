from __future__ import annotations

import copy
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from mobile.python import market, personal, runtime

from stock_ai.operations.manual_portfolio import ManualPortfolio
from stock_ai.operations.manual_settings import ManualPersonalSettings
from stock_ai.operations.store import OperationalConflictError, OperationalIntegrityError
from tests.test_mobile_market import payload as market_payload
from tests.test_mobile_runtime import run

NOW = datetime(2026, 1, 6, 10, tzinfo=UTC)
ACCOUNT = "11111111-1111-4111-8111-111111111111"
EMPTY = {
    "schema_version": "manual-portfolio-v1", "holdings_status": "none",
    "investment_budget_yen": None, "maximum_drawdown_percent": None,
    "accounts": [], "holdings": [],
}


@pytest.fixture()
def device(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "STATE", tmp_path / "state")
    runtime.initialize()
    return runtime


def profile(*, held=False, nisa=False):
    return ManualPortfolio.model_validate({
        **EMPTY, "investment_budget_yen": "200000", "maximum_drawdown_percent": 20.0,
        "holdings_status": "recorded" if held else "none",
        "accounts": [{"id": ACCOUNT, "name": "Synthetic test only",
                      "account_type": "nisa" if nisa else "taxable_specified",
                      "withholding_mode": "not_applicable" if nisa else "withholding",
                      "available_cash_yen": "1000.0001"}],
        "holdings": [{"account_id": ACCOUNT, "symbol": "7203", "shares": 37,
                      "average_acquisition_price_yen": "0.9"}] if held else [],
    })


def settings(revision, *, complete=True, nisa=False):
    value = {
        "schema_version": "manual-personal-settings-v1", "portfolio_revision_id": revision,
        "cash_basis": "total_including_reserved" if complete else None,
        "budget_basis": "maximum_total_equity_market_value" if complete else None,
        "nisa_capacity_basis": "remaining_purchase_notional_no_same_day_sale_restore",
        "tax_year": 2026 if complete else None,
        "accounts": [{"account_id": ACCOUNT, "reserved_cash_yen": "100" if complete else None,
                      "pending_activity": "none" if complete else "unknown",
                      "realized_gain_ytd": "0" if complete else None,
                      "realized_loss_ytd": "0" if complete else None,
                      "loss_carryforward_user_input": "0" if complete else None,
                      "nisa_annual_capacity_user_input": "123" if nisa and complete else None,
                      "nisa_lifetime_capacity_user_input": "456" if nisa and complete else None}],
        "cost_assumptions": {"commission_fixed_yen": "0" if complete else None,
                             "commission_bps": "0" if complete else None,
                             "minimum_commission_yen": "0" if complete else None,
                             "zero_commission_confirmed": complete,
                             "full_spread_bps": "10" if complete else None,
                             "slippage_bps": "5" if complete else None,
                             "impact_bps_at_full_adv": "25" if complete else None},
        "tax_assumptions": {"effective_from": "2026-01-01" if complete else None,
                            "taxable_rate_percent": "20" if complete else None,
                            "nisa_opportunity_cost_percent": "0" if complete else None},
        "research_decision_policy": "daily-decision-engine-v2",
        "research_conditions_reviewed": complete,
    }
    return ManualPersonalSettings.model_validate(value)


def setup(device, *, held=False, nisa=False, complete=True):
    store = device._app.state.store
    saved = personal.save_portfolio(store, profile(held=held, nisa=nisa), None, NOW)
    extra = settings(saved["revision_id"], complete=complete, nisa=nisa)
    personal.save_settings(store, extra, None, NOW)
    return store, extra


def test_explicit_bounded_policy_compiles_without_changing_legacy_cost_tax_or_ledger(device):
    store, old = setup(device)
    legacy = personal.input_state(store, NOW)[3]
    assert legacy.decision_policy.version == "daily-decision-engine-v2"
    before_ledger = store.latest_portfolio()
    before_saved = personal.read_settings(store)
    selected = old.model_copy(update={
        "research_decision_policy": "daily-decision-engine-v3-bounded",
    })
    personal.save_settings(store, selected, before_saved["revision_id"], NOW + timedelta(minutes=1))
    compiled = personal.input_state(store, NOW + timedelta(minutes=1))[3]
    assert compiled.decision_policy.version == "daily-decision-engine-v3-bounded"
    assert compiled.cost_policy == legacy.cost_policy and compiled.tax_policy == legacy.tax_policy
    assert store.latest_portfolio() == before_ledger
    device.initialize(device.export_state())
    restored = personal.input_state(device._app.state.store, NOW + timedelta(minutes=1))[3]
    assert restored == compiled


def preview(device, store):
    return personal.preview_initial(store, device.STATE / "mobile.sqlite3", NOW, persist=True)


def test_legacy_saved_input_migrates_without_changing_payload_or_creating_ledger(device):
    path = device.STATE / "mobile.sqlite3"
    original = json.dumps(EMPTY)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO manual_inputs(saved_at,payload) VALUES(?,?)",
                   (NOW.isoformat(), original))
    device.initialize(device.export_state())
    store = device._app.state.store
    migrated = personal.portfolio_view(store)
    assert migrated["portfolio"] == EMPTY
    assert store.latest_manual_portfolio().portfolio.model_dump(mode="json") == EMPTY
    assert store.latest_portfolio() is None
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT payload FROM manual_inputs").fetchone()[0] == original
    device.initialize(device.export_state())
    assert personal.portfolio_view(device._app.state.store) == migrated


def test_portfolio_revisions_reject_stale_and_raw_overwrite(device):
    first = run(device, "POST", "/api/v1/mobile/portfolio", EMPTY)["body"]
    assert first["revision_id"]
    assert run(device, "POST", "/api/v1/mobile/portfolio", EMPTY)["status"] == 409
    second = run(device, "POST", "/api/v1/mobile/portfolio", {
        "expected_revision_id": first["revision_id"], "portfolio": EMPTY,
    })
    assert second["status"] == 200
    assert second["body"]["revision_id"] != first["revision_id"]
    assert run(device, "POST", "/api/v1/mobile/portfolio", {
        "expected_revision_id": first["revision_id"], "portfolio": EMPTY,
    })["status"] == 409


def test_incomplete_settings_keep_unknowns_and_never_initialize(device):
    store, _ = setup(device, complete=False)
    saved = personal.read_settings(store)
    assert saved["settings"]["accounts"][0]["realized_gain_ytd"] is None
    ready = personal.readiness(store, device.STATE / "mobile.sqlite3", NOW)
    assert {"cash_basis", "realized_tax_state", "cost_assumptions"} <= set(ready["input_gaps"])
    result = preview(device, store)
    assert result["portfolio"] is None
    with pytest.raises(ValueError):
        personal.confirm_initial(store, device.STATE / "mobile.sqlite3",
                                 result["preview_id"], True, NOW)
    assert store.latest_portfolio() is None
    assert ready["comparison"]["manual_revision_id"] == saved["settings"]["portfolio_revision_id"]
    assert ready["comparison"]["proposal"] is None


def test_settings_conflict_and_changed_portfolio_are_rejected(device):
    store, extra = setup(device)
    with pytest.raises(OperationalConflictError):
        personal.save_settings(store, extra, None, NOW)
    previous = personal.portfolio_view(store)
    personal.save_portfolio(store, profile(), previous["revision_id"], NOW)
    with pytest.raises(ValueError):
        personal.save_settings(store, extra, personal.read_settings(store)["revision_id"], NOW)
    assert "settings_outdated" in personal.readiness(
        store, device.STATE / "mobile.sqlite3", NOW
    )["input_gaps"]


@pytest.mark.parametrize("cash_basis,expected", [
    ("total_including_reserved", Decimal("1000.0001")),
    ("deployable_after_reserved", Decimal("1100.0001")),
])
def test_reviewed_initial_cash_is_exact_atomic_once_only_and_shared_with_home(
    device, cash_basis, expected
):
    store, extra = setup(device)
    old = personal.read_settings(store)
    changed = ManualPersonalSettings.model_validate({
        **extra.model_dump(), "cash_basis": cash_basis,
    })
    personal.save_settings(store, changed, old["revision_id"], NOW)
    value = preview(device, store)
    assert value["blocking_reasons"] == []
    assert store.latest_portfolio() is None
    with pytest.raises(ValueError):
        personal.confirm_initial(store, device.STATE / "mobile.sqlite3", value["preview_id"], False,
                                 NOW)
    reply = personal.confirm_initial(store, device.STATE / "mobile.sqlite3", value["preview_id"],
                                     True, NOW)
    ledger = store.latest_portfolio()
    assert ledger.portfolio_id == reply["portfolio_id"]
    assert ledger.cash[0].available_cash == expected
    assert ledger.cash[0].reserved_cash == Decimal(100)
    assert ledger.tax_states[0].realized_gain_ytd == 0
    assert ledger.applied_execution_ids == ()
    store.verify_integrity()
    assert run(device, "GET", "/api/v1/home")["body"]["portfolio"]["cashValue"] == str(expected)
    again = personal.confirm_initial(store, device.STATE / "mobile.sqlite3", value["preview_id"],
                                     True, NOW)
    assert again["already_confirmed"] is True
    assert "ledger_already_initialized" in preview(device, store)["blocking_reasons"]
    before = ledger.model_dump_json()
    p = personal.portfolio_view(store)
    personal.save_portfolio(store, profile().model_copy(update={"investment_budget_yen": "1"}),
                            p["revision_id"], NOW)
    assert store.latest_portfolio().model_dump_json() == before
    assert store.executions() == ()


def test_nisa_capacity_and_odd_lot_holdings_are_preserved_with_stored_source_prices(device):
    store, extra = setup(device, held=True, nisa=True)
    path = device.STATE / "mobile.sqlite3"
    market.ingest(path, market_payload())
    value = preview(device, store)
    assert value["blocking_reasons"] == []
    assert value["prices"]["date"] == "2026-01-05"
    assert value["portfolio"]["positions"][0]["shares"] == 37
    assert Decimal(value["portfolio"]["positions"][0]["market_price"]) == Decimal(1)
    personal.confirm_initial(store, path, value["preview_id"], True, NOW)
    assert store.latest_portfolio().tax_states[0].nisa_annual_capacity_user_input == Decimal(123)
    compiled = extra.compile(extra.portfolio_revision_id, profile(held=True, nisa=True))
    assert compiled.tax_policy.taxable_rate == Decimal("0.2")


def test_missing_stale_or_special_code_price_blocks_without_using_acquisition_price(device):
    store, _ = setup(device, held=True)
    assert "held_prices_missing" in preview(device, store)["blocking_reasons"]
    source = market_payload()
    source["datasets"]["daily_prices"][0]["Code"] = "72031"
    market.ingest(device.STATE / "mobile.sqlite3", source)
    assert "held_prices_missing" in preview(device, store)["blocking_reasons"]
    market.ingest(device.STATE / "mobile.sqlite3", market_payload())
    late = personal.preview_initial(store, device.STATE / "mobile.sqlite3",
                                    NOW + timedelta(days=6), persist=False)
    assert "held_prices_stale" in late["blocking_reasons"]


def test_changed_input_or_settings_invalidates_preview(device):
    store, extra = setup(device)
    initial = preview(device, store)
    personal.save_settings(store, extra, personal.read_settings(store)["revision_id"], NOW)
    with pytest.raises(OperationalConflictError):
        personal.confirm_initial(store, device.STATE / "mobile.sqlite3", initial["preview_id"],
                                 True, NOW)
    assert store.latest_portfolio() is None


def test_later_price_correction_invalidates_preview_without_ledger_write(device):
    store, _ = setup(device, held=True)
    market.ingest(device.STATE / "mobile.sqlite3", market_payload())
    initial = preview(device, store)
    correction = market_payload()
    correction["received_at"] = (NOW + timedelta(seconds=1)).isoformat()
    correction["datasets"]["daily_prices"][0].update(C=1.5, AdjC=1.5)
    market.ingest(device.STATE / "mobile.sqlite3", correction)
    with pytest.raises(OperationalConflictError):
        personal.confirm_initial(store, device.STATE / "mobile.sqlite3", initial["preview_id"],
                                 True, NOW + timedelta(seconds=2))
    assert store.latest_portfolio() is None


def test_initial_confirmation_expires_and_transaction_rolls_back_on_receipt_failure(device):
    store, _ = setup(device)
    initial = preview(device, store)
    with pytest.raises(OperationalConflictError):
        personal.confirm_initial(store, device.STATE / "mobile.sqlite3", initial["preview_id"],
                                 True, NOW + timedelta(minutes=16))
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_confirmation BEFORE INSERT ON mobile_initial_confirmations "
                   "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        personal.confirm_initial(store, device.STATE / "mobile.sqlite3", initial["preview_id"],
                                 True, NOW)
    assert store.latest_portfolio() is None
    assert store.metadata("runtime_mode") is None


def test_backup_restores_settings_and_initialized_shared_ledger(device):
    store, _ = setup(device)
    initial = preview(device, store)
    personal.confirm_initial(store, device.STATE / "mobile.sqlite3", initial["preview_id"], True,
                             NOW)
    before = personal.settings_view(store)
    ledger = store.latest_portfolio()
    device.initialize(device.export_state())
    restored = device._app.state.store
    assert personal.settings_view(restored) == before
    assert restored.latest_portfolio() == ledger
    restored.verify_integrity()


def test_tampered_settings_fail_closed(device):
    store, _ = setup(device)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE mobile_personal_settings SET payload='{}'")
    with pytest.raises(OperationalIntegrityError):
        personal.read_settings(store)


def test_confirmation_rebuilds_balances_even_if_preview_hash_is_replaced(device):
    store, _ = setup(device)
    original = preview(device, store)
    value = {key: item for key, item in original.items() if key != "preview_id"}
    value["portfolio"]["cash"][0]["available_cash"] = "999999"
    encoded = personal.canonical(value)
    identity = personal.digest(encoded)
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO mobile_initial_previews VALUES(?,?,?)",
                   (identity, encoded, identity))
    with pytest.raises(OperationalConflictError):
        personal.confirm_initial(store, device.STATE / "mobile.sqlite3", identity, True, NOW)
    assert store.latest_portfolio() is None


@pytest.mark.parametrize("change,reason", [
    ({"tax_year": 2025}, "tax_year_outdated"),
    ({"tax_assumptions": {"effective_from": "2027-01-01", "taxable_rate_percent": "20",
                          "nisa_opportunity_cost_percent": "0"}}, "tax_policy_future"),
])
def test_outdated_or_future_tax_inputs_cannot_initialize(device, change, reason):
    store, extra = setup(device)
    revised = ManualPersonalSettings.model_validate({**extra.model_dump(mode="json"), **change})
    personal.save_settings(store, revised, personal.read_settings(store)["revision_id"], NOW)
    assert reason in preview(device, store)["blocking_reasons"]
    assert store.latest_portfolio() is None


@pytest.mark.parametrize("mutation", [
    lambda x: x["cost_assumptions"].update(zero_commission_confirmed=False),
    lambda x: x["cost_assumptions"].update(commission_bps="1"),
    lambda x: x["tax_assumptions"].update(taxable_rate_percent="100.0001"),
    lambda x: x.update(tax_year=True),
])
def test_invalid_explicit_cost_and_tax_assumptions_are_rejected(mutation):
    value = copy.deepcopy(settings("a" * 64).model_dump(mode="json"))
    mutation(value)
    with pytest.raises(ValueError):
        ManualPersonalSettings.model_validate(value)


def test_reserved_cash_decimal_boundary_and_non_nisa_capacity_validation():
    value = settings("a" * 64).model_dump(mode="json")
    value["accounts"][0]["reserved_cash_yen"] = "1000.0002"
    with pytest.raises(ValueError, match="reserved"):
        ManualPersonalSettings.model_validate(value).validate_portfolio("a" * 64, profile())
    value["accounts"][0]["reserved_cash_yen"] = "1000.0001"
    ManualPersonalSettings.model_validate(value).validate_portfolio("a" * 64, profile())
    value["accounts"][0]["nisa_annual_capacity_user_input"] = "0"
    with pytest.raises(ValueError, match="NISA"):
        ManualPersonalSettings.model_validate(value).validate_portfolio("a" * 64, profile())
