from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.domain import ExecutionRecord, MarketSnapshot, Position, Security
from stock_ai.operations.api import create_app
from stock_ai.operations.daily import PredictionSnapshot
from stock_ai.operations.manual_portfolio import ImportedManualPortfolio
from stock_ai.operations.personal import (
    AccountBinding,
    ExplicitTaxState,
    PersonalComparison,
    PersonalComparisonRequest,
    PersonalMarket,
    PersonalSettings,
    compare_personal,
    compare_stored_personal,
)
from stock_ai.operations.store import OperationalConflictError, OperationalStore
from tests.conftest import AS_OF, candidate, decision_engine, portfolio, prediction
from tests.test_manual_portfolio import ACCOUNT, EMPTY, envelope


def scenario(*, budget="100000", nisa=False, held=True):
    positions = (
        (
            Position(
                symbol="1001",
                account_bucket_id="bucket",
                shares=100,
                average_acquisition_price=Decimal(900),
                market_price=Decimal(950),
            ),
        )
        if held
        else ()
    )
    ledger = portfolio(positions)
    if nisa:
        ledger = ledger.model_copy(
            update={
                "account_buckets": (
                    ledger.account_buckets[0].model_copy(
                        update={"account_type": "nisa", "withholding_mode": "not_applicable"}
                    ),
                ),
                "tax_states": (
                    ledger.tax_states[0].model_copy(
                        update={
                            "nisa_annual_capacity_user_input": Decimal(100000),
                            "nisa_lifetime_capacity_user_input": Decimal(100000),
                        }
                    ),
                ),
            }
        )
    profile = {
        **EMPTY,
        "investment_budget_yen": budget,
        "maximum_drawdown_percent": 20.0,
        "holdings_status": "recorded" if held else "none",
        "accounts": [
            {
                **ACCOUNT,
                "available_cash_yen": "200000",
                "account_type": "nisa" if nisa else "taxable_specified",
                "withholding_mode": "not_applicable" if nisa else "withholding",
            }
        ],
        "holdings": [
            {
                "account_id": ACCOUNT["id"],
                "symbol": "1001",
                "shares": 100,
                "average_acquisition_price_yen": "900",
            }
        ]
        if held
        else [],
    }
    manual = ImportedManualPortfolio.from_response(
        envelope(portfolio=profile, saved_at=(AS_OF - timedelta(hours=1)).isoformat()),
        received_at=AS_OF - timedelta(minutes=50),
    )
    preds = tuple(
        prediction(s, mu).model_copy(
            update={
                "schema_version": 2,
                "expected_return_1d": None,
                "active_horizons": (5, 20),
                "risk_horizon": 20,
            }
        )
        for s, mu in (("1001", -0.1), ("1002", 0.2))
        if held or s == "1002"
    )
    forecast = PredictionSnapshot.create(
        as_of=AS_OF,
        generated_at=AS_OF,
        data_as_of=AS_OF - timedelta(hours=18),
        selection_id="fixture-selection",
        model_version="test-model-v1",
        feature_version="test-features-v1",
        data_snapshot_id="test-snapshot",
        large_loss_threshold=-0.1,
        downside_quantile_alpha=0.1,
        candidate_symbols=("1002",),
        holding_symbols=("1001",) if held else (),
        predictions=preds,
    )
    engine = decision_engine(tax_rate=Decimal("0.2"))
    cost = engine.cost_engine.policy.model_copy(update={"slippage_bps": Decimal(100)})
    settings = PersonalSettings(
        version="TEST_ONLY",
        bindings=(AccountBinding(manual_account_id=ACCOUNT["id"], ledger_bucket_id="bucket"),),
        cash_basis="total_including_reserved",
        budget_basis="maximum_total_equity_market_value",
        nisa_capacity_basis="remaining_purchase_notional_no_same_day_sale_restore",
        reviewed_drawdown_preference_percent=20,
        tax_inputs=tuple(
            ExplicitTaxState.model_validate(x.model_dump()) for x in ledger.tax_states
        ),
        cost_policy=cost,
        tax_policy=engine.tax_engine.policy,
        decision_policy=engine.config.model_copy(
            update={"horizon_weights": (Decimal(0), Decimal(0), Decimal(1))}
        ),
    )
    market = PersonalMarket(
        market=MarketSnapshot(
            snapshot_id="TEST_ONLY",
            as_of=AS_OF,
            available_at=AS_OF - timedelta(hours=18),
            source="TEST_ONLY",
            prices={"1001": 1000, "1002": 1000},
        ),
        observed_at=AS_OF - timedelta(hours=19),
        securities=tuple(
            Security(symbol=s, company_name=s, sector="fixture") for s in ("1001", "1002")
        ),
        average_daily_trading_values=(("1001", Decimal(100000000)), ("1002", Decimal(100000000))),
    )
    request = PersonalComparisonRequest(
        checked_at=AS_OF + timedelta(minutes=1),
        maximum_input_age_hours=72,
        settings=settings,
        market=market,
    )
    return request, dict(manual=manual, ledger=ledger, forecast=forecast, executions=())


