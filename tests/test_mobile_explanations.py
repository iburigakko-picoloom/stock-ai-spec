from __future__ import annotations

import copy
import sqlite3
from datetime import timedelta

import pytest
from mobile.python import explanations, forecasts, models
from mobile.python.model_bundle import encoded
from mobile.python.portable_model import predict
from mobile.python.research_ensemble import ResearchEnsembleBundle

from tests.test_mobile_bundles import IMPORTED
from tests.test_mobile_forecasts import NOW
from tests.test_mobile_research_ensemble import ensemble_bundle, pin

pytest_plugins = ("tests.test_mobile_forecasts",)


def test_median_replacement_separates_positive_negative_and_rank_ties():
    model = {
        "schema_version": "stockai-portable-tree-v1",
        "family": "lightgbm",
        "task": "ranking",
        "preprocessor": {
            "retained": ["a", "b"],
            "lower": {"a": None, "b": None},
            "upper": {"a": None, "b": None},
            "median": {"a": 0.0, "b": 0.0},
        },
        "base_score": 0.0,
        "link": "identity",
        "trees": [
            {
                "feature": 0,
                "threshold": 0.0,
                "operator": "<=",
                "missing_left": True,
                "left": {"leaf": -0.1},
                "right": {"leaf": 0.2},
            },
            {
                "feature": 1,
                "threshold": -0.5,
                "operator": "<=",
                "missing_left": True,
                "left": {"leaf": -0.5},
                "right": {"leaf": 0.4},
            },
        ],
    }
    row = {"a": 1.0, "b": -1.0}
    original = predict(model, [row])[0]
    peers = [("1000", original), ("2000", original), ("3000", 0.1)]
    result = explanations.sensitivity(model, row, original, symbol="2000", peers=peers)
    assert result["originalRank"] == 3
    assert [(x["feature"], x["difference"]) for x in result["positive"]] == [
        ("a", pytest.approx(0.3))
    ]
    assert [(x["feature"], x["difference"]) for x in result["negative"]] == [
        ("b", pytest.approx(-0.9))
    ]
    assert result["positive"][0]["rankChange"] == 0
    assert result["negative"][0]["rankChange"] == -2
    with pytest.raises(ValueError, match="differs"):
        explanations.sensitivity(model, row, original + 0.001)


def test_saved_forecast_is_replayed_without_mutating_portfolio(ready):
    _, store, path, _, _, _ = ready
    saved = forecasts.generate(path, store, NOW)
    before = store.latest_portfolio()
    result = explanations.read(
        path, store, "7203", saved["snapshot"]["snapshot_id"], NOW + timedelta(seconds=1)
    )
    assert result["snapshotId"] == saved["snapshot"]["snapshot_id"]
    assert [(item["horizon"], item["role"], item["available"]) for item in result["models"]] == [
        (5, "return", True),
        (20, "return", True),
        (20, "ranking", False),
    ]
    assert result["models"][0]["prediction"] == 0.01
    assert result["models"][0]["positive"] == result["models"][0]["negative"] == []
    assert store.latest_portfolio() == before


def test_current_three_head_composition_explains_return_and_rank_separately(ready):
    _, store, path, _, _, policy = ready
    source = ensemble_bundle().model_dump(exclude={"bundle_id"})
    source["components"] = [
        c
        for c in source["components"]
        if c["model_id"] in ("h5-regression", "h20-regression", "h20-ranking")
    ]
    source["outputs"] = [o for o in source["outputs"] if o["role"] == "return"]
    source["outputs"].append(
        {
            "horizon": 20,
            "role": "ranking",
            "output_id": "rank-20",
            "recipe_version": "research-composition-v1",
            "unit": "rank_score",
            "components": ["h20-ranking"],
            "weights": [1.0],
            "weight_source": "single",
            "transform": "identity",
        }
    )
    bundle = ResearchEnsembleBundle.create(**source)
    policy["research_bundles"] = [pin(bundle)]
    models.import_bundle(path, encoded(bundle), IMPORTED)
    saved = forecasts.generate(path, store, NOW)
    result = explanations.read(
        path, store, "7203", saved["snapshot"]["snapshot_id"], NOW + timedelta(seconds=1)
    )
    assert [(x["horizon"], x["role"], x["available"]) for x in result["models"]] == [
        (5, "return", True),
        (20, "return", True),
        (20, "ranking", True),
    ]
    assert result["models"][0]["positive"][0]["feature"] == "f1"
    rank = result["models"][2]
    assert rank["prediction"] == pytest.approx(-0.2)
    assert rank["originalRank"] == 2
    assert rank["negative"][0]["difference"] == pytest.approx(-0.1)
    assert rank["negative"][0]["rankChange"] == -1


def test_changed_feature_input_or_bundle_is_never_explained(ready, monkeypatch):
    _, store, path, _, features, _ = ready
    saved = forecasts.generate(path, store, NOW)
    identity = saved["snapshot"]["snapshot_id"]
    changed = copy.deepcopy(features)
    changed["features"]["5"][0]["f1"] += 1
    with monkeypatch.context() as patch:
        patch.setattr(forecasts, "calculate", lambda *args, **kwargs: changed)
        with pytest.raises(ValueError, match="feature inputs"):
            explanations.read(path, store, "7203", identity, NOW + timedelta(seconds=1))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE mobile_model_bundles SET payload='{}'")
    with pytest.raises(ValueError, match="bundle unavailable or changed"):
        explanations.read(path, store, "7203", identity, NOW + timedelta(seconds=1))
