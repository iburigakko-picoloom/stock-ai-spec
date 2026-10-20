"""Data-only private model bundle with explicit, pinned calibration and adoption lineage."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictFloat, StrictInt, ValidationInfo, model_validator

from stock_ai.operations.daily import (
    DAILY_NEXT_SESSION_CLOSE_LABEL,
    DailyLabelDefinition,
    OwnerAdoptionReview,
    canonical_json,
    content_id,
    require_daily_close_label,
)
from stock_ai.operations.manual_portfolio import Digest, InputModel, strict_json

from .portable_model import predict, validate

REQUIRED_HEADS = frozenset(((5, "regression"), (20, "regression"),
                            (20, "quantile"), (20, "large_loss")))
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


class Calibration(InputModel):
    method: Literal["received_past_only_20d_residual_rmse"]
    residual_rmse: Annotated[StrictFloat, Field(ge=0)]
    rows: Annotated[StrictInt, Field(ge=1)]
    dates: Annotated[StrictInt, Field(ge=20)]
    latest_label_available_at: AwareDatetime
    fitted_at: AwareDatetime
    source_evidence_sha256: Digest

    @model_validator(mode="after")
    def received_history(self) -> Self:
        if self.dates > self.rows or self.latest_label_available_at > self.fitted_at:
            raise ValueError("Invalid calibration history")
        return self


class ModelHead(InputModel):
    horizon: Literal[5, 20]
    task: Literal["regression", "quantile", "large_loss"]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]
    sha256: Digest
    content: Annotated[str, Field(min_length=1, max_length=MAX_BUNDLE_BYTES)]

    def decoded(self, selection: dict) -> dict:
        if hashlib.sha256(self.content.encode()).hexdigest() != self.sha256:
            raise ValueError("Model head content changed")
        value = strict_json(self.content)
        if value["task"] != self.task:
            raise ValueError("Model head task mismatch")
        names = next(x["feature_names"] for x in selection["horizons"]
                     if x["horizon"] == self.horizon)
        validate(value)
        if not set(value["preprocessor"]["retained"]) <= set(names):
            raise ValueError("Model features differ from the frozen selection")
        return value


class ModelBundle(InputModel):
    schema_version: Literal["stockai-mobile-bundle-v1"] = "stockai-mobile-bundle-v1"
    bundle_id: Digest
    created_at: AwareDatetime
    trained_at: AwareDatetime
    training_data_cutoff: AwareDatetime
    feature_selection_id: Digest
    feature_manifest_hash: Digest
    selection_id: Digest
    adoption_review: OwnerAdoptionReview
    calibration: Calibration
    large_loss_threshold: Annotated[StrictFloat, Field(gt=-1, lt=0)]
    downside_quantile_alpha: Annotated[StrictFloat, Field(gt=0, lt=0.5)]
    unit: Literal["fractional_return"] = "fractional_return"
    label_definition: DailyLabelDefinition = DAILY_NEXT_SESSION_CLOSE_LABEL
    price_semantics: Literal["daily_close_research_proxy"] = "daily_close_research_proxy"
    heads: Annotated[tuple[ModelHead, ...], Field(min_length=4, max_length=4)]

    @model_validator(mode="after")
    def coherent_bundle(self, info: ValidationInfo) -> Self:
        if {(x.horizon, x.task) for x in self.heads} != REQUIRED_HEADS:
            raise ValueError("Bundle requires exactly the four declared 5d/20d heads")
        if len({x.model_id for x in self.heads}) != 4:
            raise ValueError("Model head IDs must be unique")
        if (self.adoption_review.selection_id != self.selection_id
                or self.adoption_review.decision not in ("adopt", "continue_paper")):
            raise ValueError("Explicit owner review of the same selection required")
        if (self.training_data_cutoff > self.trained_at
                or max(self.trained_at, self.calibration.fitted_at,
                       self.adoption_review.reviewed_at) > self.created_at):
            raise ValueError("Model bundle timestamps are out of order")
        if not (info.context or {}).get("creating") and self.bundle_id != content_id(
            self.model_dump(mode="json", exclude={"bundle_id"})
        ):
            raise ValueError("Model bundle identity mismatch")
        return self

    def at(self, cutoff: datetime) -> None:
        if (cutoff.tzinfo is None or self.created_at > cutoff
                or self.training_data_cutoff >= cutoff
                or self.calibration.latest_label_available_at >= cutoff):
            raise ValueError("Model or calibration was unavailable at the alpha cutoff")

    @classmethod
    def create(cls, **values) -> ModelBundle:
        # A packaging helper does not create an approval pin.
        provisional = cls.model_validate({**values, "bundle_id": "0" * 64},
                                         context={"creating": True})
        payload = provisional.model_dump(mode="json", exclude={"bundle_id"})
        return cls.model_validate({**payload, "bundle_id": content_id(payload)})


class ResearchModelBundle(InputModel):
    """Two authenticated integration heads; no fabricated adoption or calibration."""

    schema_version: Literal["stockai-mobile-research-bundle-v1"]
    bundle_id: Digest
    created_at: AwareDatetime
    trained_at: AwareDatetime
    training_data_cutoff: AwareDatetime
    feature_selection_id: Digest
    feature_manifest_hash: Digest
    selection_id: Digest
    source_evidence_sha256: Digest
    use: Literal["return-only-research"] = "return-only-research"
    adoption_review: None = None
    calibration: None = None
    large_loss_threshold: None = None
    downside_quantile_alpha: None = None
    unit: Literal["fractional_return"] = "fractional_return"
    label_definition: DailyLabelDefinition = DAILY_NEXT_SESSION_CLOSE_LABEL
    price_semantics: Literal["daily_close_research_proxy"] = "daily_close_research_proxy"
    heads: Annotated[tuple[ModelHead, ...], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def coherent_research(self, info: ValidationInfo) -> Self:
        if ({(h.horizon, h.task) for h in self.heads} != {(5, "regression"), (20, "regression")}
                or len({h.model_id for h in self.heads}) != 2):
            raise ValueError("Research bundle requires exactly two daily return heads")
        if not self.training_data_cutoff <= self.trained_at <= self.created_at:
            raise ValueError("Research bundle timestamps are out of order")
        if not (info.context or {}).get("creating") and self.bundle_id != content_id(
            self.model_dump(mode="json", exclude={"bundle_id"})
        ):
            raise ValueError("Research bundle identity mismatch")
        return self

    def at(self, cutoff: datetime) -> None:
        if (cutoff.tzinfo is None or self.created_at > cutoff
                or self.training_data_cutoff >= cutoff):
            raise ValueError("Research model was unavailable at the alpha cutoff")

    @classmethod
    def create(cls, **values) -> ResearchModelBundle:
        value = cls.model_validate({**values, "bundle_id": "0" * 64}, context={"creating": True})
        data = value.model_dump(mode="json", exclude={"bundle_id"})
        return cls.model_validate({**data, "bundle_id": content_id(data)})


def reviewed(
    content: str, policy: dict, selection: dict | Callable[[], dict],
) -> tuple[ModelBundle | ResearchModelBundle, dict]:
    if not isinstance(content, str) or len(content.encode()) > MAX_BUNDLE_BYTES:
        raise ValueError("Model bundle size limit")
    value = strict_json(content)
    if value.get("schema_version") != "stockai-mobile-research-bundle-v1":
        return approved(content, policy, selection)
    digest = hashlib.sha256(content.encode()).hexdigest()
    pins = [p for p in policy.get("research_bundles", []) if p["sha256"] == digest]
    if len(pins) != 1:
        raise ValueError("RESEARCH_BUNDLE_NOT_REVIEWED")
    entry = pins[0]
    for key in ("source_evidence_sha256", "pc_parity_evidence_sha256",
                "device_parity_evidence_sha256"):
        if not isinstance(entry.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", entry[key]):
            raise ValueError("RESEARCH_BUNDLE_EVIDENCE_MISSING")
    if (entry.get("distribution_review") != "private-research-import-approved"
            or entry.get("use") != "return-only-research"):
        raise ValueError("RESEARCH_BUNDLE_DISTRIBUTION_NOT_REVIEWED")
    selection = selection() if callable(selection) else selection
    bundle = ResearchModelBundle.model_validate(value)
    require_daily_close_label(bundle.label_definition)
    if (entry.get("bundle_id") != bundle.bundle_id
            or entry["source_evidence_sha256"] != bundle.source_evidence_sha256
            or any(getattr(bundle, k) != selection[k]
                   for k in ("feature_selection_id", "feature_manifest_hash"))):
        raise ValueError("Research bundle evidence/selection lineage mismatch")
    for head in bundle.heads:
        head.decoded(selection)
    return bundle, entry


def approved(content: str, policy: dict,
             selection: dict | Callable[[], dict]) -> tuple[ModelBundle, dict]:
    if not isinstance(content, str) or len(content.encode()) > MAX_BUNDLE_BYTES:
        raise ValueError("Model bundle size limit")
    digest = hashlib.sha256(content.encode()).hexdigest()
    entries = [x for x in policy.get("approved_bundles", []) if x["sha256"] == digest]
    if len(entries) != 1:
        raise ValueError("MODEL_BUNDLE_NOT_REVIEWED")
    entry = entries[0]
    for key in ("adoption_evidence_sha256", "pc_parity_evidence_sha256",
                "device_parity_evidence_sha256", "calibration_evidence_sha256"):
        if not isinstance(entry.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", entry[key]):
            raise ValueError("MODEL_BUNDLE_EVIDENCE_MISSING")
    if entry.get("distribution_review") not in ("private-user-import-approved", "public-approved"):
        raise ValueError("MODEL_DISTRIBUTION_NOT_REVIEWED")
    selection = selection() if callable(selection) else selection
    bundle = ModelBundle.model_validate(strict_json(content))
    require_daily_close_label(bundle.label_definition)
    if (entry.get("bundle_id") != bundle.bundle_id
            or entry["adoption_evidence_sha256"] != content_id(
                bundle.adoption_review.model_dump(mode="json"))
            or entry["calibration_evidence_sha256"] != bundle.calibration.source_evidence_sha256
            or any(getattr(bundle, key) != selection[key]
                   for key in ("feature_selection_id", "feature_manifest_hash"))):
        raise ValueError("Model bundle approval/selection lineage mismatch")
    for head in bundle.heads:
        head.decoded(selection)
    return bundle, entry


def encoded(bundle: ModelBundle | ResearchModelBundle) -> str:
    content = canonical_json(bundle.model_dump(mode="json"))
    if len(content.encode()) > MAX_BUNDLE_BYTES:
        raise ValueError("Model bundle size limit")
    return content


def parity(content: str, rows: dict, selection: dict) -> dict:
    """Read-only PC/device probe; never approve, import or publish a forecast."""
    if not isinstance(content, str) or len(content.encode()) > MAX_BUNDLE_BYTES:
        raise ValueError("Model bundle size limit")
    if (not isinstance(rows, dict) or set(rows) != {"5", "20"}
            or any(not isinstance(value, list) for value in rows.values())
            or sum(len(value) for value in rows.values()) > 1000
            or any(not isinstance(row, dict) for value in rows.values() for row in value)):
        raise ValueError("Parity input limit or shape")
    value = strict_json(content)
    bundle = (ResearchModelBundle.model_validate(value)
              if value.get("schema_version") == "stockai-mobile-research-bundle-v1"
              else ModelBundle.model_validate(value))
    if any(getattr(bundle, key) != selection[key]
           for key in ("feature_selection_id", "feature_manifest_hash")):
        raise ValueError("Frozen feature selection mismatch")
    return {"bundle_id": bundle.bundle_id, "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "research_only": True, "model_adopted": False, "persisted": False,
            "label_definition": bundle.label_definition,
            "label_definition_supported": bundle.label_definition == DAILY_NEXT_SESSION_CLOSE_LABEL,
            "heads": [{"horizon": head.horizon, "task": head.task, "model_id": head.model_id,
                       "sha256": head.sha256,
                       "values": predict(head.decoded(selection), rows[str(head.horizon)])}
                      for head in bundle.heads]}
