"""Explicit conservative research cash release; never certifies a broker balance."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from stock_ai.data.contracts import DatasetName, StoredObject
from stock_ai.data.storage import ImmutableParquetStore, StorageIntegrityError
from stock_ai.ml.daily_market import _META, DailyMarketRequest, _authenticate_object, _read_frame
from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.nav import JST, NavInput
from stock_ai.ml.selection import load_development_feature_selection
from stock_ai.operations.daily import content_id

POLICY_VERSION = "t2-equity-calendar-proxy-t3-0900-jst-v1"
RULE_SOURCES = (
    "https://www.jpx.co.jp/news/0010/20190714.html",
    "https://www.jpx.co.jp/equities/clearing-settlement/tplus2-settlement-cycle/",
    "https://jpx-jquants.com/ja/spec/mkt-cal",
    "https://jpx-jquants.com/ja/spec/mkt-cal/holiday-division",
)


def build_funding_schedule(
    calendar: Sequence[tuple[date, int]], *, start: date, end: date,
) -> dict[str, Any]:
    """Separate a T+2 settlement-date proxy from assumed T+3 09:00 funding.

    Cash-equity dates are an explicit research proxy for the settlement calendar.
    The release clock is a frozen conservative assumption, not an observed rule.
    Every civil date is required; no missing day is filled as a weekday/holiday.
    """
    if end < start:
        raise ValueError("calendar window is reversed")
    expected = tuple(start + timedelta(days=i) for i in range((end - start).days + 1))
    if tuple(row[0] for row in calendar) != expected or any(
        type(division) is not int or division not in (0, 1, 2, 3) for _, division in calendar
    ):
        raise ValueError("funding requires an ordered complete calendar with valid divisions")
    days = [day for day, division in calendar if division in (1, 2)]
    rows = []
    for i, day in enumerate(days):
        settlement = days[i + 2] if i + 2 < len(days) else None
        release = days[i + 3] if i + 3 < len(days) else None
        reason = None
        if day < date(2019, 7, 16):
            reason, settlement, release = "UNSUPPORTED_SETTLEMENT_REGIME", None, None
        elif release is None:
            reason = "CALENDAR_TAIL_INSUFFICIENT"
        rows.append({"trading_date": str(day), "settlement_date_proxy": (
            None if settlement is None else str(settlement)), "sale_cash_available_at": (
            None if release is None else datetime.combine(release, time(9), JST).isoformat()),
            "blocking_reason": reason})
    calendar_rows = [{"date": str(day), "holiday_division": div} for day, div in calendar]
    return {
        "schema_version": "research-funding-schedule-v1", "policy_version": POLICY_VERSION,
        "calendar_id": content_id({"schema_version": "equity-calendar-v1", "rows": calendar_rows}),
        "calendar_rows": calendar_rows, "rows": rows, "research_assumption": True,
        "broker_verified": False, "adoption_eligible": False, "research_only": True,
        "calendar_basis": "cash_equity_business_days_as_research_settlement_proxy",
        "settlement_session_offset": 2, "release_session_offset": 3, "release_time_jst": "09:00",
        "status": "PARTIAL" if any(row["blocking_reason"] for row in rows) else "COMPLETE",
        "summary": {"calendar_days": len(calendar), "equity_sessions": len(rows),
                    "funding_rows": sum(row["blocking_reason"] is None for row in rows),
                    "blocked_rows": sum(row["blocking_reason"] is not None for row in rows)},
    }


def _calendar_pair(normal: StoredObject, raw: StoredObject) -> tuple[date, int]:
    left, right = _read_frame(normal), _read_frame(raw)
    if len(left) != 1 or len(right) != 1:
        raise StorageIntegrityError("calendar partition must contain exactly one calendar date")
    if normal.payload_hash != raw.payload_hash or normal.source_date != raw.source_date:
        raise StorageIntegrityError("calendar pair identity differs")
    if (
        pd.Timestamp(left.trading_date.iloc[0]).date() != normal.source_date
        or pd.Timestamp(right.Date.iloc[0]).date() != normal.source_date
    ):
        raise StorageIntegrityError("calendar date differs from partition")
    if any(left[key].iloc[0] != right[key].iloc[0] for key in _META):
        raise StorageIntegrityError("raw/normalized calendar lineage differs")
    division = str(right.HolDiv.iloc[0])
    if division not in ("0", "1", "2", "3") or (
        left.holiday_division.iloc[0] != int(division)
        or not pd.api.types.is_bool_dtype(left.is_equity_business_day)
        or bool(left.is_equity_business_day.iloc[0]) != (division in ("1", "2"))
    ):
        raise StorageIntegrityError("raw/normalized calendar value differs")
    return normal.source_date, int(division)


def project_research_funding(request: DailyMarketRequest) -> dict[str, Any]:
    features = load_development_feature_selection(request.feature_selection_path)
    if request.end >= date.fromisoformat(features.locked_holdout_start):
        raise ValueError("funding calendar reaches locked holdout")
    store = ImmutableParquetStore(request.store_root)
    sources: dict[str, StoredObject] = {}
    selected: dict[date, tuple[tuple[Any, ...], int]] = {}
    with duckdb.connect(str(request.catalog_path), read_only=True) as connection:
        connection.execute("BEGIN TRANSACTION")
        cursor = connection.execute("""
            SELECT DISTINCT stored.* FROM stored_objects stored
            JOIN ingestion_run_objects link ON stored.object_id=link.object_id
            JOIN ingestion_runs run ON run.ingestion_run_id=link.ingestion_run_id
            LEFT JOIN bulk_file_checkpoints bulk ON bulk.fingerprint=run.bulk_fingerprint
            WHERE stored.dataset='trading_calendar' AND stored.quality_passed
              AND stored.source_date BETWEEN ? AND ? AND stored.available_at<=?
              AND run.status='SUCCEEDED'
              AND (run.bulk_fingerprint IS NULL OR bulk.status='SUCCEEDED')
            ORDER BY stored.object_id
        """, [request.start, request.end, request.source_snapshot_as_of])
        names = [column[0] for column in cursor.description]
        catalog = {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}
        for entry in catalog.values():
            if entry["kind"] != "normalized":
                continue
            normal = _authenticate_object(store, entry, dataset=DatasetName.TRADING_CALENDAR)
            frame = _read_frame(normal)
            raw_ids = list(frame.raw_object_id.unique()) if "raw_object_id" in frame else []
            if len(raw_ids) != 1 or raw_ids[0] not in catalog:
                raise StorageIntegrityError("calendar needs one successful raw link")
            raw = _authenticate_object(
                store, catalog[raw_ids[0]], dataset=DatasetName.TRADING_CALENDAR,
            )
            if raw.kind.value != "raw":
                raise StorageIntegrityError("calendar raw link has wrong kind")
            day, division = _calendar_pair(normal, raw)
            priority = (normal.available_at, normal.received_at,
                        normal.payload_hash, normal.object_id)
            if day not in selected or priority > selected[day][0]:
                selected[day] = priority, division
            sources.update({normal.object_id: normal, raw.object_id: raw})
    result = build_funding_schedule(tuple((d, selected[d][1]) for d in sorted(selected)),
                                    start=request.start, end=request.end)
    for source in sources.values():
        if store.verify(source.parquet_path.parent) != source:
            raise StorageIntegrityError("funding calendar source changed during projection")
    return {**result, "request": request.model_dump(mode="json"),
            "feature_selection_id": features.feature_selection_id,
            "model_data_snapshot_id": features.data_snapshot_id,
            "locked_holdout_start": features.locked_holdout_start, "holdout_rows_read": False,
            "historical_as_known": False, "rule_sources": RULE_SOURCES,
            "source_objects": [sources[key].model_dump(mode="json") for key in sorted(sources)],
            "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "limitations": ["T+3 09:00 is a research assumption, not broker buying-power evidence.",
                            "Cash-equity calendar is an explicit settlement-calendar proxy.",
                            "T+2 proxy date does not certify settlement completion or timing.",
                            "Current calendar vintage does not prove historical known-at inputs.",
                            "No missing day/tail is filled; pending sale receipts remain in NAV."]}


def require_research_funding(accounting: NavInput, schedule: dict[str, Any]) -> None:
    """Verify the chosen schedule before replay; never repair session timestamps."""
    days = [(date.fromisoformat(r["date"]), r["holiday_division"])
            for r in schedule["calendar_rows"]]
    if not days:
        raise ValueError("research funding calendar is empty")
    expected = build_funding_schedule(days, start=days[0][0], end=days[-1][0])
    if any(schedule.get(key) != value for key, value in expected.items()):
        raise ValueError("research funding receipt differs from the frozen rule")
    if accounting.calendar_id != expected["calendar_id"]:
        raise ValueError("research funding calendar identity differs")
    rows = {row["trading_date"]: row for row in expected["rows"]}
    for session in accounting.sessions:
        row = rows.get(str(session.trading_date))
        if row is None or row["blocking_reason"] is not None or (
            session.sale_cash_available_at != datetime.fromisoformat(row["sale_cash_available_at"])
        ):
            raise ValueError("session research funding is unresolved or differs from the rule")


def write_research_funding(request: DailyMarketRequest, output_root: Path) -> Path:
    return write_audit_receipt(project_research_funding(request), output_root)
