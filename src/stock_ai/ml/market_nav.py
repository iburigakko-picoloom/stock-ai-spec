"""Connect pinned, development-only raw market receipts to the existing NAV ledger.

Execution and corporate-action evidence are independent inputs. A daily bar, a
unit adjustment factor, or an empty event list never supplies that evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from stock_ai.ml.daily_oof import DailyOofDay
from stock_ai.ml.daily_strategy import DailyStrategyInput, evaluate_daily_strategy
from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.nav import JST, NavModel
from stock_ai.ml.selection import load_development_feature_selection


class PinnedEvidence(NavModel):
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def read(self) -> bytes:
        encoded = self.path.read_bytes()
        if hashlib.sha256(encoded).hexdigest() != self.sha256:
            raise ValueError(f"evidence bytes changed: {self.path}")
        return encoded


class MarketReceipt(PinnedEvidence):
    # Check the declared boundary before opening the file, then check its envelope.
    start: date
    end: date


class ForecastReceipt(PinnedEvidence):
    as_of: datetime


class ActionCoverage(NavModel):
    symbol: str = Field(min_length=1)
    start_at: datetime
    end_at: datetime
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: Literal[
        "splits_dividends_cash_conversions_and_other_rights_reviewed",
        "splits_cash_conversions_and_other_rights_reviewed_excluding_dividends",
    ]
    # All events found in the declared scope, including a reviewed empty set.
    event_ids: tuple[str, ...]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_at < self.start_at or len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("invalid corporate-action coverage interval or event IDs")
        return self


class MarketStrategyRequest(NavModel):
    schema_version: Literal["market-nav-request-v1"] = "market-nav-request-v1"
    # Preserve the stronger historical contract unless price-only is explicit.
    evaluation_tier: Literal[
        "price_only_research", "dividend_inclusive_research"
    ] = "dividend_inclusive_research"
    feature_selection_path: Path
    strategy: DailyStrategyInput
    market_receipts: tuple[MarketReceipt, ...]
    forecast_receipts: tuple[ForecastReceipt, ...] = ()
    evidence_sources: tuple[PinnedEvidence, ...] = ()
    action_coverage: tuple[ActionCoverage, ...] = ()
    # These pin the reviewed source evidence, not a claim of vendor certification.
    decision_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    execution_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    cost_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def explicit_dividend_treatment(self) -> Self:
        if self.evaluation_tier == "price_only_research" and any(
            event.kind == "dividend" for event in self.strategy.accounting.actions
        ):
            raise ValueError("price-only evaluation must not credit dividend events")
        return self


def profile_market_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Inventory known price capability without filtering on future performance."""
    counts: Counter[str] = Counter()
    symbols: set[str] = set()
    dates: set[str] = set()
    adjustment_symbols: set[str] = set()
    for row in rows:
        counts["rows"] += 1
        dates.add(str(row["trading_date"]))
        counts[str(row["bar_state"])] += 1
        if row.get("symbol_status") != "standard_equity_code":
            counts["nonstandard_code_rows"] += 1
        elif row.get("symbol"):
            symbols.add(str(row["symbol"]))
        if row["adjustment_requires_event_evidence"]:
            counts["adjustment_rows"] += 1
            if row.get("symbol"):
                adjustment_symbols.add(str(row["symbol"]))
    return {
        "counts": dict(counts), "dates": sorted(dates), "symbols": sorted(symbols),
        "adjustment_symbols": sorted(adjustment_symbols),
        "price_observations_are_not_execution_or_action_coverage": True,
    }


