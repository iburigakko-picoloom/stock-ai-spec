"""Full research composition path on isolated fixture state, no adoption or orders."""
import copy
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from mobile.pc.package_bundle import package
from mobile.python import decisions, forecasts, manual_chatgpt, models
from mobile.python.model_bundle import encoded
from mobile.python.research_ensemble import ResearchEnsembleBundle

from stock_ai.domain.models import ResearchEnsemblePrediction
from stock_ai.operations.api import create_app
from stock_ai.operations.daily import content_id
from stock_ai.operations.models import RankingRecord
from tests import test_mobile_decisions as decision_fixture
from tests.test_mobile_bundles import SELECTION
from tests.test_mobile_decisions import NOW, SETUP
from tests.test_mobile_manual_chatgpt import permission
from tests.test_mobile_research_ensemble import ensemble_bundle, pin


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    # Reuse the current personal/market fixture rather than changing freshness
    # timestamps or weakening the production decision guard.
    device, path, store, numerical, policy = decision_fixture.ready.__wrapped__(
        tmp_path, monkeypatch,
    )
    selection = copy.deepcopy(numerical["scope"]["universe"])
    features = copy.deepcopy(forecasts.calculate({}, SELECTION))
    monkeypatch.setattr(forecasts.universe, "select", lambda *a, **kw: copy.deepcopy(selection))
    monkeypatch.setattr(forecasts, "calculate", lambda *a: copy.deepcopy(features))
    return device, store, path, selection, features, policy


def install(ready, *, rank_only=False, population="decision_symbols"):
    device, store, path, selection, features, policy = ready
    data = ensemble_bundle().model_dump(exclude={"bundle_id"})
    if rank_only:
        data["outputs"] = [o for o in data["outputs"] if o["role"] == "ranking"]
    for recipe in data["outputs"]:
        if recipe["transform"] != "identity":
            recipe["universe_rule_version"] = selection["policy"]
            recipe["rank_universe"] = population
    bundle = ResearchEnsembleBundle.create(**data)
    policy["research_bundles"] = [pin(bundle)]
    models.import_bundle(path, encoded(bundle), SETUP + timedelta(minutes=1))
    for rows in features["features"].values():
        for row in rows:
            row["f1"] = 1. if row["symbol"] != "7203" else -1.
    return device, store, path, bundle, features


@pytest.mark.parametrize("rank_only", [False, True])
def test_composition_snapshot_consultation_and_restore(ready, monkeypatch, rank_only):
    device, store, path, _bundle, _ = install(ready, rank_only=rank_only)
    before = store.latest_portfolio()
    numerical = forecasts.generate(path, store, NOW)
    assert numerical["phase"] == "published" and numerical["outcome"] == "forecast"
    snapshot = store.latest_prediction_snapshot()
    assert all(isinstance(p, ResearchEnsemblePrediction) for p in snapshot.predictions)
    assert snapshot.schema_version == "daily-prediction-snapshot-v2"
    assert snapshot.mode == "research" and not snapshot.risk_available
    assert snapshot.holding_symbols == ("7203",)
    assert len(numerical["component_outputs"]) == 4
    if rank_only:
        assert all(p.expected_return_20d is None for p in snapshot.predictions)
    assert models.status(path, store)["ensemble_research"]
    assert not models.status(path, store)["risk_available"]
    decision = decisions.generate(path, store, NOW)
    assert decision["blocking_reasons"] == ["FORECAST_RISK_UNAVAILABLE"]
    exported = manual_chatgpt.export(path, store, permission(), NOW)
    package_value = json.loads(exported["prompt"].split("\n入力:\n")[1])
    assert all(row["ranking_20d"]["unit"] == "rank_score" for row in package_value["securities"])
    assert all(row["forecast_20d"]["unit"] == "fractional_return"
               for row in package_value["securities"])
    answer = dict(
        schema_version="chatgpt-target-shares-v1",
        input_snapshot_id=package_value["input_snapshot_id"], evidence_as_of=NOW.isoformat(),
        targets=[dict(symbol=row["symbol"], account=row["account"],
                      target_shares=row["current_shares"], reason="Synthetic hold", sources=[])
                 for row in package_value["required_targets"]],
        unknowns=["Synthetic research fixture"],
    )
    reviewed_answer = manual_chatgpt.import_answer(path, store, {
        "input_record_id": exported["input_record_id"], "answer_json": json.dumps(answer),
    }, NOW)
    assert not reviewed_answer["review"]["applied_to_ledger"]
    assert all(row["share_difference"] == 0 for row in reviewed_answer["review"]["lines"])
    assert store.latest_portfolio() == before
    with TestClient(create_app(store.path, clock=lambda: NOW),
                    base_url="http://localhost") as client:
        response = client.get("/api/v1/ranking?rankType=overall")
        assert response.status_code == 200, response.text
        ranking = response.json()
    assert [r["symbol"] for r in ranking] == ["7203", "1000", "1001"]
    assert all(r["total_universe"] == 3 and r["portfolio_action"] is None for r in ranking)
    saved = device.export_state()
    device.initialize(saved)
    restored = device._app.state.store
    assert restored.latest_prediction_snapshot() == snapshot
    assert restored.latest_portfolio() == before
    status = manual_chatgpt.status(path, restored, NOW)
    assert status["selected_input"] == exported["input_record_id"]
    monkeypatch.setattr(forecasts, "inference", lambda *a, **kw: pytest.fail("Cached run refitted"))
    assert forecasts.generate(path, restored, NOW + timedelta(minutes=1)) == numerical


