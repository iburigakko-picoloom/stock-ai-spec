from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.data.contracts import CapabilityStatus
from stock_ai.features import V0_MANIFEST, V2_EXTENDED_MANIFEST
from stock_ai.ml import advanced, production
from stock_ai.ml.daily_baselines import (
    BASELINES,
    _canonical,
    _write_parquet,
    evaluate_baseline_folds,
    fit_streamed_logistic,
    fit_streamed_ridge,
    run_daily_baselines,
)
from stock_ai.ml.models import RidgeRegressor
from stock_ai.ml.validation import PurgedExpandingWindowSplitter


@pytest.mark.parametrize("block_size", [1, 7, 127, 1000])
def test_streamed_ridge_matches_existing_median_scaler_ridge(block_size):
    rng = np.random.default_rng(17)
    x = rng.normal(size=(501, 7))
    x[:, 1] = 100_000_000 + 10 * x[:, 1]
    x[:, 2] = 7
    x[:, 3] = np.nan
    x[::3, 4] = np.nan
    y = 0.3 * x[:, 0] + (x[:, 1] - 100_000_000) * 0.02 + rng.normal(0, 0.01, len(x))
    medians = np.array(
        [np.nanmedian(x[:, i]) if np.isfinite(x[:, i]).any() else 0 for i in range(x.shape[1])]
    )
    model = fit_streamed_ridge(
        ((x[i : i + block_size], y[i : i + block_size]) for i in range(0, len(x), block_size)),
        medians,
    )
    baseline = RidgeRegressor(alpha=5).fit(pd.DataFrame(x), pd.Series(y))
    predict = x[:30].copy()
    predict[1, 0] = np.nan  # Missing only at validation must not add a learned indicator.
    np.testing.assert_allclose(
        model.predict(predict), baseline.predict(pd.DataFrame(predict)), atol=3e-8, rtol=3e-8
    )
    assert model.rows == len(x)
    assert np.isfinite(model.coefficient).all()


@pytest.mark.parametrize(
    "case", ["empty", "infinite_x", "infinite_y", "bad_width", "bad_y", "bad_median", "bad_alpha"]
)
def test_streamed_ridge_refuses_invalid_training(case):
    x, y, median, alpha = np.ones((2, 2)), np.ones(2), np.zeros(2), 5
    if case == "infinite_x":
        x[0, 0] = np.inf
    elif case == "infinite_y":
        y[0] = np.inf
    elif case == "bad_width":
        x = np.ones((2, 3))
    elif case == "bad_y":
        y = np.ones(3)
    elif case == "bad_median":
        median[0] = np.nan
    elif case == "bad_alpha":
        alpha = 0
    with pytest.raises(ValueError):
        fit_streamed_ridge([] if case == "empty" else [(x, y)], median, alpha=alpha)


def _dataset():
    dates = pd.bdate_range("2025-01-06", periods=150)
    rows = []
    for i, day in enumerate(dates):
        for j, symbol in enumerate(("A", "B", "C")):
            as_of = (day + pd.Timedelta(days=1)).tz_localize("Asia/Tokyo").to_pydatetime().replace(
                hour=11, minute=30
            )
            row = {
                "symbol": symbol,
                "trading_date": day,
                "as_of": as_of,
                "available_at": as_of,
                "historical_revision_policy": "SINGLE_VINTAGE_AS_REVISED",
                "historical_revision_status": "PARTIAL",
            }
            for k, feature in enumerate(V2_EXTENDED_MANIFEST.feature_names):
                row[feature] = ((i + 3 * j + k) % 37) * 0.01
            for horizon in (1, 5, 20):
                end = day + pd.offsets.BDay(horizon + 1)
                for family in ("return", "topix_excess", "sector_excess", "beta_residual"):
                    row[f"target_{family}_{horizon}d"] = j * 0.02 + 0.005 * np.sin(i / 5)
                    suffix = "" if family == "return" else f"_{family}"
                    row[f"label_status{suffix}_{horizon}d"] = "AVAILABLE"
                row[f"label_end_date_{horizon}d"] = end
                row[f"label_available_at_{horizon}d"] = end.tz_localize(
                    "Asia/Tokyo"
                ).to_pydatetime().replace(hour=16)
                row[f"target_large_loss_{horizon}d"] = 0
            rows.append(row)
    return pd.DataFrame(rows)


