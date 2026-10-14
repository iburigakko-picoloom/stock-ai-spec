"""Forward cross-fitted daily ensembles; no selection or holdout evaluation."""

from __future__ import annotations

import gc
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import asdict
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression

from stock_ai.ml.advanced import (
    AdvancedResearchReport,
    _authenticate_advanced_research_bundle,
    load_advanced_research_run,
)
from stock_ai.ml.campaign import CampaignBatchStatus, load_campaign_manifest
from stock_ai.ml.daily_baselines import KEYS, _canonical, _write_parquet
from stock_ai.ml.evaluation_audit import validate_development_oof, write_audit_receipt
from stock_ai.ml.evaluation_metrics import (
    METRIC_VERSION,
    evaluate_probabilities,
    evaluate_quantiles,
    evaluate_ranking_panel,
)
from stock_ai.ml.production import _file_sha256, load_production_dataset_snapshot
from stock_ai.ml.research_metrics import within_date_rank_standardize
from stock_ai.ml.selection import _authenticate_batch_report, load_development_feature_selection

VERSION = "daily-forward-crossfit-v1"
TASKS = ("regression", "ranking", "large_loss", "quantile")
FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


def fit_simplex(
    matrix: FloatArray,
    target: FloatArray,
    mask: BoolArray,
    *,
    batch_rows: int = 32_768,
    max_iterations: int = 500,
) -> dict[str, Any]:
    """Exact row-equal quadratic objective, accumulated in bounded blocks.

    One common target centering/scaling preserves raw MSE on the simplex.
    The reported dual gap checks convex optimality, not just optimizer status.
    """
    if (
        matrix.ndim != 2
        or matrix.shape[1] < 1
        or target.shape != (len(matrix),)
        or mask.shape != target.shape
        or mask.dtype != np.bool_
        or not mask.any()
        or batch_rows < 1
        or max_iterations < 1
        or not np.isfinite(matrix).all()
        or not np.isfinite(target).all()
    ):
        raise ValueError("invalid simplex training input")
    rows = np.flatnonzero(mask)
    center, scale = float(target[rows].mean()), float(target[rows].std())
    scale = scale if scale > 1e-12 else 1.0
    width = matrix.shape[1]
    gram, cross, square = np.zeros((width, width)), np.zeros(width), 0.0
    for offset in range(0, len(rows), batch_rows):
        indices = rows[offset : offset + batch_rows]
        x, y = (matrix[indices] - center) / scale, (target[indices] - center) / scale
        gram += x.T @ x
        cross += x.T @ y
        square += float(y @ y)
    gram, cross, square = gram / len(rows), cross / len(rows), square / len(rows)

    def objective(w: FloatArray) -> tuple[float, FloatArray]:
        return float(w @ gram @ w - 2 * w @ cross + square), 2 * (gram @ w - cross)

    result = minimize(
        objective,
        np.full(width, 1 / width),
        jac=True,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * width,
        constraints={"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(width)},
        options={"maxiter": max_iterations, "ftol": 1e-12},
    )
    weights = np.asarray(result.x, dtype=float)
    if (
        not result.success
        or not np.isfinite(weights).all()
        or weights.min() < -1e-10
        or abs(weights.sum() - 1) > 1e-8
    ):
        raise ValueError(f"simplex optimizer failed: {result.message}")
    weights = np.maximum(weights, 0)
    weights /= weights.sum()
    _, gradient = objective(weights)
    gap = float(weights @ gradient - gradient.min())
    if not np.isfinite(gap) or gap > 2e-6:
        raise ValueError(f"simplex optimality gap too large: {gap}")
    # Direct residuals avoid cancellation in an almost perfectly fitted Gram loss.
    mse = sum(
        float(np.square(matrix[indices] @ weights - target[indices]).sum())
        for indices in (rows[i : i + batch_rows] for i in range(0, len(rows), batch_rows))
    ) / len(rows)
    return {
        "weights": weights.tolist(),
        "rows": len(rows),
        "iterations": int(result.nit),
        "mse": mse,
        "normalized_dual_gap": gap,
        "target_center": center,
        "target_scale": scale,
        "converged": True,
    }


def _aware(values: pd.Series) -> pd.Series:
    if values.isna().any() or any(pd.Timestamp(v).tzinfo is None for v in values.unique()):
        raise ValueError("ensemble timestamps must be nonmissing and timezone-aware")
    return pd.to_datetime(values, utc=True).astype("datetime64[ns, UTC]")


def validate_panel(frame: pd.DataFrame, *, holdout_start: str) -> pd.DataFrame:
    """Require exact ordered rows: silently sorting could misalign prediction arrays."""
    if frame.empty:
        raise ValueError("empty ensemble panel")
    _aware(frame.as_of)
    canonical = _canonical(frame)
    original_keys = frame[["trading_date", "symbol"]].reset_index(drop=True).copy()
    original_keys["trading_date"] = pd.to_datetime(original_keys.trading_date).astype(
        "datetime64[ns]"
    )
    if not original_keys.equals(canonical[["trading_date", "symbol"]]):
        raise ValueError("ensemble panel must be sorted by date and symbol")
    for name in ("label_available_at", "available_at"):
        canonical[name] = _aware(frame[name]).to_numpy()
        canonical[name] = pd.to_datetime(canonical[name], utc=True)
    dates, endpoints = canonical.trading_date, canonical.label_end
    local_as_of = canonical.as_of.dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    end_midnight = endpoints.dt.tz_localize("Asia/Tokyo").dt.tz_convert("UTC")
    if (
        (dates != dates.dt.normalize()).any()
        or (endpoints != endpoints.dt.normalize()).any()
        or (dates >= pd.Timestamp(holdout_start)).any()
        or (endpoints >= pd.Timestamp(holdout_start)).any()
        or (endpoints <= dates).any()
        or (local_as_of.dt.normalize() <= dates).any()
        or (end_midnight <= canonical.as_of).any()
        or (canonical.available_at > canonical.as_of).any()
        or (canonical.label_available_at < end_midnight).any()
        or not np.isfinite(canonical.target).all()
        or not canonical.groupby("trading_date").as_of.nunique().eq(1).all()
    ):
        raise ValueError("invalid development panel timing, target or holdout boundary")
    day_as_of = canonical.groupby("trading_date").as_of.first()
    if not day_as_of.is_monotonic_increasing or day_as_of.duplicated().any():
        raise ValueError("daily decision timestamps must increase strictly")
    return canonical


def _mask_audit(frame: pd.DataFrame, mask: BoolArray) -> dict[str, Any]:
    part = frame.loc[mask]
    key_bytes = part[KEYS].to_json(orient="records", date_format="iso", date_unit="ns").encode()
    return {
        "rows": len(part),
        "dates": int(part.trading_date.nunique()),
        "start": str(part.trading_date.min().date()),
        "end": str(part.trading_date.max().date()),
        "latest_label_end": str(part.label_end.max().date()),
        "latest_label_available_at": part.label_available_at.max().isoformat(),
        "key_target_sha256": hashlib.sha256(key_bytes).hexdigest(),
    }


def forward_splits(
    frame: pd.DataFrame,
    *,
    horizon: int,
) -> list[tuple[BoolArray, BoolArray, BoolArray, dict[str, Any]]]:
    """Three fixed later evaluation blocks, with disjoint matured fit/calibration."""
    if horizon not in (5, 20):
        raise ValueError("daily crossfit supports only 5d and 20d")
    dates = pd.DatetimeIndex(frame.trading_date.unique()).sort_values()
    n, width = len(dates), len(dates) // 5
    boundaries = [n // 2, 2 * n // 3, 5 * n // 6, n]
    result: list[tuple[BoolArray, BoolArray, BoolArray, dict[str, Any]]] = []
    for number, (start, stop) in enumerate(pairwise(boundaries), 1):
        cal_start = start - width
        if min(cal_start - horizon, width - horizon, stop - start) < 1:
            raise ValueError("insufficient dates for forward calibration and embargo")
        cal_cutoff = frame.loc[frame.trading_date == dates[cal_start], "as_of"].iloc[0]
        eval_cutoff = frame.loc[frame.trading_date == dates[start], "as_of"].iloc[0]
        fit_window = frame.trading_date < dates[cal_start]
        cal_window = (frame.trading_date >= dates[cal_start]) & (frame.trading_date < dates[start])
        fit = (
            fit_window
            & (frame.trading_date < dates[cal_start - horizon])
            & (frame.label_end < dates[cal_start])
            & (frame.label_available_at < cal_cutoff)
        )
        cal = (
            cal_window
            & (frame.trading_date < dates[start - horizon])
            & (frame.label_end < dates[start])
            & (frame.label_available_at < eval_cutoff)
        )
        evaluate = (frame.trading_date >= dates[start]) & (frame.trading_date <= dates[stop - 1])
        if min(frame.loc[fit].trading_date.nunique(), frame.loc[cal].trading_date.nunique()) < 20:
            raise ValueError("at least 20 eligible dates required in every fit/calibration block")
        masks = tuple(m.to_numpy(bool) for m in (fit, cal, evaluate))
        audit = {
            "meta_fold": number,
            "fit": _mask_audit(frame, masks[0]),
            "calibration": _mask_audit(frame, masks[1]),
            "evaluation": _mask_audit(frame, masks[2]),
            "weight_fit_cutoff": cal_cutoff.isoformat(),
            "calibration_cutoff": eval_cutoff.isoformat(),
            "embargo_observed_dates": horizon,
            "fit_excluded_rows": int(fit_window.sum() - fit.sum()),
            "calibration_excluded_rows": int(cal_window.sum() - cal.sum()),
        }
        result.append((masks[0], masks[1], masks[2], audit))
    return result


def fit_calibration(
    rank: FloatArray,
    probability: FloatArray,
    quantile: FloatArray,
    target: FloatArray,
    *,
    threshold: float,
    alpha: float,
) -> dict[str, Any]:
    """Fit only the caller's disjoint calibration window; keep return units explicit."""
    x_center, y_center = float(rank.mean()), float(target.mean())
    centered = rank - x_center
    variance = float(centered @ centered)
    slope = max(0.0, float(centered @ (target - y_center)) / variance) if variance > 1e-20 else 0.0
    intercept = y_center - slope * x_center
    event = (target <= threshold).astype(float)
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(probability, event)
    residual = target - (intercept + slope * rank)
    return {
        "rows": len(target),
        "rank_to_return": {"slope": slope, "intercept": intercept},
        "isotonic": {
            "x": iso.X_thresholds_.tolist(),
            "y": iso.y_thresholds_.tolist(),
            "events": int(event.sum()),
            "single_class": len(np.unique(event)) == 1,
        },
        "quantile_offset": float(np.quantile(target - quantile, alpha, method="linear")),
        "return_residual": {
            "rmse": float(np.sqrt(np.mean(residual**2))),
            "absolute_q80": float(np.quantile(abs(residual), 0.8)),
            "absolute_q90": float(np.quantile(abs(residual), 0.9)),
        },
    }


def _ranking(frame: pd.DataFrame, values: FloatArray, *, return_units: bool) -> dict[str, Any]:
    audit = asdict(evaluate_ranking_panel(frame.assign(prediction=values)))
    if audit["excluded_rows"]:
        raise ValueError("ensemble metrics may not silently discard observations")
    if not return_units and audit["metrics"] is not None:
        del audit["metrics"]["mean_squared_error"]
    audit["prediction_units"] = "fractional_return" if return_units else "rank_score"
    return audit


def _correlation(left: FloatArray, right: FloatArray) -> float | None:
    a, b = left - left.mean(), right - right.mean()
    denominator = float(np.sqrt((a @ a) * (b @ b)))
    return float(np.clip(a @ b / denominator, -1, 1)) if denominator > 1e-20 else None


def score_ensemble(
    frame: pd.DataFrame,
    matrices: dict[str, FloatArray],
    names: Sequence[str],
    *,
    threshold: float,
    alpha: float,
) -> dict[str, Any]:
    y = frame.target.to_numpy(float)
    event = (y <= threshold).astype(float).tolist()
    metrics: dict[str, Any] = {task: {} for task in TASKS}
    for task, matrix in matrices.items():
        values = {name: matrix[:, i] for i, name in enumerate(names)}
        if task == "regression":
            values.update(
                {
                    name: frame[name].to_numpy(float)
                    for name in ("uniform_return", "weighted_return", "rank_calibrated_return")
                }
            )
        elif task == "ranking":
            values.update(
                {name: frame[name].to_numpy(float) for name in ("uniform_rank", "weighted_rank")}
            )
        elif task == "large_loss":
            values.update(
                {
                    name: frame[name].to_numpy(float)
                    for name in (
                        "uniform_probability",
                        "weighted_probability",
                        "calibrated_probability",
                    )
                }
            )
        else:
            values.update(
                {
                    name: frame[name].to_numpy(float)
                    for name in ("uniform_quantile", "calibrated_quantile")
                }
            )
        for name, prediction in values.items():
            if task in ("regression", "ranking"):
                metrics[task][name] = _ranking(frame, prediction, return_units=task == "regression")
            elif task == "large_loss":
                metrics[task][name] = asdict(evaluate_probabilities(event, prediction.tolist()))
            else:
                metrics[task][name] = asdict(
                    evaluate_quantiles(y.tolist(), [alpha], prediction.reshape(-1, 1).tolist())
                )
    error = abs(y - frame.rank_calibrated_return.to_numpy(float))
    metrics["uncertainty"] = {
        "rows": len(frame),
        "units": "fractional_return",
        "absolute_q80_coverage": float((error <= frame.return_absolute_q80).mean()),
        "absolute_q90_coverage": float((error <= frame.return_absolute_q90).mean()),
        "rmse_error_pearson": _correlation(frame.return_residual_rmse.to_numpy(float), error),
        "disagreement_error_pearson": _correlation(
            frame.return_disagreement.to_numpy(float), error
        ),
        "interpretation": "calibration residual scale, not standard error or coverage guarantee",
    }
    return metrics


def crossfit_panel(
    frame: pd.DataFrame,
    matrices: dict[str, FloatArray],
    names: Sequence[str],
    *,
    horizon: int,
    threshold: float,
    alpha: float,
    holdout_start: str,
    batch_rows: int = 32_768,
    progress: Callable[[str], None] = lambda _message: None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = validate_panel(frame, holdout_start=holdout_start)
    if (
        set(matrices) != set(TASKS)
        or not names
        or len(names) != len(set(names))
        or not np.isfinite(threshold)
        or threshold >= 0
        or not 0 < alpha < 0.5
        or any(
            m.shape != (len(frame), len(names)) or not np.isfinite(m).all()
            for m in matrices.values()
        )
        or ((matrices["large_loss"] < 0) | (matrices["large_loss"] > 1)).any()
    ):
        raise ValueError("invalid aligned candidate matrices or risk definitions")
    splits = forward_splits(frame, horizon=horizon)
    # Cross-sectional transforms use that date's predictions only, never outcomes.
    rank_matrix = np.column_stack(
        [
            within_date_rank_standardize(pd.Series(matrix[:, i]), frame.trading_date)
            for matrix in (matrices["regression"], matrices["ranking"])
            for i in range(len(names))
        ]
    )
    target = frame.target.to_numpy(float)
    event = (target <= threshold).astype(float)
    output, audits = [], []
    for fit, cal, evaluate, audit in splits:
        progress(f"{horizon}d meta fold {audit['meta_fold']}: fit weights, calibrate, evaluate")
        # Unreceived peers' labels must not affect a received row's rank target.
        rank_target = np.zeros(len(frame))
        rank_target[fit] = within_date_rank_standardize(
            frame.loc[fit, "target"], frame.loc[fit, "trading_date"]
        )
        models = {
            "return": fit_simplex(matrices["regression"], target, fit, batch_rows=batch_rows),
            "rank": fit_simplex(rank_matrix, rank_target, fit, batch_rows=batch_rows),
            "probability": fit_simplex(matrices["large_loss"], event, fit, batch_rows=batch_rows),
        }
        rank = rank_matrix @ np.array(models["rank"]["weights"])
        probability = matrices["large_loss"] @ np.array(models["probability"]["weights"])
        quantile = matrices["quantile"].mean(axis=1)
        calibration = fit_calibration(
            rank[cal],
            probability[cal],
            quantile[cal],
            target[cal],
            threshold=threshold,
            alpha=alpha,
        )
        part = frame.loc[evaluate].copy()
        part["meta_fold"] = audit["meta_fold"]
        part["uniform_return"] = matrices["regression"][evaluate].mean(axis=1)
        part["weighted_return"] = matrices["regression"][evaluate] @ np.array(
            models["return"]["weights"]
        )
        part["uniform_rank"] = rank_matrix[evaluate].mean(axis=1)
        part["weighted_rank"] = rank[evaluate]
        mapping, isotonic = calibration["rank_to_return"], calibration["isotonic"]
        part["rank_calibrated_return"] = mapping["intercept"] + mapping["slope"] * rank[evaluate]
        part["uniform_probability"] = matrices["large_loss"][evaluate].mean(axis=1)
        part["weighted_probability"] = probability[evaluate]
        part["calibrated_probability"] = np.interp(
            probability[evaluate], isotonic["x"], isotonic["y"]
        )
        part["uniform_quantile"] = quantile[evaluate]
        part["calibrated_quantile"] = quantile[evaluate] + calibration["quantile_offset"]
        part["return_disagreement"] = matrices["regression"][evaluate].std(axis=1)
        for key, value in calibration["return_residual"].items():
            column = "return_residual_rmse" if key == "rmse" else f"return_{key}"
            part[column] = value
        audit.update(
            models=models,
            calibration_model=calibration,
            scores=score_ensemble(
                part,
                {t: m[evaluate] for t, m in matrices.items()},
                names,
                threshold=threshold,
                alpha=alpha,
            ),
        )
        audits.append(audit)
        output.append(part)
    result = pd.concat(output).sort_index()
    if result.index.duplicated().any():
        raise ValueError("crossfit evaluation rows overlap")
    evaluation_matrices = {t: m[result.index] for t, m in matrices.items()}
    correlations = {
        t: [[_correlation(m[:, i], m[:, j]) for j in range(len(names))] for i in range(len(names))]
        for t, m in evaluation_matrices.items()
    }
    # Preserve exact source candidate values alongside the new predictions for replay.
    for task, matrix in evaluation_matrices.items():
        for i, name in enumerate(names):
            result[f"{task}__{name}"] = matrix[:, i]
    return result.reset_index(drop=True), {
        "horizon": horizon,
        "input_rows": len(frame),
        "evaluation_rows": len(result),
        "burn_in_rows": len(frame) - len(result),
        "candidate_order": list(names),
        "rank_component_order": [
            f"{task}__{name}" for task in ("regression", "ranking") for name in names
        ],
        "folds": audits,
        "component_pearson_correlations": correlations,
        "scores": score_ensemble(
            result, evaluation_matrices, names, threshold=threshold, alpha=alpha
        ),
        "large_loss_threshold": threshold,
        "quantile_alpha": alpha,
    }


def run_daily_ensemble(
    *,
    feature_selection_path: Path,
    campaign_paths: Sequence[Path],
    dataset_path: Path,
    output_root: Path,
    batch_rows: int = 32_768,
    progress: Callable[[str], None] = lambda _message: None,
) -> Path:
    features = load_development_feature_selection(feature_selection_path)
    input_hashes = {
        str(p.resolve()): _file_sha256(p)
        for p in (feature_selection_path, dataset_path, *campaign_paths)
    }
    progress("authenticate full dataset logical identity (no holdout scoring)")
    snapshot, keys = load_production_dataset_snapshot(
        dataset_path, columns=("symbol", "trading_date")
    )
    del keys
    if snapshot.snapshot_id != features.data_snapshot_id:
        raise ValueError("ensemble dataset differs from frozen feature selection")
    runs: dict[tuple[int, str, int], tuple[AdvancedResearchReport, Path]] = {}
    for path in campaign_paths:
        manifest = load_campaign_manifest(path)
        for batch in manifest.batches:
            if batch.horizon not in (5, 20):
                continue
            if (
                batch.status is not CampaignBatchStatus.SUCCEEDED
                or batch.oof_path is None
                or batch.seed is None
            ):
                raise ValueError("ensemble requires successful candidate artifacts")
            source = Path(batch.oof_path)
            _, report, digest = _authenticate_advanced_research_bundle(source)
            _authenticate_batch_report(manifest, batch, report)
            selected = next(item for item in features.horizons if item.horizon == batch.horizon)
            if (
                report.feature_names != selected.feature_names
                or report.data_snapshot_id != features.data_snapshot_id
                or report.feature_snapshot_id != features.feature_snapshot_id
                or report.feature_manifest_hash != features.feature_manifest_hash
                or report.locked_holdout_start != features.locked_holdout_start
                or report.config.holdout_periods != features.holdout_periods
                or report.config.run_ablations
                or manifest.build_id != features.build_id
            ):
                raise ValueError("ensemble candidate differs from frozen data/features")
            key = (batch.horizon, batch.model_family, int(batch.seed))
            if key in runs:
                raise ValueError("duplicate ensemble candidate")
            runs[key] = report, source
            input_hashes[str(source.resolve())] = digest
    expected = {
        (h, f, s)
        for h in (5, 20)
        for f in ("lightgbm", "xgboost", "catboost")
        for s in features.seeds
    }
    if set(runs) != expected:
        raise ValueError("ensemble candidate matrix is incomplete")
    results = []
    for horizon in (5, 20):
        reference: pd.DataFrame | None = None
        reference_report: AdvancedResearchReport | None = None
        columns: dict[str, list[FloatArray]] = {task: [] for task in TASKS}
        names, report_ids = [], []
        for key, (declared, path) in sorted(runs.items()):
            if key[0] != horizon:
                continue
            progress(f"authenticate {horizon}d {key[1]} seed {key[2]} and all task keys")
            report, full = load_advanced_research_run(path)
            if report != declared:
                raise ValueError("candidate report changed during ensemble evaluation")
            validate_development_oof(full, report)
            _aware(full.as_of)
            for task in TASKS:
                part = full.loc[full.task == task].sort_values(["trading_date", "symbol"])
                canonical = _canonical(part)
                if reference is None:
                    reference, reference_report = canonical, report
                if not canonical.equals(reference):
                    raise ValueError("candidate/task keys, targets, as_of or folds differ")
                columns[task].append(part.prediction.to_numpy(float, copy=True))
            assert reference_report is not None
            if report.stage_boundaries != reference_report.stage_boundaries or any(
                getattr(report.config, name) != getattr(reference_report.config, name)
                for name in (
                    "initial_train_periods",
                    "validation_periods",
                    "step_periods",
                    "large_loss_threshold",
                    "quantile_alpha",
                )
            ):
                raise ValueError("candidate split/risk rules differ")
            names.append(f"{key[1]}_s{key[2]}")
            report_ids.append(report.report_id)
            del full, part, canonical
            gc.collect()
        assert reference is not None and reference_report is not None
        with duckdb.connect(config={"threads": 1, "memory_limit": "512MB"}) as connection:
            connection.register("oof_keys", reference[["symbol", "trading_date"]])
            available = connection.execute(
                f"""
                SELECT d.symbol, d.trading_date, d.as_of, d.available_at,
                       d.target_return_{horizon}d AS target,
                       d.label_end_date_{horizon}d AS label_end,
                       d.label_available_at_{horizon}d AS label_available_at
                FROM read_parquet(?) d JOIN oof_keys k
                ON d.symbol=k.symbol AND d.trading_date=k.trading_date
                WHERE d.trading_date < CAST(? AS TIMESTAMP)
                  AND d.label_end_date_{horizon}d < CAST(? AS TIMESTAMP)
                  AND d.label_status_{horizon}d = 'AVAILABLE'
                ORDER BY d.trading_date, d.symbol
            """,
                [str(dataset_path), features.locked_holdout_start, features.locked_holdout_start],
            ).df()
        if len(available) != len(reference):
            raise ValueError("source label projection has missing/duplicate OOF keys")
        available["fold"] = reference.fold.to_numpy()
        if not _canonical(available).equals(reference):
            raise ValueError("source keys/targets differ from authenticated OOF")
        if (_aware(available.label_available_at) > pd.Timestamp(snapshot.as_of)).any():
            raise ValueError("label receipt exceeds source snapshot cutoff")
        matrices = {task: np.column_stack(values) for task, values in columns.items()}
        del columns
        output, audit = crossfit_panel(
            available,
            matrices,
            names,
            horizon=horizon,
            threshold=reference_report.config.large_loss_threshold,
            alpha=reference_report.config.quantile_alpha,
            holdout_start=features.locked_holdout_start,
            batch_rows=batch_rows,
            progress=progress,
        )
        destination = _write_parquet(output, output_root / "oof")
        audit.update(
            source_report_ids=report_ids,
            oof_path=str(destination.resolve()),
            oof_byte_sha256=destination.stem,
        )
        results.append(audit)
        del matrices, output, reference, available
        gc.collect()
    for path_string, digest in input_hashes.items():
        if _file_sha256(Path(path_string)) != digest:
            raise ValueError("ensemble input changed during evaluation")
    sources = (
        "daily_ensemble.py",
        "daily_baselines.py",
        "advanced.py",
        "campaign.py",
        "selection.py",
        "production.py",
        "evaluation_audit.py",
        "evaluation_metrics.py",
        "research_metrics.py",
    )
    return write_audit_receipt(
        {
            "schema_version": VERSION,
            "metric_version": METRIC_VERSION,
            "research_only": True,
            "adoption_eligible": False,
            "holdout_scored": False,
            "feature_selection_id": features.feature_selection_id,
            "data_snapshot_id": snapshot.snapshot_id,
            "locked_holdout_start": features.locked_holdout_start,
            "historical_revision_policy": snapshot.historical_revision_policy,
            "input_byte_sha256": input_hashes,
            "batch_rows": batch_rows,
            "results": results,
            "policy": {
                "evaluation_date_fractions": ["1/2", "2/3", "5/6", "1"],
                "calibration_preceding_date_fraction": "1/5",
                "minimum_fit_calibration_dates": 20,
                "simplex_objective": "row-equal MSE; Brier for probability",
                "quantile_weights": "fixed uniform; calibration residual offset only",
                "embargo": "at least horizon observed OOF dates plus strict endpoint/receipt purge",
            },
            "source_sha256": {
                name: _file_sha256(Path(__file__).with_name(name)) for name in sources
            },
            "library_versions": {
                name: version(name) for name in ("numpy", "pandas", "scipy", "scikit-learn")
            },
            "limitations": [
                "development diagnostics only; no selection, holdout, adoption or live inference",
                "same later-half cohort for all comparisons; burn-in not scored",
                "observed-date embargo does not authenticate the full market calendar",
                "single-vintage research; historical as-known availability not proven",
                "no stateful economic, cost, tax or personalized performance claim",
                "calibration may worsen future metrics; residual scales are not standard errors",
                "single quantile cannot establish noncrossing",
            ],
        },
        output_root / "receipts",
    )
