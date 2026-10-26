"""Synthetic, reproducible component timings; never an Android latency claim."""

from __future__ import annotations

import argparse
import json
import platform
import random
import sqlite3
import statistics
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mobile.python import runtime

from stock_ai.operations import bootstrap_goal5_fixture
from stock_ai.operations.integrity import IntegrityGuard


def measure(function, repeats=5):
    values = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = function()
        values.append((time.perf_counter() - start) * 1000)
    return {"median_ms": statistics.median(values), "samples_ms": values}, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-mib", type=int, default=16)
    parser.add_argument("--portfolios", type=int, default=500)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="stock-ai-ui-benchmark-") as directory:
        runtime.STATE = Path(directory) / "state"
        runtime.initialize()
        store = runtime._app.state.store
        as_of = datetime(2026, 1, 8, 11, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
        bootstrap_goal5_fixture(store, as_of=as_of)
        original = store.latest_portfolio()
        for index in range(args.portfolios):
            store.append_portfolio(original.model_copy(update={
                "portfolio_id": f"synthetic-{index}",
                "as_of": as_of + timedelta(seconds=index + 1),
            }), created_at=as_of)
        with closing(sqlite3.connect(runtime.STATE / "mobile.sqlite3")) as db:
            db.execute("CREATE TABLE benchmark_payload(data BLOB)")
            rng = random.Random(42)
            for _ in range(args.market_mib):
                db.execute("INSERT INTO benchmark_payload VALUES(?)", (rng.randbytes(1024**2),))
            db.commit()
        baseline, counts = measure(store.verify_integrity)
        guard = IntegrityGuard(store)
        assert guard.verify() == counts
        reused, checked = measure(guard.verify)
        assert checked == counts

        def archive(operations):
            stream = runtime.StateExport(operations_only=operations)
            size = stream.length
            while stream.read_next() is not None:
                pass
            return size

        # Warm compaction once; exclude migration from the comparison.
        archive(False)
        full, full_size = measure(lambda: archive(False), 3)
        operations, operations_size = measure(lambda: archive(True), 3)
        report = {
            "scope": "synthetic CPython component benchmark; not Android/end-to-end",
            "python": platform.python_version(), "platform": platform.platform(),
            "portfolio_snapshots": args.portfolios + 1,
            "synthetic_market_payload_mib": args.market_mib,
            "full_integrity": baseline, "unchanged_integrity": reused,
            "full_archive": {**full, "base64_characters": full_size},
            "operations_archive": {**operations, "base64_characters": operations_size},
            "excludes": ["cold startup", "queue wait", "native transfer/encryption",
                         "device storage", "actual market compression ratio", "screen rendering"],
        }
        guard.close()
        runtime._app.state.integrity_guard.close()
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n")
        print(text)


if __name__ == "__main__":
    main()
