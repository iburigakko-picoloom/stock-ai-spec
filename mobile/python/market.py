"""Versioned, compressed SQLite batches using the exact PC validation/normalization."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zlib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_ai.data.contracts import ENDPOINT_SCHEMAS, DatasetName, FetchedPayload
from stock_ai.data.normalize import canonical_payload_hash, normalize_payload
from stock_ai.data.production import build_production_data
from stock_ai.data.quality import require_quality, validate_rows


def initialize(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS market_batches("
            "dataset TEXT NOT NULL, day TEXT NOT NULL, received_at TEXT NOT NULL, "
            "payload_hash TEXT NOT NULL, raw BLOB NOT NULL, normalized BLOB NOT NULL, "
            "normalized_hash TEXT NOT NULL, PRIMARY KEY(dataset,day,payload_hash))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS market_days("
            "day TEXT PRIMARY KEY, received_at TEXT NOT NULL)"
        )


def ingest(path: Path, payload: dict) -> dict:
    day = date.fromisoformat(payload["date"])
    received = datetime.fromisoformat(payload["received_at"]).astimezone(UTC)
    if (
        not datetime.fromisoformat(payload["received_at"]).tzinfo
        or day > received.astimezone(ZoneInfo("Asia/Tokyo")).date()
    ):
        raise ValueError("Invalid source/receipt date")
    if set(payload["datasets"]) != {dataset.value for dataset in DatasetName}:
        raise ValueError("Incomplete acquisition")
    calendars = payload["datasets"]["trading_calendar"]
    calendar = [row for row in calendars if row.get("Date") == str(day)]
    if len(calendar) != 1 or len(calendars) > 22:
        raise ValueError("Missing exact calendar day")
    if str(calendar[0].get("HolDiv")) in ("1", "2") and any(
        not payload["datasets"][key] for key in ("security_master", "daily_prices", "topix")
    ):
        raise ValueError("Missing business-day inputs")
    batches = []
    for dataset in DatasetName:
        rows = tuple(payload["datasets"][dataset.value])
        if dataset is DatasetName.TRADING_CALENDAR:
            for row in rows:
                selected = date.fromisoformat(row["Date"])
                if not day <= selected <= day + timedelta(days=21):
                    raise ValueError("Calendar range mismatch")
                require_quality(validate_rows(dataset, (row,), requested_source_date=selected))
        else:
            require_quality(validate_rows(dataset, rows, requested_source_date=day))
        schema = ENDPOINT_SCHEMAS[dataset]
        digest = canonical_payload_hash(rows)
        fetched = FetchedPayload(
            dataset=dataset,
            endpoint=schema.endpoint,
            query=(("date", str(day)),),
            requested_at=received,
            received_at=received,
            pages=1,
            rows=rows,
        )
        frame = normalize_payload(
            fetched,
            ingestion_run_id="mobile-" + digest,
            as_of=received,
            payload_hash=digest,
            raw_object_id=digest,
        )
        normalized = frame.to_json(orient="table", date_format="iso").encode()
        batches.append(
            (
                dataset.value,
                str(day),
                received.isoformat(),
                digest,
                zlib.compress(json.dumps(rows, allow_nan=False).encode()),
                zlib.compress(normalized),
                hashlib.sha256(normalized).hexdigest(),
            )
        )
    with sqlite3.connect(path) as db:
        # Publish a day only after every dataset passes. The previous good day
        # remains the latest if any endpoint returns 403 or fails validation.
        db.executemany("INSERT OR IGNORE INTO market_batches VALUES(?,?,?,?,?,?,?)", batches)
        db.execute(
            "INSERT OR REPLACE INTO market_days VALUES(?,?)", (str(day), received.isoformat())
        )
    return status(path)


def status(path: Path) -> dict:
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT MAX(day),COUNT(*) FROM market_days").fetchone()
        completed = [item[0] for item in db.execute("SELECT day FROM market_days ORDER BY day")]
    return {
        "latest_data_date": row[0],
        "completed_days": row[1],
        "research_only": True,
        "latest_forecast_available": False,
        "model_adopted": False,
        "completed_dates": completed,
    }


class SQLiteSource:
    def __init__(self, path: Path):
        self.path = path

    def point_in_time(self, dataset: DatasetName, as_of: datetime) -> pd.DataFrame:
        if not as_of.tzinfo:
            raise ValueError("Aware cutoff required")
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT normalized,normalized_hash FROM market_batches "
                "WHERE dataset=? AND received_at<=? ORDER BY received_at,payload_hash",
                (dataset.value, as_of.astimezone(UTC).isoformat()),
            ).fetchall()
        parts = []
        total = 0
        for content, expected in rows:
            decoded = zlib.decompress(content)
            if hashlib.sha256(decoded).hexdigest() != expected:
                raise ValueError("Stored normalized data changed")
            frame = pd.read_json(io.BytesIO(decoded), orient="table")
            total += len(frame)
            if total > 1_500_000:
                raise ValueError("MOBILE_MEMORY_LIMIT: input is too large for the mobile worker")
            if not frame.empty:
                parts.append(frame)
        if not parts:
            return pd.DataFrame()
        frame = pd.concat(parts, ignore_index=True)
        keys = {
            DatasetName.SECURITY_MASTER: ["effective_date", "provider_code"],
            DatasetName.DAILY_PRICES: ["trading_date", "provider_code"],
            DatasetName.TRADING_CALENDAR: ["trading_date"],
            DatasetName.TOPIX: ["trading_date"],
            DatasetName.FINANCIAL_SUMMARY: ["disclosure_number"],
        }[dataset]
        frame = frame.sort_values(["available_at", "received_at", "payload_hash"]).drop_duplicates(
            keys, keep="last"
        )
        return frame.sort_values(keys).reset_index(drop=True)


def feature_inputs(path: Path, as_of: datetime) -> dict:
    cutoff = datetime.combine(
        as_of.astimezone(ZoneInfo("Asia/Tokyo")).date(), time(11, 30), ZoneInfo("Asia/Tokyo")
    )
    if as_of < cutoff:
        raise ValueError("11:30 input cutoff is not closed")
    bundle = build_production_data(
        SQLiteSource(path), source_snapshot_as_of=cutoff, proposal_as_of=cutoff
    )
    return {
        "as_of": cutoff.isoformat(),
        **{
            key: json.loads(frame.to_json(orient="records", date_format="iso"))
            for key, frame in [
                ("daily", bundle.daily),
                ("market", bundle.market_context),
                ("sector", bundle.sector_context),
                ("financials", bundle.financials),
            ]
        },
    }
