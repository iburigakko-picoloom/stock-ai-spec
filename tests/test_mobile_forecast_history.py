from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta

import pytest
from mobile.python import forecast_history, forecasts, market

from tests.test_mobile_forecasts import NOW

pytest_plugins = ("tests.test_mobile_forecasts",)


def test_history_includes_today_and_both_predictions_without_market_reads(ready, monkeypatch):
    _, store, path, *_ = ready
    saved = forecasts.generate(path, store, NOW)
    before = store.latest_portfolio()
    monkeypatch.setattr(
        "mobile.python.stock_chart._prices", lambda *args: pytest.fail("market read")
    )
    monkeypatch.setattr(
        "mobile.python.stock_chart._calendar", lambda *args: pytest.fail("calendar read")
    )
    result = forecast_history.read(path, store, "7203", NOW + timedelta(seconds=1), days=30)
    assert result["lastDate"] == "2026-02-03"
    assert len(result["forecasts"]) == 1
    row = result["forecasts"][0]
    assert row["snapshotId"] == saved["snapshot"]["snapshot_id"]
    assert row["date"] == "2026-02-03"
    assert row["return5d"] == 0.01 and row["return20d"] == 0.04
    assert not forecast_history.read(path, store, "7203", NOW + timedelta(days=31), days=30)[
        "forecasts"
    ]
    assert store.latest_portfolio() == before


def test_old_archived_prediction_remains_visible_without_receipt(ready):
    _, store, path, *_ = ready
    saved = forecasts.generate(path, store, NOW)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM mobile_forecast_runs")
    result = forecast_history.read(path, store, "7203", NOW + timedelta(days=1))
    assert len(result["forecasts"]) == 1
    row = result["forecasts"][0]
    assert row["kind"] == "archive"
    assert row["snapshotId"] == saved["snapshot"]["snapshot_id"]
    assert (row["return5d"], row["return20d"]) == (0.01, 0.04)


def test_same_day_daily_and_reference_are_kept_separate(ready, monkeypatch):
    _, store, path, selected, features, _ = ready
    daily = forecasts.generate(path, store, NOW)
    reference_time = NOW + timedelta(minutes=1)
    selected["as_of"] = reference_time.isoformat()
    features["as_of"] = reference_time.isoformat()
    for rows in features["features"].values():
        for row in rows:
            row["available_at"] = reference_time.isoformat()

    def reference_inputs(*args, **kwargs):
        assert kwargs["reference_only"] is True
        return {
            "as_of": reference_time.isoformat(),
            "latest_source_received_at": NOW.isoformat(),
            "reference_price_date": selected["latest_source_date"],
            "source_snapshot_ids": [(name.value, "4" * 64) for name in market.DatasetName],
            "revision_policy": "synthetic-fixture-conservative",
        }

    monkeypatch.setattr(forecasts.market, "feature_inputs", reference_inputs)
    reference = forecasts.generate(path, store, reference_time, reference_only=True)
    result = forecast_history.read(path, store, "7203", reference_time + timedelta(seconds=1))
    rows = result["forecasts"]
    assert [row["kind"] for row in rows] == ["daily", "reference"]
    assert rows[0]["date"] == rows[1]["date"] == "2026-02-03"
    assert [row["snapshotId"] for row in rows] == [
        daily["snapshot"]["snapshot_id"], reference["snapshot"]["snapshot_id"]
    ]


def test_history_api_rejects_tampered_original(ready, monkeypatch):
    device, store, path, *_ = ready
    forecasts.generate(path, store, NOW)

    class FixedDatetime(type(NOW)):
        @classmethod
        def now(cls, tz=None):
            current = NOW + timedelta(seconds=1)
            return current if tz is None else current.astimezone(tz)

    monkeypatch.setattr(device, "datetime", FixedDatetime)
    url = "/api/v1/mobile/stocks/7203/forecast-history?days=90"
    response = asyncio.run(device.request("GET", url))
    assert response["status"] == 200
    assert response["body"]["forecasts"][0]["return5d"] == 0.01
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE prediction_snapshots SET content_hash=?", ("0" * 64,))
    response = asyncio.run(device.request("GET", url))
    assert response["status"] == 422
