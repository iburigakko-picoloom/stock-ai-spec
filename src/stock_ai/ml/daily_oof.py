"""Daily 5d/20d research predictions with receipt-time causal risk calibration."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

import duckdb
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from stock_ai.decision import DailyPortfolioDecisionEngine, DecisionCandidate
from stock_ai.domain import (
    MarketSnapshot,
    PortfolioProposal,
    PortfolioState,
    Prediction,
    PredictionUncertainty,
    Security,
)
from stock_ai.domain.models import DailyDecisionAudit, _require_aware
from stock_ai.ml.advanced import (
    AdvancedResearchReport,
    DecisionPredictionBlock,
    load_advanced_research_run,
)
from stock_ai.ml.campaign import CampaignBatchStatus, load_campaign_manifest
from stock_ai.ml.evaluation_audit import validate_development_oof, write_audit_receipt
from stock_ai.ml.production import _file_sha256, load_production_dataset_snapshot
from stock_ai.ml.selection import _authenticate_batch_report, load_development_feature_selection
from stock_ai.operations.daily import content_id

KEY = ["symbol", "trading_date"]
VERSION = "daily-oof-adapter-v1"


class DailyOofDay(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["daily-oof-day-v1"] = "daily-oof-day-v1"
    research_only: Literal[True] = True
    adoption_eligible: Literal[False] = False
    as_of: datetime
    predictions: tuple[Prediction, ...]
    blocked: tuple[DecisionPredictionBlock, ...]
    calibration_rows: int = Field(ge=0)
    calibration_dates: int = Field(ge=0)
    latest_calibration_available_at: datetime | None
    residual_rmse: float | None = Field(ge=0)
    model_version: str
    feature_version: str
    data_snapshot_id: str
    source_report_ids: tuple[str, str]
    minimum_calibration_dates: int = Field(ge=1)
    large_loss_threshold: float = Field(lt=0)
    quantile_alpha: float = Field(gt=0, lt=0.5)

    _aware = field_validator("as_of")(_require_aware)

    @model_validator(mode="after")
    def coherent_day(self) -> Self:
        symbols = [p.symbol for p in self.predictions]
        blocked = [b.symbol for b in self.blocked]
        if (
            len(symbols) != len(set(symbols))
            or len(blocked) != len(set(blocked))
            or set(symbols) & set(blocked)
        ):
            raise ValueError("daily prediction/block symbols must be unique and disjoint")
        if (
            self.calibration_dates > self.calibration_rows
            or bool(self.calibration_dates) != bool(self.calibration_rows)
            or bool(self.calibration_rows) != (self.residual_rmse is not None)
        ):
            raise ValueError("incoherent calibration counts or residual scale")
        if bool(self.calibration_rows) != (self.latest_calibration_available_at is not None):
            raise ValueError("calibration receipt time must match history")
        if self.latest_calibration_available_at is not None:
            _require_aware(self.latest_calibration_available_at)
            if self.latest_calibration_available_at >= self.as_of:
                raise ValueError("calibration receipt must precede the decision")
        if self.predictions and self.calibration_dates < self.minimum_calibration_dates:
            raise ValueError("daily predictions require the declared calibration history")
        for p in self.predictions:
            if (
                p.schema_version != 2
                or p.as_of != self.as_of
                or p.model_version != self.model_version
                or p.feature_version != self.feature_version
                or p.data_snapshot_id != self.data_snapshot_id
                or p.uncertainty.standard_error != self.residual_rmse
            ):
                raise ValueError("daily prediction provenance differs from its day")
        if any(b.as_of != self.as_of for b in self.blocked):
            raise ValueError("blocked prediction timestamps differ from their day")
        return self


def compact_oof(frame: pd.DataFrame, report: AdvancedResearchReport) -> pd.DataFrame:
    """Retain one candidate's declared absolute-return tasks; never mix model identities."""
    validate_development_oof(frame, report)
    if (
        len(report.config.horizons) != 1
        or report.config.horizons[0] not in (5, 20)
        or len(report.config.model_families) != 1
        or len(report.config.seeds) != 1
        or report.config.target_family != "return"
    ):
        raise ValueError("daily adapter requires one absolute-return candidate per horizon")
    if "as_of" not in frame or frame.as_of.isna().any():
        raise ValueError("OOF requires prediction availability timestamps")
    if any(pd.Timestamp(value).tzinfo is None for value in frame.as_of.unique()):
        raise ValueError("OOF as_of must be timezone-aware")
    dates = pd.to_datetime(frame.trading_date)
    as_of = pd.to_datetime(frame.as_of, utc=True)
    if (as_of.dt.tz_convert("Asia/Tokyo").dt.tz_localize(None).dt.normalize() <= dates).any():
        raise ValueError("daily close features require a subsequent decision date")
    reference = frame.loc[frame.task == "regression", [*KEY, "as_of", "label_end", "target"]]
    for _, part in frame.groupby("task", sort=False):
        check = part[[*KEY, "as_of"]].merge(reference[[*KEY, "as_of"]], on=KEY)
        if not (
            pd.to_datetime(check.as_of_x, utc=True) == pd.to_datetime(check.as_of_y, utc=True)
        ).all():
            raise ValueError("task prediction timestamps do not align")
    horizon = report.config.horizons[0]
    wide = frame.pivot(index=KEY, columns="task", values="prediction")
    wide = wide.join(reference.set_index(KEY)).reset_index()
    wide["as_of"] = pd.to_datetime(wide.as_of, utc=True)
    wide["label_end"] = pd.to_datetime(wide.label_end)
    columns = [*KEY, "as_of", "regression"]
    if horizon == 20:
        columns += ["quantile", "large_loss", "label_end", "target"]
    return wide[columns].rename(columns={"regression": f"expected_return_{horizon}d"})