def codes(result):
    return {x.code for x in result.blocking_reasons}


def test_reconciled_personal_comparison_matches_hand_cost_tax_cash_and_budget():
    request, inputs = scenario()
    originals = {k: v.model_dump_json() for k, v in inputs.items() if k != "executions"}
    result = compare_personal(request, **inputs)
    assert not result.blocking_reasons
    proposal = result.proposal
    assert proposal is not None and proposal.is_research_only
    assert {x.symbol: x.action.value for x in proposal.lines} == {"1001": "SELL", "1002": "BUY"}
    assert proposal.estimated_cash_after["bucket"] == Decimal(196000)
    assert proposal.hold_utility == Decimal(-10000)
    assert proposal.proposed_utility == Decimal(16000)
    assert proposal.net_improvement == Decimal(26000)
    assert result.selected_equity_value_yen == Decimal(100000)
    assert not result.budget_exceeded_by_existing_holdings
    assert {k: v.model_dump_json() for k, v in inputs.items() if k != "executions"} == originals
    assert PersonalComparison.model_validate_json(result.model_dump_json()) == result
    assert not result.adoption_eligible and not result.applied_to_ledger


@pytest.mark.parametrize(
    "budget,shares", [("0", 0), ("99999", 0), ("100000", 100), ("200000", 100)]
)
def test_no_holdings_and_zero_budget_never_invent_cash(budget, shares):
    request, inputs = scenario(budget=budget, held=False)
    result = compare_personal(request, **inputs)
    assert result.proposal.targets[0].target_shares == shares
    assert result.investment_budget_yen == Decimal(budget)


@pytest.mark.parametrize(
    "change,reason",
    [
        ("cash", "CASH_DIFFERS"),
        ("shares", "HOLDING_SHARES_DIFFER"),
        ("acquisition", "ACQUISITION_PRICE_DIFFERS"),
        ("mapping", "ACCOUNT_MAPPING_INCOMPLETE"),
        ("classification", "ACCOUNT_CLASSIFICATION_DIFFERS"),
        ("tax", "TAX_STATE_NOT_RECONCILED"),
        ("risk", "RISK_PREFERENCE_CHANGED"),
        ("policy", "COST_TAX_POLICY_DIFFERS"),
        ("old", "FORECAST_NOT_CURRENT_DAY"),
        ("price", "MARKET_EVIDENCE_MISSING"),
        ("price_age", "MARKET_STALE_OR_FUTURE"),
        ("future_manual", "MANUAL_INPUT_STALE_OR_AFTER_FORECAST"),
        ("missing_holding", "FORECAST_HOLDINGS_DIFFER"),
        ("nisa", "NISA_CAPACITY_UNKNOWN"),
        ("cap", "SEARCH_CAP_EXCEEDED"),
        ("ledger_age", "LEDGER_STALE_OR_AFTER_FORECAST"),
    ],
)
def test_disagreement_or_missing_evidence_blocks_without_proposal(change, reason):
    request, inputs = scenario(nisa=change == "nisa")
    ledger = inputs["ledger"]
    settings = request.settings
    if change == "cash":
        ledger = ledger.model_copy(
            update={"cash": (ledger.cash[0].model_copy(update={"available_cash": Decimal(1)}),)}
        )
    elif change == "shares":
        ledger = ledger.model_copy(
            update={"positions": (ledger.positions[0].model_copy(update={"shares": 99}),)}
        )
    elif change == "acquisition":
        ledger = ledger.model_copy(
            update={
                "positions": (
                    ledger.positions[0].model_copy(
                        update={"average_acquisition_price": Decimal(1)}
                    ),
                )
            }
        )
    elif change == "mapping":
        settings = settings.model_copy(update={"bindings": ()})
    elif change == "classification":
        ledger = ledger.model_copy(
            update={
                "account_buckets": (
                    ledger.account_buckets[0].model_copy(
                        update={"withholding_mode": "no_withholding"}
                    ),
                )
            }
        )
    elif change == "tax":
        settings = settings.model_copy(update={"tax_inputs": ()})
    elif change == "risk":
        settings = settings.model_copy(update={"reviewed_drawdown_preference_percent": 10.0})
    elif change == "policy":
        settings = settings.model_copy(
            update={
                "cost_policy": settings.cost_policy.model_copy(update={"policy_id": "different"})
            }
        )
    elif change == "old":
        request = request.model_copy(update={"checked_at": AS_OF + timedelta(days=1)})
    elif change == "price":
        request = request.model_copy(
            update={"market": request.market.model_copy(update={"securities": ()})}
        )
    elif change == "price_age":
        request = request.model_copy(
            update={
                "market": request.market.model_copy(
                    update={"observed_at": AS_OF - timedelta(days=20)}
                )
            }
        )
    elif change == "future_manual":
        inputs["manual"] = inputs["manual"].model_copy(
            update={"received_at": AS_OF + timedelta(seconds=1)}
        )
    elif change == "missing_holding":
        f = inputs["forecast"].model_dump(exclude={"snapshot_id"})
        f["holding_symbols"] = ()
        f["predictions"] = (inputs["forecast"].predictions[1],)
        inputs["forecast"] = PredictionSnapshot.create(**f)
    elif change == "nisa":
        state = ledger.tax_states[0].model_copy(update={"nisa_annual_capacity_user_input": None})
        ledger = ledger.model_copy(update={"tax_states": (state,)})
        settings = settings.model_copy(
            update={"tax_inputs": (ExplicitTaxState.model_validate(state.model_dump()),)}
        )
    elif change == "cap":
        settings = settings.model_copy(
            update={
                "decision_policy": settings.decision_policy.model_copy(
                    update={"max_search_combinations": 1}
                )
            }
        )
    elif change == "ledger_age":
        ledger = ledger.model_copy(update={"as_of": AS_OF - timedelta(days=20)})
    request = request.model_copy(update={"settings": settings})
    inputs["ledger"] = ledger
    result = compare_personal(request, **inputs)
    assert reason in codes(result) and result.proposal is None


