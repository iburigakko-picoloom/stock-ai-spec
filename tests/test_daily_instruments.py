from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.data.contracts import ENDPOINT_SCHEMAS, DatasetName, FetchedPayload, ObjectKind
from stock_ai.data.normalize import canonical_payload_hash, normalize_payload, raw_frame
from stock_ai.data.storage import DuckDBCatalog, ImmutableParquetStore, StorageIntegrityError
from stock_ai.ml.daily_instruments import instrument_rules, project_daily_instruments
from stock_ai.ml.daily_market import DailyMarketRequest
from tests.test_daily_market import DAY, RECEIVED, _publish, _rows
from tests.test_daily_market import features as feature_fixture
from tests.test_data_foundation import _all_endpoint_rows


@pytest.fixture(scope="module")
def features(tmp_path_factory):
    return feature_fixture.__wrapped__(tmp_path_factory)


def master(root, *, rows=None, received=RECEIVED, mutate=None):
    if rows is None:
        base = dict(_all_endpoint_rows()['/v2/equities/master'][0], Date=str(DAY))
        rows = [dict(base, Code='72030', ProdCat='011', ScaleCat='TOPIX Large70'),
                dict(base, Code='67580', ProdCat='021', ScaleCat='-'),
                dict(base, Code='130A0', ScaleCat='-')]
    payload = FetchedPayload(dataset=DatasetName.SECURITY_MASTER, endpoint='/equities/master',
                             query=(), pages=1, requested_at=received, received_at=received,
                             rows=tuple(rows))
    digest = canonical_payload_hash(payload.rows)
    run = 'master-' + digest + received.isoformat()
    from stock_ai.data.contracts import IngestionStatus, QualityReport
    store = ImmutableParquetStore(root / 'store')
    metadata = dict(dataset=payload.dataset, source_date=DAY, payload_hash=digest,
                    source_endpoint=payload.endpoint, received_at=received, available_at=received,
                    as_of=received, ingestion_run_id=run,
                    quality=QualityReport(dataset=payload.dataset, rows=len(rows)))
    schema = ENDPOINT_SCHEMAS[payload.dataset].schema_version
    raw = store.write(kind=ObjectKind.RAW,
                      frame=raw_frame(payload, ingestion_run_id=run, as_of=received,
                                      payload_hash=digest), schema_version=schema, **metadata)
    frame = normalize_payload(payload, ingestion_run_id=run, as_of=received, payload_hash=digest,
                              raw_object_id=raw.object_id)
    if mutate:
        mutate(frame)
    normalized = store.write(kind=ObjectKind.NORMALIZED, frame=frame,
                              schema_version='normalized+' + schema, **metadata)
    with DuckDBCatalog(root / 'catalog.duckdb') as catalog:
        catalog.begin_run(run, DAY, received)
        for value in [raw, normalized]:
            catalog.record_object(run, value)
        catalog.finish_run(run, IngestionStatus.SUCCEEDED, received)
    return raw, normalized


@pytest.fixture
def request_data(tmp_path, features):
    _publish(tmp_path)
    master(tmp_path)
    return DailyMarketRequest(catalog_path=tmp_path / 'catalog.duckdb',
                              store_root=tmp_path / 'store',
                              feature_selection_path=features, start=DAY, end=DAY,
                              source_snapshot_as_of=RECEIVED)


def test_projection_recovers_optional_product_without_mutating_frozen_sources(request_data):
    before = request_data.catalog_path.read_bytes()
    result = project_daily_instruments(request_data)
    assert request_data.catalog_path.read_bytes() == before
    rows = {row['provider_code']: row for row in result['rows']}
    assert rows['72030']['round_lot_size'] == 100
    assert rows['72030']['tick_size'] == '0.5'  # 1020 yen, historical Large70
    assert rows['72030']['product_category'] == '011'
    assert rows['67580']['round_lot_size'] is None  # Foreign shares are not domestic lots.
    assert rows['67580']['raw_close'] is None  # Never lose a no-trade row.
    assert rows['130A0']['round_lot_size'] is None  # Legacy missing ProdCat stays unknown.
    assert len(result['source_objects']) == 4
    assert result['historical_as_known'] is False and result['adoption_eligible'] is False
    assert result['evaluation_ready'] is False
    assert result['unresolved_capabilities'] == [
        'corporate_action_coverage', 'directional_execution', 'execution_capacity',
        'settlement_buying_power', 'historical_known_at_inputs',
    ]


