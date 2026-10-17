"""Bounded synthetic PC context/latest-feature probe, without API or model fitting."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from mobile.python.market import SQLiteSource

from stock_ai.data.production import build_production_data
from stock_ai.features import V2_EXTENDED_MANIFEST, FeatureEngine

ROOT = Path(__file__).resolve().parents[1]


class WindowsCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
        (name, ctypes.c_size_t)
        for name in (
            "peak",
            "current",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "pagefile",
            "peak_pagefile",
        )
    ]


def memory_bytes():
    if sys.platform == "win32":
        counters = WindowsCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.K32GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(WindowsCounters),
            ctypes.c_ulong,
        )
        if not kernel.K32GetProcessMemoryInfo(
            kernel.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        ):
            raise OSError("Cannot observe probe memory")
        return counters.current, counters.peak
    if sys.platform.startswith("linux"):
        values = {}
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, value, unit = line.split()
                if unit != "kB":
                    raise ValueError("Unexpected process memory unit")
                values[key] = int(value) * 1024
        return values["VmRSS:"], values["VmHWM:"]
    raise ValueError("This PC probe supports Windows and Linux")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--memory-mib", type=int, default=3500)
    parser.add_argument("--reference-history", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.report.resolve()
    isolated = ROOT / ".demo-artifacts"
    if (
        Path.cwd().resolve() != ROOT
        or source == isolated
        or not source.is_relative_to(isolated)
        or not output.is_relative_to(isolated)
        or not source.is_dir()
        or not output.parent.is_dir()
        or output.exists()
    ):
        raise ValueError("Use isolated synthetic history and a fresh .demo-artifacts report")
    if not 1 <= args.seconds <= 900 or not 256 <= args.memory_mib <= 4000:
        raise ValueError("Bounded time and memory required")
    capacity_path = source / "report.json"
    capacity = json.loads(capacity_path.read_text(encoding="utf-8"))
    if (
        capacity.get("synthetic_only") is not True
        or capacity.get("status") != "passed"
        or capacity.get("seed") != 20261017
        or not 1 <= capacity.get("symbols", 0) <= 5000
        or not 1 <= capacity.get("requested_sessions", 0) <= 300
    ):
        raise ValueError("A completed synthetic capacity probe is required")
    path = source / "mobile.sqlite3"
    before = digest(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        count, latest = db.execute("SELECT COUNT(*),MAX(received_at) FROM market_days").fetchone()
    if count != capacity["requested_sessions"]:
        raise ValueError("Synthetic history count changed")
    cutoff = datetime.fromisoformat(latest)
    current, peak = memory_bytes()
    report = {
        "synthetic_only": True,
        "scope": (
            "PC source context and FeatureEngine; not mobile JSON/forecast or phone performance"
        ),
        "mode": "full-history-reference" if args.reference_history else "latest",
        "status": "running",
        "phase": "source-context",
        "symbols": capacity["symbols"],
        "source_sessions": count,
        "source_cutoff": cutoff.isoformat(),
        "capacity_report_sha256": digest(capacity_path),
        "database_sha256": before,
        "working_set_abort_bytes": args.memory_mib * 1024 * 1024,
        "wall_abort_seconds": args.seconds,
        "current_working_set_bytes": current,
        "peak_working_set_bytes": peak,
        "checkpoints": [],
        "source_sha256": {
            name: digest(ROOT / name)
            for name in (
                "scripts/mobile_feature_check.py",
                "mobile/python/market.py",
                "mobile/python/market_codec.py",
                "src/stock_ai/data/production.py",
                "src/stock_ai/features/engine.py",
                "src/stock_ai/features/indicators.py",
            )
        },
    }
    started = time.perf_counter()
    lock = threading.RLock()

    def save():
        report["elapsed_seconds"] = time.perf_counter() - started
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def guard():
        while True:
            with lock:
                if report["status"] != "running":
                    return
                try:
                    current, peak = memory_bytes()
                    reason = (
                        "memory"
                        if peak > report["working_set_abort_bytes"]
                        else "time"
                        if time.perf_counter() - started > args.seconds
                        else None
                    )
                except Exception:
                    current, peak, reason = None, None, "observation-failed"
                if reason:
                    report.update(
                        status="budget-exceeded",
                        reason=reason,
                        current_working_set_bytes=current,
                        peak_working_set_bytes=peak,
                    )
                    save()
                    print(json.dumps(report), flush=True)
                    os._exit(72)  # Only this dedicated probe process.
            time.sleep(0.25)

    save()
    print(json.dumps({"phase": report["phase"], "pid": os.getpid()}), flush=True)
    threading.Thread(target=guard, daemon=True).start()
    try:
        bundle = build_production_data(SQLiteSource(path), source_snapshot_as_of=cutoff)
        with lock:
            report["checkpoints"].append(
                {
                    "phase": "source-context",
                    "daily_rows": len(bundle.daily),
                    "financial_rows": len(bundle.financials),
                    "universe_rows": len(bundle.universe),
                    "market_rows": len(bundle.market_context),
                    "sector_rows": len(bundle.sector_context),
                    "elapsed_seconds": time.perf_counter() - started,
                    "peak_working_set_bytes": memory_bytes()[1],
                }
            )
            report["phase"] = "features"
            save()
        engine = FeatureEngine(V2_EXTENDED_MANIFEST)
        function = engine.transform if args.reference_history else engine.latest_snapshot
        values = function(
            bundle.daily,
            bundle.market_context,
            bundle.sector_context,
            financials=bundle.financials,
            as_of=cutoff,
        )
        if args.reference_history:
            values = values.groupby("symbol", sort=True).tail(1).reset_index(drop=True)
        assert values.symbol.nunique() == len(values) == capacity["symbols"]
        assert digest(path) == before, "Synthetic source was modified"
        feature_digest = hashlib.sha256(values.to_json(orient="table").encode()).hexdigest()
        current, peak = memory_bytes()
        with lock:
            report.update(
                status="passed",
                feature_rows=len(values),
                feature_columns=len(values.columns),
                current_working_set_bytes=current,
                peak_working_set_bytes=peak,
                feature_json_sha256=feature_digest,
            )
            if (
                peak > report["working_set_abort_bytes"]
                or time.perf_counter() - started > args.seconds
            ):
                report.update(status="budget-exceeded", reason="final-budget-check")
    except Exception as error:
        with lock:
            report.update(status="failed", error_type=type(error).__name__, code=str(error))
    with lock:
        save()
        print(json.dumps(report), flush=True)
    if report["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