def test_empty_actual_shape_keeps_unknown_budget_and_risk():
    manual = ImportedManualPortfolio.from_response(
        envelope(saved_at=AS_OF.isoformat()), received_at=AS_OF
    )
    result = compare_personal(
        PersonalComparisonRequest(checked_at=AS_OF, maximum_input_age_hours=72),
        manual=manual,
        ledger=None,
        forecast=None,
        executions=(),
    )
    assert result.investment_budget_yen is None and result.holding_symbols == ()
    assert {
        "INPUT_MISSING_ACCOUNTS",
        "INPUT_MISSING_INVESTMENT_BUDGET_YEN",
        "INPUT_MISSING_MAXIMUM_DRAWDOWN_PERCENT",
        "LEDGER_MISSING",
        "FORECAST_MISSING",
    } <= codes(result)
    assert "INPUT_MISSING_HOLDINGS_STATUS" not in codes(result)


def test_execution_and_race_checks_and_store_remain_unchanged(tmp_path, monkeypatch):
    request, inputs = scenario()
    execution = ExecutionRecord(
        execution_id="unapplied",
        decision_id="TEST_ONLY",
        executed_at=AS_OF,
        symbol="1001",
        account_bucket_id="bucket",
        status="filled",
        side="BUY",
        ordered_shares=100,
        filled_shares=100,
        average_fill_price=Decimal(1000),
    )
    assert "UNAPPLIED_EXECUTION" in codes(
        compare_personal(request, **{**inputs, "executions": (execution,)})
    )
    store = OperationalStore(tmp_path / "state.sqlite3")
    store.import_manual_portfolio(inputs["manual"])
    store.append_portfolio(inputs["ledger"], created_at=AS_OF)
    store.append_prediction_snapshot(inputs["forecast"])
    before = store.verify_integrity()
    result = compare_stored_personal(store, request, now=request.checked_at)
    assert result.proposal and store.verify_integrity() == before
    calls = iter([inputs["ledger"], None])
    monkeypatch.setattr(store, "latest_portfolio", lambda: next(calls))
    with pytest.raises(OperationalConflictError, match="changed"):
        compare_stored_personal(store, request, now=request.checked_at)


