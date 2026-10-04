from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from stock_ai.ml import memory


class Pool:
    backend_name = "fixture-only"

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def bytes_allocated(self):
        return 1234

    def release_unused(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("fixture cleanup failure")


def test_pressure_cleanup_uses_actual_after_value_and_only_one_attempt(tmp_path, monkeypatch):
    pool = Pool()
    readings = iter([3.1, 3.7, 3.2])
    monkeypatch.setattr(memory.pa, "default_memory_pool", lambda: pool)
    monkeypatch.setattr(memory, "_available_physical_bytes", lambda: int(next(readings) * 1024**3))
    with memory.array_workspace(tmp_path, 3.5) as workspace:
        memory.check_fit_headroom()
        assert workspace.fit_checks[0]["passed"] is True
        assert workspace.fit_checks[0]["minimum_gib"] == 3.5
        with pytest.raises(RuntimeError, match=r"below required headroom 3\.500"):
            memory.check_fit_headroom()
        assert workspace.fit_checks[1]["passed"] is False
        assert pool.calls == 1


def test_sufficient_headroom_never_touches_allocator(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("cleanup is only for resource diagnosis")

    monkeypatch.setattr(memory.pa, "default_memory_pool", forbidden)
    monkeypatch.setattr(memory, "_available_physical_bytes", lambda: 5 * 1024**3)
    with memory.array_workspace(tmp_path, 3.5):
        memory.check_fit_headroom()


def test_cleanup_error_does_not_bypass_guard(tmp_path, monkeypatch):
    pool = Pool(fail=True)
    monkeypatch.setattr(memory.pa, "default_memory_pool", lambda: pool)
    monkeypatch.setattr(memory, "_available_physical_bytes", lambda: 3 * 1024**3)
    with memory.array_workspace(tmp_path, 3.5) as workspace:
        with pytest.raises(RuntimeError, match="below required headroom"):
            memory.check_fit_headroom()
        assert workspace.fit_checks[0]["passed"] is False
        assert "fixture cleanup failure" in workspace.fit_checks[0]["arrow_unused_cleanup_error"]


def test_real_unused_cleanup_preserves_live_arrow_buffer_bits(tmp_path, monkeypatch):
    array = pa.array([1.5, -0.0, float("nan"), -2.25] * 256, type=pa.float64())
    view = array.to_numpy(zero_copy_only=True)
    before = view.view(np.uint64).copy()
    buffer = pa.allocate_buffer(1024 * 1024)
    del buffer
    monkeypatch.setattr(memory, "_available_physical_bytes", lambda: 2 * 1024**3)
    with memory.array_workspace(tmp_path, 3.5) as workspace:
        with pytest.raises(RuntimeError, match="below required headroom"):
            memory.check_fit_headroom()
        record = workspace.fit_checks[0]
        assert record["arrow_unused_cleanup_attempted"] is True
        assert record["arrow_live_bytes_after"] == record["arrow_live_bytes_before"]
        assert np.array_equal(view.view(np.uint64), before)
        assert array.to_numpy(zero_copy_only=True).dtype == np.dtype("float64")
