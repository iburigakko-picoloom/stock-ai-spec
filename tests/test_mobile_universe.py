from __future__ import annotations

import copy
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from mobile.python import market, universe

from stock_ai.data.contracts import ENDPOINT_SCHEMAS, DatasetName

CUTOFF = datetime.fromisoformat("2026-02-03T11:30:00+09:00")
RECEIPT = "2026-02-03T01:00:00+00:00"


def daily(day, count=303):
    values = {name.value: [] for name in DatasetName}
    for index in range(count):
        code = str(10000 + index * 10)
        master = dict.fromkeys(ENDPOINT_SCHEMAS[DatasetName.SECURITY_MASTER].required_columns, "0")
        master.update(Date=str(day), Code=code, Mkt="0111", CoName="synthetic", S33="3700")
        price = dict.fromkeys(ENDPOINT_SCHEMAS[DatasetName.DAILY_PRICES].required_columns, 1)
        price.update(Date=str(day), Code=code, H=2, AdjH=2, L=0.5, AdjL=0.5, Va=100)
        values["security_master"].append(master)
        values["daily_prices"].append(price)
    values["trading_calendar"] = [
        {"Date": str(day + timedelta(days=i)),
         "HolDiv": "1" if (day + timedelta(days=i)).weekday() < 5 else "0"}
        for i in range(22)
    ]
    values["topix"] = [{"Date": str(day), "O": 1, "H": 2, "L": .5, "C": 1}]
    return {"date": str(day), "received_at": RECEIPT, "datasets": values, "valuations": [
        {"Date": str(day), "Code": row["Code"], "MktCap": 30000}
        for row in values["security_master"]
    ]}


@pytest.fixture()
def acquired(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    days = [date(2026, 1, 6) + timedelta(days=i) for i in range(28)]
    days = [day for day in days if day.weekday() < 5]
    assert len(days) == 20
    for day in days:
        market.ingest(path, daily(day))
    return path, days


def test_top300_ties_units_boundary_and_every_holding_without_narrowing_sources(acquired):
    path, days = acquired
    before = market.SQLiteSource(path).point_in_time(DatasetName.DAILY_PRICES, CUTOFF)
    selected = universe.select(path, CUTOFF, ("1302", "ZZZZ", "1000", "ZZZZ"))
    assert not selected["blocking_reasons"]
    assert selected["window_dates"] == [str(day) for day in days]
    assert [x["symbol"] for x in selected["new_candidates"]] == [str(x) for x in range(1000, 1300)]
    assert selected["new_candidates"][0]["market_cap_yen"] == "30000000000"
    assert selected["new_candidates"][0]["mean_trading_value_yen"] == "100"
    assert selected["held_only"] == ["1302", "ZZZZ"]
    assert len(selected["decision_symbols"]) == 302
    after = market.SQLiteSource(path).point_in_time(DatasetName.DAILY_PRICES, CUTOFF)
    assert before.equals(after) and len(after) == 20 * 303
    assert len({x["payload_hash"] for x in selected["sources"]}) >= 22


def test_null_cap_never_uses_deprecated_bars_and_null_or_missing_value_is_not_zero(acquired):
    path, days = acquired
    changed = daily(days[-1])
    changed["received_at"] = "2026-02-03T02:00:00+00:00"
    changed["valuations"][0]["MktCap"] = None
    changed["valuations"][1]["MktCap"] = 29999
    changed["datasets"]["daily_prices"][0]["MktCap"] = 999999
    changed["datasets"]["daily_prices"][2]["Va"] = None
    changed["datasets"]["daily_prices"].pop(3)
    market.ingest(path, changed)
    result = universe.select(path, CUTOFF, ("1000", "1001", "1002", "1003"))
    assert result["held_only"] == ["1000", "1001", "1002", "1003"]
    assert {x["symbol"]: x["reason"] for x in result["excluded"]} == {
        "1000": "market_cap_missing", "1001": "below_market_cap",
        "1002": "twenty_valid_trading_values_required",
        "1003": "twenty_valid_trading_values_required",
    }
    # A removed row in a complete correction must not reappear from an older batch.
    frame = market.SQLiteSource(path).point_in_time(DatasetName.DAILY_PRICES, CUTOFF)
    assert len(frame[frame.symbol == "1003"]) == 19


def test_cutoff_rejects_later_receipt_and_later_cap_correction(acquired):
    path, days = acquired
    original = universe.select(path, CUTOFF)
    assert universe.select(path, datetime.fromisoformat("2026-02-03T00:59:59+00:00"), ("ZZZZ",))[
        "decision_symbols"
    ] == ["ZZZZ"]
    corrected = daily(days[-1])
    corrected["received_at"] = "2026-02-03T02:30:00.000001+00:00"
    corrected["valuations"][0]["MktCap"] = 1
    market.ingest(path, corrected)
    assert universe.select(path, CUTOFF) == original
    assert universe.select(path, datetime.fromisoformat(corrected["received_at"]))[
        "new_candidates"
    ][0]["symbol"] == "1001"


def test_missing_whole_session_blocks_new_candidates_but_preserves_holdings(acquired):
    path, days = acquired
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM market_batches WHERE dataset='daily_prices' AND day=?",
                   (str(days[3]),))
    result = universe.select(path, CUTOFF, ("ZZZZ",))
    assert result["blocking_reasons"] == ["price_session_missing"]
    assert result["decision_symbols"] == ["ZZZZ"] and not result["new_candidates"]


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), True, "yen"])
def test_invalid_valuation_is_atomic_and_cannot_publish_day(tmp_path, value):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    data = daily(date(2026, 1, 6), 1)
    data["valuations"][0]["MktCap"] = value
    with pytest.raises(ValueError):
        market.ingest(path, data)
    assert not market.status(path)["completed_dates"]


