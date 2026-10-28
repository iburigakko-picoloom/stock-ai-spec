from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from mobile.python import forecasts, forward_protocol, market

from tests.test_mobile_bundles import IMPORTED
from tests.test_mobile_forecasts import NOW
from tests.test_mobile_stock_chart import _history

pytest_plugins = ("tests.test_mobile_forecasts",)


def test_rank_correlation_uses_ordinal_scores_and_average_ties():
    assert forward_protocol._spearman([(30, .02), (20, .01), (10, -.01)]) == pytest.approx(1)
    assert forward_protocol._spearman([(30, -.01), (20, .01), (10, .02)]) == pytest.approx(-1)
    assert forward_protocol._spearman([(1, .01), (1, .02)]) is None
    assert forward_protocol._spearman([(1, .01)]) is None
    assert forward_protocol._spearman([(1, .01), (1, .02), (2, .03)]) == pytest.approx(3**.5 / 2)


def test_rank_only_output_is_scored_without_inventing_a_return(tmp_path, monkeypatch):
    path = tmp_path / "forward.sqlite3"
    start = date(2026, 2, 3)
    last = date(2026, 3, 5)
    now = datetime(2026, 3, 10, tzinfo=UTC)
    registration = {"registration_id": "a", "registered_at": IMPORTED.isoformat()}
    snapshot = SimpleNamespace(snapshot_id="snapshot", generated_at=NOW, predictions=[
        SimpleNamespace(symbol="1000", expected_return_5d=None, expected_return_20d=None,
                        rank_score_20d=2.0),
        SimpleNamespace(symbol="7203", expected_return_5d=None, expected_return_20d=None,
                        rank_score_20d=1.0),
    ])
    monkeypatch.setattr(forward_protocol, "registrations", lambda _: [registration])
    monkeypatch.setattr(forward_protocol, "_run", lambda *_: (
        {"excluded_candidates": []}, snapshot, start - timedelta(days=1), last))
    source = {"received_at": now.isoformat(), "payload_hash": "a" * 64}
    def observations(_path, dataset, _first, _last, _now):
        for i in range((last - start).days + 1):
            day = start + timedelta(days=i)
            if dataset == "trading_calendar":
                rows = [{"Date": str(day), "HolDiv": "1" if day.weekday() < 5 else "0"}]
            elif day.weekday() < 5:
                rows = [{"Date": str(day), "Code": symbol + "0", "AdjC": 100 + sign * i,
                         "AdjFactor": 1} for symbol, sign in (("1000", 1), ("7203", -1))]
            else:
                rows = []
            yield str(day), rows, source
    monkeypatch.setattr(forward_protocol.universe, "_observations", observations)
    result = forward_protocol.observe(path, None, "a", "run", 20, now)["evidence"]
    assert result["scored_count"] == 0 and result["mean_absolute_error"] is None
    assert result["rank_scored_count"] == 2 and result["conditional_rank_correlation"] == 1
    assert all(row["expected_return"] is None for row in result["results"])


def test_registration_is_future_only_idempotent_and_survives_backup(ready):
    device, store, path, *_ = ready
    before = store.latest_portfolio()
    started = IMPORTED + timedelta(minutes=2)
    registration = forward_protocol.register(path, started)
    assert registration["eligible_from"] == "2026-02-02T15:00:00+00:00"
    assert registration["registered_at"] == started.isoformat()
    assert not registration["formal_evaluation"] and not registration["external_time_authenticated"]
    assert forward_protocol.register(path, started + timedelta(minutes=1)) == registration
    with pytest.raises(ValueError, match="clock moved backwards"):
        forward_protocol.register(path, IMPORTED + timedelta(minutes=1))
    encoded = device.export_state()
    device.initialize(encoded)
    assert forward_protocol.registrations(path) == [registration]
    assert device._app.state.store.latest_portfolio() == before