def test_local_readiness_and_comparison_use_server_clock_and_manual_intent(tmp_path):
    request, inputs = scenario()
    db = tmp_path / "state.sqlite3"
    store = OperationalStore(db)
    store.import_manual_portfolio(inputs["manual"])
    store.append_portfolio(inputs["ledger"], created_at=AS_OF)
    store.append_prediction_snapshot(inputs["forecast"])
    client = TestClient(
        create_app(db, clock=lambda: request.checked_at), base_url="http://localhost"
    )
    assert client.get("/api/v1/personal/readiness").json()["proposal"] is None
    payload = request.model_dump(mode="json")
    payload["checked_at"] = "2000-01-01T00:00:00Z"
    assert client.post("/api/v1/personal/compare", json=payload).status_code == 428
    response = client.post(
        "/api/v1/personal/compare", json=payload, headers={"X-Stock-AI-Intent": "manual-record"}
    )
    assert response.status_code == 200 and response.json()["proposal"] is not None


def test_cli_exports_missing_inputs_without_seeding_financial_records(tmp_path):
    db = tmp_path / "state.sqlite3"
    store = OperationalStore(db)
    before = store.verify_integrity()
    out = tmp_path / "result.json"
    result = CliRunner().invoke(
        app, ["ops", "compare-personal", "--database", str(db), "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    saved = PersonalComparison.model_validate_json(out.read_text())
    assert "MANUAL_INPUT_MISSING" in codes(saved) and not saved.applied_to_ledger
    assert store.verify_integrity() == before
    assert json.loads(result.output)["blocked"] is True


def test_budget_is_shared_across_accounts_and_cash_is_not_transferred():
    ledger = portfolio(cash=Decimal(200000))
    ledger = ledger.model_copy(
        update={
            "account_buckets": (
                *ledger.account_buckets,
                ledger.account_buckets[0].model_copy(update={"bucket_id": "second"}),
            ),
            "cash": (
                *ledger.cash,
                ledger.cash[0].model_copy(update={"account_bucket_id": "second"}),
            ),
            "tax_states": (
                *ledger.tax_states,
                ledger.tax_states[0].model_copy(update={"account_bucket_id": "second"}),
            ),
        }
    )
    result = decision_engine().propose(
        portfolio=ledger,
        candidates=(candidate("A", 0.2), candidate("A", 0.2, bucket="second")),
        generated_at=AS_OF,
        model_bundle_version="test-model-v1",
        maximum_invested_value=Decimal(100000),
    )
    assert sum(x.target_shares for x in result.targets) == 100
    assert sorted(result.estimated_cash_after.values()) == [Decimal(100000), Decimal(200000)]


def test_nisa_sales_do_not_replenish_purchase_capacity_and_known_zero_is_valid():
    request, inputs = scenario(nisa=True, budget="300000")
    state = (
        inputs["ledger"]
        .tax_states[0]
        .model_copy(update={"nisa_annual_capacity_user_input": Decimal(0)})
    )
    inputs["ledger"] = inputs["ledger"].model_copy(update={"tax_states": (state,)})
    request = request.model_copy(
        update={
            "settings": request.settings.model_copy(
                update={"tax_inputs": (ExplicitTaxState.model_validate(state.model_dump()),)}
            )
        }
    )
    result = compare_personal(request, **inputs)
    assert not result.blocking_reasons
    assert {x.symbol: x.action.value for x in result.proposal.lines} == {
        "1001": "SELL",
        "1002": "SKIP",
    }
    assert result.proposal.estimated_cash_after["bucket"] == Decimal(299000)
    assert all(x.estimated_tax_effect == 0 for x in result.proposal.lines)


def test_cash_basis_reserved_amount_and_missing_tax_amount_are_explicit():
    request, inputs = scenario()
    ledger = inputs["ledger"]
    inputs["ledger"] = ledger.model_copy(
        update={"cash": (ledger.cash[0].model_copy(update={"reserved_cash": Decimal(50000)}),)}
    )
    result = compare_personal(request, **inputs)
    assert not result.blocking_reasons and result.proposal.estimated_cash_after[
        "bucket"
    ] == Decimal(146000)
    assert inputs["ledger"].cash[0].reserved_cash == Decimal(50000)
    request = request.model_copy(
        update={
            "settings": request.settings.model_copy(
                update={"cash_basis": "deployable_after_reserved"}
            )
        }
    )
    assert "CASH_DIFFERS" in codes(compare_personal(request, **inputs))
    tax = request.settings.tax_inputs[0].model_dump()
    del tax["realized_gain_ytd"]
    with pytest.raises(ValueError, match="realized_gain_ytd"):
        ExplicitTaxState.model_validate(tax)


@pytest.mark.parametrize(
    "status,filled,applied,when,reason",
    [
        ("open", 0, False, AS_OF, "OPEN_EXECUTION"),
        ("partially_filled", 50, False, AS_OF, "UNAPPLIED_EXECUTION"),
        ("filled", 100, True, AS_OF + timedelta(seconds=1), "EXECUTION_AFTER_FORECAST"),
    ],
)
def test_pending_and_future_executions_cannot_disappear(status, filled, applied, when, reason):
    request, inputs = scenario()
    execution = ExecutionRecord(
        execution_id="event",
        decision_id="fixture",
        executed_at=when,
        symbol="1001",
        account_bucket_id="bucket",
        status=status,
        side="BUY",
        ordered_shares=100,
        filled_shares=filled,
        average_fill_price=Decimal(1000) if filled else None,
    )
    inputs["executions"] = (execution,)
    if applied:
        inputs["ledger"] = inputs["ledger"].model_copy(update={"applied_execution_ids": ("event",)})
    result = compare_personal(request, **inputs)
    assert reason in codes(result) and result.proposal is None


def test_budget_breach_is_reported_without_forcing_a_sale():
    request, inputs = scenario(budget="0")
    forecast = inputs["forecast"].model_dump(exclude={"snapshot_id"})
    forecast["predictions"] = tuple(
        p.model_copy(update={"expected_return_20d": 0.5 if p.symbol == "1001" else -0.5})
        for p in inputs["forecast"].predictions
    )
    inputs["forecast"] = PredictionSnapshot.create(**forecast)
    result = compare_personal(request, **inputs)
    assert result.budget_exceeded_by_existing_holdings
    assert (
        result.proposal.lines[0].current_shares
        == result.proposal.lines[0].recommended_shares
        == 100
    )
    changed = result.model_dump()
    changed["investment_budget_yen"] = "1000000"
    with pytest.raises(ValueError, match="identity"):
        PersonalComparison.model_validate(changed)


def test_every_account_holding_and_odd_lot_is_preserved():
    request, inputs = scenario()
    ledger = inputs["ledger"]
    second_id = "00000000-0000-4000-8000-000000000002"
    second_bucket = ledger.account_buckets[0].model_copy(update={"bucket_id": "second"})
    second_cash = ledger.cash[0].model_copy(
        update={"account_bucket_id": "second", "available_cash": Decimal(0)}
    )
    second_tax = ledger.tax_states[0].model_copy(update={"account_bucket_id": "second"})
    odd = ledger.positions[0].model_copy(update={"account_bucket_id": "second", "shares": 1})
    inputs["ledger"] = ledger.model_copy(
        update={
            "account_buckets": (*ledger.account_buckets, second_bucket),
            "cash": (*ledger.cash, second_cash),
            "tax_states": (*ledger.tax_states, second_tax),
            "positions": (*ledger.positions, odd),
        }
    )
    profile = inputs["manual"].portfolio.model_dump(mode="json")
    profile["accounts"].append(
        {**profile["accounts"][0], "id": second_id, "available_cash_yen": "0"}
    )
    profile["holdings"].append({**profile["holdings"][0], "account_id": second_id, "shares": 1})
    inputs["manual"] = ImportedManualPortfolio.from_response(
        envelope(portfolio=profile, saved_at=(AS_OF - timedelta(hours=1)).isoformat()),
        received_at=AS_OF - timedelta(minutes=50),
    )
    request = request.model_copy(
        update={
            "settings": request.settings.model_copy(
                update={
                    "bindings": (
                        *request.settings.bindings,
                        AccountBinding(manual_account_id=second_id, ledger_bucket_id="second"),
                    ),
                    "tax_inputs": tuple(
                        ExplicitTaxState.model_validate(x.model_dump())
                        for x in inputs["ledger"].tax_states
                    ),
                }
            )
        }
    )
    result = compare_personal(request, **inputs)
    assert not result.blocking_reasons and result.holding_symbols == ("1001",)
    lines = {(x.symbol, x.account_bucket_id): x for x in result.proposal.lines}
    assert lines["1001", "second"].current_shares == lines["1001", "second"].recommended_shares == 1
    assert lines["1001", "bucket"].current_shares == 100
    assert result.proposal.estimated_cash_after["second"] == 0


def test_non1130_snapshot_never_becomes_a_personal_daily_comparison():
    request, inputs = scenario()
    forecast = inputs["forecast"].model_dump(exclude={"snapshot_id"})
    changed = AS_OF + timedelta(seconds=1)
    forecast.update(
        as_of=changed,
        generated_at=changed,
        predictions=tuple(
            p.model_copy(update={"as_of": changed}) for p in inputs["forecast"].predictions
        ),
    )
    inputs["forecast"] = PredictionSnapshot.create(**forecast)
    result = compare_personal(request, **inputs)
    assert "FORECAST_NOT_1130_FREEZE" in codes(result) and result.proposal is None
