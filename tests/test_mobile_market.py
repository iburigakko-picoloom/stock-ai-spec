from __future__ import annotations

import copy
import sqlite3
from datetime import datetime

import pytest
from mobile.python import market

from stock_ai.data.contracts import ENDPOINT_SCHEMAS, DatasetName


def payload():
    day = "2026-01-05"
    datasets = {name.value: [] for name in DatasetName}
    master = {key: "0" for key in ENDPOINT_SCHEMAS[DatasetName.SECURITY_MASTER].required_columns}
    master.update(Date=day, Code="72030", Mkt="0111", CoName="synthetic fixture", S33="3700")
    prices = {key: 1 for key in ENDPOINT_SCHEMAS[DatasetName.DAILY_PRICES].required_columns}
    prices.update(Date=day, Code="72030", H=2, AdjH=2, L=0.5, AdjL=0.5)
    datasets["security_master"] = [master]
    datasets["daily_prices"] = [prices]
    datasets["trading_calendar"] = [{"Date": day, "HolDiv": "1"}]
    datasets["topix"] = [{"Date": day, "O": 1, "H": 2, "L": 0.5, "C": 1}]
    return {"date": day, "received_at": "2026-01-06T08:00:00+00:00", "datasets": datasets}


def test_delta_ingestion_is_idempotent_and_retains_exact_receipt_boundary(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    value = payload()
    assert market.ingest(path, value)["completed_days"] == 1
    market.ingest(path, value)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM market_batches").fetchone()[0] == 5
    reader = market.SQLiteSource(path)
    assert reader.point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat("2026-01-06T07:59:59+00:00")
    ).empty
    known = reader.point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat(value["received_at"])
    )
    assert known.iloc[0].raw_close == 1


def test_later_correction_does_not_replace_earlier_known_price(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    original = payload()
    market.ingest(path, original)
    corrected = copy.deepcopy(original)
    corrected["received_at"] = "2026-01-07T08:00:00+00:00"
    corrected["datasets"]["daily_prices"][0].update(C=1.5, AdjC=1.5)
    market.ingest(path, corrected)
    reader = market.SQLiteSource(path)
    before = reader.point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat(original["received_at"])
    )
    after = reader.point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat(corrected["received_at"])
    )
    assert before.iloc[0].raw_close == 1
    assert after.iloc[0].raw_close == 1.5


def test_partial_or_invalid_day_cannot_advance_success_watermark(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    incomplete = payload()
    incomplete["datasets"]["daily_prices"] = []
    with pytest.raises(ValueError):
        market.ingest(path, incomplete)
    invalid = payload()
    invalid["datasets"]["daily_prices"][0]["H"] = -1
    with pytest.raises(ValueError):
        market.ingest(path, invalid)
    assert market.status(path)["latest_data_date"] is None
    assert market.status(path)["latest_forecast_available"] is False
