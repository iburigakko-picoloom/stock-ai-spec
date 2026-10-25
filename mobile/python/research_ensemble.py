"""Private research compositions with explicit units and complete ranking populations.

No training, adoption or portfolio mutation occurs here. All scalar portable outputs
are produced before any cross-sectional transform, independent of input ordering.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    StrictFloat,
    StrictInt,
    ValidationInfo,
    model_serializer,
    model_validator,
)

from stock_ai.operations.daily import (
    DAILY_NEXT_SESSION_CLOSE_LABEL,
    DailyLabelDefinition,
    canonical_json,
    content_id,
)
from stock_ai.operations.manual_portfolio import Digest, InputModel, strict_json

from .portable_model import predict, validate

MAX_BUNDLE_BYTES = 64 * 1024 * 1024
SCHEMA: Final = "stockai-mobile-research-ensemble-v1"
Role = Literal["return", "ranking", "quantile", "large_loss"]
Population = Literal["decision_symbols", "all_market_symbols", "predictable_decision_symbols"]
PREDICTABILITY_RULE = "completed-history-before-label-v1"


class FeaturePredictability(InputModel):
    """Independent eligible/predictable domains; no outcome/execution mask is accepted."""

    schema_version: Literal["feature-predictability-v1"] = "feature-predictability-v1"
    rule_version: Literal["completed-history-before-label-v1"] = PREDICTABILITY_RULE
    as_of: AwareDatetime
    feature_selection_id: Digest
    feature_manifest_hash: Digest
    calculation_code_sha256: Digest
    source_snapshot_ids: Annotated[
        tuple[tuple[str, Digest], ...], Field(min_length=5, max_length=5)
    ]
    required_history_sessions: Annotated[StrictInt, Field(gt=0)]
    eligible_symbols: tuple[str, ...]
    eligible_sha256: Digest
    completed_sessions: tuple[tuple[str, Annotated[StrictInt, Field(ge=0)]], ...]
    predictable_symbols: tuple[str, ...]
    predictable_sha256: Digest
    abstentions: tuple[tuple[str, Literal["INSUFFICIENT_COMPLETED_HISTORY"]], ...]

    @model_validator(mode="after")
    def complete_independent_population(self) -> Self:
        eligible = self.eligible_symbols
        if (not eligible or eligible != tuple(sorted(set(eligible))) or any(not s for s in eligible)
                or tuple(s for s, _ in self.completed_sessions) != eligible
                or len(dict(self.source_snapshot_ids)) != len(self.source_snapshot_ids)):
            raise ValueError("Predictability requires the whole independent eligible population")
        predictable = tuple(s for s, n in self.completed_sessions
                            if n >= self.required_history_sessions)
        abstentions = tuple((s, "INSUFFICIENT_COMPLETED_HISTORY")
                            for s, n in self.completed_sessions
                            if n < self.required_history_sessions)
        if (self.predictable_symbols != predictable or self.abstentions != abstentions
                or self.eligible_sha256 != content_id(list(eligible))
                or self.predictable_sha256 != content_id(list(predictable))):
            raise ValueError("Predictability counts, abstentions or population hash changed")
        return self


class EnsembleComponent(InputModel):
    horizon: Literal[5, 20]
    task: Literal["regression", "ranking", "quantile", "large_loss"]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]
    seed: Annotated[StrictInt, Field(ge=0)]
    sha256: Digest
    preprocessing_sha256: Digest
    content: Annotated[str, Field(min_length=1, max_length=MAX_BUNDLE_BYTES)]

    def decoded(self, selection: dict) -> dict:
        if hashlib.sha256(self.content.encode()).hexdigest() != self.sha256:
            raise ValueError("Ensemble component content changed")
        value = strict_json(self.content)
        validate(value)
        if value["task"] != self.task:
            raise ValueError("Ensemble component task mismatch")
        if content_id(value["preprocessor"]) != self.preprocessing_sha256:
            raise ValueError("Ensemble component preprocessing changed")
        names = next(x["feature_names"] for x in selection["horizons"]
                     if x["horizon"] == self.horizon)
        if not set(value["preprocessor"]["retained"]) <= set(names):
            raise ValueError("Ensemble component features differ from selection")
        return value


class EnsembleCalibration(InputModel):
    method: Literal["affine_rank_to_return", "isotonic_probability", "quantile_offset"]
    source_evidence_sha256: Digest
    latest_label_available_at: AwareDatetime
    fitted_at: AwareDatetime
    slope: StrictFloat | None = None
    intercept: StrictFloat | None = None
    x: tuple[StrictFloat, ...] | None = None
    y: tuple[StrictFloat, ...] | None = None
    offset: StrictFloat | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.latest_label_available_at > self.fitted_at:
            raise ValueError("Calibration used unreceived labels")
        supplied = {key for key in ("slope", "intercept", "x", "y", "offset")
                    if getattr(self, key) is not None}
        required = {"affine_rank_to_return": {"slope", "intercept"},
                    "isotonic_probability": {"x", "y"},
                    "quantile_offset": {"offset"}}[self.method]
        if supplied != required:
            raise ValueError("Calibration parameters differ from method")
        if self.method == "affine_rank_to_return" and self.slope is not None and self.slope < 0:
            raise ValueError("Rank to return slope must be nonnegative")
        if self.method == "isotonic_probability":
            assert self.x is not None and self.y is not None
            if (not self.x or len(self.x) != len(self.y)
                    or any(a >= b for a, b in zip(self.x, self.x[1:], strict=False))
                    or any(a > b for a, b in zip(self.y, self.y[1:], strict=False))
                    or any(not 0 <= v <= 1 for v in (*self.x, *self.y))):
                raise ValueError("Invalid isotonic calibration")
        return self

    def apply(self, value: float) -> float:
        if self.method == "affine_rank_to_return":
            assert self.slope is not None and self.intercept is not None
            return self.intercept + self.slope * value
        if self.method == "quantile_offset":
            assert self.offset is not None
            return value + self.offset
        assert self.x is not None and self.y is not None
        if value <= self.x[0]:
            return self.y[0]
        for i in range(1, len(self.x)):
            if value <= self.x[i]:
                width = self.x[i] - self.x[i - 1]
                return self.y[i - 1] + (self.y[i] - self.y[i - 1]) * (
                    (value - self.x[i - 1]) / width
                )
        return self.y[-1]


class EnsembleOutput(InputModel):
    horizon: Literal[5, 20]
    role: Role
    output_id: Annotated[str, Field(min_length=1, max_length=200)]
    recipe_version: Literal[
        "daily-forward-crossfit-v1", "selection-rank-space-v1", "research-composition-v1"
    ]
    components: Annotated[tuple[str, ...], Field(min_length=1, max_length=72)]
    weights: Annotated[tuple[StrictFloat, ...], Field(min_length=1, max_length=72)]
    weight_source: Literal["single", "equal", "learned"]
    transform: Literal["identity", "within_date_average_percentile_v1"]
    unit: Literal["fractional_return", "rank_score", "probability"]
    rank_universe: Population | None = None
    universe_rule_version: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    universe_evidence_sha256: Digest | None = None
    predictability_rule_version: Literal["completed-history-before-label-v1"] | None = None
    predictability_evidence_sha256: Digest | None = None
    calibration: EnsembleCalibration | None = None

    @model_serializer(mode="wrap")
    def legacy_population_identity(self, handler):
        value = handler(self)
        for name in ("predictability_rule_version", "predictability_evidence_sha256"):
            if getattr(self, name) is None:
                value.pop(name, None)
        return value

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (len(self.components) != len(set(self.components))
                or len(self.components) != len(self.weights)
                or any(w < 0 for w in self.weights) or abs(sum(self.weights) - 1) > 1e-10):
            raise ValueError("Ensemble weights must be an aligned nonnegative simplex")
        if self.weight_source == "single" and (len(self.weights) != 1 or self.weights != (1.,)):
            raise ValueError("Single component requires weight one")
        if self.weight_source == "equal" and any(
            abs(w - 1 / len(self.weights)) > 1e-12 for w in self.weights
        ):
            raise ValueError("Equal weights changed")
        ranked = self.transform != "identity"
        predictable = self.rank_universe == "predictable_decision_symbols"
        if (predictable != (self.predictability_rule_version is not None
                            and self.predictability_evidence_sha256 is not None)
                or (not predictable and any(x is not None for x in (
                    self.predictability_rule_version, self.predictability_evidence_sha256)))):
            raise ValueError("Predictable ranks require a separately pinned rule/evidence")
        if self.recipe_version == "selection-rank-space-v1" and not ranked:
            raise ValueError("Selection rank-space recipe requires percentile transforms")
        if ranked != all(x is not None for x in (
            self.rank_universe, self.universe_rule_version, self.universe_evidence_sha256
        )) or (not ranked and any(x is not None for x in (
            self.rank_universe, self.universe_rule_version, self.universe_evidence_sha256
        ))):
            raise ValueError("Ranking requires an explicit complete population contract")
        calibration = self.calibration
        if calibration is not None:
            expected = {"return": "affine_rank_to_return", "large_loss": "isotonic_probability",
                        "quantile": "quantile_offset"}.get(self.role)
            if calibration.method != expected or (self.role == "return" and not ranked):
                raise ValueError("Calibration does not match output role/transform")
        if self.role == "return" and ranked and calibration is None:
            raise ValueError("Rank scores are not uncalibrated expected returns")
        if self.role in ("quantile", "large_loss") and ranked:
            raise ValueError("Risk outputs cannot use ranking transforms")
        if self.role == "ranking" and len(self.components) > 1 and not ranked:
            raise ValueError("Rank ensembles require explicit percentile normalization")
        if self.unit != {"return": "fractional_return", "ranking": "rank_score",
                         "quantile": "fractional_return", "large_loss": "probability"}[self.role]:
            raise ValueError("Ensemble output units differ from role")
        return self


class ResearchEnsembleBundle(InputModel):
    schema_version: Literal["stockai-mobile-research-ensemble-v1"] = SCHEMA
    bundle_id: Digest
    created_at: AwareDatetime
    trained_at: AwareDatetime
    training_data_cutoff: AwareDatetime
    feature_selection_id: Digest
    feature_manifest_hash: Digest
    selection_id: Digest
    data_snapshot_id: Digest
    source_code_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    source_evidence_sha256: Digest
    evaluation_receipt_id: Digest
    use: Literal["ensemble-research"] = "ensemble-research"
    adoption_review: None = None
    calibration: None = None
    label_definition: DailyLabelDefinition = DAILY_NEXT_SESSION_CLOSE_LABEL
    price_semantics: Literal["daily_close_research_proxy"] = "daily_close_research_proxy"
    large_loss_threshold: Annotated[StrictFloat, Field(gt=-1, lt=0)] | None = None
    downside_quantile_alpha: Annotated[StrictFloat, Field(gt=0, lt=.5)] | None = None
    components: Annotated[tuple[EnsembleComponent, ...], Field(min_length=1, max_length=72)]
    outputs: Annotated[tuple[EnsembleOutput, ...], Field(min_length=2, max_length=8)]

    @model_validator(mode="after")
    def coherent(self, info: ValidationInfo) -> Self:
        if not self.training_data_cutoff <= self.trained_at <= self.created_at:
            raise ValueError("Research ensemble timestamps are out of order")
        if sum(len(c.content.encode()) for c in self.components) > MAX_BUNDLE_BYTES:
            raise ValueError("Model bundle size limit")
        components = {c.model_id: c for c in self.components}
        if len(components) != len(self.components):
            raise ValueError("Ensemble component IDs must be unique")
        roles = {(o.horizon, o.role) for o in self.outputs}
        if (len(roles) != len(self.outputs) or {o.horizon for o in self.outputs} != {5, 20}
                or len({o.output_id for o in self.outputs}) != len(self.outputs)):
            raise ValueError("Outputs require unique roles/IDs and both daily horizons")
        if any(not ({(horizon, "return"), (horizon, "ranking")} & roles)
               for horizon in (5, 20)):
            raise ValueError("Each horizon requires a daily priority return or ranking output")
        used: set[str] = set()
        for output in self.outputs:
            if not set(output.components) <= set(components):
                raise ValueError("Ensemble output references missing component")
            used.update(output.components)
            for name in output.components:
                component = components[name]
                allowed = {"return": {"regression"}, "ranking": {"regression", "ranking"},
                           "quantile": {"quantile"}, "large_loss": {"large_loss"}}[output.role]
                if output.role == "return" and output.transform != "identity":
                    allowed = {"regression", "ranking"}
                if component.horizon != output.horizon or component.task not in allowed:
                    raise ValueError("Component horizon/task differs from output recipe")
            if output.calibration is not None and output.calibration.fitted_at > self.created_at:
                raise ValueError("Calibration unavailable at bundle creation")
        if used != set(components):
            raise ValueError("Bundle contains unused components")
        predictable_pins = {(o.predictability_rule_version, o.predictability_evidence_sha256)
                            for o in self.outputs
                            if o.rank_universe == "predictable_decision_symbols"}
        if len(predictable_pins) > 1:
            raise ValueError("Daily predictable ranks require one frozen eligibility rule/evidence")
        if ((self.large_loss_threshold is not None) != any(r == "large_loss" for _, r in roles)
                or (self.downside_quantile_alpha is not None)
                != any(r == "quantile" for _, r in roles)):
            raise ValueError("Risk definitions must match provided risk outputs")
        if not (info.context or {}).get("creating") and self.bundle_id != content_id(
            self.model_dump(mode="json", exclude={"bundle_id"})
        ):
            raise ValueError("Research ensemble identity mismatch")
        return self

    @property
    def heads(self) -> tuple[EnsembleComponent, ...]:
        """Read-only inventory compatibility; output recipes remain separate."""
        return self.components

    def at(self, cutoff: datetime) -> None:
        if (cutoff.tzinfo is None or self.created_at > cutoff or self.training_data_cutoff >= cutoff
                or any(o.calibration is not None and
                       o.calibration.latest_label_available_at >= cutoff for o in self.outputs)):
            raise ValueError("Research ensemble unavailable at alpha cutoff")

    @classmethod
    def create(cls, **values) -> ResearchEnsembleBundle:
        value = cls.model_validate({**values, "bundle_id": "0" * 64}, context={"creating": True})
        data = value.model_dump(mode="json", exclude={"bundle_id"})
        result = cls.model_validate({**data, "bundle_id": content_id(data)})
        if len(canonical_json(result.model_dump(mode="json")).encode()) > MAX_BUNDLE_BYTES:
            raise ValueError("Model bundle size limit")
        return result


def average_percentile(values: list[float]) -> list[float]:
    """Exactly 2 * (average within-day percentile - .5), including tied values."""
    if any(not math.isfinite(v) for v in values):
        raise ValueError("Nonfinite ensemble component output")
    result = [0.] * len(values)
    order = sorted(range(len(values)), key=values.__getitem__)
    start = 0
    while start < len(order):
        stop = start + 1
        while stop < len(order) and values[order[stop]] == values[order[start]]:
            stop += 1
        value = (((start + 1 + stop) / 2) / len(order) - .5) * 2
        for i in order[start:stop]:
            result[i] = value
        start = stop
    return result


def inference(bundle: ResearchEnsembleBundle, rows: dict, selection: dict,
              *, rank_universes: dict | None = None, component_cache=None) -> dict:
    """Evaluate complete horizon populations; never normalize partial batches."""
    if any(getattr(bundle, k) != selection[k]
           for k in ("feature_selection_id", "feature_manifest_hash")):
        raise ValueError("Frozen feature selection mismatch")
    if (not isinstance(rows, dict) or set(rows) != {"5", "20"}
            or any(not isinstance(v, list) for v in rows.values())
            or sum(len(v) for v in rows.values()) > 10_000):
        raise ValueError("Ensemble input limit or shape")
    symbols, ordered_rows = {}, {}
    for horizon, values in rows.items():
        if any(not isinstance(row, dict) or not isinstance(row.get("symbol"), str)
               or not row["symbol"] for row in values):
            raise ValueError("Ensemble input requires explicit symbols")
        names = [row["symbol"] for row in values]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ensemble input symbol")
        ordered_rows[horizon] = sorted(values, key=lambda row: row["symbol"])
        symbols[horizon] = sorted(names)
    for recipe in bundle.outputs:
        if recipe.rank_universe != "predictable_decision_symbols":
            continue
        contracts = []
        for horizon in ("5", "20"):
            declared = (rank_universes or {}).get(horizon, {})
            proof = FeaturePredictability.model_validate(declared.get("predictability_proof"))
            if (proof.rule_version != recipe.predictability_rule_version
                    or declared.get("predictability_evidence_sha256")
                    != recipe.predictability_evidence_sha256
                    or proof.feature_selection_id != bundle.feature_selection_id
                    or proof.feature_manifest_hash != bundle.feature_manifest_hash
                    or list(proof.predictable_symbols) != symbols[horizon]
                    or declared.get("predictable_decision_symbols") != symbols[horizon]):
                raise ValueError("PREDICTABLE_RANK_CONTRACT_MISMATCH")
            for row in ordered_rows[horizon]:
                stamp = datetime.fromisoformat(
                    str(row.get("available_at", "")).replace("Z", "+00:00"))
                if stamp != proof.as_of:
                    raise ValueError("PREDICTABLE_FEATURE_TIME_MISMATCH")
            contracts.append(proof)
        if contracts[0] != contracts[1] or symbols["5"] != symbols["20"]:
            raise ValueError("PREDICTABLE_HORIZON_POPULATIONS_DIFFER")
    raw = {}
    for component in bundle.components:
        def evaluate(current=component):
            return predict(current.decoded(selection), ordered_rows[str(current.horizon)])
        raw[component.model_id] = (evaluate() if component_cache is None else
            component_cache(
                "model-" + content_id([component.sha256, component.horizon, component.model_id]),
                evaluate, units=1, phase="predicting"))
        if len(raw[component.model_id]) != len(symbols[str(component.horizon)]):
            raise ValueError("COMPONENT_POPULATION_INCOMPLETE")
    outputs = []
    for recipe in bundle.outputs:
        horizon = str(recipe.horizon)
        matrices = [raw[name] for name in recipe.components]
        population_hash = None
        if recipe.transform != "identity":
            declared = (rank_universes or {}).get(horizon, {}).get(recipe.rank_universe)
            if (not isinstance(declared, list)
                    or any(not isinstance(s, str) or not s for s in declared)
                    or len(declared) != len(set(declared)) or sorted(declared) != symbols[horizon]
                    or not declared):
                raise ValueError("RANK_UNIVERSE_INCOMPLETE_OR_MISMATCHED")
            population_hash = content_id(sorted(declared))
            matrices = [average_percentile(values) for values in matrices]
        combined = [sum(weight * values[i] for weight, values in
                        zip(recipe.weights, matrices, strict=True))
                    for i in range(len(symbols[horizon]))]
        if recipe.calibration is not None:
            combined = [recipe.calibration.apply(value) for value in combined]
        if any(not math.isfinite(v) or (recipe.role == "large_loss" and not 0 <= v <= 1)
               for v in combined):
            raise ValueError("Invalid composed prediction")
        outputs.append({"output_id": recipe.output_id, "horizon": recipe.horizon,
                        "role": recipe.role, "unit": recipe.unit,
                        "recipe_version": recipe.recipe_version,
                        "rank_universe": recipe.rank_universe,
                        "rank_universe_sha256": population_hash,
                        "values": list(zip(symbols[horizon], combined, strict=True)),
                        **({"predictability_rule_version": recipe.predictability_rule_version,
                            "predictability_evidence_sha256": recipe.predictability_evidence_sha256}
                           if recipe.rank_universe == "predictable_decision_symbols" else {})})
    return {"bundle_id": bundle.bundle_id, "research_only": True, "model_adopted": False,
            "persisted": False, "symbols": symbols,
            "components": [{"model_id": c.model_id, "sha256": c.sha256, "horizon": c.horizon,
                            "task": c.task, "values": list(zip(symbols[str(c.horizon)],
                                                               raw[c.model_id], strict=True))}
                           for c in bundle.components], "outputs": outputs}
