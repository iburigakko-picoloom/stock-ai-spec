"""Synthetic funding receipts through the actual strict market/NAV entry point."""

import hashlib
import json
from datetime import date, datetime, timedelta

import pytest

from stock_ai.ml.daily_market import DailyMarketRequest
from stock_ai.ml.market_nav import MarketReceipt, MarketStrategyRequest, evaluate_market_strategy
from stock_ai.ml.research_funding import POLICY_VERSION, build_funding_schedule
from tests.test_market_nav import connected  # noqa: F401 -- shared synthetic market fixture


def save_receipt(path, value, start, end):
    path.write_text(json.dumps(value), encoding="utf-8")
    return MarketReceipt(
        path=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), start=start, end=end
    )


@pytest.fixture
def funded(connected, tmp_path):  # noqa: F811
    accounting = connected.strategy.accounting
    start, end = accounting.calendar_dates[0], accounting.calendar_dates[-1] + timedelta(days=14)
    required = set(accounting.calendar_dates)
    # This deliberately synthetic calendar accommodates the shared scenario's
    # decision dates; it is not an exchange holiday or historical data claim.
    calendar = tuple(
        (
            start + timedelta(days=i),
            int(start + timedelta(days=i) in required or (start + timedelta(days=i)).weekday() < 5),
        )
        for i in range((end - start).days + 1)
    )
    value = build_funding_schedule(calendar, start=start, end=end)
    source = DailyMarketRequest(
        catalog_path=tmp_path / "TEST_ONLY.duckdb",
        store_root=tmp_path / "TEST_ONLY",
        feature_selection_path=connected.feature_selection_path,
        start=start,
        end=end,
        source_snapshot_as_of=accounting.sessions[-1].close_at + timedelta(days=30),
    )
    value.update(
        request=source.model_dump(mode="json"),
        feature_selection_id="TEST",
        model_data_snapshot_id=connected.strategy.observations[0].forecasts.data_snapshot_id,
        locked_holdout_start="2026-08-01",
        holdout_rows_read=False,
    )
    by_date = {row["trading_date"]: row for row in value["rows"]}
    sessions = tuple(
        s.model_copy(
            update={
                "sale_cash_available_at": datetime.fromisoformat(
                    by_date[str(s.trading_date)]["sale_cash_available_at"]
                )
            }
        )
        for s in accounting.sessions
    )
    strategy = connected.strategy.model_copy(
        update={
            "accounting": accounting.model_copy(
                update={"calendar_id": value["calendar_id"], "sessions": sessions}
            )
        }
    )
    market_ref = connected.market_receipts[0]
    market = json.loads(market_ref.path.read_bytes())
    market["request"].update(
        {
            k: source.model_dump(mode="json")[k]
            for k in [
                "catalog_path",
                "store_root",
                "feature_selection_path",
                "source_snapshot_as_of",
            ]
        }
    )
    market_ref = save_receipt(market_ref.path, market, market_ref.start, market_ref.end)
    funding_ref = save_receipt(tmp_path / "funding.json", value, start, end)
    data = connected.model_dump()
    data.update(
        strategy=strategy, market_receipts=(market_ref,), research_funding_receipt=funding_ref
    )
    return MarketStrategyRequest.model_validate(data)


def changed_funding(request, mutate):
    ref = request.research_funding_receipt
    value = json.loads(ref.path.read_bytes())
    mutate(value)
    ref = save_receipt(ref.path, value, ref.start, ref.end)
    return request.model_copy(update={"research_funding_receipt": ref})


def test_market_replay_authenticates_pinned_funding_without_mutating_inputs(funded):
    before = funded.model_dump_json()
    result = evaluate_market_strategy(funded)
    assert result["status"] == "COMPLETE" and result["comparison"]["decisions_complete"]
    assert result["research_funding_policy"] == {
        "policy_version": POLICY_VERSION,
        "calendar_id": funded.strategy.accounting.calendar_id,
        "receipt_sha256": funded.research_funding_receipt.sha256,
        "research_assumption": True,
        "broker_verified": False,
    }
    assert funded.model_dump_json() == before
    assert not result["adoption_eligible"] and result["no_order_sent"]
    assert "ml/research_funding.py" in result["source_sha256"]


@pytest.mark.parametrize(
    "change",
    [
        {"feature_selection_id": "other"},
        {"model_data_snapshot_id": "other"},
        {"locked_holdout_start": "2099-01-01"},
        {"holdout_rows_read": True},
    ],
)
def test_rehashed_funding_cannot_change_model_or_final_identity(funded, change):
    with pytest.raises(ValueError, match=r"funding.*identity"):
        evaluate_market_strategy(changed_funding(funded, lambda value: value.update(change)))


