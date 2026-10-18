"""Dated domestic lot/tick rules from authenticated raw master, never fill evidence."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from stock_ai.data.contracts import DatasetName, StoredObject
from stock_ai.data.storage import ImmutableParquetStore, StorageIntegrityError
from stock_ai.ml.daily_market import (
    _META,
    DailyMarketRequest,
    _authenticate_object,
    _read_frame,
    project_daily_market,
)
from stock_ai.ml.evaluation_audit import write_audit_receipt

RULE_VERSION = "tse-domestic-100-topix500-ticks-20230605-to-20270228-v1"
RULE_SOURCES = (
    "https://jpx-jquants.com/ja/spec/eq-master/product-category",
    "https://jpx-jquants.com/ja/spec/eq-master/scalecategory",
    "https://www.jpx.co.jp/equities/improvements/unit/index.html",
    "https://www.jpx.co.jp/news/1030/20230602-01.html",
    "https://www.jpx.co.jp/equities/trading/domestic/07.html",
)
# Upper bound, TOPIX500, other domestic shares. Prices and ticks are exact decimals.
_TICKS = (
    (1000, "0.1", "1"), (3000, "0.5", "1"), (5000, "1", "5"),
    (10000, "1", "10"), (30000, "5", "10"), (50000, "10", "50"),
    (100000, "10", "100"), (300000, "50", "100"), (500000, "100", "500"),
    (1000000, "100", "1000"), (3000000, "500", "1000"),
    (5000000, "1000", "5000"), (10000000, "1000", "10000"),
    (30000000, "5000", "10000"), (50000000, "10000", "50000"),
)
_TOPIX500 = frozenset(("TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"))
_OTHER = frozenset(("TOPIX Small 1", "TOPIX Small 2", "-"))


def instrument_rules(
    day: date, product: str | None, scale: str | None, price: Decimal | None,
) -> dict[str, Any]:
    """No foreign/legacy default, no future-regime extrapolation or price rounding."""
    if price is not None and (not price.is_finite() or price <= 0):
        raise ValueError("instrument price must be finite and positive")
    lot = 100 if product == "011" and day >= date(2018, 10, 1) else None
    reason = None
    tick = None
    if product != "011":
        reason = "domestic_product_not_proven"
    elif not date(2023, 6, 5) <= day < date(2027, 3, 1):
        reason = "tick_regime_outside_supported_dates"
    elif scale not in _TOPIX500 | _OTHER:
        reason = "scale_category_unknown"
    elif price is None:
        reason = "reference_price_missing"
    else:
        index = 1 if scale in _TOPIX500 else 2
        tick = next((row[index] for row in _TICKS if price <= row[0]),
                    "10000" if index == 1 else "100000")
    return {"round_lot_size": lot, "tick_size": tick, "tick_missing_reason": reason,
            "round_lot_missing_reason": None if lot is not None else "domestic_100_rule_not_proven"}


def _master_pair(
    normal: StoredObject, raw: StoredObject, left: pd.DataFrame, right: pd.DataFrame,
) -> pd.DataFrame:
    required = {"effective_date", "provider_code", "symbol", "size_category", "market_code"}
    if (
        normal.payload_hash != raw.payload_hash or normal.source_date != raw.source_date
        or not required.issubset(left) or not {"Code", "Date", "ScaleCat", "Mkt"}.issubset(right)
    ):
        raise StorageIntegrityError("master pair identity/columns differ")
    for frame, date_column, code_column in [(left, "effective_date", "provider_code"),
                                            (right, "Date", "Code")]:
        if not pd.to_datetime(frame[date_column]).dt.date.eq(normal.source_date).all():
            raise StorageIntegrityError("master contains another date")
        if frame[code_column].duplicated().any():
            raise StorageIntegrityError("duplicate master key")
        if not frame[code_column].astype(str).str.fullmatch("[0-9A-Z]{5}").all():
            raise StorageIntegrityError("invalid master code")
    if not left.symbol.eq(left.provider_code.str[:-1]).all():
        raise StorageIntegrityError("master symbol differs")
    left = left.set_index("provider_code").sort_index()
    right = right.set_index("Code").sort_index()
    if not left.index.equals(right.index):
        raise StorageIntegrityError("raw/normalized master key sets differ")
    for key in _META:
        if not left[key].eq(right[key]).all():
            raise StorageIntegrityError("raw/normalized master lineage differs")
    for target, source in [("size_category", "ScaleCat"), ("market_code", "Mkt")]:
        if not left[target].eq(right[source]).all():
            raise StorageIntegrityError("raw/normalized master value differs")
    left["product_category"] = right.get(
        "ProdCat", pd.Series(None, index=right.index, dtype=object),
    )
    left["master_object_id"] = normal.object_id
    return left.reset_index()


def project_daily_instruments(request: DailyMarketRequest) -> dict[str, Any]:
    # Reuse its pre-open holdout guard, authenticated raw bars and snapshot policy.
    market = project_daily_market(request)
    store = ImmutableParquetStore(request.store_root)
    sources = {s["object_id"]: s for s in market["source_objects"]}
    selected: dict[date, tuple[tuple[Any, ...], pd.DataFrame]] = {}
    with duckdb.connect(str(request.catalog_path), read_only=True) as connection:
        connection.execute("BEGIN TRANSACTION")
        cursor = connection.execute("""
            SELECT DISTINCT stored.* FROM stored_objects stored
            JOIN ingestion_run_objects link ON stored.object_id=link.object_id
            JOIN ingestion_runs run ON run.ingestion_run_id=link.ingestion_run_id
            LEFT JOIN bulk_file_checkpoints bulk ON bulk.fingerprint=run.bulk_fingerprint
            WHERE stored.dataset='security_master' AND stored.quality_passed
              AND stored.source_date BETWEEN ? AND ? AND stored.available_at<=?
              AND run.status='SUCCEEDED'
              AND (run.bulk_fingerprint IS NULL OR bulk.status='SUCCEEDED')
            ORDER BY stored.object_id
        """, [request.start, request.end, request.source_snapshot_as_of])
        names = [c[0] for c in cursor.description]
        catalog = {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}
        for entry in catalog.values():
            if entry["kind"] != "normalized":
                continue
            normal = _authenticate_object(store, entry, dataset=DatasetName.SECURITY_MASTER)
            frame = _read_frame(normal)
            if frame.empty:
                raw_ids = [key for key, value in catalog.items() if value["kind"] == "raw"
                           and value["source_date"] == normal.source_date
                           and value["payload_hash"] == normal.payload_hash]
            else:
                raw_ids = list(frame.raw_object_id.unique()) if "raw_object_id" in frame else []
            if len(raw_ids) != 1 or raw_ids[0] not in catalog:
                raise StorageIntegrityError("master needs one successful raw link")
            raw = _authenticate_object(
                store, catalog[raw_ids[0]], dataset=DatasetName.SECURITY_MASTER,
            )
            if raw.kind.value != "raw":
                raise StorageIntegrityError("master raw link has wrong kind")
            paired = _master_pair(normal, raw, frame, _read_frame(raw))
            for obj in (normal, raw):
                sources[obj.object_id] = obj.model_dump(mode="json")
            priority = (normal.available_at, normal.received_at,
                        normal.payload_hash, normal.object_id)
            # Each source-date master is a full snapshot. Do not retain removed
            # members from an older version, including when the latest is empty.
            if normal.source_date not in selected or priority > selected[normal.source_date][0]:
                selected[normal.source_date] = priority, paired
    masters: dict[tuple[str, str], dict[str, Any]] = {}
    for day, (_, frame) in selected.items():
        for row in frame.to_dict(orient="records"):
            masters[str(day), row["provider_code"]] = {str(k): v for k, v in row.items()}
    prices = {(row["trading_date"], row["provider_code"]): row for row in market["rows"]}
    rows = []
    for key in sorted(prices.keys() | masters.keys()):
        price, master = prices.get(key), masters.get(key)
        product = None if master is None or pd.isna(master["product_category"]) else str(
            master["product_category"])
        scale = None if master is None or pd.isna(master["size_category"]) else str(
            master["size_category"])
        close = None if price is None else price["raw_close"]
        rules = instrument_rules(
            date.fromisoformat(key[0]), product, scale,
            None if close is None else Decimal(str(close)),
        ) if key[1].endswith("0") else {
            "round_lot_size": None, "tick_size": None,
            "round_lot_missing_reason": "ordinary_share_class_not_proven",
            "tick_missing_reason": "ordinary_share_class_not_proven",
        }
        record: dict[str, Any] = {"trading_date": key[0], "provider_code": key[1],
               "symbol": key[1][:-1] if key[1].endswith("0") else None,
               "product_category": product, "size_category": scale, "raw_close": close,
               "market_code": None if master is None else master["market_code"],
               "master_available_at": (
                   None if master is None else master["available_at"].isoformat()),
               "master_object_id": None if master is None else master["master_object_id"],
               "master_record_hash": None if master is None else master["source_record_hash"],
               "price_object_id": None if price is None else price["normalized_object_id"],
               "price_record_hash": None if price is None else price["source_record_hash"],
               **rules}
        rows.append(record)
    # Reauthenticate every source after all reads/joins; no source is rewritten.
    for source in sources.values():
        if store.verify(Path(source["parquet_path"]).parent).model_dump(mode="json") != source:
            raise StorageIntegrityError("instrument source changed during projection")
    return {
        "schema_version": "daily-instrument-rules-v1", "research_only": True,
        "adoption_eligible": False, "historical_as_known": False, "evaluation_ready": False,
        "request": request.model_dump(mode="json"), "rule_version": RULE_VERSION,
        "rule_sources": RULE_SOURCES, "rules_reviewed_on": "2026-10-18",
        "feature_selection_id": market["feature_selection_id"],
        "data_snapshot_id_declared_by_features": market["data_snapshot_id_declared_by_features"],
        "locked_holdout_start": market["locked_holdout_start"], "holdout_rows_read": False,
        "rows": rows, "source_objects": [sources[key] for key in sorted(sources)],
        "summary": {"rows": len(rows), "dates": len({r["trading_date"] for r in rows}),
                    "lot_rule_rows": sum(r["round_lot_size"] is not None for r in rows),
                    "tick_rule_rows": sum(r["tick_size"] is not None for r in rows),
                    "missing_master_rows": sum(r["master_object_id"] is None for r in rows),
                    "missing_price_rows": sum(r["price_object_id"] is None for r in rows)},
        "unresolved_capabilities": ["corporate_action_coverage", "directional_execution",
                                    "execution_capacity", "settlement_buying_power",
                                    "historical_known_at_inputs"],
        "limitations": ["Current corrected master vintage, not historical knowledge.",
                        "Derived units and ticks do not establish execution capacity or status.",
                        "No default domestic category for legacy missing/foreign products.",
                        "All provider codes persist, including priority classes and missing bars.",
                        "Prices are neither rounded nor treated as feasible executions.",
                        "This is a rule overlay; not a replacement for a market NAV receipt."],
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "market_implementation_sha256": market["implementation_sha256"],
    }


def write_daily_instruments(request: DailyMarketRequest, output_root: Path) -> Path:
    return write_audit_receipt(project_daily_instruments(request), output_root)
