"""Small synthetic populations only; historical 250-session evaluation is not certified."""

import copy
import hashlib
import importlib
import inspect
import json
import zipfile
from datetime import timedelta

import pandas as pd
import pytest
from mobile.python import features as feature_module
from mobile.python import forecasts, models, research_ensemble
from mobile.python.model_bundle import encoded, parity
from mobile.python.research_ensemble import FeaturePredictability, ResearchEnsembleBundle

from stock_ai.ml.selection import FrozenCompositionOutput
from stock_ai.operations.daily import content_id
from tests.test_mobile_bundles import CUTOFF, SELECTION
from tests.test_mobile_decisions import NOW, SETUP
from tests.test_mobile_ensemble_forecasts import ready as old_ready
from tests.test_mobile_features import frozen_selection
from tests.test_mobile_research_ensemble import ensemble_bundle, pin

EXTRA = ["641A", "642A", "646A", "8303"]


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    device, store, path, selection, numerical, policy = old_ready.__wrapped__(tmp_path, monkeypatch)
    original = forecasts.latest(path)
    for symbol in EXTRA:
        selection["new_candidates"].append({"symbol": symbol, "reason": "SYNTHETIC_TEST_ONLY"})
    selection["decision_symbols"] = sorted([*selection["decision_symbols"], *EXTRA])
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    for output in data["outputs"]:
        if output["transform"] != "identity":
            output.update(
                rank_universe="predictable_decision_symbols",
                universe_rule_version=selection["policy"],
                predictability_rule_version=research_ensemble.PREDICTABILITY_RULE,
                predictability_evidence_sha256="8" * 64,
            )
    bundle = ResearchEnsembleBundle.create(**data)
    policy["research_bundles"] = [pin(bundle)]
    models.import_bundle(path, encoded(bundle), SETUP + timedelta(minutes=1))
    state = {
        "features": copy.deepcopy(numerical),
        "counts": {s: 249 if s in EXTRA else 250 for s in selection["decision_symbols"]},
        "selection": selection,
        "tamper": None,
    }

    def calculate(*args, include_predictability=False):
        result = copy.deepcopy(state["features"])
        result["required_history_sessions"] = 250
        if include_predictability:
            result["predictability_proof"] = feature_module.history_predictability(
                {
                    "as_of": CUTOFF.isoformat(),
                    "source_snapshot_ids": original["data_proof"]["source_snapshot_ids"],
                },
                SELECTION,
                pd.Series(state["counts"]),
                selection["decision_symbols"],
                250,
            )
            if state["tamper"]:
                state["tamper"](result["predictability_proof"])
        return result

    monkeypatch.setattr(forecasts, "calculate", calculate)
    return device, store, path, bundle, state


def checked(run):
    value = copy.deepcopy(run)
    phase = value.pop("phase")
    return forecasts._checked(
        (value["run_id"], value["scope_hash"], json.dumps(value), content_id(value), phase)
    )


def test_four_known_feature_abstentions_keep_eligible_and_predictable_separate(ready):
    _, store, path, bundle, _ = ready
    before = store.latest_portfolio()
    run = forecasts.generate(path, store, NOW)
    assert run["phase"] == "published" and len(run["snapshot"]["predictions"]) == 3
    assert len(run["scope"]["universe"]["decision_symbols"]) == 7
    proof = run["data_proof"]["feature_predictability"]
    assert len(proof["eligible_symbols"]) == 7 and len(proof["predictable_symbols"]) == 3
    assert proof["abstentions"] == [[s, "INSUFFICIENT_COMPLETED_HISTORY"] for s in EXTRA]
    assert [x["symbol"] for x in run["excluded_candidates"]] == EXTRA
    assert checked(run) == run and store.latest_portfolio() == before
    ranks = [r for r in run["outputs"] if r["role"] == "ranking"]
    assert all(r["rank_universe"] == "predictable_decision_symbols" for r in ranks)
    rows = {h: list(values) for h, values in ready[-1]["features"]["features"].items()}
    reference = parity(
        encoded(bundle),
        rows,
        SELECTION,
        rank_universes={
            h: {
                "predictable_decision_symbols": proof["predictable_symbols"],
                "predictability_proof": proof,
                "predictability_evidence_sha256": "8" * 64,
            }
            for h in ("5", "20")
        },
    )
    assert json.loads(json.dumps(reference["outputs"])) == run["outputs"]


