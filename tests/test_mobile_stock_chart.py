from __future__ import annotations

import asyncio
import copy
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from mobile.python import forecasts, market, stock_chart

from tests.test_mobile_forecasts import NOW
from tests.test_mobile_market import payload

pytest_plugins = ("tests.test_mobile_forecasts",)


def test_realized_requires_calendar_and_exact_adjusted_closes():
    first = date(2026, 2, 2)
    days = [first + timedelta(days=n) for n in range(1, 10)]
    calendar = {str(day): day.weekday() < 5 for day in days}
    prices = {
        str(day): {"adjustedClose": float(100 + i), "adjustmentFactor": 1}
        for i, day in enumerate(days)
    }
    result = stock_chart.realized(first, 5, days[-1], calendar, prices)
    assert result == {
        "status": "available",
        "entryDate": "2026-02-03",
        "exitDate": "2026-02-10",
        "return": 107 / 100 - 1,
    }
    missing = dict(calendar)
    del missing["2026-02-07"]  # A missing Saturday cannot be assumed to be a closure.
    assert stock_chart.realized(first, 5, days[-1], missing, prices)["status"] == "calendar_missing"
    prices["2026-02-05"]["adjustmentFactor"] = 0.5
    assert (
        stock_chart.realized(first, 5, days[-1], calendar, prices)["status"] == "corporate_action"
    )
    prices["2026-02-05"]["adjustmentFactor"] = 1
    del prices["2026-02-10"]
    assert stock_chart.realized(first, 5, days[-1], calendar, prices)["status"] == "price_missing"
    assert stock_chart.realized(first, 20, days[-1], calendar, prices)["status"] == "pending"


