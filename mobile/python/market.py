"""Versioned, compressed SQLite batches using the exact PC validation/normalization."""

from __future__ import annotations

import hashlib
import json
import re
import weakref
from collections import OrderedDict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo

import pandas as pd

from stock_ai.data.contracts import ENDPOINT_SCHEMAS, DatasetName, FetchedPayload
from stock_ai.data.normalize import canonical_payload_hash, normalize_payload
from stock_ai.data.production import _source_frame_id, _source_row_hashes, build_production_data
from stock_ai.data.quality import require_quality, validate_rows

from . import checkpoints, market_codec
from .features import model_input_frame
from .storage import connect


def initialize(path: Path) -> None:
    with connect(path) as db:
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
        market_codec.initialize(db)


def plan(path: Path, payload: dict | None = None) -> dict | None:
    with connect(path) as db:
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


def receipt_time(value: str) -> datetime:
    """Round sub-microsecond native receipt precision forward, never backward."""
    if not isinstance(value, str):
        raise ValueError("Invalid receipt time")
    match = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d{1,9}))?(?:Z|[+-]\d{2}:\d{2})",
        value,
    )
    if match is None:
        raise ValueError("Aware ISO receipt time required")
    instant = datetime.fromisoformat(value)
    fraction = match.group(1) or ""
    if len(fraction) > 6 and any(char != "0" for char in fraction[6:]):
        instant += timedelta(microseconds=1)
    return instant


def receipt_identity(payload: dict, expected_rows: dict, received: datetime):
    acquisition = payload["acquisitionId"]
    if not isinstance(acquisition, str) or not re.fullmatch(
        r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", acquisition
    ):
        raise ValueError("Invalid acquisition receipt")
    pages = payload["source_pages"]
    counts, numbers = dict.fromkeys(expected_rows, 0), dict.fromkeys(expected_rows, 0)
    if not isinstance(pages, list) or not 1 <= len(pages) <= 600:
        raise ValueError("Invalid source page manifest")
    for page in pages:
        name = page["dataset"]
        stamp = receipt_time(page["received_at"])
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
    return acquisition, digest.hexdigest(), pages


def ingest(path: Path, payload: dict) -> dict:
    day = date.fromisoformat(payload["date"])
    received = receipt_time(payload["received_at"]).astimezone(UTC)
    if day > received.astimezone(ZoneInfo("Asia/Tokyo")).date():
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
            rows,
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
                rows,
                normalized,
                hashlib.sha256(normalized).hexdigest(),
            )
        )
    with connect(path) as db:
        # Publish a day only after every dataset passes. The previous good day
        # remains the latest if any endpoint returns 403 or fails validation.
        if "acquisitionId" in payload:
            expected_rows = {name: len(rows) for name, rows in payload["datasets"].items()}
            expected_rows["valuations"] = len(payload["valuations"])
            acquisition, receipt_hash, pages = receipt_identity(payload, expected_rows, received)
            identity = (str(day), receipt_hash)
            previous = db.execute(
                "SELECT day,content_hash FROM market_acquisitions WHERE id=?", (acquisition,)
            ).fetchone()
            if previous is not None and previous != identity:
                raise ValueError("Acquisition receipt changed")
            db.execute("INSERT OR IGNORE INTO market_acquisitions VALUES(?,?,?,?)",
                       (acquisition, *identity, json.dumps(pages, sort_keys=True)))
        for dataset, source_day, receipt, digest, records, normalized, normalized_hash in batches:
            raw = market_codec.pack_records(db, records)
            compact = market_codec.pack_table(db, normalized, records)
            db.execute(
                "INSERT OR IGNORE INTO market_batches(dataset,day,received_at,payload_hash,raw,"
                "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)",
                (dataset, source_day, receipt, digest, raw, compact, normalized_hash),
            )
        if valuation_batch is not None:
            db.execute(
                "INSERT OR IGNORE INTO market_valuations(day,received_at,payload_hash,raw) "
                "VALUES(?,?,?,?)",
                (*valuation_batch[:3], market_codec.pack_records(db, valuation_batch[3])),
            )
        db.execute(
            "INSERT OR REPLACE INTO market_days VALUES(?,?)", (str(day), received.isoformat())
        )
    return status(path)


