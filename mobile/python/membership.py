"""Current-day membership observations, isolated from historical feature inputs."""

from __future__ import annotations

import hashlib
import json
import zlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ai.data.contracts import DatasetName
from stock_ai.data.quality import require_quality, validate_rows

from .market import receipt_identity, receipt_time
from .storage import connect

JST = ZoneInfo("Asia/Tokyo")


def initialize(path: Path) -> None:
    with connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_membership("
            "sequence INTEGER PRIMARY KEY,acquisition_id TEXT NOT NULL UNIQUE,"
            "day TEXT NOT NULL,received_at TEXT NOT NULL,payload_hash TEXT NOT NULL,"
            "raw BLOB NOT NULL)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS membership_lookup "
            "ON mobile_membership(day,received_at,sequence)"
        )


def ingest(path: Path, payload: dict, now: datetime) -> dict:
    received = receipt_time(payload["received_at"])
    day = date.fromisoformat(payload["date"])
    if (now.tzinfo is None or received.tzinfo is None or received > now
            or day > received.astimezone(JST).date() or payload.get("purpose") != "membership"
            or payload.get("status") != 200):
        raise ValueError("Invalid membership observation")
    datasets = payload["datasets"]
    if set(datasets) != {"security_master", "trading_calendar"}:
        raise ValueError("Incomplete membership acquisition")
    master, calendar = datasets["security_master"], datasets["trading_calendar"]
    if (not isinstance(master, list) or not isinstance(calendar, list)
            or len(master) > 50000 or not 1 <= len(calendar) <= 22):
        raise ValueError("Invalid membership size")
    exact = []
    seen = set()
    for row in calendar:
        if not isinstance(row, dict):
            raise ValueError("Invalid calendar row")
        source = date.fromisoformat(row["Date"])
        if not day <= source <= day + timedelta(days=21) or source in seen:
            raise ValueError("Invalid calendar range")
        seen.add(source)
        require_quality(validate_rows(DatasetName.TRADING_CALENDAR, (row,),
                                      requested_source_date=source))
        if source == day:
            exact.append(row)
    if len(exact) != 1:
        raise ValueError("Exact membership calendar day required")
    business = str(exact[0]["HolDiv"]) in ("1", "2")
    if (not business and master) or (business and not master):
        raise ValueError("Calendar and master disagree")
    if any(not isinstance(row, dict) for row in master):
        raise ValueError("Invalid master row")
    require_quality(validate_rows(DatasetName.SECURITY_MASTER, tuple(master),
                                  requested_source_date=day))
    acquisition, digest, _ = receipt_identity(
        payload, {name: len(rows) for name, rows in datasets.items()}, received
    )
    content = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    if len(content) > 64 * 1024 * 1024:
        raise ValueError("Membership size limit")
    with connect(path) as db:
        previous = db.execute(
            "SELECT payload_hash FROM mobile_membership WHERE acquisition_id=?", (acquisition,)
        ).fetchone()
        if previous is not None and previous[0] != digest:
            raise ValueError("Membership acquisition changed")
        db.execute("INSERT OR IGNORE INTO mobile_membership VALUES(NULL,?,?,?,?,?)", (
            acquisition, str(day), received.astimezone(UTC).isoformat(timespec="microseconds"),
            digest, zlib.compress(content),
        ))
    return status(path, now)


def snapshot(path: Path, as_of: datetime) -> dict | None:
    if as_of.tzinfo is None:
        raise ValueError("Aware membership cutoff required")
    day = as_of.astimezone(JST).date()
    with connect(path) as db:
        row = db.execute(
            "SELECT acquisition_id,payload_hash,raw,received_at FROM mobile_membership "
            "WHERE day=? AND received_at<=? ORDER BY received_at DESC,sequence DESC LIMIT 1",
            (str(day), as_of.astimezone(UTC).isoformat(timespec="microseconds")),
        ).fetchone()
    if row is None:
        return None
    return _checked(row, day, as_of)


def reference(path: Path, acquisition_id: str, as_of: datetime) -> dict:
    """Read the exact frozen observation, including after a later correction."""
    if as_of.tzinfo is None:
        raise ValueError("Aware membership cutoff required")
    with connect(path) as db:
        row = db.execute(
            "SELECT acquisition_id,payload_hash,raw,received_at FROM mobile_membership "
            "WHERE acquisition_id=?", (acquisition_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Frozen membership missing")
    return _checked(row, as_of.astimezone(JST).date(), as_of)


def _checked(row, day, as_of):
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(row[2], 64 * 1024 * 1024 + 1)
        if (len(raw) > 64 * 1024 * 1024 or decoder.unconsumed_tail
                or decoder.unused_data or not decoder.eof):
            raise ValueError("Membership compression limit")
    except zlib.error as error:
        raise ValueError("Membership observation changed") from error
    if hashlib.sha256(raw).hexdigest() != row[1]:
        raise ValueError("Membership observation changed")
    payload = json.loads(raw)
    received = receipt_time(payload["received_at"])
    if (payload["acquisitionId"] != row[0] or payload["date"] != str(day)
            or received > as_of or received != datetime.fromisoformat(row[3])):
        raise ValueError("Membership reference changed")
    calendar = next(row for row in payload["datasets"]["trading_calendar"]
                    if row["Date"] == str(day))
    return {**payload, "payload_hash": row[1],
            "is_business_day": str(calendar["HolDiv"]) in ("1", "2")}


def status(path: Path, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("Aware observation time required")
    local = now.astimezone(JST)
    cutoff = local.replace(hour=11, minute=30, second=0, microsecond=0)
    latest = snapshot(path, now)
    eligible = latest if local <= cutoff else snapshot(path, cutoff)
    return {"date": str(local.date()), "cutoff": cutoff.isoformat(),
            "latest_received_at": None if latest is None else latest["received_at"],
            "available_at_cutoff": eligible is not None,
            "is_business_day": None if eligible is None else eligible["is_business_day"],
            "latest_is_business_day": None if latest is None else latest["is_business_day"],
            "acquisitionId": None if latest is None else latest["acquisitionId"],
            "eligible_acquisition_id": None if eligible is None else eligible["acquisitionId"],
            "eligible_received_at": None if eligible is None else eligible["received_at"],
            "after_cutoff": local > cutoff,
            "research_only": True}
