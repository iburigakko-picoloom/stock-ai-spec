from __future__ import annotations

import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from mobile.python import features, market
from scripts.mobile_capacity_check import initial_cutoff, make_payload

from stock_ai.fixtures import market_fixture


def frozen_selection():
    source = next(
        (Path(__file__).resolve().parents[1] / "artifacts/selections/goal3-features").glob(
            "*/*.json"
        )
    )
    return json.loads(source.read_text(encoding="utf-8"))["feature_selection"]


def timely_history(path, sessions=270, symbols=4):
    """Synthetic initial download only; no production fixture transport or models."""
    market.initialize(path)
    cutoff = initial_cutoff(sessions)
    receipt = cutoff - timedelta(minutes=30)
    rng = random.Random(20261017)
    day = date(2024, 1, 2)
    for index in range(sessions):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        market.ingest(path, make_payload(day, index, symbols, rng, initial_receipt=receipt))
        day += timedelta(days=1)
    return cutoff


def typed_frame():
    return pd.DataFrame(
        {
            "code": pd.Series(["0123", "1A00", None] * 4, dtype="string"),
            "nullable_int": pd.Series([1, None, -2] * 4, dtype="Int64"),
            "nullable_bool": pd.Series([True, None, False] * 4, dtype="boolean"),
            "float": pd.Series([None, 1.23e17, -0.0, 1.2e-9] * 3, dtype="Float64"),
            "when": pd.date_range("2026-01-01", periods=12, freq="123456789ns", tz="Asia/Tokyo"),
            "date_missing": pd.Series([pd.Timestamp("2026-01-01", tz="UTC"), pd.NaT] * 6),
            "date_null": pd.Series([pd.NaT] * 12, dtype="datetime64[ns, UTC]"),
            "objects": ["合成/😀", None, "0000123"] * 4,
            "nested": [{"value": [1, False, None]}] * 12,
            "decimal": [Decimal("1.234567891234")] * 12,
            "all_null": [None] * 12,
            "nonfinite": [np.nan, np.inf, -np.inf] * 4,
        }
    )


@pytest.mark.parametrize(
    "kind",
    ["daily", "market", "sector", "financials", "typed", "empty", "one-row", "numeric-label"],
)
def test_columnwise_roundtrip_matches_original_records_values_types_and_precision(kind):
    frames = dict(
        zip(("daily", "market", "sector", "financials"), market_fixture(270), strict=True)
    )
    frames.update(
        typed=typed_frame(),
        empty=pd.DataFrame({"a": pd.Series(dtype="Int64")}),
        **{
            "one-row": pd.DataFrame({"code": ["0000"], "flag": [False], "n": [0.0]}),
            "numeric-label": pd.DataFrame({1: [1, None], 2: [2, 3]}),
        },
    )
    source = frames[kind]
    original = source.copy(deep=True)
    expected = pd.DataFrame.from_records(
        json.loads(source.to_json(orient="records", date_format="iso", date_unit="ns"))
    )
    actual = features._json_records_frame(source)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual.to_json(orient="table", date_format="iso", date_unit="ns") == expected.to_json(
        orient="table", date_format="iso", date_unit="ns"
    )
    pd.testing.assert_frame_equal(source, original, check_exact=True)
    if kind == "typed":
        # pandas timezone JSON supports Python datetime microseconds;
        # preserve those instead of the previous millisecond truncation.
        assert list(pd.to_datetime(actual["when"], utc=True)) == list(
            source["when"].dt.floor("us"))
        old = json.loads(source.to_json(orient="records", date_format="iso"))
        pd.testing.assert_series_equal(actual["float"], pd.DataFrame(old)["float"])


@pytest.mark.parametrize(
    "scenario", ["normal", "missing-financials", "older-last-row", "late-context"]
)
def test_dataframe_feature_inputs_produce_the_same_frozen_json_as_records(scenario):
    daily, market, sector, financials = market_fixture(270)
    cutoff = daily.available_at.max()
    first = sorted(daily.symbol.unique())[0]
    if scenario == "missing-financials":
        financials = financials.loc[financials.symbol != first].copy()
    elif scenario == "older-last-row":
        latest = daily.trading_date.max() - timedelta(days=5)
        daily = daily.loc[(daily.symbol != first) | (daily.trading_date < latest)].copy()
    elif scenario == "late-context":
        latest = sector.trading_date.max()
        sector.loc[sector.trading_date == latest, "available_at"] += timedelta(minutes=1)
        cutoff += timedelta(minutes=2)
    native = dict(
        zip(
            ("daily", "market", "sector", "financials"),
            (daily, market, sector, financials),
            strict=True,
        )
    )
    original = {name: frame.copy(deep=True) for name, frame in native.items()}
    legacy = {
        name: json.loads(frame.to_json(orient="records", date_format="iso", date_unit="ns"))
        for name, frame in native.items()
    }
    native["as_of"] = legacy["as_of"] = cutoff.isoformat()
    selection = frozen_selection()
    reference = features.calculate(native, selection)
    assert reference == features.calculate(legacy, selection)
    focused = {**native, "decision_symbols": [first]}
    for name in ("daily", "financials"):
        focused[name] = native[name].loc[native[name].symbol == first].copy()
    expected = {**reference, "features": {
        horizon: [row for row in rows if row["symbol"] == first]
        for horizon, rows in reference["features"].items()},
        "excluded_for_insufficient_history": [
            symbol for symbol in reference["excluded_for_insufficient_history"]
            if symbol == first]}
    assert features.calculate(focused, selection) == expected
    for name, frame in original.items():
        pd.testing.assert_frame_equal(native[name], frame, check_exact=True)


