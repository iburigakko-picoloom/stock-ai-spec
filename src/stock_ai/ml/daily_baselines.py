"""Same-fold development comparisons with bounded-memory linear baselines."""

from __future__ import annotations

import gc
import hashlib
import math
import shutil
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import expit

from stock_ai.features import V0_MANIFEST
from stock_ai.ml.advanced import (
    AdvancedResearchReport,
    _authenticate_advanced_research_bundle,
    _split_research_stages,
    load_advanced_research_run,
)
from stock_ai.ml.campaign import CampaignBatchStatus, load_campaign_manifest
from stock_ai.ml.daily_simple_baselines import (
    ELASTIC_ALPHA,
    ELASTIC_L1_RATIO,
    RULE_FEATURES,
    RULES,
    fit_streamed_elastic_net,
    fixed_rule_scores,
)
from stock_ai.ml.evaluation_audit import validate_development_oof, write_audit_receipt
from stock_ai.ml.evaluation_metrics import (
    evaluate_probabilities,
    evaluate_quantiles,
    evaluate_ranking_panel,
)
from stock_ai.ml.production import _file_sha256, load_production_dataset_snapshot
from stock_ai.ml.selection import _authenticate_batch_report, load_development_feature_selection

VERSION = "daily-regression-risk-simple-baselines-v3"
KEYS = ["trading_date", "symbol", "as_of", "label_end", "target", "fold"]
BASELINES = ("zero_return", "momentum_20d", "ridge_v0", "elastic_net_v0")
RISK_BASELINES = ("training_loss_rate", "logistic_v0", "training_quantile")
FloatArray = NDArray[np.float64]


def _impute(values: FloatArray, medians: FloatArray) -> FloatArray:
    if values.ndim != 2 or values.shape[1] != len(medians) or np.isinf(values).any():
        raise ValueError("invalid baseline feature matrix")
    missing = np.isnan(values)
    # All indicators are retained. Indicators never active in training have zero
    # variance and coefficient, equivalent to SimpleImputer(add_indicator=True).
    return np.column_stack((np.where(missing, medians, values), missing.astype(float)))


@dataclass(frozen=True)
class StreamedRidge:
    medians: FloatArray
    mean: FloatArray
    scale: FloatArray
    coefficient: FloatArray
    target_mean: float
    rows: int
    alpha: float

    def predict(self, values: FloatArray) -> FloatArray:
        x = _impute(values, self.medians)
        return np.asarray(self.target_mean + ((x - self.mean) / self.scale) @ self.coefficient)

    def receipt(self) -> dict[str, Any]:
        return {
            key: value.tolist() if isinstance(value, np.ndarray) else value
            for key, value in asdict(self).items()
        }


def fit_streamed_ridge(
    batches: Iterable[tuple[FloatArray, FloatArray]],
    medians: FloatArray,
    *,
    alpha: float = 5.0,
) -> StreamedRidge:
    """Exact sufficient statistics, not SGD; median values must be training-only.

    Chan's centered covariance merge avoids subtracting huge uncentered moments.
    This solves the same standardized Ridge objective as the existing baseline.
    """
    if not math.isfinite(alpha) or alpha <= 0 or not len(medians) or not np.isfinite(medians).all():
        raise ValueError("baseline requires finite medians and positive Ridge alpha")
    n = 0
    mean = np.zeros(2 * len(medians))
    target_mean = 0.0
    cross = np.zeros((len(mean), len(mean)))
    target_cross = np.zeros(len(mean))
    for values, target in batches:
        x = _impute(values, medians)
        if target.ndim != 1 or len(target) != len(x) or not np.isfinite(target).all():
            raise ValueError("invalid baseline training target")
        count = len(x)
        if not count:
            continue
        block_mean, block_target = x.mean(axis=0), float(target.mean())
        centered, centered_target = x - block_mean, target - block_target
        delta, target_delta = block_mean - mean, block_target - target_mean
        weight = n * count / (n + count)
        cross += centered.T @ centered + np.outer(delta, delta) * weight
        target_cross += centered.T @ centered_target + delta * target_delta * weight
        mean += delta * (count / (n + count))
        target_mean += target_delta * (count / (n + count))
        n += count
    if not n:
        raise ValueError("baseline training is empty")
    variance = np.maximum(np.diag(cross) / n, 0)
    eps = np.finfo(np.float64).eps
    # StandardScaler's numerical constant-feature bound.
    constant = variance <= n * eps * variance + (n * mean * eps) ** 2
    scale = np.sqrt(variance)
    scale[constant] = 1
    standardized = cross / np.outer(scale, scale)
    standardized.flat[:: len(mean) + 1] += alpha
    coefficient = np.linalg.solve(standardized, target_cross / scale)
    if not np.isfinite(coefficient).all():
        raise ValueError("nonfinite Ridge coefficients")
    return StreamedRidge(medians, mean, scale, coefficient, target_mean, n, alpha)


