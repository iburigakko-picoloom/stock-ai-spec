"""Versioned, compressed SQLite batches using the exact PC validation/normalization."""

from __future__ import annotations

import hashlib
import io
import json
import re
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
        db.execute("BEGIN IMMEDIATE")
        # v1 keyed observations only by content. Preserve a later observation
        # when a corrected value returns to an earlier value (A -> B -> A).
        existing = db.execute("PRAGMA table_info(market_batches)").fetchall()
        migrate = bool(existing) and "sequence" not in {row[1] for row in existing}
        if migrate:
            db.execute("ALTER TABLE market_batches RENAME TO market_batches_v1")
        db.execute(
            "CREATE TABLE IF NOT EXISTS market_batches("
            "sequence INTEGER PRIMARY KEY,dataset TEXT NOT NULL, "
            "day TEXT NOT NULL, received_at TEXT NOT NULL, "
            "payload_hash TEXT NOT NULL, raw BLOB NOT NULL, normalized BLOB NOT NULL, "
            "normalized_hash TEXT NOT NULL, UNIQUE(dataset,day,received_at,payload_hash))"
        )
        if migrate:
            db.execute(
                "INSERT INTO market_batches(dataset,day,received_at,payload_hash,raw,"
                "normalized,normalized_hash) SELECT dataset,day,received_at,payload_hash,"
                "raw,normalized,normalized_hash FROM market_batches_v1 ORDER BY rowid"
            )
            db.execute("DROP TABLE market_batches_v1")
        db.execute(
            "CREATE INDEX IF NOT EXISTS market_batch_lookup "
            "ON market_batches(dataset,day,received_at,sequence)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS market_days("
            "day TEXT PRIMARY KEY, received_at TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS market_valuations("
            "sequence INTEGER PRIMARY KEY,day TEXT NOT NULL,received_at TEXT NOT NULL,"
            "payload_hash TEXT NOT NULL,raw BLOB NOT NULL,UNIQUE(day,received_at,payload_hash))"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS market_valuation_lookup "
            "ON market_valuations(day,received_at,sequence)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS market_download_plan("
            "id INTEGER PRIMARY KEY CHECK(id=1),first_day TEXT NOT NULL,last_day TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS market_acquisitions("
            "id TEXT PRIMARY KEY,day TEXT NOT NULL,content_hash TEXT NOT NULL,"
            "source_pages TEXT NOT NULL)"
        )


