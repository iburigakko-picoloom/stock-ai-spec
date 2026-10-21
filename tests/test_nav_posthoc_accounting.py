"""Small synthetic accounting tests; no real prices, labels or holdout access."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date, datetime
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from stock_ai.ml.nav import (
    NavAction,
    NavCash,
    NavDecisionState,
    NavInput,
    NavOrder,
    NavPosition,
    NavPosthocAction,
    NavPrice,
    NavSession,
    PosthocOfficialSource,
    _Ledger,
    evaluate_daily_nav,
    evaluate_stateful_nav,
    fixed_bps_policy,
)

JST = ZoneInfo("Asia/Tokyo")
INITIAL = datetime(2025, 9, 26, 16, tzinfo=JST)
DATES = (date(2025, 9, 29), date(2025, 9, 30), date(2025, 10, 1))
RECEIVED = datetime(2026, 10, 21, 11, 40, tzinfo=JST)
LEGACY_GOLDEN_INPUT_HASH = "14bcb17ff05a8e11ec1cdb5416dcefc3f18465cf19b7cf510a8166f76ef2fdb5"


def at(index=0, hour=9):
    return datetime.combine(DATES[index], datetime.min.time(), JST).replace(hour=hour)


def official(**changes):
    return PosthocOfficialSource.model_validate({
        "url": "https://issuer.example.invalid/synthetic-document.pdf",
        "document_sha256": "a" * 64, "actual_received_at": RECEIVED,
        "publication_date": date(2025, 8, 6), "publication_at": None,
        "authority": "issuer", **changes,
    })


def posthoc(**changes):
    return NavPosthocAction.model_validate({
        "event_id": "synthetic-posthoc-split", "symbol": "A", "kind": "split",
        "actual_received_at": RECEIVED, "official_sources": (official(),),
        "legal_effective_date": DATES[2], "legal_effective_at": None,
        "ex_rights_date": DATES[0], "quantity_basis_at": at(),
        "quantity_basis": "ex_rights_daily_price_proxy",
        "research_assumption_version": "synthetic-ex-post-economic-basis-only-v1",
        "numerator": 7, "denominator": 1, **changes,
    })


def quote(symbol="A", price="10", tick="1"):
    return NavPrice(symbol=symbol, execution_price=D(price), close_price=D(price),
        buy_status="tradable", sell_status="tradable", capacity_shares=100000,
        tick_size=D(tick), source_id="synthetic-not-observed-market")


def position(symbol="A", shares=100, cost="70"):
    return NavPosition(symbol=symbol, bucket="cash", shares=shares,
        unit_cost=D(cost), last_price=D(cost), last_price_at=INITIAL)


def request(*, prices=None, **changes):
    if prices is None:
        prices = ((quote(),),)
    return NavInput.model_validate({
        "data_mode": "fixture", "source_snapshot_id": "synthetic-posthoc-only",
        "calendar_id": "synthetic-calendar-not-JPX", "calendar_dates": DATES[:len(prices)],
        "price_basis": "unadjusted", "execution_semantics": "observed_execution_window",
        "initial_as_of": INITIAL, "cash": (NavCash(bucket="cash", amount=D(100000)),),
        "positions": (position(),), "cost_policy": fixed_bps_policy(D(0)),
        "sessions": tuple(NavSession(trading_date=DATES[i], execution_at=at(i, 12),
            close_at=at(i, 16), sale_cash_available_at=at(i, 12), prices=values)
            for i, values in enumerate(prices)), **changes,
    })


class TestNavPosthocCore(unittest.TestCase):
    def test_no_available_at_or_fake_nav_action(self):
        event = posthoc()
        self.assertNotIsInstance(event, NavAction)
        self.assertNotIn("available_at", event.model_dump())
        self.assertNotIn("effective_at", event.model_dump())
        self.assertEqual(event.actual_received_at, RECEIVED)
        self.assertEqual(event.legal_effective_date, DATES[2])
        self.assertIsNone(event.legal_effective_at)
        self.assertEqual(event.ex_rights_date, DATES[0])
        self.assertIsNone(event.official_sources[0].publication_at)
        with self.assertRaises(ValueError):
            posthoc(available_at=at())

    def test_existing_pit_validator_still_rejects_late_receipt(self):
        with self.assertRaisesRegex(ValueError, "not available"):
            NavAction(event_id="not-posthoc", symbol="A", kind="split",
                numerator=7, denominator=1, effective_at=at(), available_at=RECEIVED,
                source_id="synthetic-late")

    def test_split_quantity_cost_and_nav_share_original_ledger_math(self):
        data = request(posthoc_actions=(posthoc(),))
        result = evaluate_daily_nav(data)
        day = result.days[0]
        self.assertEqual([(p.symbol, p.shares, p.unit_cost) for p in day.positions],
            [("A", 700, 10)])
        self.assertEqual(day.nav, result.initial_nav)
        self.assertEqual(day.cash[0].amount, 100000)
        self.assertFalse(day.receivables)
        self.assertEqual(day.trading_cost, 0)
        self.assertTrue(result.valuation_complete)
        self.assertEqual(result.maximum_drawdown, 0)
        legacy = NavAction(event_id="synthetic-posthoc-split", symbol="A", kind="split",
            numerator=7, denominator=1, effective_at=at(), available_at=INITIAL,
            source_id="synthetic-early-known-for-mathematical-parity-only")
        expected = evaluate_daily_nav(request(actions=(legacy,)))
        self.assertEqual(result.days, expected.days)
        self.assertFalse(result.adoption_eligible)

    def test_actual_receipt_legal_date_and_unknown_publication_survive_roundtrip(self):
        data = request(posthoc_actions=(posthoc(),))
        saved = NavInput.model_validate_json(data.model_dump_json())
        self.assertEqual(saved, data)
        self.assertEqual(saved.posthoc_actions[0].actual_received_at, RECEIVED)
        self.assertEqual(saved.posthoc_actions[0].legal_effective_date, DATES[2])
        self.assertIsNone(saved.posthoc_actions[0].official_sources[0].publication_at)
        self.assertEqual(evaluate_daily_nav(data), evaluate_daily_nav(saved))

    def test_empty_posthoc_omits_field_and_preserves_legacy_hash(self):
        data = request()
        self.assertNotIn("posthoc_actions", data.model_dump(mode="json"))
        self.assertEqual(data.model_dump(mode="json"),
            request(posthoc_actions=()).model_dump(mode="json"))
        canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(evaluate_daily_nav(data).input_sha256,
            hashlib.sha256(canonical).hexdigest())
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), LEGACY_GOLDEN_INPUT_HASH)

    def test_receipt_metadata_changes_authenticated_input_not_share_math(self):
        original = request(posthoc_actions=(posthoc(),))
        other_time = RECEIVED.replace(minute=41)
        changed = request(posthoc_actions=(posthoc(actual_received_at=other_time),))
        before, after = evaluate_daily_nav(original), evaluate_daily_nav(changed)
        self.assertEqual(before.days, after.days)
        self.assertNotEqual(before.input_sha256, after.input_sha256)

    def test_same_event_is_not_applied_or_paid_twice(self):
        event = posthoc()
        ledger = _Ledger(request())
        ledger.apply_action(event)
        ledger.apply_action(event)
        self.assertEqual(ledger.positions[("A", "cash")].shares, 700)
        self.assertEqual(len(ledger.events), 1)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            ledger.apply_action(posthoc(numerator=8))

    def test_duplicate_ids_and_same_time_aliases_across_both_inputs_rejected(self):
        legacy = NavAction(event_id="synthetic-posthoc-split", symbol="A", kind="split",
            effective_at=at(), available_at=INITIAL, source_id="synthetic", numerator=2)
        with self.assertRaisesRegex(ValueError, "duplicate corporate-action"):
            request(actions=(legacy,), posthoc_actions=(posthoc(),))
        with self.assertRaisesRegex(ValueError, "simultaneous same-symbol"):
            request(actions=(legacy.model_copy(update={"event_id": "alias"}),),
                posthoc_actions=(posthoc(),))

    def test_future_quantity_effect_is_not_applied_early_or_sent_to_signal(self):
        event = posthoc(quantity_basis_at=at(2), quantity_basis="legal_effective")
        data = request(prices=((quote(price="70"),), (quote(price="70"),), (quote(),)),
            posthoc_actions=(event,))
        states = []

        def decide(state: NavDecisionState):
            states.append(state)
            return ()

        _, nav = evaluate_stateful_nav(data,
            decision_times=tuple(at(i, 11) for i in range(3)), decide=decide)
        self.assertEqual([s.positions[0].shares for s in states], [100, 100, 700])
        self.assertEqual([s.applied_event_ids for s in states], [(), (), (event.event_id,)])
        for state in states:
            encoded = state.model_dump_json()
            self.assertNotIn("actual_received_at", encoded)
            self.assertNotIn("official_sources", encoded)
            self.assertNotIn("publication_date", encoded)
        self.assertEqual([day.nav for day in nav.days], [107000, 107000, 107000])

    def test_pre_effect_order_is_not_reinterpreted_in_new_share_units(self):
        order = NavOrder(order_id="before-basis", trading_date=DATES[0], decided_at=at(hour=8),
            symbol="A", bucket="cash", side="SELL", shares=100)
        day = evaluate_daily_nav(request(orders=(order,), posthoc_actions=(posthoc(),))).days[0]
        self.assertEqual(day.fills[0].reason, "CORPORATE_ACTION_AFTER_DECISION")
        self.assertEqual(day.positions[0].shares, 700)

    def test_missing_mark_does_not_use_scaled_reference_as_confirmed_nav(self):
        nav = evaluate_daily_nav(request(prices=((),), posthoc_actions=(posthoc(),)))
        self.assertEqual(nav.days[0].missing_marks, ("A",))
        self.assertIsNone(nav.days[0].nav)
        self.assertIsNone(nav.maximum_drawdown)
        self.assertFalse(nav.valuation_complete)

    def test_unknown_split_fraction_is_stopped_without_fabricated_cash(self):
        ledger = _Ledger(request(positions=(position(shares=1),)))
        with self.assertRaisesRegex(ValueError, "fractional-share entitlement"):
            ledger.apply_action(posthoc(numerator=1, denominator=3))
        self.assertEqual(ledger.positions[("A", "cash")].shares, 1)
        self.assertEqual(ledger.cash["cash"].amount, 100000)
        self.assertFalse(ledger.receivables)

    def test_share_exchange_preserves_fractional_right_and_book_cost(self):
        event = posthoc(kind="share_exchange", recipient_symbol="B", numerator=13, denominator=20)
        nav = evaluate_daily_nav(request(positions=(position(shares=3, cost="13"),),
            prices=((quote("B", "20"),),), posthoc_actions=(event,)))
        day = nav.days[0]
        self.assertEqual([(p.symbol, p.shares, p.unit_cost) for p in day.positions], [("B", 1, 20)])
        self.assertEqual(day.fractional_entitlements[0].cost_basis, 19)
        self.assertIsNone(day.nav)
        self.assertIsNone(nav.maximum_drawdown)
        self.assertFalse(nav.valuation_complete)

    def test_unknown_fraction_payment_is_not_reinvestable_or_confirmed_nav(self):
        event = posthoc(kind="share_exchange", recipient_symbol="B", numerator=13, denominator=20,
            fractional_cash_price=D(20))
        nav = evaluate_daily_nav(request(positions=(position(shares=3, cost="13"),),
            cash=(NavCash(bucket="cash", amount=D(0)),),
            prices=((quote("B", "20"),),), posthoc_actions=(event,)))
        day = nav.days[0]
        self.assertEqual(day.cash[0].amount, 0)
        self.assertEqual(day.receivables[0].amount, 19)
        self.assertIsNone(day.receivables[0].payment_at)
        self.assertEqual(day.receivables[0].kind, "fractional_cash_pending_payment")
        self.assertIsNone(day.nav)
        self.assertIsNone(nav.maximum_drawdown)

    def test_known_fraction_payment_settles_once_only_at_declared_payment(self):
        event = posthoc(kind="share_exchange", recipient_symbol="B", numerator=13, denominator=20,
            fractional_cash_price=D(20), payment_at=at(2, 10))
        orders = tuple(NavOrder(order_id=f"buy-{i}", trading_date=DATES[i], decided_at=at(i, 11),
            symbol="C", bucket="cash", side="BUY", shares=100) for i in range(3))
        nav = evaluate_daily_nav(request(positions=(position(shares=3, cost="13"),),
            cash=(NavCash(bucket="cash", amount=D(0)),), prices=((quote("B", "20"),
                quote("C", ".1", ".1")),) * 3, orders=orders, posthoc_actions=(event,)))
        self.assertEqual([day.fills[0].reason for day in nav.days],
            ["INSUFFICIENT_CASH", "INSUFFICIENT_CASH", "FILLED"])
        self.assertEqual([day.cash[0].amount for day in nav.days], [0, 0, 9])
        self.assertEqual([day.nav for day in nav.days], [39, 39, 39])

    def test_posthoc_clock_source_ratio_and_kind_validation(self):
        invalid = (
            {"actual_received_at": at()}, {"official_sources": ()},
            {"legal_effective_at": at()}, {"quantity_basis_at": at(1)},
            {"quantity_basis": "legal_effective"}, {"numerator": 1},
            {"kind": "cash_conversion"}, {"recipient_symbol": "B"},
            {"official_sources": (official(), official())},
            {"legal_effective_date": date(2027, 1, 1)},
            {"kind": "share_exchange", "recipient_symbol": "A"},
            {"kind": "share_exchange", "recipient_symbol": "B", "payment_at": at(2, 10)},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                posthoc(**change)
        for change in ({"url": "http://issuer.example.invalid/a"},
            {"document_sha256": "not-a-hash"}, {"publication_at": at()},
            {"publication_date": date(2027, 1, 1)}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                official(**change)


class TestPosthocFixedRule(unittest.TestCase):
    """Run with the later root source-test slot; fixed_rule imports ML modules."""

    def test_affected_reference_check_uses_both_action_types(self):
        from stock_ai.ml.fixed_rule import FixedRulePolicy, FixedSignalDay, evaluate_fixed_rule

        data = request(positions=(), posthoc_actions=(posthoc(),))
        policy = FixedRulePolicy(horizon=5, initial_cash_yen=100000, top_n=1, one_way_bps=0)
        signal = FixedSignalDay(as_of=at(hour=11), available_at=INITIAL,
            reference_price_at=INITIAL, horizon=5, score_unit="ranking_score",
            scores=(("A", 1),), reference_prices=(("A", D(70)),), source_id="synthetic-score-only")
        with self.assertRaisesRegex(ValueError, "reference predates"):
            evaluate_fixed_rule(data, (signal,), policy)
        signal = signal.model_copy(update={"reference_price_at": at(),
            "reference_prices": (("A", D(10)),)})
        realized, nav, _ = evaluate_fixed_rule(data, (signal,), policy)
        self.assertEqual(nav.days[0].positions[0].shares, 9000)
        self.assertEqual(evaluate_daily_nav(realized), nav)


class TestPosthocStrictEntrypoints(unittest.TestCase):
    """No market artifacts opened; methods reject before evidence/path reads."""

    def test_market_and_assumed_entries_reject_new_contract(self):
        from stock_ai.ml.assumed_market import AssumedMarketRequest
        from stock_ai.ml.market_nav import MarketStrategyRequest

        accounting = request(posthoc_actions=(posthoc(),))
        wrapper = SimpleNamespace(accounting=accounting)
        with self.assertRaisesRegex(ValueError, "rejects posthoc"):
            MarketStrategyRequest.explicit_dividend_treatment(SimpleNamespace(strategy=wrapper))
        with self.assertRaisesRegex(ValueError, "rejects a new posthoc"):
            AssumedMarketRequest.preserve_existing_evidence_contract(SimpleNamespace(rule=wrapper))

    def test_final_real_entry_rejects_before_final_prediction_access(self):
        from stock_ai.ml.final_strategy import FinalHorizonInputs

        accounting = request(data_mode="historical_research", posthoc_actions=(posthoc(),))
        with self.assertRaisesRegex(ValueError, "strict final evaluation rejects"):
            FinalHorizonInputs.same_calendar(SimpleNamespace(accounting=accounting))


if __name__ == "__main__":
    unittest.main()
