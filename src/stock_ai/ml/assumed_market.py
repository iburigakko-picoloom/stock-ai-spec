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

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import model_validator

from stock_ai.ml.daily_market import DailyMarketRequest
from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.fixed_rule import FixedRuleRequest, evaluate_fixed_rule
from stock_ai.ml.market_nav import MarketReceipt, PinnedEvidence, read_market_receipts
from stock_ai.ml.nav import JST, NavAction, NavDecisionState, NavModel, NavOrder, evaluate_daily_nav
from stock_ai.ml.research_funding import require_research_funding
from stock_ai.ml.selection import load_development_feature_selection
from stock_ai.operations.daily import content_id


class SavedScoreSource(PinnedEvidence):
    family: Literal["lightgbm", "xgboost", "catboost"]
    horizon: Literal[5, 20]
    seed: int
    task: Literal["regression", "ranking", "rank_return", "rank_return_risk"]


class SavedBenchmarkSource(PinnedEvidence):
    kind: Literal["saved-benchmark"]
    horizon: Literal[5, 20]
    recipe: Literal["weighted_return", "momentum_20d"]
    receipt: PinnedEvidence
    authentication: PinnedEvidence

    @property
    def task(self) -> Literal["regression"]:
        return "regression"


class ResearchAssumptions(NavModel):
    version: Literal[
        "daily-close-declared-assumptions-v1", "daily-close-declared-assumptions-v2",
        "daily-close-declared-assumptions-v3",
    ]
    entitlement_basis: Literal["confirmed-current-Light-frozen-acquisition"]
    known_future_information_present: Literal[False]
    execution: Literal["reported-close-with-5pct-volume-capacity"]
    limit_touches: Literal["withhold-buy-on-UL-sell-on-LL"]
    action_scope: Literal[
        "reported-splits-only-unreported-coverage-unverified",
        "reported-splits-and-documented-cash-unreported-coverage-unverified",
    ]
    revision_policy: Literal["single-as-revised-vintage-not-historical-known-at"]
    timing: Literal["saved-OOF-asof-after-feature-day-before-next-close-proxy"]
    split_factor_interpretation: Literal["small-rational-with-identical-float-representation"]
    missing_held_reference: Literal["stop", "skip_rebalance"] = "stop"
    comparison_use: Literal[
        "original_frozen_comparison", "post_result_exploratory_sensitivity"
    ] = "original_frozen_comparison"

    @model_validator(mode="after")
    def explicit_sensitivity(self) -> ResearchAssumptions:
        expected = (
            ("stop", "original_frozen_comparison")
            if self.version == "daily-close-declared-assumptions-v1"
            else ("skip_rebalance", "post_result_exploratory_sensitivity")
        )
        if (self.missing_held_reference, self.comparison_use) != expected:
            raise ValueError("missing reference sensitivity requires explicit v2 exploratory use")
        expected_scope = (
            "reported-splits-and-documented-cash-unreported-coverage-unverified"
            if self.version == "daily-close-declared-assumptions-v3"
            else "reported-splits-only-unreported-coverage-unverified"
        )
        if self.action_scope != expected_scope:
            raise ValueError("documented cash accounting requires explicit v3 research scope")
        return self


class KnownActionBlocker(NavModel):
    """Supplemental evidence can stop accounting, never certify an event treatment."""

    symbol: str
    effective_from: date
    kind: Literal["delisting_cash_accounting_unresolved"]
    evidence: PinnedEvidence
    evidence_use: Literal["ex_post_accounting_only"] = "ex_post_accounting_only"


