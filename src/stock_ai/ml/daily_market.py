"""Authenticate development-only daily bars without inventing execution capability."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from stock_ai.data.contracts import ENDPOINT_SCHEMAS, DatasetName, StoredObject
from stock_ai.data.storage import ImmutableParquetStore, StorageIntegrityError
from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.selection import load_development_feature_selection

VERSION = "daily-market-projection-v1"
_VALUES = {
    "raw_open": "O", "raw_high": "H", "raw_low": "L", "raw_close": "C",
    "raw_volume": "Vo", "trading_value": "Va", "adjustment_factor": "AdjFactor",
}
_META = (
    "provider", "source_endpoint", "source_date", "received_at", "available_at", "as_of",
    "payload_hash", "schema_version", "ingestion_run_id", "source_record_hash",
)
_CATALOG_FIELDS = (
    "object_id", "kind", "dataset", "source_date", "payload_hash", "parquet_hash", "rows",
    "schema_version", "source_endpoint", "received_at", "available_at", "as_of",
    "parquet_path", "manifest_path", "quality_passed",
)


class DailyMarketRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_path: Path
    store_root: Path
    feature_selection_path: Path
    start: date
    end: date
    source_snapshot_as_of: datetime
    revision_policy: Literal["SINGLE_VINTAGE_AS_REVISED"] = "SINGLE_VINTAGE_AS_REVISED"

    @field_validator("source_snapshot_as_of")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("source snapshot time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered(self) -> DailyMarketRequest:
        if self.end < self.start:
            raise ValueError("market window end precedes start")
        return self


def _authenticate_object(
    store: ImmutableParquetStore, catalog_row: dict[str, Any],
    *, dataset: DatasetName = DatasetName.DAILY_PRICES,
) -> StoredObject:
    stored = store.verify(Path(catalog_row["parquet_path"]).parent)
    for key in _CATALOG_FIELDS:
        expected, observed = getattr(stored, key), catalog_row[key]
        if key in ("parquet_path", "manifest_path"):
            matches = Path(expected).resolve() == Path(observed).resolve()
        else:
            matches = expected == observed
        if not matches:
            raise StorageIntegrityError(f"catalog/manifest mismatch: {key}")
    if (
        stored.provider != "J-Quants" or stored.dataset != dataset
        or stored.source_endpoint != ENDPOINT_SCHEMAS[dataset].endpoint
    ):
        raise StorageIntegrityError("unexpected daily market provider/endpoint")
    return stored


def _read_frame(stored: StoredObject) -> pd.DataFrame:
    frame = pd.read_parquet(stored.parquet_path)
    if not set(_META).issubset(frame):
        raise StorageIntegrityError("daily market row metadata is incomplete")
    for key in _META:
        if key == "source_record_hash":
            if frame[key].isna().any() or not frame[key].astype(str).str.fullmatch(
                "[0-9a-f]{64}"
            ).all():
                raise StorageIntegrityError("invalid source record hash")
            continue
        expected = (
            ENDPOINT_SCHEMAS[stored.dataset].schema_version
            if key == "schema_version" else getattr(stored, key)
        )
        if not frame[key].eq(expected).all():
            raise StorageIntegrityError(f"row/manifest mismatch: {key}")
    return frame


def _pair_rows(
    normalized: StoredObject, raw: StoredObject,
    normalized_frame: pd.DataFrame, raw_frame: pd.DataFrame,
) -> pd.DataFrame:
    if normalized.payload_hash != raw.payload_hash or normalized.source_date != raw.source_date:
        raise StorageIntegrityError("raw/normalized object lineage differs")
    required = {*_VALUES, "provider_code", "trading_date", "symbol", "raw_object_id"}
    if not required.issubset(normalized_frame) or not {
        *_VALUES.values(), "Code", "Date",
    }.issubset(raw_frame):
        raise StorageIntegrityError("daily market price columns are incomplete")
    left = normalized_frame.copy()
    right = raw_frame.copy()
    left["provider_code"] = left.provider_code.astype(str)
    right["provider_code"] = right.Code.astype(str)
    right["trading_date"] = pd.to_datetime(right.Date, errors="raise").dt.date
    for frame in (left, right):
        if not frame.trading_date.eq(normalized.source_date).all():
            raise StorageIntegrityError("daily market partition contains another date")
        if frame.duplicated(["trading_date", "provider_code"]).any():
            raise StorageIntegrityError("duplicate daily market key")
    if not left.raw_object_id.eq(raw.object_id).all():
        raise StorageIntegrityError("wrong raw object link")
    if not left.symbol.eq(left.provider_code.str[:-1]).all():
        raise StorageIntegrityError("normalized symbol differs from provider code")
    if not left.provider_code.str.fullmatch("[0-9A-Z]{5}").all():
        raise StorageIntegrityError("invalid daily market security code")
    standard_code = left.provider_code.str.endswith("0")
    left["symbol_status"] = "standard_equity_code"
    left.loc[~standard_code, "symbol_status"] = "nonstandard_provider_code"
    # Preserve special share classes by the exact provider code. Do not collapse
    # them into the normal stock's four-character symbol or silently drop them.
    left.loc[~standard_code, "symbol"] = None
    left = left.set_index(["trading_date", "provider_code"]).sort_index()
    right = right.set_index(["trading_date", "provider_code"]).sort_index()
    if not left.index.equals(right.index):
        raise StorageIntegrityError("raw/normalized market key sets differ")
    for key in _META:
        if not left[key].eq(right[key]).all():
            raise StorageIntegrityError(f"raw/normalized row lineage differs: {key}")
    for target, source in _VALUES.items():
        values = pd.to_numeric(right[source], errors="raise")
        observed = pd.to_numeric(left[target], errors="raise")
        if not (values.eq(observed) | (values.isna() & observed.isna())).all():
            raise StorageIntegrityError(f"raw/normalized market value differs: {target}")
        if not (values.isna() | ((values >= 0) & (values < float("inf")))).all():
            raise StorageIntegrityError(f"invalid market value: {source}")
        left[target] = observed
    # ExRT distinguishes a reported event from a price factor. Rights issues
    # can have factor=1 for excluded product classes, so keep both observations.
    rights = right.ExRT.astype("string") if "ExRT" in right else pd.Series(
        pd.NA, dtype="string", index=right.index,
    )
    rights = rights.mask(rights.eq(""))  # CSV blanks have the API's null meaning.
    if "ex_rights_type" in left:
        observed_rights = left.ex_rights_type.astype("string")
        observed_rights = observed_rights.mask(observed_rights.eq(""))
        if not (rights.eq(observed_rights).fillna(False) | (
            rights.isna() & observed_rights.isna()
        )).all():
            raise StorageIntegrityError("raw/normalized ex-rights type differs")
    left["ex_rights_type"] = rights
    left["ex_rights_type_source_present"] = "ExRT" in right
    for source, target in (("UL", "intraday_upper_limit_reached"),
                           ("LL", "intraday_lower_limit_reached")):
        values = pd.to_numeric(right[source], errors="raise") if source in right else pd.Series(
            float("nan"), index=right.index
        )
        if not (values.isna() | values.isin((0, 1))).all():
            raise StorageIntegrityError(f"invalid intraday limit flag: {source}")
        left[target] = values.astype("Int64")
    left["normalized_object_id"] = normalized.object_id
    bar_columns = list(_VALUES)[:-1]
    no_trade = left[bar_columns].isna().all(axis=1)
    complete = left[bar_columns].notna().all(axis=1) & left[bar_columns].gt(0).all(axis=1)
    left["bar_state"] = "incomplete_bar"
    left.loc[no_trade, "bar_state"] = "reported_no_trade"
    left.loc[complete, "bar_state"] = "reported_trade"
    # Non-unit factors identify an unresolved adjustment, not a verified share split.
    left["adjustment_requires_event_evidence"] = (
        left.adjustment_factor.isna() | left.adjustment_factor.ne(1) | rights.notna()
    )
    columns = [
        "symbol", "symbol_status", *_VALUES,
        "intraday_upper_limit_reached", "intraday_lower_limit_reached",
        "ex_rights_type", "ex_rights_type_source_present",
        "bar_state", "adjustment_requires_event_evidence", "raw_object_id",
        "normalized_object_id", *_META,
    ]
    return left[columns].reset_index()


def project_daily_market(request: DailyMarketRequest) -> dict[str, Any]:
    """Read only the declared development window and authenticate every raw/normal pair.

    This authenticates local provenance and bytes, not vendor historical correctness,
    an original correction vintage, exchange execution, or corporate-action coverage.
    """
    features = load_development_feature_selection(request.feature_selection_path)
    protected_from = date.fromisoformat(features.locked_holdout_start)
    if request.end >= protected_from:
        raise ValueError("daily market window reaches the locked holdout")
    store = ImmutableParquetStore(request.store_root)
    with duckdb.connect(str(request.catalog_path), read_only=True) as connection:
        # Do not use DuckDBCatalog.__init__: it initializes a writable catalog.
        connection.execute("BEGIN TRANSACTION")
        query = """
            SELECT DISTINCT stored.* FROM stored_objects stored
            JOIN ingestion_run_objects link ON stored.object_id = link.object_id
            JOIN ingestion_runs run ON run.ingestion_run_id = link.ingestion_run_id
            LEFT JOIN bulk_file_checkpoints bulk ON bulk.fingerprint = run.bulk_fingerprint
            WHERE stored.dataset = 'daily_prices' AND stored.quality_passed
              AND stored.source_date BETWEEN ? AND ? AND stored.available_at <= ?
              AND run.status = 'SUCCEEDED'
              AND (run.bulk_fingerprint IS NULL OR bulk.status = 'SUCCEEDED')
            ORDER BY stored.object_id
        """
        cursor = connection.execute(query, [request.start, request.end,
                                            request.source_snapshot_as_of])
        names = [item[0] for item in cursor.description]
        catalog = {row[0]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}
        parts: list[pd.DataFrame] = []
        sources: dict[str, StoredObject] = {}
        for entry in catalog.values():
            if entry["kind"] != "normalized":
                continue
            normalized = _authenticate_object(store, entry)
            frame = _read_frame(normalized)
            if frame.empty:
                raw_ids = [key for key, value in catalog.items() if value["kind"] == "raw"
                           and value["payload_hash"] == normalized.payload_hash
                           and value["source_date"] == normalized.source_date]
                if len(raw_ids) != 1:
                    raise StorageIntegrityError("empty normalized object needs one raw pair")
                raw_id = raw_ids[0]
            elif "raw_object_id" not in frame or frame.raw_object_id.nunique(dropna=False) != 1:
                raise StorageIntegrityError("normalized market object needs one raw link")
            else:
                raw_id = str(frame.raw_object_id.iloc[0])
            if raw_id not in catalog or catalog[raw_id]["kind"] != "raw":
                raise StorageIntegrityError("raw market object lacks successful eligible ingestion")
            raw = _authenticate_object(store, catalog[raw_id])
            parts.append(_pair_rows(normalized, raw, frame, _read_frame(raw)))
            sources.update({normalized.object_id: normalized, raw.object_id: raw})
        if not parts:
            raise ValueError("no authenticated daily market objects in requested window")
        all_rows = pd.concat(parts, ignore_index=True)
        # Keep the catalog's PIT version priority; object ID breaks identical version ties.
        selected = all_rows.sort_values([
            "trading_date", "provider_code", "available_at", "received_at", "payload_hash",
            "normalized_object_id",
        ]).drop_duplicates(["trading_date", "provider_code"], keep="last")
        # Verify again after reads; never issue a receipt for changed files.
        for stored in sources.values():
            if store.verify(stored.parquet_path.parent) != stored:
                raise StorageIntegrityError("market source changed during projection")
    selected = selected.sort_values(["trading_date", "symbol"]).reset_index(drop=True)
    # Preserve Python float values without a second decimal-rounding operation.
    records = selected.to_dict(orient="records")
    for record in records:
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None
            elif isinstance(value, (date, datetime)):
                record[key] = value.isoformat()
    counts = {str(key): int(value) for key, value in selected.bar_state.value_counts().items()}
    return {
        "schema_version": VERSION, "research_only": True, "adoption_eligible": False,
        "request": request.model_dump(mode="json"),
        "feature_selection_id": features.feature_selection_id,
        "data_snapshot_id_declared_by_features": features.data_snapshot_id,
        "locked_holdout_start": protected_from.isoformat(), "holdout_rows_read": False,
        "price_basis": "unadjusted", "rows": records,
        "source_objects": [sources[key].model_dump(mode="json") for key in sorted(sources)],
        "summary": {"rows": len(selected), "source_rows": len(all_rows),
                    "dates": selected.trading_date.nunique(), "bar_states": counts,
                    "nonstandard_code_rows": int(selected.symbol.isna().sum()),
                    "adjustment_rows": int(selected.adjustment_requires_event_evidence.sum()),
                    "ex_rights_types": {
                        str(key): int(count)
                        for key, count in selected.ex_rights_type.value_counts().items()
                    },
                    "ex_rights_source_missing_rows": int(
                        (~selected.ex_rights_type_source_present).sum()
                    ),
                    "upper_limit_rows": int(selected.intraday_upper_limit_reached.eq(1).sum()),
                    "lower_limit_rows": int(selected.intraday_lower_limit_reached.eq(1).sum())},
        "capabilities": {
            "buy_status": "unknown", "sell_status": "unknown", "capacity_shares": None,
            "tick_size": None, "sale_cash_available_at": None,
            "corporate_actions": "UNVERIFIED", "historical_as_known": False,
            "evaluation_ready": False,
        },
        "limitations": [
            "Single provider vintage; received_at is local receipt, not historical availability.",
            "Daily UL/LL are intraday limit touches, not closing execution status.",
            "No-trade rows persist; absent rows are not interpreted as no-trade or delisting.",
            "Adjustment factors do not establish dated splits, dividends or cash conversion.",
            "ExRT flags do not establish complete corporate-action coverage.",
            "No universe/calendar completeness or equality to frozen dataset source is asserted.",
            "Execution capacity, tick rules and settlement evidence are still required.",
        ],
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dependencies": {"pandas": pd.__version__, "duckdb": duckdb.__version__},
    }


def write_daily_market(request: DailyMarketRequest, output_root: Path) -> Path:
    return write_audit_receipt(project_daily_market(request), output_root)
