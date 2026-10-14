from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.data.contracts import CapabilityStatus
from stock_ai.domain import MarketSnapshot, Position, Security
from stock_ai.features import V0_MANIFEST, V2_EXTENDED_MANIFEST
from stock_ai.ml.advanced import AdvancedResearchConfig
from stock_ai.ml.daily_oof import (
    DailyOofAdapter,
    DailyOofDay,
    compact_oof,
    load_daily_oof_adapter,
    propose_daily_oof,
    write_daily_oof_day,
)
from tests.conftest import decision_engine, portfolio
from tests.test_research_selection import _run_fixture


@pytest.fixture
def authenticated_pair(tmp_path: Path, monkeypatch):
    """Write authentic fixture bundles; never bypass production authentication."""
    import stock_ai.ml.advanced as advanced
    import stock_ai.ml.production as production
    import tests.test_research_selection as fixtures
    from stock_ai.ml.selection import (
        freeze_development_features,
        write_development_feature_selection,
    )

    original_oof = fixtures._oof_fixture

    def next_day_oof(**kwargs):
        frame = original_oof(**kwargs)
        frame["as_of"] += pd.Timedelta(days=1)
        return frame

    monkeypatch.setattr(fixtures, "_oof_fixture", next_day_oof)
    raw = next_day_oof(horizon=20, family="lightgbm", seed=17)
    frame = raw.loc[raw.task == "regression", ["symbol", "trading_date", "as_of"]].copy()
    # A protected row is part of the authenticated snapshot, never the adapter projection.
    protected = frame.iloc[:1].copy()
    protected["symbol"] = "PROTECTED"
    protected["trading_date"] = pd.Timestamp("2026-08-05")
    protected["as_of"] = pd.Timestamp("2026-08-06 11:30", tz="Asia/Tokyo")
    frame = pd.concat([frame, protected], ignore_index=True)
    frame["historical_revision_policy"] = "SINGLE_VINTAGE_AS_REVISED"
    frame["historical_revision_status"] = "PARTIAL"
    frame["unused_authentication_value"] = 1.0
    for horizon in (1, 5, 20):
        for family in ("return", "topix_excess", "sector_excess", "beta_residual"):
            frame[f"target_{family}_{horizon}d"] = 0.1
            suffix = "" if family == "return" else f"_{family}"
            frame[f"label_status{suffix}_{horizon}d"] = "AVAILABLE"
        frame[f"target_large_loss_{horizon}d"] = 0.0
        end = frame.trading_date + pd.Timedelta(days=horizon + 1)
        frame[f"label_end_date_{horizon}d"] = end
        frame[f"label_available_at_{horizon}d"] = end.dt.tz_localize("Asia/Tokyo").map(
            lambda value: value.to_pydatetime().replace(hour=16)
        )
    instant = datetime(2026, 9, 1, tzinfo=UTC)
    snapshot = production.write_production_dataset_snapshot(
        frame,
        tmp_path / "datasets",
        source_snapshot_as_of=instant,
        source_snapshot_ids=(("fixture", "source"),),
        as_of=instant,
        created_at=instant,
        label_1230_status=CapabilityStatus.BLOCKED_BY_DATA_CAPABILITY,
        manifests=(V2_EXTENDED_MANIFEST,),
    )
    original_run = fixtures._run_fixture

    def dataset_run(**kwargs):
        run = original_run(**kwargs)
        report = run.report.model_copy(update={"data_snapshot_id": snapshot.snapshot_id})
        report = report.model_copy(
            update={"report_id": advanced._stable_hash(advanced._report_identity(report))}
        )
        return advanced.AdvancedResearchRun(report=report, oof_predictions=run.oof_predictions)

    original_marker = fixtures._build_marker

    def dataset_marker(path):
        _, old_path = original_marker(path)
        payload = json.loads(old_path.read_text(encoding="utf-8"))
        payload["dataset_snapshot_id"] = snapshot.snapshot_id
        identity = {
            k: v
            for k, v in payload.items()
            if k.endswith("snapshot_id") or k in ("source_snapshot_ids", "source_snapshot_as_of")
        }
        build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        new_path = (path / "builds" / build_id / f"{build_id}.json").resolve()
        new_path.parent.mkdir(parents=True)
        payload.update(build_id=build_id, manifest_path=str(new_path))
        payload["metadata_hash"] = production._metadata_hash(payload)
        new_path.write_text(json.dumps(payload), encoding="utf-8")
        return build_id, new_path

    monkeypatch.setattr(fixtures, "_run_fixture", dataset_run)
    monkeypatch.setattr(fixtures, "_build_marker", dataset_marker)
    ablation, candidate = fixtures._campaign_fixtures(tmp_path)
    features = freeze_development_features(ablation_campaign_paths=(ablation,))
    feature_path = write_development_feature_selection(features, tmp_path / "features")
    return dict(
        feature_selection_path=feature_path,
        campaign_paths=(candidate,),
        dataset_path=snapshot.parquet_path,
        family="lightgbm",
        seed=17,
    )