def test_250th_completed_session_changes_population_snapshot_and_cache(ready, monkeypatch):
    _, store, path, _, state = ready
    first = forecasts.generate(path, store, NOW)
    state["counts"][EXTRA[0]] = 250
    for rows in state["features"]["features"].values():
        rows.append({"symbol": EXTRA[0], "available_at": CUTOFF.isoformat(), "f1": 0.0})
    second = forecasts.generate(path, store, NOW + timedelta(minutes=1))
    assert second["phase"] == "published" and second["run_id"] != first["run_id"]
    assert second["snapshot"]["snapshot_id"] != first["snapshot"]["snapshot_id"]
    assert len(second["snapshot"]["predictions"]) == 4
    monkeypatch.setattr(
        forecasts, "inference", lambda *a, **k: pytest.fail("Same cache re-inferred")
    )
    assert forecasts.generate(path, store, NOW + timedelta(minutes=2)) == second


@pytest.mark.parametrize(
    "change", ["one_horizon", "both_horizons", "false_abstention", "stale_snapshot", "code_pin"]
)
def test_unexplained_loss_or_wrong_proof_blocks_before_component_execution(
    ready, monkeypatch, change
):
    _, store, path, _, state = ready
    if change in ("one_horizon", "both_horizons"):
        for h in ["5"] if change == "one_horizon" else ["5", "20"]:
            state["features"]["features"][h] = [
                row for row in state["features"]["features"][h] if row["symbol"] != "1000"
            ]
    elif change == "false_abstention":
        state["tamper"] = lambda p: p["completed_sessions"][0].__setitem__(1, 249)
    elif change == "stale_snapshot":
        state["tamper"] = lambda p: p["source_snapshot_ids"][0].__setitem__(1, "0" * 64)
    else:
        state["tamper"] = lambda p: p.__setitem__("calculation_code_sha256", "0" * 64)
    monkeypatch.setattr(
        forecasts, "inference", lambda *a, **k: pytest.fail("Bad population inferred")
    )
    run = forecasts.generate(path, store, NOW)
    assert run["outcome"] == "blocked" and run["snapshot"] is None
    assert run["blocking_reasons"][0].startswith("ENSEMBLE_")


def test_missing_held_history_is_still_a_hard_block(ready, monkeypatch):
    _, store, path, _, state = ready
    state["counts"]["7203"] = 249
    for h in ("5", "20"):
        state["features"]["features"][h] = [
            row for row in state["features"]["features"][h] if row["symbol"] != "7203"
        ]
    monkeypatch.setattr(
        forecasts, "inference", lambda *a, **k: pytest.fail("Missing holding inferred")
    )
    run = forecasts.generate(path, store, NOW)
    assert run["blocking_reasons"] == ["HELD_FORECAST_MISSING:7203"]


def test_unknown_future_labels_stay_in_complete_predictable_rank_population(ready):
    _, store, path, _, state = ready
    for rows in state["features"]["features"].values():
        rows[0].update(target_return=None, label_evaluable=False, future_exit_price=None)
    run = forecasts.generate(path, store, NOW)
    assert run["phase"] == "published"
    assert "1000" in run["data_proof"]["feature_predictability"]["predictable_symbols"]
    assert all("1000" in dict(output["values"]) for output in run["outputs"])


def test_component_loss_is_not_repaired_by_intersecting_predictions(ready, monkeypatch):
    _, store, path, _, _ = ready
    original = research_ensemble.predict
    monkeypatch.setattr(research_ensemble, "predict", lambda *a, **k: original(*a, **k)[:-1])
    run = forecasts.generate(path, store, NOW)
    assert run["blocking_reasons"] == ["ENSEMBLE_COMPONENT_PREDICTION_INVALID"]
    assert run["snapshot"] is None and run["component_outputs"] == []


@pytest.mark.parametrize(
    "key",
    [
        "predictable_sha256",
        "eligible_sha256",
        "source_snapshot_ids",
        "completed_sessions",
        "abstentions",
    ],
)
def test_saved_population_proof_is_revalidated(ready, key):
    _, store, path, _, _ = ready
    run = forecasts.generate(path, store, NOW)
    forged = copy.deepcopy(run)
    proof = forged["data_proof"]["feature_predictability"]
    if key.endswith("sha256"):
        proof[key] = "0" * 64
    elif key == "source_snapshot_ids":
        proof[key][0][1] = "0" * 64
    else:
        proof[key] = proof[key][:-1]
    with pytest.raises((ValueError, KeyError)):
        forecasts._check_ensemble_outputs(
            forged, {p["symbol"] for p in run["snapshot"]["predictions"]}
        )


