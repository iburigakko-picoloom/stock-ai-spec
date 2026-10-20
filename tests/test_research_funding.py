from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

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
from stock_ai.ml.daily_market import DailyMarketRequest
from stock_ai.ml.nav import NavCash, evaluate_stateful_nav, fixed_bps_policy
from stock_ai.ml.research_funding import (
    build_funding_schedule,
    project_research_funding,
    require_research_funding,
)
from tests.test_daily_market import features as feature_fixture
from tests.test_daily_nav import DATES, at, order, position, quote, request

FIRST = date(2024, 4, 26)
LAST = date(2024, 5, 10)
RECEIVED = datetime(2026, 10, 18, tzinfo=UTC)


def calendar():
    # Golden Week: 4/29 and 5/3/6 are non-cash sessions even when OSE trades.
    closed = {date(2024, 4, 29), date(2024, 5, 3), date(2024, 5, 6)}
    days = [FIRST + timedelta(days=i) for i in range((LAST - FIRST).days + 1)]
    return tuple((day, 3 if day in closed else int(day.weekday() < 5)) for day in days)


@pytest.fixture(scope='module')
def features(tmp_path_factory):
    return feature_fixture.__wrapped__(tmp_path_factory)


def publish(root, day, division, *, received=RECEIVED, mutate=None):
    payload = FetchedPayload(dataset=DatasetName.TRADING_CALENDAR, endpoint='/markets/calendar',
                             query=(), pages=1, requested_at=received, received_at=received,
                             rows=({'Date': str(day), 'HolDiv': str(division)},))
    digest = canonical_payload_hash(payload.rows)
    run = str(day) + received.isoformat() + digest
    store = ImmutableParquetStore(root / 'store')
    metadata = dict(dataset=payload.dataset, source_date=day, payload_hash=digest,
                    source_endpoint=payload.endpoint, received_at=received, available_at=received,
                    as_of=received, ingestion_run_id=run,
                    quality=QualityReport(dataset=payload.dataset, rows=1))
    schema = ENDPOINT_SCHEMAS[payload.dataset].schema_version
    raw = store.write(kind=ObjectKind.RAW, schema_version=schema, **metadata,
                      frame=raw_frame(payload, ingestion_run_id=run, as_of=received,
                                      payload_hash=digest))
    frame = normalize_payload(payload, ingestion_run_id=run, as_of=received, payload_hash=digest,
                              raw_object_id=raw.object_id)
    if mutate:
        mutate(frame)
    normal = store.write(kind=ObjectKind.NORMALIZED, schema_version='normalized+' + schema,
                         frame=frame, **metadata)
    with DuckDBCatalog(root / 'catalog.duckdb') as catalog:
        catalog.begin_run(run, day, received)
        for obj in [raw, normal]:
            catalog.record_object(run, obj)
        catalog.finish_run(run, IngestionStatus.SUCCEEDED, received)
    return raw, normal


@pytest.fixture
def source(tmp_path, features):
    for day, division in calendar():
        publish(tmp_path, day, division)
    return DailyMarketRequest(catalog_path=tmp_path / 'catalog.duckdb',
                              store_root=tmp_path / 'store',
                              feature_selection_path=features, start=FIRST, end=LAST,
                              source_snapshot_as_of=RECEIVED)


def test_holidays_and_weekends_do_not_release_cash_early():
    result = build_funding_schedule(calendar(), start=FIRST, end=LAST)
    rows = {row['trading_date']: row for row in result['rows']}
    assert rows['2024-04-26']['settlement_date_proxy'] == '2024-05-01'
    assert rows['2024-04-26']['sale_cash_available_at'] == '2024-05-02T09:00:00+09:00'
    assert rows['2024-05-02']['settlement_date_proxy'] == '2024-05-08'
    assert rows['2024-05-02']['sale_cash_available_at'] == '2024-05-09T09:00:00+09:00'
    assert '2024-04-29' not in rows and '2024-05-03' not in rows
    assert rows['2024-05-10']['sale_cash_available_at'] is None
    assert rows['2024-05-10']['blocking_reason'] == 'CALENDAR_TAIL_INSUFFICIENT'
    assert result['research_assumption'] is True and not result['broker_verified']


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unsorted', 'bool', 'invalid', 'extra'])
def test_incomplete_or_invalid_calendar_never_falls_back_to_weekdays(change):
    rows = list(calendar())
    if change == 'missing':
        del rows[3]
    elif change == 'duplicate':
        rows.insert(2, rows[2])
    elif change == 'unsorted':
        rows.reverse()
    elif change == 'bool':
        rows[0] = rows[0][0], True
    elif change == 'invalid':
        rows[0] = rows[0][0], 4
    else:
        rows.append((LAST + timedelta(days=1), 0))
    with pytest.raises(ValueError, match='calendar'):
        build_funding_schedule(tuple(rows), start=FIRST, end=LAST)


def test_rule_start_half_day_and_partial_tail_are_explicit():
    days = tuple((date(2019, 7, 15) + timedelta(days=i), 2) for i in range(6))
    result = build_funding_schedule(days, start=days[0][0], end=days[-1][0])
    assert result['rows'][0]['blocking_reason'] == 'UNSUPPORTED_SETTLEMENT_REGIME'
    assert result['rows'][1]['sale_cash_available_at'].startswith('2019-07-19T09:00:00')
    assert result['rows'][-2]['settlement_date_proxy'] is None