def test_timely_market_inputs_match_records_and_preserve_frozen_source_identity(tmp_path):
    path = tmp_path / "market.sqlite3"
    cutoff = timely_history(path)
    legacy = market.feature_inputs(path, cutoff)
    native = market.feature_inputs(path, cutoff, True)
    for name in ("as_of", "latest_source_received_at", "source_snapshot_ids", "revision_policy"):
        assert legacy[name] == native[name]
    for name in ("daily", "financials", "market", "sector"):
        pd.testing.assert_frame_equal(
            features._json_records_frame(native[name]),
            features.model_input_frame(name, pd.DataFrame.from_records(legacy[name])),
            check_exact=True,
        )
    assert len(native["daily"]) == 4 * 270
    reference = features.calculate(native, frozen_selection())
    assert reference == features.calculate(legacy, frozen_selection())
    symbols = sorted(native["daily"].symbol.unique())
    # One candidate plus a holding outside that candidate's selection. Shared
    # market/sector inputs still cover every original security and session.
    selected = [symbols[0], symbols[-1]]
    focused = market.feature_inputs(path, cutoff, True, decision_symbols=selected)
    assert focused["decision_symbols"] == selected
    for key in ("as_of", "latest_source_received_at", "source_snapshot_ids", "revision_policy"):
        assert focused[key] == native[key]
    for name in ("market", "sector"):
        pd.testing.assert_frame_equal(focused[name], native[name], check_exact=True)
    for name in ("daily", "financials"):
        expected_frame = native[name].loc[native[name].symbol.isin(selected)].reset_index(drop=True)
        pd.testing.assert_frame_equal(focused[name], expected_frame, check_exact=True)
    expected = {**reference, "features": {
        horizon: [row for row in rows if row["symbol"] in selected]
        for horizon, rows in reference["features"].items()},
        "excluded_for_insufficient_history": [
            symbol for symbol in reference["excluded_for_insufficient_history"]
            if symbol in selected]}
    assert features.calculate(focused, frozen_selection()) == expected
    absent = market.feature_inputs(path, cutoff, True, decision_symbols=["9999"])
    missing = features.calculate(absent, frozen_selection())
    assert missing["features"] == {"5": [], "20": []}
    assert missing["excluded_for_insufficient_history"] == []
    with pytest.raises(ValueError, match="cutoff is not closed"):
        market.feature_inputs(path, cutoff - timedelta(seconds=1), True)


@pytest.mark.parametrize("scope", [[], "1000", ["1000", "1000"], [None], [""]])
def test_invalid_feature_scope_is_rejected_before_opening_the_source(tmp_path, scope):
    path = tmp_path / "not-created.sqlite3"
    with pytest.raises(ValueError, match="calculation scope"):
        market.feature_inputs(path, initial_cutoff(270), True, decision_symbols=scope)
    assert not path.exists()


def test_focused_inputs_keep_insufficient_history_explicit_and_reject_extra_symbols():
    daily, context, sector, financials = market_fixture(270)
    symbol = sorted(daily.symbol.unique())[0]
    short = daily.loc[daily.symbol == symbol].tail(5)
    daily = pd.concat([daily.loc[daily.symbol != symbol], short], ignore_index=True)
    original = dict(as_of=daily.available_at.max().isoformat(), daily=daily,
                    market=context, sector=sector, financials=financials)
    reference = features.calculate(original, frozen_selection())
    focused = {**original, "decision_symbols": [symbol], "daily": short.copy(),
               "financials": financials.loc[financials.symbol == symbol].copy()}
    result = features.calculate(focused, frozen_selection())
    assert result["features"] == {"5": [], "20": []}
    assert result["excluded_for_insufficient_history"] == [symbol]
    assert symbol in reference["excluded_for_insufficient_history"]
    assert result["required_history_sessions"] == reference["required_history_sessions"]
    with pytest.raises(ValueError, match="differ from the decision-symbol scope"):
        features.calculate({**original, "decision_symbols": [symbol]}, frozen_selection())


@pytest.mark.parametrize("availability_only", [False, True])
def test_focused_missing_financial_source_schema_is_still_rejected(availability_only):
    daily, context, sector, _ = market_fixture(270)
    financials = (pd.DataFrame({"available_at": pd.Series(dtype="datetime64[ns, UTC]")})
                  if availability_only else pd.DataFrame())
    payload = dict(as_of=daily.available_at.max().isoformat(), daily=daily,
                   market=context, sector=sector, financials=financials,
                   decision_symbols=sorted(daily.symbol.unique()))
    with pytest.raises(ValueError, match=r"missing|required"):
        features.calculate(payload, frozen_selection())
