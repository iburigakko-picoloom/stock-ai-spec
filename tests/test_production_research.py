from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest
from typer.testing import CliRunner

import stock_ai.cli as stock_cli
import stock_ai.data.production as production_module
import stock_ai.ml.advanced as advanced_module
from stock_ai.cli import app
from stock_ai.data import DatasetName, HistoricalRevisionPolicy, SubscriptionPlan
from stock_ai.data.production import build_production_data
from stock_ai.decision import (
    CostPolicy,
    DailyPortfolioDecisionEngine,
    DecisionEngineConfig,
    SimpleJapanTaxEngine,
    TaxPolicy,
    TransactionCostEngine,
)
from stock_ai.domain import (
    Account,
    AccountBucket,
    AccountType,
    CashState,
    PortfolioState,
    TaxState,
    WithholdingMode,
)
from stock_ai.features import V0_MANIFEST, V1_CORE_MANIFEST, V2_EXTENDED_MANIFEST
from stock_ai.ml.production import (
    build_production_feature_sets,
    build_production_supervised_dataset,
    load_production_build_manifest,
    load_production_dataset_snapshot,
    load_production_feature_snapshot,
    load_production_feature_snapshot_metadata,
    run_production_walk_forward_baselines,
    write_production_baseline_report,
    write_production_build_manifest,
    write_production_dataset_snapshot,
    write_production_feature_snapshot,
)
from stock_ai.research import run_research_decision_e2e

JST = ZoneInfo("Asia/Tokyo")


@pytest.mark.parametrize("symbol_dtype", ["object", "string", "category"])
@pytest.mark.parametrize("duplicate_index", [False, True])
@pytest.mark.parametrize("timezone", [None, "Asia/Tokyo"])
def test_universe_intervals_preserve_gaps_and_exclude_invalid_symbol_history(
    symbol_dtype: str, duplicate_index: bool, timezone: str | None,
) -> None:
    dates = pd.bdate_range("2026-01-05", periods=7, tz=timezone)
    rows = []
    for symbol, sessions in [("A", [0, 1, 3, 4, 6]), ("B", list(range(7))),
                             ("outside", [1, 2, 7]), (None, [0])]:
        for session in sessions:
            rows.append({
                "effective_date": dates[session] if session < 7 else dates[-1] + timedelta(days=1),
                "provider_code": "10000", "symbol": symbol, "company_name": "Example",
                "sector_33_code": "10", "sector_33_name": "Sector", "market_code": "0111",
                "market_name": "Prime", "available_at": "2026-02-01T00:00:00Z",
            })
    master = pd.DataFrame(rows).sample(frac=1, random_state=19)
    if symbol_dtype == "category":
        master["symbol"] = pd.Categorical(master.symbol, categories=["B", "A", "outside", "unused"])
    else:
        master["symbol"] = master.symbol.astype(symbol_dtype)
    if duplicate_index:
        master.index = [0] * len(master)
    before = master.copy(deep=True)

    actual = production_module.build_point_in_time_universe(master, business_dates=dates)

    assert set(actual.symbol) == {"A", "B"}
    a = actual.loc[actual.symbol == "A"]
    assert list(a.effective_date) == [dates[i] for i in [0, 1, 3, 4, 6]]
    assert list(a.valid_from) == [dates[i] for i in [0, 0, 3, 3, 6]]
    assert list(a.valid_to.iloc[:-1]) == [dates[i] for i in [2, 2, 5, 5]]
    assert pd.isna(a.valid_to.iloc[-1])
    b = actual.loc[actual.symbol == "B"]
    assert list(b.effective_date) == list(dates)
    assert (b.valid_from == dates[0]).all()
    assert b.valid_to.isna().all()
    pdt.assert_series_equal(actual.listing_date, actual.valid_from, check_names=False)
    pdt.assert_series_equal(actual.delisting_date, actual.valid_to, check_names=False)
    assert actual.is_member.all()
    pdt.assert_frame_equal(master, before)