@pytest.mark.parametrize('price,topix,other', [
    ('1000', '0.1', '1'), ('1000.1', '0.5', '1'), ('3000', '0.5', '1'),
    ('3000.5', '1', '5'), ('5000', '1', '5'), ('5001', '1', '10'),
    ('10000', '1', '10'), ('10001', '5', '10'), ('30000', '5', '10'),
    ('30001', '10', '50'), ('50000', '10', '50'), ('50001', '10', '100'),
    ('100000', '10', '100'), ('100001', '50', '100'), ('300000', '50', '100'),
    ('300001', '100', '500'), ('500000', '100', '500'), ('500001', '100', '1000'),
    ('1000000', '100', '1000'), ('1000001', '500', '1000'),
    ('3000000', '500', '1000'), ('3000001', '1000', '5000'),
    ('5000000', '1000', '5000'), ('5000001', '1000', '10000'),
    ('10000000', '1000', '10000'), ('10000001', '5000', '10000'),
    ('30000000', '5000', '10000'), ('30000001', '10000', '50000'),
    ('50000000', '10000', '50000'), ('50000001', '10000', '100000'),
])
def test_published_tick_table_boundaries(price, topix, other):
    for category, expected in [('TOPIX Mid400', topix), ('TOPIX Small 1', other)]:
        result = instrument_rules(DAY, '011', category, Decimal(price))
        assert Decimal(result['tick_size']) == Decimal(expected)


@pytest.mark.parametrize('day,product,scale,price,lot,tick', [
    ('2018-09-28', '011', '-', '100', None, None),
    ('2018-10-01', '011', '-', '100', 100, None),
    ('2023-06-04', '011', 'TOPIX Mid400', '100', 100, None),
    ('2023-06-05', '011', 'TOPIX Core30', '100', 100, '0.1'),
    ('2027-02-28', '011', 'TOPIX Large70', '100', 100, '0.1'),
    ('2027-03-01', '011', 'TOPIX Large70', '100', 100, None),
    ('2025-11-06', '021', '-', '100', None, None),
    ('2025-11-06', '024', '-', '100', None, None),
    ('2025-11-06', '012', '-', '100', None, None),
    ('2025-11-06', '013', 'TOPIX Large70', '100', None, None),
    ('2025-11-06', None, 'TOPIX Large70', '100', None, None),
    ('2025-11-06', '011', 'unknown', '100', 100, None),
    ('2025-11-06', '011', None, '100', 100, None),
    ('2025-11-06', '011', '-', None, 100, None),
])
def test_rule_applicability_and_announced_regime_boundary(day, product, scale, price, lot, tick):
    result = instrument_rules(date.fromisoformat(day), product, scale,
                              None if price is None else Decimal(price))
    assert result['round_lot_size'] == lot and result['tick_size'] == tick


@pytest.mark.parametrize('price', ['0', '-1', 'NaN', 'Infinity'])
def test_invalid_prices_never_yield_a_tick(price):
    with pytest.raises(ValueError, match='price'):
        instrument_rules(DAY, '011', '-', Decimal(price))


def test_latest_vintage_respects_cutoff_and_not_current_scale(request_data, tmp_path):
    original = project_daily_instruments(request_data)
    row = dict(_all_endpoint_rows()['/v2/equities/master'][0], Date=str(DAY),
               Code='72030', ProdCat='011', ScaleCat='TOPIX Small 2')
    later = RECEIVED + timedelta(days=1)
    master(tmp_path, rows=[row], received=later)
    assert project_daily_instruments(request_data) == original
    result = project_daily_instruments(request_data.model_copy(update={
        'source_snapshot_as_of': later}))
    rows = {row['provider_code']: row for row in result['rows']}
    assert rows['72030']['tick_size'] == '1'
    assert rows['67580']['master_available_at'] is None
    assert result['summary']['missing_master_rows'] == 2


@pytest.mark.parametrize('change,message', [
    (lambda f: f.__setitem__('size_category', 'changed'), 'master value differs'),
    (lambda f: f.__setitem__('market_code', 'changed'), 'master value differs'),
    (lambda f: f.__setitem__('symbol', 'changed'), 'master symbol'),
    (lambda f: f.__setitem__('raw_object_id', 'unknown'), 'raw link'),
    (lambda f: f.__setitem__('effective_date', date(2025, 1, 1)), 'another date'),
    (lambda f: f.__setitem__('source_record_hash', 'a' * 64), 'lineage'),
])
def test_rehashed_master_corruption_rejected(tmp_path, features, change, message):
    _publish(tmp_path)
    master(tmp_path, mutate=change)
    request = DailyMarketRequest(catalog_path=tmp_path / 'catalog.duckdb',
                                store_root=tmp_path / 'store',
                                feature_selection_path=features, start=DAY, end=DAY,
                                source_snapshot_as_of=RECEIVED)
    with pytest.raises(StorageIntegrityError, match=message):
        project_daily_instruments(request)