def _oof(frame, config, horizon, family, seed):
    endpoint, target = f"label_end_date_{horizon}d", f"target_return_{horizon}d"
    stage = advanced._split_research_stages(
        frame, horizon=horizon, label_end_column=endpoint, config=config
    )
    splitter = PurgedExpandingWindowSplitter(
        initial_train_periods=config.initial_train_periods,
        validation_periods=config.validation_periods,
        step_periods=config.step_periods,
        embargo_periods=horizon,
        label_horizon_periods=horizon,
    )
    parts = []
    for fold in splitter.split(frame, label_end_column=endpoint):
        part = frame.iloc[list(fold.validation_indices)]
        part = part.loc[part.trading_date >= stage.model_evaluation_start]
        if part.empty:
            continue
        part = part[["symbol", "trading_date", "as_of", endpoint, target]].rename(
            columns={endpoint: "label_end", target: "target"}
        )
        for task in ("regression", "ranking", "quantile", "large_loss"):
            prediction = 0.1 if task == "large_loss" else part.target + seed * 0.00001
            parts.append(
                part.assign(
                    horizon=horizon,
                    model_family=family,
                    seed=seed,
                    task=task,
                    fold=fold.fold_number,
                    prediction=prediction,
                    retained_feature_count=2,
                )
            )
    return pd.concat(parts, ignore_index=True).sort_values(
        ["horizon", "model_family", "task", "seed", "trading_date", "symbol"]
    ).reset_index(drop=True), stage.boundary


@pytest.fixture(scope="module")
def authentic(tmp_path_factory, request):
    import tests.test_research_selection as fixtures
    from stock_ai.ml.selection import (
        freeze_development_features,
        write_development_feature_selection,
    )

    tmp_path = tmp_path_factory.mktemp("baseline-authentic")
    monkeypatch = pytest.MonkeyPatch()
    request.addfinalizer(monkeypatch.undo)
    frame = _dataset()
    protected = frame.iloc[:5].copy()
    protected["symbol"] = [f"PROTECTED{i}" for i in range(5)]
    protected["trading_date"] = pd.bdate_range("2026-08-03", periods=5)
    dataset = pd.concat([frame, protected], ignore_index=True)
    instant = datetime(2026, 9, 1, tzinfo=UTC)
    snapshot = production.write_production_dataset_snapshot(
        dataset,
        tmp_path / "dataset",
        source_snapshot_as_of=instant,
        source_snapshot_ids=(("fixture", "source"),),
        as_of=instant,
        created_at=instant,
        label_1230_status=CapabilityStatus.BLOCKED_BY_DATA_CAPABILITY,
        manifests=(V2_EXTENDED_MANIFEST,),
    )
    original_run, original_marker = fixtures._run_fixture, fixtures._build_marker

    def wrapped_run(**kwargs):
        original = original_run(**kwargs)
        config = kwargs["config"]
        horizon, family, seed = config.horizons[0], config.model_families[0], config.seeds[0]
        oof, stage = _oof(frame, config, horizon, family, seed)
        folds = tuple(
            advanced.AdvancedFoldResult(
                horizon=horizon,
                model_family=family,
                seed=seed,
                task=str(task),
                fold=int(number),
                validation_start=str(part.trading_date.min().date()),
                validation_end=str(part.trading_date.max().date()),
                rows=len(part),
                mean_squared_error=0,
                mean_daily_rank_ic=1,
            )
            for (task, number), part in oof.groupby(["task", "fold"])
        )
        report = original.report.model_copy(
            update={
                "data_snapshot_id": snapshot.snapshot_id,
                "stage_boundaries": (stage,),
                "fold_results": folds,
                "oof_rows": len(oof),
                "oof_sha256": advanced._frame_hash(oof),
            }
        )
        report = report.model_copy(
            update={"report_id": advanced._stable_hash(advanced._report_identity(report))}
        )
        return advanced.AdvancedResearchRun(report, oof)

    def wrapped_marker(path):
        _, old_path = original_marker(path)
        payload = json.loads(old_path.read_text(encoding="utf-8"))
        payload["dataset_snapshot_id"] = snapshot.snapshot_id
        identity = {
            k: v
            for k, v in payload.items()
            if k.endswith("snapshot_id") or k in ("source_snapshot_ids", "source_snapshot_as_of")
        }
        build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        new_path = (path / "builds" / build_id / f"{build_id}.json").resolve()
        new_path.parent.mkdir(parents=True)
        payload.update(build_id=build_id, manifest_path=str(new_path))
        payload["metadata_hash"] = production._metadata_hash(payload)
        new_path.write_text(json.dumps(payload), encoding="utf-8")
        return build_id, new_path

    monkeypatch.setattr(fixtures, "_run_fixture", wrapped_run)
    monkeypatch.setattr(fixtures, "_build_marker", wrapped_marker)
    ablation, candidate = fixtures._campaign_fixtures(tmp_path)
    features = freeze_development_features(ablation_campaign_paths=(ablation,))
    feature_path = write_development_feature_selection(features, tmp_path / "features")
    manifest = json.loads(candidate.read_text(encoding="utf-8"))
    batch = next(b for b in manifest["batches"] if b["horizon"] == 20)
    report, oof = advanced.load_advanced_research_run(Path(batch["oof_path"]))
    return (
        dict(
            feature_selection_path=feature_path,
            campaign_paths=(candidate,),
            dataset_path=snapshot.parquet_path,
        ),
        frame,
        report,
        oof.loc[oof.task == "regression"],
    )


