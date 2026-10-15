"""Opt-in, owned local scratch arrays; research dtypes/order remain unchanged."""

from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import pickle
import shutil
import sys
import tempfile
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

_ACTIVE: ContextVar[ArrayWorkspace | None] = ContextVar("stock_array_workspace", default=None)


def _spill_column_digest(values: Any) -> str:
    dtype = pd.Series(values, copy=False).dtype
    digest = hashlib.sha256(str(dtype).encode())
    if isinstance(dtype, np.dtype) and dtype.kind in "fiu":
        digest.update(np.asarray(values).tobytes(order="C"))
    else:
        digest.update(
            pd.util.hash_pandas_object(pd.Series(values, copy=False), index=False)
            .to_numpy()
            .tobytes()
        )
    return digest.hexdigest()


def _spill_file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class FrameSpill:
    """Lossless, owned column files; no references to the original frame survive."""

    def __init__(self, root: Path, frame: pd.DataFrame):
        self.path = Path(tempfile.mkdtemp(prefix=".frame-", dir=root)).resolve()
        self.files: list[tuple[Path, str, str]] = []
        self.header = self.path / "header.pickle"
        self.report: dict[str, object] = {
            "rows": len(frame),
            "columns": len(frame.columns),
            "restored": False,
        }
        try:
            with self.header.open("wb") as handle:
                pickle.dump(
                    (
                        frame.index,
                        frame.columns,
                        frame.attrs,
                        frame.flags["allows_duplicate_labels"],
                    ),
                    handle,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            self.header_digest = _spill_file_digest(self.header)
            for position in range(len(frame.columns)):
                values = frame.iloc[:, position].array
                digest = _spill_column_digest(values)
                path = self.path / f"{position:06d}.pickle"
                with path.open("wb") as handle:
                    pickle.dump(values, handle, protocol=pickle.HIGHEST_PROTOCOL)
                self.files.append((path, _spill_file_digest(path), digest))
            self.report["bytes"] = sum(p.stat().st_size for p, _, _ in self.files)
        except Exception:
            self.close()
            raise

    def restore(self) -> pd.DataFrame:
        if _spill_file_digest(self.header) != self.header_digest:
            raise RuntimeError("development spill header integrity mismatch")
        with self.header.open("rb") as handle:
            index, columns, attrs, duplicate_labels = pickle.load(handle)
        restored: dict[int, Any] = {}
        for position, (path, file_digest, content_digest) in enumerate(self.files):
            if _spill_file_digest(path) != file_digest:
                raise RuntimeError("development spill file integrity mismatch")
            with path.open("rb") as handle:
                values = pickle.load(handle)
            if _spill_column_digest(values) != content_digest:
                raise RuntimeError("development spill values/dtype mismatch")
            dtype = pd.Series(values, copy=False).dtype
            if isinstance(dtype, np.dtype) and dtype.kind in "fiu":
                mapped = allocate_array((len(values),), dtype)
                mapped[:] = np.asarray(values)
                if isinstance(mapped.base, np.memmap):
                    mapped.base.flush()
                values = mapped
            restored[position] = values
        frame = pd.DataFrame(restored, index=index, copy=False)
        frame.columns = columns
        frame.attrs = attrs
        frame.flags["allows_duplicate_labels"] = duplicate_labels
        for position, (_, _, digest) in enumerate(self.files):
            if _spill_column_digest(frame.iloc[:, position].array) != digest:
                raise RuntimeError("restored development values/dtype mismatch")
        self.report["restored"] = True
        return frame

    def close(self) -> None:
        # Only files generated in this newly owned directory are removed.
        for path in self.path.iterdir():
            path.unlink()
        self.path.rmdir()


def spill_frame(frame: pd.DataFrame) -> FrameSpill:
    active = _ACTIVE.get()
    if active is None:
        raise ValueError("development spill requires an owned array workspace")
    if shutil.disk_usage(active.path).free < int(frame.memory_usage(deep=True).sum()) + 2 * 1024**3:
        raise RuntimeError("insufficient disk headroom for development spill")
    spill = FrameSpill(active.path, frame)
    active.frame_spills.append(spill)
    return spill


class ArrayWorkspace:
    def __init__(self, root: Path, minimum_fit_headroom_gib: float = 0.0):
        if not np.isfinite(minimum_fit_headroom_gib) or minimum_fit_headroom_gib < 0:
            raise ValueError("fit memory headroom must be finite and non-negative")
        self.minimum_fit_headroom_gib = minimum_fit_headroom_gib
        self.fit_checks: list[dict[str, object]] = []
        self.unused_pool_cleanup_attempted = False
        root.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=".stock-ai-arrays-", dir=root)).resolve()
        self.files: list[tuple[Path, weakref.ReferenceType[Any]]] = []
        self.allocations: list[dict[str, object]] = []
        self.frame_spills: list[FrameSpill] = []

    def reap(self) -> None:
        remaining = []
        for path, reference in self.files:
            if reference() is not None:
                remaining.append((path, reference))
                continue
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                remaining.append((path, reference))
        self.files = remaining

    def allocate(self, shape: tuple[int, ...], dtype: Any) -> np.ndarray[Any, Any]:
        dtype = np.dtype(dtype)
        if not int(np.prod(shape)):
            return np.empty(shape, dtype=dtype)
        self.reap()
        size = int(np.prod(shape)) * dtype.itemsize
        if shutil.disk_usage(self.path).free < size + 2 * 1024**3:
            raise RuntimeError("insufficient disk headroom for local array scratch")
        number = len(self.allocations)
        path = self.path / f"{number:06d}.array"
        array = np.memmap(path, dtype=dtype, mode="w+", shape=shape, order="C")
        self.files.append((path, weakref.ref(array)))
        self.allocations.append({"shape": list(shape), "dtype": str(dtype), "bytes": size})
        return np.asarray(array)

    def close(self) -> None:
        # Never close a mapping while a surviving DataFrame/view can reference it.
        gc.collect()
        self.reap()
        for spill in self.frame_spills:
            if spill.path.exists():
                spill.close()
        receipt = self.path.with_suffix(".receipt.json")
        receipt.write_text(
            json.dumps(
                {
                    "allocations": self.allocations,
                    "remaining_files": [path.name for path, _ in self.files],
                    "left_live_mappings_open": bool(self.files),
                    "fit_headroom_checks": self.fit_checks,
                    "development_spills": [spill.report for spill in self.frame_spills],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if not self.files:
            self.path.rmdir()


@contextmanager
def array_workspace(
    root: Path | None, minimum_fit_headroom_gib: float = 0.0
) -> Iterator[ArrayWorkspace | None]:
    if root is None:
        if minimum_fit_headroom_gib:
            raise ValueError("fit memory headroom requires an explicit scratch root")
        yield None
        return
    workspace = ArrayWorkspace(root, minimum_fit_headroom_gib)
    token = _ACTIVE.set(workspace)
    try:
        yield workspace
    finally:
        _ACTIVE.reset(token)
        workspace.close()


def allocate_array(shape: tuple[int, ...], dtype: Any) -> np.ndarray[Any, Any]:
    active = _ACTIVE.get()
    return np.empty(shape, dtype=dtype) if active is None else active.allocate(shape, dtype)


def _available_physical_bytes() -> int:
    if sys.platform != "win32":
        raise RuntimeError("explicit fit memory guard is currently Windows-only")

    else:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (name, ctypes.c_uint64)
                for name in (
                    "total_physical",
                    "available_physical",
                    "total_pagefile",
                    "available_pagefile",
                    "total_virtual",
                    "available_virtual",
                    "available_extended_virtual",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError(ctypes.get_last_error(), "unable to read fit memory headroom")
        return int(status.available_physical)


def check_fit_headroom() -> None:
    active = _ACTIVE.get()
    if active is None or not active.minimum_fit_headroom_gib:
        return
    gc.collect()
    active.reap()
    available_before = _available_physical_bytes() / 1024**3
    available_gib = available_before
    cleanup: dict[str, object] = {"arrow_unused_cleanup_attempted": False}
    if (
        available_before < active.minimum_fit_headroom_gib
        and not active.unused_pool_cleanup_attempted
    ):
        # One pressure-triggered diagnostic per owned run, never a restart loop.
        # Arrow releases unused allocator storage only; live buffers stay owned.
        active.unused_pool_cleanup_attempted = True
        pool = pa.default_memory_pool()
        cleanup.update(
            arrow_unused_cleanup_attempted=True,
            arrow_backend=pool.backend_name,
            arrow_live_bytes_before=pool.bytes_allocated(),
        )
        try:
            pool.release_unused()
        except Exception as exc:
            cleanup["arrow_unused_cleanup_error"] = f"{type(exc).__name__}: {exc}"
        cleanup["arrow_live_bytes_after"] = pool.bytes_allocated()
        available_gib = _available_physical_bytes() / 1024**3
    passed = available_gib >= active.minimum_fit_headroom_gib
    active.fit_checks.append(
        {
            "checked_at_utc": datetime.now(UTC).isoformat(),
            "available_gib": available_gib,
            "available_gib_before_unused_cleanup": available_before,
            **cleanup,
            "minimum_gib": active.minimum_fit_headroom_gib,
            "passed": passed,
        }
    )
    active.path.with_suffix(".fit-headroom.json").write_text(
        json.dumps(active.fit_checks, indent=2), encoding="utf-8"
    )
    if not passed:
        raise RuntimeError(
            f"BLOCKED_BY_RESOURCE_CAPABILITY: before fit available physical RAM "
            f"{available_gib:.3f} GiB below required headroom "
            f"{active.minimum_fit_headroom_gib:.3f} GiB"
        )


def take_column(series: Any, indices: np.ndarray[Any, Any]) -> Any:
    active = _ACTIVE.get()
    if active is None or not isinstance(series.dtype, np.dtype) or series.dtype.kind not in "fiu":
        return series.array.take(indices)
    array = active.allocate((len(indices),), series.dtype)
    np.take(series.to_numpy(copy=False), indices, out=array)
    if isinstance(array.base, np.memmap):
        array.base.flush()
    return array