class DocumentedCashConversion(NavModel):
    """Reviewed cash-only terms; a hash authenticates bytes, not their meaning.

    Conditional fractional proceeds and other rights do not satisfy this
    contract. Ex-post evidence is for accounting only, never model features.
    """

    action: NavAction
    delisted_from: date
    terms_evidence: PinnedEvidence
    payment_evidence: PinnedEvidence | None = None
    entitlement_review: Literal["confirmed_unconditional_cash"]
    evidence_use: Literal["ex_post_accounting_only"] = "ex_post_accounting_only"

    @model_validator(mode="after")
    def coherent_terms(self) -> DocumentedCashConversion:
        event = self.action
        if (
            event.kind not in {"cash_conversion", "cash_conversion_pending_payment"}
            or self.delisted_from > event.effective_at.astimezone(JST).date()
            or event.source_id != "documented-cash-conversion:" + self.terms_evidence.sha256
            or (event.payment_at is not None) != (self.payment_evidence is not None)
        ):
            raise ValueError(
                "cash conversion requires matching reviewed terms and payment evidence"
            )
        return self


class AssumedMarketRequest(NavModel):
    schema_version: Literal["assumed-market-fixed-rule-request-v1"]
    assumptions: ResearchAssumptions
    feature_selection_path: Path
    frozen_source_manifest: PinnedEvidence
    candidate_registry: PinnedEvidence
    score_source: SavedScoreSource | SavedBenchmarkSource
    # A shared, fixed daily domain; never candidate-specific survivor filtering.
    eligible_universe: PinnedEvidence
    market_receipts: tuple[MarketReceipt, ...]
    instrument_receipts: tuple[PinnedEvidence, ...]
    research_funding_receipt: MarketReceipt
    rule: FixedRuleRequest
    known_action_blockers: tuple[KnownActionBlocker, ...] = ()
    cash_conversions: tuple[DocumentedCashConversion, ...] = ()


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
    if isinstance(source, SavedBenchmarkSource):
        return _benchmark_scores(request, source)
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
    tasks = {
        "regression": ["regression"],
        "ranking": ["ranking"],
        "rank_return": ["regression", "ranking"],
        "rank_return_risk": ["regression", "ranking", "quantile", "large_loss"],
    }[source.task]
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
            ("task", "in", tasks),
        ],
    )
    return saved_score_mapping(table.to_pandas(), source.task)


def saved_score_mapping(frame: Any, task: str) -> dict[datetime, dict[str, float]]:
    """One fixed mapping for both input preparation and authenticated replay."""
    tasks = {
        "regression": ["regression"],
        "ranking": ["ranking"],
        "rank_return": ["regression", "ranking"],
        "rank_return_risk": ["regression", "ranking", "quantile", "large_loss"],
    }[task]
    frame = frame.loc[frame.task.isin(tasks)]
    _validate_score_rows(frame)
    if len(tasks) > 1:
        panel = frame.pivot(index=["as_of", "symbol"], columns="task", values="prediction")
        if set(panel.columns) != set(tasks) or panel.isna().any().any():
            raise ValueError("fixed combination requires every saved task on identical keys")
        # Existing uniform within-date percentile normalization, without fitting.
        ranks = (panel.groupby(level="as_of").rank(method="average", pct=True) - 0.5) * 2
        combined = ranks["regression"] + ranks["ranking"]
        if task == "rank_return_risk":
            combined = combined + ranks["quantile"] - ranks["large_loss"]
        frame = (combined / len(tasks)).rename("prediction").reset_index()
    return _score_mapping(frame)


def _validate_score_rows(frame: Any) -> None:
    if frame.duplicated(
        ["as_of", "symbol", "task"] if "task" in frame else ["as_of", "symbol"]
    ).any():
        raise ValueError("duplicate saved prediction key")
    if not np.isfinite(frame.prediction.to_numpy(float)).all():
        raise ValueError("nonfinite saved prediction")
    local = frame.as_of.dt.tz_convert(JST).dt.tz_localize(None).dt.normalize()
    if (frame.trading_date >= local).any():
        raise ValueError("known future feature-day close in saved prediction")


def _score_mapping(frame: Any) -> dict[datetime, dict[str, float]]:
    result: dict[datetime, dict[str, float]] = {}
    for at, symbol, value in frame[["as_of", "symbol", "prediction"]].itertuples(
        index=False, name=None
    ):
        result.setdefault(at.to_pydatetime(), {})[symbol] = float(value)
    return result