def status(path: Path) -> dict:
    with connect(path) as db:
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


def compact_legacy(path: Path, budget: int = 5) -> int:
    """Bounded, transactional repacking; observation identities/hashes stay fixed."""
    if not 1 <= budget <= 20:
        raise ValueError("Invalid market compaction budget")
    with connect(path) as db:
        # Zero freed legacy blobs so the next capsule does not retain their
        # obsolete physical copies. SQLite can reuse these pages on later days.
        db.execute("PRAGMA secure_delete=ON")
        db.execute("BEGIN IMMEDIATE")
        state = db.execute(
            "SELECT sequence,valuation_sequence FROM market_compaction WHERE id=1"
        ).fetchone()
        sequence, valuation_sequence = state or (0, 0)
        prefix_length = len(market_codec.PREFIX)
        rows = db.execute(
            "SELECT sequence,payload_hash,raw,normalized,normalized_hash FROM market_batches "
            "WHERE sequence>? AND (substr(raw,1,?)<>? OR substr(normalized,1,?)<>?) "
            "ORDER BY sequence LIMIT ?",
            (sequence, prefix_length, market_codec.PREFIX,
             prefix_length, market_codec.PREFIX, budget),
        ).fetchall()
        for sequence, digest, raw, normalized, expected in rows:
            records = market_codec.records(db, raw)
            if canonical_payload_hash(tuple(records)) != digest:
                raise ValueError("Stored raw data changed")
            decoded = market_codec.table(db, normalized, raw, expected)
            db.execute("UPDATE market_batches SET raw=?,normalized=? WHERE sequence=?", (
                market_codec.pack_records(db, records),
                market_codec.pack_table(db, decoded, records), sequence,
            ))
        valuations = db.execute(
            "SELECT sequence,payload_hash,raw FROM market_valuations "
            "WHERE sequence>? AND substr(raw,1,?)<>? ORDER BY sequence LIMIT ?",
            (valuation_sequence, prefix_length, market_codec.PREFIX, budget - len(rows)),
        ).fetchall()
        for valuation_sequence, digest, raw in valuations:
            records = market_codec.records(db, raw)
            if canonical_payload_hash(tuple(records)) != digest:
                raise ValueError("Stored valuation data changed")
            db.execute("UPDATE market_valuations SET raw=? WHERE sequence=?",
                       (market_codec.pack_records(db, records), valuation_sequence))
        db.execute("INSERT OR REPLACE INTO market_compaction VALUES(1,?,?)",
                   (sequence, valuation_sequence))
    return len(rows) + len(valuations)


def _daily_snapshots(db, dataset, as_of, *, descending=False, first_day=None):
    return db.execute(
        "WITH versions AS (SELECT sequence,day,raw,normalized,normalized_hash,"
        "ROW_NUMBER() OVER(PARTITION BY day ORDER BY received_at DESC,sequence DESC) n "
        "FROM market_batches WHERE dataset=? AND received_at<=? AND (? IS NULL OR day>=?)) "
        "SELECT sequence,day,raw,normalized,normalized_hash FROM versions WHERE n=1 "
        + ("ORDER BY day DESC" if descending else "ORDER BY day"),
        (dataset.value, as_of.astimezone(UTC).isoformat(timespec="microseconds"),
         first_day, first_day),
    )


def _mixed_datetime_casts(parts):
    """Unify mixed bulk/API time representations without changing old snapshots.

    Bulk dates can be stored as datetime64 while API date objects round-trip as
    ISO strings. Mixed aware timezones otherwise become expensive object arrays.
    Preserve homogeneous schemas; only these mixed representations need casts.
    """
    casts = {}
    for name in dict.fromkeys(name for part in parts for name in part):
        dtypes = [part[name].dtype for part in parts if name in part]
        if all(isinstance(dtype, pd.DatetimeTZDtype) for dtype in dtypes):
            if len({str(dtype.tz) for dtype in dtypes}) > 1:
                casts[name] = pd.DatetimeTZDtype(unit="ns", tz="UTC")
        elif name in {"effective_date", "trading_date"}:
            dates = [pd.api.types.is_datetime64_dtype(dtype) for dtype in dtypes]
            if any(dates) and not all(dates) and all(
                date_dtype or pd.api.types.is_object_dtype(dtype)
                or isinstance(dtype, pd.StringDtype)
                for dtype, date_dtype in zip(dtypes, dates, strict=True)
            ):
                casts[name] = pd.api.types.pandas_dtype("datetime64[ns]")
    return casts


