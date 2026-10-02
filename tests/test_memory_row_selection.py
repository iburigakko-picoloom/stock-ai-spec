"""Small deterministic parity fixtures; no production data or workers are used."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

import stock_ai.ml.advanced as patched


def _frame(index_kind):
    rows = 64
    values = np.arange(rows, dtype=np.float64)
    values[1:6] = [np.nan, np.inf, -np.inf, -0.0, 0.0]
    columns = {f"f{i}": values + i for i in range(89)}
    columns.update(
        {
            "float32": pd.array(values, dtype="float32"),
            "int64": np.arange(rows, dtype=np.int64),
            "nullable_int": pd.array([None, 1] * 32, dtype="Int64"),
            "nullable_float": pd.array([None, 1.5] * 32, dtype="Float64"),
            "nullable_bool": pd.array([None, True, False, True] * 16, dtype="boolean"),
            "string": pd.array([None, "株式"] * 32, dtype="string[python]"),
            "arrow_string": pd.array([None, "株式"] * 32, dtype="string[pyarrow]"),
            "datetime": pd.date_range("2024-01-01", periods=rows),
            "tz_datetime": pd.date_range("2024-01-01", periods=rows, tz="Asia/Tokyo"),
            "timedelta": pd.to_timedelta(np.arange(rows), unit="D"),
            "category": pd.Categorical(["a", "b"] * 32, ordered=True),
            "object": pd.array([None, ("a", 1)] * 32, dtype=object),
        }
    )
    frame = pd.DataFrame(columns)
    if index_kind == "duplicate":
        frame.index = pd.Index(np.arange(rows) // 2, name="row_id")
    elif index_kind == "unsorted":
        frame.index = pd.Index(np.arange(rows)[::-1] * 3, name="row_id")
    elif index_kind == "datetime":
        frame.index = pd.date_range("2020-01-01", periods=rows, name="row_id")
    frame.columns.name = "source_column"
    frame.attrs = {"metadata": {"version": "same", "values": [1, 2]}}
    return frame


@pytest.mark.parametrize("copy_on_write", [False, True])
@pytest.mark.parametrize("index_kind", ["range", "duplicate", "unsorted", "datetime"])
@pytest.mark.parametrize("mask_kind", ["alternating", "all", "none", "nullable"])
def test_row_values_dtypes_index_metadata_hash_and_independence(
    copy_on_write,
    index_kind,
    mask_kind,
):
    with pd.option_context("mode.copy_on_write", copy_on_write):
        frame = _frame(index_kind)
        if mask_kind == "all":
            values = [True] * len(frame)
        elif mask_kind == "none":
            values = [False] * len(frame)
        elif mask_kind == "nullable":
            values = [True, None, False, True] * 16
        else:
            values = [True, False] * 32
        mask = pd.Series(values, index=frame.index, dtype="boolean")
        expected = frame.loc[mask].copy()
        actual = patched._select_rows_columnwise(frame, mask)
        pdt.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
        assert actual.flags == expected.flags
        assert patched._frame_hash(actual) == patched._frame_hash(expected)
        if len(actual):
            before = frame.copy()
            actual.iloc[0, 0] = 123456.0
            actual.iloc[0, -1] = "changed"
            actual.attrs["metadata"]["values"].append(3)
            pdt.assert_frame_equal(frame, before, check_exact=True)
            assert frame.attrs == before.attrs


def test_wide_float64_allocation_is_per_column_without_precision_reduction():
    frame = pd.DataFrame({f"f{i}": np.arange(64, dtype=np.float64) for i in range(89)})
    mask = pd.Series([True, False] * 32, index=frame.index)
    old = frame.loc[mask].copy()
    new = patched._select_rows_columnwise(frame, mask)
    pdt.assert_frame_equal(old, new, check_exact=True)
    old_blocks = [block.values.nbytes for block in old._mgr.blocks]
    new_blocks = [block.values.nbytes for block in new._mgr.blocks]
    assert max(old_blocks) == 89 * 32 * 8
    assert max(new_blocks) == 32 * 8
    assert sum(old_blocks) == sum(new_blocks)
    assert all(dtype == np.dtype("float64") for dtype in new.dtypes)


def test_empty_columns_duplicate_columns_and_unaligned_mask():
    for frame in [
        pd.DataFrame(index=pd.Index([3, 2, 1], name="id")),
        pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], columns=["a", "a"]),
    ]:
        mask = pd.Series([True] + [False] * (len(frame) - 1), index=frame.index)
        pdt.assert_frame_equal(
            patched._select_rows_columnwise(frame, mask),
            frame.loc[mask].copy(),
            check_exact=True,
        )
    with pytest.raises(ValueError, match="exact index"):
        patched._select_rows_columnwise(pd.DataFrame({"a": [1]}), pd.Series([True], index=[9]))


@pytest.mark.parametrize("index_kind", ["range", "duplicate", "unsorted", "datetime"])
@pytest.mark.parametrize("validation_cut", [None, pd.Timestamp("2024-01-04")])
@pytest.mark.parametrize("empty", [False, True])
def test_fold_selection_stable_sort_evidence_and_column_blocks(index_kind, validation_cut, empty):
    frame = _frame(index_kind)
    frame["trading_date"] = pd.to_datetime(["2024-01-05", "2024-01-03", None, "2024-01-04"] * 16)
    frame["symbol"] = ["B", "A", "A", "B"] * 16
    frame["target"] = [0.1, 0.2, np.nan, 0.3] * 16
    positions = [] if empty else [5, 3, 0, 3, 6, 8, 1, 9]
    expected = frame.iloc[positions].copy()
    expected = expected.loc[expected["target"].notna()].sort_values(
        ["trading_date", "symbol"],
        kind="stable",
    )
    if validation_cut is not None:
        expected = expected.loc[pd.to_datetime(expected["trading_date"]) >= validation_cut]
    actual = patched._prepare_fold_rows(
        frame,
        positions,
        target_column="target",
        validation_not_before=validation_cut,
    )
    pdt.assert_frame_equal(actual, expected, check_exact=True)
    assert patched._frame_hash(actual) == patched._frame_hash(expected)
    assert actual.attrs == expected.attrs
    if len(actual):
        float_blocks = [
            block.values.nbytes
            for block in actual._mgr.blocks
            if block.dtype == np.dtype("float64")
        ]
        assert max(float_blocks) == len(actual) * 8
