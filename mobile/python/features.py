"""The PC FeatureEngine, with the exact frozen 41/51 column selections."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_ai.features import FEATURE_REGISTRY, V2_EXTENDED_MANIFEST, FeatureEngine
from stock_ai.features.engine import (
    DAILY_REQUIRED,
    FINANCIAL_COLUMNS,
    MARKET_REQUIRED,
    SECTOR_REQUIRED,
)


def model_input_frame(name: str, source: pd.DataFrame) -> pd.DataFrame:
    """Project engine inputs after the identity of every full source is frozen."""
    required = {
        "daily": DAILY_REQUIRED | {"adjusted_open", "shares_outstanding", "trading_session_index"},
        "market": MARKET_REQUIRED,
        "sector": SECTOR_REQUIRED,
        "financials": {"symbol", "trading_date", "available_at", *FINANCIAL_COLUMNS},
    }[name]
    return source.loc[:, [column for column in source.columns if column in required]].copy()


def _json_records_frame(source: pd.DataFrame) -> pd.DataFrame:
    """Match the shipped records JSON precision/inference one column at a time."""
    if (source.empty or not source.columns.is_unique
            or any(not isinstance(name, str) for name in source.columns)):
        return pd.DataFrame.from_records(
            json.loads(source.to_json(orient="records", date_format="iso"))
        )
    columns = {}
    for name in source.columns:
        column = source[name]
        if (pd.api.types.is_datetime64_any_dtype(column.dtype)
                or pd.api.types.infer_dtype(column, skipna=True) == "string"):
            # Repeated immutable strings/dates need the same JSON values, not
            # a separate Python string allocation for every historical row.
            codes, unique = pd.factorize(column, sort=False, use_na_sentinel=False)
            encoded = pd.Series(unique, dtype=column.dtype).to_frame(name=name)
            parsed = json.loads(encoded.to_json(orient="values", date_format="iso"))
            values = [row[0] for row in parsed]
            columns[name] = pd.Series([values[code] for code in codes])
            del codes, unique, encoded, parsed, values
        else:
            values = json.loads(column.to_json(orient="values", date_format="iso"))
            columns[name] = pd.Series(values)
            del values
    return pd.DataFrame(columns, copy=False)


def calculate(payload: dict, selection: dict) -> dict:
    frames = {}
    for name in ("daily", "market", "sector", "financials"):
        source = payload[name]
        frame = (_json_records_frame(source) if isinstance(source, pd.DataFrame)
                 else pd.DataFrame.from_records(source))
        for column in ("available_at",):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], utc=True)
        if "trading_date" in frame:
            frame["trading_date"] = pd.to_datetime(frame["trading_date"])
        frames[name] = frame
    as_of = datetime.fromisoformat(payload["as_of"])
    names = {name for item in selection["horizons"] for name in item["feature_names"]}
    required = max(FEATURE_REGISTRY.definition(name).warmup_period for name in names)
    daily = frames["daily"]
    completed = daily.loc[
        (daily.available_at <= as_of)
        & (daily.trading_date.dt.date < as_of.astimezone(ZoneInfo("Asia/Tokyo")).date())
    ]
    counts = completed.groupby("symbol").trading_date.nunique()
    eligible = set(counts[counts >= required].index)
    if not eligible:
        raise ValueError(f"INSUFFICIENT_HISTORY: at least {required} completed sessions required")
    result = FeatureEngine(V2_EXTENDED_MANIFEST).latest_snapshot(
        frames["daily"],
        frames["market"],
        frames["sector"],
        financials=frames["financials"],
        as_of=as_of,
    )
    excluded = sorted(set(result.symbol) - eligible)
    result = result.loc[result.symbol.isin(eligible)]
    output = {}
    for horizon in selection["horizons"]:
        days, names = horizon["horizon"], horizon["feature_names"]
        if (days, len(names)) not in ((5, 41), (20, 51)):
            raise ValueError("Unexpected frozen feature selection")
        output[str(days)] = json.loads(
            result[["symbol", "available_at", *names]].to_json(orient="records", date_format="iso")
        )
    return {
        "as_of": payload["as_of"],
        "features": output,
        "research_only": True,
        "excluded_for_insufficient_history": excluded,
        "required_history_sessions": required,
    }


def bundled_selection() -> dict:
    return json.loads(Path("/stockai-code/feature-selection.json").read_text())