def test_valuation_date_code_and_duplicate_contract(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    for field, value in [("Date", "2026-01-05"), ("Code", "1234"), ("MktCap", {})]:
        data = daily(date(2026, 1, 6), 1)
        data["valuations"][0][field] = value
        with pytest.raises(ValueError):
            market.ingest(path, data)
    data = daily(date(2026, 1, 6), 1)
    data["valuations"] *= 2
    with pytest.raises(ValueError):
        market.ingest(path, data)
    assert market.status(path)["latest_data_date"] is None


def test_saved_acquisition_is_idempotent_but_cannot_change_and_plan_survives_reopen(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    data = daily(date(2026, 1, 6), 1)
    data["acquisitionId"] = "11111111-1111-1111-1111-111111111111"
    data["source_pages"] = [
        {"dataset": name, "page": 0, "row_count": len(rows), "received_at": RECEIPT,
         "sha256": "0" * 64}
        for name, rows in {**data["datasets"], "valuations": data["valuations"]}.items()
    ]
    market.ingest(path, data)
    assert market.ingest(path, data)["committed_acquisitions"] == [
        {"date": data["date"], "acquisitionId": data["acquisitionId"]}
    ]
    changed = copy.deepcopy(data)
    changed["valuations"][0]["MktCap"] = 123
    with pytest.raises(ValueError, match="receipt changed"):
        market.ingest(path, changed)
    plan = {"first_day": "2026-01-01", "last_day": "2026-01-06"}
    market.plan(path, plan)
    market.initialize(path)
    assert market.plan(path) == plan
    with pytest.raises(ValueError):
        market.plan(path, {"first_day": "2020-01-01", "last_day": "2026-01-06"})


def test_tampered_source_is_rejected_instead_of_returning_candidates(acquired):
    path, _ = acquired
    with sqlite3.connect(path) as db:
        db.execute("UPDATE market_valuations SET payload_hash=?", ("0" * 64,))
    with pytest.raises(ValueError, match="source changed"):
        universe.select(path, CUTOFF)