@pytest.mark.parametrize("integer_close", [False, True])
@pytest.mark.parametrize("utc_cutoffs", [False, True])
@pytest.mark.parametrize("categorical", [False, True])
@pytest.mark.parametrize("duplicate_index", [False, True])
@pytest.mark.parametrize("policy", list(HistoricalRevisionPolicy))
def test_financial_expansion_is_symbol_independent_and_preserves_inputs(
    integer_close: bool,
    utc_cutoffs: bool,
    categorical: bool,
    duplicate_index: bool,
    policy: HistoricalRevisionPolicy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames, dates = _source_frames(periods=30)
    disclosures = frames[DatasetName.FINANCIAL_SUMMARY].copy()
    disclosures["available_at"] = disclosures["announced_at"]
    correction = disclosures.loc[disclosures.symbol == "A"].copy()
    correction["disclosure_number"] = "disc-A-z-correction"
    correction["forecast_eps"] = 121.0
    correction["available_at"] = correction["available_at"] + pd.Timedelta(days=2)
    disclosures = pd.concat([disclosures, correction], ignore_index=True).iloc[[2, 3, 0, 1]]
    if categorical:
        disclosures["symbol"] = pd.Categorical(
            disclosures.symbol, categories=["C", "A", "B", "unused"]
        )
    if duplicate_index:
        disclosures.index = [7] * len(disclosures)
    daily = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "trading_date": day,
                "available_at": pd.Timestamp(day)
                .tz_localize("Asia/Tokyo")
                .replace(hour=11, minute=30),
                "close": 1100.0 + index,
            }
            for symbol in ("B", "A", "missing", "C")
            for index, day in enumerate(dates[:4])
        ]
    ).iloc[::-1]
    if integer_close:
        daily["close"] = daily["close"].astype("int64")
    if utc_cutoffs:
        daily["available_at"] = pd.to_datetime(daily["available_at"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
    batch_calls = []
    original_batch = production_module._batch_daily_financials

    def observed_batch(*args, **kwargs):
        batch_calls.append(1)
        return original_batch(*args, **kwargs)

    monkeypatch.setattr(production_module, "_batch_daily_financials", observed_batch)
    before_daily, before_disclosures = daily.copy(deep=True), disclosures.copy(deep=True)
    actual = production_module._daily_financial_features(
        disclosures, daily=daily, revision_policy=policy
    )
    independent = [
        production_module._daily_financial_features(
            disclosures.loc[disclosures.symbol == symbol].copy(),
            # Object timestamps use the unchanged per-symbol compatibility path.
            daily=group.assign(available_at=group["available_at"].astype(object)),
            revision_policy=policy,
        )
        for symbol, group in daily.groupby("symbol", sort=True)
    ]
    for index in (0, 1):
        expected = pd.concat([part[index] for part in independent], ignore_index=True)
        pdt.assert_frame_equal(actual[index], expected, check_exact=True)
    missing = actual[0].loc[actual[0].symbol == "missing"]
    assert missing["financial_available_at"].isna().all() and missing["per"].isna().all()
    pdt.assert_frame_equal(daily, before_daily, check_exact=True)
    pdt.assert_frame_equal(disclosures, before_disclosures, check_exact=True)
    assert len(batch_calls) == int(utc_cutoffs)


def test_bulk_adjusted_prices_follow_official_cumulative_factor_formula() -> None:
    dates = pd.to_datetime(["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-13"])
    frame = pd.DataFrame(
        {
            "symbol": "A",
            "trading_date": dates,
            "raw_open": [990.0, 475.0, 395.0, 405.0],
            "raw_high": [1010.0, 485.0, 405.0, 415.0],
            "raw_low": [980.0, 470.0, 390.0, 400.0],
            "raw_close": [1000.0, 480.0, 400.0, 410.0],
            "raw_volume": [100.0, 200.0, 300.0, 400.0],
            "adjustment_factor": [1.0, 0.5, 0.8, 1.0],
            "ex_rights_type": [pd.NA, "1", "3", pd.NA],
            "research_open": np.nan,
            "research_high": np.nan,
            "research_low": np.nan,
            "research_close": np.nan,
            "research_volume": np.nan,
            "adjustment_version": "bulk-payload",
            "adjustment_source": "bulk_adjfactor_only",
        }
    )

    before = frame.copy(deep=True)
    adjusted = production_module._reconstruct_bulk_adjusted_prices(frame)

    assert adjusted["research_close"].tolist() == pytest.approx([400.0, 384.0, 400.0, 410.0])
    assert adjusted["research_volume"].tolist() == pytest.approx([200.0, 200.0, 300.0, 400.0])
    assert set(adjusted["adjustment_source"]) == {"official_file_adjfactor_formula_v1"}
    assert (
        adjusted["adjustment_version"].str.startswith("jquants-file-cumulative-adjfactor-v1:").all()
    )
    pdt.assert_frame_equal(frame, before, check_exact=True)
    owned = frame.copy(deep=True)
    pdt.assert_frame_equal(
        production_module._reconstruct_bulk_adjusted_prices(owned, owned_input=True),
        adjusted,
        check_exact=True,
    )
    pdt.assert_frame_equal(frame, before, check_exact=True)
    changed_input = frame.copy()
    changed_input.loc[0, "raw_high"] += 1
    changed = production_module._reconstruct_bulk_adjusted_prices(changed_input)
    assert changed.loc[0, "adjustment_version"] != adjusted.loc[0, "adjustment_version"]


def test_production_coverage_starts_at_first_eligible_market_snapshot() -> None:
    dates = pd.bdate_range("2022-03-31", periods=4)
    calendar = pd.DataFrame({"trading_date": dates, "is_equity_business_day": True})
    master = pd.DataFrame(
        {
            "effective_date": dates,
            "provider_code": "13010",
            "market_code": ["0101", "0101", "0111", "0111"],
        }
    )
    prices = pd.DataFrame({"trading_date": dates})
    topix = pd.DataFrame({"trading_date": dates})

    bounded = production_module._bounded_business_dates(
        calendar,
        master=master,
        prices=prices,
        topix=topix,
    )

    assert bounded.tolist() == dates[2:].tolist()


def test_canonical_daily_joins_common_issues_by_provider_code() -> None:
    trading_date = pd.Timestamp("2025-01-06")
    revision_at = pd.Timestamp("2026-08-24T00:00:00Z")
    prices = pd.DataFrame(
        {
            "trading_date": [trading_date, trading_date, trading_date],
            "provider_code": ["25930", "25935", "99990"],
            "symbol": ["2593", "2593", "9999"],
            "raw_open": [995.0, 895.0, np.nan],
            "raw_high": [1010.0, 910.0, np.nan],
            "raw_low": [990.0, 890.0, np.nan],
            "raw_close": [1000.0, 900.0, np.nan],
            "raw_volume": [1000.0, 100.0, np.nan],
            "trading_value": [1_000_000.0, 100_000.0, np.nan],
            "adjustment_factor": [1.0, 1.0, 1.0],
            "research_open": [995.0, 895.0, np.nan],
            "research_high": [1010.0, 910.0, np.nan],
            "research_low": [990.0, 890.0, np.nan],
            "research_close": [1000.0, 900.0, np.nan],
            "research_volume": [1000.0, 100.0, np.nan],
            "adjustment_version": ["adjustment-v1", "adjustment-v1", "adjustment-v1"],
            "available_at": [revision_at, revision_at, revision_at],
        }
    )
    universe = pd.DataFrame(
        {
            "effective_date": [trading_date, trading_date],
            "provider_code": ["25930", "99990"],
            "symbol": ["2593", "9999"],
            "sector_33_code": ["10", "20"],
            "sector_33_name": ["Sector 10", "Sector 20"],
        }
    )
    availability = {trading_date: pd.Timestamp("2025-01-07T02:30:00Z")}
    before_prices, before_universe = prices.copy(deep=True), universe.copy(deep=True)

    daily = production_module._canonical_daily(
        prices,
        universe=universe,
        availability=availability,
        revision_policy=HistoricalRevisionPolicy.SINGLE_VINTAGE_AS_REVISED,
    )

    assert daily["provider_code"].tolist() == ["25930"]
    assert daily["symbol"].tolist() == ["2593"]
    reused = production_module._canonical_daily(
        prices,
        universe=universe,
        availability=availability,
        revision_policy=HistoricalRevisionPolicy.SINGLE_VINTAGE_AS_REVISED,
        reuse_working_frame=True,
    )
    pdt.assert_frame_equal(reused, daily, check_exact=True)
    pdt.assert_frame_equal(prices, before_prices, check_exact=True)
    pdt.assert_frame_equal(universe, before_universe, check_exact=True)


class FrameCatalog:
    def __init__(self, frames: dict[DatasetName, pd.DataFrame]) -> None:
        self.frames = frames

    def point_in_time(self, dataset: DatasetName, _as_of: datetime) -> pd.DataFrame:
        return self.frames[dataset].copy()


class ContextFrameCatalog(FrameCatalog):
    def __enter__(self) -> ContextFrameCatalog:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_mobile_latest_features_require_authenticated_next_session_and_closed_cutoff() -> None:
    frames, dates = _source_frames(periods=8)
    cutoff = datetime.combine((dates[-1] + pd.offsets.BDay()).date(), datetime.min.time(), JST)
    cutoff = cutoff.replace(hour=11, minute=30)
    received = cutoff - timedelta(hours=1)
    for frame in frames.values():
        frame["available_at"] = pd.Timestamp(received)
    calendar = frames[DatasetName.TRADING_CALENDAR]
    next_day = calendar.iloc[[-1]].copy()
    next_day["trading_date"] = pd.Timestamp(cutoff.date())
    frames[DatasetName.TRADING_CALENDAR] = pd.concat([calendar, next_day], ignore_index=True)
    catalog = FrameCatalog(frames)
    bundle = build_production_data(
        catalog,
        source_snapshot_as_of=received,
        minimum_market_coverage=0.60,
        proposal_as_of=cutoff,
    )
    latest = bundle.daily.loc[bundle.daily.trading_date == dates[-1]]
    assert len(latest) == 2
    assert (latest.available_at == pd.Timestamp(cutoff)).all()
    with pytest.raises(ValueError, match="closed 11:30"):
        build_production_data(
            catalog, source_snapshot_as_of=cutoff + timedelta(seconds=1), proposal_as_of=cutoff
        )
    with pytest.raises(ValueError, match="closed 11:30"):
        build_production_data(
            catalog, source_snapshot_as_of=received, proposal_as_of=cutoff.replace(minute=29)
        )
    with pytest.raises(ValueError, match="not authenticated"):
        build_production_data(
            catalog, source_snapshot_as_of=received, proposal_as_of=cutoff + timedelta(days=1)
        )


def test_daily_label_metadata_matches_actual_production_next_session_target() -> None:
    from mobile.python.model_bundle import ModelBundle

    from stock_ai.ml import build_supervised_dataset
    from stock_ai.operations.daily import PredictionSnapshot

    frames, _ = _source_frames()
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames), source_snapshot_as_of=datetime(2026, 8, 24, tzinfo=UTC),
        minimum_market_coverage=0.60,
    )
    dates = pd.DatetimeIndex(bundle.universe.effective_date.unique()).sort_values()
    origin = 100
    daily = bundle.daily.copy()
    for offset, price in ((0, 100.0), (1, 200.0), (5, 150.0), (6, 170.0),
                          (20, 250.0), (21, 300.0)):
        daily.loc[(daily.symbol == "B") & (daily.trading_date == dates[origin + offset]),
                  "adjusted_close"] = price
    bundle = replace(bundle, daily=daily)
    features = build_production_feature_sets(bundle).v2_extended
    assert features is not None
    production, _ = build_production_supervised_dataset(
        features, bundle, plan=SubscriptionPlan.LIGHT,
    )
    row = production.loc[(production.symbol == "B") &
                         (production.trading_date == dates[origin])].iloc[0]
    assert row.label_entry_date == dates[origin + 1]
    assert row.as_of.tz_convert(JST).date() == row.label_entry_date.date()
    for h, value in ((5, 170 / 200 - 1), (20, 300 / 200 - 1)):
        assert row[f"target_return_{h}d"] == pytest.approx(value)
        assert row[f"label_end_date_{h}d"] == dates[origin + 1 + h]
    generic = build_supervised_dataset(features.loc[features.symbol == "B"])
    generic_row = generic.loc[generic.trading_date == dates[origin]].iloc[0]
    assert generic_row.target_return_5d == pytest.approx(150 / 100 - 1)
    assert generic_row.target_return_20d == pytest.approx(250 / 100 - 1)
    for cls in (ModelBundle, PredictionSnapshot):
        assert cls.model_fields["label_definition"].default == (
            "next_session_adjusted_close_to_h_sessions_later"
        )


