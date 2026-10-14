"""Research-only, long-only daily accounting; never creates actual executions.

Inputs are explicit raw execution/closing prices and corporate-action evidence.
Forward-return labels are deliberately absent. Cash settlements, receivables,
unfilled orders and unvalued holdings survive until their actual resolution.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Context, Decimal, localcontext
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from stock_ai.decision.costs import CostPolicy, TransactionCostEngine
from stock_ai.domain import TradeSide, TransactionCostEstimate

ZERO = Decimal("0")
ONE = Decimal("1")
JST = ZoneInfo("Asia/Tokyo")
Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
PositivePrice = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Quantity = Annotated[int, Field(strict=True, ge=0)]
TradingStatus = Literal[
    "tradable", "suspended", "special_quote", "price_limit", "delisted", "unknown"
]


class NavModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def aware_times(cls, value: object) -> object:
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("NAV timestamps must be timezone-aware")
        return value


class NavCash(NavModel):
    bucket: str = Field(min_length=1)
    amount: Money
    reserved: Money = ZERO

    @model_validator(mode="after")
    def valid_reservation(self) -> Self:
        if self.reserved > self.amount:
            raise ValueError("reserved cash exceeds cash")
        return self


class NavPosition(NavModel):
    symbol: str = Field(min_length=1)
    bucket: str = Field(min_length=1)
    shares: Quantity
    unit_cost: Money
    last_price: PositivePrice
    last_price_at: datetime

    @property
    def key(self) -> tuple[str, str]:
        return self.symbol, self.bucket


class NavPrice(NavModel):
    symbol: str = Field(min_length=1)
    execution_price: PositivePrice | None
    close_price: PositivePrice | None
    buy_status: TradingStatus
    sell_status: TradingStatus
    capacity_shares: Quantity | None
    tick_size: PositivePrice
    average_daily_trading_value: Money | None = None
    source_id: str = Field(min_length=1)


class NavSession(NavModel):
    trading_date: date
    execution_at: datetime
    close_at: datetime
    # Explicit buying-power release timestamp, not an assumed T+N calendar.
    sale_cash_available_at: datetime
    prices: tuple[NavPrice, ...]

    @model_validator(mode="after")
    def valid_session(self) -> Self:
        if self.execution_at > self.close_at:
            raise ValueError("execution must precede the closing valuation")
        if self.sale_cash_available_at < self.execution_at:
            raise ValueError("sale buying power cannot precede execution")
        if any(
            at.astimezone(JST).date() != self.trading_date
            for at in (self.execution_at, self.close_at)
        ):
            raise ValueError("session date differs from execution/close date in JST")
        if len({price.symbol for price in self.prices}) != len(self.prices):
            raise ValueError("duplicate symbol price in session")
        return self


class NavOrder(NavModel):
    order_id: str = Field(min_length=1)
    trading_date: date
    decided_at: datetime
    symbol: str = Field(min_length=1)
    bucket: str = Field(min_length=1)
    side: TradeSide
    shares: Annotated[int, Field(strict=True, gt=0)]


class NavAction(NavModel):
    event_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    kind: Literal["split", "dividend", "cash_conversion"]
    effective_at: datetime
    available_at: datetime
    source_id: str = Field(min_length=1)
    numerator: Annotated[int, Field(strict=True, gt=0)] = 1
    denominator: Annotated[int, Field(strict=True, gt=0)] = 1
    cash_per_share: Money | None = None
    payment_at: datetime | None = None
    fractional_cash_price: Money | None = None

    @model_validator(mode="after")
    def valid_action(self) -> Self:
        if self.available_at > self.effective_at:
            raise ValueError("corporate-action evidence is not available at its effective time")
        if self.payment_at is not None and self.payment_at < self.effective_at:
            raise ValueError("payment cannot precede entitlement")
        if self.kind == "split":
            if self.cash_per_share is not None or self.numerator == self.denominator:
                raise ValueError("split requires a non-unit share ratio and no distribution")
            if (self.fractional_cash_price is None) != (self.payment_at is None):
                raise ValueError("fractional cash requires both an amount and a payment time")
        elif (
            self.cash_per_share is None
            or self.payment_at is None
            or self.numerator != 1
            or self.denominator != 1
            or self.fractional_cash_price is not None
        ):
            raise ValueError("cash event requires amount/payment and no split parameters")
        return self


class NavInput(NavModel):
    schema_version: Literal["daily-nav-input-v1"] = "daily-nav-input-v1"
    data_mode: Literal["fixture", "historical_research"]
    source_snapshot_id: str = Field(min_length=1)
    calendar_id: str = Field(min_length=1)
    calendar_dates: tuple[date, ...]
    price_basis: Literal["unadjusted"]
    execution_semantics: Literal["daily_close_research_proxy", "observed_execution_window"]
    initial_as_of: datetime
    cash: tuple[NavCash, ...]
    positions: tuple[NavPosition, ...] = ()
    sessions: tuple[NavSession, ...]
    orders: tuple[NavOrder, ...] = ()
    actions: tuple[NavAction, ...] = ()
    cost_policy: CostPolicy
    fill_fraction: Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)] = ONE
    lot_size: Annotated[int, Field(strict=True, gt=0)] = 100
    tax_mode: Literal["pre_tax"] = "pre_tax"

    @model_validator(mode="after")
    def coherent_input(self) -> Self:
        dates = tuple(session.trading_date for session in self.sessions)
        if not dates or dates != tuple(sorted(set(dates))) or dates != self.calendar_dates:
            raise ValueError("sessions must cover the entire ordered fixed calendar")
        buckets = {item.bucket for item in self.cash}
        if not buckets or len(buckets) != len(self.cash):
            raise ValueError("cash buckets must be nonempty and unique")
        if len({item.key for item in self.positions}) != len(self.positions):
            raise ValueError("duplicate initial position")
        if any(item.bucket not in buckets for item in self.positions) or any(
            item.bucket not in buckets for item in self.orders
        ):
            raise ValueError("unknown account bucket")
        if any(item.last_price_at != self.initial_as_of for item in self.positions):
            raise ValueError("initial holdings require an exact initial valuation")
        if len({order.order_id for order in self.orders}) != len(self.orders):
            raise ValueError("duplicate order ID")
        if len({event.event_id for event in self.actions}) != len(self.actions):
            raise ValueError("duplicate corporate-action ID")
        if len({(e.symbol, e.effective_at) for e in self.actions}) != len(self.actions):
            raise ValueError(
                "simultaneous same-symbol corporate actions require explicit sequencing"
            )
        previous = self.initial_as_of
        windows: dict[date, tuple[datetime, datetime]] = {}
        for session in self.sessions:
            if session.execution_at <= previous:
                raise ValueError("execution must follow the preceding valuation")
            if self.execution_semantics == "daily_close_research_proxy" and (
                session.execution_at != session.close_at
                or any(
                    p.execution_price is not None and p.execution_price != p.close_price
                    for p in session.prices
                )
            ):
                raise ValueError("daily-close proxy requires closing execution time and price")
            windows[session.trading_date] = (previous, session.execution_at)
            previous = session.close_at
        for order in self.orders:
            if order.trading_date not in windows:
                raise ValueError("order is outside the evaluation calendar")
            previous, execution = windows[order.trading_date]
            if not previous <= order.decided_at < execution:
                raise ValueError("decision must precede execution and follow prior valuation")
        if any(
            not self.initial_as_of < e.effective_at <= self.sessions[-1].close_at
            for e in self.actions
        ):
            raise ValueError("corporate action is outside the evaluation window")
        return self


class NavReceivable(NavModel):
    reference_id: str
    bucket: str
    amount: Money
    payment_at: datetime
    kind: Literal["sale", "dividend", "cash_conversion", "fractional_cash"]


class NavFill(NavModel):
    order_id: str
    filled_shares: Quantity
    reason: str
    notional: Money
    cost: TransactionCostEstimate


class NavDay(NavModel):
    trading_date: date
    as_of: datetime
    cash: tuple[NavCash, ...]
    positions: tuple[NavPosition, ...]
    receivables: tuple[NavReceivable, ...]
    fills: tuple[NavFill, ...]
    applied_event_ids: tuple[str, ...]
    missing_marks: tuple[str, ...]
    nav: Money | None
    daily_return: Decimal | None
    # Hypothetical valuations, never fills or observed NAV.
    missing_mark_haircut_0_nav: Money
    missing_mark_haircut_50_nav: Money
    missing_mark_haircut_100_nav: Money
    traded_notional: Money
    trading_cost: Money


class NavResult(NavModel):
    schema_version: Literal["daily-nav-result-v1"] = "daily-nav-result-v1"
    input_sha256: str
    research_only: Literal[True] = True
    tax_mode: Literal["pre_tax"] = "pre_tax"
    execution_semantics: str
    initial_nav: Money
    days: tuple[NavDay, ...]
    total_return: Decimal | None
    maximum_drawdown: Money | None
    total_trading_cost: Money
    valuation_complete: bool
    adoption_eligible: Literal[False] = False


def fixed_bps_policy(bps: Decimal) -> CostPolicy:
    """One-way all-in sensitivity, represented once in the slippage component.

    This is an explicit research assumption, not a broker zero-fee assertion or a
    claim that the bps level is realistic. Do not add a second spread adjustment.
    """
    return CostPolicy(
        policy_id=f"research-all-in-{bps}-bps",
        version="research-one-way-v1",
        zero_commission_confirmed=True,
        full_spread_bps=ZERO,
        slippage_bps=bps,
        impact_bps_at_full_adv=ZERO,
    )


def _canonical(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


class _Ledger:
    def __init__(self, request: NavInput):
        self.request = request
        self.cash = {item.bucket: item for item in request.cash}
        self.positions = {item.key: item for item in request.positions if item.shares}
        self.receivables: list[NavReceivable] = []
        self.cost_engine = TransactionCostEngine(request.cost_policy)
        self.events: list[NavAction] = []

    def settle(self, at: datetime) -> None:
        pending = []
        for item in self.receivables:
            if item.payment_at <= at:
                cash = self.cash[item.bucket]
                self.cash[item.bucket] = cash.model_copy(
                    update={"amount": cash.amount + item.amount}
                )
            else:
                pending.append(item)
        self.receivables = pending

    def claim(
        self,
        *,
        reference: str,
        bucket: str,
        amount: Decimal,
        payment_at: datetime,
        kind: Literal["sale", "dividend", "cash_conversion", "fractional_cash"],
    ) -> None:
        self.receivables.append(
            NavReceivable(
                reference_id=reference,
                bucket=bucket,
                amount=amount,
                payment_at=payment_at,
                kind=kind,
            )
        )

    def apply_action(self, event: NavAction) -> None:
        self.settle(event.effective_at)
        for key, position in list(self.positions.items()):
            if position.symbol != event.symbol:
                continue
            if event.kind == "split":
                # Integer arithmetic identifies fractional shares without Decimal rounding.
                shares, remainder = divmod(position.shares * event.numerator, event.denominator)
                ratio = Decimal(event.numerator) / Decimal(event.denominator)
                if remainder:
                    if event.fractional_cash_price is None or event.payment_at is None:
                        raise ValueError("BLOCKED_BY_DATA_CAPABILITY: fractional-share entitlement")
                    self.claim(
                        reference=event.event_id,
                        bucket=position.bucket,
                        amount=Decimal(remainder) / event.denominator * event.fractional_cash_price,
                        payment_at=event.payment_at,
                        kind="fractional_cash",
                    )
                if shares:
                    self.positions[key] = position.model_copy(
                        update={
                            "shares": shares,
                            "unit_cost": position.unit_cost / ratio,
                            "last_price": position.last_price / ratio,
                        }
                    )
                else:
                    del self.positions[key]
            else:
                assert event.cash_per_share is not None and event.payment_at is not None
                self.claim(
                    reference=event.event_id,
                    bucket=position.bucket,
                    amount=position.shares * event.cash_per_share,
                    payment_at=event.payment_at,
                    kind=event.kind,
                )
                if event.kind == "cash_conversion":
                    del self.positions[key]
        self.events.append(event)
        self.settle(event.effective_at)

    def fill(
        self,
        order: NavOrder,
        session: NavSession,
        prices: dict[str, NavPrice],
        capacity: dict[str, int],
    ) -> NavFill:
        zero_cost = TransactionCostEstimate(policy_version=self.request.cost_policy.version)

        def no_fill(reason: str) -> NavFill:
            return NavFill(
                order_id=order.order_id,
                filled_shares=0,
                reason=reason,
                notional=ZERO,
                cost=zero_cost,
            )

        lot = self.request.lot_size
        if order.shares % lot:
            return no_fill("INVALID_LOT")
        if any(
            event.symbol == order.symbol
            and event.kind in {"split", "cash_conversion"}
            and order.decided_at < event.effective_at <= session.execution_at
            for event in self.events
        ):
            return no_fill("CORPORATE_ACTION_AFTER_DECISION")
        if any(e.symbol == order.symbol and e.kind == "cash_conversion" for e in self.events):
            return no_fill("CASH_CONVERSION_COMPLETE")
        quote = prices.get(order.symbol)
        if quote is None or quote.execution_price is None:
            return no_fill("MISSING_EXECUTION_PRICE")
        status = quote.buy_status if order.side is TradeSide.BUY else quote.sell_status
        if status != "tradable":
            return no_fill(status.upper())
        if quote.capacity_shares is None:
            return no_fill("UNKNOWN_CAPACITY")
        key = order.symbol, order.bucket
        position = self.positions.get(key)
        if order.side is TradeSide.SELL and (position is None or order.shares > position.shares):
            return no_fill("INSUFFICIENT_HOLDINGS")
        eligible = min(int(order.shares * self.request.fill_fraction), capacity[order.symbol])
        filled = eligible // lot * lot
        if not filled:
            return no_fill("NO_FILL_OR_CAPACITY")
        price = quote.execution_price
        if price % quote.tick_size:
            return no_fill("INVALID_PRICE_TICK")

        def cost_for(shares: int) -> TransactionCostEstimate:
            return self.cost_engine.estimate(
                shares=shares,
                price=price,
                average_daily_trading_value=quote.average_daily_trading_value,
            )

        cash = self.cash[order.bucket]
        if order.side is TradeSide.BUY:
            # Monotone cost function: binary-search affordable lots, including minimum fees.
            low, high = 0, filled // lot
            while low < high:
                middle = (low + high + 1) // 2
                quantity = middle * lot
                if quantity * price + cost_for(quantity).total <= cash.amount - cash.reserved:
                    low = middle
                else:
                    high = middle - 1
            filled = low * lot
            if not filled:
                return no_fill("INSUFFICIENT_CASH")
        cost = cost_for(filled)
        notional = filled * price
        if order.side is TradeSide.BUY:
            self.cash[order.bucket] = cash.model_copy(
                update={"amount": cash.amount - notional - cost.total}
            )
            previous_shares = position.shares if position else 0
            previous_book = position.unit_cost * previous_shares if position else ZERO
            self.positions[key] = NavPosition(
                symbol=order.symbol,
                bucket=order.bucket,
                shares=previous_shares + filled,
                unit_cost=(previous_book + notional + cost.total) / (previous_shares + filled),
                last_price=price,
                last_price_at=session.execution_at,
            )
        else:
            assert position is not None
            if cost.total > notional:
                return no_fill("COST_EXCEEDS_PROCEEDS")
            remaining = position.shares - filled
            if remaining:
                self.positions[key] = position.model_copy(update={"shares": remaining})
            else:
                del self.positions[key]
            self.claim(
                reference=order.order_id,
                bucket=order.bucket,
                amount=notional - cost.total,
                payment_at=session.sale_cash_available_at,
                kind="sale",
            )
            self.settle(session.execution_at)
        capacity[order.symbol] -= filled
        return NavFill(
            order_id=order.order_id,
            filled_shares=filled,
            reason="FILLED" if filled == order.shares else "PARTIAL_FILL",
            notional=notional,
            cost=cost,
        )

    def mark(
        self,
        session: NavSession,
        fills: tuple[NavFill, ...],
        events: tuple[str, ...],
        previous_nav: Decimal | None,
    ) -> NavDay:
        self.settle(session.close_at)
        prices = {price.symbol: price for price in session.prices}
        missing: set[str] = set()
        known = sum((cash.amount for cash in self.cash.values()), ZERO)
        known += sum((item.amount for item in self.receivables), ZERO)
        stale = ZERO
        for key, position in list(self.positions.items()):
            quote = prices.get(position.symbol)
            if quote is None or quote.close_price is None:
                missing.add(position.symbol)
                stale += position.shares * position.last_price
            else:
                position = position.model_copy(
                    update={"last_price": quote.close_price, "last_price_at": session.close_at}
                )
                self.positions[key] = position
                known += position.shares * quote.close_price
        nav = known if not missing else None
        daily_return = nav / previous_nav - ONE if nav is not None and previous_nav else None
        return NavDay(
            trading_date=session.trading_date,
            as_of=session.close_at,
            cash=tuple(self.cash[key] for key in sorted(self.cash)),
            positions=tuple(self.positions[key] for key in sorted(self.positions)),
            receivables=tuple(self.receivables),
            fills=fills,
            applied_event_ids=events,
            missing_marks=tuple(sorted(missing)),
            nav=nav,
            daily_return=daily_return,
            missing_mark_haircut_0_nav=known + stale,
            missing_mark_haircut_50_nav=known + stale / 2,
            missing_mark_haircut_100_nav=known,
            traded_notional=sum((fill.notional for fill in fills), ZERO),
            trading_cost=sum((fill.cost.total for fill in fills), ZERO),
        )


def evaluate_daily_nav(request: NavInput) -> NavResult:
    """Evaluate explicit day orders; sells precede buys, ID breaks same-side ties.

    Unfilled quantities expire that session and need a fresh decision to retry.
    Settlement timestamps, shared symbol capacity and reserved cash constrain buys.
    """
    # An unrelated caller's Decimal precision must not alter the research ledger.
    with localcontext(Context(prec=28)):
        return _evaluate_daily_nav(request)


def _evaluate_daily_nav(request: NavInput) -> NavResult:
    request = NavInput.model_validate(request.model_dump())
    ledger = _Ledger(request)
    initial = sum((cash.amount for cash in request.cash), ZERO)
    initial += sum((position.shares * position.last_price for position in request.positions), ZERO)
    if initial <= 0:
        raise ValueError("initial NAV must be positive")
    pending_actions = iter(sorted(request.actions, key=lambda e: (e.effective_at, e.event_id)))
    event = next(pending_actions, None)
    previous_nav: Decimal | None = initial
    days: list[NavDay] = []
    orders_by_date: dict[date, list[NavOrder]] = {}
    for order in request.orders:
        orders_by_date.setdefault(order.trading_date, []).append(order)
    peak = initial
    drawdown = ZERO
    for session in request.sessions:
        applied: list[str] = []
        while event is not None and event.effective_at <= session.execution_at:
            ledger.apply_action(event)
            applied.append(event.event_id)
            event = next(pending_actions, None)
        ledger.settle(session.execution_at)
        prices = {price.symbol: price for price in session.prices}
        capacity = {price.symbol: price.capacity_shares or 0 for price in session.prices}
        orders = sorted(
            orders_by_date.get(session.trading_date, []),
            key=lambda o: (o.side is TradeSide.BUY, o.order_id),
        )
        fills = tuple(ledger.fill(order, session, prices, capacity) for order in orders)
        while event is not None and event.effective_at <= session.close_at:
            ledger.apply_action(event)
            applied.append(event.event_id)
            event = next(pending_actions, None)
        day = ledger.mark(session, fills, tuple(applied), previous_nav)
        days.append(day)
        previous_nav = day.nav
        if day.nav is not None:
            peak = max(peak, day.nav)
            drawdown = max(drawdown, ONE - day.nav / peak)
    complete = all(day.nav is not None for day in days)
    return NavResult(
        input_sha256=hashlib.sha256(_canonical(request)).hexdigest(),
        execution_semantics=request.execution_semantics,
        initial_nav=initial,
        days=tuple(days),
        total_return=days[-1].nav / initial - ONE if days[-1].nav is not None else None,
        maximum_drawdown=drawdown if complete else None,
        total_trading_cost=sum((day.trading_cost for day in days), ZERO),
        valuation_complete=complete,
    )


def compare_with_hold(request: NavInput) -> tuple[NavResult, NavResult, tuple[Decimal | None, ...]]:
    strategy = evaluate_daily_nav(request)
    hold = evaluate_daily_nav(request.model_copy(update={"orders": ()}))
    with localcontext(Context(prec=28)):
        differences = tuple(
            a.nav - b.nav if a.nav is not None and b.nav is not None else None
            for a, b in zip(strategy.days, hold.days, strict=True)
        )
    return strategy, hold, differences


def write_nav_evaluation(request: NavInput, root: Path) -> Path:
    """Persist canonical inputs and paired results together; no holdout/data loading."""
    strategy, hold, differences = compare_with_hold(request)
    payload = {
        "input": request.model_dump(mode="json"),
        "strategy": strategy.model_dump(mode="json"),
        "hold": hold.model_dump(mode="json"),
        "daily_nav_difference": [
            str(value) if value is not None else None for value in differences
        ],
        "evaluator_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cost_source_sha256": hashlib.sha256(
            Path(__file__).parents[1].joinpath("decision/costs.py").read_bytes()
        ).hexdigest(),
        "domain_source_sha256": hashlib.sha256(
            Path(__file__).parents[1].joinpath("domain/models.py").read_bytes()
        ).hexdigest(),
        "decimal_precision": 28,
        "pydantic_version": version("pydantic"),
        "limitations": [
            "pre-tax research, no model adoption",
            "source IDs are supplied declarations",
            "requires authenticated market/corporate-action adapter before real-data use",
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
    identity = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{identity}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")
    return path


def load_nav_evaluation(path: Path) -> tuple[NavInput, NavResult, NavResult]:
    """Authenticate a retained receipt, without claiming its sources are genuine."""
    encoded = path.read_bytes()
    if not encoded.endswith(b"\n") or hashlib.sha256(encoded[:-1]).hexdigest() != path.stem:
        raise ValueError("NAV receipt byte hash mismatch")
    payload = json.loads(encoded)
    request = NavInput.model_validate(payload["input"])
    strategy = NavResult.model_validate(payload["strategy"])
    hold = NavResult.model_validate(payload["hold"])
    if strategy.input_sha256 != hashlib.sha256(_canonical(request)).hexdigest():
        raise ValueError("NAV strategy input identity mismatch")
    hold_input = request.model_copy(update={"orders": ()})
    if hold.input_sha256 != hashlib.sha256(_canonical(hold_input)).hexdigest():
        raise ValueError("NAV HOLD input identity mismatch")
    return request, strategy, hold
