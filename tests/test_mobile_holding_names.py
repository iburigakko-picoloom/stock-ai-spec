from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from mobile.python import forecasts, holding_names, market, membership

from tests.test_mobile_forecasts import NOW
from tests.test_mobile_membership import observation
from tests.test_mobile_stock_chart import _history

pytest_plugins = ("tests.test_mobile_forecasts",)


def test_names_use_saved_master_without_forecast_or_portfolio_change(ready, monkeypatch):
    _, store, path, *_ = ready
    ledger = store.latest_portfolio()
    monkeypatch.setattr(forecasts, "latest", lambda *_: pytest.fail("forecast was read"))
    result = holding_names.read(path, store, NOW)
    assert result == {"portfolioId": ledger.portfolio_id, "names": {"7203": "synthetic fixture"},
                      "prices": {"7203": "1"}, "priceDate": "2026-01-05"}
    assert store.latest_portfolio() == ledger


def test_latest_received_membership_name_overrides_older_master(ready):
    _, store, path, *_ = ready
    recent = observation()
    recent["datasets"]["security_master"][0].update(Code="72030", CoName="新しい保存銘柄名")
    membership.ingest(path, recent, NOW)
    assert holding_names.read(path, store, NOW)["names"]["7203"] == "新しい保存銘柄名"
    earlier = datetime.fromisoformat("2026-02-03T01:59:59+00:00")
    assert holding_names.read(path, store, earlier)["names"]["7203"] == "synthetic fixture"


def test_missing_and_tampered_name_sources_are_not_guessed(ready):
    _, store, path, *_ = ready
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM market_batches WHERE dataset='security_master'")
    assert holding_names.read(path, store, NOW)["names"] == {}
    recent = observation()
    recent["datasets"]["security_master"][0].update(Code="72030", CoName="保存銘柄")
    membership.ingest(path, recent, NOW)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE mobile_membership SET raw=?", (b"broken",))
    with pytest.raises(ValueError, match="changed"):
        holding_names.read(path, store, NOW)


def test_latest_closed_price_is_used_without_future_or_unreceived_values(ready):
    _, store, path, *_ = ready
    receipt = datetime(2026, 2, 2, 8, tzinfo=UTC)
    market.ingest(path, _history(date(2026, 2, 2), receipt, 1100.5))
    market.ingest(path, _history(date(2026, 2, 3), NOW, 2000))
    result = holding_names.read(path, store, NOW)
    assert result["priceDate"] == "2026-02-02" and result["prices"] == {"7203": "1100.5"}
    before_receipt = holding_names.read(path, store, receipt - timedelta(seconds=1))
    assert before_receipt["priceDate"] == "2026-01-05"
    assert before_receipt["prices"] == {"7203": "1"}


def test_price_received_before_market_close_is_not_labeled_as_closing_price(ready):
    _, store, path, *_ = ready
    received_early = datetime(2026, 2, 2, 5, tzinfo=UTC)
    market.ingest(path, _history(date(2026, 2, 2), received_early, 1100))
    result = holding_names.read(path, store, NOW)
    assert result["priceDate"] == "2026-02-02" and result["prices"] == {}


def test_market_endpoint_preserves_ledger_and_rejects_corruption(ready, monkeypatch):
    device, store, path, *_ = ready
    before = store.latest_portfolio()

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = NOW + timedelta(seconds=1)
            return current if tz is None else current.astimezone(tz)

    monkeypatch.setattr(device, "datetime", FixedDatetime)
    result = asyncio.run(device.request("GET", "/api/v1/mobile/holdings/market"))
    assert result["status"] == 200 and result["body"]["names"]["7203"] == "synthetic fixture"
    assert result["body"]["portfolioId"] == before.portfolio_id
    assert store.latest_portfolio() == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE market_batches SET raw=? WHERE dataset='security_master'", (b"broken",))
    rejected = asyncio.run(device.request("GET", "/api/v1/mobile/holdings/market"))
    assert rejected["status"] == 422
