from __future__ import annotations

import random
import sqlite3
from datetime import timedelta
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from mobile.python import input_cache, market
from scripts.mobile_capacity_check import make_payload

from tests.test_mobile_features import timely_history


def assert_same(actual, expected):
    for name in ("daily", "financials", "market", "sector"):
        pd.testing.assert_frame_equal(actual[name], expected[name], check_exact=True)
    assert dict(actual["source_snapshot_ids"]) == dict(expected["source_snapshot_ids"])
    for name in ("as_of", "latest_source_received_at", "revision_policy", "decision_symbols"):
        assert actual[name] == expected[name]


def test_cache_codec_preserves_bits_null_masks_and_timezones():
    original = pd.DataFrame(
        {
            "f": [np.nextafter(1.0, 2.0), -0.0, np.nan],
            "n": pd.Series([1.2345678912345678, None, -0.0], dtype="Float64"),
            "i": pd.Series([1, None, -2], dtype="Int64"),
            "s": pd.Series(["合成", None, "0001"], dtype="string"),
            "b": pd.Series([True, None, False], dtype="boolean"),
            "t": pd.date_range("2026-01-01", periods=3, freq="123456789ns", tz="Asia/Tokyo"),
        }
    )
    actual = input_cache._unpack(input_cache._pack(original))
    pd.testing.assert_frame_equal(actual, original, check_exact=True)
    assert actual.f.iloc[0].hex() == original.f.iloc[0].hex()
    assert np.signbit(actual.f.iloc[1])


def test_cold_warm_restart_and_append_equal_full_market_calculation(tmp_path, monkeypatch):
    path = tmp_path / "mobile.sqlite3"
    cutoff = timely_history(path, sessions=12)
    # Missing history must remain an explicit empty cached member, including
    # after the index avoids a full-history scan for every symbol.
    selected = ["1000", "1003", "9999"]
    expected = market.feature_inputs(path, cutoff, True, decision_symbols=selected)
    first = market.feature_inputs(path, cutoff, True, decision_symbols=selected, preselected=True)
    assert_same(first, expected)
    assert first["input_cache"]["mode"] == "cold"
    # Recreating readers after process restart must not decode long raw sources.
    original = market.FeatureSource.point_in_time
    monkeypatch.setattr(
        market.FeatureSource,
        "point_in_time",
        lambda *a: pytest.fail("warm cache decoded broad history"),
    )
    warm = market.feature_inputs(path, cutoff, True, decision_symbols=selected, preselected=True)
    assert_same(warm, expected)
    assert warm["input_cache"]["mode"] == "warm"
    monkeypatch.setattr(market.FeatureSource, "point_in_time", original)
    next_cutoff = cutoff + timedelta(days=1)
    while next_cutoff.weekday() >= 5:
        next_cutoff += timedelta(days=1)
    day = cutoff.date()
    addition = make_payload(
        day, 12, 4, random.Random(99), initial_receipt=next_cutoff - timedelta(minutes=30)
    )
    market.ingest(path, addition)
    expected = market.feature_inputs(path, next_cutoff, True, decision_symbols=selected)
    actual = market.feature_inputs(
        path, next_cutoff, True, decision_symbols=selected, preselected=True
    )
    assert_same(actual, expected)
    assert actual["input_cache"]["mode"] == "append"
    assert actual["input_cache"]["raw_snapshot_days"] == 4
    assert actual["input_cache"]["raw_source_rows"] == 16


@pytest.mark.parametrize("event", ["correction", "split", "holding-added", "code-version"])
def test_invalidating_changes_rebuild_without_changing_results(tmp_path, monkeypatch, event):
    path = tmp_path / "mobile.sqlite3"
    cutoff = timely_history(path, sessions=8)
    selected = ["1000"]
    market.feature_inputs(path, cutoff, True, decision_symbols=selected, preselected=True)
    if event in ("correction", "split"):
        day = cutoff.date() - timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        changed = make_payload(
            day, 7, 4, random.Random(77), initial_receipt=cutoff - timedelta(minutes=10)
        )
        changed["acquisitionId"] = str(uuid4())
        if event == "split":
            changed["datasets"]["daily_prices"][0]["AdjFactor"] = 0.5
        market.ingest(path, changed)
    elif event == "holding-added":
        selected.append("1003")
    else:
        monkeypatch.setattr(input_cache, "code_version", lambda: "changed code")
    expected = market.feature_inputs(path, cutoff, True, decision_symbols=selected)
    actual = market.feature_inputs(path, cutoff, True, decision_symbols=selected, preselected=True)
    assert_same(actual, expected)
    assert actual["input_cache"]["mode"] == "rebuild"


def test_corrupted_cache_fails_before_returning_forecasts(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    cutoff = timely_history(path, sessions=5)
    market.feature_inputs(path, cutoff, True, decision_symbols=["1000"], preselected=True)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE mobile_input_cache SET payload=? WHERE name='symbol:1000'", (b"bad",))
    with pytest.raises(ValueError, match="cache content changed"):
        market.feature_inputs(path, cutoff, True, decision_symbols=["1000"], preselected=True)


def test_interrupted_cache_rebuild_keeps_previous_cache_and_all_raw_data(tmp_path, monkeypatch):
    path = tmp_path / "mobile.sqlite3"
    cutoff = timely_history(path, sessions=5)
    market.feature_inputs(path, cutoff, True, decision_symbols=["1000"], preselected=True)
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT * FROM mobile_input_cache ORDER BY name").fetchall()
        raw = db.execute("SELECT * FROM market_batches ORDER BY sequence").fetchall()
    original = input_cache._put

    def interrupted(db, name, payload):
        original(db, name, payload)
        if name == "sector":
            raise OSError("simulated write interruption")

    monkeypatch.setattr(input_cache, "_put", interrupted)
    with pytest.raises(OSError, match="write interruption"):
        market.feature_inputs(
            path, cutoff, True, decision_symbols=["1000", "1003"], preselected=True
        )
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM mobile_input_cache ORDER BY name").fetchall() == before
        assert db.execute("SELECT * FROM market_batches ORDER BY sequence").fetchall() == raw
