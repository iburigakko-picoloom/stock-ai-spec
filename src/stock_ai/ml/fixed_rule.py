"""Common top-N allocation for research; reuse the stateful NAV ledger."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from stock_ai.domain import TradeSide
from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.nav import (
    NavDecisionState,
    NavInput,
    NavModel,
    NavOrder,
    NavResult,
    evaluate_stateful_nav,
    fixed_bps_policy,
)
from stock_ai.operations.daily import content_id


class FixedRulePolicy(NavModel):
    version: Literal["daily-top20-equal-research-v1"] = "daily-top20-equal-research-v1"
    horizon: Literal[5, 20]
    initial_cash_yen: Decimal = Field(default=Decimal("10000000"), gt=0, allow_inf_nan=False)
    top_n: Annotated[int, Field(strict=True, gt=0)] = 20
    invested_fraction: Decimal = Field(default=Decimal("0.9"), gt=0, le=1, allow_inf_nan=False)
    lot_size: Annotated[int, Field(strict=True, gt=0)] = 100
    one_way_bps: Decimal = Field(default=Decimal("20"), ge=0, allow_inf_nan=False)
    rebalance: Literal["every_horizon_sessions"] = "every_horizon_sessions"


class FixedSignalDay(NavModel):
    as_of: datetime
    available_at: datetime
    reference_price_at: datetime
    horizon: Literal[5, 20]
    score_unit: Literal["fractional_return", "ranking_score"]
    scores: tuple[tuple[str, float], ...]
    reference_prices: tuple[tuple[str, Decimal], ...]
    source_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def causal(self) -> FixedSignalDay:
        if self.available_at > self.as_of or self.reference_price_at > self.as_of:
            raise ValueError("fixed-rule inputs are not available at the decision cutoff")
        symbols = [s for s, _ in self.scores]
        prices = dict(self.reference_prices)
        if (
            not symbols
            or len(symbols) != len(set(symbols))
            or len(prices) != len(self.reference_prices)
            or not set(symbols) <= set(prices)
            or any(not math.isfinite(v) for _, v in self.scores)
            or any(not p.is_finite() or p <= 0 for p in prices.values())
        ):
            raise ValueError("fixed-rule scores/prices must have complete unique finite keys")
        return self


class FixedRuleRequest(NavModel):
    evaluation_tier: Literal[
        "synthetic_accounting", "price_only_research", "dividend_inclusive_research"
    ] = "synthetic_accounting"
    policy: FixedRulePolicy
    accounting: NavInput
    signals: tuple[FixedSignalDay, ...]

    @model_validator(mode="after")
    def explicit_tier(self) -> FixedRuleRequest:
        if (self.evaluation_tier == "synthetic_accounting") != (
            self.accounting.data_mode == "fixture"
        ):
            raise ValueError("synthetic and historical evaluation tiers must remain separate")
        if self.evaluation_tier == "price_only_research" and any(
            e.kind == "dividend" for e in self.accounting.actions
        ):
            raise ValueError("price-only evaluation must not credit dividends")
        return self


def evaluate_fixed_rule(
    accounting: NavInput,
    signals: tuple[FixedSignalDay, ...],
    policy: FixedRulePolicy,
    *,
    exposure_guard: Callable[[NavDecisionState, tuple[NavOrder, ...]], None] | None = None,
) -> tuple[NavInput, NavResult, tuple[dict[str, object], ...]]:
    """Equal capital per top score; no overlapping label-return compounding.

    Buys use only currently released cash, never an unfilled sale. Missing held
    references stop the replay instead of removing the holding. Generated orders
    and unfilled quantities remain in the existing NAV receipt.
    """
    accounting = NavInput.model_validate(accounting.model_dump())
    signals = tuple(FixedSignalDay.model_validate(s.model_dump()) for s in signals)
    policy = FixedRulePolicy.model_validate(policy.model_dump())
    if (
        len(accounting.cash) != 1
        or accounting.positions
        or accounting.orders
        or accounting.cash[0].amount != policy.initial_cash_yen
        or accounting.cash[0].reserved != 0
        or accounting.lot_size != policy.lot_size
        or accounting.cost_policy != fixed_bps_policy(policy.one_way_bps)
        or len(signals) != len(accounting.sessions)
        or any(s.horizon != policy.horizon for s in signals)
    ):
        raise ValueError("fixed-rule accounting differs from the frozen research policy")
    bucket = accounting.cash[0].bucket
    by_time = {s.as_of: (i, s) for i, s in enumerate(signals)}
    if len(by_time) != len(signals):
        raise ValueError("duplicate fixed-rule signal times")
    decisions: list[dict[str, object]] = []

    def decide(state: NavDecisionState) -> tuple[NavOrder, ...]:
        index, signal = by_time[state.as_of]
        if index % policy.horizon:
            if exposure_guard is not None:
                exposure_guard(state, ())
            return ()
        prices = dict(signal.reference_prices)
        held = {p.symbol: p.shares for p in state.positions}
        if set(held) - set(prices):
            raise ValueError("missing held reference; cannot silently exclude a holding")
        prior = accounting.initial_as_of if index == 0 else accounting.sessions[index - 1].close_at
        if signal.reference_price_at < prior:
            raise ValueError("stale reference price")
        affected = {a.event_id: a for a in accounting.actions}
        if any(
            affected[e].symbol in prices
            and affected[e].kind != "dividend"
            and affected[e].effective_at > signal.reference_price_at
            for e in state.applied_event_ids
        ):
            raise ValueError("reference predates a share-changing corporate action")
        ranked = sorted(signal.scores, key=lambda x: (-x[1], x[0]))[: policy.top_n]
        # Receivables remain in NAV but cannot be deployed before their release.
        cash = sum((c.amount - c.reserved for c in state.cash), Decimal(0))
        wealth = cash + sum((prices[s] * q for s, q in held.items()), Decimal(0))
        per_symbol = wealth * policy.invested_fraction / policy.top_n
        targets = {
            s: int(per_symbol // (prices[s] * policy.lot_size)) * policy.lot_size for s, _ in ranked
        }
        orders = []
        for symbol in sorted(set(held) | set(targets)):
            delta = targets.get(symbol, 0) - held.get(symbol, 0)
            if not delta:
                continue
            # Do not fund buys from the simultaneous requested sales. Leave
            # reserve for the declared all-in bps cost. The ledger checks fills
            # against actual execution prices/capacity and released funds again.
            if delta > 0:
                affordable = (
                    int(
                        cash
                        // (prices[symbol] * policy.lot_size * (1 + policy.one_way_bps / 10000))
                    )
                    * policy.lot_size
                )
                delta = min(delta, affordable)
                cash -= prices[symbol] * delta * (1 + policy.one_way_bps / 10000)
            if delta:
                orders.append(
                    NavOrder(
                        order_id=f"fixed-{index}-{symbol}",
                        trading_date=accounting.sessions[index].trading_date,
                        decided_at=state.as_of,
                        symbol=symbol,
                        bucket=bucket,
                        side=TradeSide.BUY if delta > 0 else TradeSide.SELL,
                        shares=abs(delta),
                    )
                )
        decisions.append(
            {
                "as_of": state.as_of.isoformat(),
                "ranked_symbols": [s for s, _ in ranked],
                "source_id": signal.source_id,
                "target_shares": targets,
                "orders": [o.model_dump(mode="json") for o in orders],
            }
        )
        if exposure_guard is not None:
            exposure_guard(state, tuple(orders))
        return tuple(orders)

    realized, result = evaluate_stateful_nav(
        accounting, decision_times=[s.as_of for s in signals], decide=decide
    )
    return realized, result, tuple(decisions)


def write_fixed_rule(request: FixedRuleRequest, root: Path) -> Path:
    from stock_ai.ml.nav import evaluate_daily_nav

    started = perf_counter()
    realized, result, decisions = evaluate_fixed_rule(
        request.accounting, request.signals, request.policy
    )
    cash = evaluate_daily_nav(request.accounting)
    receipt = {
        "schema_version": "daily-fixed-rule-result-v1",
        "research_only": True,
        "evaluation_tier": request.evaluation_tier,
        "adoption_eligible": False,
        "tax_mode": "pre_tax",
        "no_order_sent": True,
        "market_evidence_certified": False,
        "evidence_scope": "Explicit accounting inputs; not a certified market-data evaluation",
        "policy_sha256": content_id(request.policy.model_dump(mode="json")),
        "input": request.model_dump(mode="json"),
        "realized_accounting": realized.model_dump(mode="json"),
        "strategy": result.model_dump(mode="json"),
        "cash": cash.model_dump(mode="json"),
        "decisions": decisions,
        "elapsed_seconds": perf_counter() - started,
        "implementation_sha256": {
            name: file_digest(Path(__file__).with_name(name))
            for name in ("fixed_rule.py", "nav.py")
        },
    }
    return write_audit_receipt(receipt, root)


def file_digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