def test_old_bundle_identity_is_byte_identical_and_new_pin_is_mandatory(monkeypatch):
    from scripts.generate_research_ensemble_golden import generate

    # The frozen synthetic golden records this source commit in its bundle
    # identity. Both the pre-change 531d2b1 serializer and the new serializer
    # reproduce these same bytes from that identical input; do not let the
    # test runner's moving HEAD/GITHUB_SHA alter the reference metadata.
    monkeypatch.setenv("GITHUB_SHA", "232b4d3919eafa5f3f5f3d783534a896dafc3aa6")
    legacy_hashes = {
        "return_and_rank": "cb96524f830416fe55f65826410f2a4f2b3508e6208dd3a1ea83cf8d646a663a",
        "rank_only": "a291dbeb11dc6431a0034055cb139656f33661ba0857fb34a06093350ace43f0",
    }
    for variant in generate()["variants"]:
        assert (
            hashlib.sha256(variant["content"].encode()).hexdigest()
            == legacy_hashes[variant["name"]]
        )
    current = ensemble_bundle()
    assert "predictability_rule_version" not in current.outputs[1].model_dump()
    data = current.model_dump(exclude={"bundle_id"})
    data["outputs"][1]["rank_universe"] = "predictable_decision_symbols"
    with pytest.raises(ValueError, match="separately pinned"):
        ResearchEnsembleBundle.create(**data)


def test_legacy_frozen_output_serialization_and_hash_do_not_gain_null_fields():
    output = ensemble_bundle().outputs[1].model_dump(mode="json")
    output.update(
        source_evidence_sha256="9" * 64,
        latest_weight_label_available_at=CUTOFF.isoformat(),
        weights_fitted_at=CUTOFF.isoformat(),
        received_at=CUTOFF.isoformat(),
    )
    recipe = FrozenCompositionOutput.model_validate(output)
    assert recipe.model_dump(mode="json") == output
    assert content_id(recipe.model_dump(mode="json")) == content_id(output)
    output.update(
        rank_universe="predictable_decision_symbols",
        predictability_rule_version=research_ensemble.PREDICTABILITY_RULE,
        predictability_evidence_sha256="8" * 64,
    )
    assert FrozenCompositionOutput.model_validate(output).model_dump(mode="json") == output


def test_code_identity_works_with_real_zipimport_without_a_physical_module_path(
    tmp_path, monkeypatch
):
    text = "import hashlib\n" + inspect.getsource(feature_module.predictability_code_sha256)
    path = tmp_path / "synthetic-code-pin.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synthetic_code_pin/__init__.py", "")
        archive.writestr("synthetic_code_pin/module.py", text)
    monkeypatch.syspath_prepend(str(path))
    module = importlib.import_module("synthetic_code_pin.module")
    assert module.predictability_code_sha256() == hashlib.sha256(text.encode()).hexdigest()


def test_real_feature_engine_proof_uses_existing_completed_session_mask_and_no_values_change():
    from stock_ai.fixtures import market_fixture

    daily, market, sector, financials = market_fixture(270)
    symbols = sorted(daily.symbol.unique())
    first = symbols[0]
    rows = daily.index[daily.symbol == first]
    # Keep exactly 249 historic completed sessions for one member.
    daily = daily.drop(rows[: len(rows) - 249])
    payload = dict(
        daily=daily,
        market=market,
        sector=sector,
        financials=financials,
        decision_symbols=symbols,
        as_of=daily.available_at.max().isoformat(),
        source_snapshot_ids=[(str(i), str(i) * 64) for i in range(1, 6)],
    )
    selection = frozen_selection()
    old = feature_module.calculate(payload, selection)
    new = feature_module.calculate(payload, selection, include_predictability=True)
    proof = FeaturePredictability.model_validate(new.pop("predictability_proof"))
    assert new == old
    completed = daily.loc[
        (daily.available_at <= proof.as_of) & (daily.trading_date.dt.date < proof.as_of.date())
    ]
    expected = completed.groupby("symbol").trading_date.nunique().to_dict()
    assert dict(proof.completed_sessions) == expected
    assert proof.required_history_sessions == 250 and first not in proof.predictable_symbols