def test_production_pipeline_is_point_in_time_and_uses_fixed_calendar_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames, dates = _source_frames()
    source_as_of = datetime(2026, 8, 24, tzinfo=UTC)
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames),
        source_snapshot_as_of=source_as_of,
        minimum_market_coverage=0.60,
    )

    historical_a = bundle.universe.loc[bundle.universe["symbol"] == "A"]
    assert not historical_a.empty
    assert historical_a["effective_date"].min() == dates[0]
    assert historical_a["delisting_date"].dropna().max() == dates[-10]
    assert "A" not in set(
        bundle.universe.loc[bundle.universe["effective_date"] == dates[-1], "symbol"]
    )

    b_financial = bundle.financials.loc[bundle.financials["symbol"] == "B"].sort_values(
        "trading_date"
    )
    assert pd.isna(b_financial.iloc[0]["financial_available_at"])
    assert pd.notna(b_financial.iloc[1]["financial_available_at"])
    assert (
        pd.to_datetime(bundle.financials["financial_available_at"], utc=True).dropna()
        <= pd.to_datetime(
            bundle.financials.loc[
                bundle.financials["financial_available_at"].notna(), "available_at"
            ],
            utc=True,
        )
    ).all()

    assert len(bundle.corporate_actions) == 1
    assert bundle.corporate_actions.iloc[0]["symbol"] == "A"
    assert bundle.corporate_actions.iloc[0]["ratio"] == 2.0

    feature_sets = build_production_feature_sets(bundle)
    assert set(V0_MANIFEST.feature_names) <= set(feature_sets.v0)
    assert set(V1_CORE_MANIFEST.feature_names) <= set(feature_sets.v1_core)
    assert feature_sets.v2_extended is not None
    assert set(V2_EXTENDED_MANIFEST.feature_names) <= set(feature_sets.v2_extended)
    assert len(feature_sets.v0) == len(feature_sets.v1_core)
    assert feature_sets.v1_core["shares_outstanding_is_missing"].any()

    dataset, label_1230_status = build_production_supervised_dataset(
        feature_sets.v2_extended,
        bundle,
        plan=SubscriptionPlan.STANDARD,
    )
    assert label_1230_status.value == "BLOCKED_BY_DATA_CAPABILITY"
    assert not any(column.startswith("target_1230_return") for column in dataset)
    available_labels = dataset.loc[dataset["label_status_5d"] == "AVAILABLE"]
    label_as_of_dates = pd.to_datetime(available_labels["as_of"], utc=True).dt.tz_convert(JST)
    assert (
        pd.to_datetime(available_labels["label_entry_date"]).dt.date == label_as_of_dates.dt.date
    ).all()
    assert (label_as_of_dates.dt.hour == 11).all()
    assert (label_as_of_dates.dt.minute == 30).all()

    delisted = dataset.loc[
        (dataset["symbol"] == "A") & (dataset["trading_date"] == dates[-15])
    ].iloc[0]
    assert delisted["label_entry_date"] == dates[-14]
    assert delisted["label_end_date_5d"] == dates[-9]
    assert delisted["label_status_5d"] == "DELISTED_NO_EXIT_PRICE"
    assert pd.isna(delisted["target_return_5d"])

    suspended = dataset.loc[
        (dataset["symbol"] == "C") & (dataset["trading_date"] == dates[194])
    ].iloc[0]
    assert suspended["label_entry_date"] == dates[195]
    assert suspended["label_end_date_5d"] == dates[200]
    assert suspended["label_status_5d"] == "SUSPENDED_NO_EXIT_PRICE"
    assert pd.isna(suspended["target_return_5d"])

    snapshot = write_production_dataset_snapshot(
        dataset,
        tmp_path,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
        label_1230_status=label_1230_status,
        manifests=(V0_MANIFEST, V1_CORE_MANIFEST, V2_EXTENDED_MANIFEST),
    )
    repeated = write_production_dataset_snapshot(
        dataset,
        tmp_path,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
        label_1230_status=label_1230_status,
        manifests=(V0_MANIFEST, V1_CORE_MANIFEST, V2_EXTENDED_MANIFEST),
    )
    assert repeated.snapshot_id == snapshot.snapshot_id
    assert snapshot.parquet_path.is_file()
    assert snapshot.metadata_path.is_file()
    loaded_snapshot, loaded = load_production_dataset_snapshot(snapshot.parquet_path)
    assert loaded_snapshot.snapshot_id == snapshot.snapshot_id
    assert len(loaded) == snapshot.rows
    persisted = pd.read_parquet(snapshot.parquet_path)
    persisted_delisted = persisted.loc[
        (persisted["symbol"] == "A") & (persisted["trading_date"] == dates[-15])
    ].iloc[0]
    assert persisted_delisted["label_status_5d"] == "DELISTED_NO_EXIT_PRICE"
    feature_snapshot = write_production_feature_snapshot(
        feature_sets.v1_core,
        tmp_path / "features",
        manifest=V1_CORE_MANIFEST,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
    )
    assert feature_snapshot.parquet_path.is_file()
    loaded_feature_snapshot, loaded_features = load_production_feature_snapshot(
        feature_snapshot.parquet_path
    )
    assert loaded_feature_snapshot.snapshot_id == feature_snapshot.snapshot_id
    assert len(loaded_features) == feature_snapshot.rows
    historical_manifest = V1_CORE_MANIFEST.model_copy(update={"code_commit": "historical-commit"})
    historical_feature_snapshot = write_production_feature_snapshot(
        feature_sets.v1_core,
        tmp_path / "features-historical-manifest",
        manifest=historical_manifest,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
    )
    loaded_historical, _ = load_production_feature_snapshot(
        historical_feature_snapshot.parquet_path
    )
    assert loaded_historical.manifest_hash == historical_manifest.manifest_hash
    assert (
        load_production_feature_snapshot_metadata(historical_feature_snapshot.parquet_path)
        == historical_feature_snapshot
    )
    v0_snapshot = write_production_feature_snapshot(
        feature_sets.v0,
        tmp_path / "features-v0",
        manifest=V0_MANIFEST,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
    )
    v2_snapshot = write_production_feature_snapshot(
        feature_sets.v2_extended,
        tmp_path / "features-v2",
        manifest=V2_EXTENDED_MANIFEST,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
    )
    build_manifest = write_production_build_manifest(
        v0_snapshot,
        feature_snapshot,
        v2_snapshot,
        snapshot,
        tmp_path / "builds",
        created_at=datetime(2026, 8, 25, 0, 2, tzinfo=UTC),
    )
    assert load_production_build_manifest(build_manifest.manifest_path) == build_manifest
    with pytest.raises(ValueError, match="one observation as_of"):
        write_production_build_manifest(
            v0_snapshot,
            feature_snapshot,
            v2_snapshot.model_copy(update={"as_of": v2_snapshot.as_of - timedelta(days=1)}),
            snapshot,
            tmp_path / "as-of-mismatch-builds",
            created_at=datetime(2026, 8, 25, 0, 2, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="one revision policy"):
        write_production_build_manifest(
            v0_snapshot,
            feature_snapshot,
            v2_snapshot.model_copy(update={"historical_revision_policy": "STRICT_AS_KNOWN"}),
            snapshot,
            tmp_path / "revision-mismatch-builds",
            created_at=datetime(2026, 8, 25, 0, 2, tzinfo=UTC),
        )
    mismatched_dataset = dataset.copy()
    mismatched_dataset.loc[mismatched_dataset.index[0], "risk.max_drawdown_120d"] = 0.25
    mismatched_snapshot = write_production_dataset_snapshot(
        mismatched_dataset,
        tmp_path / "mismatched-datasets",
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
        label_1230_status=label_1230_status,
        manifests=(V0_MANIFEST, V1_CORE_MANIFEST, V2_EXTENDED_MANIFEST),
    )
    with pytest.raises(ValueError, match="feature values do not match featureset-v2-extended"):
        write_production_build_manifest(
            v0_snapshot,
            feature_snapshot,
            v2_snapshot,
            mismatched_snapshot,
            tmp_path / "content-mismatch-builds",
            created_at=datetime(2026, 8, 25, 0, 2, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="V0 manifest mismatch"):
        write_production_build_manifest(
            feature_snapshot,
            v0_snapshot,
            v2_snapshot,
            snapshot,
            tmp_path / "invalid-builds",
            created_at=datetime(2026, 8, 25, 0, 2, tzinfo=UTC),
        )
    experiment_registry = tmp_path / "advanced-experiments.jsonl"
    advanced_result = CliRunner().invoke(
        app,
        [
            "research",
            "advanced",
            "--build-manifest",
            str(build_manifest.manifest_path),
            "--code-commit",
            "goal3-cli-test",
            "--report-root",
            str(tmp_path / "advanced-reports"),
            "--experiment-registry",
            str(experiment_registry),
            "--horizons",
            "1",
            "--initial-train-periods",
            "20",
            "--validation-periods",
            "5",
            "--step-periods",
            "5",
            "--holdout-periods",
            "5",
            "--tuning-trials",
            "1",
            "--tuning-timeout-seconds",
            "10",
            "--estimator-count",
            "5",
            "--no-run-ablations",
            "--no-run-diagnostics",
        ],
    )
    assert advanced_result.exit_code == 0, advanced_result.output
    success_record = json.loads(experiment_registry.read_text(encoding="utf-8").splitlines()[0])
    assert success_record["decision"] == "research_only"
    assert success_record["locked_holdout_accessed"] is False
    assert success_record["parameters"]["build_id"] == build_manifest.build_id
    assert success_record["parameters"]["feature_snapshot_id"] == v2_snapshot.snapshot_id
    assert success_record["parameters"]["report_id"]
    assert success_record["parameters"]["config_json"]
    assert success_record["fold_results"][0]["model_family"] == "lightgbm"
    assert {item["task"] for item in success_record["fold_results"]} == {
        "large_loss",
        "quantile",
        "ranking",
        "regression",
    }
    assert success_record["fold_results"][0]["validation_start"]
    assert success_record["trial_results"][0]["state"] == "COMPLETE"

    failed_result = CliRunner().invoke(
        app,
        [
            "research",
            "advanced",
            "--build-manifest",
            str(build_manifest.manifest_path),
            "--code-commit",
            "UNSET",
            "--experiment-registry",
            str(experiment_registry),
            "--horizons",
            "1",
            "--initial-train-periods",
            "20",
            "--validation-periods",
            "5",
            "--step-periods",
            "5",
            "--holdout-periods",
            "5",
            "--tuning-trials",
            "1",
            "--tuning-timeout-seconds",
            "10",
            "--estimator-count",
            "5",
            "--no-run-ablations",
            "--no-run-diagnostics",
        ],
    )
    assert failed_result.exit_code == 2
    records = [
        json.loads(line) for line in experiment_registry.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["decision"] == "rejected"
    assert "advanced research code_commit must be explicit" in records[-1]["rejection_reason"]

    invalid_config_result = CliRunner().invoke(
        app,
        [
            "research",
            "advanced",
            "--build-manifest",
            str(build_manifest.manifest_path),
            "--code-commit",
            "",
            "--experiment-registry",
            str(experiment_registry),
            "--horizons",
            "",
        ],
    )
    assert invalid_config_result.exit_code == 2
    records = [
        json.loads(line) for line in experiment_registry.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["decision"] == "rejected"
    assert records[-1]["code_commit"] == "UNSET"
    assert records[-1]["parameters"]["raw_config_json"]

    def forced_tuning_failure(**_: object) -> np.ndarray:
        raise RuntimeError("forced CLI trial failure")

    monkeypatch.setattr(advanced_module, "_fit_predict", forced_tuning_failure)
    all_failed_result = CliRunner().invoke(
        app,
        [
            "research",
            "advanced",
            "--build-manifest",
            str(build_manifest.manifest_path),
            "--code-commit",
            "goal3-failed-trial-test",
            "--experiment-registry",
            str(experiment_registry),
            "--horizons",
            "1",
            "--initial-train-periods",
            "20",
            "--validation-periods",
            "5",
            "--step-periods",
            "5",
            "--holdout-periods",
            "5",
            "--tuning-trials",
            "1",
            "--tuning-timeout-seconds",
            "10",
            "--estimator-count",
            "5",
            "--no-run-ablations",
            "--no-run-diagnostics",
        ],
    )
    assert all_failed_result.exit_code == 2
    records = [
        json.loads(line) for line in experiment_registry.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["trial_results"][0]["state"] == "FAIL"
    assert "forced CLI trial failure" in records[-1]["trial_results"][0]["failure_reason"]
    assert records[-1]["parameters"]["build_id"] == build_manifest.build_id
    assert records[-1]["parameters"]["feature_snapshot_id"] == v2_snapshot.snapshot_id

    monkeypatch.undo()
    completed_report, completed_oof = stock_cli.load_advanced_research_run(
        Path(success_record["parameters"]["oof_path"])
    )
    completed_run = advanced_module.AdvancedResearchRun(
        report=completed_report,
        oof_predictions=completed_oof,
    )
    monkeypatch.setattr(
        stock_cli,
        "run_advanced_research",
        lambda *_args, **_kwargs: completed_run,
    )

    def forced_artifact_failure(*_: object, **__: object) -> tuple[Path, Path]:
        raise OSError("forced artifact publication failure")

    monkeypatch.setattr(stock_cli, "write_advanced_research_run", forced_artifact_failure)
    artifact_failure_result = CliRunner().invoke(
        app,
        [
            "research",
            "advanced",
            "--build-manifest",
            str(build_manifest.manifest_path),
            "--code-commit",
            "goal3-artifact-failure-test",
            "--experiment-registry",
            str(experiment_registry),
        ],
    )
    assert artifact_failure_result.exit_code == 2
    records = [
        json.loads(line) for line in experiment_registry.read_text(encoding="utf-8").splitlines()
    ]
    artifact_failure_record = records[-1]
    assert len(artifact_failure_record["trial_results"]) == len(success_record["trial_results"])
    assert len(artifact_failure_record["fold_results"]) == len(success_record["fold_results"])
    assert artifact_failure_record["parameters"]["build_id"] == build_manifest.build_id
    assert artifact_failure_record["parameters"]["feature_snapshot_id"] == v2_snapshot.snapshot_id
    assert artifact_failure_record["parameters"]["report_id"] == completed_report.report_id

    monkeypatch.undo()
    original_generate = advanced_module.generate_oof_predictions
    oof_call_count = 0

    def forced_post_tuning_failure(*args: object, **kwargs: object) -> pd.DataFrame:
        nonlocal oof_call_count
        oof_call_count += 1
        if oof_call_count == 3:
            raise RuntimeError("forced CLI post-tuning failure")
        return original_generate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(advanced_module, "generate_oof_predictions", forced_post_tuning_failure)
    partial_failure_result = CliRunner().invoke(
        app,
        [
            "research",
            "advanced",
            "--build-manifest",
            str(build_manifest.manifest_path),
            "--code-commit",
            "goal3-partial-failure-test",
            "--experiment-registry",
            str(experiment_registry),
            "--horizons",
            "1",
            "--initial-train-periods",
            "20",
            "--validation-periods",
            "5",
            "--step-periods",
            "5",
            "--holdout-periods",
            "5",
            "--tuning-trials",
            "1",
            "--tuning-timeout-seconds",
            "10",
            "--estimator-count",
            "5",
            "--no-run-ablations",
            "--no-run-diagnostics",
        ],
    )
    assert partial_failure_result.exit_code == 2
    records = [
        json.loads(line) for line in experiment_registry.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["trial_results"][0]["state"] == "COMPLETE"
    assert {item["task"] for item in records[-1]["fold_results"]} == {"regression"}
    assert records[-1]["parameters"]["build_id"] == build_manifest.build_id
    assert records[-1]["parameters"]["feature_snapshot_id"] == v2_snapshot.snapshot_id

    renamed = dataset.rename(columns={"market.breadth": "market.breadth.renamed"})
    renamed_snapshot = write_production_dataset_snapshot(
        renamed,
        tmp_path,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=datetime(2026, 8, 25, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 0, 1, tzinfo=UTC),
        label_1230_status=label_1230_status,
        manifests=(V0_MANIFEST, V1_CORE_MANIFEST, V2_EXTENDED_MANIFEST),
    )
    assert renamed_snapshot.snapshot_id != snapshot.snapshot_id

    with snapshot.parquet_path.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(RuntimeError, match="Parquet hash"):
        load_production_dataset_snapshot(snapshot.parquet_path)


def test_future_price_mutation_does_not_change_prior_production_features() -> None:
    frames, dates = _source_frames()
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames),
        source_snapshot_as_of=datetime(2026, 8, 24, tzinfo=UTC),
        minimum_market_coverage=0.60,
    )
    original_sets = build_production_feature_sets(bundle)
    changed_daily = bundle.daily.copy()
    final_date = changed_daily["trading_date"].max()
    changed_daily.loc[changed_daily["trading_date"] == final_date, "adjusted_close"] *= 10
    changed_sets = build_production_feature_sets(replace(bundle, daily=changed_daily))
    for attribute, manifest in (
        ("v0", V0_MANIFEST),
        ("v1_core", V1_CORE_MANIFEST),
        ("v2_extended", V2_EXTENDED_MANIFEST),
    ):
        original, changed = getattr(original_sets, attribute), getattr(changed_sets, attribute)
        assert original is not None and changed is not None
        prior_columns = ["symbol", "trading_date", *manifest.feature_names]
        original_prior = original.loc[
            original["trading_date"] < final_date, prior_columns
        ].reset_index(drop=True)
        changed_prior = changed.loc[
            changed["trading_date"] < final_date, prior_columns
        ].reset_index(drop=True)
        pdt.assert_frame_equal(original_prior, changed_prior, check_exact=True)
    assert dates[-1] > final_date


@pytest.mark.parametrize("missing_entry", [False, True])
def test_jpx_holiday_labels_keep_session_endpoints_when_a_price_is_missing(
    missing_entry: bool,
) -> None:
    # JPX 2026 equity holidays: https://www.jpx.co.jp/corporate/about-jpx/calendar/
    # This fixture exercises the Jan 9 -> Jan 13 boundary, not a weekday offset.
    frames, _ = _source_frames(periods=320)
    holidays = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-12", "2026-02-11"])
    calendar = frames[DatasetName.TRADING_CALENDAR]
    calendar.loc[calendar.trading_date.isin(holidays), "is_equity_business_day"] = False
    for name, date_column in (
        (DatasetName.SECURITY_MASTER, "effective_date"),
        (DatasetName.DAILY_PRICES, "trading_date"),
        (DatasetName.TOPIX, "trading_date"),
    ):
        frames[name] = frames[name].loc[~frames[name][date_column].isin(holidays)].copy()
    if missing_entry:
        prices = frames[DatasetName.DAILY_PRICES]
        frames[DatasetName.DAILY_PRICES] = prices.loc[
            ~((prices.symbol == "B") & (prices.trading_date == pd.Timestamp("2026-01-13")))
        ].copy()
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames),
        source_snapshot_as_of=datetime(2026, 8, 24, tzinfo=UTC),
        minimum_market_coverage=0.60,
    )
    features = build_production_feature_sets(bundle).v2_extended
    assert features is not None
    dataset, _ = build_production_supervised_dataset(
        features,
        bundle,
        plan=SubscriptionPlan.STANDARD,
    )
    row = dataset.loc[
        (dataset.symbol == "B") & (dataset.trading_date == pd.Timestamp("2026-01-09"))
    ].iloc[0]
    assert row.label_entry_date == pd.Timestamp("2026-01-13")
    assert row.label_end_date_1d == pd.Timestamp("2026-01-14")
    assert row.label_end_date_5d == pd.Timestamp("2026-01-20")
    assert row.label_end_date_20d == pd.Timestamp("2026-02-10")
    assert pd.Timestamp("2026-01-12") not in set(bundle.universe.effective_date)
    for horizon in (1, 5, 20):
        if missing_entry:
            assert row[f"label_status_{horizon}d"] == "SUSPENDED_NO_ENTRY_PRICE"
            assert pd.isna(row[f"target_return_{horizon}d"])
        else:
            assert row[f"label_status_{horizon}d"] == "AVAILABLE"
            endpoint = row[f"label_end_date_{horizon}d"]
            prices = bundle.daily.loc[bundle.daily.symbol == "B"].set_index("trading_date")
            expected = (
                prices.loc[endpoint, "adjusted_close"]
                / prices.loc[pd.Timestamp("2026-01-13"), "adjusted_close"]
                - 1
            )
            assert row[f"target_return_{horizon}d"] == pytest.approx(expected)


def test_production_momentum_and_ridge_walk_forward_keep_holdout_locked(
    tmp_path: Path,
) -> None:
    frames, _dates = _source_frames()
    source_as_of = datetime(2026, 8, 24, tzinfo=UTC)
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames),
        source_snapshot_as_of=source_as_of,
        minimum_market_coverage=0.60,
    )
    features = build_production_feature_sets(bundle).v1_core
    dataset, _status = build_production_supervised_dataset(
        features,
        bundle,
        plan=SubscriptionPlan.STANDARD,
    )
    report = run_production_walk_forward_baselines(
        dataset,
        data_snapshot_id="d" * 64,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        code_commit="test-commit",
        initial_train_periods=120,
        validation_periods=20,
        step_periods=20,
        holdout_periods=30,
    )
    assert [model.model_name for model in report.models] == ["CASH", "Momentum", "Ridge"]
    assert all(model.folds >= 1 for model in report.models)
    assert report.models[0].top_decile_mean_target == 0
    assert report.models[0].cost_scenarios == ((10, 0.0), (20, 0.0), (30, 0.0), (50, 0.0))
    assert report.locked_holdout_start
    assert not report.adoption_eligible
    assert report.historical_revision_status.value == "PARTIAL"
    path = write_production_baseline_report(report, tmp_path)
    assert write_production_baseline_report(report, tmp_path) == path
    assert path.is_file()

    mutated = dataset.copy()
    holdout_start = pd.Timestamp(report.locked_holdout_start)
    crossing = pd.to_datetime(mutated["label_end_date_5d"]) >= holdout_start
    mutated.loc[crossing, "target_return_5d"] = 999.0
    repeated_report = run_production_walk_forward_baselines(
        mutated,
        data_snapshot_id="d" * 64,
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
        code_commit="test-commit",
        initial_train_periods=120,
        validation_periods=20,
        step_periods=20,
        holdout_periods=30,
    )
    assert repeated_report.report_id == report.report_id
    assert repeated_report.models == report.models


