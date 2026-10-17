from __future__ import annotations

import copy
import hashlib
import io
import json
import sqlite3
import zlib
from collections import OrderedDict
from datetime import datetime

import pandas as pd
import pytest
from mobile.python import market, market_codec, runtime

from stock_ai.data.contracts import DatasetName
from stock_ai.data.normalize import record_hash_v1
from tests.test_mobile_market import legacy_rows, payload


def test_scalar_types_missing_fields_unicode_and_nested_values_are_lossless(tmp_path):
    with sqlite3.connect(tmp_path / "values.sqlite3") as db:
        market_codec.initialize(db)
        original = [{"code": "00010", "value": False, "zero": -0.0, "optional": None},
                    {"code": "00020", "value": 0, "zero": 0.0},
                    {"code": "00030", "value": 0.0, "zero": 1e-20,
                     "text": '合成/株 "😀" \\ \n'}]
        decoded = market_codec.records(db, market_codec.pack_records(db, original))
        assert json.dumps(decoded, sort_keys=True) == json.dumps(original, sort_keys=True)
        nested = [{"extra": {"value": [False, 0, None]}}]
        encoded = market_codec.pack_records(db, nested)
        assert not encoded.startswith(market_codec.PREFIX)
        assert market_codec.records(db, encoded) == nested


def test_normalized_numeric_spelling_and_original_bytes_are_preserved(tmp_path):
    raw = [{"value": 1}, {"value": 2}]
    hashes = [record_hash_v1(row) for row in raw]
    original = ('{"schema":{"fields":[]},"data":['
                '{"number":0.0000000012,"zero":-0.0,"source_record_hash":"' + hashes[0] + '"},'
                '{"number":1.2300000000e+17,"zero":0,"source_record_hash":"'
                + hashes[1] + '"}]}').encode()
    with sqlite3.connect(tmp_path / "values.sqlite3") as db:
        market_codec.initialize(db)
        source = market_codec.pack_records(db, raw)
        compact = market_codec.pack_table(db, original, raw)
        assert compact.startswith(market_codec.PREFIX)
        assert market_codec.table(
            db, compact, source, hashlib.sha256(original).hexdigest()
        ) == original