def test_calendar_uses_verified_prior_batch_with_forward_dates(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    batch_day = date(2026, 1, 30)
    value = _history(batch_day, datetime(2026, 1, 31, tzinfo=UTC), 100)
    value["datasets"]["trading_calendar"] = [
        {
            "Date": str(batch_day + timedelta(days=i)),
            "HolDiv": "1" if (batch_day + timedelta(days=i)).weekday() < 5 else "0",
        }
        for i in range(12)
    ]
    market.ingest(path, value)
    calendar = stock_chart._calendar(
        path, date(2026, 2, 3), date(2026, 2, 6), datetime(2026, 2, 7, tzinfo=UTC)
    )
    assert calendar == {
        "2026-02-03": True,
        "2026-02-04": True,
        "2026-02-05": True,
        "2026-02-06": True,
    }


def _history(day: date, receipt: datetime, price: float):
    value = copy.deepcopy(payload())
    value["date"] = str(day)
    value["received_at"] = receipt.isoformat()
    for records in value["datasets"].values():
        for row in records:
            row["Date"] = str(day)
    value["datasets"]["trading_calendar"][0]["HolDiv"] = "1" if day.weekday() < 5 else "0"
    if day.weekday() >= 5:
        value["datasets"]["daily_prices"] = []
    else:
        row = value["datasets"]["daily_prices"][0]
        row.update(
            O=price,
            H=price + 1,
            L=price - 1,
            C=price,
            Vo=1000,
            AdjO=price,
            AdjH=price + 1,
            AdjL=price - 1,
            AdjC=price,
            AdjVo=1000,
        )
    return value


def test_chart_reads_verified_sources_and_distinguishes_saved_forecast_from_actual(ready):
    _, store, path, _, _, _ = ready
    forecast = forecasts.generate(path, store, NOW)
    portfolio_before = store.latest_portfolio()
    receipt = datetime(2026, 3, 10, tzinfo=UTC)
    start = date(2026, 2, 3)
    for i in range(31):
        market.ingest(path, _history(start + timedelta(days=i), receipt, 100 + i))
    # A later, authenticated correction is visible only once received.
    market.ingest(path, _history(start, receipt + timedelta(days=2), 200))
    before = stock_chart.read(path, store, "7203", receipt + timedelta(days=1), days=90)
    after = stock_chart.read(path, store, "7203", receipt + timedelta(days=3), days=90)
    assert before["prices"][0]["close"] == 1  # Existing January history is preserved.
    assert next(p for p in before["prices"] if p["date"] == str(start))["close"] == 100
    assert next(p for p in after["prices"] if p["date"] == str(start))["close"] == 200
    assert len(after["forecasts"]) == 1
    saved = after["forecasts"][0]
    assert saved["snapshotId"] == forecast["snapshot"]["snapshot_id"]
    assert saved["priceDate"] == "2026-02-02" and saved["kind"] == "daily"
    five, twenty = saved["horizons"]
    assert five["expectedReturn"] == 0.01 and five["return"] == pytest.approx(107 / 200 - 1)
    assert five["entryDate"] == "2026-02-03" and five["exitDate"] == "2026-02-10"
    assert twenty["expectedReturn"] == 0.04 and twenty["status"] == "available"
    assert twenty["entryDate"] == "2026-02-03" and twenty["exitDate"] == "2026-03-03"
    assert twenty["return"] == pytest.approx(128 / 200 - 1)
    assert store.latest_portfolio() == portfolio_before

    with sqlite3.connect(path) as db:
        db.execute("UPDATE mobile_forecast_runs SET content_hash=?", ("0" * 64,))
    with pytest.raises(ValueError, match="receipt changed"):
        stock_chart.read(path, store, "7203", receipt + timedelta(days=3), days=90)


def test_runtime_chart_is_read_only_and_rejects_tampered_market(ready, monkeypatch):
    device, store, path, _, _, _ = ready
    forecasts.generate(path, store, NOW)
    clock = datetime(2026, 2, 4, tzinfo=UTC)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock if tz is None else clock.astimezone(tz)

    monkeypatch.setattr(device, "datetime", FixedDatetime)
    before = store.latest_portfolio()
    result = asyncio.run(device.request("GET", "/api/v1/mobile/stocks/7203/chart?days=90"))
    assert result["status"] == 200
    assert result["body"]["forecasts"][0]["horizons"][0]["status"] == "calendar_missing"
    assert result["body"]["forecasts"][0]["horizons"][0]["return"] is None
    assert store.latest_portfolio() == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE market_batches SET raw=? WHERE dataset='daily_prices'", (b"broken",))
    rejected = asyncio.run(device.request("GET", "/api/v1/mobile/stocks/7203/chart?days=90"))
    assert rejected["status"] == 422 and "確認できません" in rejected["body"]["detail"]


def test_older_unlinked_snapshot_is_listed_without_guessing_price_date(ready):
    _, store, path, _, _, _ = ready
    forecast = forecasts.generate(path, store, NOW)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM mobile_forecast_runs")  # Synthetic pre-mobile-receipt record.
    result = stock_chart.read(path, store, "7203", NOW + timedelta(days=2), days=90)
    assert len(result["forecasts"]) == 1
    old = result["forecasts"][0]
    assert old["snapshotId"] == forecast["snapshot"]["snapshot_id"]
    assert old["kind"] == "archive" and old["priceDate"] is None
    assert old["horizons"][0]["expectedReturn"] == 0.01
    assert old["horizons"][0]["status"] == "price_date_missing"
    assert old["horizons"][0]["return"] is None


def test_runtime_chart_rejects_tampered_original_snapshot(ready, monkeypatch):
    device, store, _, _, _, _ = ready
    forecasts.generate(device.STATE / "mobile.sqlite3", store, NOW)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = NOW + timedelta(days=1)
            return current if tz is None else current.astimezone(tz)

    monkeypatch.setattr(device, "datetime", FixedDatetime)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE prediction_snapshots SET content_hash=?", ("0" * 64,))
    rejected = asyncio.run(device.request("GET", "/api/v1/mobile/stocks/7203/chart?days=90"))
    assert rejected["status"] == 422 and "確認できません" in rejected["body"]["detail"]


def test_reference_and_daily_predictions_remain_separate(ready, monkeypatch):
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
    result = stock_chart.read(path, store, "7203", reference_time + timedelta(days=1))
    assert {item["kind"] for item in result["forecasts"]} == {"daily", "reference"}
    assert {item["snapshotId"] for item in result["forecasts"]} == {
        daily["snapshot"]["snapshot_id"],
        reference["snapshot"]["snapshot_id"],
    }
    assert store.latest_prediction_snapshot().snapshot_id == daily["snapshot"]["snapshot_id"]