class DailyOofAdapter:
    """One explicit 5d/20d candidate pair, not a selected or calibrated ensemble.

    Only the requested day's rows become typed objects. The sorted receipt-time
    prefix keeps repeated daily risk queries independent of future outcomes.
    """

    def __init__(
        self,
        five: pd.DataFrame,
        twenty: pd.DataFrame,
        availability: pd.DataFrame,
        *,
        reports: tuple[AdvancedResearchReport, AdvancedResearchReport],
        minimum_calibration_dates: int = 20,
    ) -> None:
        if type(minimum_calibration_dates) is not int or minimum_calibration_dates < 1:
            raise ValueError("minimum calibration dates must be a positive integer")
        r5, r20 = reports
        if r5.config.horizons != (5,) or r20.config.horizons != (20,):
            raise ValueError("reports must be ordered 5d then 20d")
        if (r5.data_snapshot_id, r5.locked_holdout_start) != (
            r20.data_snapshot_id,
            r20.locked_holdout_start,
        ):
            raise ValueError("daily horizons must share data and holdout boundary")
        self.reports = reports
        self.minimum_dates = minimum_calibration_dates
        self.model_version = (
            VERSION
            + ":"
            + content_id(
                {
                    "reports": [r.report_id for r in reports],
                    "minimum_dates": minimum_calibration_dates,
                }
            )
        )
        self.feature_version = "daily-features:" + content_id(
            {str(r.config.horizons[0]): [r.feature_manifest_hash, r.feature_names] for r in reports}
        )
        boundary = pd.Timestamp(r20.locked_holdout_start)
        for frame, horizon in ((five, 5), (twenty, 20)):
            required = [*KEY, "as_of", f"expected_return_{horizon}d"]
            if horizon == 20:
                required += ["quantile", "large_loss", "target", "label_end"]
            if frame.empty or frame[required].isna().any().any():
                raise ValueError("compact forecast fields must be nonempty and nonmissing")
            numeric = [f"expected_return_{horizon}d"]
            if horizon == 20:
                numeric += ["quantile", "large_loss", "target"]
            if not np.isfinite(frame[numeric].to_numpy(dtype=float)).all():
                raise ValueError("compact forecast values must be finite")
            if any(pd.Timestamp(value).tzinfo is None for value in frame.as_of.unique()):
                raise ValueError("compact forecast as_of must be timezone-aware")
            if (pd.to_datetime(frame.trading_date) >= boundary).any():
                raise ValueError("forecast crosses locked holdout")
        if not twenty.large_loss.between(0, 1).all():
            raise ValueError("large-loss probabilities outside [0,1]")
        if five.duplicated(KEY).any() or twenty.duplicated(KEY).any():
            raise ValueError("duplicate compact forecast key")
        meta = availability[[*KEY, "as_of", "label_end", "label_available_at"]].copy()
        if meta.duplicated(KEY).any() or meta.isna().any().any():
            raise ValueError("duplicate or missing label availability metadata")
        if any(
            pd.Timestamp(value).tzinfo is None
            for column in ("as_of", "label_available_at")
            for value in meta[column].unique()
        ):
            raise ValueError("label availability timestamps must be timezone-aware")
        # Require complete source coverage instead of silently dropping OOF rows.
        history = twenty.merge(meta, on=KEY, suffixes=("", "_source"), validate="one_to_one")
        if len(history) != len(twenty):
            raise ValueError("label availability does not cover every 20d OOF row")
        if not (
            pd.to_datetime(history.as_of, utc=True)
            == pd.to_datetime(history.as_of_source, utc=True)
        ).all():
            raise ValueError("source/OOF prediction timestamps differ")
        if not (
            pd.to_datetime(history.label_end) == pd.to_datetime(history.label_end_source)
        ).all():
            raise ValueError("source/OOF label endpoints differ")
        history["label_available_at"] = pd.to_datetime(history.label_available_at, utc=True)
        # A daily-close outcome is not mature before the end of its endpoint date.
        earliest = pd.to_datetime(history.label_end).dt.tz_localize("Asia/Tokyo")
        if (history.label_available_at < earliest).any():
            raise ValueError("label availability precedes its endpoint")
        if (pd.to_datetime(history.trading_date) >= boundary).any() or (
            pd.to_datetime(history.label_end) >= boundary
        ).any():
            raise ValueError("calibration history crosses locked holdout")
        history["squared_error"] = (history.target - history.expected_return_20d) ** 2
        # Require both receipt time and the next local date after the endpoint.
        history["eligible_at"] = pd.concat(
            [history.label_available_at, (earliest + pd.DateOffset(days=1)).dt.tz_convert("UTC")],
            axis=1,
        ).max(axis=1)
        history = history.sort_values(["eligible_at", "trading_date", "symbol"]).reset_index(
            drop=True
        )
        self._cutoffs = (
            history.eligible_at.astype("datetime64[ns, UTC]").astype("int64").to_numpy(copy=True)
        )
        self._sums = history.squared_error.cumsum().to_numpy(dtype=float)
        self._dates = (~history.trading_date.duplicated()).cumsum().to_numpy(dtype=int)
        self._latest_receipt = history.label_available_at.cummax()
        combined = five.merge(
            twenty, on=KEY, how="outer", suffixes=("_5d", "_20d"), validate="one_to_one"
        )
        both = combined.as_of_5d.notna() & combined.as_of_20d.notna()
        if not (combined.loc[both, "as_of_5d"] == combined.loc[both, "as_of_20d"]).all():
            raise ValueError("horizon prediction timestamps differ")
        combined["as_of"] = combined.as_of_20d.fillna(combined.as_of_5d)
        if combined.duplicated(["symbol", "as_of"]).any():
            raise ValueError("multiple feature dates produce one daily prediction")
        self.frame = (
            combined[
                [
                    *KEY,
                    "as_of",
                    "expected_return_5d",
                    "expected_return_20d",
                    "quantile",
                    "large_loss",
                ]
            ]
            .sort_values(["as_of", "symbol"])
            .reset_index(drop=True)
        )

    def at(self, as_of: datetime, *, required_symbols: Sequence[str] = ()) -> DailyOofDay:
        as_of = _require_aware(as_of)
        if (
            pd.Timestamp(as_of).tz_convert("Asia/Tokyo").date()
            >= pd.Timestamp(self.reports[0].locked_holdout_start).date()
        ):
            raise ValueError("requested decision is inside locked holdout")
        if len(required_symbols) != len(set(required_symbols)) or any(
            not s for s in required_symbols
        ):
            raise ValueError("required symbols must be nonempty and unique")
        count = int(np.searchsorted(self._cutoffs, pd.Timestamp(as_of).value, side="left"))
        dates = int(self._dates[count - 1]) if count else 0
        rmse = math.sqrt(float(self._sums[count - 1]) / count) if count else None
        rows = self.frame.loc[self.frame.as_of == pd.Timestamp(as_of)]
        predictions: list[Prediction] = []
        blocks: list[DecisionPredictionBlock] = []
        present = set(rows.symbol)
        for symbol in sorted(set(required_symbols) - present):
            blocks.append(
                DecisionPredictionBlock(symbol=symbol, as_of=as_of, reason="MISSING_DAILY_FORECAST")
            )
        for row in rows.to_dict(orient="records"):
            reason = None
            if pd.isna(row["expected_return_5d"]) or pd.isna(row["expected_return_20d"]):
                reason = "BLOCKED_BY_HORIZON_ALIGNMENT: requires 5d/20d"
            elif dates < self.minimum_dates:
                reason = "BLOCKED_BY_CALIBRATION_HISTORY: insufficient received past outcomes"
            if reason:
                blocks.append(
                    DecisionPredictionBlock(symbol=str(row["symbol"]), as_of=as_of, reason=reason)
                )
                continue
            assert rmse is not None
            predictions.append(
                Prediction(
                    schema_version=2,
                    active_horizons=(5, 20),
                    risk_horizon=20,
                    symbol=str(row["symbol"]),
                    as_of=as_of,
                    expected_return_1d=None,
                    expected_return_5d=row["expected_return_5d"],
                    expected_return_20d=row["expected_return_20d"],
                    downside_quantile=row["quantile"],
                    large_loss_probability=row["large_loss"],
                    uncertainty=PredictionUncertainty(
                        standard_error=rmse,
                        model_disagreement=0,
                        coverage_warning=(
                            "Received past-only 20d residual RMSE; not a confidence "
                            "interval; single candidate per horizon"
                        ),
                    ),
                    model_version=self.model_version,
                    feature_version=self.feature_version,
                    data_snapshot_id=self.reports[0].data_snapshot_id,
                )
            )
        return DailyOofDay(
            as_of=as_of,
            predictions=tuple(predictions),
            blocked=tuple(blocks),
            calibration_rows=count,
            calibration_dates=dates,
            latest_calibration_available_at=self._latest_receipt.iloc[count - 1].to_pydatetime()
            if count
            else None,
            residual_rmse=rmse,
            model_version=self.model_version,
            feature_version=self.feature_version,
            data_snapshot_id=self.reports[0].data_snapshot_id,
            source_report_ids=(self.reports[0].report_id, self.reports[1].report_id),
            minimum_calibration_dates=self.minimum_dates,
            large_loss_threshold=self.reports[1].config.large_loss_threshold,
            quantile_alpha=self.reports[1].config.quantile_alpha,
        )