def test_authentication_preserves_original_source_and_late_vintage(source, tmp_path):
    before = source.catalog_path.read_bytes()
    result = project_research_funding(source)
    assert source.catalog_path.read_bytes() == before
    assert len(result['source_objects']) == 30
    assert result['historical_as_known'] is False and result['adoption_eligible'] is False
    later = RECEIVED + timedelta(days=1)
    publish(tmp_path, FIRST, 0, received=later)
    assert project_research_funding(source) == result
    revised = project_research_funding(source.model_copy(update={'source_snapshot_as_of': later}))
    assert len(revised['rows']) == len(result['rows']) - 1


@pytest.mark.parametrize('change,message', [
    (lambda f: f.__setitem__('holiday_division', 0), 'calendar value'),
    (lambda f: f.__setitem__('is_equity_business_day', False), 'calendar value'),
    (lambda f: f.__setitem__('trading_date', date(2020, 1, 1)), 'calendar date'),
    (lambda f: f.__setitem__('raw_object_id', 'unknown'), 'raw link'),
    (lambda f: f.__setitem__('source_record_hash', 'a' * 64), 'lineage'),
])
def test_rehashed_source_inconsistency_rejected(tmp_path, features, change, message):
    publish(tmp_path, FIRST, 1, mutate=change)
    request_data = DailyMarketRequest(catalog_path=tmp_path / 'catalog.duckdb',
                                      store_root=tmp_path / 'store',
                                      feature_selection_path=features,
                                      start=FIRST, end=FIRST, source_snapshot_as_of=RECEIVED)
    with pytest.raises(StorageIntegrityError, match=message):
        project_research_funding(request_data)


def test_holdout_rejected_before_opening_catalog(source):
    with pytest.raises(ValueError, match='holdout'):
        project_research_funding(source.model_copy(update={
            'end': date(2099, 1, 1), 'catalog_path': Path('absent.duckdb')}))


@pytest.mark.parametrize('released', [False, True])
def test_sale_remains_in_nav_but_not_funding_until_exact_release_time(released):
    # Existing ledger, 20bps cost, a synthetic weekday-only (not JPX) calendar.
    # Holiday accuracy is independently hand-checked against Golden Week above.
    end = DATES[11]
    # Construct all preceding sessions too so no evaluation date is omitted.
    all_dates = tuple((DATES[0] + timedelta(days=i),
                       int((DATES[0] + timedelta(days=i)).weekday() < 5))
                      for i in range((end - DATES[0]).days + 1))
    schedule = build_funding_schedule(all_dates, start=DATES[0], end=end)
    by_date = {row['trading_date']: row for row in schedule['rows']}
    accounting = request(prices=tuple((quote('A', '100'), quote('B', '50')) for _ in range(8)),
                         positions=(position(),), cash=(NavCash(bucket='cash', amount=D(0)),),
                         cost_policy=fixed_bps_policy(D(20)))
    sessions = tuple(s.model_copy(update={'sale_cash_available_at': datetime.fromisoformat(
        by_date[str(s.trading_date)]['sale_cash_available_at'])}) for s in accounting.sessions)
    if not released:
        # The negative fill must actually execute before release. An order
        # decided earlier but executed at noon can legitimately see 09:00 cash.
        sessions = (*sessions[:-1], sessions[-1].model_copy(update={
            'execution_at': at(7, 9) - timedelta(seconds=1)}))
    accounting = accounting.model_copy(update={'sessions': sessions,
                                               'calendar_id': schedule['calendar_id']})
    require_research_funding(accounting, schedule)
    seen = []

    def decide(state):
        i = DATES.index(state.as_of.date())
        seen.append((i, state.cash[0].amount, sum(r.amount for r in state.receivables)))
        orders = (order(i, side='SELL'),) if i == 4 else (
            (order(i, symbol='B'),) if i >= 5 else ())
        return tuple(o.model_copy(update={'decided_at': state.as_of}) for o in orders)

    times = [at(i, 11) for i in range(8)]
    times[-1] = at(7, 9) - timedelta(seconds=0 if released else 2)
    _, result = evaluate_stateful_nav(accounting, decision_times=times,
                                     decide=decide)
    assert seen[5][1:] == (D(0), D(9980)) and seen[6][1:] == (D(0), D(9980))
    assert result.days[4].nav == D(9980) and result.days[5].nav == D(9980)
    assert result.days[5].fills[0].filled_shares == result.days[6].fills[0].filled_shares == 0
    assert seen[7][1:] == ((D(9980), D(0)) if released else (D(0), D(9980)))
    assert result.days[7].fills[0].filled_shares == (100 if released else 0)
    assert result.days[7].cash[0].amount == (D(4970) if released else D(9980))
    # Releasing one second before the declared policy is rejected before replay.
    changed = sessions[4].model_copy(update={
        'sale_cash_available_at': sessions[4].sale_cash_available_at - timedelta(seconds=1)})
    with pytest.raises(ValueError, match='funding'):
        require_research_funding(accounting.model_copy(update={
            'sessions': (*sessions[:4], changed, *sessions[5:])}), schedule)
    altered = copy.deepcopy(schedule)
    altered['rows'][4]['sale_cash_available_at'] = at(4).isoformat()
    with pytest.raises(ValueError, match='funding'):
        require_research_funding(accounting, altered)


def test_cli_persists_schedule_and_explicit_assumption(source, tmp_path):
    path = tmp_path / 'request.json'
    path.write_text(source.model_dump_json(), encoding='utf-8')
    result = CliRunner().invoke(app, ['research', 'project-research-funding', '--input', str(path),
                                      '--output-root', str(tmp_path / 'out')])
    assert result.exit_code == 0, result.output
    data = json.loads(Path(json.loads(result.stdout)['receipt']).read_text(encoding='utf-8'))
    assert data['research_assumption'] is True and data['broker_verified'] is False
