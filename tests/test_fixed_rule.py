from decimal import Decimal as D
from pathlib import Path

import pytest

from stock_ai.ml.fixed_rule import FixedRulePolicy, FixedSignalDay, evaluate_fixed_rule
from stock_ai.ml.nav import NavCash, evaluate_daily_nav, fixed_bps_policy
from tests.test_daily_nav import INITIAL, at, quote, request


def setup(days=6, **changes):
    accounting = request(
        prices=tuple((quote("A", "100"), quote("B", "100")) for _ in range(days)),
        cash=(NavCash(bucket="cash", amount=D(100000)),),
        cost_policy=fixed_bps_policy(D(20)),
    )
    signals = tuple(
        FixedSignalDay(
            as_of=at(i, 11),
            available_at=at(i, 10),
            reference_price_at=INITIAL if i == 0 else accounting.sessions[i - 1].close_at,
            horizon=5,
            score_unit="ranking_score",
            scores=(("A", 10 if i < 5 else 0), ("B", 0 if i < 5 else 10)),
            reference_prices=(("A", D(100)), ("B", D(100))),
            source_id="synthetic",
        )
        for i in range(days)
    )
    policy = FixedRulePolicy(horizon=5, initial_cash_yen=100000, top_n=1, **changes)
    return accounting, signals, policy


def test_fixed_allocation_uses_actual_capital_costs_and_only_horizon_rebalances():
    accounting, signals, policy = setup()
    realized, nav, decisions = evaluate_fixed_rule(accounting, signals, policy)
    assert len(decisions) == 2
    assert [o.trading_date for o in realized.orders] == [
        accounting.calendar_dates[0],
        accounting.calendar_dates[5],
    ]
    assert nav.days[0].positions[0].shares == 900
    assert nav.days[0].trading_cost == D(180)
    assert nav.days[0].nav == D(99820)
    assert not nav.days[-1].positions
    assert nav.days[-1].nav == D(99640)
    assert nav.total_trading_cost == D(360)
    assert evaluate_daily_nav(realized) == nav


def test_ranking_score_is_used_only_for_order_and_never_as_a_return():
    accounting, signals, policy = setup()
    _, expected, _ = evaluate_fixed_rule(accounting, signals, policy)
    transformed = tuple(
        s.model_copy(update={"scores": tuple((k, v * 1000 + 100) for k, v in s.scores)})
        for s in signals
    )
    _, observed, _ = evaluate_fixed_rule(accounting, transformed, policy)
    assert observed == expected


def test_unknown_fill_is_retained_instead_of_assuming_buy_success():
    accounting, signals, policy = setup(days=1)
    session = accounting.sessions[0].model_copy(
        update={
            "prices": (
                quote("A", "100", buy_status="unknown"),
                quote("B", "100"),
            )
        }
    )
    accounting = accounting.model_copy(update={"sessions": (session,)})
    _, result, _ = evaluate_fixed_rule(accounting, signals, policy)
    assert result.days[0].fills[0].filled_shares == 0
    assert not result.days[0].positions and result.total_trading_cost == 0


@pytest.mark.parametrize(
    "change",
    ["future", "same-execution", "missing-price", "nonfinite", "horizon", "capital", "cost"],
)
def test_fixed_rule_rejects_noncausal_incomplete_or_changed_policy(change):
    accounting, signals, policy = setup(days=1)
    if change == "future":
        signals = (signals[0].model_copy(update={"available_at": at(0, 12)}),)
    elif change == "same-execution":
        signals = (signals[0].model_copy(update={"as_of": at(0, 12)}),)
    elif change == "missing-price":
        signals = (signals[0].model_copy(update={"reference_prices": (("A", D(100)),)}),)
    elif change == "nonfinite":
        signals = (signals[0].model_copy(update={"scores": (("A", float("nan")), ("B", 0))}),)
    elif change == "horizon":
        policy = policy.model_copy(update={"horizon": 20})
    elif change == "capital":
        policy = policy.model_copy(update={"initial_cash_yen": D(1)})
    else:
        accounting = accounting.model_copy(update={"cost_policy": fixed_bps_policy(D(0))})
    with pytest.raises(ValueError):
        evaluate_fixed_rule(accounting, signals, policy)


def test_future_scores_do_not_change_past_nav():
    accounting, signals, policy = setup()
    _, expected, _ = evaluate_fixed_rule(accounting, signals, policy)
    changed = (*signals[:-1], signals[-1].model_copy(update={"scores": (("A", 100), ("B", -100))}))
    _, observed, _ = evaluate_fixed_rule(accounting, changed, policy)
    assert observed.days[:-1] == expected.days[:-1]
    assert observed.days[-1] != expected.days[-1]


def test_twenty_day_rule_does_not_reuse_five_day_schedule():
    accounting, signals, policy = setup()
    signals = tuple(s.model_copy(update={"horizon": 20}) for s in signals)
    _, _, decisions = evaluate_fixed_rule(
        accounting, signals, policy.model_copy(update={"horizon": 20})
    )
    assert len(decisions) == 1


def test_cli_saves_a_replayable_research_receipt_with_explicit_evidence_limits(tmp_path):
    import json

    from typer.testing import CliRunner

    from stock_ai.cli import app
    from stock_ai.ml.fixed_rule import FixedRuleRequest

    accounting, signals, policy = setup(days=1)
    parsed = FixedRuleRequest(accounting=accounting, signals=signals, policy=policy)
    source = tmp_path / "input.json"
    source.write_text(parsed.model_dump_json())
    result = CliRunner().invoke(
        app,
        [
            "research",
            "evaluate-fixed-rule",
            "--input",
            str(source),
            "--output-root",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    receipt = json.loads(Path(output["evaluation_path"]).read_text())
    assert receipt["evaluation_tier"] == "synthetic_accounting"
    assert receipt["market_evidence_certified"] is False and receipt["adoption_eligible"] is False
    assert D(receipt["cash"]["total_return"]) == 0
    assert D(receipt["strategy"]["total_trading_cost"]) == 180