def _canonical(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame[KEYS].copy()
    for column in ("trading_date", "label_end"):
        result[column] = pd.to_datetime(result[column]).astype("datetime64[ns]")
    result["as_of"] = pd.to_datetime(result.as_of, utc=True).astype("datetime64[ns, UTC]")
    result["target"] = result.target.astype(float)
    result["fold"] = result.fold.astype("int64")
    if result.isna().any().any() or result.duplicated(["trading_date", "symbol"]).any():
        raise ValueError("missing or duplicate baseline comparison keys")
    return result.sort_values(["trading_date", "symbol"]).reset_index(drop=True)


@dataclass(frozen=True)
class StreamedLogistic:
    coefficient: FloatArray
    intercept: float
    rows: int
    events: int
    iterations: int
    objective: float | None
    gradient_max: float | None
    constant_probability: float | None = None
    c: float = 1.0

    def predict(self, values: FloatArray, transform: StreamedRidge) -> FloatArray:
        x = (_impute(values, transform.medians) - transform.mean) / transform.scale
        if self.constant_probability is not None:
            return np.full(len(x), self.constant_probability, dtype=float)
        return np.asarray(expit(x @ self.coefficient + self.intercept), dtype=float)

    def receipt(self) -> dict[str, Any]:
        return {
            key: value.tolist() if isinstance(value, np.ndarray) else value
            for key, value in asdict(self).items()
        }


def fit_streamed_logistic(
    batches: Iterable[tuple[FloatArray, FloatArray]],
    transform: StreamedRidge,
    *,
    threshold: float,
    batch_rows: int = 32_768,
    c: float = 1.0,
    max_iterations: int = 500,
) -> StreamedLogistic:
    """Full-batch L2 logistic, C=1, unpenalized intercept; disk-backed feature blocks.

    Minimize mean logistic loss + ||w||²/(2*C*n), matching sklearn's C convention.
    The fitted Ridge contributes only training medians/means/scales, not its targets
    or coefficients. A single-class training set is an explicit constant fallback.
    """
    if (
        not math.isfinite(threshold) or not math.isfinite(c) or c <= 0
        or batch_rows < 1 or max_iterations < 1
    ):
        raise ValueError("invalid logistic baseline configuration")
    width = len(transform.mean)
    # Never-active/always-active missing indicators standardize to zero. Dropping
    # these known zero columns reduces disk IO without changing the objective.
    active = np.ones(width, dtype=bool)
    indicator_mean = transform.mean[len(transform.medians):]
    active[len(transform.medians):] = (indicator_mean > 0) & (indicator_mean < 1)
    dimension = int(active.sum())
    n, events = 0, 0
    with tempfile.TemporaryFile() as cached:
        for values, target in batches:
            x = (_impute(values, transform.medians) - transform.mean) / transform.scale
            if target.ndim != 1 or len(target) != len(x) or not np.isfinite(target).all():
                raise ValueError("invalid logistic baseline target")
            y = (target <= threshold).astype(float)
            block = np.column_stack((x[:, active], y)).astype(np.float64)
            if not np.isfinite(block).all():
                raise ValueError("nonfinite logistic baseline design")
            block.tofile(cached)
            n += len(y)
            events += int(y.sum())
        if n != transform.rows or n == 0:
            raise ValueError("logistic training rows differ from preprocessing fit")
        if events in (0, n):
            return StreamedLogistic(
                np.zeros(width), 0.0, n, events, 0, None, None, events / n, c
            )
        cached.flush()

        def loss_gradient(parameters: FloatArray) -> tuple[float, FloatArray]:
            cached.seek(0)
            w, intercept = parameters[:-1], parameters[-1]
            loss = 0.0
            gradient = np.zeros(dimension + 1)
            while True:
                flat = np.fromfile(cached, dtype=np.float64, count=batch_rows * (dimension + 1))
                if not flat.size:
                    break
                block = flat.reshape(-1, dimension + 1)
                x, y = block[:, :-1], block[:, -1]
                score = x @ w + intercept
                loss += float(np.sum(np.logaddexp(0, score) - y * score))
                residual = expit(score) - y
                gradient[:-1] += x.T @ residual
                gradient[-1] += residual.sum()
            gradient[:-1] += w / c
            return (loss + float(w @ w) / (2 * c)) / n, gradient / n

        initial = np.zeros(dimension + 1)
        initial[-1] = math.log(events / (n - events))
        fitted = minimize(
            loss_gradient, initial, method="L-BFGS-B", jac=True,
            options={"maxiter": max_iterations, "gtol": 1e-8, "ftol": 1e-14, "maxls": 50},
        )
        objective, gradient = loss_gradient(fitted.x)
        gradient_max = float(np.max(np.abs(gradient)))
        if (
            not fitted.success or not np.isfinite(fitted.x).all()
            or not math.isfinite(objective) or not math.isfinite(gradient_max)
            or gradient_max > 1e-6
        ):
            raise ValueError(
                f"logistic baseline did not converge: {fitted.message}; {gradient_max=}"
            )
        coefficient = np.zeros(width)
        coefficient[active] = fitted.x[:-1]
        return StreamedLogistic(
            coefficient, float(fitted.x[-1]), n, events, int(fitted.nit),
            objective, gradient_max, c=c,
        )


def _risk_scores(
    frame: pd.DataFrame, report: AdvancedResearchReport, *, probability: str, quantile: str
) -> dict[str, Any]:
    return {
        "large_loss": asdict(evaluate_probabilities(
            (frame.target <= report.config.large_loss_threshold).astype(int).tolist(),
            frame[probability].tolist(),
        )),
        "quantile": asdict(evaluate_quantiles(
            frame.target.tolist(), [report.config.quantile_alpha],
            frame[quantile].to_numpy(float).reshape(-1, 1).tolist(),
        )),
    }


def _baseline_risk_scores(
    frame: pd.DataFrame, report: AdvancedResearchReport
) -> dict[str, Any]:
    distribution = _risk_scores(
        frame, report, probability="training_loss_rate", quantile="training_quantile"
    )
    return {
        "training_loss_rate": distribution["large_loss"],
        "training_quantile": distribution["quantile"],
        "logistic_v0": asdict(evaluate_probabilities(
            (frame.target <= report.config.large_loss_threshold).astype(int).tolist(),
            frame.logistic_v0.tolist(),
        )),
    }


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _one(cursor: duckdb.DuckDBPyConnection) -> tuple[Any, ...]:
    row = cursor.fetchone()
    if row is None:
        raise ValueError("baseline aggregate returned no row")
    return row


def _scores(frame: pd.DataFrame) -> dict[str, Any]:
    audit = evaluate_ranking_panel(frame)
    if audit.excluded_rows:
        raise ValueError("baseline comparison cannot discard nonfinite observations")
    # Constant forecasts have no IC. MSE is still defined, not a cash NAV return.
    return {
        "mse": float(np.mean(np.square(frame.prediction - frame.target))),
        "ranking": asdict(audit),
    }


def _rule_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    metrics = {}
    for name in RULES:
        audit = evaluate_ranking_panel(frame.rename(columns={name: "prediction"}))
        if audit.excluded_rows:
            raise ValueError("rule comparison cannot exclude observations")
        ranking = asdict(audit)
        # The shared audit also computes return MSE. Rule scores have no return
        # units, so omit that field from the nested serialized metrics as well.
        if ranking["metrics"] is not None:
            del ranking["metrics"]["mean_squared_error"]
        metrics[name] = {"score_unit": "dimensionless_rank", "ranking": ranking}
    return metrics


def evaluate_baseline_folds(
    connection: duckdb.DuckDBPyConnection,
    report: AdvancedResearchReport,
    reference: pd.DataFrame,
    *,
    feature_names: tuple[str, ...] = V0_MANIFEST.feature_names,
    batch_rows: int = 32_768,
    progress: Callable[[str], None] = lambda _message: None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Use authenticated caller's `source` relation, and exactly the candidate folds."""
    if batch_rows < 1 or not feature_names or len(feature_names) != len(set(feature_names)):
        raise ValueError("baseline features and batch size must be nonempty")
    if "price.return_20d" not in feature_names or report.config.target_family != "return":
        raise ValueError("daily baselines require momentum and absolute-return targets")
    if len(report.config.horizons) != 1 or report.config.horizons[0] not in (5, 20):
        raise ValueError("daily baselines require one 5d/20d horizon")
    horizon = report.config.horizons[0]
    boundary = date.fromisoformat(report.locked_holdout_start).isoformat()
    target, endpoint = f"target_return_{horizon}d", f"label_end_date_{horizon}d"
    availability = f"label_available_at_{horizon}d"
    connection.execute(f"""
        CREATE OR REPLACE TEMP VIEW development AS SELECT * FROM source
        WHERE trading_date < DATE '{boundary}' AND {endpoint} < DATE '{boundary}'
          AND {target} IS NOT NULL AND label_status_{horizon}d = 'AVAILABLE'
    """)
    grouped = connection.execute(f"""
        SELECT trading_date, min({endpoint}) AS {endpoint} FROM development
        GROUP BY trading_date ORDER BY trading_date
    """).df()
    if grouped.empty:
        raise ValueError("empty baseline development period")
    stage = _split_research_stages(
        grouped, horizon=horizon, label_end_column=endpoint, config=report.config
    )
    boundaries = [b for b in report.stage_boundaries if b.horizon == horizon]
    if len(boundaries) != 1 or boundaries[0].model_evaluation_start != str(
        stage.model_evaluation_start.date()
    ):
        raise ValueError("candidate model-evaluation boundary differs from dataset")
    ref = _canonical(reference)
    if (ref.trading_date >= pd.Timestamp(boundary)).any() or (
        ref.label_end >= pd.Timestamp(boundary)
    ).any():
        raise ValueError("baseline reference reaches holdout")
    dates = pd.DatetimeIndex(grouped.trading_date)
    config = report.config
    fold_receipts: list[dict[str, Any]] = []
    outputs: list[pd.DataFrame] = []
    feature_sql = ", ".join(_identifier(name) for name in feature_names)
    for number, start in enumerate(
        range(
            config.initial_train_periods + horizon,
            len(dates) - config.validation_periods + 1,
            config.step_periods,
        )
    ):
        validation_start, validation_end = (
            dates[start],
            dates[start + config.validation_periods - 1],
        )
        score_start = max(validation_start, stage.model_evaluation_start)
        if score_start > validation_end:
            continue
        train_end = dates[start - horizon - 1]
        train_predicate = (
            f"trading_date <= DATE '{train_end.date()}' "
            f"AND {endpoint} < DATE '{validation_start.date()}'"
        )
        score_predicate = (
            f"trading_date BETWEEN DATE '{score_start.date()}' AND DATE '{validation_end.date()}'"
        )
        progress(f"{horizon}d fold {number}: verify keys and training cutoffs")
        expected = connection.execute(f"""
            SELECT trading_date, symbol, as_of, {endpoint} AS label_end,
                   {target} AS target, {number} AS fold
            FROM development WHERE {score_predicate}
        """).df()
        expected = _canonical(expected)
        observed = ref.loc[ref.fold == number].reset_index(drop=True)
        if not expected.equals(observed):
            raise ValueError(
                f"candidate/dataset keys, targets or folds differ: {horizon}d/{number}"
            )
        declared = [f for f in report.fold_results if f.task == "regression" and f.fold == number]
        if len(declared) != 1 or (
            declared[0].rows != len(observed)
            or declared[0].validation_start != str(observed.trading_date.min().date())
            or declared[0].validation_end != str(observed.trading_date.max().date())
        ):
            raise ValueError("candidate fold report differs from actual validation keys")
        cutoff = _one(
            connection.execute(f"""
            SELECT min(as_of) FROM development WHERE trading_date = DATE '{validation_start.date()}'
        """)
        )[0]
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW training AS SELECT * FROM development "
            f"WHERE {train_predicate}"
        )
        train_audit = _one(
            connection.execute(
                f"""
            SELECT count(*), max(trading_date), max({endpoint}), max({availability}),
                   count(*) FILTER (WHERE {availability} IS NULL OR {availability} >= ?
                     OR available_at IS NULL OR available_at > ? OR NOT isfinite({target}))
            FROM training
        """,
                [cutoff, cutoff],
            )
        )
        late_validation = _one(
            connection.execute(f"""
            SELECT count(*) FROM development WHERE {score_predicate}
              AND (as_of IS NULL OR available_at IS NULL OR available_at > as_of)
        """)
        )[0]
        if not train_audit[0] or train_audit[4] or late_validation:
            raise ValueError("baseline training/validation has unavailable inputs or targets")
        medians: list[float] = []
        # One exact median column at a time avoids an O(rows * features) allocation.
        for name in feature_names:
            column = _identifier(name)
            median, invalid = _one(
                connection.execute(f"""
                SELECT median({column}), count(*) FILTER (
                    WHERE {column} IS NOT NULL AND NOT isfinite({column})) FROM training
            """)
            )
            if invalid:
                raise ValueError("nonfinite baseline training feature")
            medians.append(0.0 if median is None else float(median))

        def batches() -> Iterable[tuple[FloatArray, FloatArray]]:
            reader = connection.execute(
                f"SELECT {feature_sql}, {target} AS target FROM training "
                "ORDER BY trading_date, symbol"
            ).fetch_record_batch(batch_rows)
            for batch in reader:
                frame = batch.to_pandas()
                yield frame[list(feature_names)].to_numpy(dtype=float), frame.target.to_numpy(float)

        progress(f"{horizon}d fold {number}: fit streamed Ridge ({train_audit[0]} rows)")
        model = fit_streamed_ridge(batches(), np.asarray(medians))
        if model.rows != train_audit[0]:
            raise ValueError("Ridge training count changed during fit")
        progress(f"{horizon}d fold {number}: fit fixed Elastic Net ({train_audit[0]} rows)")
        elastic = fit_streamed_elastic_net(batches(), model)
        probability, quantile = _one(connection.execute(
            f"SELECT avg(CAST({target} <= ? AS DOUBLE)), quantile_cont({target}, ?) FROM training",
            [config.large_loss_threshold, config.quantile_alpha],
        ))
        progress(f"{horizon}d fold {number}: fit full-batch logistic ({train_audit[0]} rows)")
        logistic = fit_streamed_logistic(
            batches(), model, threshold=config.large_loss_threshold, batch_rows=batch_rows
        )
        if not math.isclose(logistic.events / logistic.rows, probability, abs_tol=1e-15):
            raise ValueError("logistic event count differs from training distribution")
        momentum_column = _identifier("price.return_20d")
        fallback = _one(
            connection.execute(f"""
            SELECT avg({target}) FROM training WHERE {momentum_column} IS NOT NULL
        """)
        )[0]
        fallback = 0.0 if fallback is None else float(fallback)
        predictions: list[pd.DataFrame] = []
        reader = connection.execute(f"""
            SELECT trading_date, symbol, {feature_sql} FROM development
            WHERE {score_predicate} ORDER BY trading_date, symbol
        """).fetch_record_batch(batch_rows)
        for batch in reader:
            frame = batch.to_pandas()
            output = frame[["trading_date", "symbol"]].copy()
            output["zero_return"] = 0.0
            output["momentum_20d"] = frame["price.return_20d"].fillna(fallback)
            output["ridge_v0"] = model.predict(frame[list(feature_names)].to_numpy(dtype=float))
            output["elastic_net_v0"] = elastic.predict(
                frame[list(feature_names)].to_numpy(dtype=float), model
            )
            output["training_loss_rate"] = probability
            output["training_quantile"] = quantile
            output["logistic_v0"] = logistic.predict(
                frame[list(feature_names)].to_numpy(dtype=float), model
            )
            predictions.append(output)
        predicted = pd.concat(predictions, ignore_index=True)
        result = observed.merge(predicted, on=["trading_date", "symbol"], validate="one_to_one")
        if len(result) != len(observed) or not np.isfinite(
            result[list((*BASELINES, *RISK_BASELINES))]
        ).all().all():
            raise ValueError("incomplete or nonfinite baseline output")
        # Rank every available contemporaneous feature row before joining labels.
        # The scoring cohort must not determine the rule's cross-sectional peers.
        rule_columns = ", ".join(_identifier(name) for name in RULE_FEATURES)
        rule_universe = connection.execute(f"""
            SELECT trading_date, as_of, available_at, symbol, {rule_columns}
            FROM source WHERE {score_predicate} ORDER BY trading_date, symbol
        """).df()
        rules, rule_audit = fixed_rule_scores(rule_universe)
        result = result.merge(rules, on=["trading_date", "as_of", "symbol"],
                              how="left", validate="one_to_one")
        if len(result) != len(observed) or not np.isfinite(result[list(RULES)]).all().all():
            raise ValueError("rule universe does not cover every scoring row")
        outputs.append(result)
        fold_receipts.append(
            {
                "fold": number,
                "original_validation_start": str(validation_start.date()),
                "score_start": str(score_start.date()),
                "validation_end": str(validation_end.date()),
                "train_end": str(train_end.date()),
                "fit_cutoff": cutoff.isoformat(),
                "training_rows": train_audit[0],
                "latest_training_label_end": str(train_audit[2]),
                "latest_training_label_available_at": train_audit[3].isoformat(),
                "validation_rows": len(result),
                "momentum_missing_fallback": fallback,
                "ridge": model.receipt(),
                "logistic": logistic.receipt(),
                "elastic_net": elastic.receipt(),
                "rule_universe": rule_audit,
                "rule_scores": _rule_metrics(result),
                "training_loss_rate": probability,
                "training_quantile": quantile,
                "risk_scores": _baseline_risk_scores(result, report),
                "scores": {
                    name: _scores(result.rename(columns={name: "prediction"})) for name in BASELINES
                },
            }
        )
    if not outputs:
        raise ValueError("no evaluation folds for daily baselines")
    output = pd.concat(outputs, ignore_index=True)
    if not _canonical(output).equals(ref):
        raise ValueError("baseline output does not cover every candidate evaluation row")
    return output.sort_values(["trading_date", "symbol"]).reset_index(drop=True), fold_receipts


def _write_parquet(frame: pd.DataFrame, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as temporary:
        frame.to_parquet(temporary, index=False)
        temporary.seek(0)
        digest = hashlib.file_digest(temporary, "sha256").hexdigest()
        destination = root / f"{digest}.parquet"
        if destination.exists():
            if _file_sha256(destination) != digest:
                raise ValueError("baseline output file identity mismatch")
        else:
            temporary.seek(0)
            with destination.open("xb") as stream:
                shutil.copyfileobj(temporary, stream)
    return destination


def run_daily_baselines(
    *,
    feature_selection_path: Path,
    campaign_paths: Sequence[Path],
    dataset_path: Path,
    output_root: Path,
    batch_rows: int = 32_768,
    progress: Callable[[str], None] = lambda _message: None,
) -> Path:
    """Authenticate all 18 candidates and compare regression/risk on exact OOF rows."""
    features = load_development_feature_selection(feature_selection_path)
    source_hash = _file_sha256(dataset_path)
    progress("authenticate full dataset logical identity (no holdout scoring)")
    snapshot, dates = load_production_dataset_snapshot(
        dataset_path, columns=("symbol", "trading_date")
    )
    del dates
    if snapshot.snapshot_id != features.data_snapshot_id:
        raise ValueError("baseline dataset differs from frozen feature selection")
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
                raise ValueError("baseline comparison requires successful candidate artifacts")
            _, report, _ = _authenticate_advanced_research_bundle(Path(batch.oof_path))
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
                raise ValueError("baseline candidate differs from frozen data/features")
            key = (batch.horizon, batch.model_family, int(batch.seed))
            if key in runs:
                raise ValueError("duplicate baseline comparison candidate")
            runs[key] = report, Path(batch.oof_path)
    expected = {
        (h, f, s)
        for h in (5, 20)
        for f in ("lightgbm", "xgboost", "catboost")
        for s in features.seeds
    }
    if set(runs) != expected:
        raise ValueError("baseline comparison candidate matrix is incomplete")
    results: list[dict[str, Any]] = []
    for horizon in (5, 20):
        reference: pd.DataFrame | None = None
        reference_report: AdvancedResearchReport | None = None
        candidate_scores: list[dict[str, Any]] = []
        sum_prediction: FloatArray | None = None
        sum_risk: FloatArray | None = None
        for key, (declared, path) in sorted(runs.items()):
            if key[0] != horizon:
                continue
            progress(f"authenticate {horizon}d {key[1]} seed {key[2]} OOF and compare keys")
            report, full = load_advanced_research_run(path)
            if report != declared:
                raise ValueError("candidate report changed during baseline comparison")
            validate_development_oof(full, report)
            part = (
                full.loc[full.task == "regression"]
                .sort_values(["trading_date", "symbol"])
                .reset_index(drop=True)
            )
            canonical = _canonical(part)
            if reference is None:
                reference, reference_report = canonical, report
            elif (
                not reference.equals(canonical)
                or reference_report is None
                or any(
                    getattr(reference_report.config, name) != getattr(report.config, name)
                    for name in (
                        "initial_train_periods", "validation_periods", "step_periods",
                        "large_loss_threshold", "quantile_alpha",
                    )
                )
                or report.stage_boundaries != reference_report.stage_boundaries
            ):
                raise ValueError("candidate comparison dates, folds, targets or split rules differ")
            for task in ("large_loss", "quantile"):
                task_part = full.loc[full.task == task].sort_values(
                    ["trading_date", "symbol"]
                ).reset_index(drop=True)
                if not _canonical(task_part).equals(canonical):
                    raise ValueError("candidate risk task keys differ from regression reference")
                part[task] = task_part.prediction.to_numpy(float)
            del full, task_part
            risk = part[["large_loss", "quantile"]].to_numpy(float)
            sum_risk = risk.copy() if sum_risk is None else sum_risk + risk
            prediction = part.prediction.to_numpy(float)
            sum_prediction = (
                prediction.copy() if sum_prediction is None else sum_prediction + prediction
            )
            candidate_scores.append(
                {
                    "model_family": key[1],
                    "seed": key[2],
                    "report_id": report.report_id,
                    "scores": _scores(part),
                    "risk_scores": _risk_scores(
                        part, report, probability="large_loss", quantile="quantile"
                    ),
                }
            )
            del part, canonical
            gc.collect()
        assert reference is not None and reference_report is not None and sum_prediction is not None
        assert sum_risk is not None
        with duckdb.connect(config={"threads": 1, "memory_limit": "512MB"}) as connection:
            connection.read_parquet(str(dataset_path)).create_view("source")
            oof, folds = evaluate_baseline_folds(
                connection, reference_report, reference, batch_rows=batch_rows, progress=progress
            )
        oof["equal_weight_candidate_mean"] = sum_prediction / len(candidate_scores)
        oof["equal_weight_large_loss"] = sum_risk[:, 0] / len(candidate_scores)
        oof["equal_weight_quantile"] = sum_risk[:, 1] / len(candidate_scores)
        output = _write_parquet(oof, output_root / "oof")
        results.append(
            {
                "horizon": horizon,
                "reference_report_id": reference_report.report_id,
                "comparison_rows": len(oof),
                "folds": folds,
                "candidates": candidate_scores,
                "baseline_scores": {
                    name: _scores(oof.rename(columns={name: "prediction"}))
                    for name in (*BASELINES, "equal_weight_candidate_mean")
                },
                "rule_scores": _rule_metrics(oof),
                "risk_definition": {
                    "event": "target <= large_loss_threshold",
                    "large_loss_threshold": reference_report.config.large_loss_threshold,
                    "quantile_alpha": reference_report.config.quantile_alpha,
                    "weighting": "equal_observation_rows",
                },
                "baseline_risk_scores": _baseline_risk_scores(oof, reference_report),
                "equal_weight_risk_scores": _risk_scores(
                    oof, reference_report, probability="equal_weight_large_loss",
                    quantile="equal_weight_quantile",
                ),
                "oof_path": str(output.resolve()),
                "oof_byte_sha256": output.stem,
            }
        )
        del reference, oof, sum_prediction, sum_risk, risk
        gc.collect()
    if _file_sha256(dataset_path) != source_hash:
        raise ValueError("baseline dataset changed during evaluation")
    sources = (
        "daily_baselines.py",
        "daily_simple_baselines.py",
        "models.py",
        "advanced.py",
        "selection.py",
        "production.py",
        "evaluation_audit.py",
        "evaluation_metrics.py",
        "research_metrics.py",
    )
    return write_audit_receipt(
        {
            "schema_version": VERSION,
            "research_only": True,
            "adoption_eligible": False,
            "feature_selection_id": features.feature_selection_id,
            "data_snapshot_id": snapshot.snapshot_id,
            "dataset_byte_sha256": source_hash,
            "locked_holdout_start": features.locked_holdout_start,
            "holdout_scored": False,
            "feature_names": V0_MANIFEST.feature_names,
            "ridge_alpha": 5.0,
            "additional_baseline_policy": {
                "role": "fixed_exploratory_diagnostic_not_adoption_gate",
                "elastic_net_alpha": ELASTIC_ALPHA,
                "elastic_net_l1_ratio": ELASTIC_L1_RATIO,
                "elastic_net_target_scaling": "none",
                "elastic_net_max_iterations": 50_000,
                "elastic_net_max_kkt_residual": 1e-9,
                "rule_features_positive_direction": RULE_FEATURES,
                "rule_equal_weight_components": RULES,
                "rule_normalization": "centered_within_date_midranks_minus1_to1",
                "rule_missing_constant_singleton": "neutral_zero_fixed_weight",
                "rule_universe": "all_source_features_on_scoring_dates_before_label_join",
                "rule_score_unit": "dimensionless_rank_not_return_or_probability",
            },
            "logistic_c": 1.0,
            "quantile_method": "training_empirical_linear_interpolation",
            "batch_rows": batch_rows,
            "results": results,
            "source_sha256": {
                name: _file_sha256(Path(__file__).with_name(name)) for name in sources
            },
            "dependencies": {
                name: version(name) for name in ("numpy", "pandas", "duckdb", "pyarrow", "scipy")
            },
            "limitations": [
                "Prediction diagnostics only; zero forecast is not a cash NAV strategy.",
                "Momentum uses unscaled trailing 20d return and training-only missing fallback.",
                "Equal-weight candidate mean is fixed, not a fitted or selected ensemble.",
                "No bootstrap significance, economic adoption, holdout scoring or live forecast.",
                "One quantile level cannot verify interval coverage or quantile crossing.",
                "Single-class logistic fits use an explicitly recorded empirical constant.",
                "Cost/tax/NAV, final selection and learned-ensemble adoption remain separate.",
            ],
        },
        output_root / "receipts",
    )