def test_authenticated_loader_projects_development_and_rejects_rehashed_tampering(
    authenticated_pair,
) -> None:
    import stock_ai.ml.production as production

    data = load_daily_oof_adapter(**authenticated_pair)
    assert set(data.frame.symbol) == {"A", "B", "C"}
    assert data.frame.trading_date.max() < pd.Timestamp("2026-08-01")
    day = data.at(data.frame.as_of.iloc[-1].to_pydatetime())
    assert len(day.predictions) == 3 and not day.blocked
    assert day.calibration_dates >= 20
    for changes, reason in (
        ({"campaign_paths": ()}, "both"),
        ({"family": "absent"}, "both"),
        ({"campaign_paths": authenticated_pair["campaign_paths"] * 2}, "duplicated"),
    ):
        with pytest.raises(ValueError, match=reason):
            load_daily_oof_adapter(**{**authenticated_pair, **changes})
    path = authenticated_pair["dataset_path"]
    altered = pd.read_parquet(path)
    altered.loc[altered.symbol == "PROTECTED", "unused_authentication_value"] = 2.0
    altered.to_parquet(path, index=False)
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["parquet_sha256"] = production._file_sha256(path)
    metadata["metadata_hash"] = production._metadata_hash(metadata)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(RuntimeError, match="content identity"):
        load_daily_oof_adapter(**authenticated_pair)


def inputs():
    reports = tuple(
        _run_fixture(
            config=AdvancedResearchConfig(horizons=(h,), model_families=("lightgbm",), seeds=(17,)),
            feature_names=V0_MANIFEST.feature_names,
            run_ablations=False,
            code_commit="fixture",
        ).report
        for h in (5, 20)
    )
    dates = pd.bdate_range("2026-01-05", periods=70)
    rows = []
    for index in range(40):
        for symbol, residual, expected in (("A", 0.01, 0.10), ("B", 0.03, -0.10)):
            rows.append(
                dict(
                    symbol=symbol,
                    trading_date=dates[index],
                    as_of=dates[index + 1]
                    .tz_localize("Asia/Tokyo")
                    .to_pydatetime()
                    .replace(hour=11, minute=30),
                    expected_return_20d=expected,
                    quantile=-0.02,
                    large_loss=0.1,
                    target=expected + residual,
                    label_end=dates[index + 21],
                )
            )
    twenty = pd.DataFrame(rows)
    five = twenty[["symbol", "trading_date", "as_of"]].copy()
    five["expected_return_5d"] = [-99 if symbol == "A" else 99 for symbol in five.symbol]
    availability = twenty[["symbol", "trading_date", "as_of", "label_end"]].copy()
    availability["label_available_at"] = availability.label_end.dt.tz_localize("Asia/Tokyo").map(
        lambda value: value.to_pydatetime().replace(hour=16)
    )
    return five, twenty, availability, reports


def adapter(*, minimum=3):
    five, twenty, availability, reports = inputs()
    return DailyOofAdapter(
        five, twenty, availability, reports=reports, minimum_calibration_dates=minimum
    )