def _benchmark_scores(
    request: AssumedMarketRequest, source: SavedBenchmarkSource
) -> dict[datetime, dict[str, float]]:
    proof, audit = json.loads(source.receipt.read()), json.loads(source.authentication.read())
    registry = json.loads(request.candidate_registry.read())
    expected_schema = (
        "daily-forward-crossfit-v1"
        if source.recipe == "weighted_return"
        else "daily-regression-risk-simple-baselines-v3"
    )
    matches = [
        r
        for r in proof["results"]
        if r["horizon"] == source.horizon
        and Path(r["oof_path"]).resolve() == source.path.resolve()
        and r["oof_byte_sha256"] == source.sha256
    ]
    if (
        len(matches) != 1
        or proof["schema_version"] != expected_schema
        or proof["feature_selection_id"] != registry["feature_selection_id"]
        or not proof["research_only"]
        or proof["holdout_scored"]
        or proof["adoption_eligible"]
        or audit["status"] != "COMPLETE_RESEARCH"
        or audit["holdout_opened"]
        or audit["training_performed"]
        or audit["weights_or_calibration_changed"]
        or audit["feature_selection_id"] != proof["feature_selection_id"]
        or audit["model_data_snapshot_id"] != proof["data_snapshot_id"]
        or audit["input_receipts"].get(str(source.receipt.path)) != source.receipt.sha256
    ):
        raise ValueError("saved benchmark differs from its authenticated development receipt")
    if source.recipe == "weighted_return":
        rows = [r for r in audit["results"] if r["horizon"] == source.horizon]
        if len(rows) != 1 or not rows[0]["ensemble_predictions_reproduced_from_saved_models"]:
            raise ValueError("saved ensemble lacks its authenticated forward replay")
    if _sha(source.path) != source.sha256:
        raise ValueError("saved benchmark bytes changed")
    timestamp_type = pq.ParquetFile(source.path).schema_arrow.field("as_of").type
    if not pa.types.is_timestamp(timestamp_type) or timestamp_type.tz is None:
        raise ValueError("saved benchmark timestamps need an explicit timezone")
    frame = pq.read_table(
        source.path,
        columns=["as_of", "symbol", "trading_date", source.recipe],
        filters=[
            ("as_of", ">=", pa.scalar(request.rule.signals[0].as_of, type=timestamp_type)),
            ("as_of", "<=", pa.scalar(request.rule.signals[-1].as_of, type=timestamp_type)),
        ],
    ).to_pandas()
    frame = frame.rename(columns={source.recipe: "prediction"})
    _validate_score_rows(frame)
    return _score_mapping(frame)


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
        or any(b.effective_from >= boundary for b in request.known_action_blockers)
        or any(
            c.delisted_from >= boundary
            or c.action.effective_at.astimezone(JST).date() >= boundary
            or (c.action.payment_at is not None
                and c.action.payment_at.astimezone(JST).date() >= boundary)
            for c in request.cash_conversions
        )
    ):
        raise ValueError("assumption research reaches the locked holdout")
    for blocker in request.known_action_blockers:
        blocker.evidence.read()
    cash_events = {c.action.event_id: c for c in request.cash_conversions}
    if len(cash_events) != len(request.cash_conversions) or len(
        {c.action.symbol for c in request.cash_conversions}
    ) != len(request.cash_conversions):
        raise ValueError("duplicate documented cash conversion")
    declared_cash = {a.event_id: a for a in accounting.actions if a.kind != "split"}
    if (
        declared_cash != {key: value.action for key, value in cash_events.items()}
        or (cash_events and request.assumptions.version != "daily-close-declared-assumptions-v3")
    ):
        raise ValueError("cash actions require exact documented terms and explicit v3 scope")
    for conversion in request.cash_conversions:
        conversion.terms_evidence.read()
        if conversion.payment_evidence is not None:
            conversion.payment_evidence.read()
    if (
        rule.evaluation_tier != "price_only_research"
        or accounting.data_mode != "historical_research"
        or accounting.execution_semantics != "daily_close_research_proxy"
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
    scope = frozenset(p.symbol for session in accounting.sessions for p in session.prices)
    rows = read_market_receipts(request.market_receipts, features, funding_request, symbols=scope)
    for conversion in request.cash_conversions:
        effective = conversion.action.effective_at.astimezone(JST).date()
        if any(
            symbol == conversion.action.symbol
            and conversion.delisted_from <= day <= effective
            and (row.get("ex_rights_type") not in (None, "")
                 or row.get("adjustment_requires_event_evidence"))
            for (day, symbol), row in rows.items()
        ):
            raise ValueError("cash terms cannot replace an unresolved share or rights event")
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
                instruments[(date.fromisoformat(row["trading_date"]), row["symbol"])] = {
                    "round_lot_size": row["round_lot_size"],
                    "tick_size": row["tick_size"],
                }
    for action in accounting.actions:
        if action.kind != "split":
            continue  # Matched to reviewed supplemental cash terms above.
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
            "ranking_score"
            if source.task in ("ranking", "rank_return", "rank_return_risk")
            else "fractional_return"
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
                if (action.kind == "split" and action.symbol == symbol
                        and prior_at < action.effective_at <= signal.as_of):
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
        for blocker in request.known_action_blockers:
            if blocker.symbol in exposed and day >= blocker.effective_from:
                if any(
                    c.action.symbol == blocker.symbol
                    and c.delisted_from == blocker.effective_from
                    for c in request.cash_conversions
                ):
                    continue
                issues.append(
                    {
                        "symbol": blocker.symbol,
                        "date": str(day),
                        "related_held_value_yen": str(sum(
                            (p.shares * p.last_price for p in state.positions
                             if p.symbol == blocker.symbol), Decimal(0)
                        )),
                        "reason": "KNOWN_UNRESOLVED_CORPORATE_ACTION",
                        "event_kind": blocker.kind,
                        "source_evidence_sha256": blocker.evidence.sha256,
                        "required_evidence": (
                            "dated cash entitlement, valuation and release treatment"
                        ),
                    }
                )
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
                and a.kind == "split"
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
        "final_test_executed": False,
        "no_order_sent": True,
        "input_sha256": content_id(request.model_dump(mode="json")),
        "policy_sha256": content_id(rule.policy.model_dump(mode="json")),
        "decision_policy_sha256": content_id(
            {
                "allocation": rule.policy.model_dump(mode="json"),
                "missing_held_reference": request.assumptions.missing_held_reference,
            }
        ),
        "comparison_use": request.assumptions.comparison_use,
        "supersedes_original_comparison": False,
        "known_action_blockers": [b.model_dump(mode="json")
                                  for b in request.known_action_blockers],
        "documented_cash_conversions": [c.model_dump(mode="json")
                                       for c in request.cash_conversions],
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
            accounting, rule.signals, rule.policy, exposure_guard=guard,
            missing_held_reference_policy=request.assumptions.missing_held_reference,
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
                "skipped_rebalances": sum(
                    d.get("status") == "SKIPPED_MISSING_HELD_REFERENCE" for d in decisions
                ),
                "unresolved_cash_payment_ids": sorted({
                    event for day in result.days for event in day.unresolved_cash_payments
                }),
                "sessions": len(result.days),
                "common_domain_rows": sum(len(v) for v in domains.values()),
                "hold_return_difference": None
                if result.total_return is None or hold.total_return is None
                else str(result.total_return - hold.total_return),
            },
        )
        if not result.valuation_complete:
            receipt["status"] = "INCOMPLETE"
        if any(day.unresolved_cash_payments for day in result.days):
            receipt["unverified"].append(
                "cash payment timing: nominal claim retained; no reinvestment or confirmed NAV"
            )
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
