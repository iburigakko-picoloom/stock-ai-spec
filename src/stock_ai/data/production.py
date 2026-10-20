"""Point-in-time production research inputs derived from immutable J-Quants data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, time
from itertools import pairwise
from typing import Final, Protocol, cast, runtime_checkable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pandas.core.util.hashing import combine_hash_arrays  # type: ignore[attr-defined]

from stock_ai.data.contracts import (
    CapabilityStatus,
    DatasetName,
    HistoricalRevisionPolicy,
)


class PointInTimeCatalog(Protocol):
    """Read-only input boundary shared by desktop DuckDB and mobile SQLite."""

    def point_in_time(self, dataset: DatasetName, as_of: datetime) -> pd.DataFrame: ...


@runtime_checkable
class SourceIdentityCatalog(Protocol):
    """A trusted adapter may return verified projections of complete PIT sources."""

    def source_frame_id(self, dataset: DatasetName, frame: pd.DataFrame) -> str: ...


_JST: Final = ZoneInfo("Asia/Tokyo")
_ELIGIBLE_MARKETS: Final = frozenset(("0111", "0112", "0113"))
_FINANCIAL_FEATURES: Final = (
    "per",
    "pbr",
    "roe",
    "operating_margin",
    "revenue_growth_yoy",
    "operating_profit_growth_yoy",
    "forecast_revision",
)


@dataclass(frozen=True)
class ProductionDataBundle:
    source_snapshot_as_of: datetime
    source_snapshot_ids: tuple[tuple[str, str], ...]
    revision_policy: HistoricalRevisionPolicy
    historical_revision_status: CapabilityStatus
    universe: pd.DataFrame
    daily: pd.DataFrame
    market_context: pd.DataFrame
    sector_context: pd.DataFrame
    financials: pd.DataFrame
    corporate_actions: pd.DataFrame


def build_production_data(
    catalog: PointInTimeCatalog,
    *,
    source_snapshot_as_of: datetime,
    minimum_market_coverage: float = 0.95,
    revision_policy: HistoricalRevisionPolicy = HistoricalRevisionPolicy.SINGLE_VINTAGE_AS_REVISED,
    proposal_as_of: datetime | None = None,
    detail_symbols: frozenset[str] | None = None,
    price_context_only: bool = False,
) -> ProductionDataBundle:
    """Build causally timestamped research inputs from one immutable source vintage."""

    if source_snapshot_as_of.tzinfo is None or source_snapshot_as_of.utcoffset() is None:
        raise ValueError("source_snapshot_as_of must be timezone-aware")
    if not 0 < minimum_market_coverage <= 1:
        raise ValueError("minimum market coverage must be in (0, 1]")

    master = catalog.point_in_time(DatasetName.SECURITY_MASTER, source_snapshot_as_of)
    prices = catalog.point_in_time(DatasetName.DAILY_PRICES, source_snapshot_as_of)
    calendar = catalog.point_in_time(DatasetName.TRADING_CALENDAR, source_snapshot_as_of)
    topix = catalog.point_in_time(DatasetName.TOPIX, source_snapshot_as_of)
    disclosures = catalog.point_in_time(DatasetName.FINANCIAL_SUMMARY, source_snapshot_as_of)
    required_nonempty = {
        "security master": master,
        "daily prices": prices,
        "trading calendar": calendar,
        "TOPIX": topix,
        "financial summary": disclosures,
    }
    empty = [name for name, frame in required_nonempty.items() if frame.empty]
    if empty:
        raise ValueError(
            "BLOCKED_BY_DATA_CAPABILITY: production inputs are empty: " + ", ".join(empty)
        )
    for name, frame in required_nonempty.items():
        _assert_source_vintage(frame, source_snapshot_as_of, name)
    # Validation must not retain every full source frame through later merges.
    del required_nonempty, frame
    identity = (
        catalog.source_frame_id if isinstance(catalog, SourceIdentityCatalog) else _source_frame_id
    )
    source_snapshot_ids = tuple(
        (dataset.value, identity(dataset, frame))
        for dataset, frame in (
            (DatasetName.SECURITY_MASTER, master),
            (DatasetName.DAILY_PRICES, prices),
            (DatasetName.TRADING_CALENDAR, calendar),
            (DatasetName.TOPIX, topix),
            (DatasetName.FINANCIAL_SUMMARY, disclosures),
        )
    )

    business_dates = _bounded_business_dates(
        calendar,
        master=master,
        prices=prices,
        topix=topix,
    )
    availability = _next_proposal_cutoffs(business_dates)
    if proposal_as_of is not None:
        if proposal_as_of.tzinfo is None or proposal_as_of.utcoffset() is None:
            raise ValueError("proposal_as_of must be timezone-aware")
        local_cutoff = proposal_as_of.astimezone(_JST)
        if local_cutoff.time() != time(11, 30) or source_snapshot_as_of > proposal_as_of:
            raise ValueError("current features require a closed 11:30 source cutoff")
        future_sessions = _business_dates(calendar)
        future_sessions = future_sessions[future_sessions > business_dates[-1]]
        if len(future_sessions) == 0 or future_sessions[0].date() != local_cutoff.date():
            raise ValueError("BLOCKED_BY_DATA_CAPABILITY: next session is not authenticated")
        availability[business_dates[-1]] = pd.Timestamp(proposal_as_of).tz_convert("UTC")
    del calendar
    universe = build_point_in_time_universe(master, business_dates=business_dates)
    del master
    daily = _canonical_daily(
        prices,
        universe=universe,
        availability=availability,
        revision_policy=revision_policy,
        reuse_working_frame=price_context_only,
    )
    del prices
    financials = pd.DataFrame()
    if detail_symbols is None and not price_context_only:
        # Keep the original research/default validation and merge order.
        daily, financials = complete_daily_financials(daily, disclosures, revision_policy)
    market_context, sector_context = _aggregate_context(
        daily,
        universe=universe,
        topix=topix,
        availability=availability,
        minimum_market_coverage=minimum_market_coverage,
        revision_policy=revision_policy,
    )
    del topix
    # Common contexts always use the full historical market. Individual daily
    # financial expansion need not run for securities outside the decision set.
    if detail_symbols is not None:
        if not detail_symbols:
            raise ValueError("Empty individual calculation scope")
        daily = daily.loc[daily.symbol.isin(detail_symbols)].reset_index(drop=True)
        disclosures = disclosures.loc[disclosures.symbol.isin(detail_symbols)]
    if detail_symbols is not None and not price_context_only:
        daily, financials = complete_daily_financials(daily, disclosures, revision_policy)
    del disclosures
    corporate_actions = _corporate_actions(daily)
    return ProductionDataBundle(
        source_snapshot_as_of=source_snapshot_as_of,
        source_snapshot_ids=source_snapshot_ids,
        revision_policy=revision_policy,
        historical_revision_status=CapabilityStatus.PARTIAL,
        universe=universe,
        daily=daily,
        market_context=market_context,
        sector_context=sector_context,
        financials=financials,
        corporate_actions=corporate_actions,
    )


def complete_daily_financials(
    daily: pd.DataFrame,
    disclosures: pd.DataFrame,
    revision_policy: HistoricalRevisionPolicy,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the same PIT financial formulas for either original or cached prices."""
    financials, shares = _daily_financial_features(
        disclosures, daily=daily, revision_policy=revision_policy,
    )
    return daily.merge(
        shares, on=["symbol", "trading_date", "available_at"],
        how="left", validate="one_to_one",
    ), financials