def test_real_data_research_predictions_reach_decision_engine_without_order_path() -> None:
    frames, _dates = _source_frames()
    source_as_of = datetime(2026, 8, 24, tzinfo=UTC)
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames),
        source_snapshot_as_of=source_as_of,
        minimum_market_coverage=0.60,
    )
    feature_sets = build_production_feature_sets(bundle)
    dataset, _status = build_production_supervised_dataset(
        feature_sets.v1_core,
        bundle,
        plan=SubscriptionPlan.STANDARD,
    )
    report = run_production_walk_forward_baselines(
        dataset,
        data_snapshot_id="d" * 64,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        code_commit="test-commit",
        initial_train_periods=120,
        validation_periods=20,
        step_periods=20,
        holdout_periods=30,
    )
    latest_date = feature_sets.v1_core["trading_date"].max()
    latest = feature_sets.v1_core.loc[feature_sets.v1_core["trading_date"] == latest_date].copy()
    as_of = pd.Timestamp(latest["available_at"].max()).to_pydatetime()
    account = Account(account_id="research", broker="manual", display_name="Research")
    bucket = AccountBucket(
        bucket_id="research-taxable",
        account_id=account.account_id,
        account_type=AccountType.TAXABLE_SPECIFIED,
        withholding_mode=WithholdingMode.WITHHOLDING,
        fee_policy_id="research-cost-v1",
        tax_policy_id="research-tax-v1",
    )
    portfolio = PortfolioState(
        portfolio_id="research-cash",
        as_of=as_of,
        accounts=(account,),
        account_buckets=(bucket,),
        positions=(),
        cash=(CashState(account_bucket_id=bucket.bucket_id, available_cash=Decimal("1000000")),),
        tax_states=(TaxState(account_bucket_id=bucket.bucket_id, tax_year=as_of.year),),
    )
    engine = DailyPortfolioDecisionEngine(
        config=DecisionEngineConfig(
            maximum_positions=2,
            maximum_symbol_weight=Decimal("0.5"),
            maximum_sector_weight=Decimal("1"),
            minimum_cash_ratio=Decimal("0"),
            minimum_improvement_yen=Decimal("0"),
        ),
        cost_engine=TransactionCostEngine(
            CostPolicy(
                policy_id="research-cost-v1",
                version="research-cost-v1",
                zero_commission_confirmed=True,
                full_spread_bps=Decimal("10"),
                slippage_bps=Decimal("5"),
                impact_bps_at_full_adv=Decimal("10"),
            )
        ),
        tax_engine=SimpleJapanTaxEngine(
            TaxPolicy(
                policy_id="research-tax-v1",
                version="research-tax-v1",
                effective_from=as_of.date().replace(month=1, day=1),
            )
        ),
    )
    result = run_research_decision_e2e(
        dataset=dataset,
        latest_features=latest,
        universe=bundle.universe,
        data_snapshot_id="d" * 64,
        baseline_report=report,
        portfolio=portfolio,
        engine=engine,
        candidate_limit=2,
    )
    assert result.candidate_count == 2
    assert len(result.predictions) == 2
    assert result.proposal.current_portfolio_id == portfolio.portfolio_id
    assert result.proposal.model_bundle_version.startswith("ridge-real-v1-")
    assert "BLOCKED_BY_DATA_CAPABILITY" in result.reference_price_rule

    mutated = dataset.copy()
    holdout_start = pd.Timestamp(report.locked_holdout_start)
    for horizon in (1, 5, 20):
        crossing = pd.to_datetime(mutated[f"label_end_date_{horizon}d"]) >= holdout_start
        mutated.loc[crossing, f"target_return_{horizon}d"] = 999.0
    repeated = run_research_decision_e2e(
        dataset=mutated,
        latest_features=latest,
        universe=bundle.universe,
        data_snapshot_id="d" * 64,
        baseline_report=report,
        portfolio=portfolio,
        engine=engine,
        candidate_limit=2,
    )
    assert repeated.predictions == result.predictions
    mismatched = report.model_copy(update={"data_snapshot_id": "e" * 64})
    with pytest.raises(ValueError, match="dataset snapshot"):
        run_research_decision_e2e(
            dataset=dataset,
            latest_features=latest,
            universe=bundle.universe,
            data_snapshot_id="d" * 64,
            baseline_report=mismatched,
            portfolio=portfolio,
            engine=engine,
            candidate_limit=2,
        )


