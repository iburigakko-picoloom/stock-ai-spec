"""Synthetic consultation fixtures; no network or external AI calls."""

import copy
import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from mobile.python import market

from stock_ai.domain import Position
from stock_ai.domain.models import ResearchEnsemblePrediction
from stock_ai.operations.chatgpt_research import (
    accept_response,
    comparison_request,
    create_record,
    independent_request,
)
from stock_ai.operations.consultation import consultation_context
from stock_ai.operations.daily import PredictionSnapshot
from tests.conftest import portfolio
from tests.test_chatgpt_research import context_for, pass_for, response_for
from tests.test_daily_readiness import daily_snapshot
from tests.test_mobile_market import payload


def findings(symbols, now):
    return {
        "market_5d": "合成資料では判断保留",
        "market_20d": "合成資料では判断保留",
        "companies": [
            {
                "symbol": s,
                "independent_research": "合成IRの確認",
                "impact_5d": "不明",
                "impact_20d": "不明",
                "numerical_comparison": "数値は変更しない",
                "action": "HOLD",
                "rationale": "未確認のため維持",
            }
            for s in symbols
        ],
        "cash_rationale": "買付の根拠が不足しているため現金維持",
        "sources": [
            {
                "url": "https://example.com/fixture",
                "title": "合成資料",
                "published_at": None,
                "observed_at": now.isoformat(),
            }
        ],
        "unknowns": ["合成テストで実データではない"],
    }


def test_full_population_ranks_all_holdings_and_distinct_return_score_units():
    original = daily_snapshot()
    symbols = tuple(f"S{i:02d}" for i in range(60))
    predictions = tuple(
        ResearchEnsemblePrediction(
            symbol=s,
            as_of=original.as_of,
            model_version=original.model_version,
            feature_version=original.feature_version,
            data_snapshot_id=original.data_snapshot_id,
            expected_return_5d=i / 1000,
            expected_return_20d=i / 500,
            rank_score_20d=100 - i,
        )
        for i, s in enumerate(symbols)
    )
    snapshot = PredictionSnapshot.create(
        **{
            **original.model_dump(exclude={"snapshot_id", "predictions"}),
            "schema_version": "daily-prediction-snapshot-v2",
            "predictions": predictions,
            "candidate_symbols": symbols,
            "holding_symbols": symbols[25:],
            "large_loss_threshold": None,
            "downside_quantile_alpha": None,
            "risk_horizon": None,
        }
    )
    held = portfolio(
        tuple(
            Position(
                symbol=s,
                account_bucket_id="bucket",
                shares=100,
                average_acquisition_price=Decimal(100),
                market_price=Decimal(100),
            )
            for s in symbols[25:]
        )
    )
    before = snapshot.model_dump_json(), held.model_dump_json()
    result = consultation_context(snapshot, held, now=snapshot.generated_at)
    rows = {r["symbol"]: r for r in result["securities"]}
    assert set(rows) == set(snapshot.research_symbols()) and len(rows) == 55
    last = rows["S59"]
    assert last["5d"]["rank"] == 1 and last["20d"]["rank"] == 60
    assert last["5d"]["rank_basis"] == "expected_return"
    assert last["5d"]["rank_score"] is None
    assert last["20d"]["rank_score"] == 41
    assert last["20d"]["expected_return"] == 0.118
    assert all(last[h]["population_count"] == 60 for h in ("5d", "20d"))
    assert last["shares"] == 100 and last["market_value_yen"] == "10000"
    assert last["asset_weight"] == pytest.approx(10000 / 550000)
    assert result["cash_weight"] == pytest.approx(200000 / 550000)
    assert "account_bucket_id" not in json.dumps(result)
    assert before == (snapshot.model_dump_json(), held.model_dump_json())