def _source_row_hashes(frame: pd.DataFrame) -> NDArray[np.uint64]:
    """Keep the persisted 64-bit v1 NA hash on 32-bit WASM as well."""
    masked_types = (pd.arrays.IntegerArray, pd.arrays.FloatingArray, pd.arrays.BooleanArray)
    na_hash = 2305843009213693951
    if hash(pd.NA) == na_hash or not any(
        isinstance(column.array, masked_types) for _, column in frame.items()
    ):
        values = pd.util.hash_pandas_object(frame, index=False).to_numpy()
        return values.astype(np.uint64, copy=False)

    def arrays() -> Iterator[NDArray[np.uint64]]:
        for _, column in frame.items():
            values = pd.util.hash_pandas_object(column, index=False).to_numpy().astype(
                np.uint64, copy=False
            )
            if isinstance(column.array, masked_types):
                values[column.isna().to_numpy()] = np.uint64(na_hash)
            yield values

    return cast(NDArray[np.uint64], combine_hash_arrays(arrays(), len(frame.columns)))


def _source_frame_id(dataset: DatasetName, frame: pd.DataFrame) -> str:
    """Hash the exact PIT source-frame schema and values used by a derived build."""

    keys = {
        DatasetName.SECURITY_MASTER: ("effective_date", "provider_code"),
        DatasetName.DAILY_PRICES: ("trading_date", "provider_code"),
        DatasetName.TRADING_CALENDAR: ("trading_date",),
        DatasetName.TOPIX: ("trading_date",),
        DatasetName.FINANCIAL_SUMMARY: ("disclosure_number",),
    }[dataset]
    # Sort only the keys, then gather bounded row slices. Sorting the entire
    # wide source would retain another full-market copy just to hash it.
    order = frame[list(keys)].reset_index(drop=True).sort_values(list(keys)).index.to_numpy()
    schema = tuple((str(column), str(dtype)) for column, dtype in frame.dtypes.items())
    metadata = json.dumps({"dataset": dataset.value, "schema": schema}, sort_keys=True).encode(
        "utf-8"
    )
    digest = hashlib.sha256(metadata)
    # Preserve the exact ordered row-hash byte stream without factorizing
    # high-cardinality text columns for the whole market at once.
    for start in range(0, len(frame), 10000):
        rows = _source_row_hashes(frame.iloc[order[start:start + 10000]]).tobytes()
        digest.update(rows)
    return digest.hexdigest()