def test_holdout_rejected_before_any_catalog_open(request_data):
    with pytest.raises(ValueError, match='holdout'):
        project_daily_instruments(request_data.model_copy(update={
            'end': date(2099, 1, 1), 'catalog_path': request_data.catalog_path / 'absent'}))


def test_cli_saves_private_receipt_with_no_nav_claim(request_data, tmp_path):
    path = tmp_path / 'request.json'
    path.write_text(request_data.model_dump_json(), encoding='utf-8')
    result = CliRunner().invoke(app, ['research', 'project-daily-instruments', '--input', str(path),
                                      '--output-root', str(tmp_path / 'receipts')])
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout)
    data = json.loads(Path(receipt['receipt']).read_text(encoding='utf-8'))
    assert data['evaluation_ready'] is False and data['adoption_eligible'] is False


def test_preferred_share_keeps_own_code_without_ordinary_tick_or_lot(tmp_path, features):
    prices = _rows()
    prices.append(dict(prices[0], Code='72035', C=3888))
    _publish(tmp_path, prices)
    row = dict(_all_endpoint_rows()['/v2/equities/master'][0], Date=str(DAY),
               Code='72035', ProdCat='011', ScaleCat='-')
    master(tmp_path, rows=[row])
    request = DailyMarketRequest(catalog_path=tmp_path / 'catalog.duckdb',
                                store_root=tmp_path / 'store', feature_selection_path=features,
                                start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    data = project_daily_instruments(request)
    rows = {row['provider_code']: row for row in data['rows']}
    assert len(rows) == 4 and rows['72035']['symbol'] is None
    assert rows['72035']['raw_close'] == 3888
    assert rows['72035']['round_lot_size'] is None
    assert rows['72035']['tick_size'] is None
    assert rows['72035']['tick_missing_reason'] == 'ordinary_share_class_not_proven'
    # Missing master and master-only keys survive rather than an inner join.
    assert rows['72030']['master_object_id'] is None


def test_empty_newer_master_replaces_whole_older_date_snapshot(request_data, tmp_path):
    later = RECEIVED + timedelta(days=1)
    master(tmp_path, rows=[], received=later)
    data = project_daily_instruments(request_data.model_copy(update={
        'source_snapshot_as_of': later}))
    assert data['summary']['rows'] == 3
    assert data['summary']['missing_master_rows'] == 3
    assert data['summary']['lot_rule_rows'] == 0


def test_master_only_rows_and_unreceived_master_not_silently_used(tmp_path, features):
    _publish(tmp_path)
    master_row = dict(_all_endpoint_rows()['/v2/equities/master'][0], Date=str(DAY),
                      Code='99990', ProdCat='011', ScaleCat='-')
    master(tmp_path, rows=[master_row], received=RECEIVED + timedelta(seconds=1))
    request = DailyMarketRequest(catalog_path=tmp_path / 'catalog.duckdb',
                                store_root=tmp_path / 'store', feature_selection_path=features,
                                start=DAY, end=DAY, source_snapshot_as_of=RECEIVED)
    data = project_daily_instruments(request)
    assert data['summary']['missing_master_rows'] == 3
    newer = project_daily_instruments(request.model_copy(update={
        'source_snapshot_as_of': RECEIVED + timedelta(seconds=1)}))
    assert newer['summary']['rows'] == 4 and newer['summary']['missing_price_rows'] == 1
    row = next(row for row in newer['rows'] if row['provider_code'] == '99990')
    assert row['round_lot_size'] == 100 and row['tick_size'] is None


def test_cli_rejects_holdout_without_receipt(request_data, tmp_path):
    path = tmp_path / 'future.json'
    path.write_text(request_data.model_copy(update={'end': date(2099, 1, 1)}).model_dump_json(),
                    encoding='utf-8')
    result = CliRunner().invoke(app, ['research', 'project-daily-instruments', '--input', str(path),
                                      '--output-root', str(tmp_path / 'out')])
    assert result.exit_code == 2 and 'holdout' in result.output
    assert not (tmp_path / 'out').exists()
