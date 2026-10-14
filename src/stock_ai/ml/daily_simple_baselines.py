"""Fixed diagnostic Elastic Net and causal, dimensionless rule comparisons."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

if TYPE_CHECKING:
    from stock_ai.ml.daily_baselines import StreamedRidge

FloatArray = NDArray[np.float64]
ELASTIC_ALPHA = 0.001
ELASTIC_L1_RATIO = 0.5
RULE_FEATURES = (
    "price.return_20d",
    "relative.sector_20d",
    "fundamental.roe",
    "fundamental.forecast_revision",
)
RULES = {
    "momentum_revision_rank": ("price.return_20d", "fundamental.forecast_revision"),
    "equal_weight_rule_rank": RULE_FEATURES,
}


def _design(values: FloatArray, transform: StreamedRidge) -> FloatArray:
    if values.ndim != 2 or values.shape[1] != len(transform.medians) or np.isinf(values).any():
        raise ValueError("invalid Elastic Net feature matrix")
    missing = np.isnan(values)
    imputed = np.column_stack((np.where(missing, transform.medians, values), missing.astype(float)))
    result = (imputed - transform.mean) / transform.scale
    if not np.isfinite(result).all():
        raise ValueError("nonfinite Elastic Net design")
    return result


@dataclass(frozen=True)
class StreamedElasticNet:
    coefficient: FloatArray
    target_mean: float
    rows: int
    alpha: float
    l1_ratio: float
    iterations: int
    objective: float
    kkt_residual: float
    objective_gap_bound: float

    def predict(self, values: FloatArray, transform: StreamedRidge) -> FloatArray:
        return np.asarray(self.target_mean + _design(values, transform) @ self.coefficient)

    def receipt(self) -> dict[str, Any]:
        return {
            key: value.tolist() if isinstance(value, np.ndarray) else value
            for key, value in asdict(self).items()
        }


def fit_streamed_elastic_net(
    batches: Iterable[tuple[FloatArray, FloatArray]],
    transform: StreamedRidge,
    *,
    alpha: float = ELASTIC_ALPHA,
    l1_ratio: float = ELASTIC_L1_RATIO,
    max_iter: int = 50_000,
    tolerance: float = 1e-9,
) -> StreamedElasticNet:
    """Full-data standardized Elastic Net; no row sampling or hyperparameter search.

    Minimize mean squared residual / 2 + alpha*rho*L1 + alpha*(1-rho)*L2^2/2.
    Accumulate normalized Gram statistics, then cyclic coordinate descent. Check
    the minimum-norm subgradient, not just coefficient step size. Positive L2
    gives the objective suboptimality bound ||subgradient||^2/(2*L2).
    """
    if (
        not math.isfinite(alpha)
        or alpha <= 0
        or not 0 < l1_ratio < 1
        or max_iter < 1
        or not math.isfinite(tolerance)
        or tolerance <= 0
    ):
        raise ValueError("invalid Elastic Net configuration")
    width = len(transform.mean)
    gram = np.zeros((width, width))
    xy = np.zeros(width)
    yy = 0.0
    rows = 0
    for values, target in batches:
        x = _design(values, transform)
        if target.ndim != 1 or len(target) != len(x) or not np.isfinite(target).all():
            raise ValueError("invalid Elastic Net target")
        centered = target - transform.target_mean
        gram += x.T @ x
        xy += x.T @ centered
        yy += float(centered @ centered)
        rows += len(x)
    if not rows or rows != transform.rows:
        raise ValueError("Elastic Net training row count differs from transform")
    gram /= rows
    xy /= rows
    yy /= rows
    if not np.isfinite(gram).all() or not np.isfinite(xy).all() or not math.isfinite(yy):
        raise ValueError("nonfinite Elastic Net sufficient statistics")
    l1, l2 = alpha * l1_ratio, alpha * (1 - l1_ratio)
    diagonal = np.diag(gram) + l2
    coefficient = np.zeros(width)
    gradient = np.zeros(width)
    for iteration in range(1, max_iter + 1):
        for column in range(width):
            partial = (
                xy[column] - gram[column] @ coefficient + gram[column, column] * coefficient[column]
            )
            coefficient[column] = np.sign(partial) * max(abs(partial) - l1, 0.0) / diagonal[column]
        smooth = gram @ coefficient - xy + l2 * coefficient
        gradient = np.where(
            coefficient != 0,
            smooth + l1 * np.sign(coefficient),
            np.sign(smooth) * np.maximum(np.abs(smooth) - l1, 0.0),
        )
        residual = float(np.max(np.abs(gradient)))
        if math.isfinite(residual) and residual <= tolerance:
            objective = (yy - 2 * coefficient @ xy + coefficient @ gram @ coefficient) / 2
            objective += l1 * np.abs(coefficient).sum() + l2 * (coefficient @ coefficient) / 2
            bound = float(gradient @ gradient) / (2 * l2)
            if not math.isfinite(objective) or objective < -1e-12 or not math.isfinite(bound):
                raise ValueError("invalid Elastic Net objective")
            return StreamedElasticNet(
                coefficient,
                transform.target_mean,
                rows,
                alpha,
                l1_ratio,
                iteration,
                max(float(objective), 0.0),
                residual,
                bound,
            )
    raise ValueError("Elastic Net did not converge")


def fixed_rule_scores(universe: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Rank features from the full contemporaneous feature cohort, before label joins.

    Every feature has a fixed positive direction. Midranks map to [-1, 1], with
    tied constants, singleton observations and missing values assigned neutral 0.
    Missing components keep their fixed weight; they are never redistributed.
    """
    columns = ["trading_date", "as_of", "available_at", "symbol", *RULE_FEATURES]
    if not set(columns) <= set(universe.columns) or universe.empty:
        raise ValueError("rule baseline requires the complete feature universe")
    frame = universe[columns].copy().reset_index(drop=True)
    frame["trading_date"] = pd.to_datetime(frame.trading_date)
    frame["as_of"] = pd.to_datetime(frame.as_of, utc=True)
    frame["available_at"] = pd.to_datetime(frame.available_at, utc=True)
    if (
        frame[["trading_date", "as_of", "available_at", "symbol"]].isna().any().any()
        or frame.duplicated(["trading_date", "symbol"]).any()
        or (frame.available_at > frame.as_of).any()
        or (frame.groupby("trading_date").as_of.nunique() != 1).any()
    ):
        raise ValueError("invalid rule universe keys or information cutoffs")
    components = pd.DataFrame(index=frame.index)
    coverage = {}
    for name in RULE_FEATURES:
        values = frame[name].astype(float)
        if np.isinf(values).any():
            raise ValueError("nonfinite rule feature")
        grouped = values.groupby(frame.trading_date, sort=False)
        count = grouped.transform("count")
        rank = grouped.rank(method="average")
        score = (2 * rank - count - 1) / (count - 1)
        components[name] = score.where(count > 1, 0).fillna(0)
        coverage[name] = {
            "observed_rows": int(values.notna().sum()),
            "neutral_missing_rows": int(values.isna().sum()),
        }
    result = frame[["trading_date", "as_of", "symbol"]].copy()
    for name, features in RULES.items():
        result[name] = components[list(features)].mean(axis=1)
    return result, {
        "universe_rows": len(frame),
        "dates": int(frame.trading_date.nunique()),
        "score_unit": "dimensionless_rank",
        "feature_coverage": coverage,
        "universe_uses_labels": False,
    }