def build_point_in_time_universe(
    master: pd.DataFrame,
    *,
    business_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Retain exact historical master membership and derive non-backfilled intervals."""

    required = {
        "effective_date",
        "provider_code",
        "symbol",
        "sector_33_code",
        "sector_33_name",
        "market_code",
        "market_name",
        "available_at",
    }
    _require_columns(master, required, "security master")
    # Replace converted columns without copying all unchanged source arrays.
    # The filtered frame below owns its arrays before any further mutation.
    frame = master.copy(deep=False)
    frame["effective_date"] = pd.to_datetime(frame["effective_date"]).dt.normalize()
    frame["provider_code"] = frame["provider_code"].astype("string")
    frame["revision_available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    frame["market_code"] = frame["market_code"].astype("string")
    eligible = frame["provider_code"].str.endswith("0") & frame["market_code"].isin(
        _ELIGIBLE_MARKETS
    )
    frame = frame.loc[eligible].copy()
    if frame.empty:
        raise ValueError("BLOCKED_BY_DATA_CAPABILITY: no eligible common-share universe rows")
    if frame.duplicated(["effective_date", "symbol"]).any():
        raise ValueError("security master has duplicate date/symbol membership")

    required_dates = set(pd.DatetimeIndex(business_dates).normalize())
    observed_dates = set(frame["effective_date"].unique())
    missing_dates = required_dates - observed_dates
    if missing_dates:
        first = min(missing_dates).date()
        raise ValueError(
            "BLOCKED_BY_DATA_CAPABILITY: security master lacks an exact historical "
            f"snapshot for {first}"
        )

    ordered_dates = pd.DatetimeIndex(sorted(required_dates))
    date_position = {value: index for index, value in enumerate(ordered_dates)}
    positions = frame["effective_date"].map(date_position)
    # As before, one date outside the requested calendar excludes that symbol's
    # entire history. Null symbols never participate in membership intervals.
    outside_symbols = frame.loc[positions.isna(), "symbol"]
    member = frame.loc[
        frame["symbol"].notna() & ~frame["symbol"].isin(outside_symbols)
    ].sort_values(["symbol", "effective_date"])
    # Preserve the previous empty result for unused categorical groups.
    if member.empty and not (
        isinstance(frame["symbol"].dtype, pd.CategoricalDtype)
        and (frame["symbol"].value_counts() == 0).any()
    ):
        raise ValueError("BLOCKED_BY_DATA_CAPABILITY: universe interval construction is empty")
    del frame, outside_symbols
    member = member.reset_index(drop=True)
    positions = member["effective_date"].map(date_position).astype(int)
    same_symbol = member["symbol"].eq(member["symbol"].shift()).fillna(False)
    interval_id = (~same_symbol | positions.diff().ne(1)).cumsum()
    intervals = member.groupby(interval_id)["effective_date"]
    member["valid_from"] = intervals.transform("min")
    member["last_member_date"] = intervals.transform("max")
    # Format each calendar successor once, preserving the existing ISO parser
    # and its timezone/missing-value behavior without a Python loop per row.
    successors = {
        day: ordered_dates[index + 1].isoformat() if index + 1 < len(ordered_dates) else pd.NA
        for index, day in enumerate(ordered_dates)
    }
    member["valid_to"] = member["last_member_date"].map(successors).astype("string")
    member["listing_date"] = member["valid_from"]
    member["delisting_date"] = member["valid_to"]
    member["is_member"] = True
    member["eligibility_rule"] = "TSE common issue: market 0111/0112/0113 and code suffix 0"
    universe = member
    universe["valid_to"] = pd.to_datetime(universe["valid_to"], errors="coerce")
    universe["delisting_date"] = pd.to_datetime(universe["delisting_date"], errors="coerce")
    columns = [
        "effective_date",
        "provider_code",
        "symbol",
        "company_name",
        "sector_33_code",
        "sector_33_name",
        "market_code",
        "market_name",
        "listing_date",
        "delisting_date",
        "valid_from",
        "valid_to",
        "is_member",
        "eligibility_rule",
        "revision_available_at",
    ]
    optional = [column for column in columns if column in universe]
    return universe[optional].sort_values(["effective_date", "symbol"], ignore_index=True)


def _business_dates(calendar: pd.DataFrame) -> pd.DatetimeIndex:
    _require_columns(
        calendar,
        {"trading_date", "is_equity_business_day"},
        "trading calendar",
    )
    frame = calendar.copy()
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    if frame.duplicated("trading_date").any():
        raise ValueError("trading calendar contains duplicate dates")
    dates = pd.DatetimeIndex(
        frame.loc[frame["is_equity_business_day"].astype(bool), "trading_date"]
        .sort_values()
        .unique()
    )
    if len(dates) < 2:
        raise ValueError("BLOCKED_BY_DATA_CAPABILITY: trading calendar needs at least two dates")
    return dates


def _bounded_business_dates(
    calendar: pd.DataFrame,
    *,
    master: pd.DataFrame,
    prices: pd.DataFrame,
    topix: pd.DataFrame,
) -> pd.DatetimeIndex:
    """Use the contiguous common provider coverage, rejecting internal date gaps."""

    calendar_dates = _business_dates(calendar)
    _require_columns(
        master,
        {"effective_date", "provider_code", "market_code"},
        "security master",
    )
    provider_codes = master["provider_code"].astype("string")
    market_codes = master["market_code"].astype("string")
    eligible_master = master.loc[
        provider_codes.str.endswith("0", na=False) & market_codes.isin(_ELIGIBLE_MARKETS)
    ]
    source_columns = (
        ("eligible security master", eligible_master, "effective_date"),
        ("daily prices", prices, "trading_date"),
        ("TOPIX", topix, "trading_date"),
    )
    coverage: list[tuple[str, set[pd.Timestamp]]] = []
    for name, frame, column in source_columns:
        _require_columns(frame, {column}, name)
        dates = {
            pd.Timestamp(value).normalize()
            for value in pd.to_datetime(frame[column], errors="coerce").dropna().unique()
        }
        if not dates:
            raise ValueError(f"BLOCKED_BY_DATA_CAPABILITY: {name} has no dated rows")
        coverage.append((name, dates))
    start = max(min(dates) for _, dates in coverage)
    end = min(max(dates) for _, dates in coverage)
    bounded = calendar_dates[(calendar_dates >= start) & (calendar_dates <= end)]
    if len(bounded) < 2:
        raise ValueError("BLOCKED_BY_DATA_CAPABILITY: common production coverage is too short")
    expected = set(bounded)
    for name, dates in coverage:
        missing = expected - dates
        if missing:
            first = min(missing).date()
            raise ValueError(
                f"BLOCKED_BY_DATA_CAPABILITY: {name} has an internal date gap at {first}"
            )
    return bounded


def _next_proposal_cutoffs(business_dates: pd.DatetimeIndex) -> dict[pd.Timestamp, pd.Timestamp]:
    result: dict[pd.Timestamp, pd.Timestamp] = {}
    for current, following in pairwise(business_dates):
        cutoff = datetime.combine(following.date(), time(11, 30), _JST)
        result[pd.Timestamp(current)] = pd.Timestamp(cutoff).tz_convert("UTC")
    return result


def _canonical_daily(
    prices: pd.DataFrame,
    *,
    universe: pd.DataFrame,
    availability: dict[pd.Timestamp, pd.Timestamp],
    revision_policy: HistoricalRevisionPolicy,
    reuse_working_frame: bool = False,
) -> pd.DataFrame:
    required = {
        "trading_date",
        "provider_code",
        "symbol",
        "raw_close",
        "trading_value",
        "adjustment_factor",
        "research_open",
        "research_high",
        "research_low",
        "research_close",
        "research_volume",
        "adjustment_version",
        "available_at",
    }
    _require_columns(prices, required, "daily prices")
    # Only whole-column replacement occurs before merge creates the working
    # frame; the caller's original source arrays remain unchanged.
    frame = prices.copy(deep=False)
    frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.normalize()
    frame["provider_code"] = frame["provider_code"].astype("string")
    if frame.duplicated(["trading_date", "provider_code"]).any():
        raise ValueError("daily prices contain duplicate trading_date/provider_code rows")
    members = universe.rename(columns={"effective_date": "trading_date"})
    member_columns = [
        "trading_date",
        "provider_code",
        "symbol",
        "sector_33_code",
        "sector_33_name",
    ]
    frame = frame.merge(
        members[member_columns],
        on=["trading_date", "provider_code", "symbol"],
        how="inner",
        validate="one_to_one",
    )
    del members
    if frame.duplicated(["trading_date", "symbol"]).any():
        raise ValueError("PIT-universe daily prices contain duplicate trading_date/symbol rows")
    raw_ohlc = frame.reindex(columns=["raw_open", "raw_high", "raw_low", "raw_close"])
    adjusted_ohlcv = frame.reindex(
        columns=[
            "research_open",
            "research_high",
            "research_low",
            "research_close",
            "research_volume",
        ]
    )
    no_trade = (
        raw_ohlc.isna().all(axis=1)
        & adjusted_ohlcv.isna().all(axis=1)
        & frame.reindex(columns=["raw_volume", "trading_value"]).isna().all(axis=1)
    )
    del raw_ohlc, adjusted_ohlcv
    frame = _reconstruct_bulk_adjusted_prices(frame, owned_input=reuse_working_frame)
    if not reuse_working_frame or no_trade.any():
        frame = frame.loc[~no_trade].copy(deep=not reuse_working_frame)
    frame["revision_available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    frame["available_at"] = frame["trading_date"].map(availability)
    session_position = {day: index for index, day in enumerate(sorted(availability))}
    frame["trading_session_index"] = frame["trading_date"].map(session_position)
    if not reuse_working_frame or frame["available_at"].isna().any():
        frame = frame.loc[frame["available_at"].notna()].copy(deep=not reuse_working_frame)
    if revision_policy is HistoricalRevisionPolicy.STRICT_AS_KNOWN:
        frame["available_at"] = frame[["available_at", "revision_available_at"]].max(axis=1)

    observed_dates = set(frame["trading_date"])
    missing_price_dates = set(availability) - observed_dates
    if missing_price_dates:
        first = min(missing_price_dates).date()
        raise ValueError(
            f"BLOCKED_BY_DATA_CAPABILITY: daily prices contain no PIT-universe rows for {first}"
        )
    frame = frame.rename(
        columns={
            "sector_33_code": "sector",
            "research_open": "adjusted_open",
            "research_high": "adjusted_high",
            "research_low": "adjusted_low",
            "research_close": "adjusted_close",
            "research_volume": "adjusted_volume",
            "raw_close": "close",
        }
    )
    numeric = (
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "adjusted_volume",
        "close",
        "trading_value",
        "adjustment_factor",
    )
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    invalid = (
        ~np.isfinite(frame[list(numeric)].to_numpy(dtype=float)).all(axis=1)
        | (frame["adjusted_open"] <= 0)
        | (frame["adjusted_high"] <= 0)
        | (frame["adjusted_low"] <= 0)
        | (frame["adjusted_close"] <= 0)
        | (frame["close"] <= 0)
        | (frame["adjustment_factor"] <= 0)
        | (frame["adjusted_volume"] < 0)
        | (frame["trading_value"] < 0)
    )
    if invalid.any():
        raise ValueError("daily production prices contain invalid finite/positive values")
    return frame.sort_values(["trading_date", "symbol"], ignore_index=True)


def _reconstruct_bulk_adjusted_prices(
    frame: pd.DataFrame, *, owned_input: bool = False,
) -> pd.DataFrame:
    """Apply the official file-download AdjFactor formula when adjusted fields are absent."""

    # The opt-in mobile context path supplies a private merge result. It is no
    # longer shared with the original source, so another full deep copy only
    # increases WASM heap pressure. Standalone/default callers keep copy safety.
    output = frame if owned_input else frame.copy()
    adjusted = (
        "research_open",
        "research_high",
        "research_low",
        "research_close",
        "research_volume",
    )
    for column in (
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "raw_volume",
        "adjustment_factor",
        *adjusted,
    ):
        if column not in output:
            output[column] = np.nan
        output[column] = pd.to_numeric(output[column], errors="coerce")
    provided_count = output[list(adjusted)].notna().sum(axis=1)
    mixed = (provided_count > 0) & (provided_count < len(adjusted))
    if mixed.any():
        raise ValueError("daily prices contain a partial adjusted-OHLCV provider row")
    missing = provided_count.eq(0)
    if not missing.any():
        return output
    invalid_factor = (
        output["adjustment_factor"].isna()
        | ~np.isfinite(output["adjustment_factor"])
        | (output["adjustment_factor"] <= 0)
    )
    if invalid_factor.any():
        raise ValueError("daily prices cannot reconstruct adjustment from invalid AdjFactor")

    factor_columns = ["symbol", "trading_date", "adjustment_factor"]
    if "ex_rights_type" in output:
        factor_columns.append("ex_rights_type")
    ordered = output[factor_columns].sort_values(
        ["symbol", "trading_date"],
        ascending=(True, False),
    )
    price_factor = ordered.groupby("symbol", sort=False)["adjustment_factor"].transform(
        lambda values: values.shift(1, fill_value=1.0).cumprod()
    )
    ex_rights = (
        ordered["ex_rights_type"].astype("string")
        if "ex_rights_type" in ordered
        else pd.Series(pd.NA, index=ordered.index, dtype="string")
    )
    volume_event_factor = ordered["adjustment_factor"].where(ex_rights != "3", 1.0)
    volume_factor = volume_event_factor.groupby(ordered["symbol"], sort=False).transform(
        lambda values: values.shift(1, fill_value=1.0).cumprod()
    )
    ordered["__price_cum_adj"] = price_factor
    ordered["__volume_cum_adj"] = volume_factor
    factors = ordered[["__price_cum_adj", "__volume_cum_adj"]].reindex(output.index)
    for raw_column, research_column in (
        ("raw_open", "research_open"),
        ("raw_high", "research_high"),
        ("raw_low", "research_low"),
        ("raw_close", "research_close"),
    ):
        output.loc[missing, research_column] = (
            output.loc[missing, raw_column] * factors.loc[missing, "__price_cum_adj"]
        )
    output.loc[missing, "research_volume"] = (
        output.loc[missing, "raw_volume"] / factors.loc[missing, "__volume_cum_adj"]
    )
    lineage_columns = [
        "symbol",
        "trading_date",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "raw_volume",
        "adjustment_factor",
    ]
    lineage = output[lineage_columns].sort_values(["symbol", "trading_date"])
    lineage["ex_rights_type"] = (
        output.loc[lineage.index, "ex_rights_type"].astype("string")
        if "ex_rights_type" in output
        else pd.Series(pd.NA, index=lineage.index, dtype="string")
    )
    lineage_hash = hashlib.sha256(
        pd.util.hash_pandas_object(lineage, index=False).to_numpy().tobytes()
    ).hexdigest()
    output.loc[missing, "adjustment_version"] = (
        f"jquants-file-cumulative-adjfactor-v1:{lineage_hash}"
    )
    output.loc[missing, "adjustment_source"] = "official_file_adjfactor_formula_v1"
    return output


def _daily_financial_features(
    disclosures: pd.DataFrame,
    *,
    daily: pd.DataFrame,
    revision_policy: HistoricalRevisionPolicy,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {
        "symbol",
        "disclosure_number",
        "announced_at",
        "period_type",
        "period_end",
        "sales",
        "operating_profit",
        "eps",
        "equity",
        "shares_outstanding_fy",
        "treasury_shares_fy",
        "forecast_eps",
        "available_at",
    }
    _require_columns(disclosures, required, "financial summary")
    right = disclosures.copy()
    right["revision_available_at"] = pd.to_datetime(right["available_at"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    right["available_at"] = pd.to_datetime(right["announced_at"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    if revision_policy is HistoricalRevisionPolicy.STRICT_AS_KNOWN:
        right["available_at"] = right[["available_at", "revision_available_at"]].max(axis=1)
    right["period_end"] = pd.to_datetime(right["period_end"], errors="coerce").dt.normalize()
    numeric_columns = (
        "sales",
        "operating_profit",
        "eps",
        "equity",
        "shares_outstanding_fy",
        "treasury_shares_fy",
        "forecast_eps",
        "bps",
        "provider_roe",
    )
    for column in numeric_columns:
        if column not in right:
            right[column] = np.nan
        right[column] = pd.to_numeric(right[column], errors="coerce")
    right["shares_outstanding"] = right["shares_outstanding_fy"] - right["treasury_shares_fy"]
    shares_reason = pd.Series(pd.NA, index=right.index, dtype="string")
    shares_reason = shares_reason.mask(
        right["shares_outstanding_fy"].isna(),
        "fiscal shares outstanding is missing",
    )
    shares_reason = shares_reason.mask(
        right["shares_outstanding_fy"].notna() & right["treasury_shares_fy"].isna(),
        "fiscal treasury shares is missing",
    )
    invalid_shares = right["shares_outstanding"].notna() & (right["shares_outstanding"] <= 0)
    shares_reason = shares_reason.mask(invalid_shares, "derived shares outstanding is non-positive")
    right.loc[invalid_shares, "shares_outstanding"] = np.nan
    right["shares_outstanding_missing_reason"] = shares_reason
    computed_bps = right["equity"] / right["shares_outstanding"]
    right["effective_bps"] = right["bps"].where(right["bps"].notna(), computed_bps)
    provider_roe = right["provider_roe"].copy()
    provider_roe = provider_roe.where(provider_roe.abs() <= 2, provider_roe / 100)
    right["roe"] = provider_roe
    right["operating_margin"] = _safe_ratio(right["operating_profit"], right["sales"])
    right["revenue_growth_yoy"] = _point_in_time_year_over_year(right, "sales")
    right["operating_profit_growth_yoy"] = _point_in_time_year_over_year(right, "operating_profit")
    right = right.sort_values(["symbol", "available_at", "disclosure_number"])
    # The normalized V2 contract has no stronger forecast-target key. Comparing only the
    # same disclosed accounting period avoids treating a fiscal-period rollover as a revision.
    previous_forecast = right.groupby(["symbol", "period_end"], sort=False, dropna=False)[
        "forecast_eps"
    ].shift(1)
    right["forecast_revision"] = _safe_ratio(right["forecast_eps"], previous_forecast) - 1
    right.loc[previous_forecast.isna(), "forecast_revision"] = np.nan

    right_columns = [
        "available_at",
        "revision_available_at",
        "disclosure_number",
        "eps",
        "forecast_eps",
        "effective_bps",
        "roe",
        "operating_margin",
        "revenue_growth_yoy",
        "operating_profit_growth_yoy",
        "forecast_revision",
        "shares_outstanding",
        "shares_outstanding_missing_reason",
    ]
    merged_financials = _join_daily_financials(daily, right, right_columns)
    feature_columns = [
        "symbol",
        "trading_date",
        "available_at",
        "financial_available_at",
        "financial_revision_available_at",
        "disclosure_number",
        *_FINANCIAL_FEATURES,
    ]
    features = merged_financials[feature_columns].copy()
    shares = merged_financials[
        [
            "symbol",
            "trading_date",
            "available_at",
            "shares_outstanding",
            "shares_outstanding_missing_reason",
        ]
    ].copy()
    return features, shares


def _join_daily_financials(
    daily: pd.DataFrame, right: pd.DataFrame, right_columns: list[str],
) -> pd.DataFrame:
    # Batch unique UTC cutoffs, plain 64-bit closes and non-null string
    # symbols. Keep legacy semantics for other
    # callers, including categorical empty groups and unstable cutoff ties.
    if (
        not daily.empty
        and {"symbol", "available_at", "close"} <= set(daily)
        and not isinstance(daily["symbol"].dtype, pd.CategoricalDtype)
        and pd.api.types.is_string_dtype(daily["symbol"])
        and daily["symbol"].notna().all()
        and str(daily["available_at"].dtype) == "datetime64[ns, UTC]"
        and daily["available_at"].notna().all()
        and str(daily["close"].dtype) in {"float64", "int64"}
        and not daily.duplicated(["symbol", "available_at"]).any()
    ):
        return _batch_daily_financials(daily, right, right_columns)
    parts: list[pd.DataFrame] = []
    source_rows = right.groupby("symbol", sort=False, observed=True).indices
    for symbol, left in daily.groupby("symbol", sort=True):
        locations = source_rows.get(symbol)
        source = right.iloc[locations] if locations is not None else right.iloc[:0]
        source = source.loc[:, right_columns].copy()
        left_columns = left[["symbol", "trading_date", "available_at", "close"]].sort_values(
            "available_at"
        )
        left_columns["available_at"] = pd.to_datetime(
            left_columns["available_at"], utc=True
        ).astype("datetime64[ns, UTC]")
        if source.empty:
            merged = left_columns.copy()
            for column in right_columns[1:]:
                merged[column] = np.nan
            merged["financial_available_at"] = pd.NaT
            merged["financial_revision_available_at"] = pd.NaT
        else:
            source = source.sort_values(["available_at", "disclosure_number"]).drop_duplicates(
                "available_at", keep="last"
            )
            source = source.rename(
                columns={
                    "available_at": "financial_available_at",
                    "revision_available_at": "financial_revision_available_at",
                }
            )
            source["financial_available_at"] = pd.to_datetime(
                source["financial_available_at"], utc=True
            ).astype("datetime64[ns, UTC]")
            merged = pd.merge_asof(
                left_columns,
                source,
                left_on="available_at",
                right_on="financial_available_at",
                direction="backward",
                allow_exact_matches=True,
            )
        merged["per"] = merged["close"] / merged["forecast_eps"].where(
            merged["forecast_eps"].notna() & (merged["forecast_eps"] != 0),
            merged["eps"],
        )
        merged["pbr"] = _safe_ratio(merged["close"], merged["effective_bps"])
        parts.append(merged)
    merged_financials = pd.concat(parts, ignore_index=True)
    parts.clear()
    return merged_financials


def _batch_daily_financials(
    daily: pd.DataFrame, right: pd.DataFrame, right_columns: list[str],
) -> pd.DataFrame:
    left = daily[["symbol", "trading_date", "available_at", "close"]].copy()
    codes, labels = pd.factorize(left["symbol"], sort=False)
    left["__financial_symbol"] = codes.astype("int64")
    left["available_at"] = pd.to_datetime(left["available_at"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    mapping = {symbol: index for index, symbol in enumerate(labels)}
    source = right.loc[:, right_columns].copy()
    source["__financial_symbol"] = (
        right["symbol"].astype(object).map(mapping).fillna(-1).astype("int64").to_numpy()
    )
    source = source.loc[source["__financial_symbol"] >= 0]
    known = left["__financial_symbol"].isin(source["__financial_symbol"])
    parts = []
    if known.any():
        source = source.sort_values(["available_at", "disclosure_number"]).drop_duplicates(
            ["__financial_symbol", "available_at"], keep="last"
        ).rename(columns={
            "available_at": "financial_available_at",
            "revision_available_at": "financial_revision_available_at",
        })
        parts.append(pd.merge_asof(
            left.loc[known].sort_values("available_at"), source,
            left_on="available_at", right_on="financial_available_at",
            by="__financial_symbol", direction="backward", allow_exact_matches=True,
        ))
    if not known.all():
        missing = left.loc[~known].copy()
        for column in right_columns[1:]:
            missing[column] = np.nan
        missing["financial_available_at"] = pd.NaT
        missing["financial_revision_available_at"] = pd.NaT
        parts.append(missing)
        del missing
    del left, source, known, codes
    # Preserve the missing-source partition's original concat dtype behavior.
    for merged in parts:
        merged["per"] = merged["close"] / merged["forecast_eps"].where(
            merged["forecast_eps"].notna() & (merged["forecast_eps"] != 0), merged["eps"],
        )
        merged["pbr"] = _safe_ratio(merged["close"], merged["effective_bps"])
    result = parts[0] if len(parts) == 1 else pd.concat(parts, ignore_index=True)
    parts.clear()
    del merged
    result.drop(columns="__financial_symbol", inplace=True)
    result.sort_values(["symbol", "available_at"], ignore_index=True, inplace=True)
    return result


def _point_in_time_year_over_year(frame: pd.DataFrame, value_column: str) -> pd.Series:
    """Use only prior-period values disclosed by the current disclosure timestamp."""

    lookup: dict[tuple[str, str, int, int, int], float] = {}
    result_values: dict[object, float] = {}
    ordered = frame.sort_values(["available_at", "disclosure_number"], kind="mergesort")
    for index, row in ordered.iterrows():
        period_end = row["period_end"]
        value = row[value_column]
        if pd.isna(period_end):
            continue
        timestamp = pd.Timestamp(period_end)
        key = (
            str(row["symbol"]),
            str(row["period_type"]),
            timestamp.year,
            timestamp.month,
            timestamp.day,
        )
        prior = lookup.get((key[0], key[1], key[2] - 1, key[3], key[4]))
        if prior is not None and prior != 0 and pd.notna(value):
            result_values[index] = float(value) / prior - 1
        if pd.notna(value):
            lookup[key] = float(value)
    return pd.Series(result_values, dtype="float64").reindex(frame.index)


def _aggregate_context(
    daily: pd.DataFrame,
    *,
    universe: pd.DataFrame,
    topix: pd.DataFrame,
    availability: dict[pd.Timestamp, pd.Timestamp],
    minimum_market_coverage: float,
    revision_policy: HistoricalRevisionPolicy,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = daily[
        [
            "symbol",
            "sector",
            "trading_date",
            "available_at",
            "revision_available_at",
            "trading_session_index",
            "adjusted_close",
        ]
    ].copy()
    returns["return_1d"] = returns.groupby("symbol", sort=False)["adjusted_close"].pct_change(
        fill_method=None
    )
    contiguous = returns.groupby("symbol", sort=False)["trading_session_index"].diff().eq(1)
    returns.loc[~contiguous, "return_1d"] = np.nan
    eligible_count = universe.groupby("effective_date")["symbol"].nunique()
    observed = returns.groupby("trading_date").agg(
        observed_issues=("symbol", "nunique"),
        advancing_issues=("return_1d", lambda values: int((values > 0).sum())),
        declining_issues=("return_1d", lambda values: int((values < 0).sum())),
        unchanged_issues=("return_1d", lambda values: int((values == 0).sum())),
        available_at=("available_at", "max"),
        revision_available_at=("revision_available_at", "max"),
    )
    observed["eligible_issues"] = observed.index.map(eligible_count.to_dict()).astype("Int64")
    observed["coverage_ratio"] = observed["observed_issues"] / observed["eligible_issues"]
    observed["coverage_complete"] = observed["coverage_ratio"] >= minimum_market_coverage
    observed = observed.reset_index()

    topix_frame = topix.copy()
    _require_columns(topix_frame, {"trading_date", "close"}, "TOPIX")
    topix_frame["trading_date"] = pd.to_datetime(topix_frame["trading_date"]).dt.normalize()
    if topix_frame.duplicated("trading_date").any():
        raise ValueError("TOPIX contains duplicate dates")
    topix_frame["topix_close"] = pd.to_numeric(topix_frame["close"], errors="coerce")
    invalid_topix = ~np.isfinite(topix_frame["topix_close"]) | (topix_frame["topix_close"] <= 0)
    if invalid_topix.any():
        raise ValueError("TOPIX production prices must be finite and positive")
    topix_frame["topix_revision_available_at"] = pd.to_datetime(
        topix_frame["available_at"], utc=True
    )
    topix_frame["topix_available_at"] = topix_frame["trading_date"].map(availability)
    if revision_policy is HistoricalRevisionPolicy.STRICT_AS_KNOWN:
        topix_frame["topix_available_at"] = topix_frame[
            ["topix_available_at", "topix_revision_available_at"]
        ].max(axis=1)
    topix_frame = topix_frame.loc[topix_frame["topix_available_at"].notna()]
    market = observed.merge(
        topix_frame[
            [
                "trading_date",
                "topix_close",
                "topix_available_at",
                "topix_revision_available_at",
            ]
        ],
        on="trading_date",
        how="left",
        validate="one_to_one",
    )
    if market["topix_close"].isna().any():
        first = market.loc[market["topix_close"].isna(), "trading_date"].min().date()
        raise ValueError(f"BLOCKED_BY_DATA_CAPABILITY: TOPIX coverage is missing for {first}")
    market["available_at"] = market[["available_at", "topix_available_at"]].max(axis=1)
    market["revision_available_at"] = market[
        ["revision_available_at", "topix_revision_available_at"]
    ].max(axis=1)

    sector_eligible = universe.groupby(["sector_33_code", "effective_date"])["symbol"].nunique()
    sector = returns.groupby(["sector", "trading_date"]).agg(
        sector_return_1d=("return_1d", "mean"),
        observed_issues=("symbol", "nunique"),
        available_at=("available_at", "max"),
        revision_available_at=("revision_available_at", "max"),
    )
    sector["eligible_issues"] = [
        sector_eligible.get((sector_code, trading_date), 0)
        for sector_code, trading_date in sector.index
    ]
    sector["coverage_ratio"] = sector["observed_issues"] / sector["eligible_issues"]
    sector["coverage_complete"] = sector["coverage_ratio"] >= minimum_market_coverage
    sector.loc[~sector["coverage_complete"], "sector_return_1d"] = np.nan
    return (
        market.sort_values("trading_date").reset_index(drop=True),
        sector.reset_index().sort_values(["trading_date", "sector"]).reset_index(drop=True),
    )


def _corporate_actions(daily: pd.DataFrame) -> pd.DataFrame:
    actions = daily.loc[
        ~np.isclose(daily["adjustment_factor"].astype(float), 1.0),
        [
            "symbol",
            "provider_code",
            "trading_date",
            "adjustment_factor",
            "adjustment_version",
            "available_at",
            "revision_available_at",
        ],
    ].copy()
    actions = actions.rename(columns={"trading_date": "effective_date"})
    actions["action_type"] = "provider_price_adjustment"
    actions["ratio"] = 1 / actions["adjustment_factor"]
    actions["announcement_at"] = pd.NaT
    actions["announcement_at_missing_reason"] = "not provided by daily price endpoint"
    return actions.sort_values(["effective_date", "symbol"]).reset_index(drop=True)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = pd.to_numeric(numerator, errors="coerce") / pd.to_numeric(denominator, errors="coerce")
    return result.where(np.isfinite(result), np.nan)


def _require_columns(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"{label} is missing required columns: {sorted(missing)}")


def _assert_source_vintage(
    frame: pd.DataFrame,
    source_snapshot_as_of: datetime,
    label: str,
) -> None:
    _require_columns(frame, {"available_at"}, label)
    revision_time = pd.to_datetime(frame["available_at"], utc=True)
    if revision_time.isna().any():
        raise ValueError(f"{label} contains a missing source revision timestamp")
    if (revision_time > pd.Timestamp(source_snapshot_as_of)).any():
        raise ValueError(f"{label} contains a revision after source_snapshot_as_of")