def test_revision_policy_and_missing_share_components_fail_closed() -> None:
    frames, _dates = _source_frames()
    source_as_of = datetime(2026, 8, 24, tzinfo=UTC)
    future_frames = {key: value.copy() for key, value in frames.items()}
    future_frames[DatasetName.DAILY_PRICES].loc[0, "available_at"] = pd.Timestamp(
        "2026-08-25T00:00:00Z"
    )
    with pytest.raises(ValueError, match="after source_snapshot_as_of"):
        build_production_data(  # type: ignore[arg-type]
            FrameCatalog(future_frames),
            source_snapshot_as_of=source_as_of,
            minimum_market_coverage=0.60,
        )

    missing_component = {key: value.copy() for key, value in frames.items()}
    missing_component[DatasetName.FINANCIAL_SUMMARY].loc[
        missing_component[DatasetName.FINANCIAL_SUMMARY]["symbol"] == "B",
        "treasury_shares_fy",
    ] = np.nan
    component_bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(missing_component),
        source_snapshot_as_of=source_as_of,
        minimum_market_coverage=0.60,
    )
    b_daily = component_bundle.daily.loc[component_bundle.daily["symbol"] == "B"]
    assert b_daily["shares_outstanding"].isna().all()
    assert set(b_daily["shares_outstanding_missing_reason"].dropna()) == {
        "fiscal treasury shares is missing"
    }

    strict_frames = {key: value.copy() for key, value in frames.items()}
    for dataset, frame in strict_frames.items():
        if dataset is not DatasetName.SECURITY_MASTER:
            frame["available_at"] = pd.Timestamp("2026-08-23T00:00:00Z")
    strict_bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(strict_frames),
        source_snapshot_as_of=source_as_of,
        minimum_market_coverage=0.60,
        revision_policy=HistoricalRevisionPolicy.STRICT_AS_KNOWN,
    )
    strict_features = build_production_feature_sets(strict_bundle).v1_core
    assert (
        pd.to_datetime(strict_features["source_revision_available_at"], utc=True)
        <= pd.to_datetime(strict_features["available_at"], utc=True)
    ).all()
    strict_dataset, _ = build_production_supervised_dataset(
        strict_features,
        strict_bundle,
        plan=SubscriptionPlan.STANDARD,
    )
    assert strict_dataset["target_return_5d"].isna().all()
    assert set(strict_dataset["label_status_5d"]) == {"BLOCKED_BY_REVISION_HISTORY"}