def _evaluate(frame, report, reference):
    with duckdb.connect() as connection:
        connection.register("source", frame)
        return evaluate_baseline_folds(connection, report, reference, batch_rows=41)


def test_same_fold_baselines_authenticate_all_candidates_and_save_replay(authentic, tmp_path):
    request, _, report, _ = authentic
    path = run_daily_baselines(**request, output_root=tmp_path / "output", batch_rows=41)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert [r["horizon"] for r in receipt["results"]] == [5, 20]
    for result in receipt["results"]:
        assert len(result["candidates"]) == 9
        oof = pd.read_parquet(result["oof_path"])
        assert not oof.symbol.str.startswith("PROTECTED").any()
        assert oof.trading_date.max() < pd.Timestamp(receipt["locked_holdout_start"])
        assert oof.zero_return.eq(0).all()
        assert oof.equal_weight_candidate_mean.notna().all()
        assert set(result["baseline_scores"]) == {*BASELINES, "equal_weight_candidate_mean"}
        assert set(result["baseline_risk_scores"]) == {
            "training_loss_rate", "logistic_v0", "training_quantile"
        }
        assert (
            result["risk_definition"]["large_loss_threshold"] == report.config.large_loss_threshold
        )
        assert result["risk_definition"]["quantile_alpha"] == report.config.quantile_alpha
        assert result["equal_weight_risk_scores"]["large_loss"]["rows"] == len(oof)
        assert not result["equal_weight_risk_scores"]["quantile"]["crossing_check_available"]
        assert all(c["risk_scores"]["large_loss"]["rows"] == len(oof)
                   for c in result["candidates"])
        for fold in result["folds"]:
            assert pd.Timestamp(fold["latest_training_label_available_at"]) < pd.Timestamp(
                fold["fit_cutoff"]
            )
            assert fold["ridge"]["rows"] == fold["training_rows"]
            assert fold["logistic"]["rows"] == fold["training_rows"]
    assert receipt["holdout_scored"] is False and receipt["adoption_eligible"] is False


def test_future_validation_values_do_not_change_past_fits(authentic):
    _, frame, report, reference = authentic
    before, fits_before = _evaluate(frame, report, reference)
    modified = frame.copy()
    last_date = before.trading_date.max()
    modified.loc[modified.trading_date == last_date, list(V0_MANIFEST.feature_names)] *= 20
    after, fits_after = _evaluate(modified, report, reference)
    assert fits_before[-1]["ridge"] == fits_after[-1]["ridge"]
    assert fits_before[-1]["logistic"] == fits_after[-1]["logistic"]
    pd.testing.assert_frame_equal(
        before.loc[before.trading_date < last_date], after.loc[after.trading_date < last_date]
    )
    assert not before.ridge_v0.equals(after.ridge_v0)


