from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import zlib
from datetime import datetime

import pytest
from mobile.python import market

from stock_ai.data.contracts import ENDPOINT_SCHEMAS, DatasetName, FetchedPayload
from stock_ai.data.normalize import canonical_payload_hash, normalize_payload


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


def legacy_rows(value):
    """The shipped v1 representation, independent of the new column codec."""
    received = datetime.fromisoformat(value["received_at"])
    result = []
    for dataset in DatasetName:
        records = tuple(value["datasets"][dataset.value])
        digest = canonical_payload_hash(records)
        fetched = FetchedPayload(
            dataset=dataset, endpoint=ENDPOINT_SCHEMAS[dataset].endpoint,
            query=(("date", value["date"]),), requested_at=received, received_at=received,
            pages=1, rows=records,
        )
        frame = normalize_payload(fetched, ingestion_run_id="mobile-" + digest,
                                  as_of=received, payload_hash=digest, raw_object_id=digest)
        normalized = frame.to_json(orient="table", date_format="iso").encode()
        result.append((dataset.value, value["date"], received.isoformat(timespec="microseconds"),
                       digest, zlib.compress(json.dumps(records, allow_nan=False).encode()),
                       zlib.compress(normalized), hashlib.sha256(normalized).hexdigest()))
    return result


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


def test_same_day_closing_data_is_rejected_before_seventeen(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    value = payload()
    value["received_at"] = "2026-01-05T07:59:59+00:00"
    with pytest.raises(ValueError, match="only accepted after 17:00"):
        market.ingest(path, value)
    assert market.status(path)["completed_days"] == 0
    value["received_at"] = "2026-01-05T08:00:00+00:00"
    assert market.ingest(path, value)["latest_data_date"] == "2026-01-05"


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


def test_repeat_content_is_new_observation_and_legacy_migration_preserves_rows(tmp_path):
    path = tmp_path / "market.sqlite3"
    first = payload()
    legacy = legacy_rows(first)
    # Genuine pre-upgrade schema; migration preserves the original blobs.
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE market_batches(dataset TEXT,day TEXT,received_at TEXT,payload_hash TEXT,"
            "raw BLOB,normalized BLOB,normalized_hash TEXT,PRIMARY KEY(dataset,day,payload_hash))"
        )
        db.executemany("INSERT INTO market_batches VALUES(?,?,?,?,?,?,?)", legacy)
    market.initialize(path)
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT dataset,day,received_at,payload_hash,raw,normalized,normalized_hash "
            "FROM market_batches ORDER BY sequence"
        ).fetchall() == legacy
    # Reading before any new ingestion cannot depend on new-format columns.
    assert market.SQLiteSource(path).point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat(first["received_at"])
    ).iloc[0].raw_close == 1
    market.ingest(path, first)
    second = copy.deepcopy(first)
    second["received_at"] = "2026-01-07T08:00:00+00:00"
    second["datasets"]["daily_prices"][0].update(C=1.5, AdjC=1.5)
    market.ingest(path, second)
    third = copy.deepcopy(first)
    third["received_at"] = "2026-01-08T08:00:00+00:00"
    market.ingest(path, third)
    for source, expected in [(first, 1), (second, 1.5), (third, 1)]:
        frame = market.SQLiteSource(path).point_in_time(
            DatasetName.DAILY_PRICES, datetime.fromisoformat(source["received_at"])
        )
        assert frame.iloc[0].raw_close == expected
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM market_batches").fetchone()[0] == 15
        before = db.execute("SELECT * FROM market_batches ORDER BY sequence").fetchall()
    market.initialize(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM market_batches ORDER BY sequence").fetchall() == before


def test_nanosecond_receipts_cannot_enter_a_microsecond_cutoff_early(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    value = payload()
    value["received_at"] = "2026-01-06T02:30:00.000000001Z"
    market.ingest(path, value)
    assert market.SQLiteSource(path).point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat("2026-01-06T02:30:00Z")
    ).empty
    assert not market.SQLiteSource(path).point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat("2026-01-06T02:30:00.000001Z")
    ).empty