def test_feature_lineage_accepts_an_entirely_missing_revision_source() -> None:
    frames, _dates = _source_frames()
    source_as_of = datetime(2026, 8, 24, tzinfo=UTC)
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames),
        source_snapshot_as_of=source_as_of,
        minimum_market_coverage=0.60,
    )
    financials = bundle.financials.copy()
    financials["financial_revision_available_at"] = np.nan

    features = build_production_feature_sets(replace(bundle, financials=financials)).v1_core

    assert str(features["source_revision_available_at"].dtype) == "datetime64[ns, UTC]"
    assert features["source_revision_available_at"].notna().all()


def test_premium_1230_labels_are_partial_and_snapshot_maturity_is_enforced(
    tmp_path: Path,
) -> None:
    frames, dates = _source_frames()
    price_frame = frames[DatasetName.DAILY_PRICES].copy()
    price_frame["research_afternoon_open"] = price_frame["research_close"] * 1.001
    price_frame.loc[price_frame.index[0], "research_afternoon_open"] = np.nan
    frames[DatasetName.DAILY_PRICES] = price_frame
    source_as_of = datetime(2026, 8, 24, tzinfo=UTC)
    bundle = build_production_data(  # type: ignore[arg-type]
        FrameCatalog(frames),
        source_snapshot_as_of=source_as_of,
        minimum_market_coverage=0.60,
    )
    features = build_production_feature_sets(bundle).v1_core
    dataset, status = build_production_supervised_dataset(
        features,
        bundle,
        plan=SubscriptionPlan.PREMIUM,
    )
    assert status.value == "PARTIAL"
    assert "label_1230_available_at_5d" in dataset
    cutoff_row = dataset.loc[
        (dataset["symbol"] == "B") & (dataset["trading_date"] == dates[99])
    ].iloc[0]
    cutoff = pd.Timestamp(cutoff_row["as_of"]).to_pydatetime()
    assert cutoff_row["label_1230_available_at_5d"] > pd.Timestamp(cutoff)
    snapshot = write_production_dataset_snapshot(
        dataset,
        tmp_path,
        source_snapshot_as_of=source_as_of,
        source_snapshot_ids=bundle.source_snapshot_ids,
        as_of=cutoff,
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
        label_1230_status=status,
    )
    persisted = pd.read_parquet(snapshot.parquet_path)
    stored = persisted.loc[
        (persisted["symbol"] == "B") & (persisted["trading_date"] == dates[99])
    ].iloc[0]
    assert pd.isna(stored["target_1230_return_5d"])
    assert stored["label_1230_status_5d"] == "HORIZON_NOT_MATURE"