def _canonical_daily_part(frame, common, keys, sequence, day):
    if not frame.dtypes.equals(common):
        frame = frame.reindex(columns=common.index).astype(common.to_dict())
    if not pd.to_datetime(frame[keys[0]]).dt.date.astype(str).eq(day).all():
        raise ValueError("Stored daily source contains a different snapshot date")
    if frame.duplicated(keys).any():
        frame["_observation_order"] = sequence
        frame.sort_values(
            ["available_at", "received_at", "_observation_order", "payload_hash"], inplace=True
        )
        frame.drop_duplicates(keys, keep="last", inplace=True)
        frame.drop(columns="_observation_order", inplace=True)
    frame.sort_values(keys, inplace=True)
    return frame


class SQLiteSource:
    def __init__(self, path: Path):
        self.path = path

    def point_in_time(self, dataset: DatasetName, as_of: datetime) -> pd.DataFrame:
        if not as_of.tzinfo:
            raise ValueError("Aware cutoff required")
        parts = []
        cache = OrderedDict()
        total = 0
        with connect(self.path) as db:
            # Each endpoint response is a complete daily snapshot. A correction
            # that removes a row must not resurrect it from an older response.
            rows = db.execute(
                "WITH versions AS (SELECT sequence,raw,normalized,normalized_hash,"
                "received_at,payload_hash,ROW_NUMBER() OVER("
                "PARTITION BY day ORDER BY received_at DESC,sequence DESC) n "
                "FROM market_batches WHERE dataset=? AND received_at<=?) "
                "SELECT normalized,normalized_hash,sequence,raw FROM versions WHERE n=1 "
                "ORDER BY received_at,sequence",
                (dataset.value, as_of.astimezone(UTC).isoformat(timespec="microseconds")),
            )
            for content, expected, sequence, raw in rows:
                frame = market_codec.frame(db, content, raw, expected, cache)
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
        casts = _mixed_datetime_casts(parts)
        if casts:
            parts = [part.astype({name: dtype for name, dtype in casts.items() if name in part},
                                 copy=False) for part in parts]
        frame = pd.concat(parts, ignore_index=True)
        parts.clear()
        cache.clear()
        keys = {
            DatasetName.SECURITY_MASTER: ["effective_date", "provider_code"],
            DatasetName.DAILY_PRICES: ["trading_date", "provider_code"],
            DatasetName.TRADING_CALENDAR: ["trading_date"],
            DatasetName.TOPIX: ["trading_date"],
            DatasetName.FINANCIAL_SUMMARY: ["disclosure_number"],
        }[dataset]
        frame.sort_values(
            ["available_at", "received_at", "_observation_order", "payload_hash"], inplace=True
        )
        frame.drop_duplicates(keys, keep="last", inplace=True)
        frame.drop(columns="_observation_order", inplace=True)
        frame.sort_values(keys, inplace=True)
        frame.reset_index(drop=True, inplace=True)
        return frame

    def latest_closed_prices(self, as_of, *, reference_only=False):
        """The same latest common-issue rows, without assembling all historical prices."""
        if not as_of.tzinfo:
            raise ValueError("Aware cutoff required")
        kind = DatasetName.DAILY_PRICES
        cache, profiles = OrderedDict(), []
        local_day = as_of.astimezone(ZoneInfo("Asia/Tokyo")).date()
        with connect(self.path) as db:
            db.execute("BEGIN")
            common = None
            if not reference_only:
                for _, _, raw, normalized, expected in _daily_snapshots(db, kind, as_of):
                    frame = market_codec.frame(db, normalized, raw, expected, cache)
                    if not frame.empty:
                        profiles.append(market_codec.frame_profile(frame))
                if not profiles:
                    return pd.DataFrame()
                common = pd.concat(profiles, ignore_index=True).dtypes
                for name, dtype in _mixed_datetime_casts(profiles).items():
                    common[name] = dtype
            profiles.clear()
            for sequence, day, raw, normalized, expected in _daily_snapshots(
                db, kind, as_of, descending=True
            ):
                # Ledger references need verified source values, not the concat
                # dtype of unrelated history. Keep the feature reader unchanged.
                if reference_only and date.fromisoformat(day) >= local_day:
                    continue
                frame = market_codec.frame(db, normalized, raw, expected, cache)
                if frame.empty:
                    continue
                frame = _canonical_daily_part(
                    frame, frame.dtypes if common is None else common,
                    ["trading_date", "provider_code"], sequence, day
                )
                if date.fromisoformat(day) >= local_day:
                    continue
                frame = frame.loc[frame.provider_code.astype(str).str.fullmatch(r"[0-9A-Z]{4}0")]
                if not frame.empty:
                    return frame.reset_index(drop=True)
        return pd.DataFrame()


