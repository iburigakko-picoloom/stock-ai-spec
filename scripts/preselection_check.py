"""Compare one private SQLite snapshot and real heads; never fit or score holdout.

Run baseline, cold and warm in separate processes, serially, against the SAME
isolated database copy. Output contains private market/model-derived values.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from mobile.python import features, input_cache, market, models, preselection
from mobile.python.portable_model import predict
from scripts.mobile_feature_check import memory_bytes

from stock_ai.ml.memory import _available_physical_bytes
from stock_ai.operations.daily import content_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("baseline", "cold", "warm"))
    args = parser.parse_args()
    root = Path.cwd().resolve()
    out = args.output.resolve()
    if not out.is_relative_to(root / ".demo-artifacts") or out == root / ".demo-artifacts":
        raise ValueError("Private experiment output required")
    if not args.database.resolve().is_relative_to(out):
        raise ValueError("Use an isolated database copy inside the experiment directory")
    out.mkdir(parents=True, exist_ok=True)
    report_file = out / (args.mode + ".json")
    if report_file.exists():
        raise ValueError("Preserve previous results; use a fresh experiment")
    if _available_physical_bytes() < 4 * 1024**3:
        raise ValueError("At least four GiB host reserve required to start")
    cutoff = datetime.fromisoformat(args.as_of)
    selection = preselection.select(args.database, cutoff)
    if selection["blocking_reasons"]:
        raise ValueError(selection["blocking_reasons"])
    (out / "preselection.json").write_text(json.dumps(selection), encoding="utf-8")
    selected = selection["decision_symbols"]
    frozen = next((root / "artifacts/selections/goal3-features").glob("*/*.json"))
    feature_selection = json.loads(frozen.read_text(encoding="utf-8"))["feature_selection"]
    models.bundled_selection = lambda: feature_selection
    bundle, pin = models.load_bundle(args.database, cutoff)
    # Only pointwise portable heads are used here. There is no cross-universe
    # normalization or new ensemble whose changed domain could alter predictions.
    if any(head.task != "regression" for head in bundle.heads):
        raise ValueError("This probe requires the existing two research return heads")
    original_connect = sqlite3.connect
    reads = {"rows": 0, "returned_value_bytes": 0, "by_table": {}}

    class Cursor(sqlite3.Cursor):
        def execute(self, sql, parameters=()):
            self.read_kind = (
                next(
                    (
                        name
                        for name in (
                            "mobile_input_cache",
                            "market_columns",
                            "market_batches",
                        )
                        if name in sql
                    ),
                    "other",
                )
                if sql.lstrip().upper().startswith(("SELECT", "WITH", "PRAGMA"))
                else None
            )
            return super().execute(sql, parameters)

        def observed(self, rows):
            if self.read_kind is not None:
                size = sum(
                    len(x)
                    if isinstance(x, bytes)
                    else len(x.encode())
                    if isinstance(x, str)
                    else 0
                    if x is None
                    else 8
                    for row in rows
                    for x in row
                )
                reads["rows"] += len(rows)
                reads["returned_value_bytes"] += size
                group = reads["by_table"].setdefault(self.read_kind, [0, 0])
                group[0] += len(rows)
                group[1] += size
            return rows

        def __next__(self):
            return self.observed([super().__next__()])[0]

        def fetchone(self):
            row = super().fetchone()
            return self.observed([row])[0] if row is not None else None

        def fetchall(self):
            return self.observed(super().fetchall())

    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            return self.cursor(factory=Cursor).execute(sql, parameters)

    def observed_connect(*a, **kw):
        return original_connect(*a, **kw, factory=Connection)

    sqlite3.connect = observed_connect
    peak = [0]
    stopped = threading.Event()
    started = time.perf_counter()

    def sample():
        while not stopped.wait(0.25):
            current, high = memory_bytes()
            peak[0] = max(peak[0], current, high)
            if (
                current > 3500 * 1024**2
                or _available_physical_bytes() < 1024**3
                or time.perf_counter() - started > 1800
            ):
                (out / (args.mode + "-resource-stop.json")).write_text(
                    json.dumps({"current_bytes": current, "peak_bytes": peak[0]}),
                    encoding="utf-8",
                )
                os._exit(3)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        inputs = market.feature_inputs(
            args.database,
            cutoff,
            True,
            decision_symbols=selected,
            preselected=args.mode != "baseline",
        )
        input_seconds = time.perf_counter() - started
        print(
            json.dumps(
                {"phase": "inputs", "mode": args.mode, "seconds": input_seconds, "sqlite": reads}
            ),
            flush=True,
        )
        for name in ("daily", "market", "sector", "financials"):
            reference_file = out / ("baseline-" + name + ".npz")
            if args.mode == "baseline":
                reference_file.write_bytes(input_cache._pack(inputs[name]))
            else:
                pd.testing.assert_frame_equal(
                    inputs[name],
                    input_cache._unpack(reference_file.read_bytes()),
                    check_exact=True,
                )
        mark = time.perf_counter()
        calculated = features.calculate(inputs, feature_selection)
        feature_seconds = time.perf_counter() - mark
        mark = time.perf_counter()
        outputs = [
            {
                "horizon": head.horizon,
                "values": list(
                    zip(
                        [row["symbol"] for row in calculated["features"][str(head.horizon)]],
                        predict(
                            head.decoded(feature_selection),
                            calculated["features"][str(head.horizon)],
                        ),
                        strict=True,
                    )
                ),
            }
            for head in bundle.heads
        ]
        inference_seconds = time.perf_counter() - mark
        proof = {
            "features": calculated,
            "predictions": outputs,
            "source_snapshot_ids": sorted(inputs["source_snapshot_ids"]),
        }
        if args.mode == "baseline":
            (out / "baseline-values.json").write_text(json.dumps(proof), encoding="utf-8")
        else:
            assert json.loads(json.dumps(proof)) == json.loads(
                (out / "baseline-values.json").read_text(encoding="utf-8")
            )
        result = {
            "mode": args.mode,
            "status": "PASS",
            "as_of": cutoff.isoformat(),
            "input_seconds": input_seconds,
            "feature_seconds": feature_seconds,
            "inference_seconds": inference_seconds,
            "total_seconds": time.perf_counter() - started,
            "peak_bytes": peak[0],
            "candidates": len(selected),
            "rows": {
                name: len(inputs[name]) for name in ("daily", "market", "sector", "financials")
            },
            "predictions": sum(len(item["values"]) for item in outputs),
            "feature_values_hash": content_id(calculated),
            "sqlite_reads": reads,
            "sqlite_byte_definition": "returned BLOB/UTF8/scalars; excludes physical page IO",
            "cache": inputs.get("input_cache"),
            "model_bundle_sha256": pin["sha256"],
            "code_version": input_cache.code_version(),
            "formal_adoption": "HOLD",
            "new_fits": 0,
            "holdout_scored": False,
            "Android_measured": False,
        }
        report_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    finally:
        stopped.set()
        sampler.join()
        sqlite3.connect = original_connect


if __name__ == "__main__":
    main()
