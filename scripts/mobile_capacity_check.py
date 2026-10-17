"""Synthetic storage probe only: no API, training, holdout or production state."""

from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import io
import json
import random
import re
import time
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from mobile.python import market, runtime

from stock_ai.data.contracts import DatasetName

ROOT = Path(__file__).resolve().parents[1]


def make_payload(day, session, count, rng):
    stamp = day.isoformat()
    datasets = {kind.value: [] for kind in DatasetName}
    for index in range(count):
        code = f"{1000 + index:04d}0"
        name = hashlib.sha256(str(index).encode()).hexdigest()[:12]
        datasets["security_master"].append(
            {
                "Date": stamp,
                "Code": code,
                "CoName": "synthetic-" + name,
                "CoNameEn": "synthetic-" + name,
                "S17": "10",
                "S17Nm": "synthetic",
                "S33": "3700",
                "S33Nm": "synthetic",
                "ScaleCat": "TOPIX Small 2",
                "Mkt": "0111",
                "MktNm": "synthetic",
                "Mrgn": "1",
                "MrgnNm": "synthetic",
            }
        )
        opened = round(100 + index % 1000 + rng.random() * 30, 2)
        closed = round(opened * (0.98 + rng.random() * 0.04), 2)
        high = round(max(opened, closed) + rng.random() * 4, 2)
        low = round(min(opened, closed) - rng.random() * 4, 2)
        volume = 100 * rng.randint(100, 10000)
        datasets["daily_prices"].append(
            {
                "Date": stamp,
                "Code": code,
                "O": opened,
                "H": high,
                "L": low,
                "C": closed,
                "Vo": volume,
                "Va": round(volume * closed, 2),
                "AdjFactor": 1,
                "AdjO": opened,
                "AdjH": high,
                "AdjL": low,
                "AdjC": closed,
                "AdjVo": volume,
            }
        )
        if index % 63 == session % 63:
            datasets["financial_summary"].append(
                {
                    "DiscDate": stamp,
                    "DiscTime": "15:00:00",
                    "Code": code,
                    "DiscNo": f"{session:04d}{index:05d}",
                    "DocType": "synthetic",
                    "CurPerType": "FY",
                    "CurPerSt": "2023-01-01",
                    "CurPerEn": "2023-12-31",
                    "Sales": 1000000 + index * 1000,
                    "OP": 100000 + index * 100,
                    "NP": 50000 + index * 100,
                    "EPS": round(20 + rng.random() * 100, 2),
                    "TA": 10000000 + index * 100,
                    "Eq": 5000000 + index * 100,
                    "ShOutFY": 1000000 + index * 100,
                    "TrShFY": 0,
                }
            )
    datasets["trading_calendar"] = [{"Date": stamp, "HolDiv": "1"}]
    datasets["topix"] = [{"Date": stamp, "O": 2000, "H": 2010, "L": 1990, "C": 2001}]
    valuations = [
        {
            "Date": stamp,
            "Code": f"{1000 + index:04d}0",
            "MktCap": round(30000 + rng.random() * 1000000, 2),
        }
        for index in range(count)
    ]
    received = (
        datetime.combine(day, datetime.min.time(), UTC) + timedelta(days=1, hours=8)
    ).isoformat()
    pages = [
        {
            "dataset": key,
            "page": 0,
            "row_count": len(rows),
            "received_at": received,
            "sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest(),
        }
        for key, rows in {**datasets, "valuations": valuations}.items()
    ]
    return {
        "date": stamp,
        "received_at": received,
        "datasets": datasets,
        "valuations": valuations,
        "source_pages": pages,
        "acquisitionId": str(uuid.uuid5(uuid.NAMESPACE_URL, "stockai-synthetic-capacity:" + stamp)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", type=int, default=5000)
    parser.add_argument("--sessions", type=int, default=300)
    parser.add_argument("--checkpoint", type=int, default=30)
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        raise ValueError("Run this verification module from the repository root")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".demo-artifacts") or output == ROOT / ".demo-artifacts":
        raise ValueError("Probe output must be a fresh isolated .demo-artifacts subdirectory")
    if not 1 <= args.symbols <= 5000 or not 1 <= args.sessions <= 300 or args.checkpoint < 1:
        raise ValueError("Bounded synthetic storage dimensions required")
    output.mkdir(parents=True, exist_ok=False)
    runtime.STATE = output
    runtime.initialize()
    native = (ROOT / "web/android/app/src/main/java/jp/stockai/app/LocalStateStore.java").read_text(
        encoding="utf-8"
    )
    matched = re.search(r"MAX_CHARACTERS = (\d+) \* 1024 \* 1024", native)
    if matched is None:
        raise ValueError("Native payload policy must be inspected before this probe")
    report = {
        "synthetic_only": True,
        "scope": "PC ingestion/export/restore capacity, not phone performance",
        "symbols": args.symbols,
        "requested_sessions": args.sessions,
        "seed": 20261017,
        "native_max_base64_characters": int(matched[1]) * 1024 * 1024,
        "restore_max_sqlite_bytes": runtime.MAX_DATABASE_BYTES,
        "export_policy": "checkpoint exports only; not every Android commit",
        "encrypted_native_write_measured": False,
        "phone_performance_measured": False,
        "calendar": "synthetic weekdays, not the Japanese exchange calendar",
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "mobile/python/market.py",
                "mobile/python/market_codec.py",
                "mobile/python/runtime.py",
                "mobile/python/universe.py",
                "mobile/python/decision_market.py",
                "src/stock_ai/data/normalize.py",
                "scripts/mobile_capacity_check.py",
                "web/android/app/src/main/java/jp/stockai/app/LocalStateStore.java",
            )
        },
        "checkpoints": [],
        "status": "running",
    }
    rng = random.Random(20261017)
    day = date(2024, 1, 2)
    started = time.perf_counter()
    encoded = ""
    for session in range(args.sessions):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        tick = time.perf_counter()
        value = make_payload(day, session, args.symbols, rng)
        market.ingest(output / "mobile.sqlite3", value)
        del value
        gc.collect()
        completed = session + 1
        if completed == 1 or completed % args.checkpoint == 0 or completed == args.sessions:
            export_started = time.perf_counter()
            encoded = runtime.export_state()
            export_seconds = time.perf_counter() - export_started
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded))) as archive:
                sizes = {entry.filename: entry.file_size for entry in archive.infolist()}
            row = {
                "sessions": completed,
                "rows_per_full_dataset": completed * args.symbols,
                "last_ingest_and_generation_seconds": export_started - tick,
                "export_seconds": export_seconds,
                "base64_characters": len(encoded),
                "sqlite_bytes": sizes,
                "elapsed_seconds": time.perf_counter() - started,
                "fits_native_payload_limit": len(encoded) <= report["native_max_base64_characters"],
                "fits_restore_limit": max(sizes.values()) <= report["restore_max_sqlite_bytes"],
            }
            report["checkpoints"].append(row)
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(row), flush=True)
            if not row["fits_native_payload_limit"] or not row["fits_restore_limit"]:
                break
        day += timedelta(days=1)
    probe = output / "restore-probe"
    runtime.STATE = probe
    restore_started = time.perf_counter()
    try:
        runtime.initialize(encoded)
        count = market.status(probe / "mobile.sqlite3")["completed_days"]
        assert count == completed
        report["restore"] = {"status": "passed", "completed_days": count}
    except Exception as error:
        report["restore"] = {
            "status": "failed",
            "error_type": type(error).__name__,
            "code": str(error),
        }
    report["restore"]["seconds"] = time.perf_counter() - restore_started
    final = report["checkpoints"][-1]
    report["status"] = (
        "passed"
        if completed == args.sessions
        and final["fits_native_payload_limit"]
        and final["fits_restore_limit"]
        and report["restore"]["status"] == "passed"
        else "capacity-exceeded"
    )
    if report["restore"]["status"] != "passed":
        report["status"] = "restore-failed"
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "completed_sessions": completed,
                "restore": report["restore"],
            }
        ),
        flush=True,
    )
    if report["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
