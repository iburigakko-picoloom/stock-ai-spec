"""Versioned development metrics; historical research reports remain unchanged."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from stock_ai.ml.advanced import AdvancedResearchReport
from stock_ai.ml.evaluation_audit import rank_ic, validate_development_oof
from stock_ai.ml.research_metrics import RankingMetrics, evaluate_cross_sectional_predictions

METRIC_VERSION = "daily-development-metrics-v1"
LOG_LOSS_EPSILON = 1e-8


def evaluate_development_tasks(oof: pd.DataFrame, report: AdvancedResearchReport) -> dict[str, Any]:
    """Score only authenticated callers' development OOF, with aligned task keys.

    The campaign audit authenticates artifact bytes and frozen feature lineage
    before calling this. This function independently checks OOF identities and
    the declared holdout boundary; it never loads any data itself.
    """
    validate_development_oof(oof, report)
    scores: dict[str, Any] = {}
    for task, part in oof.groupby("task", sort=True):
        if task in {"regression", "ranking"}:
            scores[str(task)] = asdict(evaluate_ranking_panel(part))
        elif task == "quantile":
            scores[str(task)] = asdict(
                evaluate_quantiles(
                    part.target.tolist(),
                    [report.config.quantile_alpha],
                    part.prediction.to_numpy(dtype=float).reshape(-1, 1).tolist(),
                )
            )
        else:
            scores[str(task)] = asdict(
                evaluate_probabilities(
                    (part.target <= report.config.large_loss_threshold).astype(int).tolist(),
                    part.prediction.tolist(),
                )
            )
    return {
        "version": METRIC_VERSION,
        "source_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("evaluation_metrics.py", "evaluation_audit.py", "research_metrics.py")
        },
        "library_versions": {name: version(name) for name in ("numpy", "pandas", "scipy")},
        "report_id": report.report_id,
        "quantile_alpha": report.config.quantile_alpha,
        "event_definition": "target <= large_loss_threshold",
        "large_loss_threshold": report.config.large_loss_threshold,
        "probability_quantile_weighting": "equal_observation_rows",
        "ranking_weighting": "equal_dates_with_separate_row_weighted_ic",
        "scores": scores,
        "adoption_eligible": False,
    }


@dataclass(frozen=True)
class RankingAudit:
    metrics: RankingMetrics | None
    input_rows: int
    excluded_rows: int
    # Includes dates with no usable IC. Dates are not replaced by zero.
    daily_ic: tuple[tuple[str, int, float | None], ...]
    row_weighted_rank_ic: float | None
    version: str = METRIC_VERSION


def evaluate_ranking_panel(frame: pd.DataFrame) -> RankingAudit:
    """Date-equal metrics, >=3-row IC, and symbol-ascending tie breaks.

    Relevance and top-K set-overlap Precision retain the historical definitions.
    Nonfinite values are excluded and counted; duplicate/missing keys are errors.
    """
    data = frame.loc[:, ["trading_date", "symbol", "target", "prediction"]].reset_index(drop=True)
    if data.empty or data[["trading_date", "symbol"]].isna().any().any():
        raise ValueError("ranking requires nonempty, nonmissing keys")
    if not data.symbol.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise ValueError("symbols must be nonempty strings")
    data["trading_date"] = pd.to_datetime(data.trading_date, errors="raise")
    if data.trading_date.isna().any():
        raise ValueError("ranking requires nonmissing dates")
    if (data.trading_date != data.trading_date.dt.normalize()).any():
        raise ValueError("ranking keys must be trading dates, not intraday timestamps")
    if data.duplicated(["trading_date", "symbol"]).any():
        raise ValueError("duplicate date/symbol key")
    for column in ("target", "prediction"):
        data[column] = pd.to_numeric(data[column], errors="raise").astype(float)
    data = data.sort_values(["trading_date", "symbol"], kind="stable")
    usable = pd.Series(
        np.isfinite(data[["target", "prediction"]].to_numpy(dtype=float)).all(axis=1),
        index=data.index,
    )
    clean = data.loc[usable]
    daily: list[tuple[str, int, float | None]] = []
    for day, group in data.groupby("trading_date", sort=True):
        valid = group.loc[usable.loc[group.index]]
        daily.append(
            (
                str(pd.Timestamp(str(day)).date()),
                len(valid),
                rank_ic(valid.prediction.tolist(), valid.target.tolist()),
            )
        )
    metrics: RankingMetrics | None = None
    valid_ics = [(count, value) for _, count, value in daily if value is not None]
    weighted = None
    if valid_ics:
        weighted = sum(count * value for count, value in valid_ics) / sum(
            count for count, _ in valid_ics
        )
    if not clean.empty:
        original = evaluate_cross_sectional_predictions(
            dates=clean.trading_date, target=clean.target, prediction=clean.prediction
        )
        values = [value for _, value in valid_ics]
        mean = float(np.mean(values)) if values else None
        std = float(np.std(values, ddof=1)) if len(values) > 1 else None
        metrics = replace(
            original,
            mean_daily_rank_ic=mean,
            rank_ic_standard_deviation=std,
            rank_icir=mean / std if mean is not None and std is not None and std > 0 else None,
        )
    return RankingAudit(metrics, len(data), int((~usable).sum()), tuple(daily), weighted)


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_probability: float
    observed_rate: float


@dataclass(frozen=True)
class ProbabilityMetrics:
    rows: int
    base_rate: float
    mean_probability: float
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    calibration_bins: tuple[CalibrationBin, ...]
    log_loss_epsilon: float = LOG_LOSS_EPSILON
    version: str = METRIC_VERSION


def evaluate_probabilities(
    event: Sequence[float], probability: Sequence[float]
) -> ProbabilityMetrics:
    """Binary observed events; raw Brier/ECE, float64 epsilon-clipped log loss."""
    y, p = _paired_vectors(event, probability)
    if not np.isin(y, [0, 1]).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("binary events and probabilities in [0,1] required")
    clipped = np.clip(p, LOG_LOSS_EPSILON, 1 - LOG_LOSS_EPSILON)
    log_loss = float(-np.mean(y * np.log(clipped) + (1 - y) * np.log1p(-clipped)))
    bins: list[CalibrationBin] = []
    edges = np.linspace(0, 1, 11)
    for index, (lower, upper) in enumerate(pairwise(edges)):
        selected = (p >= lower) & ((p <= upper) if index == 9 else (p < upper))
        if selected.any():
            bins.append(
                CalibrationBin(
                    float(lower),
                    float(upper),
                    int(selected.sum()),
                    float(p[selected].mean()),
                    float(y[selected].mean()),
                )
            )
    ece = sum(item.count * abs(item.mean_probability - item.observed_rate) for item in bins)
    return ProbabilityMetrics(
        len(y),
        float(y.mean()),
        float(p.mean()),
        float(np.mean((y - p) ** 2)),
        log_loss,
        ece / len(y),
        tuple(bins),
    )


@dataclass(frozen=True)
class QuantileMetrics:
    alpha: float
    pinball_loss: float
    strictly_below_rate: float
    at_or_below_rate: float


@dataclass(frozen=True)
class QuantileAudit:
    rows: int
    crossed_rows: int
    crossing_check_available: bool
    scores: tuple[QuantileMetrics, ...]
    version: str = METRIC_VERSION


def evaluate_quantiles(
    target: Sequence[float], levels: Sequence[float], prediction: Sequence[Sequence[float]]
) -> QuantileAudit:
    """Keep raw crossing predictions; one level cannot establish noncrossing."""
    y = np.asarray(target, dtype=np.float64)
    alpha = np.asarray(levels, dtype=np.float64)
    q = np.asarray(prediction, dtype=np.float64)
    if y.ndim != 1 or alpha.ndim != 1 or not y.size or not alpha.size:
        raise ValueError("nonempty target and quantile levels required")
    if q.shape != (len(y), len(alpha)):
        raise ValueError("quantile prediction shape must be rows by levels")
    if not all(np.isfinite(value).all() for value in (y, alpha, q)):
        raise ValueError("quantile values must be finite")
    if ((alpha <= 0) | (alpha >= 1)).any() or (np.diff(alpha) <= 0).any():
        raise ValueError("quantile levels must increase strictly inside (0,1)")
    scores: list[QuantileMetrics] = []
    for column, level in enumerate(alpha):
        error = y - q[:, column]
        scores.append(
            QuantileMetrics(
                float(level),
                float(np.mean(np.maximum(level * error, (level - 1) * error))),
                float(np.mean(y < q[:, column])),
                float(np.mean(y <= q[:, column])),
            )
        )
    crossed = int((np.diff(q, axis=1) < 0).any(axis=1).sum())
    return QuantileAudit(len(y), crossed, len(alpha) > 1, tuple(scores))


def _paired_vectors(
    left: Sequence[float], right: Sequence[float]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    a, b = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if a.ndim != 1 or b.ndim != 1 or not len(a) or a.shape != b.shape:
        raise ValueError("nonempty equal-length vectors required")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("values must be finite")
    return a, b
