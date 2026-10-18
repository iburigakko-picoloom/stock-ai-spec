"""Prepare/verify only the synthetic full-market native capacity fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from mobile.python import market, models, runtime
from scripts.sqlite_evidence import table_snapshot as table_snapshot

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "synthetic-native-history-v1"
SOURCE_FILES = (
    "scripts/mobile_native_history_fixture.py",
    "scripts/sqlite_evidence.py",
    "scripts/android_history_check.py",
    "mobile/python/runtime.py",
    "mobile/python/market.py",
    "mobile/python/market_codec.py",
    "web/android/app/src/main/java/jp/stockai/app/LocalStateStore.java",
    "web/android/app/src/main/java/jp/stockai/app/LocalComputeOwner.java",
    "web/android/app/src/main/java/jp/stockai/app/ComputeHost.java",
    "web/android/app/src/androidTest/java/jp/stockai/app/FullHistoryCapacityTest.java",
    "web/src/mobile/compute-host.ts",
    "web/src/mobile/compute-worker.ts",
    "web/android/app/src/main/java/jp/stockai/app/PortableBackup.java",
    "web/android/app/src/main/java/jp/stockai/app/BackupCrypto.java",
    "web/android/app/build.gradle",
    "web/android/app/src/androidTest/java/jp/stockai/app/LocalComputeOwnerTest.java",
)
CAPACITY_SOURCES = (
    "mobile/python/market.py",
    "mobile/python/market_codec.py",
    "mobile/python/runtime.py",
    "mobile/python/universe.py",
    "mobile/python/decision_market.py",
    "src/stock_ai/data/normalize.py",
    "scripts/mobile_capacity_check.py",
    "web/android/app/src/main/java/jp/stockai/app/LocalStateStore.java",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def isolated(path: Path) -> Path:
    result = path.resolve()
    if not result.is_relative_to(ROOT / ".demo-artifacts") or result == ROOT / ".demo-artifacts":
        raise ValueError("Use an isolated .demo-artifacts directory")
    return result


def prepare(source: Path, output: Path) -> dict:
    source, output = isolated(source), isolated(output)
    capacity = json.loads((source / "report.json").read_text(encoding="utf-8"))
    if (
        capacity.get("synthetic_only") is not True
        or capacity.get("status") != "passed"
        or capacity.get("seed") != 20261017
        or capacity.get("symbols") != 5000
        or capacity.get("requested_sessions") != 520
        or capacity.get("receipt_mode") != "initial-download"
        or capacity.get("restore", {}).get("completed_days") != 520
    ):
        raise ValueError("A passed synthetic 5000-stock/520-session initial download is required")
    if set(capacity.get("source_sha256", {})) != set(CAPACITY_SOURCES):
        raise ValueError("Capacity source proof is incomplete")
    for name, expected in capacity["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Capacity source changed")
    output.mkdir(parents=True, exist_ok=False)
    original = {name: digest(source / name) for name in ("operations.sqlite3", "mobile.sqlite3")}
    work = output / "normalized-source"
    work.mkdir()
    for name in original:
        shutil.copy2(source / name, work / name)
    runtime.STATE = work
    runtime.initialize()
    model_status = models.status(work / "mobile.sqlite3", runtime._app.state.store)
    if model_status["imported_bundle_count"] != 0:
        raise ValueError("Synthetic native fixture must contain no model")
    reference = table_snapshot(work / "mobile.sqlite3")
    if len(reference["tables"]) != 17:
        raise ValueError("Unexpected synthetic mobile schema")
    encoded = runtime.export_state()
    if not 90_000_000 <= len(encoded) <= 128 * 1024 * 1024:
        raise ValueError("Unexpected full-history native capsule size")
    payload = output / "input.b64"
    payload.write_text(encoded, encoding="ascii")
    runtime.STATE = output / "roundtrip"
    runtime.initialize(encoded)
    if table_snapshot(runtime.STATE / "mobile.sqlite3") != reference:
        raise ValueError("Normalized fixture is not restore-idempotent")
    if market.status(runtime.STATE / "mobile.sqlite3")["completed_days"] != 520:
        raise ValueError("Restored history is incomplete")
    if original != {name: digest(source / name) for name in original}:
        raise ValueError("Capacity source was mutated")
    report = {
        "format": FORMAT,
        "synthetic_only": True,
        "status": "passed",
        "scope": "Normalized SQLite fixture; native owner/Java execution still required",
        "symbols": 5000,
        "sessions": 520,
        "models": 0,
        "characters": len(encoded),
        "payload_sha256": digest(payload),
        "capacity_report_sha256": digest(source / "report.json"),
        "original_databases_sha256": original,
        "mobile": reference,
        "source_sha256": {name: digest(ROOT / name) for name in SOURCE_FILES},
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        raise ValueError("Run from the repository root")
    report = prepare(args.source, args.output)
    print(json.dumps({key: report[key] for key in ("status", "characters", "payload_sha256")}))


if __name__ == "__main__":
    main()
