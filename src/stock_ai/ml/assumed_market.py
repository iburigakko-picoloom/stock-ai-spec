"""Explicit assumption research over saved OOF and the existing fixed-rule NAV.

This entry never certifies execution, complete corporate actions or historical
vintages. The strict market-strategy entry and its defaults remain separate.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq

from stock_ai.ml.daily_market import DailyMarketRequest
from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.fixed_rule import FixedRuleRequest, evaluate_fixed_rule
from stock_ai.ml.market_nav import MarketReceipt, PinnedEvidence, read_market_receipts
from stock_ai.ml.nav import JST, NavDecisionState, NavModel, NavOrder, evaluate_daily_nav
from stock_ai.ml.research_funding import require_research_funding
from stock_ai.ml.selection import load_development_feature_selection
from stock_ai.operations.daily import content_id


class SavedScoreSource(PinnedEvidence):
    family: Literal["lightgbm", "xgboost", "catboost"]
    horizon: Literal[5, 20]
    seed: int
    task: Literal["regression", "ranking"]


class ResearchAssumptions(NavModel):
    version: Literal["daily-close-declared-assumptions-v1"]
    entitlement_basis: Literal["confirmed-current-Light-frozen-acquisition"]
    known_future_information_present: Literal[False]
    execution: Literal["reported-close-with-5pct-volume-capacity"]
    limit_touches: Literal["withhold-buy-on-UL-sell-on-LL"]
    action_scope: Literal["reported-splits-only-unreported-coverage-unverified"]
    revision_policy: Literal["single-as-revised-vintage-not-historical-known-at"]
    timing: Literal["saved-OOF-asof-after-feature-day-before-next-close-proxy"]
    split_factor_interpretation: Literal["small-rational-with-identical-float-representation"]


class AssumedMarketRequest(NavModel):
    schema_version: Literal["assumed-market-fixed-rule-request-v1"]
    assumptions: ResearchAssumptions
    feature_selection_path: Path
    frozen_source_manifest: PinnedEvidence
    candidate_registry: PinnedEvidence
    score_source: SavedScoreSource
    # A shared, fixed daily domain; never candidate-specific survivor filtering.
    eligible_universe: PinnedEvidence
    market_receipts: tuple[MarketReceipt, ...]
    instrument_receipts: tuple[PinnedEvidence, ...]
    research_funding_receipt: MarketReceipt
    rule: FixedRuleRequest


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reported_share_ratio(factor: Any) -> Fraction:
    """Resolve 1/3 represented as a float; never round an approximate factor."""
    value = float(factor)
    if not math.isfinite(value) or value <= 0 or value == 1:
        raise ValueError("invalid/non-event reported split factor")
    rational = Fraction(str(factor)).limit_denominator(10000)
    if float(rational) != value:
        raise ValueError("reported factor has no identical small-rational representation")
    return 1 / rational


def _scores(request: AssumedMarketRequest) -> dict[datetime, dict[str, float]]:
    source, signals = request.score_source, request.rule.signals
    registry = json.loads(request.candidate_registry.read())
    matches = [
        r
        for c in registry["candidates"]
        if (c["horizon"], c["family"], c["seed"]) == (source.horizon, source.family, source.seed)
        for r in c["authenticated_reports"].values()
        if Path(r["oof_path"]).resolve() == source.path.resolve()
        and r["oof_file_sha256"] == source.sha256
    ]
    if len(matches) != 1 or registry["status"] != "AUTHENTICATED_OOF":
        raise ValueError("score source is not the authenticated candidate OOF")
    if _sha(source.path) != source.sha256:
        raise ValueError("saved prediction bytes changed")
    timestamp_type = pq.ParquetFile(source.path).schema_arrow.field("as_of").type
    if not pa.types.is_timestamp(timestamp_type) or timestamp_type.tz is None:
        raise ValueError("saved prediction timestamps need an explicit timezone")
    table = pq.read_table(
        source.path,
        columns=[
            "symbol",
            "trading_date",
            "as_of",
            "horizon",
            "model_family",
            "task",
            "seed",
            "prediction",
        ],
        filters=[
            ("as_of", ">=", pa.scalar(signals[0].as_of, type=timestamp_type)),
            ("as_of", "<=", pa.scalar(signals[-1].as_of, type=timestamp_type)),
            ("horizon", "=", source.horizon),
            ("model_family", "=", source.family),
            ("seed", "=", source.seed),
            ("task", "=", source.task),
        ],
    )
    result: dict[datetime, dict[str, float]] = {}
    for row in table.to_pylist():
        at = row["as_of"]
        if row["trading_date"].date() >= at.astimezone(JST).date():
            raise ValueError("known future feature-day close in saved prediction")
        values = result.setdefault(at, {})
        if row["symbol"] in values:
            raise ValueError("duplicate saved prediction key")
        values[row["symbol"]] = row["prediction"]
    return result


def evaluate_assumed_market(request: AssumedMarketRequest) -> dict[str, Any]:
    with localcontext(Context(prec=28)):
        return _evaluate_assumed_market(request)


def _evaluate_assumed_market(request: AssumedMarketRequest) -> dict[str, Any]:
    started = perf_counter()
    request = AssumedMarketRequest.model_validate(request.model_dump())
    rule, source = request.rule, request.score_source
    accounting = rule.accounting
    if (
        rule.policy.initial_cash_yen != 10000000
        or rule.policy.top_n != 20
        or rule.policy.invested_fraction != Decimal("0.9")
        or rule.policy.lot_size != 100
        or rule.policy.one_way_bps not in (20, 40)
    ):
        raise ValueError("research policy differs from the fixed 10m/top20/90pct/100/20-or-40bps")
    features = load_development_feature_selection(request.feature_selection_path)
    boundary = date.fromisoformat(features.locked_holdout_start)
    # All declarations are checked before opening market, source, or score files.
    if (
        accounting.calendar_dates[-1] >= boundary
        or not rule.signals
        or any(s.as_of.astimezone(JST).date() >= boundary for s in rule.signals)
        or any(
            r.end >= boundary for r in (*request.market_receipts, request.research_funding_receipt)
        )
    ):
        raise ValueError("assumption research reaches the locked holdout")
    if (
        rule.evaluation_tier != "price_only_research"
        or accounting.data_mode != "historical_research"
        or accounting.execution_semantics != "daily_close_research_proxy"
        or any(a.kind != "split" for a in accounting.actions)
        or rule.policy.horizon != source.horizon
        or registry_feature_id(request) != features.feature_selection_id
    ):
        raise ValueError("assumption research requires the frozen price-only daily contract")
    schedule = json.loads(request.research_funding_receipt.read())
    funding_request = DailyMarketRequest.model_validate(schedule["request"])
    if (
        schedule["feature_selection_id"] != features.feature_selection_id
        or schedule["model_data_snapshot_id"] != features.data_snapshot_id
        or schedule["locked_holdout_start"] != features.locked_holdout_start
        or schedule["holdout_rows_read"] is not False
        or funding_request.start != request.research_funding_receipt.start
        or funding_request.end != request.research_funding_receipt.end
    ):
        raise ValueError("funding receipt identity or declared window differs")
    require_research_funding(accounting, schedule)
    rows = read_market_receipts(request.market_receipts, features, funding_request)
    frozen = json.loads(request.frozen_source_manifest.read())
    if frozen["snapshot_id"] != accounting.source_snapshot_id:
        raise ValueError("market source snapshot differs from declared input")
    pins = {o["object_id"]: o for o in frozen["objects"]}
    for ref in request.market_receipts:
        for obj in json.loads(ref.read())["source_objects"]:
            pin = pins.get(obj["object_id"])
            if pin is None or pin["parquet_sha256"] != obj["parquet_hash"]:
                raise ValueError("market object is outside the frozen permitted acquisition")
    scores = _scores(request)
    domains = json.loads(request.eligible_universe.read())["days"]
    instruments = {}
    for instrument_ref in request.instrument_receipts:
        proof = json.loads(instrument_ref.read())
        if (
            proof["schema_version"] != "daily-instrument-rules-v1"
            or proof["feature_selection_id"] != features.feature_selection_id
            or proof["holdout_rows_read"] is not False
            or proof["request"]["end"] >= features.locked_holdout_start
        ):
            raise ValueError("instrument receipt identity/window differs")
        for row in proof["rows"]:
            if row["symbol"]:
                instruments[(date.fromisoformat(row["trading_date"]), row["symbol"])] = row
    for action in accounting.actions:
        row = rows.get((action.effective_at.astimezone(JST).date(), action.symbol))
        if (
            row is None
            or row.get("ex_rights_type") not in ("1", "2")
            or row.get("adjustment_factor") in (None, 1)
            or Fraction(action.numerator, action.denominator)
            != reported_share_ratio(row["adjustment_factor"])
            or action.available_at != action.effective_at
            or action.source_id != "reported-split-assumption:" + row["source_record_hash"]
        ):
            raise ValueError("split action differs from the reported event/factor assumption")
    issues: list[dict[str, Any]] = []
    for index, (signal, session) in enumerate(zip(rule.signals, accounting.sessions, strict=True)):
        key = signal.as_of.isoformat()
        domain = domains[key]
        if any(
            instruments.get((session.trading_date, symbol), {}).get("round_lot_size") != 100
            for symbol in domain
        ):
            raise ValueError("common domain contains an unproven domestic 100-share instrument")
        observed = scores.get(signal.as_of, {})
        if len(domain) != len(set(domain)) or set(domain) - observed.keys():
            raise ValueError("common domain has duplicate or missing saved predictions")
        expected = sorted(((s, observed[s]) for s in domain), key=lambda x: (-x[1], x[0]))[
            : rule.policy.top_n
        ]
        if list(signal.scores) != expected:
            raise ValueError("signal differs from the saved OOF top-N on the common domain")
        if signal.score_unit != (
            "ranking_score" if source.task == "ranking" else "fractional_return"
        ):
            raise ValueError("ranking score and fractional return units differ")
        if signal.available_at != signal.as_of or signal.horizon != source.horizon:
            raise ValueError("saved OOF decision/availability differs")
        prior_at = (
            accounting.initial_as_of if index == 0 else accounting.sessions[index - 1].close_at
        )
        for symbol, value in signal.reference_prices:
            original = rows.get((prior_at.astimezone(JST).date(), symbol))
            expected_price = (
                None
                if original is None or original["raw_close"] is None
                else Decimal(str(original["raw_close"]))
            )
            for action in accounting.actions:
                if action.symbol == symbol and prior_at < action.effective_at <= signal.as_of:
                    if expected_price is not None:
                        expected_price = expected_price * action.denominator / action.numerator
            if expected_price is None or value != expected_price:
                raise ValueError("reference differs from the prior raw close/split transform")
        for price in session.prices:
            row = rows.get((session.trading_date, price.symbol))
            close = (
                None if row is None or row["raw_close"] is None else Decimal(str(row["raw_close"]))
            )
            if price.close_price != close:
                raise ValueError("accounting close differs from frozen raw price")
            reported = row is not None and row["bar_state"] == "reported_trade"
            if price.execution_price != (close if reported else None):
                raise ValueError("assumed execution contradicts reported daily trade")
            volume = None if row is None else row.get("raw_volume")
            capacity = (
                0
                if not reported or volume is None
                else int(Decimal(str(volume)) * Decimal("0.05") // accounting.lot_size)
                * accounting.lot_size
            )
            buy = "tradable" if reported else "unknown"
            sell = buy
            if row is not None and reported and row.get("intraday_upper_limit_reached") == 1:
                buy = "price_limit"
            if row is not None and reported and row.get("intraday_lower_limit_reached") == 1:
                sell = "price_limit"
            if (price.capacity_shares, price.buy_status, price.sell_status) != (
                capacity,
                buy,
                sell,
            ):
                raise ValueError("execution assumption differs from the frozen declared rule")
            if close is not None:
                instrument = instruments.get((session.trading_date, price.symbol), {})
                if (
                    instrument.get("round_lot_size") != 100
                    or instrument.get("tick_size") is None
                    or price.tick_size != Decimal(instrument["tick_size"])
                ):
                    raise ValueError("execution unit/tick differs from the existing dated rule")
    known_actions = {a.event_id: a for a in accounting.actions}

    def guard(state: NavDecisionState, orders: tuple[NavOrder, ...]) -> None:
        exposed = {p.symbol for p in state.positions} | {o.symbol for o in orders}
        day = state.as_of.astimezone(JST).date()
        for symbol in sorted(exposed):
            row = rows.get((day, symbol))
            if row is None:
                continue  # A missing mark remains unknown in the existing ledger.
            rights, factor = row.get("ex_rights_type"), row.get("adjustment_factor")
            needs = row["adjustment_requires_event_evidence"] or rights not in (None, "")
            try:
                ratio = reported_share_ratio(factor)
            except (ValueError, TypeError):
                ratio = None
            matched = any(
                a.symbol == symbol
                and a.effective_at.astimezone(JST).date() == day
                and factor is not None
                and Fraction(str(factor)) != 1
                and Fraction(a.numerator, a.denominator) == ratio
                for a in known_actions.values()
            )
            if needs and (rights not in (None, "", "1", "2") or not matched):
                amount = sum(
                    (p.shares * p.last_price for p in state.positions if p.symbol == symbol),
                    Decimal(0),
                )
                issues.append(
                    {
                        "symbol": symbol,
                        "date": str(day),
                        "related_held_value_yen": str(amount),
                        "reason": "KNOWN_UNRESOLVED_CORPORATE_ACTION",
                        "reported_type": rights,
                        "factor": factor,
                        "required_evidence": "dated share/cash treatment for this exposure",
                    }
                )
        if issues:
            raise ValueError("KNOWN_UNRESOLVED_CORPORATE_ACTION")

    receipt: dict[str, Any] = {
        "schema_version": "assumed-market-fixed-rule-result-v1",
        "evaluation_mode": "declared_assumptions_research",
        "research_only": True,
        "adoption_eligible": False,
        "holdout_scored": False,
        "no_order_sent": True,
        "input_sha256": content_id(request.model_dump(mode="json")),
        "policy_sha256": content_id(rule.policy.model_dump(mode="json")),
        "assumptions": request.assumptions.model_dump(mode="json"),
        "dividend_treatment": "excluded_not_assumed_zero",
        "tax_mode": "pre_tax",
        "not_actual_execution_reconstruction": True,
        "not_standalone_adoption_evidence": True,
        "unverified": [
            "unreported corporate-action coverage",
            "closing directional tradability",
            "actual execution capacity/costs",
            "historical revision/availability vintages",
        ],
        "status": "COMPLETE_ASSUMPTION_RESEARCH",
        "unresolved_exposures": issues,
        "strategy": None,
        "hold": None,
        "decisions": None,
        "source_sha256": {
            name: _sha(Path(__file__).with_name(name))
            for name in ("assumed_market.py", "market_nav.py", "fixed_rule.py", "nav.py")
        },
    }
    try:
        realized, result, decisions = evaluate_fixed_rule(
            accounting, rule.signals, rule.policy, exposure_guard=guard
        )
        hold = evaluate_daily_nav(accounting)
        navs = [d.nav for d in result.days]
        notional = sum((d.traded_notional for d in result.days), Decimal(0))
        mean_nav = sum((v for v in navs if v is not None), Decimal(0)) / len(navs)
        reasons = Counter(f.reason for d in result.days for f in d.fills if f.reason != "FILLED")
        receipt.update(
            strategy=result.model_dump(mode="json"),
            hold=hold.model_dump(mode="json"),
            decisions=decisions,
            generated_orders=[o.model_dump(mode="json") for o in realized.orders],
            metrics={
                "turnover_definition": "gross buy+sell filled notional / mean end-of-day NAV",
                "turnover": str(notional / mean_nav)
                if mean_nav and result.valuation_complete
                else None,
                "trading_cost_yen": str(result.total_trading_cost),
                "unfilled_reasons": dict(reasons),
                "orders": len(realized.orders),
                "sessions": len(result.days),
                "common_domain_rows": sum(len(v) for v in domains.values()),
                "hold_return_difference": None
                if result.total_return is None or hold.total_return is None
                else str(result.total_return - hold.total_return),
            },
        )
        if not result.valuation_complete:
            receipt["status"] = "INCOMPLETE"
    except ValueError as exc:
        receipt.update(status="INCOMPLETE", stopped_reason=str(exc))
    if _sha(source.path) != source.sha256:
        raise ValueError("saved predictions changed during replay")
    receipt["elapsed_seconds"] = perf_counter() - started
    return receipt


def registry_feature_id(request: AssumedMarketRequest) -> str:
    return str(json.loads(request.candidate_registry.read())["feature_selection_id"])


def write_assumed_market(request: AssumedMarketRequest, root: Path) -> Path:
    # Freeze the complete configuration before any result is calculated.
    plan = write_audit_receipt(
        {
            "schema_version": "assumed-market-frozen-input-v1",
            "input": request.model_dump(mode="json"),
        },
        root / "plans",
    )
    result = evaluate_assumed_market(request)
    result["frozen_input"] = {"path": str(plan), "sha256": _sha(plan)}
    return write_audit_receipt(result, root / "results")