def test_same_columns_are_shared_without_losing_date_or_numeric_identity(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    first = payload()
    for name in ("security_master", "daily_prices"):
        other = copy.deepcopy(first["datasets"][name][0])
        other["Code"] = "72040"
        first["datasets"][name].append(other)
    first["datasets"]["security_master"][0]["CoName"] = '合成/銘柄 "😀"'
    market.ingest(path, first)
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT COUNT(*) FROM market_columns").fetchone()[0]
        for raw, normalized, expected in db.execute(
            "SELECT raw,normalized,normalized_hash FROM market_batches"
        ):
            assert raw.startswith(market_codec.PREFIX)
            assert normalized.startswith(market_codec.PREFIX)
            market_codec.table(db, normalized, raw, expected)
    second = copy.deepcopy(first)
    second.update(date="2026-01-06", received_at="2026-01-07T08:00:00+00:00")
    for values in second["datasets"].values():
        for row in values:
            row["Date"] = second["date"]
    market.ingest(path, second)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM market_columns").fetchone()[0] == before
    frame = market.SQLiteSource(path).point_in_time(
        DatasetName.DAILY_PRICES, datetime.fromisoformat(second["received_at"])
    )
    assert len(frame) == 4 and len(set(frame.trading_date)) == 2


def test_legacy_compaction_is_bounded_and_preserves_all_observation_evidence(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    value = payload()
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO market_batches(dataset,day,received_at,payload_hash,raw,"
                       "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)", legacy_rows(value))
        before = db.execute("SELECT sequence,dataset,day,received_at,payload_hash,normalized_hash "
                            "FROM market_batches").fetchall()
    reader = market.SQLiteSource(path)
    cutoff = datetime.fromisoformat(value["received_at"])
    frames = {kind: reader.point_in_time(kind, cutoff) for kind in DatasetName}
    assert market.compact_legacy(path, 1) == 1
    with sqlite3.connect(path) as db:
        assert sum(row[0].startswith(market_codec.PREFIX) for row in db.execute(
            "SELECT normalized FROM market_batches")) == 1
    for _ in range(5):
        market.compact_legacy(path, 2)
    assert market.compact_legacy(path) == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT sequence,dataset,day,received_at,payload_hash,normalized_hash "
                          "FROM market_batches").fetchall() == before
    for kind in DatasetName:
        pd.testing.assert_frame_equal(
            reader.point_in_time(kind, cutoff), frames[kind], check_exact=True
        )


def test_failed_compaction_rolls_back_columns_and_earlier_batches(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    value = payload()
    value["datasets"]["security_master"].append(
        {**value["datasets"]["security_master"][0], "Code": "72040"})
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO market_batches(dataset,day,received_at,payload_hash,raw,"
                       "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)", legacy_rows(value))
        db.execute("UPDATE market_batches SET normalized=? WHERE sequence=2", (b"bad",))
        before = db.execute("SELECT * FROM market_batches").fetchall()
    with pytest.raises((ValueError, zlib.error)):
        market.compact_legacy(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM market_batches").fetchall() == before
        assert db.execute("SELECT COUNT(*) FROM market_columns").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM market_compaction").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_referenced_column_missing_or_changed_cannot_be_read(tmp_path, change):
    with sqlite3.connect(tmp_path / "values.sqlite3") as db:
        market_codec.initialize(db)
        encoded = market_codec.pack_records(db, [{"value": 1}, {"value": 2}])
        if change == "missing":
            db.execute("DELETE FROM market_columns")
        else:
            db.execute("UPDATE market_columns SET payload=?", (zlib.compress(b'["3","4"]'),))
        with pytest.raises(ValueError, match="Market column"):
            market_codec.records(db, encoded)


def test_export_cannot_save_a_compressible_database_that_its_restore_rejects(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "STATE", tmp_path)
    runtime.initialize()
    original = runtime.export_state()
    limit = max((tmp_path / name).stat().st_size
                for name in ("mobile.sqlite3", "operations.sqlite3"))
    monkeypatch.setattr(runtime, "MAX_DATABASE_BYTES", limit + 4096)
    with sqlite3.connect(tmp_path / "mobile.sqlite3") as db:
        db.execute("CREATE TABLE synthetic_large(payload BLOB)")
        db.execute("INSERT INTO synthetic_large VALUES(zeroblob(?))", (limit + 8192,))
    with pytest.raises(ValueError, match="mobile storage limit"):
        runtime.export_state()
    assert not (tmp_path / "export.sqlite3").exists()
    runtime.initialize(original)
    assert runtime.export_state()


def test_small_descriptor_cannot_expand_an_unbounded_constant_matrix(tmp_path):
    descriptor = {"kind": "records", "rows": 50000,
                  "columns": [{"name": str(index), "constant": "0"} for index in range(2000)]}
    encoded = market_codec.PREFIX + zlib.compress(json.dumps(descriptor).encode())
    with sqlite3.connect(tmp_path / "values.sqlite3") as db:
        market_codec.initialize(db)
        with pytest.raises(ValueError, match="Expanded market records"):
            market_codec.records(db, encoded)


def test_new_ingestion_cannot_reuse_a_changed_column_as_valid_data(tmp_path):
    path = tmp_path / "market.sqlite3"
    market.initialize(path)
    value = payload()
    for name in ("security_master", "daily_prices"):
        value["datasets"][name].append({**value["datasets"][name][0], "Code": "72040"})
    market.ingest(path, value)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE market_columns SET payload=?", (zlib.compress(b'["0","0"]'),))
        before = db.execute("SELECT * FROM market_batches").fetchall()
    with pytest.raises(ValueError, match="Market column changed"):
        market.ingest(path, value)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM market_batches").fetchall() == before


def test_column_materialization_matches_pandas_types_values_and_indexes_exactly(tmp_path):
    raw = [{"row": index} for index in range(12)]
    source = pd.DataFrame({
        "text": pd.Series(['合成/銘柄 "😀"'] * 12, dtype="string"),
        "number": pd.Series([None, 1.23e17, -0.0, 1.2e-9] * 3, dtype="Float64"),
        "flag": pd.Series([True, False, None] * 4, dtype="boolean"),
        "integer": pd.Series([1, None, -2] * 4, dtype="Int64"),
        "when": pd.date_range("2026-01-01", periods=12, tz="Asia/Tokyo"),
        "source_record_hash": [record_hash_v1(row) for row in raw],
    })
    original = source.to_json(orient="table", date_format="iso").encode()
    with sqlite3.connect(tmp_path / "values.sqlite3") as db:
        market_codec.initialize(db)
        records = market_codec.pack_records(db, raw)
        compact = market_codec.pack_table(db, original, raw)
        assert compact.startswith(market_codec.PREFIX)
        actual = market_codec.frame(db, compact, records,
                                    hashlib.sha256(original).hexdigest(), OrderedDict())
        expected = pd.read_json(io.BytesIO(original), orient="table")
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_empty_table_materialization_keeps_pandas_empty_schema_semantics(tmp_path):
    source = pd.DataFrame({"unknown": pd.Series(dtype=object),
                           "number": pd.Series(dtype="Int64"),
                           "text": pd.Series(dtype="string")})
    original = source.to_json(orient="table", date_format="iso").encode()
    with sqlite3.connect(tmp_path / "values.sqlite3") as db:
        market_codec.initialize(db)
        actual = market_codec.frame(
            db, market_codec.pack_table(db, original, []),
            market_codec.pack_records(db, []), hashlib.sha256(original).hexdigest(), OrderedDict())
    pd.testing.assert_frame_equal(actual, pd.read_json(io.BytesIO(original), orient="table"),
                                  check_exact=True)