def test_production_build_orchestration_publishes_one_verifiable_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames, _dates = _source_frames()
    monkeypatch.setattr(
        stock_cli,
        "DuckDBCatalog",
        lambda _path: ContextFrameCatalog(frames),
    )
    source_as_of = datetime(2026, 8, 24, tzinfo=UTC)
    artifacts = stock_cli._build_production_artifacts(
        data_root=tmp_path,
        catalog_path=tmp_path / "unused.duckdb",
        source_snapshot_as_of=source_as_of,
        plan=SubscriptionPlan.STANDARD,
        minimum_market_coverage=0.60,
        revision_policy=HistoricalRevisionPolicy.SINGLE_VINTAGE_AS_REVISED,
    )
    assert artifacts.snapshot.source_snapshot_ids == artifacts.bundle.source_snapshot_ids
    assert len(tuple(tmp_path.glob("builds/production/*/*.json"))) == 1

    verified = CliRunner().invoke(app, ["data", "verify", "--data-root", str(tmp_path)])
    assert verified.exit_code == 0
    assert "feature_snapshots=3 dataset_snapshots=1 builds=1 status=OK" in verified.stdout


def _source_frames(periods: int = 280) -> tuple[dict[DatasetName, pd.DataFrame], pd.DatetimeIndex]:
    dates = pd.bdate_range("2025-01-06", periods=periods)
    revision_at = pd.Timestamp("2026-08-24T00:00:00Z")
    master_rows: list[dict[str, object]] = []
    price_rows: list[dict[str, object]] = []
    topix_rows: list[dict[str, object]] = []
    for position, day in enumerate(dates):
        symbols = ("B", "C") if position >= len(dates) - 10 else ("A", "B", "C")
        for symbol in symbols:
            sector = "10" if symbol in ("A", "B") else "20"
            master_rows.append(
                {
                    "effective_date": day,
                    "provider_code": f"{symbol}0000",
                    "symbol": symbol,
                    "company_name": f"Company {symbol}",
                    "sector_33_code": sector,
                    "sector_33_name": f"Sector {sector}",
                    "market_code": "0111",
                    "market_name": "Prime",
                    "available_at": revision_at,
                }
            )
            if symbol == "C" and position == 200:
                continue
            base = 1000 + position * (1 + ord(symbol) - ord("A"))
            adjustment = 0.5 if symbol == "A" and position == 100 else 1.0
            raw_close = base * 2 if adjustment == 0.5 else base
            price_rows.append(
                {
                    "trading_date": day,
                    "provider_code": f"{symbol}0000",
                    "symbol": symbol,
                    "raw_close": raw_close,
                    "trading_value": base * 100_000,
                    "adjustment_factor": adjustment,
                    "research_open": base * 0.995,
                    "research_high": base * 1.01,
                    "research_low": base * 0.99,
                    "research_close": float(base),
                    "research_volume": 100_000.0,
                    "research_afternoon_open": np.nan,
                    "adjustment_version": "adjustment-v1",
                    "available_at": revision_at,
                }
            )
        topix = 2500 + position * 2
        topix_rows.append(
            {
                "trading_date": day,
                "open": topix - 1,
                "high": topix + 3,
                "low": topix - 3,
                "close": float(topix),
                "available_at": revision_at,
            }
        )

    financial_rows = []
    for symbol in ("A", "B", "C"):
        announcement_day = dates[1] if symbol == "B" else dates[0]
        announcement_hour = 15 if symbol == "B" else 9
        financial_rows.append(
            {
                "symbol": symbol,
                "disclosure_number": f"disc-{symbol}",
                "announced_at": pd.Timestamp(
                    datetime.combine(
                        announcement_day.date(),
                        datetime.min.time().replace(hour=announcement_hour),
                        JST,
                    )
                ).tz_convert("UTC"),
                "period_type": "FY",
                "period_end": pd.Timestamp("2024-12-31"),
                "sales": 1_000_000.0,
                "operating_profit": 100_000.0,
                "eps": 100.0,
                "equity": 5_000_000.0,
                "shares_outstanding_fy": 100_000.0,
                "treasury_shares_fy": 0.0,
                "forecast_eps": 110.0,
                "bps": 50.0,
                "provider_roe": 0.10,
                "available_at": revision_at,
            }
        )
    calendar = pd.DataFrame(
        {
            "trading_date": dates,
            "is_equity_business_day": True,
            "available_at": revision_at,
        }
    )
    frames = {
        DatasetName.SECURITY_MASTER: pd.DataFrame(master_rows),
        DatasetName.DAILY_PRICES: pd.DataFrame(price_rows),
        DatasetName.TRADING_CALENDAR: calendar,
        DatasetName.TOPIX: pd.DataFrame(topix_rows),
        DatasetName.FINANCIAL_SUMMARY: pd.DataFrame(financial_rows),
    }
    frames[DatasetName.FINANCIAL_SUMMARY]["announced_at"] = frames[DatasetName.FINANCIAL_SUMMARY][
        "announced_at"
    ].astype("datetime64[us, UTC]")
    return frames, dates
