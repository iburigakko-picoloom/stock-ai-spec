from datetime import timedelta
from decimal import Decimal

import pytest

from stock_ai.decision import CostPolicy, DecisionEngineConfig
from stock_ai.decision.engine import TradeConstraintCandidate
from stock_ai.decision.research_comparison import compare_fixed_targets
from stock_ai.domain import Position
from stock_ai.domain.models import ResearchEnsemblePrediction
from stock_ai.operations.daily import PredictionSnapshot
from tests.conftest import AS_OF, account_components, candidate, decision_engine, portfolio


def fixture():
    predictions = tuple(
        ResearchEnsemblePrediction(
            symbol=symbol,
            as_of=AS_OF,
            model_version="m",
            feature_version="f",
            data_snapshot_id="d",
            expected_return_5d=0.02,
            expected_return_20d=value,
            rank_score_20d=rank,
        )
        for symbol, value, rank in (("A", 0.01, 100), ("B", 0.10, -100))
    )
    snapshot = PredictionSnapshot.create(
        schema_version="daily-prediction-snapshot-v2",
        as_of=AS_OF,
        generated_at=AS_OF + timedelta(minutes=1),
        data_as_of=AS_OF - timedelta(hours=1),
        selection_id="research",
        model_version="m",
        feature_version="f",
        data_snapshot_id="d",
        candidate_symbols=("B",),
        holding_symbols=("A",),
        predictions=predictions,
        large_loss_threshold=None,
        downside_quantile_alpha=None,
        risk_horizon=None,
    )
    holdings = (
        Position(
            symbol="A",
            account_bucket_id="bucket",
            shares=100,
            average_acquisition_price=Decimal("900"),
            market_price=Decimal("1000"),
        ),
    )
    account = portfolio(holdings, cash=Decimal("101000"))
    engine = decision_engine(
        cost_policy=CostPolicy(
            policy_id="cost-v1",
            version="cost-v1",
            commission_fixed=Decimal("100"),
            full_spread_bps=Decimal(0),
            slippage_bps=Decimal(0),
            impact_bps_at_full_adv=Decimal(0),
        )
    )
    engine.config = DecisionEngineConfig.daily().model_copy(
        update={
            "maximum_symbol_weight": Decimal(1),
            "maximum_sector_weight": Decimal(1),
            "minimum_cash_ratio": Decimal(0),
            "maximum_positions": 10,
        }
    )
    choices = tuple(
        TradeConstraintCandidate.model_validate(candidate(s, 0).model_dump(exclude={"prediction"}))
        for s in ("A", "B")
    )
    return account, snapshot, engine, choices


def compare(account, snapshot, engine, choices, targets):
    return compare_fixed_targets(
        portfolio=account,
        snapshot=snapshot,
        candidates=choices,
        targets=targets,
        evaluated_at=AS_OF + timedelta(minutes=2),
        engine=engine,
        maximum_invested_value=Decimal("200000"),
    )


def test_return_only_comparison_includes_cost_and_preserves_input():
    account, snapshot, engine, choices = fixture()
    before = account.model_dump_json(), snapshot.model_dump_json()
    result = compare(
        account, snapshot, engine, choices, {("A", "bucket"): 100, ("B", "bucket"): 100}
    )
    # 20-day return is 10%, despite the ranking score of -100; commission is 100 yen.
    assert result.hold_score_yen == Decimal("1000.00")
    assert result.improvement_yen == Decimal("9900.00")
    assert result.research_only and not result.risk_evaluated and result.violations == ()
    assert before == (account.model_dump_json(), snapshot.model_dump_json())


def test_do_not_use_sale_proceeds_for_purchase():
    account, snapshot, engine, choices = fixture()
    account = account.model_copy(
        update={"cash": (account.cash[0].model_copy(update={"available_cash": Decimal(0)}),)}
    )
    result = compare(account, snapshot, engine, choices, {("A", "bucket"): 0, ("B", "bucket"): 100})
    assert result.alternative_score_yen is None
    assert (
        "PURCHASE_REQUIRES_UNSETTLED_SALE" in result.violations
        or "INSUFFICIENT_CASH_AFTER_COST_TAX" in result.violations
    )


