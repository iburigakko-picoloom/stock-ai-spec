"""Opt-in, owned local scratch arrays; research dtypes/order remain unchanged."""

from __future__ import annotations

import gc
import json
import shutil
import tempfile
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import numpy as np

_ACTIVE: ContextVar[ArrayWorkspace | None] = ContextVar("stock_array_workspace", default=None)


class ArrayWorkspace:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=".stock-ai-arrays-", dir=root)).resolve()
        self.files: list[tuple[Path, weakref.ReferenceType[Any]]] = []
        self.allocations: list[dict[str, object]] = []

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
        receipt = self.path.with_suffix(".receipt.json")
        receipt.write_text(
            json.dumps(
                {
                    "allocations": self.allocations,
                    "remaining_files": [path.name for path, _ in self.files],
                    "left_live_mappings_open": bool(self.files),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if not self.files:
            self.path.rmdir()


@contextmanager
def array_workspace(root: Path | None) -> Iterator[ArrayWorkspace | None]:
    if root is None:
        yield None
        return
    workspace = ArrayWorkspace(root)
    token = _ACTIVE.set(workspace)
    try:
        yield workspace
    finally:
        _ACTIVE.reset(token)
        workspace.close()


def allocate_array(shape: tuple[int, ...], dtype: Any) -> np.ndarray[Any, Any]:
    active = _ACTIVE.get()
    return np.empty(shape, dtype=dtype) if active is None else active.allocate(shape, dtype)


def take_column(series: Any, indices: np.ndarray[Any, Any]) -> Any:
    active = _ACTIVE.get()
    if active is None or not isinstance(series.dtype, np.dtype) or series.dtype.kind not in "fiu":
        return series.array.take(indices)
    array = active.allocate((len(indices),), series.dtype)
    np.take(series.to_numpy(copy=False), indices, out=array)
    if isinstance(array.base, np.memmap):
        array.base.flush()
    return array
