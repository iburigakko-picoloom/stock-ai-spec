"""Independent state/cash arithmetic; all market and account values are test fixtures."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.decision.engine import DecisionEngineConfig
from stock_ai.domain import MarketSnapshot, PortfolioProposal, Security
from stock_ai.ml.daily_strategy import (
    DailyDecisionObservation,
    DailySecurityEvidence,
    DailyStrategyInput,
    evaluate_daily_strategy,
    write_daily_strategy,
)
from stock_ai.ml.nav import (
    NavAction,
    NavCash,
    NavInput,
    NavOrder,
    NavPosition,
    NavPrice,
    NavSession,
    evaluate_daily_nav,
    evaluate_stateful_nav,
    fixed_bps_policy,
)
from tests.test_daily_nav import at, order, position, quote
from tests.test_daily_nav import request as nav_request
from tests.test_daily_oof import adapter


def scenario(*, bps=0, initial_b=False):
    forecasts = adapter()
    times = [value.to_pydatetime() for value in forecasts.frame.as_of.unique()[25:28]]
    initial = times[0].replace(hour=16, minute=0) - timedelta(days=1)
    sessions = tuple(
        NavSession(
            trading_date=t.date(),
            execution_at=t.replace(hour=12, minute=30),
            close_at=t.replace(hour=16, minute=0),
            sale_cash_available_at=t.replace(hour=12, minute=30),
            prices=tuple(
                NavPrice(
                    symbol=symbol,
                    execution_price=D(1000),
                    close_price=D(1100 if i == 2 and symbol == "A" else 1000),
                    buy_status="tradable",
                    sell_status="tradable",
                    capacity_shares=100,
                    tick_size=D(1),
                    average_daily_trading_value=D(100000000),
                    source_id="TEST_ONLY",
                )
                for symbol in ("A", "B")
            ),
        )
        for i, t in enumerate(times)
    )
    accounting = NavInput(
        data_mode="fixture",
        source_snapshot_id="TEST_ONLY",
        calendar_id="TEST_ONLY",
        calendar_dates=tuple(t.date() for t in times),
        price_basis="unadjusted",
        execution_semantics="observed_execution_window",
        initial_as_of=initial,
        cash=(NavCash(bucket="cash", amount=D(200000 if initial_b else 300000)),),
        positions=(
            NavPosition(
                symbol="B",
                bucket="cash",
                shares=100,
                unit_cost=D(900),
                last_price=D(1000),
                last_price_at=initial,
            ),
        )
        if initial_b
        else (),
        sessions=sessions,
        cost_policy=fixed_bps_policy(D(bps)),
    )
    previous = (initial, *(session.close_at for session in sessions[:-1]))
    observations = tuple(
        DailyDecisionObservation(
            forecasts=forecasts.at(t),
            market=MarketSnapshot(
                snapshot_id=f"TEST-{i}",
                source="TEST_ONLY",
                as_of=t,
                available_at=previous[i],
                prices={"A": D(1000), "B": D(1000)},
            ),
            reference_price_at=previous[i],
            security_evidence_available_at=previous[i],
            securities=tuple(
                DailySecurityEvidence(
                    security=Security(symbol=s, company_name=s, sector="TEST"),
                    average_daily_trading_value=D(100000000),
                )
                for s in ("A", "B")
            ),
            candidate_symbols=("A",) if i == 0 else (),
            price_basis="unadjusted",
        )
        for i, t in enumerate(times)
    )
    policy = DecisionEngineConfig(
        horizon_weights=(D(0), D(0), D(1)),
        maximum_symbol_weight=D(1),
        maximum_sector_weight=D(1),
        minimum_cash_ratio=D(0),
        maximum_turnover_ratio=D(10),
        minimum_improvement_yen=D(0),
        downside_penalty_weight=D(0),
        uncertainty_penalty_weight=D(0),
    )
    return DailyStrategyInput(
        strategy_id="TEST_ONLY",
        accounting=accounting,
        observations=observations,
        decision_policy=policy,
    )


def replace_observation(data, index, **changes):
    observations = list(data.observations)
    observations[index] = observations[index].model_copy(update=changes)
    return data.model_copy(update={"observations": tuple(observations)})


def replace_session(data, index, **changes):
    sessions = list(data.accounting.sessions)
    sessions[index] = sessions[index].model_copy(update=changes)
    return data.model_copy(
        update={"accounting": data.accounting.model_copy(update={"sessions": tuple(sessions)})}
    )


def test_partial_fills_drive_next_day_and_replay_matches_fixed_orders():
    data = scenario()
    original = data.model_dump_json()
    result = evaluate_daily_strategy(data)
    assert data.model_dump_json() == original
    assert result.decisions_complete and result.research_only and not result.adoption_eligible
    assert [len(d.state.positions) for d in result.decisions] == [0, 1, 1]
    assert [d.state.positions[0].shares for d in result.decisions[1:]] == [100, 200]
    assert [d.orders[0].shares for d in result.decisions] == [300, 200, 100]
    assert [d.positions[0].shares for d in result.strategy.days] == [100, 200, 300]
    assert [d.cash[0].amount for d in result.strategy.days] == [200000, 100000, 0]
    assert result.strategy.days[-1].nav == 330000
    assert result.daily_nav_difference == (D(0), D(0), D(30000))
    assert result.strategy == evaluate_daily_nav(result.execution_input)
    assert result.decisions[1].evaluated_symbols == ("A",)  # Held, absent from candidates.
    for decision in result.decisions:
        proposal = decision.proposal
        assert proposal.is_research_only and not proposal.is_order_instruction
        assert proposal.daily_audit and proposal.morning_audit is None
        assert PortfolioProposal.model_validate(proposal.model_dump()) == proposal
        with pytest.raises(ValueError, match="daily proposal"):
            PortfolioProposal.model_validate({**proposal.model_dump(), "is_research_only": False})


def test_cost_is_paid_once_and_acquisition_basis_tracks_actual_fills():
    result = evaluate_daily_strategy(scenario(bps=10))
    # Two actual 100-share fills at1000, one-way10bps each: cost100 +100.
    assert [d.positions[0].shares for d in result.strategy.days] == [100, 200, 200]
    assert result.strategy.total_trading_cost == 200
    assert result.strategy.days[-1].cash[0].amount == 99800
    assert result.strategy.days[-1].positions[0].unit_cost == 1001
    assert result.strategy.days[-1].nav == 319800
    assert result.daily_nav_difference[-1] == 19800
    assert result.decisions[-1].orders == ()


def test_pending_sale_proceeds_are_nav_but_not_next_decision_buying_power():
    data = scenario(initial_b=True)
    # Allow the first day's buy to fill as many shares as actual cash allows.
    prices = tuple(
        p.model_copy(update={"capacity_shares": 1000}) for p in data.accounting.sessions[0].prices
    )
    data = replace_session(
        data, 0, prices=prices, sale_cash_available_at=data.accounting.sessions[1].execution_at
    )
    result = evaluate_daily_strategy(data)
    day1 = result.decisions[1]
    assert day1.state.cash[0].amount == 0
    assert day1.state.receivables[0].amount == 100000
    assert day1.state.positions[0].symbol == "A" and day1.state.positions[0].shares == 200
    assert not day1.orders
    assert result.strategy.days[0].nav == 300000
    assert result.decisions[2].state.cash[0].amount == 100000
    assert result.decisions[2].orders[0].shares == 100


def test_unfilled_sale_stays_in_holdings_and_is_reassessed():
    data = scenario(initial_b=True)
    prices = tuple(
        p.model_copy(update={"sell_status": "suspended"}) if p.symbol == "B" else p
        for p in data.accounting.sessions[0].prices
    )
    result = evaluate_daily_strategy(replace_session(data, 0, prices=prices))
    assert {p.symbol: p.shares for p in result.decisions[1].state.positions} == {"A": 100, "B": 100}
    assert result.decisions[1].evaluated_symbols == ("A", "B")
    assert any(f.reason == "SUSPENDED" for f in result.strategy.days[0].fills)
    assert any(o.symbol == "B" and o.side.value == "SELL" for o in result.decisions[1].orders)


@pytest.mark.parametrize("missing", ["forecast", "price", "security", "stale", "zero", "liquidity"])
def test_missing_holding_evidence_blocks_day_but_preserves_position(missing):
    data = scenario()
    obs = data.observations[1]
    if missing == "forecast":
        obs = obs.model_copy(
            update={
                "forecasts": obs.forecasts.model_copy(
                    update={
                        "predictions": tuple(
                            p for p in obs.forecasts.predictions if p.symbol != "A"
                        )
                    }
                )
            }
        )
    elif missing == "security":
        obs = obs.model_copy(
            update={"securities": tuple(s for s in obs.securities if s.security.symbol != "A")}
        )
    elif missing == "stale":
        obs = obs.model_copy(
            update={"reference_price_at": obs.reference_price_at - timedelta(days=1)}
        )
    elif missing == "liquidity":
        obs = obs.model_copy(
            update={
                "securities": tuple(
                    item.model_copy(update={"average_daily_trading_value": None})
                    if item.security.symbol == "A"
                    else item
                    for item in obs.securities
                )
            }
        )
    else:
        prices = {"B": D(1000)} if missing == "price" else {"A": D(0), "B": D(1000)}
        obs = obs.model_copy(update={"market": obs.market.model_copy(update={"prices": prices})})
    data = data.model_copy(
        update={"observations": (data.observations[0], obs, data.observations[2])}
    )
    result = evaluate_daily_strategy(data)
    assert not result.decisions_complete
    assert result.decisions[1].blocked_reasons and not result.decisions[1].orders
    assert result.decisions[1].proposal is None
    assert result.strategy.days[1].positions[0].shares == 100
    assert result.decisions[2].state.positions[0].shares == 100


def test_future_execution_and_closing_prices_do_not_enter_current_decision():
    data = scenario()
    original = evaluate_daily_strategy(data)
    future_prices = tuple(
        p.model_copy(update={"execution_price": D(2000), "close_price": D(4000)})
        for p in data.accounting.sessions[-1].prices
    )
    altered = evaluate_daily_strategy(replace_session(data, 2, prices=future_prices))
    assert original.decisions == altered.decisions
    assert original.strategy.days[:2] == altered.strategy.days[:2]
    # Last buy cannot afford a lot at the unseen doubled execution price.
    assert altered.strategy.days[-1].fills[0].reason == "INSUFFICIENT_CASH"
    assert altered.strategy.days[-1].positions[0].shares == 200


def test_split_before_cutoff_is_applied_before_decision_and_old_unit_price_blocks():
    data = scenario()
    effective = data.observations[1].forecasts.as_of.replace(hour=9)
    action = NavAction(
        event_id="split",
        symbol="A",
        kind="split",
        effective_at=effective,
        available_at=effective - timedelta(days=1),
        source_id="TEST",
        numerator=2,
    )
    accounting = data.accounting.model_copy(update={"actions": (action,)})
    data = data.model_copy(update={"accounting": accounting})
    prices = tuple(
        p.model_copy(update={"execution_price": D(500), "close_price": D(500)})
        if p.symbol == "A"
        else p
        for p in accounting.sessions[1].prices
    )
    result = evaluate_daily_strategy(replace_session(data, 1, prices=prices))
    day = result.decisions[1]
    assert day.state.positions[0].shares == 200 and day.state.positions[0].unit_cost == 500
    assert day.state.applied_event_ids == ("split",)
    assert any("CORPORATE_ACTION" in reason for reason in day.blocked_reasons)
    assert not day.orders
    assert result.strategy.days[1].nav == 300000


def test_search_cap_is_explicit_incomplete_comparison_not_silent_cash_strategy():
    data = scenario()
    data = data.model_copy(
        update={
            "decision_policy": data.decision_policy.model_copy(
                update={"max_search_combinations": 1}
            )
        }
    )
    result = evaluate_daily_strategy(data)
    assert not result.decisions_complete
    assert result.decisions[0].blocked_reasons[0].startswith("SEARCH_SPACE_TOO_LARGE")
    assert not result.execution_input.orders and not result.strategy.days[0].positions


@pytest.mark.parametrize(
    "mutation",
    [
        "future_liquidity",
        "future_price",
        "time",
        "freeze",
        "duplicate",
        "duplicate_security",
        "calendar",
        "policy",
        "lot",
        "bundle",
        "orders",
    ],
)
def test_inconsistent_or_future_inputs_are_rejected(mutation):
    data = scenario()
    obs = data.observations[0]
    if mutation == "future_liquidity":
        data = replace_observation(
            data, 0, security_evidence_available_at=obs.forecasts.as_of + timedelta(seconds=1)
        )
    elif mutation == "future_price":
        data = replace_observation(
            data, 0, reference_price_at=obs.forecasts.as_of + timedelta(seconds=1)
        )
    elif mutation == "time":
        data = replace_observation(
            data,
            0,
            market=obs.market.model_copy(
                update={"as_of": obs.forecasts.as_of + timedelta(seconds=1)}
            ),
        )
    elif mutation == "duplicate":
        data = replace_observation(data, 0, candidate_symbols=("A", "A"))
    elif mutation == "duplicate_security":
        data = replace_observation(data, 0, securities=(obs.securities[0], obs.securities[0]))
    elif mutation == "freeze":
        at = obs.forecasts.as_of + timedelta(minutes=1)
        forecast = obs.forecasts.model_copy(
            update={
                "as_of": at,
                "predictions": tuple(
                    p.model_copy(update={"as_of": at}) for p in obs.forecasts.predictions
                ),
            }
        )
        data = replace_observation(
            data, 0, forecasts=forecast, market=obs.market.model_copy(update={"as_of": at})
        )
    elif mutation == "calendar":
        data = data.model_copy(update={"observations": data.observations[:-1]})
    elif mutation in ("policy", "lot"):
        change = (
            {"horizon_weights": (D(1), D(0), D(0))} if mutation == "policy" else {"lot_size": 1}
        )
        data = data.model_copy(
            update={"decision_policy": data.decision_policy.model_copy(update=change)}
        )
    elif mutation == "bundle":
        f = obs.forecasts
        updated = f.model_copy(
            update={
                "model_version": "DIFFERENT",
                "predictions": tuple(
                    p.model_copy(update={"model_version": "DIFFERENT"}) for p in f.predictions
                ),
            }
        )
        data = replace_observation(data, 0, forecasts=updated)
    else:
        t = obs.forecasts.as_of
        fixed = NavOrder(
            order_id="fixed",
            trading_date=t.date(),
            decided_at=t,
            symbol="A",
            bucket="cash",
            side="BUY",
            shares=100,
        )
        data = data.model_copy(
            update={"accounting": data.accounting.model_copy(update={"orders": (fixed,)})}
        )
    with pytest.raises(ValueError):
        evaluate_daily_strategy(data)


def test_stateful_nav_rejects_bad_clock_and_callback_orders():
    data = nav_request()
    for times in ((), (at(0, 12),), (at(0, 11).replace(tzinfo=None),)):
        with pytest.raises(ValueError):
            evaluate_stateful_nav(data, decision_times=times, decide=lambda state: ())
    for bad in (order(0, bucket="ABSENT"), order(0).model_copy(update={"decided_at": at(0, 10)})):
        with pytest.raises(ValueError, match="generated order"):
            evaluate_stateful_nav(
                data, decision_times=(at(0, 11),), decide=lambda state, bad=bad: (bad,)
            )
    with pytest.raises(ValueError, match="repeated identity"):
        evaluate_stateful_nav(
            data, decision_times=(at(0, 11),), decide=lambda state: (order(0), order(0))
        )
    with pytest.raises(ValueError, match="mix"):
        evaluate_stateful_nav(
            data.model_copy(update={"orders": (order(0),)}),
            decision_times=(at(0, 11),),
            decide=lambda state: (),
        )


def test_stateful_receipt_contains_known_inputs_generated_orders_and_both_paths(tmp_path: Path):
    path = write_daily_strategy(scenario(), tmp_path)
    raw = path.read_bytes()
    assert hashlib.sha256(raw[:-1]).hexdigest() == path.stem
    payload = json.loads(raw)
    assert payload["result"]["decisions_complete"]
    assert len(payload["result"]["execution_input"]["orders"]) == 3
    assert len(payload["result"]["hold"]["days"]) == 3
    assert "ml/nav.py" in payload["source_sha256"]
    assert payload["input"]["accounting"]["orders"] == []


def test_dividend_claim_survives_sale_and_pays_before_later_decision():
    data = nav_request(prices=((quote(),), (quote(),)), positions=(position(),))
    dividend = NavAction(
        event_id="dividend",
        symbol="A",
        kind="dividend",
        effective_at=at(0, 9),
        available_at=at(0, 8),
        source_id="TEST",
        cash_per_share=D(10),
        payment_at=at(1, 10),
    )
    data = data.model_copy(update={"actions": (dividend,)})
    states = []

    def decide(state):
        states.append(state)
        return (order(0, side="SELL"),) if len(states) == 1 else ()

    replay, result = evaluate_stateful_nav(
        data, decision_times=(at(0, 11), at(1, 11)), decide=decide
    )
    assert states[0].receivables[0].amount == 1000
    assert not states[1].positions and not states[1].receivables
    assert states[1].cash[0].amount == data.cash[0].amount + 10000 + 1000
    assert result == evaluate_daily_nav(replay)


def test_split_after_decision_invalidates_order_without_losing_shares():
    data = nav_request(positions=(position(),))
    split = NavAction(
        event_id="split",
        symbol="A",
        kind="split",
        effective_at=at(0, 11) + timedelta(minutes=30),
        available_at=at(0, 8),
        source_id="TEST",
        numerator=2,
    )
    data = data.model_copy(update={"actions": (split,)})
    states = []

    def decide(state):
        states.append(state)
        return (order(0, side="SELL"),)

    _, result = evaluate_stateful_nav(data, decision_times=(at(0, 11),), decide=decide)
    assert states[0].positions[0].shares == 100 and not states[0].applied_event_ids
    assert result.days[0].fills[0].reason == "CORPORATE_ACTION_AFTER_DECISION"
    assert result.days[0].positions[0].shares == 200


def test_cli_writes_strategy_receipt_and_invalid_input_has_no_result(tmp_path: Path):
    data = scenario()
    path = tmp_path / "input.json"
    path.write_text(data.model_dump_json(), encoding="utf-8")
    arguments = [
        "research",
        "evaluate-daily-strategy",
        "--input",
        str(path),
        "--output-root",
        str(tmp_path / "result"),
    ]
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["research_only"] and not output["adoption_eligible"]
    assert Path(output["evaluation_path"]).is_file()
    saved = list((tmp_path / "result").iterdir())
    path.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 2 and "blocked" in result.output
    assert list((tmp_path / "result").iterdir()) == saved