def load_daily_oof_adapter(
    *,
    feature_selection_path: Path,
    campaign_paths: Sequence[Path],
    dataset_path: Path,
    family: str,
    seed: int,
    minimum_calibration_dates: int = 20,
) -> DailyOofAdapter:
    """Authenticate source identity, then project development label times only.

    Source authentication hashes all logical columns, including protected rows,
    without scoring them. Only keys leave that authentication step; calibration
    receives the filtered development timestamps and authenticated OOF outcomes.
    """
    features = load_development_feature_selection(feature_selection_path)
    original_bytes_hash = _file_sha256(dataset_path)
    snapshot, authenticated_keys = load_production_dataset_snapshot(dataset_path, columns=KEY)
    del authenticated_keys
    if snapshot.snapshot_id != features.data_snapshot_id:
        raise ValueError("dataset differs from frozen feature selection")
    compact: dict[int, pd.DataFrame] = {}
    reports: dict[int, AdvancedResearchReport] = {}
    for path in campaign_paths:
        manifest = load_campaign_manifest(path)
        for batch in manifest.batches:
            if batch.model_family != family or batch.seed != seed or batch.horizon not in (5, 20):
                continue
            if (
                batch.horizon in reports
                or batch.status is not CampaignBatchStatus.SUCCEEDED
                or batch.oof_path is None
            ):
                raise ValueError("daily candidate pair is duplicated or incomplete")
            report, oof = load_advanced_research_run(Path(batch.oof_path))
            try:
                _authenticate_batch_report(manifest, batch, report)
                selected = next(item for item in features.horizons if item.horizon == batch.horizon)
                if (
                    report.data_snapshot_id != features.data_snapshot_id
                    or report.feature_names != selected.feature_names
                    or report.feature_manifest_hash != features.feature_manifest_hash
                    or report.feature_snapshot_id != features.feature_snapshot_id
                    or report.locked_holdout_start != features.locked_holdout_start
                    or manifest.build_id != features.build_id
                    or report.config.run_ablations
                ):
                    raise ValueError("candidate differs from frozen daily data/features")
                compact[batch.horizon] = compact_oof(oof, report)
                reports[batch.horizon] = report
            finally:
                del oof
    if set(reports) != {5, 20}:
        raise ValueError("daily adapter requires both 5d and 20d candidates")
    with duckdb.connect() as connection:
        connection.register("daily_oof_keys", compact[20][KEY])
        availability = connection.execute(
            """
            SELECT d.symbol, d.trading_date, d.as_of, d.label_end_date_20d AS label_end,
                   label_available_at_20d AS label_available_at
            FROM read_parquet(?) AS d
            JOIN daily_oof_keys AS k ON d.symbol=k.symbol AND d.trading_date=k.trading_date
            WHERE d.trading_date < CAST(? AS TIMESTAMP)
              AND d.label_end_date_20d < CAST(? AS TIMESTAMP)
              AND d.label_status_20d = 'AVAILABLE'
        """,
            [str(dataset_path), features.locked_holdout_start, features.locked_holdout_start],
        ).df()
    if _file_sha256(dataset_path) != original_bytes_hash:
        raise ValueError("dataset changed during label-time projection")
    return DailyOofAdapter(
        compact[5],
        compact[20],
        availability,
        reports=(reports[5], reports[20]),
        minimum_calibration_dates=minimum_calibration_dates,
    )