@pytest.mark.parametrize(
    "change,error",
    [
        ("target", "keys, targets"),
        ("missing", "keys, targets"),
        ("fold", "keys, targets"),
        ("late_label", "unavailable"),
        ("late_feature", "unavailable"),
        ("infinite_feature", "nonfinite"),
        ("boundary", "boundary differs"),
    ],
)
def test_fold_alignment_and_causality_fail_closed(authentic, change, error):
    _, frame, report, reference = authentic
    frame, reference = frame.copy(), reference.copy()
    if change == "target":
        reference.iloc[0, reference.columns.get_loc("target")] += 1
    elif change == "missing":
        reference = reference.iloc[1:]
    elif change == "fold":
        reference.iloc[0, reference.columns.get_loc("fold")] += 1
    elif change == "late_label":
        frame.loc[0, "label_available_at_20d"] = pd.Timestamp("2030-01-01", tz="UTC")
    elif change == "late_feature":
        frame.loc[0, "available_at"] = pd.Timestamp("2030-01-01", tz="UTC")
    elif change == "infinite_feature":
        frame.loc[0, "price.return_20d"] = np.inf
    elif change == "boundary":
        report = report.model_copy(update={"stage_boundaries": ()})
    with pytest.raises(ValueError, match=error):
        _evaluate(frame, report, reference)


def test_missing_candidate_and_changed_dataset_refused(authentic, tmp_path):
    request, _, _, _ = authentic
    with pytest.raises(ValueError, match="matrix is incomplete"):
        run_daily_baselines(**{**request, "campaign_paths": ()}, output_root=tmp_path / "none")
    with pytest.raises(ValueError, match="duplicate"):
        run_daily_baselines(
            **{**request, "campaign_paths": request["campaign_paths"] * 2},
            output_root=tmp_path / "duplicate",
        )
    path = request["dataset_path"]
    original_bytes = path.read_bytes()
    data = pd.read_parquet(path)
    data.loc[0, "price.return_20d"] += 1
    try:
        data.to_parquet(path)
        with pytest.raises(RuntimeError, match=r"hash|metadata"):
            run_daily_baselines(**request, output_root=tmp_path / "changed")
    finally:
        path.write_bytes(original_bytes)


def test_output_identity_and_invalid_keys(tmp_path):
    frame = pd.DataFrame({"x": [1, 2]})
    path = _write_parquet(frame, tmp_path)
    assert _write_parquet(frame, tmp_path) == path
    path.write_bytes(b"bad")
    with pytest.raises(ValueError, match="identity"):
        _write_parquet(frame, tmp_path)
    data = pd.DataFrame(
        dict(
            trading_date=["2025-01-01"] * 2,
            symbol=["A"] * 2,
            as_of=["2025-01-02T11:30:00+09:00"] * 2,
            label_end=["2025-02-01"] * 2,
            target=[1, 1],
            fold=[1, 1],
        )
    )
    with pytest.raises(ValueError, match="duplicate"):
        _canonical(data)


def test_cli_retains_failed_run(authentic, tmp_path):
    request, _, _, _ = authentic
    # The same manifest twice must fail, with an immutable started/failed record.
    args = [
        "research",
        "compare-daily-baselines",
        "--feature-selection",
        str(request["feature_selection_path"]),
        "--dataset",
        str(request["dataset_path"]),
        "--output-root",
        str(tmp_path / "cli"),
    ]
    for _ in range(2):
        args += ["--candidate-campaign", str(request["campaign_paths"][0])]
    run = CliRunner().invoke(app, args)
    assert run.exit_code == 2
    statuses = {
        json.loads(p.read_text(encoding="utf-8"))["status"]
        for p in (tmp_path / "cli" / "runs").glob("*.json")
    }
    assert statuses == {"STARTED", "FAILED"}


@pytest.mark.parametrize("batch_rows,c", [(17, 1.0), (1000, 1.0), (127, 0.3)])
def test_disk_logistic_matches_independent_sklearn_pipeline(batch_rows, c):
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(18)
    x = rng.normal(size=(901, 7))
    event = rng.random(len(x)) < 1 / (1 + np.exp(-(1.2 * x[:, 0] - x[:, 1] - 0.5)))
    x[:, 2] = 5
    x[:, 3] = np.nan
    x[::4, 4] = np.nan
    x[:, 5] = x[:, 5] * 0.01 + 1_000_000
    target = np.where(event, -0.05, 0.1)  # Event threshold is inclusive.
    medians = np.array([
        np.nanmedian(x[:, j]) if np.isfinite(x[:, j]).any() else 0 for j in range(x.shape[1])
    ])
    transform = fit_streamed_ridge([(x, target)], medians)
    batches = ((x[i:i + batch_rows], target[i:i + batch_rows])
               for i in range(0, len(x), batch_rows))
    model = fit_streamed_logistic(batches, transform, threshold=-0.05, batch_rows=batch_rows, c=c)
    reference = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
        StandardScaler(), LogisticRegression(C=c, max_iter=5000, tol=1e-10),
    ).fit(x, event)
    validation = x[:70].copy()
    validation[0, 0] = np.nan
    np.testing.assert_allclose(
        model.predict(validation, transform), reference.predict_proba(validation)[:, 1],
        atol=2e-6, rtol=2e-6,
    )
    assert model.events == int(event.sum())
    assert model.rows == len(x) and model.constant_probability is None
    assert model.gradient_max <= 1e-6
    assert 0 < model.iterations < 500


