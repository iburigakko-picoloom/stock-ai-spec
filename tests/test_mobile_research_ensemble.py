"""Research composition only: fixture leaves are never real market or adoption evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from mobile.python import model_bundle
from mobile.python.model_bundle import approved, encoded, parity, reviewed
from mobile.python.research_ensemble import (
    EnsembleCalibration,
    ResearchEnsembleBundle,
    average_percentile,
    inference,
)

from stock_ai.ml.research_metrics import within_date_rank_standardize
from stock_ai.operations.daily import canonical_json, content_id
from tests.test_mobile_bundles import CUTOFF, SELECTION, fixture_bundle


def ensemble_bundle():
    old = fixture_bundle()
    components, outputs = [], []
    for head in old.heads[:2]:
        for task in ("regression", "ranking"):
            model = json.loads(head.content)
            model["task"] = task
            model["trees"] = [{"feature": 0, "threshold": 0., "operator": "<=",
                               "missing_left": True, "left": {"leaf": -.1},
                               "right": {"leaf": .2 if task == "regression" else -.2}}]
            content = canonical_json(model)
            components.append(dict(horizon=head.horizon, task=task, seed=17,
                                   model_id=f"h{head.horizon}-{task}", content=content,
                                   sha256=hashlib.sha256(content.encode()).hexdigest(),
                                   preprocessing_sha256=content_id(model["preprocessor"])))
        outputs += [dict(horizon=head.horizon, role="return", output_id=f"return-{head.horizon}",
                         recipe_version="daily-forward-crossfit-v1", unit="fractional_return",
                         components=[f"h{head.horizon}-regression"], weights=[1.],
                         weight_source="single", transform="identity"),
                    dict(horizon=head.horizon, role="ranking", output_id=f"rank-{head.horizon}",
                         recipe_version="selection-rank-space-v1", unit="rank_score",
                         components=[f"h{head.horizon}-regression", f"h{head.horizon}-ranking"],
                         weights=[.25, .75], weight_source="learned",
                         transform="within_date_average_percentile_v1",
                         rank_universe="decision_symbols", universe_rule_version="synthetic-v1",
                         universe_evidence_sha256="9" * 64)]
    return ResearchEnsembleBundle.create(
        created_at=old.created_at, trained_at=old.trained_at,
        training_data_cutoff=old.training_data_cutoff,
        feature_selection_id=old.feature_selection_id,
        feature_manifest_hash=old.feature_manifest_hash,
        selection_id=old.selection_id, data_snapshot_id="d" * 64, source_code_commit="e" * 40,
        source_evidence_sha256="f" * 64, evaluation_receipt_id="6" * 64,
        components=components, outputs=outputs,
    )


def fixture_rows():
    # No target_return or future price is present; the delisting-labelled symbol
    # remains in the prediction and ranking population.
    rows = [{"symbol": "9000", "f1": 1.}, {"symbol": "2000", "f1": -1.},
            {"symbol": "3000", "f1": 1.}]
    return {"5": copy.deepcopy(rows), "20": copy.deepcopy(rows)}


def universes(rows=None):
    rows = fixture_rows() if rows is None else rows
    return {h: {"decision_symbols": [r["symbol"] for r in values]} for h, values in rows.items()}


def pin(bundle):
    return dict(sha256=hashlib.sha256(encoded(bundle).encode()).hexdigest(),
                bundle_id=bundle.bundle_id, source_evidence_sha256=bundle.source_evidence_sha256,
                pc_parity_evidence_sha256="2" * 64, device_parity_evidence_sha256="3" * 64,
                distribution_review="private-research-import-approved", use="ensemble-research")


@pytest.mark.parametrize("values", [[1., 1., 3., -2.], [1.], [], [0., 0., 0.], [2., -2., 1.]])
def test_percentiles_match_existing_pc_formula_including_ties(values):
    expected = within_date_rank_standardize(
        pd.Series(values, dtype=float), pd.Series(["2025-01-10"] * len(values), dtype=str)
    )
    np.testing.assert_array_equal(average_percentile(values), expected)


def test_composition_matches_pc_and_keeps_unlabelled_predictions_in_rank_population():
    bundle, rows = ensemble_bundle(), fixture_rows()
    result = inference(bundle, rows, SELECTION, rank_universes=universes(rows))
    assert result["symbols"] == {"5": ["2000", "3000", "9000"],
                                  "20": ["2000", "3000", "9000"]}
    raw = {c["model_id"]: dict(c["values"]) for c in result["components"]}
    for output in result["outputs"]:
        horizon = output["horizon"]
        names = result["symbols"][str(horizon)]
        returns = [raw[f"h{horizon}-regression"][name] for name in names]
        ranks = [raw[f"h{horizon}-ranking"][name] for name in names]
        expected = (returns if output["role"] == "return" else
                    .25 * np.array(average_percentile(returns))
                    + .75 * np.array(average_percentile(ranks)))
        np.testing.assert_array_equal([v for _, v in output["values"]], expected)
        assert "9000" in dict(output["values"])
    assert bundle.calibration is None and bundle.adoption_review is None
    assert not result["model_adopted"] and not result["persisted"]
    assert bundle.large_loss_threshold is None and bundle.downside_quantile_alpha is None


def test_input_order_and_json_roundtrip_do_not_change_component_or_composed_outputs():
    bundle, rows = ensemble_bundle(), fixture_rows()
    reference = parity(encoded(bundle), rows, SELECTION, rank_universes=universes())
    restored = ResearchEnsembleBundle.model_validate_json(encoded(bundle))
    reversed_rows = {h: list(reversed(v)) for h, v in rows.items()}
    assert parity(encoded(restored), reversed_rows, SELECTION,
                  rank_universes=universes()) == reference
    # A subset would change all percentile values and is refused as a partial
    # batch rather than quietly ranked in isolation.
    with pytest.raises(ValueError, match="RANK_UNIVERSE"):
        inference(bundle, {h: v[:2] for h, v in rows.items()}, SELECTION,
                  rank_universes=universes())


@pytest.mark.parametrize("source,weights", [("equal", [.5, .5]), ("learned", [.25, .75])])
def test_return_ensembles_combine_fractional_returns_without_rank_conversion(source, weights):
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    for component in data["components"]:
        if component["task"] == "ranking":
            model = json.loads(component["content"])
            model["task"] = component["task"] = "regression"
            component["content"] = canonical_json(model)
            component["sha256"] = hashlib.sha256(component["content"].encode()).hexdigest()
    for output in data["outputs"]:
        if output["role"] == "return":
            output["components"] = [f"h{output['horizon']}-regression",
                                    f"h{output['horizon']}-ranking"]
            output["weights"], output["weight_source"] = weights, source
    result = inference(ResearchEnsembleBundle.create(**data), fixture_rows(), SELECTION,
                       rank_universes=universes())
    raw = {c["model_id"]: [v for _, v in c["values"]] for c in result["components"]}
    for output in result["outputs"]:
        if output["role"] == "return":
            horizon = output["horizon"]
            expected = [weights[0] * a + weights[1] * b for a, b in zip(
                raw[f"h{horizon}-regression"], raw[f"h{horizon}-ranking"], strict=True)]
            assert [v for _, v in output["values"]] == expected
            assert output["rank_universe_sha256"] is None


@pytest.mark.parametrize("change", ["absent", "duplicate", "extra", "other_population"])
def test_rank_population_must_be_explicit_complete_and_unique(change):
    population = universes()
    if change == "absent":
        population = None
    elif change == "duplicate":
        population["5"]["decision_symbols"].append("9000")
    elif change == "extra":
        population["5"]["decision_symbols"].append("8000")
    else:
        population["5"] = {"all_market_symbols": population["5"]["decision_symbols"]}
    with pytest.raises(ValueError, match="RANK_UNIVERSE"):
        inference(ensemble_bundle(), fixture_rows(), SELECTION, rank_universes=population)


def test_complete_market_population_is_not_relabelled_topix_population():
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    for output in data["outputs"]:
        if output["role"] == "ranking":
            output["rank_universe"] = "all_market_symbols"
    bundle = ResearchEnsembleBundle.create(**data)
    with pytest.raises(ValueError, match="RANK_UNIVERSE"):
        inference(bundle, fixture_rows(), SELECTION, rank_universes=universes())
    market = {h: {"all_market_symbols": p["decision_symbols"]} for h, p in universes().items()}
    assert inference(bundle, fixture_rows(), SELECTION, rank_universes=market)["outputs"]


@pytest.mark.parametrize("change", ["negative", "sum", "equal", "missing", "duplicate",
                                  "units", "rank_as_return", "horizon", "preprocess", "content"])
def test_invalid_recipes_and_changed_component_content_are_rejected(change):
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    output = data["outputs"][1]
    if change == "negative":
        output["weights"] = [-.1, 1.1]
    elif change == "sum":
        output["weights"] = [.2, .7]
    elif change == "equal":
        output["weight_source"] = "equal"
    elif change == "missing":
        output["components"] = ["missing", "h5-ranking"]
    elif change == "duplicate":
        output["components"] = ["h5-ranking", "h5-ranking"]
    elif change == "units":
        output["unit"] = "fractional_return"
    elif change == "rank_as_return":
        data["outputs"] = [o for o in data["outputs"] if o["role"] == "ranking"]
        data["outputs"][0]["role"] = "return"
        data["outputs"][0]["unit"] = "fractional_return"
    elif change == "horizon":
        output["components"] = ["h20-regression", "h20-ranking"]
    elif change == "preprocess":
        data["components"][0]["preprocessing_sha256"] = "0" * 64
    else:
        data["components"][0]["content"] += " "
    with pytest.raises(ValueError):
        bundle = ResearchEnsembleBundle.create(**data)
        inference(bundle, fixture_rows(), SELECTION, rank_universes=universes())


@pytest.mark.parametrize("key", ["sha256", "source_evidence_sha256", "pc_parity_evidence_sha256",
                               "device_parity_evidence_sha256", "distribution_review", "use"])
def test_import_requires_research_policy_pin_and_all_evidence(key):
    bundle = ensemble_bundle()
    entry = pin(bundle)
    assert reviewed(encoded(bundle), {"research_bundles": [entry]}, SELECTION)[0] == bundle
    entry[key] = None
    with pytest.raises(ValueError):
        reviewed(encoded(bundle), {"research_bundles": [entry]}, SELECTION)


def test_research_composition_cannot_pass_normal_approved_bundle_import():
    bundle = ensemble_bundle()
    entry = {**pin(bundle), "adoption_evidence_sha256": "1" * 64,
             "calibration_evidence_sha256": "2" * 64,
             "distribution_review": "private-user-import-approved"}
    with pytest.raises(ValueError):
        approved(encoded(bundle), {"approved_bundles": [entry]}, SELECTION)


def test_altered_bundle_identity_or_feature_snapshot_and_late_model_are_rejected():
    bundle = ensemble_bundle()
    data = bundle.model_dump(mode="json")
    data["selection_id"] = "0" * 64
    with pytest.raises(ValueError, match="identity"):
        ResearchEnsembleBundle.model_validate(data)
    different_selection = {**SELECTION, "feature_selection_id": "0" * 64}
    with pytest.raises(ValueError, match="selection"):
        parity(encoded(bundle), fixture_rows(), different_selection, rank_universes=universes())
    bundle.at(CUTOFF)
    with pytest.raises(ValueError, match="unavailable"):
        bundle.at(bundle.created_at - timedelta(seconds=1))


def test_duplicate_symbols_cannot_be_merged_and_missing_features_use_declared_preprocessing():
    rows = fixture_rows()
    rows["5"].append(copy.deepcopy(rows["5"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        inference(ensemble_bundle(), rows, SELECTION, rank_universes=universes())
    rows = fixture_rows()
    rows["5"][0].pop("f1")
    result = inference(ensemble_bundle(), rows, SELECTION, rank_universes=universes())
    assert len(result["components"][0]["values"]) == 3


def test_aggregate_encoding_size_guard_applies_before_import_and_parity(monkeypatch):
    bundle = ensemble_bundle()
    content = encoded(bundle)
    entry = pin(bundle)
    monkeypatch.setattr(model_bundle, "MAX_BUNDLE_BYTES", len(content.encode()) - 1)
    with pytest.raises(ValueError, match="size limit"):
        encoded(bundle)
    with pytest.raises(ValueError, match="size limit"):
        reviewed(content, {"research_bundles": [entry]}, SELECTION)
    with pytest.raises(ValueError, match="size limit"):
        parity(content, fixture_rows(), SELECTION, rank_universes=universes())


def test_optional_calibration_uses_saved_parameters_and_rejects_unreceived_labels():
    data = dict(source_evidence_sha256="1" * 64,
                latest_label_available_at="2026-02-01T00:00:00Z", fitted_at="2026-02-01T01:00:00Z")
    affine = EnsembleCalibration(method="affine_rank_to_return", slope=.2, intercept=.01, **data)
    assert affine.apply(.5) == pytest.approx(.11)
    isotonic = EnsembleCalibration(method="isotonic_probability", x=(.1, .5), y=(.2, .6), **data)
    assert isotonic.apply(.3) == pytest.approx(.4)
    assert isotonic.apply(-.1) == .2 and isotonic.apply(2.) == .6
    offset = EnsembleCalibration(method="quantile_offset", offset=-.02, **data)
    assert offset.apply(-.1) == pytest.approx(-.12)
    with pytest.raises(ValueError, match="unreceived"):
        EnsembleCalibration(method="quantile_offset", offset=-.02,
                            **{**data, "latest_label_available_at": "2026-02-02T00:00:00Z"})


def test_saved_rank_to_return_calibration_is_applied_after_composition_only():
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    recipe = data["outputs"][0]
    rank_recipe = data["outputs"][1]
    recipe.update({key: rank_recipe[key] for key in (
        "components", "weights", "weight_source", "transform", "rank_universe",
        "universe_rule_version", "universe_evidence_sha256",
    )})
    recipe["calibration"] = dict(
        method="affine_rank_to_return", slope=.2, intercept=.01,
        source_evidence_sha256="1" * 64,
        latest_label_available_at="2026-02-01T00:00:00Z", fitted_at="2026-02-01T01:00:00Z",
    )
    bundle = ResearchEnsembleBundle.create(**data)
    result = inference(bundle, fixture_rows(), SELECTION, rank_universes=universes())
    expected = [.01 + .2 * v for _, v in result["outputs"][1]["values"]]
    assert [v for _, v in result["outputs"][0]["values"]] == expected
    recipe["calibration"]["fitted_at"] = "2026-02-04T01:00:00Z"
    with pytest.raises(ValueError, match="unavailable"):
        ResearchEnsembleBundle.create(**data)


def test_only_explicit_risk_heads_and_matching_definitions_are_available():
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    data["components"] = list(data["components"])
    data["outputs"] = list(data["outputs"])
    for head in fixture_bundle().heads[2:]:
        model = json.loads(head.content)
        data["components"].append(dict(
            horizon=head.horizon, task=head.task, seed=17, model_id=head.model_id,
            content=head.content, sha256=head.sha256,
            preprocessing_sha256=content_id(model["preprocessor"]),
        ))
        data["outputs"].append(dict(
            horizon=head.horizon, role=head.task, output_id=f"risk-{head.task}",
            recipe_version="research-composition-v1", components=[head.model_id],
            weights=[1.], weight_source="single", transform="identity",
            unit="probability" if head.task == "large_loss" else "fractional_return",
        ))
    with pytest.raises(ValueError, match="Risk definitions"):
        ResearchEnsembleBundle.create(**data)
    data.update(large_loss_threshold=-.08, downside_quantile_alpha=.1)
    result = inference(ResearchEnsembleBundle.create(**data), fixture_rows(), SELECTION,
                       rank_universes=universes())
    risk = {o["role"]: dict(o["values"]) for o in result["outputs"][4:]}
    assert risk["quantile"] == dict.fromkeys(["2000", "3000", "9000"], -.08)
    assert all(0 < value < 1 for value in risk["large_loss"].values())


def test_risk_only_horizon_is_rejected_before_bundle_import():
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    data["components"] = [c for c in data["components"] if c["model_id"] == "h5-regression"]
    data["outputs"] = [o for o in data["outputs"]
                       if o["horizon"] == 5 and o["role"] == "return"]
    head = next(h for h in fixture_bundle().heads if h.task == "quantile")
    data["components"].append(dict(
        horizon=20, task="quantile", seed=17, model_id=head.model_id,
        content=head.content, sha256=head.sha256,
        preprocessing_sha256=content_id(json.loads(head.content)["preprocessor"]),
    ))
    data["outputs"].append(dict(
        horizon=20, role="quantile", output_id="risk-only-20d",
        recipe_version="research-composition-v1", components=[head.model_id], weights=[1.],
        weight_source="single", transform="identity", unit="fractional_return",
    ))
    data["downside_quantile_alpha"] = .1
    with pytest.raises(ValueError, match="daily priority"):
        ResearchEnsembleBundle.create(**data)