def plan(path: Path, payload: dict | None = None) -> dict | None:
    with sqlite3.connect(path) as db:
        if payload is not None:
            first, last = date.fromisoformat(payload["first_day"]), date.fromisoformat(
                payload["last_day"]
            )
            today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
            if first > last or last >= today or (last - first).days > 730:
                raise ValueError("Closed source dates within a two-year mobile range required")
            db.execute("INSERT OR REPLACE INTO market_download_plan VALUES(1,?,?)",
                       (str(first), str(last)))
        row = db.execute(
            "SELECT first_day,last_day FROM market_download_plan WHERE id=1"
        ).fetchone()
    return None if row is None else {"first_day": row[0], "last_day": row[1]}


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
    valuation_batch = None
    if "valuations" in payload:
        from .universe import validate_valuations

        rows = tuple(payload["valuations"])
        validate_valuations(rows, day)
        valuation_batch = (
            str(day), received.isoformat(timespec="microseconds"), canonical_payload_hash(rows),
            zlib.compress(json.dumps(rows, allow_nan=False).encode()),
        )
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
                received.isoformat(timespec="microseconds"),
                digest,
                zlib.compress(json.dumps(rows, allow_nan=False).encode()),
                zlib.compress(normalized),
                hashlib.sha256(normalized).hexdigest(),
            )
        )
    with sqlite3.connect(path) as db:
        # Publish a day only after every dataset passes. The previous good day
        # remains the latest if any endpoint returns 403 or fails validation.
        if "acquisitionId" in payload:
            acquisition = payload["acquisitionId"]
            if not isinstance(acquisition, str) or not re.fullmatch(
                r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", acquisition
            ):
                raise ValueError("Invalid acquisition receipt")
            pages = payload["source_pages"]
            expected_rows = {name: len(rows) for name, rows in payload["datasets"].items()}
            expected_rows["valuations"] = len(payload["valuations"])
            counts, numbers = dict.fromkeys(expected_rows, 0), dict.fromkeys(expected_rows, 0)
            if not isinstance(pages, list) or not 1 <= len(pages) <= 600:
                raise ValueError("Invalid source page manifest")
            for page in pages:
                name = page["dataset"]
                stamp = datetime.fromisoformat(page["received_at"])
                if (name not in counts or not stamp.tzinfo or stamp > received
                        or type(page["page"]) is not int or page["page"] != numbers[name]
                        or type(page["row_count"]) is not int or page["row_count"] < 0
                        or not isinstance(page["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", page["sha256"])):
                    raise ValueError("Invalid source page receipt")
                numbers[name] += 1
                counts[name] += page["row_count"]
            if counts != expected_rows:
                raise ValueError("Source page row count mismatch")
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
            identity = (str(day), digest.hexdigest())
            previous = db.execute(
                "SELECT day,content_hash FROM market_acquisitions WHERE id=?", (acquisition,)
            ).fetchone()
            if previous is not None and previous != identity:
                raise ValueError("Acquisition receipt changed")
            db.execute("INSERT OR IGNORE INTO market_acquisitions VALUES(?,?,?,?)",
                       (acquisition, *identity, json.dumps(pages, sort_keys=True)))
        db.executemany(
            "INSERT OR IGNORE INTO market_batches(dataset,day,received_at,payload_hash,raw,"
            "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)", batches
        )
        if valuation_batch is not None:
            db.execute(
                "INSERT OR IGNORE INTO market_valuations(day,received_at,payload_hash,raw) "
                "VALUES(?,?,?,?)", valuation_batch
            )
        db.execute(
            "INSERT OR REPLACE INTO market_days VALUES(?,?)", (str(day), received.isoformat())
        )
    return status(path)


def status(path: Path) -> dict:
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT MAX(day),COUNT(*) FROM market_days").fetchone()
        completed = [item[0] for item in db.execute("SELECT day FROM market_days ORDER BY day")]
        receipts = [{"date": day, "acquisitionId": identity} for day, identity in db.execute(
            "SELECT day,id FROM market_acquisitions ORDER BY day,id"
        )]
    return {
        "latest_data_date": row[0],
        "completed_days": row[1],
        "research_only": True,
        "latest_forecast_available": False,
        "model_adopted": False,
        "completed_dates": completed,
        "committed_acquisitions": receipts,
    }


class SQLiteSource:
    def __init__(self, path: Path):
        self.path = path

    def point_in_time(self, dataset: DatasetName, as_of: datetime) -> pd.DataFrame:
        if not as_of.tzinfo:
            raise ValueError("Aware cutoff required")
        parts = []
        total = 0
        with sqlite3.connect(self.path) as db:
            # Each endpoint response is a complete daily snapshot. A correction
            # that removes a row must not resurrect it from an older response.
            rows = db.execute(
                "WITH versions AS (SELECT sequence,normalized,normalized_hash,"
                "received_at,payload_hash,ROW_NUMBER() OVER("
                "PARTITION BY day ORDER BY received_at DESC,sequence DESC) n "
                "FROM market_batches WHERE dataset=? AND received_at<=?) "
                "SELECT normalized,normalized_hash,sequence FROM versions WHERE n=1 "
                "ORDER BY received_at,sequence",
                (dataset.value, as_of.astimezone(UTC).isoformat(timespec="microseconds")),
            )
            for content, expected, sequence in rows:
                decoded = zlib.decompress(content)
                if hashlib.sha256(decoded).hexdigest() != expected:
                    raise ValueError("Stored normalized data changed")
                frame = pd.read_json(io.BytesIO(decoded), orient="table")
                total += len(frame)
                if total > 1_500_000:
                    raise ValueError(
                        "MOBILE_MEMORY_LIMIT: input is too large for the mobile worker"
                    )
                if not frame.empty:
                    frame["_observation_order"] = sequence
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
        frame = frame.sort_values(
            ["available_at", "received_at", "_observation_order", "payload_hash"]
        ).drop_duplicates(keys, keep="last")
        return frame.drop(columns="_observation_order").sort_values(keys).reset_index(drop=True)


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