def _market_rows(request: MarketStrategyRequest) -> dict[tuple[date, str], dict[str, Any]]:
    features = load_development_feature_selection(request.feature_selection_path)
    boundary = date.fromisoformat(features.locked_holdout_start)
    accounting = request.strategy.accounting
    if accounting.calendar_dates[-1] >= boundary:
        raise ValueError("market NAV reaches the locked holdout")
    if any(
        o.forecasts.data_snapshot_id != features.data_snapshot_id
        for o in request.strategy.observations
    ):
        raise ValueError("forecast differs from the frozen development data snapshot")
    for ref in request.market_receipts:
        if ref.start > ref.end or ref.end >= boundary:
            raise ValueError("market receipt reaches the locked holdout or reverses its window")
    for forecast in request.forecast_receipts:
        if forecast.as_of.astimezone(JST).date() >= boundary:
            raise ValueError("forecast receipt reaches the locked holdout")
    rows: dict[tuple[date, str], dict[str, Any]] = {}
    for ref in request.market_receipts:
        receipt = json.loads(ref.read())
        envelope = receipt["request"]
        if (
            receipt["schema_version"] != "daily-market-projection-v1"
            or receipt["price_basis"] != "unadjusted"
            or receipt["locked_holdout_start"] != features.locked_holdout_start
            or receipt["feature_selection_id"] != features.feature_selection_id
            or receipt["data_snapshot_id_declared_by_features"] != features.data_snapshot_id
            or receipt["holdout_rows_read"] is not False
            or envelope["start"] != ref.start.isoformat()
            or envelope["end"] != ref.end.isoformat()
        ):
            raise ValueError("market receipt identity, raw price basis or window differs")
        for row in receipt["rows"]:
            trading_date = date.fromisoformat(row["trading_date"])
            if not ref.start <= trading_date <= ref.end:
                raise ValueError("market row outside its pinned development window")
            if row.get("symbol_status") != "standard_equity_code":
                continue
            key = trading_date, row["symbol"]
            if key in rows:
                raise ValueError("duplicate market key across receipts")
            rows[key] = row
    return rows