def write_daily_oof_day(day: DailyOofDay, root: Path) -> Path:
    day = DailyOofDay.model_validate(day.model_dump())
    return write_audit_receipt(
        {
            "day": day.model_dump(mode="json"),
            "adapter_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "limitations": [
                "development OOF only",
                "single-vintage declarations remain research-only",
                "no final selection, holdout evaluation, personalized portfolio or actual order",
            ],
        },
        root,
    )


def propose_daily_oof(
    day: DailyOofDay,
    *,
    portfolio: PortfolioState,
    candidate_symbols: Sequence[str],
    securities: Mapping[str, Security],
    market: MarketSnapshot,
    average_daily_trading_values: Mapping[str, Decimal],
    engine: DailyPortfolioDecisionEngine,
    generated_at: datetime,
) -> PortfolioProposal:
    """Evaluate explicit candidates and every holding using known decision-time marks.

    Missing candidate predictions can be inspected in day.blocked. Missing a held
    symbol stops the entire comparison; it never removes the position or assumes
    a zero-return forecast. This creates a research proposal, never an execution.
    """
    day = DailyOofDay.model_validate(day.model_dump())
    generated_at = _require_aware(generated_at)
    if day.as_of != portfolio.as_of or market.as_of != day.as_of:
        raise ValueError("daily forecasts, portfolio and market must have the same as_of")
    if generated_at < day.as_of:
        raise ValueError("proposal cannot precede daily predictions")
    if engine.config.horizon_weights != (Decimal(0), Decimal(0), Decimal(1)):
        raise ValueError("daily comparison requires the 20d decision policy")
    if len(set(candidate_symbols)) != len(candidate_symbols):
        raise ValueError("candidate symbols must be unique")
    predictions = {prediction.symbol: prediction for prediction in day.predictions}
    holdings = {position.symbol for position in portfolio.positions}
    if missing := holdings - set(predictions):
        raise ValueError(f"held symbols lack usable daily predictions: {sorted(missing)}")
    required = holdings | set(candidate_symbols)
    if missing := required - set(predictions):
        raise ValueError(f"candidate symbols lack usable daily predictions: {sorted(missing)}")
    if missing := required - (set(securities) & set(market.prices)):
        raise ValueError(f"daily comparison lacks security/market evidence: {sorted(missing)}")
    positions = tuple(
        position.model_copy(update={"market_price": market.prices[position.symbol]})
        for position in portfolio.positions
    )
    current = PortfolioState.model_validate({**portfolio.model_dump(), "positions": positions})
    candidates = tuple(
        DecisionCandidate(
            security=securities[symbol],
            account_bucket_id=bucket.bucket_id,
            price=market.prices[symbol],
            prediction=predictions[symbol],
            average_daily_trading_value=average_daily_trading_values.get(symbol),
        )
        for bucket in current.account_buckets
        for symbol in sorted(required)
    )
    proposal = engine.propose(
        portfolio=current,
        candidates=candidates,
        generated_at=generated_at,
        model_bundle_version=day.model_version,
    )
    audit = DailyDecisionAudit(
        as_of=day.as_of,
        forecast_content_sha256=content_id(day.model_dump(mode="json")),
        market_content_sha256=content_id(market.model_dump(mode="json")),
        portfolio_content_sha256=content_id(current.model_dump(mode="json")),
        candidate_evidence_sha256=content_id(
            {"candidates": [candidate.model_dump(mode="json") for candidate in candidates]}
        ),
        source_report_ids=day.source_report_ids,
    )
    return PortfolioProposal.model_validate(
        {
            **proposal.model_dump(),
            "proposal_id": proposal.proposal_id
            + "-daily-"
            + content_id(audit.model_dump(mode="json"))[:16],
            "daily_audit": audit,
            "is_research_only": True,
        }
    )
