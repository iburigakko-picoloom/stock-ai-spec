"""Synthetic, hand-calculated share-exchange accounting and legacy identities."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_ai.ml.nav import (
    NavAction,
    NavCash,
    NavDecisionState,
    NavInput,
    NavOrder,
    NavPosition,
    NavPrice,
    NavSession,
    _Ledger,
    evaluate_daily_nav,
    evaluate_stateful_nav,
    fixed_bps_policy,
    load_nav_evaluation,
)

JST = ZoneInfo("Asia/Tokyo")
INITIAL = datetime(2025, 6, 30, 16, tzinfo=JST)
DATES = (date(2025, 7, 1), date(2025, 7, 2), date(2025, 7, 3))


def at(index: int = 0, hour: int = 9) -> datetime:
    return datetime.combine(DATES[index], datetime.min.time(), JST).replace(hour=hour)


def position(
    symbol: str = "OLD", shares: int = 100, cost: str = "100", bucket: str = "cash"
) -> NavPosition:
    return NavPosition(
        symbol=symbol, bucket=bucket, shares=shares, unit_cost=D(cost),
        last_price=D(cost), last_price_at=INITIAL,
    )


def quote(symbol: str = "NEW", price: str = "100", tick: str = "1") -> NavPrice:
    return NavPrice(
        symbol=symbol, execution_price=D(price), close_price=D(price),
        buy_status="tradable", sell_status="tradable", capacity_shares=10000,
        tick_size=D(tick), source_id="synthetic-observed-recipient-quote",
    )


def exchange(**changes: object) -> NavAction:
    return NavAction.model_validate({
        "event_id": "synthetic-exchange", "symbol": "OLD", "recipient_symbol": "NEW",
        "kind": "share_exchange", "effective_at": at(), "available_at": INITIAL,
        "source_id": "synthetic-verified-share-exchange", **changes,
    })


def request(
    *, prices: tuple[tuple[NavPrice, ...], ...] = ((quote(),),), **changes: object
) -> NavInput:
    return NavInput.model_validate({
        "data_mode": "fixture", "source_snapshot_id": "synthetic-share-exchange-only",
        "calendar_id": "synthetic-calendar-not-JPX", "calendar_dates": DATES[:len(prices)],
        "price_basis": "unadjusted", "execution_semantics": "observed_execution_window",
        "initial_as_of": INITIAL, "cash": (NavCash(bucket="cash", amount=D(0)),),
        "positions": (position(),), "cost_policy": fixed_bps_policy(D(0)),
        "sessions": tuple(NavSession(
            trading_date=DATES[i], execution_at=at(i, 12), close_at=at(i, 16),
            sale_cash_available_at=at(i, 12), prices=values,
        ) for i, values in enumerate(prices)), **changes,
    })


@pytest.mark.parametrize(
    ("numerator", "denominator", "old_cost", "new_price", "expected_shares"),
    [(1, 1, "100", "100", 100), (13, 20, "130", "200", 65),
     (23, 20, "230", "200", 115)],
)
def test_exact_exchange_removes_old_once_and_transfers_entire_cost(
    numerator: int, denominator: int, old_cost: str, new_price: str, expected_shares: int
) -> None:
    data = request(
        positions=(position(cost=old_cost),), prices=((quote(price=new_price),),),
        actions=(exchange(numerator=numerator, denominator=denominator),),
    )
    result = evaluate_daily_nav(data)
    day = result.days[0]
    assert [(p.symbol, p.shares) for p in day.positions] == [("NEW", expected_shares)]
    assert day.positions[0].unit_cost * expected_shares == D(old_cost) * 100
    assert day.nav == result.initial_nav == D(old_cost) * 100
    assert day.trading_cost == 0 and day.cash[0].amount == 0
    assert not day.receivables and not day.fractional_entitlements
    assert day.applied_event_ids == ("synthetic-exchange",)
    assert result.valuation_complete and result.maximum_drawdown == 0


def test_exchange_merges_receiver_book_cost_only_within_same_account() -> None:
    data = request(
        positions=(position(cost="130"), position("NEW", 35, "100"),
                   position("NEW", 50, "80", bucket="other")),
        cash=(NavCash(bucket="cash", amount=D(0)), NavCash(bucket="other", amount=D(0))),
        actions=(exchange(numerator=13, denominator=20),),
        prices=((quote(price="200"),),),
    )
    positions = {p.key: p for p in evaluate_daily_nav(data).days[0].positions}
    assert positions[("NEW", "cash")].shares == 100
    assert positions[("NEW", "cash")].unit_cost == 165
    assert positions[("NEW", "other")].shares == 50
    assert positions[("NEW", "other")].unit_cost == 80
    assert sum(p.shares * p.unit_cost for p in positions.values()) == 20500


def test_unknown_fraction_survives_every_day_and_state_without_a_zero_claim() -> None:
    data = request(
        positions=(position(shares=3, cost="13"),),
        actions=(exchange(numerator=13, denominator=20),),
        prices=((quote(price="20"),),) * 3,
    )
    states: list[NavDecisionState] = []

    def decide(state: NavDecisionState) -> tuple[NavOrder, ...]:
        states.append(state)
        return ()

    _, result = evaluate_stateful_nav(data, decision_times=tuple(at(i, 11) for i in range(3)),
                                      decide=decide)
    for day, state in zip(result.days, states, strict=True):
        assert day.positions[0].symbol == "NEW" and day.positions[0].shares == 1
        assert day.positions[0].unit_cost == 20
        assert not day.receivables and day.cash[0].amount == 0
        assert day.nav is None and not day.missing_marks
        right, = day.fractional_entitlements
        assert (right.numerator, right.denominator, right.cost_basis) == (19, 20, 19)
        assert not right.value_confirmed
        assert right.cost_basis + day.positions[0].unit_cost == 39
        assert state.fractional_entitlements == day.fractional_entitlements
    assert result.total_return is None and result.maximum_drawdown is None
    assert not result.valuation_complete
    restored = type(result).model_validate_json(result.model_dump_json())
    assert restored == result


def test_all_fractional_entitlement_retains_cost_without_any_integer_holding() -> None:
    day = evaluate_daily_nav(request(
        positions=(position(shares=1),), actions=(exchange(numerator=1, denominator=2),),
        prices=((),),
    )).days[0]
    assert not day.positions and not day.receivables
    assert day.fractional_entitlements[0].cost_basis == 100
    assert day.nav is None and day.cash[0].amount == 0


def test_known_fraction_cash_is_not_spendable_until_verified_payment() -> None:
    orders = tuple(NavOrder.model_validate({
        "order_id": f"buy-{i}", "trading_date": DATES[i], "decided_at": at(i, 11),
        "symbol": "C", "bucket": "cash", "side": "BUY", "shares": 100,
    }) for i in range(3))
    result = evaluate_daily_nav(request(
        positions=(position(shares=3, cost="13"),),
        actions=(exchange(numerator=13, denominator=20, fractional_cash_price=D(20),
                          payment_at=at(2, 10)),),
        prices=((quote(price="20"), quote("C", ".1", ".1")),) * 3, orders=orders,
    ))
    for day in result.days[:2]:
        assert day.fills[0].reason == "INSUFFICIENT_CASH" and day.cash[0].amount == 0
        assert day.receivables[0].amount == 19 and day.receivables[0].cost_basis == 19
        assert day.receivables[0].kind == "fractional_cash"
        assert not day.fractional_entitlements
    assert result.days[2].fills[0].reason == "FILLED"
    assert result.days[2].cash[0].amount == 9 and not result.days[2].receivables
    assert [day.nav for day in result.days] == [39, 39, 39]


def test_known_fraction_amount_unknown_payment_remains_unspendable_and_unconfirmed() -> None:
    result = evaluate_daily_nav(request(
        positions=(position(shares=3, cost="13"),),
        actions=(exchange(numerator=13, denominator=20, fractional_cash_price=D(20)),),
        prices=((quote(price="20"),),) * 3,
    ))
    for day in result.days:
        assert day.receivables[0].amount == 19 and day.receivables[0].payment_at is None
        assert day.receivables[0].kind == "fractional_cash_pending_payment"
        assert day.receivables[0].cost_basis == 19
        assert day.unresolved_cash_payments == ("synthetic-exchange",)
        assert day.cash[0].amount == 0 and day.nav is None
    assert not result.valuation_complete and result.maximum_drawdown is None


def test_missing_recipient_mark_never_uses_scaled_old_reference_as_confirmed_nav() -> None:
    result = evaluate_daily_nav(request(
        actions=(exchange(numerator=13, denominator=20),), prices=((),),
    ))
    assert result.days[0].positions[0].last_price_at == INITIAL
    assert result.days[0].missing_marks == ("NEW",)
    assert result.days[0].nav is None and result.maximum_drawdown is None


def test_duplicate_event_ids_are_rejected_and_internal_reapply_is_idempotent() -> None:
    event = exchange(numerator=13, denominator=20)
    data = request(positions=(position(shares=3, cost="13"),))
    with pytest.raises(ValueError, match="duplicate corporate-action"):
        request(actions=(event, event))
    ledger = _Ledger(data)
    ledger.apply_action(event)
    first_positions = dict(ledger.positions)
    first_rights = tuple(ledger.fractional_entitlements)
    ledger.apply_action(event)
    assert ledger.positions == first_positions
    assert tuple(ledger.fractional_entitlements) == first_rights
    assert len(ledger.events) == 1
    with pytest.raises(ValueError, match="conflicting corporate-action"):
        ledger.apply_action(event.model_copy(update={"recipient_symbol": "C"}))


def test_repeated_exchange_and_settlement_never_double_pay_fraction_cash() -> None:
    event = exchange(numerator=13, denominator=20, fractional_cash_price=D(20),
                     payment_at=at(1, 10))
    ledger = _Ledger(request(positions=(position(shares=3, cost="13"),)))
    ledger.apply_action(event)
    ledger.apply_action(event)
    assert len(ledger.receivables) == 1 and ledger.receivables[0].amount == 19
    assert ledger.positions[("NEW", "cash")].shares == 1
    ledger.settle(at(1, 10))
    ledger.settle(at(2, 16))
    assert ledger.cash["cash"].amount == 19 and not ledger.receivables
    assert len(ledger.events) == 1


@pytest.mark.parametrize("symbol", ["OLD", "NEW"])
def test_pre_exchange_orders_are_never_reinterpreted_as_receiver_quantity(symbol: str) -> None:
    order = NavOrder.model_validate({
        "order_id": "old-decision", "trading_date": DATES[0], "decided_at": at(hour=8),
        "symbol": symbol, "bucket": "cash", "side": "SELL", "shares": 100,
    })
    day = evaluate_daily_nav(request(actions=(exchange(),), orders=(order,))).days[0]
    assert day.fills[0].reason == "CORPORATE_ACTION_AFTER_DECISION"


def test_fresh_old_symbol_order_is_refused_even_if_old_quote_is_supplied() -> None:
    order = NavOrder.model_validate({
        "order_id": "after-exchange", "trading_date": DATES[0], "decided_at": at(hour=11),
        "symbol": "OLD", "bucket": "cash", "side": "BUY", "shares": 100,
    })
    day = evaluate_daily_nav(request(actions=(exchange(),), orders=(order,),
                                    prices=((quote(), quote("OLD")),))).days[0]
    assert day.fills[0].reason == "SHARE_EXCHANGE_COMPLETE"
    assert [(p.symbol, p.shares) for p in day.positions] == [("NEW", 100)]


@pytest.mark.parametrize("changes", [
    {"recipient_symbol": None}, {"recipient_symbol": "OLD"}, {"cash_per_share": D(1)},
    {"payment_at": at(1)}, {"numerator": 0}, {"denominator": 0},
    {"available_at": at(hour=10)},
])
def test_invalid_exchange_and_future_available_evidence_fail_closed(
    changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        exchange(**changes)


def test_old_split_cannot_disguise_a_recipient_exchange_and_chain_needs_sequencing() -> None:
    with pytest.raises(ValueError, match="only share exchange"):
        exchange(kind="split", numerator=2)
    recipient_split = exchange(event_id="recipient-split", kind="split", symbol="NEW",
                               recipient_symbol=None, numerator=2)
    with pytest.raises(ValueError, match="recipient corporate actions"):
        request(actions=(exchange(), recipient_split))


@pytest.mark.parametrize("kind", ["split", "dividend", "cash_conversion",
                                  "cash_conversion_pending_payment"])
def test_legacy_action_input_and_report_bytes_and_ids_roundtrip(kind: str, tmp_path: Path) -> None:
    old_action = {
        "event_id": "legacy", "symbol": "OLD", "kind": kind,
        "effective_at": at().isoformat(), "available_at": INITIAL.isoformat(),
        "source_id": "synthetic-legacy-evidence", "numerator": 2 if kind == "split" else 1,
        "denominator": 1, "cash_per_share": None if kind == "split" else "1",
        "payment_at": None if kind in {"split", "cash_conversion_pending_payment"}
        else at(1).isoformat(), "fractional_cash_price": None,
    }
    data = request(actions=(NavAction.model_validate(old_action),),
                   prices=((quote("OLD", "50" if kind == "split" else "100"),),))
    old_input = data.model_dump(mode="json")
    assert "recipient_symbol" not in old_input["actions"][0]
    assert old_input["actions"][0] == old_action
    encoded_input = json.dumps(old_input, sort_keys=True, separators=(",", ":"), allow_nan=False)
    strategy = evaluate_daily_nav(data)
    assert strategy.input_sha256 == hashlib.sha256(encoded_input.encode()).hexdigest()
    old_result = strategy.model_dump(mode="json")
    assert all("fractional_entitlements" not in day for day in old_result["days"])
    assert all(
        "cost_basis" not in claim
        for day in old_result["days"] for claim in day["receivables"]
    )
    old_payload = {"input": old_input, "strategy": old_result, "hold": old_result}
    original_bytes = json.dumps(old_payload, sort_keys=True, separators=(",", ":")).encode()
    receipt_id = hashlib.sha256(original_bytes).hexdigest()
    path = tmp_path / f"{receipt_id}.json"
    path.write_bytes(original_bytes + b"\n")
    loaded_input, loaded_strategy, loaded_hold = load_nav_evaluation(path)
    reserialized = json.dumps({
        "input": loaded_input.model_dump(mode="json"),
        "strategy": loaded_strategy.model_dump(mode="json"),
        "hold": loaded_hold.model_dump(mode="json"),
    }, sort_keys=True, separators=(",", ":")).encode()
    assert reserialized == original_bytes
    assert hashlib.sha256(reserialized).hexdigest() == receipt_id
    assert "fractional_entitlements" not in NavDecisionState(
        as_of=at(), cash=data.cash, positions=data.positions, receivables=(), applied_event_ids=(),
    ).model_dump(mode="json")
