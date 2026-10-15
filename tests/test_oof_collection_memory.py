from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

import stock_ai.ml.advanced as advanced

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "oof_collection_fixtures", ROOT / "tests/test_advanced_research.py"
)
fixtures = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixtures
spec.loader.exec_module(fixtures)


def arguments():
    return dict(
        feature_names=fixtures._research_features(),
        target_column="target_return_1d",
        label_end_column="label_end_date_1d",
        horizon=1,
        family="catboost",
        task="regression",
        seed=17,
        parameters={"depth": 3, "learning_rate": 0.05, "l2": 1.0},
        config=fixtures._config(model_families=("catboost",)),
    )


def test_collector_parts_match_default_without_full_width_return_sort(monkeypatch):
    frame = fixtures._production_dataset()
    monkeypatch.setattr(
        advanced, "_fit_predict", lambda **kwargs: np.arange(len(kwargs["validation_x"])) / 100
    )
    expected = advanced.generate_oof_predictions(frame, **arguments())
    sort = pd.DataFrame.sort_values
    concatenated = []
    concat = pd.concat

    def bounded_sort(self, *args, **kwargs):
        assert "prediction" not in self.columns, "Do not sort an unused complete OOF return"
        return sort(self, *args, **kwargs)

    def bounded_concat(objects, *args, **kwargs):
        objects = list(objects)
        concatenated.extend(tuple(part.columns) for part in objects)
        return concat(objects, *args, **kwargs)

    with monkeypatch.context() as local:
        local.setattr(pd.DataFrame, "sort_values", bounded_sort)
        local.setattr(pd, "concat", bounded_concat)
        parts = []
        result = advanced.generate_oof_predictions(
            frame, progress_sink=parts, _collect_parts_only=True, **arguments()
        )
    assert result.empty
    assert concatenated and all("prediction" not in columns for columns in concatenated)
    key = ["symbol", "trading_date", "horizon", "model_family", "task", "seed"]
    observed = (
        pd.concat(parts, ignore_index=True).sort_values(key, kind="stable").reset_index(drop=True)
    )
    pdt.assert_frame_equal(observed, expected, check_exact=True)
    assert advanced._frame_hash(observed) == advanced._frame_hash(expected)


def test_collector_still_rejects_duplicate_fold_identities(monkeypatch):
    frame = fixtures._production_dataset()
    original = advanced.PurgedExpandingWindowSplitter.split

    def duplicated(self, *args, **kwargs):
        first = next(original(self, *args, **kwargs))
        yield first
        yield first

    monkeypatch.setattr(advanced.PurgedExpandingWindowSplitter, "split", duplicated)
    monkeypatch.setattr(
        advanced, "_fit_predict", lambda **kwargs: np.zeros(len(kwargs["validation_x"]))
    )
    with pytest.raises(RuntimeError, match="duplicate model-row identities"):
        advanced.generate_oof_predictions(
            frame, progress_sink=[], _collect_parts_only=True, **arguments()
        )


def test_collector_still_checks_nonfinite_cached_predictions(monkeypatch):
    frame = fixtures._production_dataset()
    monkeypatch.setattr(
        advanced, "_fit_predict", lambda **kwargs: np.zeros(len(kwargs["validation_x"]))
    )
    expected = advanced.generate_oof_predictions(frame, **arguments())

    class Cached:
        def load_fold(self, evidence, **kwargs):
            part = expected.loc[expected.fold.eq(evidence["fold"])].copy()
            part["prediction"] = np.nan
            return part

    with pytest.raises(RuntimeError, match="non-finite OOF predictions"):
        advanced.generate_oof_predictions(
            frame,
            checkpoint_store=Cached(),
            progress_sink=[],
            _collect_parts_only=True,
            **arguments(),
        )


def test_parts_only_requires_owned_sink(monkeypatch):
    monkeypatch.setattr(
        advanced, "_fit_predict", lambda **kwargs: np.zeros(len(kwargs["validation_x"]))
    )
    with pytest.raises(ValueError, match="explicit progress sink"):
        advanced.generate_oof_predictions(
            fixtures._production_dataset(), _collect_parts_only=True, **arguments()
        )
