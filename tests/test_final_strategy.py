"""Synthetic final strategy integration; no real holdout or owner data is read."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import stock_ai.ml.final_strategy as final_module
import stock_ai.ml.holdout as holdout_module
import stock_ai.ml.selection as selection_module
from stock_ai.ml.final_strategy import (
    FinalDecisionDay,
    FinalHorizonInputs,
    FinalHorizonStrategy,
    FinalStrategyCriteria,
    FinalStrategyPlan,
    FinalStrategyReceipt,
    evaluate_final_strategy,
    freeze_final_strategy,
    validate_final_owner_review,
)
from stock_ai.ml.fixed_rule import FixedRulePolicy
from stock_ai.ml.holdout import evaluate_locked_holdout
from stock_ai.ml.nav import NavCash, NavInput, NavPrice, NavSession, fixed_bps_policy
from stock_ai.ml.selection import (
    DevelopmentSelectionArtifact,
    FrozenCompositionManifest,
    write_development_selection,
    write_frozen_composition,
)
from stock_ai.operations.daily import OwnerAdoptionReview, content_id
from tests.test_locked_holdout import _production_fixture, _selection_fixture

JST = ZoneInfo("Asia/Tokyo")
MARKET_ID = content_id("synthetic-final-prices-only")
UNIVERSE = content_id("independent-frozen-feature-keys-and-dated-membership")


def fixture(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    missing_labels: bool = False,
    eligible: tuple[str, ...] = ("A", "B", "C"),
    minimum_excess: str = "0",
    composition_builder: Callable[[DevelopmentSelectionArtifact], FrozenCompositionManifest]
    | None = None,
) -> dict[str, Any]:
    build, dataset, build_id = _production_fixture(root, missing_exit_labels=missing_labels)
    previous = _selection_fixture(build_id=build_id, dataset_id=dataset)
    values = previous.model_dump(mode="json", exclude={"selection_id"})
    values["horizons"] = [h for h in values["horizons"] if h["horizon"] in (5, 20)]
    values["one_day_exclusion_decision_hash"] = content_id("synthetic daily scope")
    # Construct nested types before hashing, as the established fixture does.
    provisional = previous.model_copy(
        update={
            "horizons": tuple(h for h in previous.horizons if h.horizon in (5, 20)),
            "one_day_exclusion_decision_hash": values["one_day_exclusion_decision_hash"],
        }
    )
    values["selection_id"] = selection_module._stable_hash(
        selection_module._selection_identity(provisional)
    )
    selection = DevelopmentSelectionArtifact.model_validate(values)
    selection_path = write_development_selection(selection, root / "selection")
    calls = []

    def predict(training: pd.DataFrame, prediction_frame: pd.DataFrame, **kwargs: Any):
        assert pd.to_datetime(training.trading_date).max() < pd.Timestamp("2025-03-03")
        calls.append((kwargs["horizon"], kwargs["task"]))
        return prediction_frame.symbol.map({"A": 0.03, "B": 0.02, "C": 0.01}).to_numpy()

    monkeypatch.setattr(holdout_module, "fit_predict_frozen_model", predict)
    choices = tuple(
        FinalHorizonStrategy(
            policy=FixedRulePolicy(horizon=h, initial_cash_yen=D(100000), top_n=1),
            score_source="selected_rank_ensemble",
        )
        for h in (5, 20)
    )
    criteria = FinalStrategyCriteria(
        version="synthetic-explicit-prior-criteria",
        development_evidence_id=content_id("dev"),
        minimum_excess_over_cash=D(minimum_excess),
        minimum_excess_over_momentum=D(minimum_excess),
        maximum_mdd_deterioration=D(0),
        minimum_rank_ic=-1,
        maximum_return_mse=1,
    )
    directory = root / "holdout" / selection.selection_id
    composition_path = None
    if composition_builder is not None:
        composition_path = write_frozen_composition(composition_builder(selection), selection_path)
        choices = tuple(
            FinalHorizonStrategy(
                policy=c.policy,
                score_source="frozen_composition",
                composition_output_id=f"h{c.policy.horizon}-ranking",
            )
            for c in choices
        )
    plan_path = freeze_final_strategy(
        selection_path=selection_path,
        evaluation_directory=directory,
        horizons=choices,
        criteria=criteria,
        market_snapshot_id=MARKET_ID,
        universe_rule_hash=UNIVERSE,
        evaluator_code_commit="synthetic-final-evaluator",
        owner_confirmation_reference="TEST-ONLY-confirmation-never-owner-approval",
        composition_path=composition_path,
    )
    evaluated = evaluate_locked_holdout(
        selection_path=selection_path,
        build_manifest_path=build,
        evaluation_root=root / "holdout",
        evaluator_code_commit="synthetic-final-evaluator",
        composition_path=composition_path,
    )
    dates = pd.bdate_range("2025-03-03", periods=10)
    sessions, days = [], []
    initial = datetime(2025, 3, 3, 16, tzinfo=JST)
    for index, quote_date in enumerate(dates):
        decision_date = (quote_date + pd.offsets.BDay(1)).date()
        decision = datetime.combine(decision_date, time(11, 30), JST)
        close = datetime.combine(decision_date, time(16), JST)
        prices = tuple(
            NavPrice(
                symbol=symbol,
                execution_price=D(100 + 10 * index) if symbol == "A" else D(100),
                close_price=D(100 + 10 * index) if symbol == "A" else D(100),
                buy_status="tradable",
                sell_status="tradable",
                capacity_shares=100000,
                tick_size=D(1),
                source_id="synthetic-price",
            )
            for symbol in ("A", "B", "C")
        )
        sessions.append(
            NavSession(
                trading_date=decision_date,
                execution_at=close,
                close_at=close,
                sale_cash_available_at=close + timedelta(days=5),
                prices=prices,
            )
        )
        days.append(
            FinalDecisionDay(
                feature_trading_date=quote_date.date(),
                as_of=decision,
                available_at=decision - timedelta(minutes=1),
                reference_price_at=initial if index == 0 else sessions[index - 1].close_at,
                source_id="synthetic-feature-and-universe",
                prediction_symbols=("A", "B", "C"),
                eligible_symbols=eligible,
                reference_prices=tuple(
                    (s, D(100 + 10 * max(0, index - 1)) if s == "A" else D(100))
                    for s in ("A", "B", "C")
                ),
                momentum20_scores=tuple((s, 10.0 if s == "B" else 0.0) for s in eligible),
            )
        )
    accounting = NavInput(
        data_mode="fixture",
        source_snapshot_id=MARKET_ID,
        calendar_id="synthetic-only-not-JPX",
        calendar_dates=tuple(s.trading_date for s in sessions),
        price_basis="unadjusted",
        execution_semantics="daily_close_research_proxy",
        initial_as_of=initial,
        cash=(NavCash(bucket="cash", amount=D(100000)),),
        sessions=tuple(sessions),
        cost_policy=fixed_bps_policy(D(20)),
    )
    inputs = tuple(
        FinalHorizonInputs(
            horizon=h,
            prediction_data_snapshot_id=dataset,
            universe_rule_hash=UNIVERSE,
            accounting=accounting,
            days=tuple(days),
            evaluation_tier="synthetic_accounting",
        )
        for h in (5, 20)
    )
    return dict(
        selection=selection,
        selection_path=selection_path,
        plan_path=plan_path,
        report_path=evaluated.report_path,
        inputs=inputs,
        directory=directory,
        choices=choices,
        criteria=criteria,
        build=build,
        calls=calls,
        composition_path=composition_path,
    )


def run(f: dict[str, Any], **changes: Any) -> FinalStrategyReceipt:
    return evaluate_final_strategy(
        **{key: f[key] for key in ("selection_path", "plan_path", "report_path", "inputs")}
        | changes
    )


def test_complete_frozen_selection_holdout_nav_receipt_and_owner_review_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    receipt = run(f)
    assert receipt.status == "PASS"
    assert [(c.horizon, c.one_way_bps) for c in receipt.cases] == [
        (5, D(20)),
        (5, D(40)),
        (20, D(20)),
        (20, D(40)),
    ]
    assert all(c.strategy.total_return > c.momentum.total_return for c in receipt.cases)
    assert all(c.strategy.total_trading_cost > 0 and c.turnover > 0 for c in receipt.cases)
    assert all(c.all_cash_hold.total_return == 0 for c in receipt.cases)
    assert not receipt.adoption_eligible and receipt.formal_adoption_status == "HOLD"
    review = OwnerAdoptionReview.create(
        **receipt.review_references(),
        reviewed_at=datetime.now(UTC),
        decision="continue_paper",
        unresolved_gates=receipt.unresolved_gates,
        acknowledged_limitations=("synthetic only",),
        note="TEST-ONLY independent owner form",
    )
    validate_final_owner_review(review, receipt)
    with pytest.raises(ValueError, match="cannot grant adoption"):
        validate_final_owner_review(
            OwnerAdoptionReview.create(
                **receipt.review_references(),
                reviewed_at=datetime.now(UTC),
                decision="adopt",
                unresolved_gates=(),
                acknowledged_limitations=("synthetic only",),
                note="TEST-ONLY",
            ),
            receipt,
        )
    assert FinalStrategyReceipt.model_validate_json(receipt.model_dump_json()) == receipt


def test_same_input_resume_never_refits_or_reopens_single_use_holdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    first = run(f)
    calls = list(f["calls"])
    second = run(f)
    assert first == second and f["calls"] == calls
    repeated = evaluate_locked_holdout(
        selection_path=f["selection_path"],
        build_manifest_path=f["build"],
        evaluation_root=tmp_path / "holdout",
        evaluator_code_commit="synthetic-final-evaluator",
    )
    assert repeated.resumed and f["calls"] == calls
    with pytest.raises(RuntimeError, match="provenance mismatch"):
        evaluate_locked_holdout(
            selection_path=f["selection_path"],
            build_manifest_path=f["build"],
            evaluation_root=tmp_path / "second-holdout",
            evaluator_code_commit="synthetic-final-evaluator",
        )


@pytest.mark.parametrize("field", ["prediction_data_snapshot_id", "universe_rule_hash"])
def test_mismatched_snapshot_or_universe_is_rejected_before_nav(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    items = (f["inputs"][0].model_copy(update={field: "f" * 64}), f["inputs"][1])
    with pytest.raises(ValueError, match="snapshot differs"):
        run(f, inputs=items)
    assert not (f["directory"] / "final-strategy-inputs.json").exists()


def test_prediction_population_must_equal_independent_keys_not_label_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    changed = list(f["inputs"][0].days)
    changed[0] = changed[0].model_copy(
        update={
            "prediction_symbols": ("A", "B", "D"),
            "eligible_symbols": ("A", "B"),
            "momentum20_scores": (("A", 0), ("B", 10)),
        }
    )
    inputs = (f["inputs"][0].model_copy(update={"days": tuple(changed)}), f["inputs"][1])
    with pytest.raises(ValueError, match="prediction keys differ"):
        run(f, inputs=inputs)


def test_label_missing_predictions_remain_in_full_rank_population_and_block_full_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch, missing_labels=True, eligible=("A", "B"))
    original = final_module.evaluate_fixed_rule
    captured = []

    def capture(accounting, signals, policy, **kwargs):
        captured.append(signals)
        return original(accounting, signals, policy, **kwargs)

    monkeypatch.setattr(final_module, "evaluate_fixed_rule", capture)
    receipt = run(f)
    # C has no future label, but its prediction still affects B's percentile.
    assert dict(captured[0][0].scores) == pytest.approx({"A": 1.0, "B": 1 / 3})
    assert receipt.status == "INCOMPLETE"
    assert any("LABEL_COVERAGE" in reason for reason in receipt.metric_reasons)
    assert not receipt.adoption_eligible


def test_missing_intermediate_holding_mark_cannot_produce_pass_or_mdd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    changed = []
    for item in f["inputs"]:
        sessions = list(item.accounting.sessions)
        session = sessions[8]
        sessions[8] = session.model_copy(
            update={
                "prices": tuple(
                    p.model_copy(
                        update={
                            "execution_price": None,
                            "close_price": None,
                            "buy_status": "suspended",
                            "sell_status": "suspended",
                        }
                    )
                    if p.symbol == "A"
                    else p
                    for p in session.prices
                )
            }
        )
        changed.append(
            item.model_copy(
                update={
                    "accounting": item.accounting.model_copy(update={"sessions": tuple(sessions)})
                }
            )
        )
    receipt = run(f, inputs=tuple(changed))
    assert receipt.status == "INCOMPLETE"
    assert all(
        c.strategy.maximum_drawdown is None and c.excess_over_cash is None and c.turnover is None
        for c in receipt.cases
    )
    assert all(c.status == "INCOMPLETE" for c in receipt.cases)
    assert receipt.cases[0].strategy.days[8].positions[0].symbol == "A"


@pytest.mark.parametrize("symbol", ["A", "C"])
def test_known_unresolved_action_blocks_actual_exposure_without_deleting_unheld_peers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symbol: str,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    event_date = f["inputs"][0].accounting.calendar_dates[3]
    inputs = tuple(
        item.model_copy(
            update={
                "unresolved_valuation_events": (
                    (
                        "known-unhandled-cash-or-rights-event",
                        symbol,
                        event_date,
                        "MISSING_CONSIDERATION",
                    ),
                )
            }
        )
        for item in f["inputs"]
    )
    if symbol == "A":
        with pytest.raises(ValueError, match="unresolved final accounting event"):
            run(f, inputs=inputs)
        assert not (f["directory"] / "final-strategy-result.json").exists()
    else:
        assert run(f, inputs=inputs).status == "PASS"


def test_first_input_pin_rejects_changed_market_conditions_after_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    run(f)
    changed = list(f["inputs"][0].days)
    changed[0] = changed[0].model_copy(
        update={"momentum20_scores": (("A", 10), ("B", 0), ("C", 0))}
    )
    inputs = (f["inputs"][0].model_copy(update={"days": tuple(changed)}), f["inputs"][1])
    with pytest.raises(RuntimeError, match="different conditions"):
        run(f, inputs=inputs)


def test_strategy_cannot_be_refrozen_after_access_or_timestamp_backfilled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    original = f["plan_path"].read_bytes()
    with pytest.raises(ValueError, match="after holdout access"):
        freeze_final_strategy(
            selection_path=f["selection_path"],
            evaluation_directory=f["directory"],
            horizons=f["choices"],
            criteria=f["criteria"],
            market_snapshot_id=MARKET_ID,
            universe_rule_hash=UNIVERSE,
            evaluator_code_commit="synthetic-final-evaluator",
            owner_confirmation_reference="TEST",
        )
    assert f["plan_path"].read_bytes() == original
    plan = FinalStrategyPlan.model_validate_json(original)
    values = plan.model_copy(update={"frozen_at": datetime.now(UTC)}).model_dump(
        mode="json", exclude={"plan_id"}
    )
    values["plan_id"] = content_id(values)
    f["plan_path"].write_text(json.dumps(values), encoding="utf-8")
    with pytest.raises(ValueError, match="pre-access anchor"):
        run(f)


def test_rehashing_changed_criteria_with_old_timestamp_cannot_refreeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    plan = FinalStrategyPlan.model_validate_json(f["plan_path"].read_bytes())
    criteria = plan.criteria.model_copy(update={"minimum_excess_over_cash": D(-1)})
    payload = plan.model_copy(update={"criteria": criteria}).model_dump(
        mode="json", exclude={"plan_id"}
    )
    payload["plan_id"] = content_id(payload)
    f["plan_path"].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="pre-access anchor"):
        run(f)


def test_valid_negative_result_is_fail_without_reselection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch, minimum_excess="10")
    receipt = run(f)
    assert receipt.status == "FAIL"
    assert all(case.status == "FAIL" for case in receipt.cases)
    assert all("RETURN_BELOW_CASH_CRITERION" in case.reasons for case in receipt.cases)
    assert run(f) == receipt


def test_interrupted_nav_resumes_only_same_immutable_inputs_without_refitting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    original = final_module._case

    def interrupt(*_args, **_kwargs):
        raise RuntimeError("synthetic interruption before result publication")

    monkeypatch.setattr(final_module, "_case", interrupt)
    calls = list(f["calls"])
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        run(f)
    assert (f["directory"] / "final-strategy-inputs.json").exists()
    assert not (f["directory"] / "final-strategy-result.json").exists()
    monkeypatch.setattr(final_module, "_case", original)
    receipt = run(f)
    assert receipt.status == "PASS" and f["calls"] == calls


def test_receipt_cannot_drop_an_inconvenient_horizon_or_cost_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    receipt = run(f)
    payload = receipt.model_dump(mode="json", exclude={"receipt_id"})
    payload["cases"] = payload["cases"][:-1]
    payload["receipt_id"] = content_id(payload)
    with pytest.raises(ValueError, match="every frozen horizon/cost case"):
        FinalStrategyReceipt.model_validate(payload)


def test_existing_receipt_must_match_authenticated_input_pin_not_just_own_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    receipt = run(f)
    payload = receipt.model_dump(mode="json", exclude={"receipt_id"})
    payload["inputs_hash"] = "f" * 64
    payload["receipt_id"] = content_id(payload)
    (f["directory"] / "final-strategy-result.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="differs from authenticated final inputs"):
        run(f)


def test_changed_prediction_artifact_is_rejected_even_for_an_unused_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    ledger = holdout_module._load_ledger(f["directory"] / "ledger.json")
    state = next(c for c in ledger.components if "quantile" in c.component_key)
    path = Path(state.prediction_path)
    frame = pd.read_parquet(path)
    frame.loc[0, "prediction"] = 123
    frame.to_parquet(path, index=False)
    with pytest.raises(RuntimeError, match="Parquet hash mismatch"):
        run(f)


def test_future_observation_and_unexplained_missing_prediction_are_rejected():
    base = dict(
        feature_trading_date=datetime(2025, 1, 3).date(),
        as_of=datetime(2025, 1, 6, 11, 30, tzinfo=JST),
        available_at=datetime(2025, 1, 6, 11, 29, tzinfo=JST),
        reference_price_at=datetime(2025, 1, 3, 16, tzinfo=JST),
        source_id="synthetic",
        prediction_symbols=("A",),
        eligible_symbols=("A", "NEW"),
        reference_prices=(("A", D(100)),),
        momentum20_scores=(("A", 0),),
    )
    with pytest.raises(ValueError, match="explicit abstention"):
        FinalDecisionDay(**base)
    valid = FinalDecisionDay(**base, abstentions=(("NEW", "NO_PRIOR_OBSERVATION"),))
    with pytest.raises(ValueError, match="daily close features"):
        FinalDecisionDay.model_validate(
            valid.model_dump() | {"feature_trading_date": datetime(2025, 1, 6).date()}
        )


def test_synthetic_receipt_cannot_be_presented_as_real_or_mutated_to_adoptable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="synthetic and real"):
        FinalHorizonInputs.model_validate(
            f["inputs"][0].model_dump() | {"evaluation_tier": "price_only_research"}
        )
    receipt = run(f)
    with pytest.raises(ValueError):
        FinalStrategyReceipt.model_validate(receipt.model_dump() | {"adoption_eligible": True})