@pytest.mark.parametrize("event", [0, 1])
def test_single_class_logistic_is_explicit_constant(event):
    x = np.arange(12, dtype=float).reshape(6, 2)
    y = np.full(6, -0.05 if event else 0.1)
    transform = fit_streamed_ridge([(x, y)], np.median(x, axis=0))
    model = fit_streamed_logistic([(x, y)], transform, threshold=-0.05)
    np.testing.assert_equal(model.predict(x, transform), np.full(6, event))
    assert model.constant_probability == event and model.iterations == 0
    assert model.objective is None


@pytest.mark.parametrize("case", ["rows", "target", "c", "threshold", "batch", "convergence"])
def test_logistic_refuses_bad_inputs_or_unconverged_fits(case):
    rng = np.random.default_rng(17)
    x = rng.normal(size=(200, 3))
    y = np.where(x[:, 0] + 0.3 * x[:, 1] > 0, -0.1, 0.1)
    transform = fit_streamed_ridge([(x, y)], np.median(x, axis=0))
    kwargs = dict(threshold=-0.05)
    if case == "rows":
        x, y = x[:-1], y[:-1]
    elif case == "target":
        y[0] = np.nan
    elif case == "c":
        kwargs["c"] = 0
    elif case == "threshold":
        kwargs["threshold"] = np.inf
    elif case == "batch":
        kwargs["batch_rows"] = 0
    elif case == "convergence":
        kwargs["max_iterations"] = 1
    with pytest.raises(ValueError):
        fit_streamed_logistic([(x, y)], transform, **kwargs)


def test_distribution_baselines_use_only_original_training_rows(authentic):
    _, frame, report, reference = authentic
    before, fits = _evaluate(frame, report, reference)
    for fit in fits:
        training = frame.loc[
            (frame.trading_date <= pd.Timestamp(fit["train_end"]))
            & (frame.label_end_date_20d < pd.Timestamp(fit["original_validation_start"]))
        ]
        expected = training.target_return_20d.quantile(report.config.quantile_alpha)
        assert fit["training_quantile"] == pytest.approx(expected)
        assert fit["training_loss_rate"] == pytest.approx(
            (training.target_return_20d <= report.config.large_loss_threshold).mean()
        )
        np.testing.assert_allclose(
            before.loc[before.fold == fit["fold"], "training_quantile"], expected,
            rtol=1e-14, atol=1e-14,
        )
    # Alter only the last validation outcomes, keeping exact reference labels aligned.
    modified, ref = frame.copy(), reference.copy()
    last_date = before.trading_date.max()
    modified.loc[modified.trading_date == last_date, "target_return_20d"] = -0.9
    ref.loc[ref.trading_date == last_date, "target"] = -0.9
    after, later_fits = _evaluate(modified, report, ref)
    for first, second in zip(fits, later_fits, strict=True):
        for key in ("ridge", "logistic", "training_quantile", "training_loss_rate"):
            assert first[key] == second[key]
    for column in (*BASELINES, "training_loss_rate", "training_quantile", "logistic_v0"):
        np.testing.assert_equal(before[column].to_numpy(), after[column].to_numpy())


def test_risk_as_of_must_match_regression_even_after_bundle_authentication(
    authentic, tmp_path, monkeypatch
):
    import stock_ai.ml.daily_baselines as module

    request, _, _, _ = authentic
    original = module.load_advanced_research_run

    def changed(path):
        report, oof = original(path)
        mask = oof.task == "large_loss"
        oof.loc[mask, "as_of"] += pd.Timedelta(hours=1)
        return report, oof

    monkeypatch.setattr(module, "load_advanced_research_run", changed)
    with pytest.raises(ValueError, match="risk task keys"):
        run_daily_baselines(**request, output_root=tmp_path / "changed-as-of")