def test_daily_pair_uses_only_received_mature_outcomes_and_no_one_day_imputation() -> None:
    data = adapter()
    timestamp = data.frame.as_of.unique()[25].to_pydatetime()
    result = data.at(timestamp)
    assert len(result.predictions) == 2 and not result.blocked
    assert result.calibration_dates == 5 and result.calibration_rows == 10
    assert result.residual_rmse == pytest.approx(math.sqrt((0.01**2 + 0.03**2) / 2))
    assert result.latest_calibration_available_at < timestamp
    assert all(p.schema_version == 2 and p.expected_return_1d is None for p in result.predictions)
    assert all(p.risk_horizon == 20 for p in result.predictions)
    assert result.predictions[0].expected_return_5d == -99
    assert result.predictions[0].expected_return_20d == 0.1
    assert result.research_only and not result.adoption_eligible


def test_receipt_equality_delay_and_future_outcomes_do_not_leak() -> None:
    five, twenty, availability, reports = inputs()
    timestamp = twenty.as_of.unique()[25].to_pydatetime()
    availability.loc[0, "label_available_at"] = timestamp  # Exact cutoff is not earlier.
    first = DailyOofAdapter(
        five, twenty, availability, reports=reports, minimum_calibration_dates=3
    ).at(timestamp)
    assert first.calibration_rows == 9
    changed = twenty.copy()
    future = (availability.label_available_at >= timestamp) | (
        twenty.label_end >= pd.Timestamp(timestamp).tz_localize(None).normalize()
    )
    changed.loc[future, "target"] += 1000
    second = DailyOofAdapter(
        five, changed, availability, reports=reports, minimum_calibration_dates=3
    ).at(timestamp)
    assert first == second
    # Unit differences in Arrow/duckdb timestamp storage must not admit future labels.
    availability["label_available_at"] = availability.label_available_at.astype(
        "datetime64[us, Asia/Tokyo]"
    )
    assert first == DailyOofAdapter(
        five, twenty, availability, reports=reports, minimum_calibration_dates=3
    ).at(timestamp)


def test_current_day_endpoint_is_not_used_even_with_early_receipt_declaration() -> None:
    five, twenty, availability, reports = inputs()
    timestamp = twenty.as_of.unique()[25].to_pydatetime()
    current_end = twenty.label_end == pd.Timestamp(timestamp).tz_localize(None).normalize()
    availability.loc[current_end, "label_available_at"] = timestamp - timedelta(hours=1)
    result = DailyOofAdapter(
        five, twenty, availability, reports=reports, minimum_calibration_dates=3
    ).at(timestamp)
    assert result.calibration_rows == 10


def test_cold_start_missing_horizon_and_absent_holding_are_visible() -> None:
    five, twenty, availability, reports = inputs()
    timestamp = twenty.as_of.unique()[25].to_pydatetime()
    five = five.loc[~((five.symbol == "A") & (five.as_of == timestamp))]
    data = DailyOofAdapter(five, twenty, availability, reports=reports, minimum_calibration_dates=3)
    result = data.at(timestamp, required_symbols=("A", "B", "HELD"))
    assert [p.symbol for p in result.predictions] == ["B"]
    assert {b.symbol for b in result.blocked} == {"A", "HELD"}
    assert "HORIZON" in next(b.reason for b in result.blocked if b.symbol == "A")
    cold = data.at(twenty.as_of.iloc[0].to_pydatetime())
    assert not cold.predictions and cold.calibration_rows == 0 and cold.residual_rmse is None
    assert len(cold.blocked) == 2
    high = DailyOofAdapter(
        five, twenty, availability, reports=reports, minimum_calibration_dates=6
    ).at(timestamp)
    assert not high.predictions and high.calibration_dates == 5


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "naive", "endpoint", "as_of", "early"]
)
def test_availability_source_mismatch_fails_closed(mutation: str) -> None:
    five, twenty, availability, reports = inputs()
    if mutation == "duplicate":
        availability = pd.concat([availability, availability.iloc[:1]])
    elif mutation == "missing":
        availability = availability.iloc[1:]
    elif mutation == "naive":
        availability["label_available_at"] = availability.label_available_at.dt.tz_localize(None)
    elif mutation == "endpoint":
        availability.loc[0, "label_end"] += pd.Timedelta(days=1)
    elif mutation == "as_of":
        availability.loc[0, "as_of"] += pd.Timedelta(minutes=1)
    else:
        availability.loc[0, "label_available_at"] = availability.as_of.iloc[0]
    with pytest.raises(ValueError):
        DailyOofAdapter(five, twenty, availability, reports=reports)