def test_missing_forecast_for_new_holding_is_included_without_fabricated_rank():
    snapshot = daily_snapshot()
    held = portfolio(
        (
            Position(
                symbol="NEW",
                account_bucket_id="bucket",
                shares=100,
                average_acquisition_price=Decimal(1),
                market_price=Decimal(2),
            ),
        )
    )
    result = consultation_context(snapshot, held, now=snapshot.generated_at)
    row = next(r for r in result["securities"] if r["symbol"] == "NEW")
    assert row["forecast_missing"] and row["shares"] == 100
    assert row["5d"]["rank"] is None and row["20d"]["expected_return"] is None


def test_market_first_request_withholds_numbers_and_comparison_receives_full_context():
    snapshot = daily_snapshot()
    base = context_for(snapshot)
    shared = consultation_context(snapshot, portfolio(), now=base.research_as_of)
    context = base.model_copy(update={"consultation": shared})
    first = independent_request(context)
    projected = json.loads(first["input"][0]["content"])
    assert "expected_return" not in json.dumps(projected)
    assert "securities" not in projected and "rank_populations" not in projected
    assert set(projected["web_research_needed"]) == set(shared["market_topics"])
    independent = pass_for(snapshot, context)
    second = comparison_request(context, independent, snapshot)
    assert json.loads(second["input"][0]["content"])["consultation"] == shared
    assert independent.sources[0].observed_at == independent.completed_at


def test_mobile_market_reuses_verified_topix_and_sectors_with_cutoff_and_corrections(tmp_path):
    path = tmp_path / "market.sqlite"
    market.initialize(path)
    first = payload()
    market.ingest(path, first)
    second = copy.deepcopy(first)
    second["date"] = "2026-01-06"
    second["received_at"] = "2026-01-07T08:00:00+00:00"
    for rows in second["datasets"].values():
        for row in rows:
            row["Date"] = second["date"]
    second["datasets"]["daily_prices"][0].update(C=1.5, AdjC=1.5)
    second["datasets"]["topix"][0]["C"] = 1.5
    market.ingest(path, second)
    cutoff = datetime.fromisoformat(second["received_at"])
    facts = market.consultation_evidence(path, cutoff)
    assert {f["topic"] for f in facts} == {"topix", "sectors"}
    sectors = next(f for f in facts if f["topic"] == "sectors")
    assert sectors["values"]["sectors"][0]["mean_return"] == 0.5
    assert sectors["published_at"] is None and sectors["checked_at"] == cutoff.isoformat()
    assert all(f["source_records"] and f["source_url"].startswith("https://") for f in facts)
    corrected = copy.deepcopy(second)
    corrected["received_at"] = "2026-01-08T08:00:00+00:00"
    corrected["datasets"]["topix"][0]["C"] = 1.8
    market.ingest(path, corrected)
    assert market.consultation_evidence(path, cutoff) == facts
    assert market.consultation_evidence(path, cutoff - timedelta(days=3)) == []


def test_legacy_prompt_and_saved_research_keep_original_content_identity():
    # Golden identity compared with the pre-change implementation at 1cc04ba.
    snapshot = daily_snapshot()
    base = context_for(snapshot)
    context = base.model_copy(
        update={
            "company_name": "Fixture",
            "configuration": base.configuration.model_copy(
                update={"prompt_version": "independent-company-research-v1"}
            ),
        }
    )
    first = accept_response(
        context,
        "independent",
        response_for(),
        snapshot=snapshot,
        started_at=context.research_as_of,
        completed_at=context.research_as_of + timedelta(minutes=1),
    )
    second = accept_response(
        context,
        "comparison",
        response_for(search=False),
        snapshot=snapshot,
        independent=first,
        started_at=first.completed_at,
        completed_at=first.completed_at + timedelta(minutes=1),
    )
    record = create_record(context, first, second, snapshot)
    assert record.research_id == "b4c8f1e1fae9959d686746e61acf9832833fcb8c50918423e9c099a137e14b39"
    assert "consultation" not in context.model_dump(mode="json")
    assert "observed_at" not in first.sources[0].model_dump(mode="json")