def test_observations_keep_missing_symbols_and_version_corrections(ready):
    _, store, path, *_ = ready
    registration = forward_protocol.register(path, IMPORTED)
    forecast = forecasts.generate(path, store, NOW)
    before = store.latest_portfolio()
    receipt = datetime(2026, 3, 10, tzinfo=UTC)
    start = date(2026, 2, 3)
    for i in range(31):
        market.ingest(path, _history(start + timedelta(days=i), receipt, 100 + i))
    first = forward_protocol.observe(path, store, registration["registration_id"],
                                     forecast["run_id"], 5, receipt + timedelta(days=1))
    evidence = first["evidence"]
    assert evidence["count"] == 2 and evidence["scored_count"] == 1
    assert evidence["mean_absolute_error"] == pytest.approx(abs(.01 - (107 / 100 - 1)))
    assert {x["status"] for x in evidence["results"]} == {"available", "price_missing"}
    assert evidence["source_prices"]["2026-02-03"]["payload_hash"]
    assert evidence["source_calendar"]["2026-02-03"]["payload_hash"]
    assert not evidence["formal_evaluation"] and not evidence["execution_return"]
    twenty = forward_protocol.observe(path, store, registration["registration_id"],
                                      forecast["run_id"], 20, receipt + timedelta(days=1))
    good = next(row for row in twenty["evidence"]["results"] if row["symbol"] == "7203")
    assert good["exit_date"] == "2026-03-03" and good["actual_return"] == pytest.approx(.28)
    assert forward_protocol.observe(path, store, registration["registration_id"],
                                    forecast["run_id"], 5, receipt + timedelta(days=1)) == first
    market.ingest(path, _history(start, receipt + timedelta(days=2), 200))
    corrected = forward_protocol.observe(path, store, registration["registration_id"],
                                         forecast["run_id"], 5, receipt + timedelta(days=3))
    assert corrected["observation_id"] != first["observation_id"]
    assert corrected["evidence"]["mean_absolute_error"] != evidence["mean_absolute_error"]
    assert len(forward_protocol.observations(path)) == 3
    assert store.latest_portfolio() == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE forward_observations SET payload=? WHERE observation_id=?",
                   ('{"observed_at":"altered"}', first["observation_id"]))
    with pytest.raises(ValueError, match="changed"):
        forward_protocol.observations(path)


def test_old_forecast_cannot_be_registered_retroactively(ready):
    _, store, path, *_ = ready
    forecast = forecasts.generate(path, store, NOW)
    registration = forward_protocol.register(path, NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="outside the registered protocol"):
        forward_protocol.observe(path, store, registration["registration_id"], forecast["run_id"],
                                 5, NOW + timedelta(days=1))


def test_prediction_created_after_entry_close_is_not_scored(ready):
    _, store, path, *_ = ready
    registration = forward_protocol.register(path, IMPORTED)
    forecast = forecasts.generate(path, store, NOW + timedelta(hours=5))
    receipt = datetime(2026, 3, 10, tzinfo=UTC)
    start = date(2026, 2, 3)
    for i in range(15):
        market.ingest(path, _history(start + timedelta(days=i), receipt, 100 + i))
    value = forward_protocol.observe(path, store, registration["registration_id"],
                                     forecast["run_id"], 5, receipt + timedelta(days=1))
    assert value["evidence"]["scored_count"] == 0
    good = next(row for row in value["evidence"]["results"] if row["symbol"] == "7203")
    assert good["status"] == "forecast_after_entry_close" and good["actual_return"] is None


def test_missing_calendar_and_unmatured_period_never_become_returns(ready):
    _, store, path, *_ = ready
    registration = forward_protocol.register(path, IMPORTED)
    forecast = forecasts.generate(path, store, NOW)
    value = forward_protocol.observe(path, store, registration["registration_id"],
                                     forecast["run_id"], 20, NOW + timedelta(days=1))
    assert value["evidence"]["scored_count"] == 0
    assert value["evidence"]["mean_absolute_error"] is None
    assert all(row["actual_return"] is None for row in value["evidence"]["results"])


def test_api_registration_and_observation_survive_real_state_export(ready, monkeypatch):
    device, store, path, *_ = ready
    clock = [IMPORTED]

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0] if tz is None else clock[0].astimezone(tz)

    monkeypatch.setattr(device, "datetime", FixedDatetime)
    api = "/api/v1/mobile/forward-evidence"
    registered = asyncio.run(device.request("POST", api + "/register", "{}"))
    assert registered["status"] == 200
    forecast = forecasts.generate(path, store, NOW)
    clock[0] = NOW + timedelta(days=1)
    body = json.dumps({"registration_id": registered["body"]["registration_id"],
                       "run_id": forecast["run_id"], "horizon": 20})
    observed = asyncio.run(device.request("POST", api + "/observe", body))
    assert observed["status"] == 200 and observed["body"]["evidence"]["scored_count"] == 0
    saved = device.export_state()
    device.initialize(saved)
    loaded = asyncio.run(device.request("GET", api))
    assert loaded["status"] == 200 and len(loaded["body"]["registrations"]) == 1
    assert loaded["body"]["observations"][0]["observation_id"] == observed["body"]["observation_id"]
    detail_path = api + "/observations/" + observed["body"]["observation_id"]
    detail = asyncio.run(device.request("GET", detail_path))
    assert detail["status"] == 200
    assert detail["body"]["evidence"]["results"] == observed["body"]["evidence"]["results"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE forward_observations SET payload='{}'")
    rejected = asyncio.run(device.request("GET", detail_path))
    assert rejected["status"] == 422