@pytest.mark.parametrize(
    "mutation", ["horizon", "duplicate", "nan", "probability", "holdout", "naive", "empty"]
)
def test_bad_forecasts_do_not_become_usable(mutation: str) -> None:
    five, twenty, availability, reports = inputs()
    if mutation == "horizon":
        five.loc[0, "as_of"] += pd.Timedelta(minutes=1)
    elif mutation == "duplicate":
        five = pd.concat([five, five.iloc[:1]])
    elif mutation == "nan":
        twenty.loc[0, "target"] = np.inf
    elif mutation == "probability":
        twenty.loc[0, "large_loss"] = 2
    elif mutation == "holdout":
        five.loc[0, "trading_date"] = pd.Timestamp("2026-08-01")
    elif mutation == "naive":
        five["as_of"] = five.as_of.dt.tz_localize(None)
    else:
        five = five.iloc[:0]
    with pytest.raises(ValueError):
        DailyOofAdapter(five, twenty, availability, reports=reports)


@pytest.mark.parametrize("minimum", [0, -1, True, 1.5])
def test_calibration_requirement_is_explicit(minimum) -> None:
    with pytest.raises(ValueError):
        adapter(minimum=minimum)


def test_holdout_requests_and_ambiguous_symbol_lists_are_rejected() -> None:
    data = adapter()
    with pytest.raises(ValueError, match="holdout"):
        data.at(pd.Timestamp("2026-08-01", tz="Asia/Tokyo").to_pydatetime())
    with pytest.raises(ValueError, match="aware"):
        data.at(pd.Timestamp("2026-02-10").to_pydatetime())
    with pytest.raises(ValueError, match="unique"):
        data.at(data.frame.as_of.iloc[-1].to_pydatetime(), required_symbols=("A", "A"))


def test_compact_raw_oof_uses_only_one_declared_absolute_return_candidate() -> None:
    run = _run_fixture(
        config=AdvancedResearchConfig(horizons=(20,), model_families=("lightgbm",), seeds=(17,)),
        feature_names=V0_MANIFEST.feature_names,
        run_ablations=False,
        code_commit="fixture",
    )
    frame = run.oof_predictions.copy()
    frame["as_of"] += pd.Timedelta(days=1)
    compact = compact_oof(frame, run.report)
    assert len(compact) == len(frame) // 4
    assert "ranking" not in compact and "expected_return_20d" in compact
    altered = frame.copy()
    altered.loc[altered.task == "quantile", "as_of"] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="timestamps"):
        compact_oof(altered, run.report)
    altered = frame.copy()
    altered["as_of"] -= pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="subsequent"):
        compact_oof(altered, run.report)


def test_day_receipt_preserves_all_blocks_and_predictions(tmp_path: Path) -> None:
    data = adapter()
    day = data.at(data.frame.as_of.iloc[-1].to_pydatetime(), required_symbols=("MISSING",))
    path = write_daily_oof_day(day, tmp_path)
    raw = path.read_bytes()
    assert hashlib.sha256(raw[:-1]).hexdigest() == path.stem
    assert json.loads(raw)["day"] == day.model_dump(mode="json")


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "zero_dates", "receipt", "missing_receipt", "scale", "history", "provenance"],
)
def test_saved_day_rejects_incoherent_history_and_provenance(mutation: str) -> None:
    data = adapter()
    day = data.at(data.frame.as_of.iloc[-1].to_pydatetime())
    values = day.model_dump()
    if mutation == "duplicate":
        values["predictions"] = (values["predictions"][0],) * 2
    elif mutation == "zero_dates":
        values["calibration_dates"] = 0
    elif mutation == "receipt":
        values["latest_calibration_available_at"] = day.as_of
    elif mutation == "missing_receipt":
        values["latest_calibration_available_at"] = None
    elif mutation == "scale":
        values["residual_rmse"] = None
    elif mutation == "history":
        values["minimum_calibration_dates"] = day.calibration_dates + 1
    else:
        values["model_version"] += "changed"
    with pytest.raises(ValueError):
        DailyOofDay.model_validate(values)