def test_reject_missing_holdings_and_non_lot_trade():
    account, snapshot, engine, choices = fixture()
    with pytest.raises(ValueError, match="all forecast symbols"):
        compare(account, snapshot, engine, choices[1:], {("B", "bucket"): 0})
    with pytest.raises(ValueError, match="whole-lot"):
        compare(account, snapshot, engine, choices, {("A", "bucket"): 99, ("B", "bucket"): 0})


def test_rank_score_does_not_replace_missing_20_day_return():
    account, snapshot, engine, choices = fixture()
    data = snapshot.model_dump(exclude={"snapshot_id"})
    data["predictions"] = tuple(
        prediction.model_copy(update={"expected_return_20d": None})
        for prediction in snapshot.predictions
    )
    no_return = PredictionSnapshot.create(**data)
    with pytest.raises(ValueError, match="ranking score is not a return"):
        compare(account, no_return, engine, choices, {("A", "bucket"): 100, ("B", "bucket"): 0})


def test_insufficient_cash_and_missing_liquidity_are_not_scored():
    account, snapshot, engine, choices = fixture()
    result = compare(
        account, snapshot, engine, choices, {("A", "bucket"): 100, ("B", "bucket"): 200}
    )
    assert result.improvement_yen is None and result.violations
    no_adv = (choices[0], choices[1].model_copy(update={"average_daily_trading_value": None}))
    result = compare(
        account, snapshot, engine, no_adv, {("A", "bucket"): 100, ("B", "bucket"): 100}
    )
    assert result.improvement_yen is None and "LIQUIDITY_UNKNOWN" in result.violations


def test_sale_includes_estimated_tax_as_well_as_cost():
    account, snapshot, _, choices = fixture()
    engine = decision_engine(
        cost_policy=CostPolicy(
            policy_id="cost-v1",
            version="cost-v1",
            commission_fixed=Decimal("100"),
            full_spread_bps=Decimal(0),
            slippage_bps=Decimal(0),
            impact_bps_at_full_adv=Decimal(0),
        ),
        tax_rate=Decimal("0.2"),
    )
    engine.config = DecisionEngineConfig.daily().model_copy(
        update={
            "maximum_symbol_weight": Decimal(1),
            "maximum_sector_weight": Decimal(1),
            "minimum_cash_ratio": Decimal(0),
            "maximum_positions": 10,
        }
    )
    result = compare(account, snapshot, engine, choices, {("A", "bucket"): 0, ("B", "bucket"): 0})
    # 1,000 expected return forgone, 100 commission and tax on the 9,900 gain.
    assert result.improvement_yen == Decimal("-3080.00")


def test_refuses_evaluation_before_forecast_exists():
    account, snapshot, engine, choices = fixture()
    with pytest.raises(ValueError, match="at or after forecast creation"):
        compare_fixed_targets(
            portfolio=account,
            snapshot=snapshot,
            candidates=choices,
            targets={("A", "bucket"): 100, ("B", "bucket"): 0},
            evaluated_at=AS_OF,
            engine=engine,
            maximum_invested_value=Decimal("200000"),
        )


def test_nisa_purchase_limit_cannot_exceed_confirmed_capacity():
    account, snapshot, engine, choices = fixture()
    owner, bucket, cash, tax = account_components(cash=Decimal("101000"), nisa=True)
    tax = tax.model_copy(
        update={
            "nisa_annual_capacity_user_input": Decimal("90000"),
            "nisa_lifetime_capacity_user_input": Decimal("80000"),
        }
    )
    account = account.model_copy(
        update={
            "accounts": (owner,),
            "account_buckets": (bucket,),
            "cash": (cash,),
            "tax_states": (tax,),
        }
    )
    kwargs = dict(
        portfolio=account,
        snapshot=snapshot,
        candidates=choices,
        targets={("A", "bucket"): 100, ("B", "bucket"): 100},
        evaluated_at=AS_OF + timedelta(minutes=2),
        engine=engine,
        maximum_invested_value=Decimal("200000"),
    )
    with pytest.raises(ValueError, match="confirmed NISA"):
        compare_fixed_targets(**kwargs)
    with pytest.raises(ValueError, match="exceeds confirmed"):
        compare_fixed_targets(**kwargs, purchase_limits={"bucket": Decimal("90000")})
    result = compare_fixed_targets(**kwargs, purchase_limits={"bucket": Decimal("80000")})
    assert result.improvement_yen is None and "ACCOUNT_PURCHASE_LIMIT" in result.violations
