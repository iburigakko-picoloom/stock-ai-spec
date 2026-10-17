from __future__ import annotations

import copy
import gc
import hashlib
import io
import random
import sqlite3
import weakref
import zlib
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from mobile.python import market
from scripts.mobile_capacity_check import make_payload

from stock_ai.data.contracts import DatasetName
from stock_ai.data.production import _source_frame_id
from tests.test_mobile_market import legacy_rows

KINDS = (DatasetName.SECURITY_MASTER, DatasetName.DAILY_PRICES)


def observations():
    rng = random.Random(20261017)
    values = []
    for index in range(3):
        receipt = datetime(2025, 1, 10 + index, 2, tzinfo=UTC)
        value = make_payload(
            date(2024, 1, 2) + timedelta(days=index), index, 4, rng, initial_receipt=receipt
        )
        value.pop("acquisitionId")
        value.pop("source_pages")
        for row in value["datasets"]["daily_prices"]:
            row["Vo"] = int(row["Vo"]) if index == 0 else float(row["Vo"]) + 0.125
            row["AdjVo"] = row["Vo"]
        values.append(value)
    return values


def seed(path, *, legacy=False):
    market.initialize(path)
    values = observations()
    # Arrival order differs from the canonical date order.
    for index in (2, 0, 1):
        value = values[index]
        if legacy:
            with sqlite3.connect(path) as db:
                db.executemany(
                    "INSERT INTO market_batches(dataset,day,received_at,payload_hash,raw,"
                    "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)",
                    legacy_rows(value),
                )
        else:
            market.ingest(path, value)
    return values, datetime(2025, 1, 20, tzinfo=UTC)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("legacy", [False, True])
def test_projection_preserves_every_value_dtype_order_and_complete_source_identity(
    tmp_path, kind, legacy
):
    path = tmp_path / "source.sqlite3"
    _, cutoff = seed(path, legacy=legacy)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    original = market.SQLiteSource(path).point_in_time(kind, cutoff)
    reader = market.FeatureSource(path)
    actual = reader.point_in_time(kind, cutoff)
    pd.testing.assert_frame_equal(actual, original[actual.columns], check_exact=True)
    assert len(actual) == len(original) == 12
    assert "source_record_hash" not in actual and "available_at" in actual
    assert reader.source_frame_id(kind, actual) == _source_frame_id(kind, original)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("remove_all", [False, True])
@pytest.mark.parametrize("kind", KINDS)
def test_latest_complete_correction_removes_a_row_and_cannot_change_an_earlier_cutoff(
    tmp_path, kind, remove_all
):
    path = tmp_path / "source.sqlite3"
    values, cutoff = seed(path)
    corrected = copy.deepcopy(values[0])
    corrected["received_at"] = datetime(2025, 1, 18, tzinfo=UTC).isoformat()
    if remove_all:
        corrected["datasets"][kind.value].clear()
        # An empty selected snapshot is supported by the reader. The normal
        # ingestion completeness check separately rejects a missing business day.
        with sqlite3.connect(path) as db:
            db.executemany(
                "INSERT INTO market_batches(dataset,day,received_at,payload_hash,raw,"
                "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)",
                legacy_rows(corrected),
            )
    else:
        corrected["datasets"][kind.value].pop()
        market.ingest(path, corrected)
    for when, rows in ((datetime(2025, 1, 17, tzinfo=UTC), 12), (cutoff, 8 if remove_all else 11)):
        original = market.SQLiteSource(path).point_in_time(kind, when)
        reader = market.FeatureSource(path)
        actual = reader.point_in_time(kind, when)
        assert len(actual) == rows
        pd.testing.assert_frame_equal(actual, original[actual.columns], check_exact=True)
        assert reader.source_frame_id(kind, actual) == _source_frame_id(kind, original)


def test_unused_source_fields_still_change_the_complete_source_id(tmp_path):
    path = tmp_path / "source.sqlite3"
    values, cutoff = seed(path)
    kind = DatasetName.SECURITY_MASTER
    first = market.FeatureSource(path)
    previous = first.point_in_time(kind, cutoff)
    previous_id = first.source_frame_id(kind, previous)
    corrected = copy.deepcopy(values[0])
    corrected["datasets"][kind.value][0]["CoNameEn"] = "changed unused source field"
    market.ingest(path, corrected)
    second = market.FeatureSource(path)
    current = second.point_in_time(kind, cutoff)
    pd.testing.assert_frame_equal(previous, current, check_exact=True)
    assert second.source_frame_id(kind, current) != previous_id
    assert second.source_frame_id(kind, current) == _source_frame_id(
        kind, market.SQLiteSource(path).point_in_time(kind, cutoff)
    )


def test_identity_rejects_modified_or_replaced_projection_and_does_not_retain_frames(tmp_path):
    path = tmp_path / "source.sqlite3"
    _, cutoff = seed(path)
    kind = DatasetName.DAILY_PRICES
    reader = market.FeatureSource(path)
    frame = reader.point_in_time(kind, cutoff)
    with pytest.raises(ValueError, match="changed after"):
        reader.source_frame_id(kind, frame.copy())
    frame.loc[0, "raw_close"] += 1
    with pytest.raises(ValueError, match="changed after"):
        reader.source_frame_id(kind, frame)
    reference = weakref.ref(frame)
    del frame
    gc.collect()
    assert reference() is None


