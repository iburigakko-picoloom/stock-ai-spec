"""Research-only, fixed-target comparison using 20-day return predictions.

This is not connected to the application or an adoption path. Missing risk is
never represented as zero: the comparison is explicitly return-only, and the
caller must supply alternatives rather than treating this as an optimizer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_ai.decision.engine import (
    DailyPortfolioDecisionEngine,
    TradeConstraintCandidate,
    _Evaluation,
)
from stock_ai.domain import AccountType, PortfolioState, WithholdingMode
from stock_ai.operations.daily import PredictionSnapshot, require_daily_close_label

Key = tuple[str, str]


@dataclass(frozen=True)
class ResearchComparison:
    """Estimated signals and costs, not an order or a risk-adjusted utility."""

    hold_score_yen: Decimal
    alternative_score_yen: Decimal | None
    improvement_yen: Decimal | None
    violations: tuple[str, ...]
    research_only: bool = True
    risk_evaluated: bool = False
    source_provenance_authenticated: bool = False


def compare_fixed_targets(
    *,
    portfolio: PortfolioState,
    snapshot: PredictionSnapshot,
    candidates: tuple[TradeConstraintCandidate, ...],
    targets: Mapping[Key, int],
    evaluated_at: datetime,
    engine: DailyPortfolioDecisionEngine,
    maximum_invested_value: Decimal | None,
    purchase_limits: Mapping[str, Decimal] | None = None,
) -> ResearchComparison:
    """Compare one complete fixed alternative to HOLD using existing cost/constraint code."""
    snapshot = PredictionSnapshot.model_validate_json(snapshot.model_dump_json())
    portfolio = PortfolioState.model_validate_json(portfolio.model_dump_json())
    require_daily_close_label(snapshot.label_definition)
    if (
        evaluated_at.tzinfo is None
        or evaluated_at.utcoffset() is None
        or evaluated_at < snapshot.generated_at
    ):
        raise ValueError("evaluation must be at or after forecast creation")
    cutoff = snapshot.as_of.astimezone(ZoneInfo("Asia/Tokyo"))
    if (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) != (11, 30, 0, 0):
        raise ValueError("forecast must use the 11:30 JST cutoff")
    if snapshot.mode != "research" or snapshot.blocking_reasons:
        raise ValueError("unblocked research snapshot required")
    if portfolio.as_of != snapshot.as_of:
        raise ValueError("portfolio and prediction cutoff must match")
    if engine.config.horizon_weights != (Decimal(0), Decimal(0), Decimal(1)):
        raise ValueError("research comparison uses the 20-day return only")
    if engine.tax_engine.policy.effective_from > portfolio.as_of.date():
        raise ValueError("tax policy is not effective at cutoff")
    if (
        maximum_invested_value is None
        or not maximum_invested_value.is_finite()
        or maximum_invested_value < 0
    ):
        raise ValueError("finite investment budget required")
    candidate_map = {c.key: c for c in candidates}
    if len(candidate_map) != len(candidates) or set(targets) != set(candidate_map):
        raise ValueError("targets and candidate keys must match exactly")
    current = portfolio.position_map()
    if {p.symbol for p in portfolio.positions if p.shares} != set(snapshot.holding_symbols):
        raise ValueError("snapshot holdings differ from portfolio")
    if {key[0] for key in candidate_map} != {p.symbol for p in snapshot.predictions}:
        raise ValueError("all forecast symbols must be covered")
    if set(current) - set(candidate_map):
        raise ValueError("all holdings must be covered")
    buckets = {b.bucket_id: b for b in portfolio.account_buckets}
    predictions = {p.symbol: p for p in snapshot.predictions}
    metadata: dict[str, tuple[Decimal, str, int]] = {}
    if purchase_limits is not None and (
        set(purchase_limits) - set(buckets)
        or any(not v.is_finite() or v < 0 for v in purchase_limits.values())
    ):
        raise ValueError("invalid account purchase limits")
    for key, item in candidate_map.items():
        if key[1] not in buckets or key[0] not in predictions:
            raise ValueError("unknown bucket or missing prediction")
        bucket = buckets[key[1]]
        value = targets[key]
        held = current.get(key)
        shares = held.shares if held else 0
        if type(value) is not int or value < 0 or (value - shares) % item.security.lot_size:
            raise ValueError("targets must use nonnegative whole-lot differences")
        if item.security.lot_size != engine.config.lot_size:
            raise ValueError("lot size differs from policy")
        if held and held.market_price != item.price:
            raise ValueError("current price must match candidate price")
        if (
            bucket.fee_policy_id != engine.cost_engine.policy.policy_id
            or bucket.tax_policy_id != engine.tax_engine.policy.policy_id
        ):
            raise ValueError("account policy mismatch")
        if (
            bucket.account_type is AccountType.UNKNOWN_MANUAL
            or bucket.withholding_mode is WithholdingMode.UNKNOWN
        ):
            raise ValueError("unconfirmed account cannot be evaluated")
        if (
            key[1] not in portfolio.tax_state_map()
            or key[1] not in portfolio.cash_map()
            or portfolio.tax_state_map()[key[1]].tax_year != portfolio.as_of.year
        ):
            raise ValueError("current tax state is required")
        if bucket.account_type is AccountType.NISA:
            tax_state = portfolio.tax_state_map()[key[1]]
            if (
                purchase_limits is None
                or key[1] not in purchase_limits
                or tax_state.nisa_annual_capacity_user_input is None
                or tax_state.nisa_lifetime_capacity_user_input is None
            ):
                raise ValueError("confirmed NISA purchase limits are required")
            if purchase_limits[key[1]] > min(
                tax_state.nisa_annual_capacity_user_input,
                tax_state.nisa_lifetime_capacity_user_input,
            ):
                raise ValueError("NISA purchase limit exceeds confirmed capacity")
        signature = (item.price, item.security.sector, item.security.lot_size)
        if metadata.setdefault(key[0], signature) != signature:
            raise ValueError("inconsistent same-symbol market information")
        if predictions[key[0]].expected_return_20d is None:
            raise ValueError("20-day return is unavailable; ranking score is not a return")
    wealth = sum((p.market_value for p in portfolio.positions), Decimal(0)) + sum(
        (c.deployable_cash for c in portfolio.cash), Decimal(0)
    )
    hold_targets = {key: current[key].shares if key in current else 0 for key in candidate_map}

    def evaluate(values: Mapping[Key, int], trade: bool) -> tuple[_Evaluation | None, list[str]]:
        violations: list[str] = []
        result = engine._evaluate(
            targets=dict(values),
            portfolio=portfolio,
            candidates=candidate_map,
            buckets=buckets,
            total_wealth=wealth,
            enforce_trade_constraints=trade,
            maximum_invested_value=maximum_invested_value,
            purchase_limits=purchase_limits,
            constraint_violations=violations,
            constraints_only=True,
        )
        return result, violations

    hold, _ = evaluate(hold_targets, False)
    if hold is None:
        raise ValueError("HOLD cannot be evaluated")
    alternative, violations = evaluate(targets, dict(targets) != hold_targets)
    if alternative is not None:
        # Sale proceeds are not treated as already available purchasing power.
        for bucket_id, cash in portfolio.cash_map().items():
            buys = sum(
                (
                    candidate_map[k].price * (targets[k] - hold_targets[k])
                    + alternative.costs[k].total
                    for k in candidate_map
                    if k[1] == bucket_id and targets[k] > hold_targets[k]
                ),
                Decimal(0),
            )
            if buys > cash.deployable_cash:
                violations.append("PURCHASE_REQUIRES_UNSETTLED_SALE")
                alternative = None
                break

    def score(result: _Evaluation) -> Decimal:
        gross = sum(
            (
                item.price
                * result.targets[key]
                * Decimal(str(predictions[key[0]].expected_return_20d))
                for key, item in candidate_map.items()
            ),
            Decimal(0),
        )
        return gross + result.utility

    hold_score = score(hold)
    alternative_score = None if alternative is None else score(alternative)
    return ResearchComparison(
        hold_score,
        alternative_score,
        None if alternative_score is None else alternative_score - hold_score,
        tuple(violations),
    )
