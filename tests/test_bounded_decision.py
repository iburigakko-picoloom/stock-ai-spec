from __future__ import annotations

from decimal import Decimal
from random import Random

import pytest

from stock_ai.decision.costs import CostPolicy
from stock_ai.decision.engine import DailyPortfolioDecisionEngine, SearchSpaceTooLarge
from stock_ai.domain import AccountType, Position, ProposalAction, WithholdingMode
from tests.conftest import AS_OF, candidate, decision_engine, portfolio


def engines(**kwargs):
    exact = decision_engine(**kwargs)
    exact.config = exact.config.model_copy(update={"horizon_weights": (
        Decimal(0), Decimal(0), Decimal(1),
    )})
    bounded = DailyPortfolioDecisionEngine(
        config=exact.config.model_copy(update={"version": "daily-decision-engine-v3-bounded"}),
        cost_engine=exact.cost_engine, tax_engine=exact.tax_engine,
    )
    return exact, bounded


def propose(engine, state, candidates, **kwargs):
    return engine.propose(portfolio=state, candidates=candidates, generated_at=AS_OF,
                          model_bundle_version="test-model-v1", **kwargs)


@pytest.mark.parametrize("held,signal", [(False, .2), (True, -.1), (True, .2)])
def test_small_scenarios_match_exact_and_preserve_legacy_payloads(held, signal):
    positions = (() if not held else (Position(
        symbol="A", account_bucket_id="bucket", shares=100,
        average_acquisition_price=Decimal(900), market_price=Decimal(1000),
    ),))
    state = portfolio(positions, cash=Decimal(150000))
    values = (candidate("A", signal),)
    exact, bounded = engines(tax_rate=Decimal(".2"))
    reference, result = (propose(engine, state, values) for engine in (exact, bounded))
    assert result.targets == reference.targets
    assert result.proposed_utility == reference.proposed_utility
    assert result.estimated_cash_after == reference.estimated_cash_after
    assert "search_audit" not in reference.model_dump(mode="json")
    assert result.search_audit.global_optimum_proven is False
    assert result.search_audit.considered_key_count == 1


def test_aggregate_sales_tax_and_no_trade_threshold_remain_the_exact_objective():
    positions = tuple(Position(
        symbol=symbol, account_bucket_id="bucket", shares=100,
        average_acquisition_price=Decimal(price), market_price=Decimal(1000),
    ) for symbol, price in (("A", 900), ("C", 1100)))
    state = portfolio(positions, cash=Decimal(50000))
    values = (candidate("A", -.2), candidate("C", -.2), candidate("B", .3))
    exact, bounded = engines(tax_rate=Decimal(".2"))
    reference, result = (propose(engine, state, values) for engine in (exact, bounded))
    assert result.targets == reference.targets
    assert result.proposed_utility == reference.proposed_utility
    assert sum(x.estimated_tax_effect for x in result.lines) == 0
    assert [x.action for x in result.lines] == [ProposalAction.SELL, ProposalAction.BUY,
                                               ProposalAction.SELL]
    bounded.config = bounded.config.model_copy(update={"minimum_improvement_yen": Decimal("1e9")})
    unchanged = propose(bounded, state, values)
    assert unchanged.net_improvement == 0 and unchanged.no_trade_reason
    assert unchanged.search_audit is not None


def large_scenario(*, with_costs=False):
    held = Position(symbol="HELD", account_bucket_id="bucket", shares=100,
                    average_acquisition_price=Decimal(900), market_price=Decimal(1000))
    state = portfolio((held,), cash=Decimal(900000))
    values = (candidate("HELD", -.1), *(candidate(
        f"S{i:04}", .3 - i / 2000, sector=f"Sector {i % 10}",
    ) for i in range(300)))
    costs = (CostPolicy(policy_id="cost-v1", version="bounded-cost-fixture-v1",
                        commission_fixed=Decimal(70), full_spread_bps=Decimal(10),
                        slippage_bps=Decimal(5), impact_bps_at_full_adv=Decimal(25))
             if with_costs else None)
    exact, bounded = engines(cost_policy=costs,
                             tax_rate=Decimal(".2") if with_costs else Decimal(0))
    config = {"maximum_symbol_weight": Decimal(".1"), "maximum_sector_weight": Decimal(".3"),
              "minimum_cash_ratio": Decimal(".1")}
    exact.config = exact.config.model_copy(update=config)
    bounded.config = bounded.config.model_copy(update=config)
    return state, values, exact, bounded


def test_all_300_candidates_and_holding_are_evaluated_without_enumeration(monkeypatch):
    state, values, exact, bounded = large_scenario()
    with pytest.raises(SearchSpaceTooLarge):
        propose(exact, state, values)
    monkeypatch.setattr(bounded, "_share_options", lambda *a: pytest.fail("enumerated share grid"))
    result = propose(bounded, state, values)
    assert result.search_audit.candidate_key_count == 301
    assert result.search_audit.considered_key_count == 301
    assert result.search_audit.evaluations <= result.search_audit.evaluation_budget
    assert len(result.targets) == 301
    chosen = {x.symbol: x.target_shares for x in result.targets if x.target_shares}
    assert chosen == {f"S{i:04}": 100 for i in range(9)}
    assert result.estimated_cash_after["bucket"] == 100000
    assert result.net_improvement > 0
    assert propose(bounded, state, tuple(reversed(values))) == result


