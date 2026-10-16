"""Versioned finite coordinate/exchange search, using the exact portfolio evaluator.

All money, bucket-level sale tax and hard constraints remain in engine._evaluate.
Only zero-target, unheld keys are omitted from trial scoring. The selected result
is expanded and checked with the full universe by the caller. No optimality claim.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from stock_ai.domain import AccountBucket, PortfolioState
from stock_ai.domain.models import BoundedSearchAudit

if TYPE_CHECKING:
    from stock_ai.decision.engine import (
        DailyPortfolioDecisionEngine,
        DecisionCandidate,
        _Evaluation,
    )

Key = tuple[str, str]
EVALUATION_BUDGET = 32_768
COORDINATE_PASSES = 3
EXCHANGE_PASSES = 2


class _BudgetReached(Exception):
    pass


def search(
    engine: DailyPortfolioDecisionEngine, portfolio: PortfolioState,
    candidates: dict[Key, DecisionCandidate], buckets: dict[str, AccountBucket],
    wealth: Decimal, hold: _Evaluation, maximum_invested_value: Decimal | None,
    purchase_limits: Mapping[str, Decimal] | None,
) -> tuple[_Evaluation, BoundedSearchAudit]:
    from stock_ai.decision.engine import SearchSpaceTooLarge

    current = portfolio.position_map()
    lot = engine.config.lot_size
    keys = tuple(candidates)
    if len(keys) + 3 > EVALUATION_BUDGET:
        raise SearchSpaceTooLarge("bounded search cannot cover every symbol/account key")
    hold = replace(hold, targets={key: value for key, value in hold.targets.items()
                                 if value or key in current})
    rates = {key: engine._signal_utility(candidate, lot) / (candidate.price * lot)
             for key, candidate in candidates.items()}
    ordered = sorted(keys, key=lambda key: (
        0 if key in current and rates[key] < 0 else 1, -rates[key], key,
    ))
    bounds = {}
    for key, candidate in candidates.items():
        original = current[key].shares if key in current else 0
        cap = wealth * engine.config.maximum_symbol_weight
        if maximum_invested_value is not None:
            cap = min(cap, maximum_invested_value)
        remainder = original % lot
        upper = max(original, remainder + max(0, int(
            (cap / candidate.price - remainder) // lot
        )) * lot)
        capacity = (0 if candidate.average_daily_trading_value is None else int(
            candidate.average_daily_trading_value * engine.config.maximum_trade_adv_ratio
            // (candidate.price * lot)
        ) * lot)
        lower = max(remainder, original - capacity)
        upper = min(upper, original + capacity)
        upper = remainder + max(0, (upper - remainder) // lot) * lot
        bounds[key] = (lower, upper, remainder)

    cache: OrderedDict[tuple[tuple[Key, int], ...], _Evaluation | None] = OrderedDict()
    cache_limit = max(1, min(512, 16_384 // (len(current) + engine.config.maximum_positions + 1)))
    evaluations = hits = passes = 0
    exhausted = False
    considered: set[Key] = set()
    hold_key = tuple(sorted(hold.targets.items()))

    def prefer(result: _Evaluation | None, incumbent: _Evaluation) -> bool:
        if result is None or result.utility < incumbent.utility:
            return False
        if result.utility > incumbent.utility:
            return True
        return tuple(result.targets.get(key, 0) for key in keys) < tuple(
            incumbent.targets.get(key, 0) for key in keys
        )

    def attempt(targets: dict[Key, int], limit: int) -> _Evaluation | None:
        nonlocal evaluations, hits, exhausted
        identity = tuple(sorted(targets.items()))
        if identity == hold_key:
            hits += 1
            return hold
        if identity in cache:
            hits += 1
            cache.move_to_end(identity)
            return cache[identity]
        if evaluations >= min(limit, EVALUATION_BUDGET):
            exhausted = True
            raise _BudgetReached
        evaluations += 1
        active = {key: candidates[key] for key in sorted(targets)}
        result = engine._evaluate(
            targets=targets, portfolio=portfolio, candidates=active, buckets=buckets,
            total_wealth=wealth, enforce_trade_constraints=True,
            maximum_invested_value=maximum_invested_value, purchase_limits=purchase_limits,
        )
        cache[identity] = result
        if len(cache) > cache_limit:
            cache.popitem(last=False)
        return result

    def changed(point: _Evaluation, changes: dict[Key, int]) -> dict[Key, int]:
        targets = dict(point.targets)
        for key, quantity in changes.items():
            if quantity or key in current:
                targets[key] = quantity
            else:
                targets.pop(key, None)
        return targets

    def options(point: _Evaluation, key: Key) -> list[int]:
        low, high, remainder = bounds[key]
        now = point.targets.get(key, 0)
        original = current[key].shares if key in current else 0
        # Nominal affordability adds useful intermediate targets. Actual fees,
        # withholding and shared purchase limits are checked by the evaluator.
        nominal = point.cash_after[key[1]] + candidates[key].price * now
        affordable = remainder + max(0, int(nominal // (candidates[key].price * lot))) * lot
        span = (high - low) // lot
        values = {low, high, original, now - lot, now + lot, affordable, affordable - lot,
                  *(low + (span * fraction // 4) * lot for fraction in (1, 2, 3))}
        values = {value for value in values if low <= value <= high
                  and value % lot == remainder and value != now}
        return sorted(values, reverse=rates[key] >= 0)

    def coordinate(point: _Evaluation, limit: int) -> _Evaluation:
        nonlocal passes
        for _ in range(COORDINATE_PASSES):
            passes += 1
            previous = point.targets
            for index, key in enumerate(ordered):
                remaining = len(ordered) - index
                allowance = max(1, min(24, (limit - evaluations) // max(1, remaining)))
                local_limit = min(limit, evaluations + allowance)
                best = point
                tried: dict[int, _Evaluation | None] = {}
                quantities = options(point, key)
                if not quantities:
                    considered.add(key)
                for quantity in quantities:
                    try:
                        result = attempt(changed(point, {key: quantity}), local_limit)
                    except _BudgetReached:
                        break
                    considered.add(key)
                    tried[quantity] = result
                    if prefer(result, best):
                        assert result is not None
                        best = result
                # Refine the affordable upper boundary when costs invalidate a
                # large target. Limit to twelve bisections; never round after scoring.
                feasible = [q for q, result in tried.items() if result is not None]
                if quantities and feasible and tried.get(max(quantities)) is None:
                    low, high = max(feasible), max(quantities)
                    for _ in range(12):
                        if high - low <= lot:
                            break
                        middle = low + ((high - low) // (2 * lot)) * lot
                        try:
                            result = attempt(changed(point, {key: middle}), local_limit)
                        except _BudgetReached:
                            break
                        if result is None:
                            high = middle
                        else:
                            low = middle
                            if prefer(result, best):
                                best = result
                point = best
            if point.targets == previous or evaluations >= limit:
                break
        return point

    def exchange(point: _Evaluation, limit: int) -> _Evaluation:
        nonlocal passes
        for _ in range(EXCHANGE_PASSES):
            passes += 1
            previous = point.targets
            sources = sorted((key for key, value in point.targets.items() if value > 0),
                             key=lambda key: (rates[key], key))
            for source in sources:
                quantity = point.targets.get(source, 0)
                low, _, remainder = bounds[source]
                reductions = sorted({low, quantity - lot,
                                     remainder + ((quantity - remainder) // (2 * lot)) * lot})
                for reduced in reductions:
                    if not low <= reduced < quantity:
                        continue
                    try:
                        sold = attempt(changed(point, {source: reduced}), limit)
                    except _BudgetReached:
                        return point
                    if sold is None:
                        continue
                    for target in ordered:
                        if target == source:
                            continue
                        for increase in options(sold, target):
                            if increase <= point.targets.get(target, 0):
                                continue
                            try:
                                result = attempt(changed(sold, {target: increase}), limit)
                            except _BudgetReached:
                                return point
                            if prefer(result, point):
                                assert result is not None
                                point = result
                                break
                        else:
                            continue
                        break
                    if point.targets.get(source, 0) != quantity:
                        break
            if point.targets == previous:
                break
        return point

    roots = [hold]
    cash_baseline: Literal["feasible", "infeasible", "not_regular_lot"] = "not_regular_lot"
    if all(position.shares % lot == 0 for position in current.values()):
        cash = attempt({key: 0 for key in current}, EVALUATION_BUDGET)
        cash_baseline = "infeasible" if cash is None else "feasible"
        if cash is not None and cash.targets != hold.targets:
            roots.append(cash)
    liquidation = attempt({key: bounds[key][0] for key in current}, EVALUATION_BUDGET)
    if liquidation is not None and all(liquidation.targets != root.targets for root in roots):
        roots.append(liquidation)
    best = hold
    for root in roots:
        if prefer(root, best):
            best = root
    roots = roots[:max(1, (EVALUATION_BUDGET - evaluations) // max(1, len(keys)))]
    for index, root in enumerate(roots):
        if prefer(root, best):
            best = root
        quota = evaluations + (EVALUATION_BUDGET - evaluations) // (len(roots) - index)
        point = coordinate(root, quota)
        if prefer(point, best):
            best = point
        point = exchange(point, quota)
        if prefer(point, best):
            best = point
    if len(considered) != len(keys):
        raise SearchSpaceTooLarge("bounded search did not cover every candidate key")
    audit = BoundedSearchAudit(
        candidate_key_count=len(keys), considered_key_count=len(considered),
        evaluation_budget=EVALUATION_BUDGET, evaluations=evaluations, cache_hits=hits,
        passes=passes, budget_exhausted=exhausted, cash_baseline=cash_baseline,
    )
    return best, audit
