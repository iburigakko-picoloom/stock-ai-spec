"""Hand-computed seed outliers must not choose the daily deployment seed."""

import hashlib
from types import SimpleNamespace

import pytest

import stock_ai.ml.selection as selection
from stock_ai.ml.advanced import AdvancedModelMetrics, AdvancedResearchConfig, EnsembleResult
from tests.test_locked_holdout import _selection_fixture

SEEDS = (17, 29, 43)
TASKS = ("regression", "ranking", "quantile", "large_loss")


def evidence(horizon=5):
    metrics, reports, ranks, runs = [], {}, {}, []
    for family in ("lightgbm", "xgboost", "catboost"):
        for seed in SEEDS:
            config = AdvancedResearchConfig(
                horizons=(horizon,),
                model_families=(family,),
                seeds=(seed,),
                run_ablations=False,
                run_diagnostics=False,
            )
            items = []
            for task in TASKS:
                score = (
                    (0.9 if seed == 43 else 0.0)
                    if family == "lightgbm"
                    else 0.4
                    if family == "xgboost"
                    else 0.1
                )
                loss = (
                    (0.0 if seed == 43 else 0.6)
                    if family == "lightgbm"
                    else 0.2
                    if family == "xgboost"
                    else 0.5
                )
                metric = AdvancedModelMetrics(
                    horizon=horizon,
                    model_family=family,
                    task=task,
                    seed=seed,
                    folds=2,
                    rows=100,
                    dates=10,
                    mean_daily_rank_ic=score,
                    pinball_loss=loss if task == "quantile" else None,
                    brier_score=loss if task == "large_loss" else None,
                )
                items.append(metric)
                name = selection._metric_component_name(metric)
                if task in {"regression", "ranking"}:
                    ranks[name] = score if task == "ranking" or family == "lightgbm" else 0.05
            report = SimpleNamespace(
                model_metrics=tuple(items),
                config=config,
                config_hash=config.config_hash,
                report_id=hashlib.sha256(
                    f"synthetic-{horizon}-{family}-{seed}".encode()
                ).hexdigest(),
                tuning_results=(SimpleNamespace(best_parameters={"depth": 3}),),
            )
            run = SimpleNamespace(
                report=report,
                batch=SimpleNamespace(horizon=horizon, model_family=family, seed=seed),
            )
            runs.append(run)
            for item in items:
                reports[selection._metric_component_name(item)] = run
                metrics.append(item)
    return metrics, reports, ranks, tuple(runs)


@pytest.mark.parametrize("horizon", [5, 20])
@pytest.mark.parametrize(
    "task,expected", [("regression", 0.4), ("quantile", 0.2), ("large_loss", 0.2)]
)
def test_daily_heads_choose_family_mean_and_predeclared_seed_not_lucky_seed(
    horizon, task, expected
):
    metrics, reports, _, _ = evidence(horizon)
    legacy = selection._best_component(metrics, task=task, reports=reports)
    assert legacy.model_family == "lightgbm" and legacy.seed == 43
    result = selection._seed_stable_component(metrics, task=task, reports=reports, seeds=SEEDS)
    assert result.model_family == "xgboost" and result.seed == 17
    assert result.selection_metric_value == pytest.approx(expected)
    assert result.selection_metric_name.startswith("family_seed_mean_")
    assert result.selection_metric_name.endswith("fixed_min_seed_v1")
    assert result.source_report_id == reports[result.component_name].report.report_id


@pytest.mark.parametrize("horizon", [5, 20])
def test_rank_fallback_uses_complete_family_task_group_instead_of_maximum_seed(horizon):
    metrics, reports, ranks, _ = evidence(horizon)
    result = selection._seed_stable_component(
        metrics, task=None, reports=reports, seeds=SEEDS, rank_ics=ranks
    )
    assert (result.model_family, result.task, result.seed) == ("xgboost", "ranking", 17)
    assert result.selection_metric_value == pytest.approx(0.4)
    assert max(ranks.values()) == 0.9


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "metric", "rank-missing", "rank-nan", "horizon"]
)
def test_missing_bad_or_mixed_seed_evidence_is_rejected_without_selecting_a_subset(change):
    metrics, reports, ranks, _ = evidence()
    index = next(
        i
        for i, x in enumerate(metrics)
        if x.model_family == "xgboost" and x.seed == 29 and x.task == "regression"
    )
    task = "regression"
    if change == "missing":
        metrics.pop(index)
    elif change == "duplicate":
        metrics.append(metrics[index])
    elif change == "metric":
        metrics[index] = metrics[index].model_copy(update={"mean_daily_rank_ic": None})
    elif change == "horizon":
        metrics[index] = metrics[index].model_copy(update={"horizon": 20})
    else:
        task = None
        key = selection._metric_component_name(metrics[index])
        if change == "rank-missing":
            ranks.pop(key)
        else:
            ranks[key] = float("nan")
    with pytest.raises(ValueError, match=r"seed|horizon"):
        selection._seed_stable_component(
            metrics, task=task, reports=reports, seeds=SEEDS, rank_ics=ranks
        )


def test_seed_input_order_cannot_change_the_representative_or_family_score():
    metrics, reports, _, _ = evidence()
    first = selection._seed_stable_component(
        metrics, task="regression", reports=reports, seeds=SEEDS
    )
    second = selection._seed_stable_component(
        list(reversed(metrics)), task="regression", reports=reports, seeds=(43, 17, 29)
    )
    assert first == second


@pytest.mark.parametrize("horizon", [5, 20])
def test_ensemble_must_still_beat_strongest_individual_not_weaker_fixed_seed(monkeypatch, horizon):
    _, _, ranks, runs = evidence(horizon)
    reference = next(
        x
        for x in _selection_fixture(build_id="a" * 64, dataset_id="b" * 64).horizons
        if x.horizon == horizon
    )
    names = tuple(sorted(ranks))
    ensemble = EnsembleResult.model_validate(
        {
            **reference.ensemble.model_dump(),
            "component_names": names,
            "weights": tuple(1 / len(names) for _ in names),
            "mean_daily_rank_ic": 0.5,
        }
    )
    monkeypatch.setattr(selection, "_aligned_rank_component_frame", lambda _runs: None)
    monkeypatch.setattr(
        selection,
        "_fit_selection_ensemble",
        lambda _wide, **_kw: (ensemble, reference.uncertainty, ranks),
    )
    result = selection._select_horizon(
        runs,
        feature_families=reference.feature_families,
        feature_names=reference.feature_names,
        stable_seeds=SEEDS,
    )
    assert result.rank_component.seed == 17
    assert result.rank_component.selection_metric_value == pytest.approx(0.4)
    assert result.ensemble_best_component_rank_ic == 0.9
    assert result.ensemble.mean_daily_rank_ic == 0.5
    assert not result.ensemble_adopted