class FeatureSource(SQLiteSource):
    """Verify full daily sources in batches; retain only production input columns."""

    # Array retention budget, not an assertion about total process/phone memory.
    MAX_ARRAY_BYTES = 768 * 1024 * 1024
    MASTER_COLUMNS = frozenset({
        "effective_date", "provider_code", "symbol", "company_name", "sector_33_code",
        "sector_33_name", "market_code", "market_name", "available_at",
    })
    PRICE_COLUMNS = frozenset({
        "trading_date", "provider_code", "symbol", "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_volume", "trading_value", "adjustment_factor", "research_open", "research_high",
        "research_low", "research_close", "research_volume", "ex_rights_type", "adjustment_source",
        "adjustment_version", "available_at",
    })
    KEYS: ClassVar[dict[DatasetName, list[str]]] = {
        DatasetName.SECURITY_MASTER: ["effective_date", "provider_code"],
        DatasetName.DAILY_PRICES: ["trading_date", "provider_code"],
    }

    def __init__(self, path, *, first_day=None, verified_day=None, common_schemas=None,
                 context_only=False):
        super().__init__(path)
        self._identities = {}
        self._retained = []
        self.first_day = first_day
        self.verified_day = verified_day
        self.common_schemas = common_schemas or {}
        self.context_only = context_only
        self.shared_frames = {}

    def point_in_time(self, dataset, as_of):
        if dataset not in self.KEYS:
            frame = super().point_in_time(dataset, as_of)
            if self.context_only:
                # Only small shared sources, for reuse within this one build.
                # No large master/price frame is retained by the reader.
                self.shared_frames[dataset] = frame
            return frame
        if not as_of.tzinfo:
            raise ValueError("Aware cutoff required")
        cache, profiles, parts = OrderedDict(), [], []
        strings = {}
        self._retained = [item for item in self._retained if item[0]() is not None]
        retained = sum(item[1] for item in self._retained)
        array_bytes = 0
        projected_digest, projected_schema = None, None
        with connect(self.path) as db:
            # Both passes must observe the same immutable selection, even if a
            # separate connection receives a correction during the read.
            db.execute("BEGIN")
            for sequence, day, raw, normalized, expected in _daily_snapshots(
                db, dataset, as_of, first_day=self.first_day
            ):
                profile = checkpoints.source_part(
                    ["profile", dataset.value, sequence, expected],
                    "profile:" + dataset.value + ":" + day,
                    lambda normalized=normalized, raw=raw, expected=expected:
                        market_codec.dtype_profile(db, normalized, raw, expected, cache),
                )
                if not profile.empty:
                    profiles.append(profile)
            if not profiles:
                self._identities.pop(dataset, None)
                return pd.DataFrame()
            common = pd.concat(profiles, ignore_index=True).dtypes
            for name, dtype in _mixed_datetime_casts(profiles).items():
                common[name] = dtype
            profiles.clear()
            if dataset.value in self.common_schemas:
                expected = pd.Series({name: pd.api.types.pandas_dtype(dtype)
                                      for name, dtype in self.common_schemas[dataset.value]})
                # A new schema can change old row hashes/dtypes. The caller must
                # rebuild its derived cache instead of mixing source identities.
                if set(common.index) != set(expected.index):
                    raise ValueError("INPUT_CACHE_SCHEMA_CHANGED")
                for name, dtype in common.items():
                    if dtype == expected[name]:
                        continue
                    dates = (name in {"effective_date", "trading_date"}
                             and pd.api.types.is_datetime64_dtype(expected[name]))
                    zones = (isinstance(dtype, pd.DatetimeTZDtype)
                             and isinstance(expected[name], pd.DatetimeTZDtype)
                             and str(expected[name].tz) == "UTC")
                    if not (dates or zones):
                        raise ValueError("INPUT_CACHE_SCHEMA_CHANGED")
                common = expected
            schema = tuple((str(name), str(dtype)) for name, dtype in common.items())
            metadata = json.dumps({"dataset": dataset.value, "schema": schema}, sort_keys=True)
            identity = hashlib.sha256(metadata.encode())
            keys = self.KEYS[dataset]
            for sequence, day, raw, normalized, expected in _daily_snapshots(
                db, dataset, as_of, first_day=self.first_day
            ):
                def verified_projection(normalized=normalized, raw=raw, expected=expected,
                                        sequence=sequence, day=day):
                    frame = market_codec.frame(db, normalized, raw, expected, cache)
                    if frame.empty:
                        return {"projected": frame, "hashes": ""}
                    frame = _canonical_daily_part(frame, common, keys, sequence, day)
                    columns = (self.MASTER_COLUMNS if dataset is DatasetName.SECURITY_MASTER
                               else self.PRICE_COLUMNS)
                    if self.context_only and dataset is DatasetName.SECURITY_MASTER:
                        columns = columns - {"company_name"}
                    return {
                        "projected": frame.loc[:, [name for name in frame
                                                  if name in columns]].copy(),
                        "hashes": _source_row_hashes(frame).tobytes().hex(),
                    }

                part = checkpoints.source_part(
                    ["verified", dataset.value, sequence, expected, schema, self.context_only],
                    "verified:" + dataset.value + ":" + day, verified_projection,
                )
                projected = part["projected"]
                row_hashes = bytes.fromhex(part["hashes"])
                identity.update(row_hashes)
                if self.verified_day is not None:
                    self.verified_day(dataset.value, day, schema, row_hashes)
                if projected.empty:
                    continue
                # Immutable text repeats across daily batches. Retain one
                # string per value instead of a new allocation for each day;
                # keep the exact values, nulls, dtype and full-source identity.
                for name in projected:
                    column = projected[name]
                    dtype = column.dtype
                    if not (pd.api.types.is_object_dtype(dtype) or (
                        isinstance(dtype, pd.StringDtype) and dtype.storage == "python"
                    )):
                        continue
                    pool = strings.setdefault(name, {})
                    values = column.to_numpy(copy=True)
                    for index, value in enumerate(values):
                        if type(value) is str:
                            shared = pool.get(value)
                            if shared is not None:
                                values[index] = shared
                            elif len(pool) < 8192:
                                pool[value] = value
                    projected[name] = pd.Series(values, index=column.index, dtype=dtype)
                array_bytes += int(projected.memory_usage(index=True, deep=False).sum())
                if retained + array_bytes > self.MAX_ARRAY_BYTES:
                    raise ValueError("MOBILE_MEMORY_LIMIT: projected source arrays exceed budget")
                if projected_digest is None:
                    projected_schema = tuple(
                        (str(name), str(dtype)) for name, dtype in projected.dtypes.items()
                    )
                    header = json.dumps(
                        {"dataset": dataset.value, "schema": projected_schema}, sort_keys=True
                    )
                    projected_digest = hashlib.sha256(header.encode())
                projected_digest.update(_source_row_hashes(projected).tobytes())
                parts.append(projected)
        del projected, part
        cache.clear()
        result = pd.concat(parts, ignore_index=True)
        parts.clear()
        actual_schema = tuple((str(name), str(dtype)) for name, dtype in result.dtypes.items())
        if actual_schema != projected_schema:
            raise ValueError("Projected PIT schema changed while assembling its snapshot")
        frozen = projected_digest.hexdigest()
        self._identities[dataset] = (weakref.ref(result), identity.hexdigest(), frozen, array_bytes)
        self._retained.append((weakref.ref(result), array_bytes))
        return result

    def source_frame_id(self, dataset, frame):
        if dataset not in self.KEYS:
            return _source_frame_id(dataset, frame)
        frozen = self._identities.get(dataset)
        if (frozen is None or frozen[0]() is not frame
                or _source_frame_id(dataset, frame) != frozen[2]):
            raise ValueError("Projected PIT source changed after its full identity was frozen")
        return frozen[1]


