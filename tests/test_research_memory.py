from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from stock_ai.data.contracts import CapabilityStatus
from stock_ai.ml import production as prod
from stock_ai.ml.memory import allocate_array, array_workspace


@pytest.mark.parametrize("rows", [0, 1, 37])
@pytest.mark.parametrize("dtype", ["float32", "float64", "int64"])
def test_scratch_values_layout_and_cleanup(tmp_path, rows, dtype):
    with array_workspace(tmp_path):
        array = allocate_array((rows, 7), dtype)
        expected = np.arange(rows * 7, dtype=dtype).reshape(rows, 7)
        array[:] = expected
        frame = pd.DataFrame(array, copy=False)
        assert np.array_equal(frame.to_numpy(), expected)
        assert frame.to_numpy().dtype == np.dtype(dtype)
        if rows:
            assert np.shares_memory(frame.to_numpy(), array)
            assert isinstance(array.base, np.memmap)
        del array, frame
    assert not list(tmp_path.glob(".stock-ai-arrays-*/*.array"))
    receipt = json.loads(next(tmp_path.glob("*.receipt.json")).read_text())
    assert receipt["remaining_files"] == []


@pytest.mark.parametrize("shuffle", [False, True])
def test_streamed_all_column_digest_exact_mixed_values(tmp_path, shuffle):
    frame = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(
                ["2024-01-03", "2024-01-01", "2024-01-02", "2024-01-02"]
            ),
            "symbol": ["B", "A", "B", "A"],
            "f64": np.array([np.nan, np.inf, -np.inf, -0.0], dtype="float64"),
            "f32": np.array([1.2, np.nan, 0.0, -0.0], dtype="float32"),
            "ints": pd.array([None, 1, 2, -3], dtype="Int64"),
            "floats": pd.array([None, 1.2, 0.0, -0.0], dtype="Float64"),
            "bools": pd.array([None, True, False, True], dtype="boolean"),
            "string": pd.array([None, "銘柄", "", "A"], dtype="string"),
            "category": pd.Categorical(["x", "y", "x", "y"]),
            "timestamp": pd.date_range("2024-01-01", periods=4, tz="Asia/Tokyo"),
            "delta": pd.to_timedelta([1, None, 3, 4], unit="D"),
        }
    )
    if shuffle:
        frame = frame.iloc[[3, 1, 0, 2]]
    path = tmp_path / "mixed.parquet"
    frame.to_parquet(path, index=False)
    original = pd.read_parquet(path).sort_values(["trading_date", "symbol"]).reset_index(drop=True)
    schema, digest = prod._parquet_content_digest(path)
    assert schema == prod._logical_frame_schema(original)
    assert digest == prod._stable_frame_content_digest(original)
    assert prod._stable_frame_content_digest(original) == digest


def test_projected_load_authenticates_excluded_columns(tmp_path):
    # Snapshot consists entirely of deterministic test data.
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "A", "B"],
            "trading_date": pd.to_datetime(
                ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]
            ),
            "as_of": pd.date_range("2024-01-01", periods=4, tz="UTC"),
            "historical_revision_policy": ["single_vintage_as_revised"] * 4,
            "historical_revision_status": ["AVAILABLE"] * 4,
            "unused": [1.0, np.nan, -0.0, np.inf],
        }
    )
    for horizon in (1, 5, 20):
        for family in ("return", "topix_excess", "sector_excess", "beta_residual"):
            frame[f"target_{family}_{horizon}d"] = [0.1, 0.2, None, -0.1]
            status_name = "" if family == "return" else f"_{family}"
            frame[f"label_status{status_name}_{horizon}d"] = ["AVAILABLE"] * 4
        frame[f"target_large_loss_{horizon}d"] = [0.0] * 4
        frame[f"label_end_date_{horizon}d"] = frame["trading_date"]
        frame[f"label_available_at_{horizon}d"] = frame["as_of"]
    snapshot = prod.write_production_dataset_snapshot(
        frame,
        tmp_path,
        source_snapshot_as_of=datetime(2026, 1, 1, tzinfo=UTC),
        source_snapshot_ids=(("fixture", "a" * 64),),
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        label_1230_status=CapabilityStatus.BLOCKED_BY_DATA_CAPABILITY,
    )
    loaded, full = prod.load_production_dataset_snapshot(snapshot.parquet_path)
    selected, subset = prod.load_production_dataset_snapshot(
        snapshot.parquet_path, columns=("symbol", "trading_date", "as_of")
    )
    assert loaded == selected
    pdt.assert_frame_equal(
        subset, full.loc[:, ["symbol", "trading_date", "as_of"]], check_exact=True
    )
    altered = pd.read_parquet(snapshot.parquet_path)
    altered["unused"] += 1
    altered.to_parquet(snapshot.parquet_path, index=False)
    metadata = json.loads(snapshot.metadata_path.read_text())
    metadata["parquet_sha256"] = prod._file_sha256(snapshot.parquet_path)
    metadata["metadata_hash"] = prod._metadata_hash(metadata)
    snapshot.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(RuntimeError, match="content identity"):
        prod.load_production_dataset_snapshot(
            snapshot.parquet_path, columns=("symbol", "trading_date", "as_of")
        )


def test_cli_memory_scratch_option_is_available():
    from typer.testing import CliRunner

    from stock_ai.cli import app

    result = CliRunner().invoke(
        app, ["research", "advanced", "--help"], env={"COLUMNS": "200"}, terminal_width=200
    )
    assert result.exit_code == 0
    assert "--memory-scratch-root" in result.stdout


def test_source_release_requires_explicit_single_horizon(tmp_path):
    from stock_ai.ml.advanced import AdvancedResearchConfig, run_advanced_research

    with pytest.raises(ValueError, match="one horizon and explicit ownership"):
        run_advanced_research(
            pd.DataFrame(),
            data_snapshot_id="a" * 64,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            code_commit="fixture-only",
            config=AdvancedResearchConfig(horizons=(5, 20)),
            feature_snapshot_id="b" * 64,
            feature_manifest_hash="c" * 64,
            memory_scratch_root=tmp_path,
            release_source_frame=True,
        )
