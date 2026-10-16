from datetime import timedelta

import pytest
from mobile.python import decisions, personal, research

from stock_ai.operations.daily import PredictionSnapshot
from tests.test_mobile_decisions import NOW, cash_ready
from tests.test_mobile_decisions import ready as ready


def test_plan_uses_exact_current_publication_and_preserves_every_holding(ready):
    _, path, store, numerical, _ = ready
    shares = decisions.generate(path, store, NOW)
    assert shares["phase"] == "published"
    forecast = PredictionSnapshot.model_validate(numerical["snapshot"])
    before = store.prediction_snapshot(forecast.snapshot_id)
    plan = research.plan(path, store, NOW)
    assert plan == {"day": str(NOW.date()), "snapshot_id": forecast.snapshot_id,
                    "symbols": list(forecast.research_symbols())}
    assert "7203" in plan["symbols"]
    assert store.prediction_snapshot(forecast.snapshot_id) == before
    assert "accounts" not in plan and "predictions" not in plan


def test_plan_rejects_unpublished_old_day_and_changed_personal_inputs(ready):
    _, path, store, _, _ = ready
    with pytest.raises(ValueError, match="Current active"):
        research.plan(path, store, NOW)

    decisions.generate(path, store, NOW)
    with pytest.raises(ValueError, match="Current active"):
        research.plan(path, store, NOW + timedelta(days=1))
    saved = personal.portfolio_view(store)
    personal.save_portfolio(store, store.latest_manual_portfolio().portfolio,
                            saved["revision_id"], NOW)
    with pytest.raises(ValueError, match="Current active"):
        research.plan(path, store, NOW)

def test_cash_only_finishes_without_creating_research_or_forecasts(ready):
    _, path, store, ledger = cash_ready(ready)
    decisions.generate(path, store, NOW)
    assert research.plan(path, store, NOW) == {
        "day": str(NOW.date()), "snapshot_id": None, "symbols": [],
    }
    assert store.latest_portfolio() == ledger
    assert store.latest_prediction_snapshot() is None


def test_clock_before_original_publication_cannot_schedule_future_research(ready):
    _, path, store, _, _ = ready
    decisions.generate(path, store, NOW)
    with pytest.raises(ValueError, match="Current active"):
        research.plan(path, store, NOW - timedelta(minutes=1))