def test_all_market_rank_is_not_silently_changed_to_topix(ready):
    _, store, path, _, _ = install(ready, population="all_market_symbols")
    result = forecasts.generate(path, store, NOW)
    assert result["outcome"] == "blocked"
    assert result["blocking_reasons"] == ["ENSEMBLE_REQUIRES_ALL_MARKET_FEATURES"]


def test_absent_features_are_saved_as_abstentions_instead_of_empty_ranking(ready):
    _, store, path, _, features = install(ready)
    for rows in features["features"].values():
        rows.clear()
    result = forecasts.generate(path, store, NOW)
    assert result["outcome"] == "blocked"
    assert result["blocking_reasons"] == ["HELD_FORECAST_MISSING:7203"]
    assert result["excluded_candidates"] == [
        {"symbol": symbol, "reason": "FEATURE_HISTORY_UNAVAILABLE"}
        for symbol in ("1000", "1001")]
    assert result["snapshot"] is None and result["component_outputs"] == []


@pytest.mark.parametrize("horizons", [(5,), (20,), (5, 20)])
def test_one_missing_candidate_does_not_redefine_the_frozen_rank_population(
    ready, monkeypatch, horizons,
):
    _, store, path, _, features = install(ready)
    before = store.latest_portfolio()
    for horizon in horizons:
        features["features"][str(horizon)] = [
            row for row in features["features"][str(horizon)] if row["symbol"] != "1000"
        ]
    monkeypatch.setattr(forecasts, "inference", lambda *a, **kw: pytest.fail("Partial rank run"))
    result = forecasts.generate(path, store, NOW)
    assert result["outcome"] == "blocked"
    assert result["blocking_reasons"] == ["ENSEMBLE_RANK_POPULATION_INCOMPLETE"]
    assert result["excluded_candidates"] == [
        {"symbol": "1000", "reason": "FEATURE_HISTORY_UNAVAILABLE"}]
    assert "1000" in result["scope"]["universe"]["decision_symbols"]
    assert result["snapshot"] is None and result["component_outputs"] == []
    assert store.latest_portfolio() == before


def test_saved_ensemble_rejects_a_smaller_self_declared_rank_population(ready):
    _, store, path, _, _ = install(ready)
    result = forecasts.generate(path, store, NOW)
    forged = copy.deepcopy(result)
    for component in forged["component_outputs"]:
        component["values"] = [v for v in component["values"] if v[0] != "1000"]
    with pytest.raises(ValueError, match="ranking population is incomplete"):
        forecasts._check_ensemble_outputs(forged, {"1001", "7203"})


def test_same_cutoff_old_rankings_do_not_hide_the_new_numerical_snapshot(ready):
    _, store, path, _, _ = install(ready)
    forecasts.generate(path, store, NOW)
    snapshot = store.latest_prediction_snapshot()
    old = RankingRecord(
        ranking_id="TEST_ONLY_OLD_RANK", as_of=snapshot.as_of, symbol="1000",
        company_name="TEST_ONLY", rank_type="overall", rank=1, total_universe=3,
        candidate_status="候補", model_bundle_version="TEST_ONLY_OTHER_MODEL",
        data_snapshot_id="TEST_ONLY_OTHER_SNAPSHOT",
    )
    store.append_rankings([old])
    with TestClient(create_app(store.path, clock=lambda: NOW),
                    base_url="http://localhost") as client:
        ranking = client.get("/api/v1/ranking?rankType=overall").json()
        assert [row["symbol"] for row in ranking] == ["7203", "1000", "1001"]
        assert all(row["model_bundle_version"] == snapshot.model_version for row in ranking)
        # The older numerical snapshot must not replace a later saved ranking.
        store.append_rankings([old.model_copy(update={
            "ranking_id": "TEST_ONLY_LATER_RANK", "as_of": old.as_of + timedelta(minutes=1),
        })])
        ranking = client.get("/api/v1/ranking?rankType=overall").json()
        assert [row["symbol"] for row in ranking] == ["1000"]


def test_saved_composition_rejects_self_consistent_rehashed_wrong_score(ready):
    _, store, path, _, _ = install(ready)
    result = forecasts.generate(path, store, NOW)
    forged = copy.deepcopy(result)
    forged["component_outputs"][0]["values"][0][1] += .1
    # Even rehashing receipt IDs must not turn wrong composed values into valid output.
    forged.pop("phase")
    forged["run_id"] = content_id({k: v for k, v in forged.items() if k != "run_id"})
    with pytest.raises(ValueError, match="composition changed"):
        forecasts._checked((forged["run_id"], forged["scope_hash"], json.dumps(forged),
                            content_id(forged), "published"))


def test_packaging_existing_components_does_not_create_approval():
    original = ensemble_bundle()
    metadata = original.model_dump(mode="json", exclude={"bundle_id", "components"})
    content, proposal = package(metadata, [c.model_dump(mode="json") for c in original.components],
                                SELECTION)
    assert content == encoded(original)
    assert proposal["use"] == "ensemble-research" and proposal["distribution_review"] == "pending"
    assert proposal["device_parity_evidence_sha256"] is None
