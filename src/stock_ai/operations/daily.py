"""Immutable daily forecasts and human research, independent of morning capture."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime
from typing import Any, Final, Literal, Self

from pydantic import Field, field_validator, model_validator

from stock_ai.domain.models import DomainModel, Prediction, ReturnOnlyPrediction, _require_aware

RESEARCH_CRITERIA = (
    "earnings_quality",
    "valuation_expectations",
    "balance_sheet_dilution",
    "catalyst_timing",
    "industry",
    "liquidity_portfolio_risk",
    "contrary_facts",
)

DAILY_NEXT_SESSION_CLOSE_LABEL: Final = "next_session_adjusted_close_to_h_sessions_later"
QUOTE_SESSION_LABEL: Final = "quote_session_adjusted_close_to_h_sessions_later"
DailyLabelDefinition = Literal[
    "quote_session_adjusted_close_to_h_sessions_later",
    "next_session_adjusted_close_to_h_sessions_later",
]


def require_daily_close_label(definition: str) -> None:
    """Archives stay readable; new inputs must match the actual production target."""
    if definition != DAILY_NEXT_SESSION_CLOSE_LABEL:
        raise ValueError("FORECAST_LABEL_DEFINITION_UNVERIFIED")


def daily_close_forecast_basis() -> dict[str, str | bool]:
    return {
        "T": "input quote session",
        "entry": "next trading session close, after the 11:30 prediction cutoff",
        "formula": "adjusted_close[T+1+h] / adjusted_close[T+1] - 1",
        "horizon_unit": "trading_sessions",
        "is_execution_return": False,
        "fees_taxes_dividend_cashflows_included": False,
        "dividends_zero_confirmed": False,
    }


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_id(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class PredictionSnapshot(DomainModel):
    """Original model output. Human research can only reference, never replace it."""

    schema_version: Literal["daily-prediction-snapshot-v1"] = "daily-prediction-snapshot-v1"
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime
    generated_at: datetime
    data_as_of: datetime
    mode: Literal["research", "paper", "owner_approved"] = "research"
    adoption_review_id: str | None = None
    selection_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    feature_version: str = Field(min_length=1)
    data_snapshot_id: str = Field(min_length=1)
    active_horizons: tuple[Literal[5, 20], ...] = (5, 20)
    risk_horizon: Literal[20] | None = 20
    unit: Literal["fractional_return"] = "fractional_return"
    label_definition: DailyLabelDefinition = DAILY_NEXT_SESSION_CLOSE_LABEL
    price_semantics: Literal["daily_close_research_proxy"] = "daily_close_research_proxy"
    large_loss_threshold: float | None = Field(gt=-1, lt=0)
    downside_quantile_alpha: float | None = Field(gt=0, lt=0.5)
    candidate_symbols: tuple[str, ...]
    holding_symbols: tuple[str, ...]
    predictions: tuple[Prediction | ReturnOnlyPrediction, ...]
    blocking_reasons: tuple[str, ...] = ()

    _aware = field_validator("as_of", "generated_at", "data_as_of")(_require_aware)

    @model_validator(mode="after")
    def coherent_snapshot(self) -> Self:
        if self.data_as_of > self.as_of or self.generated_at < self.as_of:
            raise ValueError("daily snapshot timestamps are out of order")
        if self.active_horizons != (5, 20):
            raise ValueError("daily snapshot requires ordered 5d/20d horizons")
        for symbols in (self.candidate_symbols, self.holding_symbols):
            if len(symbols) != len(set(symbols)) or any(not symbol for symbol in symbols):
                raise ValueError("daily universe symbols must be nonempty and unique")
        symbols = tuple(item.symbol for item in self.predictions)
        if (
            len(symbols) != len(set(symbols))
            or set(symbols) != (set(self.candidate_symbols) | set(self.holding_symbols))
            or not symbols
        ):
            raise ValueError("predictions must exactly cover candidates and all holdings")
        for prediction in self.predictions:
            if (
                prediction.schema_version not in (2, 3)
                or prediction.as_of != self.as_of
                or prediction.model_version != self.model_version
                or prediction.feature_version != self.feature_version
                or prediction.data_snapshot_id != self.data_snapshot_id
            ):
                raise ValueError("prediction does not match snapshot provenance")
        returns_only = all(isinstance(p, ReturnOnlyPrediction) for p in self.predictions)
        if returns_only:
            if (self.mode != "research" or self.adoption_review_id is not None
                    or any(x is not None for x in (
                        self.risk_horizon, self.large_loss_threshold, self.downside_quantile_alpha,
                    ))):
                raise ValueError("return-only snapshot is unadopted research with unavailable risk")
        elif (any(isinstance(p, ReturnOnlyPrediction) for p in self.predictions)
              or self.risk_horizon != 20 or self.large_loss_threshold is None
              or self.downside_quantile_alpha is None):
            raise ValueError("daily risk snapshot requires consistent complete risk outputs")
        if self.mode == "owner_approved" and self.blocking_reasons:
            raise ValueError("blocked snapshot cannot claim owner-approved operation")
        if (self.mode == "owner_approved") != (self.adoption_review_id is not None):
            raise ValueError("owner-approved snapshots require an explicit adoption review")
        if self.snapshot_id != content_id(self.model_dump(mode="json", exclude={"snapshot_id"})):
            raise ValueError("prediction snapshot identity mismatch")
        return self

    @property
    def risk_available(self) -> bool:
        return all(isinstance(p, Prediction) for p in self.predictions)

    @classmethod
    def create(cls, **values: Any) -> PredictionSnapshot:
        # Validate all fields before computing the identity; only the ID is provisional.
        provisional = cls.model_construct(snapshot_id="0" * 64, **values)
        data = provisional.model_dump(mode="json", exclude={"snapshot_id"})
        return cls.model_validate({**data, "snapshot_id": content_id(data)})

    def research_symbols(self) -> tuple[str, ...]:
        ordered = sorted(
            self.predictions, key=lambda item: (-item.expected_return_20d, item.symbol)
        )
        candidates = set(self.candidate_symbols)
        top = [item.symbol for item in ordered if item.symbol in candidates][:20]
        return tuple(dict.fromkeys([*top, *sorted(self.holding_symbols)]))


class OwnerAdoptionReview(DomainModel):
    """An owner's decision after evidence review; elapsed paper days never approve it."""

    schema_version: Literal["owner-adoption-review-v1"] = "owner-adoption-review-v1"
    review_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_receipt_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_at: datetime
    decision: Literal["adopt", "continue_paper", "reject"]
    unresolved_gates: tuple[str, ...]
    acknowledged_limitations: tuple[str, ...]
    note: str = Field(min_length=1, max_length=4000)
    actor: Literal["owner_manual"] = "owner_manual"

    _aware = field_validator("reviewed_at")(_require_aware)

    @model_validator(mode="after")
    def explicit_review(self) -> Self:
        if self.decision == "adopt" and self.unresolved_gates:
            raise ValueError("unresolved evaluation/settings gates prevent adoption")
        if self.review_id != content_id(self.model_dump(mode="json", exclude={"review_id"})):
            raise ValueError("adoption review identity mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> OwnerAdoptionReview:
        provisional = cls.model_construct(review_id="0" * 64, **values)
        data = provisional.model_dump(mode="json", exclude={"review_id"})
        return cls.model_validate({**data, "review_id": content_id(data)})


class ResearchSource(DomainModel):
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(pattern=r"^https://", max_length=2000)
    published_at: datetime
    checked_at: datetime

    _aware = field_validator("published_at", "checked_at")(_require_aware)

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.published_at > self.checked_at:
            raise ValueError("research source cannot be checked before publication")
        return self


class ResearchFinding(DomainModel):
    criterion: str
    assessment: Literal["support", "caution", "defer"]
    note: str = Field(min_length=1, max_length=4000)
    sources: tuple[ResearchSource, ...] = ()

    @model_validator(mode="after")
    def supported_finding(self) -> Self:
        if self.criterion not in RESEARCH_CRITERIA:
            raise ValueError("unknown company research criterion")
        if self.assessment != "defer" and not self.sources:
            raise ValueError("support/caution requires inspectable sources")
        return self


class CompanyResearchRecord(DomainModel):
    schema_version: Literal["company-research-v1"] = "company-research-v1"
    research_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    prediction_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(min_length=1)
    reviewed_at: datetime
    conclusion: Literal["support", "caution", "defer"]
    findings: tuple[ResearchFinding, ...]
    author: Literal["owner_manual"] = "owner_manual"

    _aware = field_validator("reviewed_at")(_require_aware)

    @model_validator(mode="after")
    def fixed_criteria(self) -> Self:
        if tuple(item.criterion for item in self.findings) != RESEARCH_CRITERIA:
            raise ValueError("research requires the seven ordered criteria")
        if self.conclusion == "support" and any(
            item.assessment == "defer" for item in self.findings
        ):
            raise ValueError("incomplete research cannot conclude support")
        if any(
            source.checked_at > self.reviewed_at
            for item in self.findings
            for source in item.sources
        ):
            raise ValueError("research review precedes source checks")
        if self.research_id != content_id(self.model_dump(mode="json", exclude={"research_id"})):
            raise ValueError("company research identity mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> CompanyResearchRecord:
        provisional = cls.model_construct(research_id="0" * 64, **values)
        data = provisional.model_dump(mode="json", exclude={"research_id"})
        return cls.model_validate({**data, "research_id": content_id(data)})


def validate_research_link(record: CompanyResearchRecord, snapshot: PredictionSnapshot) -> None:
    if record.prediction_snapshot_id != snapshot.snapshot_id:
        raise ValueError("research references another prediction snapshot")
    if record.symbol not in snapshot.research_symbols():
        raise ValueError("research must cover a top-20 candidate or a holding")
    if record.reviewed_at < snapshot.generated_at:
        raise ValueError("research review predates the original prediction")


def export_prediction_snapshot(snapshot: PredictionSnapshot, *, format: str = "json") -> str:
    """All exports describe the same immutable original snapshot, including missing 1d."""
    if format == "json":
        return canonical_json(snapshot.model_dump(mode="json")) + "\n"
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(
            [
                "snapshot_id",
                "as_of",
                "data_as_of",
                "symbol",
                "return_1d",
                "return_5d",
                "return_20d",
                "downside_20d",
                "loss_probability_20d",
                "unit",
                "label_definition",
                "model_version",
                "feature_version",
                "data_snapshot_id",
                "mode",
            ]
        )
        for item in snapshot.predictions:
            writer.writerow(
                [
                    snapshot.snapshot_id,
                    snapshot.as_of.isoformat(),
                    snapshot.data_as_of.isoformat(),
                    item.symbol,
                    "",
                    item.expected_return_5d,
                    item.expected_return_20d,
                    item.downside_quantile,
                    item.large_loss_probability,
                    snapshot.unit,
                    snapshot.label_definition,
                    snapshot.model_version,
                    snapshot.feature_version,
                    snapshot.data_snapshot_id,
                    snapshot.mode,
                ]
            )
        return stream.getvalue()
    if format == "markdown":
        lines = [
            f"# 日次原予測 {snapshot.as_of.isoformat()}",
            f"Snapshot: {snapshot.snapshot_id}",
            f"Data: {snapshot.data_as_of.isoformat()} / Model: {snapshot.model_version}",
            f"Unit: {snapshot.unit} / Label: {snapshot.label_definition} / Mode: {snapshot.mode}",
            ("入力株価日Tの翌営業日終値からh営業日後までの研究ラベル。実約定後損益ではありません。"
             if snapshot.label_definition == DAILY_NEXT_SESSION_CLOSE_LABEL else
             "入力株価日終値を起点とする別ラベルです。原本を保持し、新しい判断入力には使用できません。"),
            "",
            "| 銘柄 | 1日 | 5日 | 20日 | 20日下振れ | 20日下落確率 |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for item in snapshot.predictions:
            downside = ("未提供" if item.downside_quantile is None
                        else f"{item.downside_quantile:.6g}")
            probability = ("未提供" if item.large_loss_probability is None
                           else f"{item.large_loss_probability:.6g}")
            lines.append(
                f"| {item.symbol} | 未提供 | {item.expected_return_5d:.6g} | "
                f"{item.expected_return_20d:.6g} | {downside} | {probability} |"
            )
        return "\n".join(lines) + "\n"
    raise ValueError("snapshot export format must be json, csv or markdown")