def test_funding_file_tamper_and_rehashed_policy_changes_are_refused(funded):
    ref = funded.research_funding_receipt
    original = ref.path.read_bytes()
    ref.path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="evidence bytes changed"):
        evaluate_market_strategy(funded)
    ref.path.write_bytes(original)
    with pytest.raises(ValueError, match="frozen rule"):
        evaluate_market_strategy(
            changed_funding(funded, lambda value: value.update(broker_verified=True))
        )


def test_funding_window_checked_before_any_market_or_calendar_file_open(funded):
    funded.research_funding_receipt.path.unlink()
    funded.market_receipts[0].path.unlink()
    ref = funded.research_funding_receipt.model_copy(update={"end": date(2026, 8, 1)})
    with pytest.raises(ValueError, match=r"funding.*holdout"):
        evaluate_market_strategy(funded.model_copy(update={"research_funding_receipt": ref}))


def test_rehashed_declared_window_must_match_funding_contents(funded):
    ref = funded.research_funding_receipt
    ref = ref.model_copy(update={"start": ref.start + timedelta(days=1)})
    with pytest.raises(ValueError, match=r"funding.*window"):
        evaluate_market_strategy(funded.model_copy(update={"research_funding_receipt": ref}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("catalog_path", "OTHER.duckdb"),
        ("store_root", "OTHER"),
        ("source_snapshot_as_of", "2026-07-01T00:00:00+09:00"),
    ],
)
def test_funding_must_use_same_fixed_market_source_vintage(funded, field, value):
    ref = funded.market_receipts[0]
    market = json.loads(ref.path.read_bytes())
    market["request"][field] = value
    updated = save_receipt(ref.path, market, ref.start, ref.end)
    with pytest.raises(ValueError, match=r"funding.*vintage"):
        evaluate_market_strategy(funded.model_copy(update={"market_receipts": (updated,)}))


def test_funding_does_not_replace_corporate_actions_or_decision_execution_evidence(funded):
    value = evaluate_market_strategy(
        funded.model_copy(
            update={
                "action_coverage": (),
                "decision_evidence_sha256": None,
                "execution_evidence_sha256": None,
            }
        )
    )
    assert value["comparison"] is None and value["status"] == "BLOCKED"
    assert {
        "A:CORPORATE_ACTION_COVERAGE",
        "DECISION_POINT_IN_TIME_EVIDENCE",
        "EXECUTION_SETTLEMENT_EVIDENCE",
    } <= set(value["blockers"])


def test_market_entry_refuses_early_funding_and_unresolved_calendar_tail(funded):
    accounting = funded.strategy.accounting
    session = accounting.sessions[0].model_copy(
        update={
            "sale_cash_available_at": accounting.sessions[0].sale_cash_available_at
            - timedelta(seconds=1)
        }
    )
    changed = accounting.model_copy(update={"sessions": (session, *accounting.sessions[1:])})
    with pytest.raises(ValueError, match=r"funding.*unresolved or differs"):
        evaluate_market_strategy(
            funded.model_copy(
                update={"strategy": funded.strategy.model_copy(update={"accounting": changed})}
            )
        )
    value = json.loads(funded.research_funding_receipt.path.read_bytes())
    last = accounting.sessions[-1].trading_date
    calendar = [
        (date.fromisoformat(r["date"]), r["holiday_division"])
        for r in value["calendar_rows"]
        if date.fromisoformat(r["date"]) <= last
    ]
    shortened = build_funding_schedule(calendar, start=calendar[0][0], end=last)
    value.update(shortened)
    value["request"]["end"] = str(last)
    ref = save_receipt(funded.research_funding_receipt.path, value, calendar[0][0], last)
    with pytest.raises(ValueError, match="funding"):
        evaluate_market_strategy(
            funded.model_copy(
                update={
                    "research_funding_receipt": ref,
                    "strategy": funded.strategy.model_copy(
                        update={
                            "accounting": accounting.model_copy(
                                update={"calendar_id": shortened["calendar_id"]}
                            )
                        }
                    ),
                }
            )
        )


def test_original_explicit_funding_contract_remains_readable(connected):  # noqa: F811
    original = connected.model_dump()
    original.pop("research_funding_receipt")
    result = evaluate_market_strategy(MarketStrategyRequest.model_validate(original))
    assert result["status"] == "COMPLETE" and result["research_funding_policy"] is None