def test_liquidity_budget_and_fractional_holdings_are_never_rounded_away():
    held = Position(symbol="A", account_bucket_id="bucket", shares=137,
                    average_acquisition_price=Decimal(900), market_price=Decimal(1000))
    state = portfolio((held,), cash=Decimal(200000))
    values = (candidate("A", -.1), candidate("B", .3).model_copy(update={
        "average_daily_trading_value": Decimal(1000000),
    }))
    _, bounded = engines()
    result = propose(bounded, state, values, maximum_invested_value=Decimal(50000))
    assert result.search_audit.cash_baseline == "not_regular_lot"
    assert {x.symbol: x.target_shares for x in result.targets} == {"A": 37, "B": 0}
    assert result.net_improvement > 0


def test_enormous_cash_never_materializes_a_share_range(monkeypatch):
    _, bounded = engines()
    monkeypatch.setattr(bounded, "_share_options", lambda *a: pytest.fail("huge range allocated"))
    value = candidate("A", .3, price=Decimal(1)).model_copy(update={
        "average_daily_trading_value": Decimal("1e30"),
    })
    result = propose(bounded, portfolio(cash=Decimal("1e15")), (value,))
    assert result.targets[0].target_shares == 10**15
    assert result.search_audit.evaluations < 100


def test_existing_odd_lot_remainder_can_receive_whole_lot_additions_to_the_value_cap():
    held = Position(symbol="A", account_bucket_id="bucket", shares=137,
                    average_acquisition_price=Decimal(900), market_price=Decimal(1000))
    _, bounded = engines()
    result = propose(bounded, portfolio((held,), cash=Decimal(200000)), (candidate("A", .3),))
    assert result.targets[0].target_shares == 337
    assert result.lines[0].share_difference == 200


def test_shared_symbol_concentration_and_nisa_purchase_limits_cover_both_accounts():
    state = portfolio(cash=Decimal(100000))
    state = state.model_copy(update={
        "accounts": (*state.accounts, state.accounts[0].model_copy(update={"account_id": "nisa"})),
        "account_buckets": (*state.account_buckets, state.account_buckets[0].model_copy(update={
            "bucket_id": "nisa", "account_id": "nisa", "account_type": AccountType.NISA,
            "withholding_mode": WithholdingMode.NOT_APPLICABLE,
        })),
        "cash": (*state.cash, state.cash[0].model_copy(update={"account_bucket_id": "nisa"})),
        "tax_states": (*state.tax_states, state.tax_states[0].model_copy(update={
            "account_bucket_id": "nisa", "nisa_annual_capacity_user_input": Decimal(50000),
            "nisa_lifetime_capacity_user_input": Decimal(50000),
        })),
    })
    exact, bounded = engines()
    for engine in (exact, bounded):
        engine.config = engine.config.model_copy(update={"maximum_symbol_weight": Decimal(".5")})
    values = tuple(candidate(symbol, signal, bucket=bucket)
                   for symbol, signal in (("A", .3), ("B", .2)) for bucket in ("bucket", "nisa"))
    reference, result = (propose(engine, state, values, purchase_limits={"nisa": Decimal(50000)})
                         for engine in (exact, bounded))
    assert result.targets == reference.targets
    assert {(x.symbol, x.account_bucket_id): x.target_shares for x in result.targets
            if x.target_shares} == {("A", "bucket"): 100}
    assert result.search_audit.candidate_key_count == 4


def test_exhausted_budget_keeps_feasible_improvement_and_full_candidate_coverage(monkeypatch):
    from stock_ai.decision import bounded as implementation

    monkeypatch.setattr(implementation, "EVALUATION_BUDGET", 1000)
    state, values, _, bounded = large_scenario()
    result = propose(bounded, state, values)
    assert result.search_audit.budget_exhausted
    assert result.search_audit.evaluations <= 1000
    assert result.search_audit.considered_key_count == 301
    assert result.proposed_utility >= result.hold_utility
    assert result.estimated_cash_after["bucket"] >= 100000
    assert sum(x.target_shares > 0 for x in result.targets) <= 9


@pytest.mark.parametrize("seed", range(8))
def test_small_cost_and_tax_scenarios_are_compared_with_exhaustive_oracle(seed):
    fixture = Random(seed)
    costs = CostPolicy(policy_id="cost-v1", version="nonzero-fixture", commission_fixed=Decimal(70),
                       full_spread_bps=Decimal(10), slippage_bps=Decimal(5),
                       impact_bps_at_full_adv=Decimal(25))
    positions = (Position(symbol="A", account_bucket_id="bucket", shares=100,
                         average_acquisition_price=Decimal(700), market_price=Decimal(1000)),)
    state = portfolio(positions, cash=Decimal(220000))
    values = tuple(candidate(symbol, fixture.choice((-.1, .05, .15, .3)))
                   for symbol in ("A", "B", "C"))
    exact, bounded = engines(cost_policy=costs, tax_rate=Decimal(".2"))
    reference, result = (propose(engine, state, values) for engine in (exact, bounded))
    assert result.targets == reference.targets
    assert result.proposed_utility == reference.proposed_utility
    assert result.estimated_cash_after == reference.estimated_cash_after