@pytest.mark.parametrize("duplicate_index", [False, True])
@pytest.mark.parametrize("missing_keys", [False, True])
def test_source_frame_identity_keeps_the_original_hash_across_chunk_boundaries(
    duplicate_index, missing_keys,
):
    rows = 20037
    frame = pd.DataFrame({
        "trading_date": [pd.Timestamp("2025-01-02") + timedelta(days=i // 5000)
                         for i in range(rows)],
        "provider_code": [f"{i % 5000:04d}0" for i in range(rows)],
        "source_record_hash": [hashlib.sha256(str(i).encode()).hexdigest() for i in range(rows)],
        "label": ["合成/😀", None, "0123"] * (rows // 3),
        "number": pd.Series([None, -0.0, 1.23e17] * (rows // 3), dtype="Float64"),
        "flag": pd.Series([True, None, False] * (rows // 3), dtype="boolean"),
        "category": pd.Categorical(["A", "B", None] * (rows // 3), categories=["A", "B", "unused"]),
        "available_at": pd.date_range("2026-01-01", periods=rows, freq="1234567ns", tz="UTC"),
    }).sample(frac=1, random_state=17)
    if duplicate_index:
        frame.index = [7] * len(frame)
    if missing_keys:
        frame.iloc[::13, frame.columns.get_loc("provider_code")] = None
        frame.iloc[::17, frame.columns.get_loc("trading_date")] = pd.NaT
    for original in (frame, frame.iloc[:0]):
        canonical = original.sort_values(["trading_date", "provider_code"]).reset_index(drop=True)
        schema = tuple((str(column), str(dtype)) for column, dtype in canonical.dtypes.items())
        metadata = json.dumps(
            {"dataset": "daily_prices", "schema": schema}, sort_keys=True
        ).encode()
        # Frozen v1 identity definition, computed in one allocation as before.
        row_bytes = pd.util.hash_pandas_object(canonical, index=False).to_numpy().tobytes()
        expected = hashlib.sha256(metadata + row_bytes).hexdigest()
        assert production_module._source_frame_id(DatasetName.DAILY_PRICES, original) == expected


@pytest.mark.parametrize("empty", [False, True])
def test_source_identity_keeps_v1_with_32_bit_nullable_missing_hashes(empty, monkeypatch):
    frame = pd.DataFrame({
        "trading_date": pd.to_datetime(["2025-01-06"] * 3),
        "provider_code": ["00010", "00020", "00030"],
        "nullable_int": pd.Series([1, None, -2], dtype="Int64"),
        "nullable_float": pd.Series([None, -0.0, 1.25], dtype="Float64"),
        "nullable_bool": pd.Series([True, None, False], dtype="boolean"),
        "text": pd.Series(["合成/😀", None, "0123"], dtype="string"),
        "float": [np.nan, 1.0, -0.0],
    })
    if empty:
        frame = frame.iloc[:0]
    before = frame.copy(deep=True)
    expected = production_module._source_frame_id(DatasetName.DAILY_PRICES, frame)
    original_hash = pd.util.hash_pandas_object
    masked_types = (pd.arrays.IntegerArray, pd.arrays.FloatingArray, pd.arrays.BooleanArray)

    def wasm_hash(value, *args, **kwargs):
        result = original_hash(value, *args, **kwargs)
        if isinstance(value, pd.Series) and isinstance(value.array, masked_types):
            result = result.copy()
            result.loc[value.isna()] = np.uint64(2147483647)
        return result

    monkeypatch.setattr(production_module, "hash", lambda _: 2147483647, raising=False)
    monkeypatch.setattr(pd.util, "hash_pandas_object", wasm_hash)
    assert production_module._source_frame_id(DatasetName.DAILY_PRICES, frame) == expected
    pdt.assert_frame_equal(frame, before, check_exact=True)
