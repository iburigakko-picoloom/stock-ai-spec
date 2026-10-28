"""Rebuildable selected-history index and full-market context, never raw storage.

Cold/correction paths verify the original batches. An append-only ordinary day
reads only two days of broad prices/master plus selected indexed histories.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC
from pathlib import Path

import numpy as np
import pandas as pd

from stock_ai.data.contracts import DatasetName, HistoricalRevisionPolicy
from stock_ai.data.production import (
    _assert_source_vintage,
    _source_frame_id,
    build_production_data,
    complete_daily_financials,
)

from .features import model_input_frame
from .storage import connect

VERSION = "preselected-price-context-v1"
PRICE_KINDS = ("security_master", "daily_prices")
CONTEXT_KINDS = (*PRICE_KINDS, "trading_calendar", "topix")
MAX_BLOCK = 64 * 1024 * 1024


def code_version():
    # Canonical text makes Windows and WASM package copies share an identity.
    files = [
        Path(__file__),
        Path(__file__).with_name("market.py"),
        Path(__file__).with_name("market_codec.py"),
        Path(__file__).with_name("features.py"),
    ]
    import stock_ai.data.production as production

    files.append(Path(production.__file__))
    digest = hashlib.sha256(VERSION.encode())
    for file in files:
        digest.update(file.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def _pack(frame):
    """No pickle, float rounding or inferred datetime/string dtypes."""
    columns, arrays = [], {}
    for index, (name, column) in enumerate(frame.items()):
        dtype = column.dtype
        if pd.api.types.is_datetime64_any_dtype(dtype):
            array = column.array.asi8
            kind = "datetime"
        elif pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_extension_array_dtype(
            dtype
        ):
            array = column.to_numpy(copy=False)
            kind = "numeric"
        else:
            # Extension numerics preserve exact float hex strings and masks.
            values = [
                None
                if pd.isna(x)
                else float(x).hex()
                if isinstance(x, (float, np.floating))
                else x.item()
                if isinstance(x, np.generic)
                else x
                for x in column
            ]
            array = np.array(json.dumps(values, allow_nan=False, ensure_ascii=True))
            kind = "json"
        arrays[str(index)] = array
        columns.append((name, str(dtype), kind))
    arrays["schema"] = np.array(json.dumps(columns))
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


def _unpack(payload):
    if len(payload) > MAX_BLOCK:
        raise ValueError("Input cache block exceeds limit")
    # The ZIP format has a separate expanded size bound; never enable pickle.
    import zipfile

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_BLOCK:
            raise ValueError("Expanded input cache exceeds limit")
    with np.load(io.BytesIO(payload), allow_pickle=False) as arrays:
        columns = {}
        for index, (name, dtype, kind) in enumerate(json.loads(str(arrays["schema"]))):
            values = arrays[str(index)]
            if kind == "datetime":
                target = pd.api.types.pandas_dtype(dtype)
                unit = (
                    target.unit
                    if isinstance(target, pd.DatetimeTZDtype)
                    else np.datetime_data(target)[0]
                )
                values = pd.to_datetime(
                    values, unit=unit, utc=isinstance(target, pd.DatetimeTZDtype)
                )
                if isinstance(target, pd.DatetimeTZDtype):
                    values = values.tz_convert(target.tz)
            elif kind == "json":
                values = json.loads(str(values))
                if pd.api.types.is_float_dtype(pd.api.types.pandas_dtype(dtype)):
                    values = [None if x is None else float.fromhex(x) for x in values]
            columns[name] = pd.Series(values, dtype=dtype)
        return pd.DataFrame(columns, copy=False)


def _put(db, name, payload):
    if len(payload) > MAX_BLOCK:
        raise ValueError("Input cache block exceeds limit")
    db.execute(
        "INSERT OR REPLACE INTO mobile_input_cache VALUES(?,?,?)",
        (name, hashlib.sha256(payload).hexdigest(), payload),
    )


def _get(db, name, metrics):
    row = db.execute(
        "SELECT digest,payload FROM mobile_input_cache WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise ValueError("Input cache block missing")
    metrics["sqlite_cache_rows"] += 1
    metrics["sqlite_cache_bytes"] += len(row[1])
    if hashlib.sha256(row[1]).hexdigest() != row[0]:
        raise ValueError("Input cache content changed")
    return row[1]


def source_references(path, cutoff):
    with connect(path) as db:
        rows = db.execute(
            "WITH versions AS (SELECT dataset,day,sequence,received_at,payload_hash,"
            "normalized_hash,"
            "ROW_NUMBER() OVER(PARTITION BY dataset,day ORDER BY received_at DESC,sequence DESC) n "
            "FROM market_batches WHERE received_at<=?) SELECT dataset,day,sequence,received_at,"
            "payload_hash,normalized_hash FROM versions WHERE n=1 ORDER BY dataset,day",
            (cutoff.astimezone(UTC).isoformat(timespec="microseconds"),),
        ).fetchall()
    return [list(row) for row in rows]


def _context_references(references):
    return {tuple(row[:2]): row for row in references if row[0] in CONTEXT_KINDS}


def inputs(path, cutoff, selected):
    from .market import FeatureSource, SQLiteSource

    selected = sorted(selected)
    metrics = {
        "mode": "cold",
        "sqlite_cache_rows": 0,
        "sqlite_cache_bytes": 0,
        "raw_snapshot_days": 0,
        "raw_source_rows": 0,
        "common_population": "full_historical_eligible_market",
    }
    references = source_references(path, cutoff)
    version = code_version()
    metrics.update(code_version=version, cache_schema_version=VERSION)
    with connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_input_cache("
            "name TEXT PRIMARY KEY,digest TEXT NOT NULL,payload BLOB NOT NULL)"
        )
        exists = db.execute("SELECT 1 FROM mobile_input_cache WHERE name='metadata'").fetchone()
        metadata_bytes = _get(db, "metadata", metrics) if exists else None
        metadata = json.loads(metadata_bytes) if metadata_bytes is not None else None
    schemas, hashes, shared_frames = {}, {}, {}

    def verified(kind, day, schema, values):
        metrics["raw_snapshot_days"] += 1
        metrics["raw_source_rows"] += len(values) // 8
        schemas[kind] = [list(item) for item in schema]
        hashes[kind, day] = values

    reusable = metadata is not None and metadata["code_version"] == version
    old_refs = _context_references(metadata["references"]) if reusable else {}
    new_refs = _context_references(references)
    if reusable:
        reusable = (
            all(new_refs.get(key) == value for key, value in old_refs.items())
            and set(selected).issubset(metadata["symbols"])
            and cutoff.isoformat() >= metadata["cutoff"]
        )
    incremental = reusable and old_refs != new_refs
    if reusable and not incremental and cutoff.isoformat() != metadata["cutoff"]:
        # Missing the next closed day must not relabel yesterday's features.
        reusable = False
    if reusable:
        with connect(path) as db:
            db.execute("BEGIN")
            if _get(db, "metadata", metrics) != metadata_bytes:
                raise ValueError("INPUT_CACHE_CHANGED")
            daily = pd.concat(
                [_unpack(_get(db, "symbol:" + symbol, metrics)) for symbol in selected],
                ignore_index=True,
            )
            market = _unpack(_get(db, "market", metrics))
            sector = _unpack(_get(db, "sector", metrics))
        schemas = metadata["schemas"]
        identities = metadata["identities"]
        metrics["mode"] = "warm"
    if incremental:
        # Only append-only days qualify. A historical correction, new symbol,
        # changed schema or split takes the verified cold rebuild below.
        added = [key for key in new_refs if key not in old_refs]
        old_end = metadata["last_price_date"]
        if any(day <= old_end for _, day in added):
            reusable = False
        else:
            try:
                source = FeatureSource(
                    path, first_day=old_end, verified_day=verified, common_schemas=schemas,
                    context_only=True,
                )
                tail = build_production_data(
                    source,
                    source_snapshot_as_of=cutoff,
                    proposal_as_of=cutoff,
                    price_context_only=True,
                )
            except ValueError as error:
                if str(error) != "INPUT_CACHE_SCHEMA_CHANGED":
                    raise
                reusable = False
            else:
                newer = tail.daily.trading_date > pd.Timestamp(old_end)
                if (
                    not newer.any()
                    or not np.isclose(
                        tail.daily.loc[newer, "adjustment_factor"].astype(float),
                        1.0,
                        rtol=0,
                        atol=0,
                    ).all()
                ):
                    reusable = False
                else:
                    last_index = metadata["last_session_index"]
                    tail_index = int(tail.daily.loc[~newer, "trading_session_index"].max())
                    addition = tail.daily.loc[newer & tail.daily.symbol.isin(selected)].copy()
                    addition["trading_session_index"] += last_index - tail_index
                    daily = pd.concat([daily, addition], ignore_index=True)
                    market = pd.concat(
                        [
                            market,
                            tail.market_context.loc[
                                tail.market_context.trading_date > pd.Timestamp(old_end)
                            ],
                        ],
                        ignore_index=True,
                    )
                    sector = pd.concat(
                        [
                            sector,
                            tail.sector_context.loc[
                                tail.sector_context.trading_date > pd.Timestamp(old_end)
                            ],
                        ],
                        ignore_index=True,
                    )
                    metrics["mode"] = "append"
                    shared_frames = source.shared_frames
    if not reusable:
        schemas, hashes = {}, {}
        source = FeatureSource(path, verified_day=verified, context_only=True)
        bundle = build_production_data(
            source,
            source_snapshot_as_of=cutoff,
            proposal_as_of=cutoff,
            detail_symbols=frozenset(selected),
            price_context_only=True,
        )
        daily, market, sector = bundle.daily, bundle.market_context, bundle.sector_context
        identities = dict(bundle.source_snapshot_ids)
        shared_frames = source.shared_frames
        del bundle, source
        metrics["mode"] = "cold" if metadata is None else "rebuild"
    daily = daily.sort_values(["trading_date", "symbol"], ignore_index=True)
    # Read only small shared datasets here. Long price/master source frames are
    # served from the selected-symbol index, never reconstructed on a warm day.
    small = SQLiteSource(path)
    disclosures = shared_frames.get(DatasetName.FINANCIAL_SUMMARY)
    if disclosures is None:
        disclosures = small.point_in_time(DatasetName.FINANCIAL_SUMMARY, cutoff)
    for kind in (DatasetName.FINANCIAL_SUMMARY, DatasetName.TOPIX, DatasetName.TRADING_CALENDAR):
        frame = disclosures if kind is DatasetName.FINANCIAL_SUMMARY else shared_frames.get(kind)
        if frame is None:
            frame = small.point_in_time(kind, cutoff)
        if frame.empty:
            raise ValueError("BLOCKED_BY_DATA_CAPABILITY: empty cached input source")
        _assert_source_vintage(frame, cutoff, kind.value)
        identities[kind.value] = _source_frame_id(kind, frame)
    changed = metrics["mode"] != "warm"
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        if source_references(path, cutoff) != references:
            raise ValueError("INPUT_SNAPSHOT_CHANGED")
        if code_version() != version:
            raise ValueError("INPUT_CODE_CHANGED")
        if reusable and _get(db, "metadata", metrics) != metadata_bytes:
            raise ValueError("INPUT_CACHE_CHANGED")
        if changed:
            if not reusable:
                db.execute("DELETE FROM mobile_input_cache")
            for (kind, day), values in hashes.items():
                _put(db, "hash:" + kind + ":" + day, values)
            # Reassemble the exact v1 source byte stream; SHA digests themselves
            # cannot be concatenated to represent an updated source frame.
            for kind in PRICE_KINDS:
                header = json.dumps({"dataset": kind, "schema": schemas[kind]}, sort_keys=True)
                digest = hashlib.sha256(header.encode())
                for row in references:
                    if row[0] == kind:
                        digest.update(_get(db, "hash:" + kind + ":" + row[1], metrics))
                identities[kind] = digest.hexdigest()
            _put(db, "market", _pack(market))
            _put(db, "sector", _pack(sector))
            # Index the selected history once. Repeated string comparisons over
            # the entire history for every member are particularly slow in WASM.
            positions = daily.groupby("symbol", sort=False).indices
            for symbol in selected:
                _put(
                    db,
                    "symbol:" + symbol,
                    _pack(daily.iloc[positions.get(symbol, [])].reset_index(drop=True)),
                )
            metadata = {
                "code_version": version,
                "references": references,
                "schemas": schemas,
                "identities": identities,
                "symbols": selected,
                "cutoff": cutoff.isoformat(),
                "last_price_date": str(market.trading_date.max().date()),
                "last_session_index": len(market) - 1,
            }
            _put(db, "metadata", json.dumps(metadata, sort_keys=True).encode())
    daily, financials = complete_daily_financials(
        daily,
        disclosures.loc[disclosures.symbol.isin(selected)],
        HistoricalRevisionPolicy.SINGLE_VINTAGE_AS_REVISED,
    )
    latest = max(row[3] for row in references)
    return {
        "as_of": cutoff.isoformat(),
        "latest_source_received_at": latest,
        "source_snapshot_ids": sorted(identities.items()),
        "revision_policy": HistoricalRevisionPolicy.SINGLE_VINTAGE_AS_REVISED.value,
        "decision_symbols": selected,
        "input_cache": metrics,
        **{
            name: model_input_frame(name, frame)
            for name, frame in (
                ("daily", daily),
                ("financials", financials),
                ("market", market),
                ("sector", sector),
            )
        },
    }