def test_projected_array_budget_stops_before_assembling_an_oversized_input(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite3"
    _, cutoff = seed(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(market.FeatureSource, "MAX_ARRAY_BYTES", 1)
    with pytest.raises(ValueError, match="MOBILE_MEMORY_LIMIT: projected source arrays"):
        market.FeatureSource(path).point_in_time(DatasetName.DAILY_PRICES, cutoff)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_both_passes_share_one_snapshot_when_another_connection_receives_a_correction(
    tmp_path, monkeypatch
):
    path = tmp_path / "source.sqlite3"
    values, cutoff = seed(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
    kind = DatasetName.DAILY_PRICES
    previous = market.SQLiteSource(path).point_in_time(kind, cutoff)
    corrected = copy.deepcopy(values[0])
    corrected["received_at"] = datetime(2025, 1, 18, tzinfo=UTC).isoformat()
    corrected["datasets"][kind.value][0].update(C=1000.25, AdjC=1000.25, H=2000, AdjH=2000)
    original = market.market_codec.frame
    changed = False

    def receive_during_read(*args):
        nonlocal changed
        result = original(*args)
        if not changed:
            changed = True
            market.ingest(path, corrected)
        return result

    monkeypatch.setattr(market.market_codec, "frame", receive_during_read)
    reader = market.FeatureSource(path)
    frozen = reader.point_in_time(kind, cutoff)
    assert changed
    assert reader.source_frame_id(kind, frozen) == _source_frame_id(kind, previous)
    pd.testing.assert_frame_equal(frozen, previous[frozen.columns], check_exact=True)
    assert _source_frame_id(kind, market.SQLiteSource(path).point_in_time(kind, cutoff)) != (
        reader.source_frame_id(kind, frozen)
    )


def test_empty_sources_and_aware_cutoff_requirement_match_the_base_reader(tmp_path):
    path = tmp_path / "source.sqlite3"
    market.initialize(path)
    reader = market.FeatureSource(path)
    assert reader.point_in_time(DatasetName.SECURITY_MASTER, datetime(2025, 1, 1, tzinfo=UTC)).empty
    with pytest.raises(ValueError, match="Aware cutoff required"):
        reader.point_in_time(DatasetName.DAILY_PRICES, datetime(2025, 1, 1))


def test_null_columns_and_an_older_optional_schema_keep_concat_values_and_identity(tmp_path):
    path = tmp_path / "source.sqlite3"
    market.initialize(path)
    values = observations()
    for index, value in enumerate(values):
        if index == 2:
            for row in value["datasets"]["daily_prices"]:
                row["Va"] = None
        with sqlite3.connect(path) as db:
            for batch in legacy_rows(value):
                if index == 1 and batch[0] == "daily_prices":
                    content = pd.read_json(
                        io.BytesIO(zlib.decompress(batch[5])), orient="table"
                    ).drop(columns="adjustment_source")
                    encoded = content.to_json(orient="table", date_format="iso").encode()
                    batch = (
                        *batch[:5],
                        zlib.compress(encoded),
                        hashlib.sha256(encoded).hexdigest(),
                    )
                db.execute(
                    "INSERT INTO market_batches(dataset,day,received_at,payload_hash,raw,"
                    "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)",
                    batch,
                )
    cutoff = datetime(2025, 1, 20, tzinfo=UTC)
    kind = DatasetName.DAILY_PRICES
    original = market.SQLiteSource(path).point_in_time(kind, cutoff)
    reader = market.FeatureSource(path)
    projected = reader.point_in_time(kind, cutoff)
    pd.testing.assert_frame_equal(projected, original[projected.columns], check_exact=True)
    assert reader.source_frame_id(kind, projected) == _source_frame_id(kind, original)


@pytest.mark.parametrize("latest_noncommon", [False, True])
def test_latest_closed_prices_match_full_pit_values_types_and_same_day_exclusion(
    tmp_path, latest_noncommon
):
    path = tmp_path / "source.sqlite3"
    market.initialize(path)
    rng = random.Random(20261017)
    now = datetime(2025, 1, 10, 2, 30, tzinfo=UTC)
    for index, day in enumerate((6, 7, 8, 10)):
        value = make_payload(
            date(2025, 1, day), index, 4, rng, initial_receipt=now - timedelta(minutes=30)
        )
        value.pop("acquisitionId")
        value.pop("source_pages")
        for row in value["datasets"]["daily_prices"]:
            if day < 10:
                row["C"] = row["AdjC"] = int(row["C"])
                row["H"] = row["AdjH"] = max(row["H"], row["C"], row["O"])
                row["L"] = row["AdjL"] = min(row["L"], row["C"], row["O"])
            if latest_noncommon and day == 8:
                row["Code"] = row["Code"][:-1] + "1"
        market.ingest(path, value)
    reader = market.SQLiteSource(path)
    full = reader.point_in_time(DatasetName.DAILY_PRICES, now)
    expected = full.loc[
        full.provider_code.astype(str).str.fullmatch(r"[0-9A-Z]{4}0")
        & (pd.to_datetime(full.trading_date).dt.date < now.date())
    ]
    day = pd.to_datetime(expected.trading_date).max()
    expected = expected.loc[pd.to_datetime(expected.trading_date) == day].reset_index(drop=True)
    actual = reader.latest_closed_prices(now)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert pd.to_datetime(actual.trading_date).dt.day.eq(7 if latest_noncommon else 8).all()
    assert str(actual.raw_close.dtype) == "float64"


def test_latest_closed_prices_empty_source_and_aware_cutoff_requirement(tmp_path):
    path = tmp_path / "source.sqlite3"
    market.initialize(path)
    reader = market.SQLiteSource(path)
    assert reader.latest_closed_prices(datetime(2025, 1, 1, tzinfo=UTC)).empty
    with pytest.raises(ValueError, match="Aware cutoff required"):
        reader.latest_closed_prices(datetime(2025, 1, 1))


@pytest.mark.parametrize("kind", KINDS)
def test_source_cannot_use_a_receipt_even_one_microsecond_after_the_cutoff(tmp_path, kind):
    path = tmp_path / "source.sqlite3"
    values, _ = seed(path)
    boundary = datetime.fromisoformat(values[0]["received_at"])
    early = market.FeatureSource(path).point_in_time(kind, boundary - timedelta(microseconds=1))
    assert early.empty
    reader = market.FeatureSource(path)
    frame = reader.point_in_time(kind, boundary)
    assert len(frame) == 4
    assert reader.source_frame_id(kind, frame) == _source_frame_id(
        kind, market.SQLiteSource(path).point_in_time(kind, boundary)
    )


def test_profile_preserves_nonnull_dtype_evidence_with_an_old_nonzero_table_index():
    earlier = pd.DataFrame({"value": pd.Series([None, "legacy text"], dtype=object)})
    earlier.index = [10, 20]
    later = pd.DataFrame({"value": pd.Series(["new text"], dtype="string")})
    profiles = [market.market_codec.frame_profile(frame) for frame in (earlier, later)]
    assert profiles[0].value.iloc[0] == "legacy text"
    assert pd.concat(profiles, ignore_index=True).dtypes.equals(
        pd.concat([earlier, later], ignore_index=True).dtypes
    )


def test_legacy_duplicate_source_keys_keep_the_same_last_observation(tmp_path):
    path = tmp_path / "source.sqlite3"
    market.initialize(path)
    value = observations()[0]
    replacement = copy.deepcopy(value["datasets"]["daily_prices"][0])
    replacement.update(C=1234.5, AdjC=1234.5)
    value["datasets"]["daily_prices"].append(replacement)
    with sqlite3.connect(path) as db:
        db.executemany(
            "INSERT INTO market_batches(dataset,day,received_at,payload_hash,raw,"
            "normalized,normalized_hash) VALUES(?,?,?,?,?,?,?)",
            legacy_rows(value),
        )
    cutoff = datetime(2025, 1, 20, tzinfo=UTC)
    kind = DatasetName.DAILY_PRICES
    full = market.SQLiteSource(path).point_in_time(kind, cutoff)
    reader = market.FeatureSource(path)
    projected = reader.point_in_time(kind, cutoff)
    assert len(projected) == 4 and projected.raw_close.iloc[0] == 1234.5
    pd.testing.assert_frame_equal(projected, full[projected.columns], check_exact=True)
    assert reader.source_frame_id(kind, projected) == _source_frame_id(kind, full)


@pytest.mark.parametrize("legacy", [False, True])
def test_provisional_profiles_match_verified_types_and_all_null_evidence_for_every_dataset(
    tmp_path, legacy
):
    path = tmp_path / "source.sqlite3"
    seed(path, legacy=legacy)
    with sqlite3.connect(path) as db:
        batches = db.execute("SELECT raw,normalized,normalized_hash FROM market_batches").fetchall()
        for raw, normalized, expected in batches:
            profile = market.market_codec.dtype_profile(
                db, normalized, raw, expected, OrderedDict()
            )
            verified = market.market_codec.frame(db, normalized, raw, expected, OrderedDict())
            assert profile.dtypes.equals(verified.dtypes)
            if not verified.empty:
                assert profile.isna().all().equals(verified.isna().all())
                assert len(profile) == 1
            else:
                pd.testing.assert_frame_equal(profile, verified, check_exact=True)


def test_provisional_profile_cannot_let_a_changed_historical_batch_produce_an_identity(tmp_path):
    path = tmp_path / "source.sqlite3"
    _, cutoff = seed(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE market_batches SET normalized_hash=? WHERE dataset='daily_prices' "
            "AND day='2024-01-02'",
            ("0" * 64,),
        )
    reader = market.FeatureSource(path)
    with pytest.raises(ValueError, match="Stored normalized data changed"):
        reader.point_in_time(DatasetName.DAILY_PRICES, cutoff)
    assert not reader._identities