def test_daily_predictions_reach_hold_comparison_without_using_five_day_as_main_alpha() -> None:
    data = adapter()
    day = data.at(data.frame.as_of.iloc[-1].to_pydatetime())
    held = Position(
        symbol="B",
        account_bucket_id="bucket",
        shares=100,
        average_acquisition_price=Decimal(1000),
        market_price=Decimal(900),
    )
    current = portfolio((held,)).model_copy(update={"as_of": day.as_of})
    engine = decision_engine()
    engine.config = engine.config.model_copy(
        update={"horizon_weights": (Decimal(0), Decimal(0), Decimal(1))}
    )
    market = MarketSnapshot(
        snapshot_id="fixture-price",
        as_of=day.as_of,
        available_at=day.as_of - timedelta(hours=19),
        source="TEST_ONLY",
        prices={"A": Decimal(1000), "B": Decimal(1000)},
    )
    securities = {s: Security(symbol=s, company_name=s, sector="fixture") for s in ("A", "B")}
    result = propose_daily_oof(
        day,
        portfolio=current,
        candidate_symbols=("A",),
        securities=securities,
        market=market,
        average_daily_trading_values={"A": Decimal("100000000"), "B": Decimal("100000000")},
        engine=engine,
        generated_at=day.as_of + timedelta(minutes=1),
    )
    assert {line.symbol: line.action.value for line in result.lines} == {"A": "BUY", "B": "SELL"}
    assert result.net_improvement > 0
    assert current.positions[0].shares == 100 and current.positions[0].market_price == 900
    arguments = dict(
        portfolio=current,
        candidate_symbols=("A",),
        securities=securities,
        market=market,
        average_daily_trading_values={},
        engine=engine,
        generated_at=day.as_of,
    )
    for changes, reason in (
        (
            {"portfolio": current.model_copy(update={"as_of": day.as_of - timedelta(days=1)})},
            "same as_of",
        ),
        ({"generated_at": day.as_of - timedelta(seconds=1)}, "precede"),
        ({"generated_at": day.as_of.replace(tzinfo=None)}, "aware"),
        ({"engine": decision_engine()}, "20d"),
        ({"candidate_symbols": ("A", "A")}, "unique"),
        ({"candidate_symbols": ("ABSENT",)}, "candidate symbols"),
        ({"securities": {}}, "evidence"),
    ):
        with pytest.raises(ValueError, match=reason):
            propose_daily_oof(day, **{**arguments, **changes})
    missing_day = day.model_copy(update={"predictions": (day.predictions[0],)})
    with pytest.raises(ValueError, match="held symbols"):
        propose_daily_oof(
            missing_day,
            portfolio=current,
            candidate_symbols=("A",),
            securities=securities,
            market=market,
            average_daily_trading_values={},
            engine=engine,
            generated_at=day.as_of,
        )


def test_cli_writes_research_receipt_without_model_adoption(tmp_path: Path, monkeypatch) -> None:
    data = adapter()
    monkeypatch.setattr("stock_ai.ml.daily_oof.load_daily_oof_adapter", lambda **kwargs: data)
    path = tmp_path / "source.json"
    path.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "research",
            "daily-oof",
            "--feature-selection",
            str(path),
            "--candidate-campaign",
            str(path),
            "--dataset",
            str(path),
            "--family",
            "lightgbm",
            "--seed",
            "17",
            "--as-of",
            data.frame.as_of.iloc[-1].isoformat(),
            "--output-root",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["prediction_count"] == 2
    assert json.loads(result.output)["research_only"]
