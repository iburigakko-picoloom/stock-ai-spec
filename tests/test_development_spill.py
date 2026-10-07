from __future__ import annotations

import gc
import json
import weakref
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

import stock_ai.ml.advanced as advanced
from stock_ai.features import V2_EXTENDED_MANIFEST
from stock_ai.ml.memory import array_workspace, spill_frame
from tests.test_advanced_research import _config, _production_dataset, _research_features


def test_spill_roundtrip_releases_frame_and_preserves_bits_types_metadata(tmp_path):
    bits = np.array([0x7FF800000000002A, 0x8000000000000000, 0x3FF0000000000000], dtype="uint64")
    frame = pd.DataFrame(
        {
            "float": bits.view("float64"),
            "float32": np.array([np.nan, -0.0, np.inf], dtype="float32"),
            "int": np.array([1, -2, 3], dtype="int64"),
            "nullable": pd.array([1, None, 3], dtype="Int64"),
            "symbol": pd.array(["A", None, "B"], dtype="string"),
            "category": pd.Categorical(["x", "y", "x"], ordered=True),
            "date": pd.date_range("2024-01-01", periods=3, tz="Asia/Tokyo"),
        },
        index=pd.Index([5, 2, 9], name="original"),
    )
    frame.attrs = {"frozen": {"source": "fixture"}}
    frame.flags["allows_duplicate_labels"] = False
    expected = frame.copy(deep=True)
    reference = weakref.ref(frame)
    with array_workspace(tmp_path):
        spill = spill_frame(frame)
        del frame
        gc.collect()
        assert reference() is None
        restored = spill.restore()
        pdt.assert_frame_equal(restored, expected, check_exact=True)
        assert restored.attrs == expected.attrs
        assert not restored.flags["allows_duplicate_labels"]
        assert np.array_equal(restored["float"].to_numpy().view("uint64"), bits)
        assert restored["float32"].to_numpy().tobytes() == expected["float32"].to_numpy().tobytes()
        del restored
    assert not list(tmp_path.glob(".stock-ai-arrays-*/.frame-*"))


def test_spill_rejects_changed_file_and_cleans_failure(tmp_path):
    with pytest.raises(RuntimeError, match="integrity mismatch"):
        with array_workspace(tmp_path):
            spill = spill_frame(pd.DataFrame({"x": [1.0, 2.0]}))
            spill.files[0][0].write_bytes(b"not an authenticated pickle")
            spill.restore()
    assert not list(tmp_path.glob(".stock-ai-arrays-*/.frame-*"))


@pytest.mark.parametrize("family", ["lightgbm", "xgboost", "catboost"])
def test_spill_preserves_native_research_outputs_and_releases_before_tuning(
    tmp_path, monkeypatch, family
):
    dataset = _production_dataset()
    config = _config(model_families=(family,))
    kwargs = dict(
        data_snapshot_id="a" * 64,
        created_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
        code_commit="spill-fixture",
        config=config,
        feature_snapshot_id="b" * 64,
        feature_manifest_hash=V2_EXTENDED_MANIFEST.manifest_hash,
        feature_names=_research_features(),
        release_source_frame=True,
    )
    baseline = advanced.run_advanced_research(
        dataset.copy(deep=True), memory_scratch_root=tmp_path / "baseline", **kwargs
    )
    original_select = advanced._select_rows_columnwise
    original_search = advanced.bounded_optuna_search
    references = []

    def select(*args, **options):
        frame = original_select(*args, **options)
        references.append(weakref.ref(frame))
        return frame

    def search(*args, **options):
        assert references[0]() is None
        return original_search(*args, **options)

    monkeypatch.setattr(advanced, "_select_rows_columnwise", select)
    monkeypatch.setattr(advanced, "bounded_optuna_search", search)
    changed = advanced.run_advanced_research(
        dataset.copy(deep=True),
        memory_scratch_root=tmp_path / "spill",
        spill_development_during_tuning=True,
        **kwargs,
    )
    pdt.assert_frame_equal(baseline.oof_predictions, changed.oof_predictions, check_exact=True)
    # Wall-clock trial durations differ; compare every scientific/audit value otherwise.
    reports = [json.loads(run.report.model_dump_json()) for run in (baseline, changed)]
    for report in reports:
        for tuning in report["tuning_results"]:
            for trial in tuning["trials"]:
                trial["duration_seconds"] = None
    assert reports[0] == reports[1]
    receipt = json.loads(next((tmp_path / "spill").glob("*.receipt.json")).read_text())
    assert receipt["development_spills"][0]["restored"]
