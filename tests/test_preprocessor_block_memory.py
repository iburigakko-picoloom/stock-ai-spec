"""Independent old-code statistics/model parity and bounded quantile work arrays."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

import stock_ai.ml.advanced as current

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests/fixtures/advanced_memory_a68.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


old = _load("stock_ai.ml.block_layout_baseline", BASELINE)
fixtures = _load("block_layout_fixtures", ROOT / "tests/test_advanced_research.py")


@pytest.mark.parametrize("copy_on_write", [False, True])
@pytest.mark.parametrize("rows", [31, 32, 257])
def test_old_code_statistics_retention_input_and_hash_exact(copy_on_write, rows):
    rng = np.random.default_rng(314)
    frame = pd.DataFrame(rng.normal(size=(rows, 41)), columns=[f"f{i}" for i in range(41)])
    frame.index = pd.Index(np.arange(rows)[::-1] // 2, name="duplicate_unsorted")
    frame.iloc[0, :5] = [np.nan, np.inf, -np.inf, -0.0, 0.0]
    frame["f39"] = frame["f1"] * 2
    frame["f40"] = 1.0
    before = frame.copy()
    arguments = dict(lower_quantile=0.005, upper_quantile=0.995, correlation_threshold=0.98)
    with pd.option_context("mode.copy_on_write", copy_on_write):
        expected = old.FoldPreprocessor(tuple(frame.columns), **arguments).fit(frame)
        actual = current.FoldPreprocessor(tuple(frame.columns), **arguments).fit(frame)
        for state in ("_lower", "_upper", "_median"):
            pdt.assert_series_equal(
                getattr(actual, state), getattr(expected, state), check_exact=True
            )
        assert actual.retained_features == expected.retained_features
        wanted = expected.transform(frame)
        observed = actual.transform(frame)
        pdt.assert_frame_equal(observed, wanted, check_exact=True)
        assert all(dtype == np.dtype("float32") for dtype in observed.dtypes)
        assert current._frame_hash(observed) == old._frame_hash(wanted)
        pdt.assert_frame_equal(frame, before, check_exact=True)


def test_quantile_work_array_is_one_feature_instead_of_whole_width(monkeypatch):
    frame = pd.DataFrame(np.random.default_rng(271).normal(size=(128, 41)))
    captured = []
    percentile = np.percentile

    def observed(values, *args, **kwargs):
        captured.append(np.asarray(values).nbytes)
        return percentile(values, *args, **kwargs)

    monkeypatch.setattr(np, "percentile", observed)
    with pd.option_context("mode.copy_on_write", True):
        expected = old._finite_numeric(frame).quantile(0.005)
        old_maximum = max(captured)
        captured.clear()
        actual = current._finite_numeric(frame).quantile(0.005)
        new_maximum = max(captured)
    pdt.assert_series_equal(actual, expected, check_exact=True)
    assert old_maximum == len(frame) * len(frame.columns) * 4
    assert new_maximum <= len(frame) * 4


@pytest.mark.parametrize("copy_on_write", [False, True])
def test_entire_native_catboost_oof_and_report_match_old_code(copy_on_write):
    frame = fixtures._production_dataset()
    configuration = fixtures._config(model_families=("catboost",))
    arguments = dict(
        data_snapshot_id="a" * 64,
        created_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
        code_commit="fixture-only-equal-comparison",
        feature_snapshot_id="b" * 64,
        feature_manifest_hash=fixtures.V2_EXTENDED_MANIFEST.manifest_hash,
        feature_names=fixtures._research_features(),
    )
    with pd.option_context("mode.copy_on_write", copy_on_write):
        expected = old.run_advanced_research(
            frame.copy(),
            config=old.AdvancedResearchConfig(**configuration.model_dump()),
            **arguments,
        )
        actual = current.run_advanced_research(frame.copy(), config=configuration, **arguments)
    pdt.assert_frame_equal(actual.oof_predictions, expected.oof_predictions, check_exact=True)
    assert actual.report.report_id == expected.report.report_id
    observed = actual.report.model_dump(mode="json")
    wanted = expected.report.model_dump(mode="json")
    # Wall-clock trial durations are measured independently, not research outputs.
    for payload in (observed, wanted):
        for result in payload["tuning_results"]:
            for trial in result["trials"]:
                duration = trial.pop("duration_seconds")
                assert duration is None or duration >= 0
    assert observed == wanted