def evaluate_market_strategy(request: MarketStrategyRequest) -> dict[str, Any]:
    """Return a measured blocked receipt, or replay the existing strategy and HOLD.

    Bar availability is not backdated. Closing outcomes may be received later;
    that does not make them valid decision inputs. The independently reviewed
    decision evidence must establish the forecasts, membership and reference
    prices available at the historical freeze.
    """
    started = perf_counter()
    request = MarketStrategyRequest.model_validate(request.model_dump())
    rows = _market_rows(request)
    accounting = request.strategy.accounting
    if accounting.data_mode != "historical_research":
        raise ValueError("market NAV requires explicit historical research mode")
    source_hashes = set()
    for source in request.evidence_sources:
        source.read()
        source_hashes.add(source.sha256)
    problems: set[str] = set()
    saved_forecasts: dict[datetime, DailyOofDay] = {}
    for ref in request.forecast_receipts:
        day = DailyOofDay.model_validate(json.loads(ref.read())["day"])
        if day.as_of != ref.as_of or day.as_of in saved_forecasts:
            raise ValueError("saved forecast timestamp differs or is duplicated")
        saved_forecasts[day.as_of] = day
    for observation in request.strategy.observations:
        saved = saved_forecasts.get(observation.forecasts.as_of)
        if saved is None:
            problems.add("SAVED_FORECAST_RECEIPTS")
        elif saved != observation.forecasts:
            raise ValueError("strategy forecasts differ from the saved predictions")
    for label, digest in (
        ("DECISION_POINT_IN_TIME_EVIDENCE", request.decision_evidence_sha256),
        ("EXECUTION_SETTLEMENT_EVIDENCE", request.execution_evidence_sha256),
        ("COST_POLICY_EVIDENCE", request.cost_evidence_sha256),
    ):
        if digest is None or digest not in source_hashes:
            problems.add(label)
    if not request.market_receipts:
        problems.add("RAW_MARKET_RECEIPTS")
    required = {p.symbol for p in accounting.positions}
    for observation in request.strategy.observations:
        required.update(observation.candidate_symbols)
    for position in accounting.positions:
        row = rows.get((accounting.initial_as_of.astimezone(JST).date(), position.symbol))
        if row is None or row["raw_close"] is None:
            problems.add(f"{position.symbol}:INITIAL_RAW_VALUATION")
        elif position.last_price != Decimal(str(row["raw_close"])):
            raise ValueError("initial holding mark differs from the raw market price")
    coverage_by_symbol = {c.symbol: c for c in request.action_coverage}
    if len(coverage_by_symbol) != len(request.action_coverage):
        raise ValueError("duplicate corporate-action coverage symbol")
    actions = {event.event_id: event for event in accounting.actions}
    for symbol in required:
        coverage = coverage_by_symbol.get(symbol)
        if (
            coverage is not None
            and request.evaluation_tier == "dividend_inclusive_research"
            and coverage.scope != "splits_dividends_cash_conversions_and_other_rights_reviewed"
        ):
            problems.add(f"{symbol}:DIVIDEND_COVERAGE")
        expected = {
            key for key, event in actions.items() if event.symbol == symbol
            and accounting.initial_as_of < event.effective_at <= accounting.sessions[-1].close_at
        }
        if (
            coverage is None or coverage.evidence_sha256 not in source_hashes
            or coverage.start_at > accounting.initial_as_of
            or coverage.end_at < accounting.sessions[-1].close_at
            or set(coverage.event_ids) != expected
        ):
            problems.add(f"{symbol}:CORPORATE_ACTION_COVERAGE")
    observations_by_date = {
        o.forecasts.as_of.astimezone(JST).date(): o for o in request.strategy.observations
    }
    for session in accounting.sessions:
        quotes = {p.symbol: p for p in session.prices}
        # Future candidates need no quote before listing/first consideration.
        # Later held positions are checked by the stateful ledger's valuations.
        session_required = set(quotes) | set(
            observations_by_date[session.trading_date].candidate_symbols
        )
        for symbol in session_required:
            row = rows.get((session.trading_date, symbol))
            price = quotes.get(symbol)
            if row is None or price is None:
                problems.add(f"{symbol}:{session.trading_date}:MISSING_PRICE")
                continue
            close = row["raw_close"]
            if price.close_price != (None if close is None else Decimal(str(close))):
                raise ValueError("NAV close differs from the pinned unadjusted market price")
            if row["bar_state"] != "reported_trade" and price.execution_price is not None:
                raise ValueError("execution price contradicts an untraded/incomplete daily bar")
            if accounting.execution_semantics == "daily_close_research_proxy" and (
                price.execution_price != price.close_price
            ):
                raise ValueError("closing proxy execution differs from raw close")
            if price.buy_status == "unknown" or price.sell_status == "unknown":
                problems.add(f"{symbol}:{session.trading_date}:EXECUTION_STATUS")
            if price.capacity_shares is None:
                problems.add(f"{symbol}:{session.trading_date}:EXECUTION_CAPACITY")
            if row["adjustment_requires_event_evidence"]:
                factor = row.get("adjustment_factor")
                matching_split = any(
                    e.symbol == symbol and e.kind == "split"
                    and e.effective_at.astimezone(JST).date() == session.trading_date
                    and factor is not None
                    and Fraction(e.denominator, e.numerator) == Fraction(str(factor))
                    for e in accounting.actions
                )
                if not matching_split:
                    problems.add(f"{symbol}:{session.trading_date}:UNRESOLVED_ADJUSTMENT")
    receipt: dict[str, Any] = {
        "schema_version": "market-nav-result-v1", "research_only": True,
        "adoption_eligible": False, "tax_mode": "pre_tax", "no_order_sent": True,
        "holdout_scored": False, "input": request.model_dump(mode="json"),
        "evaluation_scope": "development_only",
        "evaluation_tier": request.evaluation_tier,
        "dividend_treatment": (
            "excluded_not_assumed_zero" if request.evaluation_tier == "price_only_research"
            else "included_requires_reviewed_coverage"
        ),
        "status": "BLOCKED" if problems else "COMPLETE", "blockers": sorted(problems),
        "comparison": None,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_sha256": {
            name: hashlib.sha256((Path(__file__).parents[1] / name).read_bytes()).hexdigest()
            for name in ("ml/daily_strategy.py", "ml/daily_oof.py", "ml/nav.py",
                         "decision/engine.py", "decision/costs.py", "decision/tax.py",
                         "domain/models.py", "ml/market_nav.py", "ml/selection.py")
        },
        "pydantic_version": version("pydantic"), "decimal_precision": 28,
        "evidence_scope": "Pinned local research evidence; not vendor certification or adoption.",
    }
    if not problems:
        result = evaluate_daily_strategy(request.strategy)
        receipt["comparison"] = result.model_dump(mode="json")
        if not result.decisions_complete:
            receipt["status"] = "BLOCKED"
            receipt["blockers"] = ["INCOMPLETE_DAILY_DECISIONS"]
        if not result.strategy.valuation_complete or not result.hold.valuation_complete:
            receipt["status"] = "BLOCKED"
            receipt["blockers"].append("INCOMPLETE_HELD_POSITION_VALUATIONS")
    receipt["elapsed_seconds"] = perf_counter() - started
    return receipt


def write_market_strategy(request: MarketStrategyRequest, root: Path) -> Path:
    return write_audit_receipt(evaluate_market_strategy(request), root)
