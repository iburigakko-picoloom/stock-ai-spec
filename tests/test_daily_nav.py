"""Independent, hand-calculated V18--V23 accounting examples; fixtures only."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D
from decimal import localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.ml.nav import (
    NavAction,
    NavCash,
    NavInput,
    NavOrder,
    NavPosition,
    NavPrice,
    NavSession,
    compare_with_hold,
    evaluate_daily_nav,
    fixed_bps_policy,
    load_nav_evaluation,
    write_nav_evaluation,
)

JST = ZoneInfo("Asia/Tokyo")
DATES = tuple(
    date(2026, 1, 5) + timedelta(days=i)
    for i in range(60)
    if (date(2026, 1, 5) + timedelta(days=i)).weekday() < 5
)
INITIAL = datetime(2026, 1, 2, 16, tzinfo=JST)


def at(index: int, hour: int = 12) -> datetime:
    return datetime.combine(DATES[index], datetime.min.time(), JST).replace(hour=hour)


def quote(symbol: str = "A", price: str | None = "100", **changes: object) -> NavPrice:
    data = dict(
        symbol=symbol,
        execution_price=price,
        close_price=price,
        buy_status="tradable",
        sell_status="tradable",
        capacity_shares=100_000,
        tick_size="1",
        source_id="test-only-raw-price",
    )
    return NavPrice.model_validate({**data, **changes})


def order(
    index: int,
    *,
    side: str = "BUY",
    shares: int = 100,
    symbol: str = "A",
    bucket: str = "cash",
    name: str | None = None,
) -> NavOrder:
    return NavOrder.model_validate(
        dict(
            order_id=name or f"{side}-{index}-{symbol}-{bucket}",
            trading_date=DATES[index],
            decided_at=at(index, 11),
            symbol=symbol,
            bucket=bucket,
            side=side,
            shares=shares,
        )
    )


def position(
    *, symbol: str = "A", bucket: str = "cash", shares: int = 100, price: str = "100"
) -> NavPosition:
    return NavPosition(
        symbol=symbol,
        bucket=bucket,
        shares=shares,
        unit_cost=D(price),
        last_price=D(price),
        last_price_at=INITIAL,
    )


def request(
    *, prices: tuple[tuple[NavPrice, ...], ...] = ((quote(),),), **changes: object
) -> NavInput:
    sessions = tuple(
        NavSession(
            trading_date=DATES[i],
            execution_at=at(i),
            close_at=at(i, 16),
            sale_cash_available_at=at(i),
            prices=values,
        )
        for i, values in enumerate(prices)
    )
    data = dict(
        data_mode="fixture",
        source_snapshot_id="synthetic-accounting-only",
        calendar_id="synthetic-weekday-calendar-not-JPX",
        calendar_dates=DATES[: len(prices)],
        price_basis="unadjusted",
        execution_semantics="observed_execution_window",
        initial_as_of=INITIAL,
        cash=(NavCash(bucket="cash", amount=D("1000000")),),
        sessions=sessions,
        cost_policy=fixed_bps_policy(D(0)),
    )
    return NavInput.model_validate({**data, **changes})


def action(kind: str, *, index: int = 0, **changes: object) -> NavAction:
    data = dict(
        event_id=f"{kind}-{index}",
        symbol="A",
        kind=kind,
        effective_at=at(index, 9),
        available_at=INITIAL,
        source_id="verified-test-only-event",
    )
    return NavAction.model_validate({**data, **changes})


@pytest.mark.parametrize("bps", [0, 10, 20, 30, 50])
def test_fixed_order_cost_is_one_way_and_exactly_monotonic(bps: int) -> None:
    value = request(
        prices=((quote(),), (quote(),)),
        orders=(order(0), order(1, side="SELL")),
        cost_policy=fixed_bps_policy(D(bps)),
    )
    strategy, hold, differences = compare_with_hold(value)
    expected_fee = D(20000) * bps / 10000
    assert strategy.total_trading_cost == expected_fee
    assert strategy.days[-1].nav == D(1000000) - expected_fee
    assert differences[-1] == -expected_fee
    assert hold.days[-1].nav == D(1000000)
    assert not strategy.days[-1].positions


def test_component_costs_are_not_also_subtracted_from_execution_price() -> None:
    policy = fixed_bps_policy(D(5)).model_copy(
        update={"commission_fixed": D(10), "commission_bps": D(1), "full_spread_bps": D(20)}
    )
    result = evaluate_daily_nav(request(cost_policy=policy, orders=(order(0),)))
    fill = result.days[0].fills[0]
    assert (fill.cost.commission, fill.cost.spread, fill.cost.slippage) == (D(11), D(10), D(5))
    assert fill.notional == D(10000)
    assert result.days[0].nav == D(999974)


def test_twenty_overlapping_cohorts_share_one_cash_and_daily_nav() -> None:
    n = 41
    orders = [order(i) for i in range(21)] + [order(i + 20, side="SELL") for i in range(21)]
    data = request(
        prices=tuple((quote(price=str(100 + i)),) for i in range(n)), orders=tuple(orders)
    )
    result = evaluate_daily_nav(data)
    for day_index, day in enumerate(result.days):
        # Independent cohort sum, not the evaluator's aggregate position/cash update.
        gain = sum(
            100 * (min(day_index, entry + 20) - entry) for entry in range(min(day_index + 1, 21))
        )
        assert day.nav == D(1000000 + gain)
        assert sum(p.shares for p in day.positions) <= 2000
        assert all(cash.amount >= 0 for cash in day.cash)
    assert result.days[-1].nav == D(1042000)
    compounded = D(1)
    for day in result.days:
        assert day.daily_return is not None
        compounded *= 1 + day.daily_return
    assert float(compounded - 1) == pytest.approx(0.042)


@pytest.mark.parametrize(
    ("shares", "cash", "reserved", "capacity", "expected", "reason"),
    [
        (99, 50000, 0, 10000, 0, "INVALID_LOT"),
        (200, 50000, 0, 150, 100, "PARTIAL_FILL"),
        (200, 10500, 0, 10000, 100, "PARTIAL_FILL"),
        (100, 50000, 45000, 10000, 0, "INSUFFICIENT_CASH"),
        (100, 50000, 0, 0, 0, "NO_FILL_OR_CAPACITY"),
        (100, 50000, 0, None, 0, "UNKNOWN_CAPACITY"),
    ],
)
def test_only_filled_lots_affect_state(
    shares: int, cash: int, reserved: int, capacity: int | None, expected: int, reason: str
) -> None:
    result = evaluate_daily_nav(
        request(
            prices=((quote(capacity_shares=capacity),),),
            cash=(NavCash(bucket="cash", amount=D(cash), reserved=D(reserved)),),
            orders=(order(0, shares=shares),),
            cost_policy=fixed_bps_policy(D(100)),
        )
    )
    day = result.days[0]
    assert (day.fills[0].filled_shares, day.fills[0].reason) == (expected, reason)
    assert day.cash[0].amount == D(cash) - D(expected) * 101
    assert sum(p.shares for p in day.positions) == expected


def test_shared_capacity_and_account_cash_are_not_reused() -> None:
    result = evaluate_daily_nav(
        request(
            prices=((quote(capacity_shares=300),),),
            cash=(NavCash(bucket="a", amount=D(30000)), NavCash(bucket="b", amount=D(30000))),
            orders=(order(0, bucket="b", shares=200), order(0, bucket="a", shares=200)),
        )
    )
    assert [fill.filled_shares for fill in result.days[0].fills] == [200, 100]
    assert [(c.bucket, c.amount) for c in result.days[0].cash] == [("a", D(10000)), ("b", D(20000))]


def test_sale_receivable_cannot_finance_buy_before_explicit_release() -> None:
    data = request(
        prices=tuple((quote(), quote("B", "50")) for _ in range(3)),
        positions=(position(),),
        cash=(NavCash(bucket="cash", amount=D(0)),),
        orders=(
            order(0, side="SELL"),
            order(0, symbol="B"),
            order(1, symbol="B"),
            order(2, symbol="B"),
        ),
    )
    sessions = tuple(
        s.model_copy(update={"sale_cash_available_at": at(2)}) if i < 2 else s
        for i, s in enumerate(data.sessions)
    )
    result = evaluate_daily_nav(data.model_copy(update={"sessions": sessions}))
    assert result.days[0].cash[0].amount == 0
    assert result.days[0].receivables[0].amount == 10000
    assert result.days[0].nav == 10000
    assert result.days[1].fills[0].reason == "INSUFFICIENT_CASH"
    assert result.days[2].cash[0].amount == 5000
    assert result.days[2].positions[0].symbol == "B"
    assert not result.days[2].receivables


@pytest.mark.parametrize(
    "status", ["suspended", "special_quote", "price_limit", "delisted", "unknown"]
)
def test_sell_inability_never_removes_holdings(status: str) -> None:
    data = request(
        prices=((quote(sell_status=status),),),
        positions=(position(),),
        orders=(order(0, side="SELL"),),
    )
    day = evaluate_daily_nav(data).days[0]
    assert day.fills[0].reason == status.upper()
    assert day.positions[0].shares == 100


def test_missing_exit_and_mark_stay_unresolved_with_separate_hypotheses() -> None:
    data = request(
        prices=((quote(price=None),), (quote(price="90"),)),
        cash=(NavCash(bucket="cash", amount=D(5000)),),
        positions=(position(),),
        orders=(order(0, side="SELL"),),
    )
    result = evaluate_daily_nav(data)
    missing, recovered = result.days
    assert missing.fills[0].reason == "MISSING_EXECUTION_PRICE"
    assert missing.nav is None and missing.missing_marks == ("A",)
    assert (
        missing.missing_mark_haircut_0_nav,
        missing.missing_mark_haircut_50_nav,
        missing.missing_mark_haircut_100_nav,
    ) == (15000, 10000, 5000)
    assert recovered.positions[0].shares == 100 and recovered.nav == 14000
    assert recovered.daily_return is None and result.maximum_drawdown is None
    assert not result.valuation_complete


def test_split_only_preserves_nav_and_cost_basis() -> None:
    split = action("split", numerator=2)
    data = request(prices=((quote(price="50"),),), positions=(position(),), actions=(split,))
    day = evaluate_daily_nav(data).days[0]
    assert (day.positions[0].shares, day.positions[0].unit_cost) == (200, 50)
    assert day.nav == 1010000 and day.trading_cost == 0


def test_fractional_split_requires_verified_cash_entitlement() -> None:
    split = action("split", numerator=2, denominator=3)
    data = request(prices=((quote(price="150"),),), positions=(position(),), actions=(split,))
    with pytest.raises(ValueError, match="fractional-share"):
        evaluate_daily_nav(data)
    verified = split.model_copy(update={"fractional_cash_price": D(150), "payment_at": at(1)})
    day = evaluate_daily_nav(data.model_copy(update={"actions": (verified,)})).days[0]
    assert day.positions[0].shares == 66 and day.receivables[0].amount == 100
    assert day.nav == 1010000


def test_dividend_entitlement_survives_sale_and_pays_once() -> None:
    dividend = action("dividend", cash_per_share=D(10), payment_at=at(2))
    data = request(
        prices=tuple((quote(price="90"),) for _ in range(3)),
        cash=(NavCash(bucket="cash", amount=D(0)),),
        positions=(position(),),
        actions=(dividend,),
        orders=(order(1, side="SELL"),),
    )
    result = evaluate_daily_nav(data)
    assert [day.nav for day in result.days] == [10000, 10000, 10000]
    assert [day.cash[0].amount for day in result.days] == [0, 9000, 10000]
    assert not result.days[-1].receivables
    late_buyer = evaluate_daily_nav(
        request(prices=((quote(price="90"),),), actions=(dividend,), orders=(order(0),))
    )
    assert not late_buyer.days[0].receivables


def test_verified_cash_conversion_not_automatic_delisting_liquidation() -> None:
    event = action("cash_conversion", index=1, cash_per_share=D(90), payment_at=at(2))
    data = request(
        prices=tuple((quote(price=None, sell_status="delisted"),) for _ in range(3)),
        cash=(NavCash(bucket="cash", amount=D(0)),),
        positions=(position(),),
        actions=(event,),
    )
    result = evaluate_daily_nav(data)
    assert result.days[0].nav is None and result.days[0].positions[0].shares == 100
    assert result.days[1].nav == 9000 and not result.days[1].positions
    assert result.days[1].cash[0].amount == 0
    assert result.days[2].cash[0].amount == 9000


def test_intraday_payment_cannot_fund_earlier_buy() -> None:
    event = action("dividend", cash_per_share=D(100), payment_at=at(0, 14))
    data = request(
        cash=(NavCash(bucket="cash", amount=D(0)),),
        positions=(position(),),
        actions=(event,),
        orders=(order(0),),
    )
    day = evaluate_daily_nav(data).days[0]
    assert day.fills[0].reason == "INSUFFICIENT_CASH"
    assert day.cash[0].amount == 10000


def test_orders_before_split_are_not_silently_reinterpreted() -> None:
    event = action("split", effective_at=at(0, 11), numerator=2)
    old_order = order(0).model_copy(update={"decided_at": at(0, 10)})
    day = evaluate_daily_nav(request(actions=(event,), orders=(old_order,))).days[0]
    assert day.fills[0].reason == "CORPORATE_ACTION_AFTER_DECISION"


def test_drawdown_uses_daily_marked_nav_and_hold_same_initial_state() -> None:
    data = request(
        prices=tuple((quote(price=p),) for p in ("100", "90", "120", "108")),
        cash=(NavCash(bucket="cash", amount=D(0)),),
        positions=(position(),),
    )
    strategy, hold, differences = compare_with_hold(data)
    assert strategy == hold and differences == (0, 0, 0, 0)
    assert strategy.maximum_drawdown == D(".1")
    assert strategy.total_return == D(".08")


def test_replacement_gain_uses_current_holdings_hold_counterfactual() -> None:
    data = request(
        prices=((quote(), quote("B")), (quote(price="90"), quote("B", "110"))),
        cash=(NavCash(bucket="cash", amount=D(1000)),),
        positions=(position(),),
        orders=(order(0, side="SELL"), order(0, symbol="B")),
        cost_policy=fixed_bps_policy(D(20)),
    )
    strategy, hold, differences = compare_with_hold(data)
    assert strategy.initial_nav == hold.initial_nav == 11000
    assert strategy.days[-1].nav == 11960
    assert hold.days[-1].nav == 10000
    assert differences == (-40, 1960)
    assert strategy.total_trading_cost == 40 and hold.total_trading_cost == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"price_basis": "adjusted"},
        {"calendar_dates": ()},
        {"initial_as_of": datetime(2026, 1, 2)},
        {"cash": (NavCash(bucket="other", amount=D(10000)),), "positions": (position(),)},
        {"orders": (order(0), order(0))},
        {"orders": (order(0).model_copy(update={"decided_at": at(0)}),)},
        {"fill_fraction": D("NaN")},
    ],
)
def test_reject_invalid_or_leaking_input(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        request(**changes)


def test_invalid_events_and_zero_initial_nav_fail_closed() -> None:
    with pytest.raises(ValueError, match="available"):
        action("split", numerator=2, available_at=at(0, 10))
    with pytest.raises(ValueError, match="entitlement"):
        action("dividend", cash_per_share=D(1), payment_at=INITIAL)
    with pytest.raises(ValueError, match="positive"):
        evaluate_daily_nav(request(cash=(NavCash(bucket="cash", amount=D(0)),)))
    with pytest.raises(ValueError, match="duplicate corporate"):
        request(actions=(action("split", numerator=2), action("split", numerator=2)))


def test_report_is_immutable_and_cli_uses_only_explicit_input(tmp_path: Path) -> None:
    data = request(orders=(order(0),))
    written = write_nav_evaluation(data, tmp_path / "reports")
    assert written.is_file()
    assert load_nav_evaluation(written)[0] == data
    with pytest.raises(FileExistsError):
        write_nav_evaluation(data, tmp_path / "reports")
    source = tmp_path / "input.json"
    source.write_text(data.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "research",
            "evaluate-nav",
            "--input",
            str(source),
            "--output-root",
            str(tmp_path / "cli"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert written.read_bytes() == next((tmp_path / "cli").glob("*.json")).read_bytes()
    written.write_bytes(
        written.read_bytes().replace(b'"research_only": true', b'"research_only":false')
    )
    with pytest.raises(ValueError, match="byte hash"):
        load_nav_evaluation(written)


def test_daily_close_proxy_cannot_masquerade_as_noon_execution() -> None:
    data = request(orders=(order(0),))
    with pytest.raises(ValueError, match="closing execution"):
        evaluate_daily_nav(
            data.model_copy(update={"execution_semantics": "daily_close_research_proxy"})
        )
    session = data.sessions[0].model_copy(
        update={"execution_at": at(0, 16), "sale_cash_available_at": at(0, 16)}
    )
    result = evaluate_daily_nav(
        data.model_copy(
            update={"execution_semantics": "daily_close_research_proxy", "sessions": (session,)}
        )
    )
    assert result.days[0].fills[0].filled_shares == 100
    assert result.execution_semantics == "daily_close_research_proxy"


def test_decimal_context_does_not_change_ledger() -> None:
    data = request(orders=(order(0),), cost_policy=fixed_bps_policy(D(17)))
    expected = compare_with_hold(data)
    with localcontext() as context:
        context.prec = 5
        assert compare_with_hold(data) == expected


def test_tick_rule_and_no_fill_fraction_are_enforced() -> None:
    data = request(prices=((quote(price="100.5"),),), orders=(order(0),))
    assert evaluate_daily_nav(data).days[0].fills[0].reason == "INVALID_PRICE_TICK"
    no_fill = request(orders=(order(0),), fill_fraction=D(0))
    assert evaluate_daily_nav(no_fill).days[0].fills[0].filled_shares == 0
    half = request(orders=(order(0, shares=400),), fill_fraction=D(".5"))
    assert evaluate_daily_nav(half).days[0].fills[0].filled_shares == 200


def test_sell_cannot_create_short_or_negative_proceeds() -> None:
    short = request(orders=(order(0, side="SELL"),))
    assert evaluate_daily_nav(short).days[0].fills[0].reason == "INSUFFICIENT_HOLDINGS"
    costly = request(
        positions=(position(),),
        orders=(order(0, side="SELL"),),
        cost_policy=fixed_bps_policy(D(0)).model_copy(update={"commission_fixed": D(20000)}),
    )
    result = evaluate_daily_nav(costly)
    assert result.days[0].fills[0].reason == "COST_EXCEEDS_PROCEEDS"
    assert result.days[0].positions[0].shares == 100


def test_partial_sale_then_cash_conversion_cannot_be_bought_back() -> None:
    event = action("cash_conversion", cash_per_share=D(100), payment_at=at(0))
    data = request(positions=(position(shares=200),), orders=(order(0, side="SELL"),))
    assert evaluate_daily_nav(data).days[0].positions[0].shares == 100
    converted = request(positions=(position(),), actions=(event,), orders=(order(0),))
    assert evaluate_daily_nav(converted).days[0].fills[0].reason == "CASH_CONVERSION_COMPLETE"


def test_missing_price_row_does_not_drop_initial_holding() -> None:
    data = request(prices=((),), positions=(position(),))
    day = evaluate_daily_nav(data).days[0]
    assert day.positions[0].shares == 100 and day.nav is None


def test_cli_rejects_bad_input_without_publishing_receipt(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text('{"schema_version":"bad"}', encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "research",
            "evaluate-nav",
            "--input",
            str(source),
            "--output-root",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 2
    assert not (tmp_path / "out").exists()