def master_references(path: Path, cutoff: datetime) -> list[dict]:
    """Freeze raw observation identities without hashing runtime-dependent Pandas dtypes."""
    with connect(path) as db:
        rows = db.execute(
            "WITH versions AS (SELECT sequence,day,received_at,payload_hash,ROW_NUMBER() OVER("
            "PARTITION BY day ORDER BY received_at DESC,sequence DESC) n FROM market_batches "
            "WHERE dataset='security_master' AND day<=? AND received_at<=?) "
            "SELECT sequence,day,received_at,payload_hash FROM versions WHERE n=1 ORDER BY day",
            (cutoff.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat(),
             cutoff.astimezone(UTC).isoformat(timespec="microseconds")),
        ).fetchall()
    return [{"dataset": "security_master", "observation_id": row[0], "date": row[1],
             "received_at": row[2], "payload_hash": row[3]} for row in rows]


def feature_inputs(path: Path, as_of: datetime, as_frames: bool = False,
                   decision_symbols: list[str] | tuple[str, ...] | None = None,
                   preselected: bool = False, reference_only: bool = False) -> dict:
    # Keep full-market verification/context construction. Only the individual
    # model frames are projected before copying/JSON precision conversion.
    selected = None
    if decision_symbols is not None:
        if (not isinstance(decision_symbols, (list, tuple)) or not decision_symbols
                or any(type(symbol) is not str or not symbol for symbol in decision_symbols)
                or len(set(decision_symbols)) != len(decision_symbols)):
            raise ValueError("Invalid decision-symbol calculation scope")
        selected = frozenset(decision_symbols)
    cutoff = as_of if reference_only else datetime.combine(
        as_of.astimezone(ZoneInfo("Asia/Tokyo")).date(), time(11, 30), ZoneInfo("Asia/Tokyo")
    )
    if as_of < cutoff:
        raise ValueError("11:30 input cutoff is not closed")
    if preselected and not reference_only:
        if selected is None or not as_frames:
            raise ValueError("Preselection requires explicit frame calculation scope")
        from .input_cache import inputs

        return inputs(path, cutoff, selected)
    bundle = build_production_data(
        FeatureSource(path) if as_frames else SQLiteSource(path),
        source_snapshot_as_of=cutoff,
        **({"reference_as_of": cutoff} if reference_only else {"proposal_as_of": cutoff})
    )
    with connect(path) as db:
        latest_receipt = db.execute(
            "SELECT MAX(received_at) FROM market_batches WHERE received_at<=?",
            (cutoff.astimezone(UTC).isoformat(timespec="microseconds"),),
        ).fetchone()[0]
    if latest_receipt is None:
        raise ValueError("Source receipt missing")
    result = {
        "as_of": cutoff.isoformat(),
        "latest_source_received_at": latest_receipt,
        "source_snapshot_ids": list(bundle.source_snapshot_ids),
        "revision_policy": bundle.revision_policy.value,
    }
    if reference_only:
        result["reference_price_date"] = str(bundle.daily.trading_date.max().date())
    for key, frame in [("daily", bundle.daily), ("market", bundle.market_context),
                       ("sector", bundle.sector_context), ("financials", bundle.financials)]:
        if selected is not None and key in ("daily", "financials"):
            frame = frame.loc[frame.symbol.isin(selected)].reset_index(drop=True)
        result[key] = (model_input_frame(key, frame) if as_frames else
                       json.loads(frame.to_json(orient="records", date_format="iso")))
    if selected is not None:
        result["decision_symbols"] = sorted(selected)
    return result
