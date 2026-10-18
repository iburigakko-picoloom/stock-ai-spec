from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.data.contracts import (
    ENDPOINT_SCHEMAS,
    DatasetName,
    FetchedPayload,
    IngestionStatus,
    ObjectKind,
    QualityReport,
)
from stock_ai.data.normalize import canonical_payload_hash, normalize_payload, raw_frame
from stock_ai.data.storage import DuckDBCatalog, ImmutableParquetStore, StorageIntegrityError
from stock_ai.ml.daily_market import DailyMarketRequest, project_daily_market, write_daily_market
from stock_ai.ml.selection import freeze_development_features, write_development_feature_selection
from tests.test_research_selection import _campaign_fixtures

DAY = date(2025, 11, 6)
RECEIVED = datetime(2026, 7, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def features(tmp_path_factory):
    root = tmp_path_factory.mktemp("market-features")
    ablation, _ = _campaign_fixtures(root)
    return write_development_feature_selection(
        freeze_development_features(ablation_campaign_paths=(ablation,)), root / "features",
    )


def _rows():
    normal = dict(Date=DAY.isoformat(), Code="72030", O=1000., H=1050., L=990., C=1020.,
                  Vo=10000., Va=10200000., AdjFactor=1., UL="1", LL="0")
    stopped = dict(normal, Code="67580", UL="0")
    for field in ("O", "H", "L", "C", "Vo", "Va"):
        stopped[field] = None
    return [normal, stopped, dict(normal, Code="130A0", C=None, AdjFactor=0.5)]


def _publish(root, rows=None, received=RECEIVED, mutate_raw=None, mutate_normal=None,
             status=IngestionStatus.SUCCEEDED, bulk_fingerprint=None):
    rows = _rows() if rows is None else rows
    payload = FetchedPayload(dataset=DatasetName.DAILY_PRICES,
                             endpoint="/equities/bars/daily", query=(), pages=1,
                             requested_at=received, received_at=received, rows=tuple(rows))
    digest = canonical_payload_hash(payload.rows)
    run = f"run-{received.isoformat()}-{digest}"
    quality = QualityReport(dataset=payload.dataset, rows=len(rows))
    store = ImmutableParquetStore(root / "store")
    raw = raw_frame(payload, ingestion_run_id=run, as_of=received, payload_hash=digest)
    if mutate_raw:
        mutate_raw(raw)
    common = dict(dataset=payload.dataset, source_date=DAY, payload_hash=digest,
                  source_endpoint=payload.endpoint, received_at=received, available_at=received,
                  as_of=received, ingestion_run_id=run, quality=quality)
    source_schema = ENDPOINT_SCHEMAS[payload.dataset].schema_version
    raw_object = store.write(kind=ObjectKind.RAW, frame=raw,
                             schema_version=source_schema, **common)
    normalized = normalize_payload(payload, ingestion_run_id=run, as_of=received,
                                   payload_hash=digest, raw_object_id=raw_object.object_id)
    if mutate_normal:
        mutate_normal(normalized)
    normal_object = store.write(kind=ObjectKind.NORMALIZED, frame=normalized,
                                schema_version=f"goal2a-normalized-v2+{source_schema}", **common)
    with DuckDBCatalog(root / "catalog.duckdb") as catalog:
        catalog.begin_run(run, DAY, received, bulk_fingerprint=bulk_fingerprint)
        catalog.record_object(run, raw_object)
        catalog.record_object(run, normal_object)
        catalog.finish_run(run, status, received)
    return raw_object, normal_object


@pytest.fixture
def market(tmp_path, features):
    objects = _publish(tmp_path)
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    return request, objects


def test_projection_preserves_no_trade_and_raw_flags_without_claiming_fills(market):
    request, objects = market
    before = request.catalog_path.read_bytes()
    result = project_daily_market(request)
    assert request.catalog_path.read_bytes() == before
    rows = {row["symbol"]: row for row in result["rows"]}
    assert set(rows) == {"7203", "6758", "130A"}
    assert rows["7203"]["raw_close"] == 1020
    assert rows["7203"]["intraday_upper_limit_reached"] == 1
    assert rows["7203"]["bar_state"] == "reported_trade"
    assert rows["6758"]["bar_state"] == "reported_no_trade"
    assert rows["6758"]["raw_close"] is None
    assert rows["6758"]["raw_volume"] is None
    assert rows["130A"]["bar_state"] == "incomplete_bar"
    assert rows["130A"]["adjustment_requires_event_evidence"] is True
    assert rows["7203"]["trading_date"] == DAY.isoformat()
    assert result["capabilities"]["buy_status"] == "unknown"
    assert result["capabilities"]["capacity_shares"] is None
    assert not result["capabilities"]["evaluation_ready"]
    assert {o["object_id"] for o in result["source_objects"]} == {o.object_id for o in objects}
    assert result["summary"]["bar_states"] == {
        "reported_trade": 1, "reported_no_trade": 1, "incomplete_bar": 1,
    }


def test_later_revision_cannot_change_earlier_source_snapshot(market, tmp_path):
    request, _ = market
    original = project_daily_market(request)
    later = RECEIVED + timedelta(days=1)
    changed = _rows()
    changed[0]["C"] = 1030.
    _publish(tmp_path, changed, received=later)
    assert project_daily_market(request) == original
    revised = project_daily_market(request.model_copy(update={"source_snapshot_as_of": later}))
    assert revised["summary"]["source_rows"] == 6
    assert revised["summary"]["rows"] == 3
    assert next(r for r in revised["rows"] if r["symbol"] == "7203")["raw_close"] == 1030


@pytest.mark.parametrize("change,error", [
    (lambda f: f.__setitem__("raw_close", 3), "value differs"),
    (lambda f: f.__setitem__("raw_object_id", "unknown"), "successful eligible"),
    (lambda f: f.__setitem__("source_record_hash", "a" * 64), "row lineage differs"),
    (lambda f: f.__setitem__("source_record_hash", "bad"), "record hash"),
    (lambda f: f.__setitem__("symbol", "other"), "symbol differs"),
    (lambda f: f.__setitem__("provider_code", "11110"), "duplicate"),
    (lambda f: f.__setitem__("trading_date", date(2026, 8, 1)), "another date"),
    (lambda f: f.__setitem__("received_at", RECEIVED + timedelta(days=1)), "row/manifest"),
    (lambda f: f.drop(columns="raw_volume", inplace=True), "price columns"),
    (lambda f: f.drop(columns="provider", inplace=True), "metadata is incomplete"),
    (lambda f: f.drop(columns="raw_object_id", inplace=True), "one raw link"),
])
def test_rehashed_bad_normalized_objects_do_not_pass(tmp_path, features, change, error):
    _publish(tmp_path, mutate_normal=change)
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    with pytest.raises(StorageIntegrityError, match=error):
        project_daily_market(request)


@pytest.mark.parametrize("field,value,error", [
    ("UL", "2", "limit flag"), ("LL", "bad", "parse string"),
    ("O", -1., "invalid market value"), ("Vo", float("inf"), "invalid market value"),
])
def test_bad_values_are_not_converted_to_missing(tmp_path, features, field, value, error):
    def raw_change(frame):
        frame[field] = value

    def normalized_change(frame):
        if field in ("O", "Vo"):
            frame["raw_open" if field == "O" else "raw_volume"] = value

    _publish(tmp_path, mutate_raw=raw_change, mutate_normal=normalized_change)
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    with pytest.raises((StorageIntegrityError, ValueError), match=error):
        project_daily_market(request)


def test_optional_flags_remain_null(tmp_path, features):
    rows = _rows()
    for row in rows:
        del row["UL"], row["LL"]
    _publish(tmp_path, rows)
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    result = project_daily_market(request)
    assert all(row["intraday_upper_limit_reached"] is None for row in result["rows"])


@pytest.mark.parametrize("rights,factor,requires_review", [
    ("1", 0.5, True), ("2", 2., True), ("3", 1., True),
    ("1", 1., True), ("99", 1., True), ("", 1., False), (None, 1., False),
])
def test_typed_rights_are_preserved_even_with_a_unit_factor(
    tmp_path, features, rights, factor, requires_review,
):
    rows = [dict(_rows()[0], ExRT=rights, AdjFactor=factor)]
    _publish(tmp_path, rows)
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    result = project_daily_market(request)
    row = result["rows"][0]
    assert row["ex_rights_type"] == (rights or None)
    assert row["ex_rights_type_source_present"] is True
    assert row["adjustment_requires_event_evidence"] is requires_review
    assert result["summary"]["ex_rights_types"] == ({rights: 1} if rights else {})
    assert result["capabilities"]["corporate_actions"] == "UNVERIFIED"
    assert result["capabilities"]["evaluation_ready"] is False


def test_missing_rights_source_is_distinct_from_a_reported_null(market):
    request, _ = market
    result = project_daily_market(request)
    assert all(row["ex_rights_type"] is None for row in result["rows"])
    assert all(row["ex_rights_type_source_present"] is False for row in result["rows"])
    assert result["summary"]["ex_rights_source_missing_rows"] == 3


def test_legacy_normalized_partition_keeps_authenticated_raw_rights(tmp_path, features):
    _publish(tmp_path, [dict(_rows()[0], ExRT="3")],
             mutate_normal=lambda frame: frame.drop(columns="ex_rights_type", inplace=True))
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    row = project_daily_market(request)["rows"][0]
    assert row["ex_rights_type"] == "3"
    assert row["ex_rights_type_source_present"] is True
    assert row["adjustment_factor"] == 1 and row["adjustment_requires_event_evidence"]


@pytest.mark.parametrize("value", ["2", "", None])
def test_rehashed_normalized_rights_mismatch_is_not_accepted(tmp_path, features, value):
    _publish(tmp_path, [dict(_rows()[0], ExRT="1")],
             mutate_normal=lambda frame: frame.__setitem__("ex_rights_type", value))
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    with pytest.raises(StorageIntegrityError, match="ex-rights type differs"):
        project_daily_market(request)


def test_nonstandard_share_classes_do_not_merge_with_ordinary_stock(tmp_path, features):
    rows = [_rows()[0], dict(_rows()[0], Code="72035")]
    _publish(tmp_path, rows)
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    result = project_daily_market(request)
    assert result["summary"]["rows"] == 2
    assert result["summary"]["nonstandard_code_rows"] == 1
    special = next(row for row in result["rows"] if row["provider_code"] == "72035")
    assert special["symbol"] is None
    assert special["symbol_status"] == "nonstandard_provider_code"


def test_empty_provider_partition_is_preserved_as_evidence(tmp_path, features):
    objects = _publish(tmp_path, [])
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    result = project_daily_market(request)
    assert result["rows"] == []
    assert len(result["source_objects"]) == len(objects)
    assert not result["capabilities"]["evaluation_ready"]


@pytest.mark.parametrize("kind", ["failed", "unfinished_bulk", "unreceived", "raw_failed"])
def test_unsuccessful_or_future_ingestion_excluded(tmp_path, features, kind):
    _publish(tmp_path, status=IngestionStatus.FAILED if kind == "failed"
             else IngestionStatus.SUCCEEDED,
             bulk_fingerprint="not-finished" if kind == "unfinished_bulk" else None)
    if kind == "raw_failed":
        with duckdb.connect(str(tmp_path / "catalog.duckdb")) as conn:
            conn.execute("DELETE FROM ingestion_run_objects WHERE object_id IN "
                         "(SELECT object_id FROM stored_objects WHERE kind = 'raw')")
    request = DailyMarketRequest(catalog_path=tmp_path / "catalog.duckdb",
                                 store_root=tmp_path / "store", feature_selection_path=features,
                                 start=DAY, end=DAY, source_snapshot_as_of=RECEIVED -
                                 (timedelta(seconds=1) if kind == "unreceived" else timedelta()))
    with pytest.raises((ValueError, StorageIntegrityError), match=r"objects|eligible"):
        project_daily_market(request)


@pytest.mark.parametrize("tamper", ["parquet", "catalog", "manifest"])
def test_source_tampering_rejected(market, tamper):
    request, objects = market
    if tamper == "parquet":
        frame = pd.read_parquet(objects[0].parquet_path)
        frame["C"] = 1
        frame.to_parquet(objects[0].parquet_path)
    elif tamper == "catalog":
        with duckdb.connect(str(request.catalog_path)) as conn:
            conn.execute("UPDATE stored_objects SET rows = rows + 1 WHERE kind = 'normalized'")
    else:
        objects[0].manifest_path.write_text("{}", encoding="utf-8")
    with pytest.raises(StorageIntegrityError):
        project_daily_market(request)


def test_holdout_rejected_before_opening_catalog(market):
    request, _ = market
    request = request.model_copy(update={"end": date(2026, 8, 1),
                                         "catalog_path": Path("does-not-exist")})
    with pytest.raises(ValueError, match="locked holdout"):
        project_daily_market(request)


def test_request_clocks_and_window(market):
    request, _ = market
    for update in ({"end": DAY - timedelta(days=1)},
                   {"source_snapshot_as_of": RECEIVED.replace(tzinfo=None)},
                   {"revision_policy": "STRICT_AS_KNOWN"}):
        with pytest.raises(ValueError):
            DailyMarketRequest.model_validate({**request.model_dump(), **update})


def test_receipt_and_cli(market, tmp_path):
    request, _ = market
    path = write_daily_market(request, tmp_path / "receipts")
    raw = path.read_bytes()
    assert path.stem == hashlib.sha256(raw.rstrip(b"\n")).hexdigest()
    with pytest.raises(FileExistsError):
        write_daily_market(request, tmp_path / "receipts")
    source = tmp_path / "request.json"
    source.write_text(request.model_dump_json(), encoding="utf-8")
    run = CliRunner().invoke(app, ["research", "project-daily-market", "--input", str(source),
                                   "--output-root", str(tmp_path / "cli")])
    assert run.exit_code == 0, run.output
    assert json.loads(run.output)["research_only"] is True
    source.write_text("{}", encoding="utf-8")
    assert CliRunner().invoke(app, ["research", "project-daily-market", "--input",
                                   str(source)]).exit_code == 2
