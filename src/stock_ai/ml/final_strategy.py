"""Precommitted final-strategy NAV joined to the existing single-use holdout.

This module never opens a dataset, fits a model, authorizes holdout access, or
grants adoption. It consumes completed prediction-only holdout artifacts. The
ordinary development-only market adapters retain their existing holdout guards.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from stock_ai.ml.fixed_rule import FixedRulePolicy, FixedSignalDay, evaluate_fixed_rule
from stock_ai.ml.holdout import (
    HoldoutEvaluationStatus,
    LockedHoldoutLedger,
    LockedHoldoutReport,
    _authenticate_envelope,
    _component_plans,
    _ExclusiveHoldoutLock,
    _file_sha256,
    _load_ledger,
    _load_prediction_artifact,
    _read_json,
    _require_completed_report,
    _require_ledger_plan,
    _write_json,
    load_locked_holdout_report,
)
from stock_ai.ml.nav import (
    NavDecisionState,
    NavInput,
    NavModel,
    NavOrder,
    NavResult,
    evaluate_daily_nav,
    fixed_bps_policy,
)
from stock_ai.ml.selection import (
    DevelopmentSelectionArtifact,
    FrozenCompositionManifest,
    load_development_selection,
    load_frozen_composition,
)
from stock_ai.operations.daily import OwnerAdoptionReview, content_id

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ScoreSource = Literal[
    "selected_return", "selected_rank", "selected_rank_ensemble", "frozen_composition"
]
_PLAN_NAME = "final-strategy-plan.json"
_JST = ZoneInfo("Asia/Tokyo")


class FinalStrategyCriteria(NavModel):
    """Explicit proposed thresholds, frozen by the caller before final access."""

    version: str = Field(min_length=1)
    development_evidence_id: Hash
    minimum_excess_over_cash: Decimal = Field(allow_inf_nan=False)
    minimum_excess_over_momentum: Decimal = Field(allow_inf_nan=False)
    maximum_mdd_deterioration: Decimal = Field(ge=0, allow_inf_nan=False)
    minimum_label_coverage: Decimal = Field(default=Decimal(1), gt=0, le=1)
    require_no_prediction_abstentions: bool = True
    minimum_rank_ic: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    maximum_return_mse: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class FinalHorizonStrategy(NavModel):
    policy: FixedRulePolicy
    score_source: ScoreSource
    # This is the population on which selection.py's ensemble was evaluated.
    rank_population: Literal["all_saved_model_predictions"] = "all_saved_model_predictions"
    composition_output_id: str | None = Field(
        default=None, min_length=1, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def explicit_composition_output(self) -> Self:
        if (self.score_source == "frozen_composition") != (self.composition_output_id is not None):
            raise ValueError("composition strategy requires exactly one explicit output ID")
        return self


class FinalStrategyPlan(NavModel):
    schema_version: Literal["final-strategy-plan-v1"] = "final-strategy-plan-v1"
    plan_id: Hash
    selection_id: Hash
    selection_file_sha256: Hash
    build_id: Hash
    data_snapshot_id: Hash
    market_snapshot_id: Hash
    universe_rule_hash: Hash
    evaluator_code_commit: str = Field(min_length=1)
    ledger_path: str = Field(min_length=1)
    frozen_at: datetime
    owner_confirmation_reference: str = Field(min_length=1)
    criteria: FinalStrategyCriteria
    horizons: tuple[FinalHorizonStrategy, ...]
    cost_scenarios_bps: tuple[Decimal, ...] = (Decimal(20), Decimal(40))
    baseline: Literal["same_fixed_rule_momentum20_and_all_cash_hold"] = (
        "same_fixed_rule_momentum20_and_all_cash_hold"
    )
    adoption_eligible: Literal[False] = False
    composition_id: Hash | None = Field(default=None, exclude_if=lambda v: v is None)
    composition_manifest_path: str | None = Field(default=None, exclude_if=lambda v: v is None)
    composition_file_sha256: Hash | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        composed = [h.score_source == "frozen_composition" for h in self.horizons]
        pins = (self.composition_id, self.composition_manifest_path, self.composition_file_sha256)
        if (any(composed) and not all(composed)) or all(composed) != all(
            v is not None for v in pins
        ):
            raise ValueError(
                "composition strategy requires both horizons and its complete manifest pins"
            )
        if not any(composed) and any(v is not None for v in pins):
            raise ValueError("legacy strategy cannot contain unused composition pins")
        if tuple(h.policy.horizon for h in self.horizons) != (5, 20):
            raise ValueError("final strategy requires ordered daily 5d/20d choices")
        if self.cost_scenarios_bps != (Decimal(20), Decimal(40)) or any(
            h.policy.one_way_bps != 20 for h in self.horizons
        ):
            raise ValueError("freeze the existing 20/40bps comparison, with base policy 20bps")
        if self.plan_id != content_id(self.model_dump(mode="json", exclude={"plan_id"})):
            raise ValueError("final strategy plan content hash mismatch")
        return self


class FinalDecisionDay(NavModel):
    """Independent feature/universe keys; future label availability is absent."""

    feature_trading_date: date
    as_of: datetime
    available_at: datetime
    reference_price_at: datetime
    source_id: str = Field(min_length=1)
    prediction_symbols: tuple[str, ...]
    eligible_symbols: tuple[str, ...]
    abstentions: tuple[tuple[str, str], ...] = ()
    reference_prices: tuple[tuple[str, Decimal], ...]
    momentum20_scores: tuple[tuple[str, float], ...]

    @model_validator(mode="after")
    def independent_keys(self) -> Self:
        for symbols in (self.prediction_symbols, self.eligible_symbols):
            if not symbols or any(not s for s in symbols) or len(symbols) != len(set(symbols)):
                raise ValueError("final universe requires nonempty unique symbols")
        absent = set(self.eligible_symbols) - set(self.prediction_symbols)
        if (
            len(dict(self.abstentions)) != len(self.abstentions)
            or set(dict(self.abstentions)) != absent
            or any(not reason for _, reason in self.abstentions)
        ):
            raise ValueError("every eligible unpredicted symbol needs an explicit abstention")
        usable = set(self.eligible_symbols) & set(self.prediction_symbols)
        if not usable or set(dict(self.momentum20_scores)) != usable:
            raise ValueError("momentum must cover the same predictable eligible symbols")
        if len(dict(self.momentum20_scores)) != len(self.momentum20_scores) or any(
            not math.isfinite(v) for _, v in self.momentum20_scores
        ):
            raise ValueError("momentum scores must be unique and finite")
        if (
            self.available_at > self.as_of
            or self.reference_price_at > self.as_of
            or self.feature_trading_date >= self.as_of.astimezone(_JST).date()
        ):
            raise ValueError("daily close features must be available before their decision")
        return self


class FinalHorizonInputs(NavModel):
    horizon: Literal[5, 20]
    prediction_data_snapshot_id: Hash
    universe_rule_hash: Hash
    accounting: NavInput
    days: tuple[FinalDecisionDay, ...]
    evaluation_tier: Literal["synthetic_accounting", "price_only_research"]
    # Ex-post accounting evidence only; never a model feature or trading signal.
    # event_id, symbol, effective date, unresolved accounting reason.
    unresolved_valuation_events: tuple[tuple[str, str, date, str], ...] = ()

    @model_validator(mode="after")
    def same_calendar(self) -> Self:
        if (self.evaluation_tier == "synthetic_accounting") != (
            self.accounting.data_mode == "fixture"
        ):
            raise ValueError("synthetic and real final evaluations must remain separate")
        if any(event.kind == "dividend" for event in self.accounting.actions):
            raise ValueError("this final strategy excludes dividends; never credit them as zero")
        if len(self.days) != len(self.accounting.sessions) or any(
            day.as_of.astimezone(_JST).date() != session.trading_date
            for day, session in zip(self.days, self.accounting.sessions, strict=True)
        ):
            raise ValueError("final prediction decisions must cover the entire NAV calendar")
        if tuple(d.feature_trading_date for d in self.days) != tuple(
            sorted({d.feature_trading_date for d in self.days})
        ):
            raise ValueError("final feature dates must be ordered and unique")
        events = self.unresolved_valuation_events
        if len({e[0] for e in events}) != len(events) or any(
            not identity or not symbol or not reason for identity, symbol, _, reason in events
        ):
            raise ValueError("unresolved final events need unique identities and explicit reasons")
        return self


class FinalStrategyCase(NavModel):
    horizon: Literal[5, 20]
    one_way_bps: Decimal
    strategy: NavResult
    momentum: NavResult
    all_cash_hold: NavResult
    decisions: tuple[dict[str, Any], ...]
    momentum_decisions: tuple[dict[str, Any], ...]
    excess_over_cash: Decimal | None
    excess_over_momentum: Decimal | None
    turnover: Decimal | None
    turnover_definition: Literal["sum_filled_notional_divided_by_mean_daily_nav"] = (
        "sum_filled_notional_divided_by_mean_daily_nav"
    )
    reasons: tuple[str, ...]
    status: Literal["PASS", "FAIL", "INCOMPLETE"]

    @model_validator(mode="after")
    def incomplete_values_remain_unknown(self) -> Self:
        complete = all(
            result.valuation_complete
            and result.total_return is not None
            and result.maximum_drawdown is not None
            and all(day.nav is not None for day in result.days)
            for result in (self.strategy, self.momentum, self.all_cash_hold)
        )
        if not complete and (
            self.status != "INCOMPLETE"
            or self.excess_over_cash is not None
            or self.excess_over_momentum is not None
            or self.turnover is not None
        ):
            raise ValueError("incomplete NAV/MDD cannot produce a completed comparison")
        return self


class FinalStrategyReceipt(NavModel):
    schema_version: Literal["final-strategy-evaluation-v1"] = "final-strategy-evaluation-v1"
    receipt_id: Hash
    created_at: datetime
    selection_id: Hash
    holdout_report_id: Hash
    ledger_id: Hash
    plan_id: Hash
    decision_policy_hash: Hash
    criteria_hash: Hash
    inputs_hash: Hash
    data_snapshot_id: Hash
    market_snapshot_id: Hash
    prediction_file_hashes: tuple[tuple[str, str], ...]
    source_file_hashes: tuple[tuple[str, str], ...]
    evaluation_tier: Literal["synthetic_accounting", "price_only_research"]
    cases: tuple[FinalStrategyCase, ...]
    status: Literal["PASS", "FAIL", "INCOMPLETE"]
    metric_reasons: tuple[str, ...]
    unresolved_gates: tuple[str, ...]
    research_only: Literal[True] = True
    adoption_eligible: Literal[False] = False
    formal_adoption_status: Literal["HOLD"] = "HOLD"
    no_order_sent: Literal[True] = True
    prediction_strategy_join_authenticated: Literal[True] = True
    market_evidence_certified: Literal[False] = False
    evaluation_scope: Literal["precommitted_prediction_checks_and_fixed_strategy_nav"] = (
        "precommitted_prediction_checks_and_fixed_strategy_nav"
    )

    @model_validator(mode="after")
    def authentic(self) -> Self:
        if self.receipt_id != content_id(self.model_dump(mode="json", exclude={"receipt_id"})):
            raise ValueError("final strategy receipt content hash mismatch")
        if not self.unresolved_gates:
            raise ValueError("an evaluator cannot grant owner adoption")
        if tuple((case.horizon, case.one_way_bps) for case in self.cases) != (
            (5, Decimal(20)),
            (5, Decimal(40)),
            (20, Decimal(20)),
            (20, Decimal(40)),
        ):
            raise ValueError("final receipt must retain every frozen horizon/cost case")
        if self.status == "PASS" and (
            self.metric_reasons or not self.cases or any(c.status != "PASS" for c in self.cases)
        ):
            raise ValueError("incomplete/failed final evidence cannot claim PASS")
        return self

    def review_references(self) -> dict[str, str]:
        """References for a separately authored OwnerAdoptionReview, never approval."""
        return {
            "selection_id": self.selection_id,
            "holdout_report_id": self.holdout_report_id,
            "evaluator_receipt_id": self.receipt_id,
            "decision_policy_hash": self.decision_policy_hash,
        }


def _publish_once(path: Path, payload: dict[str, Any]) -> None:
    """Atomic publication while the caller holds the existing evaluation lock."""
    if path.exists():
        if _read_json(path, description="immutable final artifact") != payload:
            raise RuntimeError("final artifact already exists with different conditions")
        return
    _write_json(path, payload)


def freeze_final_strategy(
    *,
    selection_path: Path,
    evaluation_directory: Path,
    horizons: tuple[FinalHorizonStrategy, ...],
    criteria: FinalStrategyCriteria,
    market_snapshot_id: str,
    universe_rule_hash: str,
    evaluator_code_commit: str,
    owner_confirmation_reference: str,
    composition_path: Path | None = None,
) -> Path:
    """Persist one plan before the existing holdout authorization is created.

    The caller supplies the human confirmation reference; this function does
    not impersonate the owner or execute the holdout. No refreezing is allowed.
    """
    selection = load_development_selection(selection_path)
    composition = load_frozen_composition(composition_path, selection) if composition_path else None
    evaluation_directory = evaluation_directory.resolve()
    evaluation_directory.mkdir(parents=True, exist_ok=True)
    path = selection_path.resolve().parent / _PLAN_NAME
    with _ExclusiveHoldoutLock(evaluation_directory / ".evaluation.lock"):
        if (selection_path.parent / "holdout-access.json").exists():
            raise ValueError("cannot freeze or refreeze a strategy after holdout access")
        if path.exists():
            raise ValueError("final strategy is already frozen; load and reuse the original plan")
        now = datetime.now(UTC)
        if selection.created_at > now:
            raise ValueError("selection cannot be frozen in the future")
        values: dict[str, Any] = dict(
            selection_id=selection.selection_id,
            selection_file_sha256=_file_sha256(selection_path),
            build_id=selection.build_id,
            data_snapshot_id=selection.data_snapshot_id,
            market_snapshot_id=market_snapshot_id,
            universe_rule_hash=universe_rule_hash,
            evaluator_code_commit=evaluator_code_commit,
            ledger_path=str(evaluation_directory / "ledger.json"),
            frozen_at=now,
            owner_confirmation_reference=owner_confirmation_reference,
            horizons=horizons,
            criteria=criteria,
        )
        if composition is not None:
            assert composition_path is not None
            if (
                composition.owner_confirmation_reference != owner_confirmation_reference
                or composition.created_at > now
            ):
                raise ValueError("composition owner confirmation/timestamp differs from strategy")
            values.update(
                composition_id=composition.composition_id,
                composition_manifest_path=str(composition_path.resolve()),
                composition_file_sha256=_file_sha256(composition_path),
            )
        provisional = FinalStrategyPlan.model_construct(plan_id="0" * 64, **values)
        plan = FinalStrategyPlan.model_validate(
            {
                **provisional.model_dump(mode="json"),
                "plan_id": content_id(provisional.model_dump(mode="json", exclude={"plan_id"})),
            }
        )
        _selected_sources(selection, plan)
        # A second immutable copy prevents rewriting/re-hashing just the plan
        # after access while retaining a backdated frozen_at value.
        _publish_once(
            evaluation_directory / "final-strategy-preaccess.json", plan.model_dump(mode="json")
        )
        _publish_once(path, plan.model_dump(mode="json"))
    return path


def _selected_sources(
    selection: DevelopmentSelectionArtifact,
    plan: FinalStrategyPlan,
) -> dict[int, dict[str, float]]:
    selections = {h.horizon: h for h in selection.horizons}
    sources: dict[int, dict[str, float]] = {}
    composition = _plan_composition(selection, plan)
    for choice in plan.horizons:
        horizon = choice.policy.horizon
        selected = selections[horizon]
        if choice.score_source == "frozen_composition":
            assert composition is not None
            output = next(
                (o for o in composition.outputs if o.output_id == choice.composition_output_id),
                None,
            )
            if (
                output is None
                or output.horizon != horizon
                or output.role not in ("ranking", "return")
            ):
                raise ValueError(
                    "final score must reference a compatible frozen composition output"
                )
            sources[horizon] = {f"output:{output.output_id}": 1.0}
        elif choice.score_source == "selected_rank_ensemble":
            if not selected.ensemble_adopted:
                raise ValueError("ensemble was not selected on development data")
            if len(set(selected.ensemble.component_names)) != len(
                selected.ensemble.component_names
            ):
                raise ValueError("frozen final ensemble contains duplicate component identities")
            sources[horizon] = {
                f"h{horizon}:{name}": weight
                for name, weight in zip(
                    selected.ensemble.component_names, selected.ensemble.weights, strict=True
                )
            }
        else:
            component = (
                selected.expected_return_component
                if choice.score_source == "selected_return"
                else selected.rank_component
            )
            sources[horizon] = {f"h{horizon}:{component.component_name}": 1.0}
    return sources


def _plan_composition(
    selection: DevelopmentSelectionArtifact, plan: FinalStrategyPlan
) -> FrozenCompositionManifest | None:
    if plan.composition_manifest_path is None:
        return None
    path = Path(plan.composition_manifest_path)
    composition = load_frozen_composition(path, selection)
    if (
        composition.composition_id != plan.composition_id
        or _file_sha256(path) != plan.composition_file_sha256
        or composition.owner_confirmation_reference != plan.owner_confirmation_reference
    ):
        raise ValueError("composition manifest differs from its frozen strategy pins")
    return composition


def _prediction_hashes(report: LockedHoldoutReport) -> tuple[tuple[str, str], ...]:
    return tuple((c.component_key, c.prediction_sha256) for c in report.component_results) + tuple(
        (c.prediction.component_key, str(c.prediction.parquet_sha256))
        for c in report.composition_results or ()
    )


def _authenticate_final_inputs(
    selection_path: Path,
    plan_path: Path,
    report_path: Path,
) -> tuple[
    DevelopmentSelectionArtifact, FinalStrategyPlan, LockedHoldoutLedger, LockedHoldoutReport
]:
    if plan_path.resolve() != selection_path.resolve().parent / _PLAN_NAME:
        raise ValueError("final plan must be the pre-access artifact beside this selection")
    selection = load_development_selection(selection_path)
    plan = FinalStrategyPlan.model_validate(_read_json(plan_path, description="final plan"))
    anchor = _read_json(
        Path(plan.ledger_path).parent / "final-strategy-preaccess.json",
        description="pre-access final strategy anchor",
    )
    if anchor != plan.model_dump(mode="json"):
        raise ValueError("final strategy differs from its immutable pre-access anchor")
    if (
        plan.selection_id != selection.selection_id
        or plan.build_id != selection.build_id
        or plan.data_snapshot_id != selection.data_snapshot_id
        or plan.selection_file_sha256 != _file_sha256(selection_path)
    ):
        raise ValueError("final selection/snapshot hash differs from frozen plan")
    ledger = _load_ledger(Path(plan.ledger_path))
    if ledger.status is not HoldoutEvaluationStatus.COMPLETED:
        raise ValueError("final NAV needs a completed prediction holdout ledger")
    report = load_locked_holdout_report(report_path)
    if ledger.report_path is None or Path(ledger.report_path).resolve() != report_path.resolve():
        raise ValueError("final report path differs from completed holdout ledger")
    authorization = _read_json(
        selection_path.parent / "holdout-access.json", description="holdout access authorization"
    )
    _authenticate_envelope(authorization, description="holdout access authorization")
    expected_access = {
        "schema_version": "locked-holdout-access-v1",
        "selection_id": selection.selection_id,
        "build_id": plan.build_id,
        "data_snapshot_id": plan.data_snapshot_id,
        "evaluator_code_commit": plan.evaluator_code_commit,
        "ledger_path": str(Path(plan.ledger_path).resolve()),
    }
    composition = _plan_composition(selection, plan)
    if composition is not None:
        expected_access["composition_id"] = composition.composition_id
    if {k: v for k, v in authorization.items() if k not in {"created_at", "metadata_hash"}} != (
        expected_access
    ):
        raise ValueError("final holdout authorization differs from frozen plan")
    access_at = datetime.fromisoformat(str(authorization["created_at"]))
    if (
        access_at.utcoffset() is None
        or not selection.created_at <= plan.frozen_at < access_at
        or not plan.frozen_at < ledger.started_at
        or report.created_at < ledger.started_at
    ):
        raise ValueError("strategy and criteria were not frozen before holdout access")
    plans = _component_plans(selection, composition)
    _require_ledger_plan(
        ledger,
        selection=selection,
        build_id=plan.build_id,
        evaluator_code_commit=plan.evaluator_code_commit,
        plans=plans,
    )
    _require_completed_report(
        report, ledger=ledger, selection=selection, build_id=plan.build_id, composition=composition
    )
    expected = {p.component_key: p.component for p in plans}
    if {r.component_key: r.component for r in report.component_results} != expected:
        raise ValueError("holdout component report differs from frozen selection")
    selected_horizons = {h.horizon: h for h in selection.horizons}
    for ensemble in report.ensemble_results:
        selected = selected_horizons[ensemble.horizon]
        if (
            ensemble.component_names != selected.ensemble.component_names
            or ensemble.weights != selected.ensemble.weights
            or ensemble.adopted_on_development != selected.ensemble_adopted
        ):
            raise ValueError("holdout ensemble differs from frozen selection")
    if report.label_coverage is None:
        raise ValueError("final NAV requires label-independent v2 prediction coverage")
    return selection, plan, ledger, report


def _prediction_scores(
    selection: DevelopmentSelectionArtifact,
    plan: FinalStrategyPlan,
    ledger: LockedHoldoutLedger,
    report: LockedHoldoutReport,
    inputs: tuple[FinalHorizonInputs, ...],
) -> dict[int, dict[tuple[date, str], float]]:
    sources = _selected_sources(selection, plan)
    expected = {
        item.horizon: sorted(
            (d.feature_trading_date, s) for d in item.days for s in d.prediction_symbols
        )
        for item in inputs
    }
    for coverage in report.label_coverage or ():
        if coverage.horizon in expected and coverage.prediction_rows != len(
            expected[coverage.horizon]
        ):
            raise ValueError("independent final keys differ from full holdout prediction coverage")
    scores = {h: np.zeros(len(keys), dtype=float) for h, keys in expected.items()}
    ensemble_horizons = {
        h.policy.horizon for h in plan.horizons if h.score_source == "selected_rank_ensemble"
    }
    for state in ledger.components:
        # Even unused heads must retain their report/ledger/file identity.
        frame = _load_prediction_artifact(state)
        if state.horizon not in expected:
            continue
        frame = frame.sort_values(["trading_date", "symbol"], kind="stable").reset_index(drop=True)
        dates = pd.to_datetime(frame["trading_date"]).dt.date
        keys = list(zip(dates, frame["symbol"].astype(str), strict=True))
        if keys != expected[state.horizon] or len(keys) != len(set(keys)):
            raise ValueError("saved prediction keys differ from independent predictable universe")
        if any(
            not report.locked_holdout_start <= d.isoformat() <= report.locked_holdout_end
            for d, _ in keys
        ):
            raise ValueError("final strategy predictions lie outside locked holdout dates")
        weight = sources[state.horizon].get(state.component_key)
        if weight is None:
            continue
        values = frame["prediction"]
        if state.horizon in ensemble_horizons:
            values = (
                frame.groupby("trading_date", sort=False)["prediction"].rank(
                    method="average", pct=True
                )
                - 0.5
            ) * 2.0
        scores[state.horizon] += values.to_numpy(dtype=float) * weight
    if plan.composition_id is not None:
        for result in report.composition_results or ():
            frame = (
                _load_prediction_artifact(result.prediction)
                .sort_values(["trading_date", "symbol"], kind="stable")
                .reset_index(drop=True)
            )
            horizon = result.recipe.horizon
            keys = list(
                zip(
                    pd.to_datetime(frame.trading_date).dt.date,
                    frame.symbol.astype(str),
                    strict=True,
                )
            )
            if keys != expected[horizon]:
                raise ValueError(
                    "composed prediction keys differ from independent predictable universe"
                )
            if result.prediction.component_key in sources[horizon]:
                scores[horizon] = frame.prediction.to_numpy(dtype=float)
    return {h: dict(zip(expected[h], scores[h].tolist(), strict=True)) for h in scores}


def _case(
    item: FinalHorizonInputs,
    choice: FinalHorizonStrategy,
    scores: dict[tuple[date, str], float],
    bps: Decimal,
    criteria: FinalStrategyCriteria,
) -> FinalStrategyCase:
    signals = []
    momentum = []
    for day in item.days:
        keys = sorted(set(day.eligible_symbols) & set(day.prediction_symbols))
        common: dict[str, Any] = dict(
            as_of=day.as_of,
            available_at=day.available_at,
            reference_price_at=day.reference_price_at,
            horizon=item.horizon,
            reference_prices=day.reference_prices,
            source_id=day.source_id,
        )
        signals.append(
            FixedSignalDay(
                **common,
                score_unit=(
                    "fractional_return"
                    if choice.score_source == "selected_return"
                    else "ranking_score"
                ),
                scores=tuple((s, scores[day.feature_trading_date, s]) for s in keys),
            )
        )
        momentum.append(
            FixedSignalDay(**common, score_unit="ranking_score", scores=day.momentum20_scores)
        )
    accounting = item.accounting.model_copy(update={"cost_policy": fixed_bps_policy(bps)})
    policy = choice.policy.model_copy(update={"one_way_bps": bps})

    def guard(state: NavDecisionState, orders: tuple[NavOrder, ...]) -> None:
        exposed = {p.symbol for p in state.positions} | {o.symbol for o in orders}
        for identity, symbol, effective, reason in item.unresolved_valuation_events:
            if effective <= state.as_of.astimezone(_JST).date() and symbol in exposed:
                raise ValueError(f"unresolved final accounting event: {identity}/{symbol}/{reason}")

    _, strategy, decisions = evaluate_fixed_rule(
        accounting, tuple(signals), policy, exposure_guard=guard
    )
    _, baseline, baseline_decisions = evaluate_fixed_rule(
        accounting, tuple(momentum), policy, exposure_guard=guard
    )
    cash = evaluate_daily_nav(accounting)
    complete = all(
        r.valuation_complete
        and r.total_return is not None
        and r.maximum_drawdown is not None
        and all(d.nav is not None for d in r.days)
        for r in (strategy, baseline, cash)
    )
    excess_cash = excess_momentum = turnover = None
    reasons = []
    if not complete:
        reasons.append("UNRESOLVED_NAV_OR_MDD")
    else:
        assert strategy.total_return is not None and baseline.total_return is not None
        assert cash.total_return is not None
        assert strategy.maximum_drawdown is not None and baseline.maximum_drawdown is not None
        excess_cash = strategy.total_return - cash.total_return
        excess_momentum = strategy.total_return - baseline.total_return
        mean_nav = sum((d.nav for d in strategy.days if d.nav is not None), Decimal(0)) / len(
            strategy.days
        )
        if mean_nav > 0:
            turnover = sum((d.traded_notional for d in strategy.days), Decimal(0)) / mean_nav
        if excess_cash < criteria.minimum_excess_over_cash:
            reasons.append("RETURN_BELOW_CASH_CRITERION")
        if excess_momentum < criteria.minimum_excess_over_momentum:
            reasons.append("RETURN_BELOW_MOMENTUM_CRITERION")
        if (
            strategy.maximum_drawdown - baseline.maximum_drawdown
            > criteria.maximum_mdd_deterioration
        ):
            reasons.append("MDD_WORSE_THAN_MOMENTUM_CRITERION")
    return FinalStrategyCase(
        horizon=item.horizon,
        one_way_bps=bps,
        strategy=strategy,
        momentum=baseline,
        all_cash_hold=cash,
        decisions=decisions,
        momentum_decisions=baseline_decisions,
        excess_over_cash=excess_cash,
        excess_over_momentum=excess_momentum,
        turnover=turnover,
        reasons=tuple(reasons),
        status="INCOMPLETE" if not complete else "FAIL" if reasons else "PASS",
    )


def evaluate_final_strategy(
    *,
    selection_path: Path,
    plan_path: Path,
    report_path: Path,
    inputs: tuple[FinalHorizonInputs, ...],
) -> FinalStrategyReceipt:
    """Evaluate the immutable final strategy once; identical inputs may resume.

    No labels, price dataset, OOF, or model fit is opened here. Real market
    inputs require their own provenance review; this receipt cannot certify
    exchange execution conditions or authorize personal deployment.
    """
    selection, plan, ledger, report = _authenticate_final_inputs(
        selection_path, plan_path, report_path
    )
    if tuple(i.horizon for i in inputs) != (5, 20) or len({i.evaluation_tier for i in inputs}) != 1:
        raise ValueError("final comparison needs ordered 5d/20d inputs of one explicit tier")
    inputs = tuple(FinalHorizonInputs.model_validate(i.model_dump()) for i in inputs)
    for item in inputs:
        if (
            item.prediction_data_snapshot_id != plan.data_snapshot_id
            or item.accounting.source_snapshot_id != plan.market_snapshot_id
            or item.universe_rule_hash != plan.universe_rule_hash
        ):
            raise ValueError("final accounting/forecast/universe snapshot differs from frozen plan")
        if item.accounting.cost_policy != fixed_bps_policy(Decimal(20)):
            raise ValueError("final accounting base cost differs from frozen20bps policy")
    scores = _prediction_scores(selection, plan, ledger, report, inputs)
    source_hashes = tuple(
        (str(p.resolve()), _file_sha256(p))
        for p in (
            selection_path,
            plan_path,
            report_path,
            Path(plan.ledger_path),
            Path(plan.ledger_path).parent / "final-strategy-preaccess.json",
        )
    )
    identity = {
        "plan_id": plan.plan_id,
        "report_id": report.report_id,
        "inputs_hash": content_id([i.model_dump(mode="json") for i in inputs]),
        "source_file_hashes": [list(x) for x in source_hashes],
        "implementation_hashes": {
            name: _file_sha256(Path(__file__).with_name(name))
            for name in ("final_strategy.py", "fixed_rule.py", "nav.py")
        },
    }
    directory = Path(plan.ledger_path).parent
    with _ExclusiveHoldoutLock(directory / ".evaluation.lock"):
        _publish_once(directory / "final-strategy-inputs.json", identity)
        receipt_path = directory / "final-strategy-result.json"
        if receipt_path.exists():
            saved = FinalStrategyReceipt.model_validate(
                _read_json(receipt_path, description="final strategy result")
            )
            if (
                saved.selection_id != selection.selection_id
                or saved.holdout_report_id != report.report_id
                or saved.ledger_id != ledger.ledger_id
                or saved.plan_id != plan.plan_id
                or saved.decision_policy_hash != plan.plan_id
                or saved.criteria_hash != content_id(plan.criteria.model_dump(mode="json"))
                or saved.inputs_hash != identity["inputs_hash"]
                or saved.source_file_hashes != source_hashes
                or saved.data_snapshot_id != plan.data_snapshot_id
                or saved.market_snapshot_id != plan.market_snapshot_id
                or saved.prediction_file_hashes != _prediction_hashes(report)
                or saved.evaluation_tier != inputs[0].evaluation_tier
            ):
                raise ValueError("saved final receipt differs from authenticated final inputs")
            return saved
        cases = tuple(
            _case(item, choice, scores[item.horizon], bps, plan.criteria)
            for item, choice in zip(inputs, plan.horizons, strict=True)
            for bps in plan.cost_scenarios_bps
        )
        incomplete = []
        metric_failures = []
        coverage = {c.horizon: c for c in report.label_coverage or ()}
        components = {c.component_key: c for c in report.component_results}
        for item, choice in zip(inputs, plan.horizons, strict=True):
            observed = coverage[item.horizon]
            if (
                Decimal(observed.evaluated_rows) / observed.prediction_rows
                < plan.criteria.minimum_label_coverage
            ):
                incomplete.append(f"h{item.horizon}:HOLDOUT_LABEL_COVERAGE")
            if plan.criteria.require_no_prediction_abstentions and any(
                d.abstentions for d in item.days
            ):
                incomplete.append(f"h{item.horizon}:ELIGIBLE_PREDICTION_ABSTENTIONS")
            selected = next(h for h in selection.horizons if h.horizon == item.horizon)
            if plan.criteria.maximum_return_mse is not None:
                if plan.composition_id is not None:
                    output = next(
                        (
                            r
                            for r in report.composition_results or ()
                            if r.recipe.horizon == item.horizon and r.recipe.role == "return"
                        ),
                        None,
                    )
                    mse = None if output is None else output.mean_squared_error
                else:
                    metric = components[
                        f"h{item.horizon}:{selected.expected_return_component.component_name}"
                    ].metrics
                    mse = None if metric is None else metric.mean_squared_error
                if mse is None:
                    incomplete.append(f"h{item.horizon}:RETURN_MSE_UNAVAILABLE")
                elif mse > plan.criteria.maximum_return_mse:
                    metric_failures.append(f"h{item.horizon}:RETURN_MSE_CRITERION")
            if plan.criteria.minimum_rank_ic is not None:
                if choice.score_source == "frozen_composition":
                    output = next(
                        r
                        for r in report.composition_results or ()
                        if r.recipe.output_id == choice.composition_output_id
                    )
                    rank_ic = output.mean_daily_rank_ic
                elif choice.score_source == "selected_rank_ensemble":
                    rank_ic = next(
                        e.mean_daily_rank_ic
                        for e in report.ensemble_results
                        if e.horizon == item.horizon
                    )
                else:
                    component = (
                        selected.expected_return_component
                        if choice.score_source == "selected_return"
                        else selected.rank_component
                    )
                    metric = components[f"h{item.horizon}:{component.component_name}"].metrics
                    rank_ic = None if metric is None else metric.mean_daily_rank_ic
                if rank_ic is None:
                    incomplete.append(f"h{item.horizon}:RANK_IC_UNAVAILABLE")
                elif rank_ic < plan.criteria.minimum_rank_ic:
                    metric_failures.append(f"h{item.horizon}:RANK_IC_CRITERION")
        status: Literal["PASS", "FAIL", "INCOMPLETE"] = "PASS"
        if incomplete or any(c.status == "INCOMPLETE" for c in cases):
            status = "INCOMPLETE"
        elif metric_failures or any(c.status == "FAIL" for c in cases):
            status = "FAIL"
        values: dict[str, Any] = dict(
            created_at=datetime.now(UTC),
            selection_id=selection.selection_id,
            holdout_report_id=report.report_id,
            ledger_id=ledger.ledger_id,
            plan_id=plan.plan_id,
            decision_policy_hash=plan.plan_id,
            criteria_hash=content_id(plan.criteria.model_dump(mode="json")),
            inputs_hash=identity["inputs_hash"],
            data_snapshot_id=plan.data_snapshot_id,
            market_snapshot_id=plan.market_snapshot_id,
            prediction_file_hashes=_prediction_hashes(report),
            source_file_hashes=source_hashes,
            evaluation_tier=inputs[0].evaluation_tier,
            cases=cases,
            status=status,
            metric_reasons=tuple(incomplete + metric_failures),
            unresolved_gates=(
                *(
                    reason
                    for reason in report.adoption_blocking_reasons
                    if reason
                    != (
                        "prediction metrics do not authenticate "
                        "a final fixed-strategy NAV evaluation"
                    )
                ),
                "market_execution_and_valuation_evidence_requires_independent_review",
                "forward_paper_evidence_and_personal_settings_require_review",
                "explicit_owner_adoption_review_not_recorded",
            ),
        )
        provisional = FinalStrategyReceipt.model_construct(receipt_id="0" * 64, **values)
        payload = provisional.model_dump(mode="json", exclude={"receipt_id"})
        receipt = FinalStrategyReceipt.model_validate(
            {**payload, "receipt_id": content_id(payload)}
        )
        _publish_once(receipt_path, receipt.model_dump(mode="json"))
        return receipt


def validate_final_owner_review(review: OwnerAdoptionReview, receipt: FinalStrategyReceipt) -> None:
    """Bind an independently created owner review; never manufacture approval."""
    review = OwnerAdoptionReview.model_validate_json(review.model_dump_json())
    receipt = FinalStrategyReceipt.model_validate_json(receipt.model_dump_json())
    if any(getattr(review, key) != value for key, value in receipt.review_references().items()):
        raise ValueError("owner review does not refer to this final evaluator evidence")
    if review.reviewed_at < receipt.created_at:
        raise ValueError("owner review precedes the final evaluator evidence")
    if review.decision == "adopt":
        raise ValueError(
            "research receipt cannot grant adoption; unresolved evidence/settings gates"
        )
