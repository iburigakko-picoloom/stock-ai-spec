"""Exact specified-account daily acquisition basis for research accounting.

Inputs are day-opening tax books and actual fills, all already expressed in JPY.
The daily buy pool affects tax basis; it never reorders execution or moves cash.
Fraction retains sub-yen cost exactly. Broker rounding, tax recognition, payment
and eligibility belong to the subsequent personal-tax NAV integration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal
from zoneinfo import ZoneInfo

from stock_ai.domain import TradeSide

JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class TaxBookPosition:
    account_bucket_id: str
    symbol: str
    shares: int
    book_cost: Fraction

    @property
    def key(self) -> tuple[str, str]:
        return self.account_bucket_id, self.symbol

    @property
    def unit_cost(self) -> Fraction:
        return self.book_cost / self.shares


@dataclass(frozen=True)
class TaxAcquisitionFill:
    fill_id: str
    execution_sequence: int
    executed_at: datetime
    available_at: datetime
    account_bucket_id: str
    symbol: str
    side: TradeSide
    filled_shares: int
    price: Decimal
    deductible_cost: Decimal

    @property
    def key(self) -> tuple[str, str]:
        return self.account_bucket_id, self.symbol


@dataclass(frozen=True)
class RealizedTaxSale:
    fill_id: str
    account_bucket_id: str
    symbol: str
    shares: int
    proceeds: Fraction
    deductible_cost: Fraction
    allocated_basis: Fraction
    realized_pnl: Fraction


@dataclass(frozen=True)
class TaxAcquisitionDay:
    trading_date: date
    opening_as_of: datetime
    opening_available_at: datetime
    known_at: datetime
    source_snapshot_id: str
    input_fill_ids: tuple[str, ...]
    positions: tuple[TaxBookPosition, ...]
    sales: tuple[RealizedTaxSale, ...]

    @property
    def method(self) -> Literal["specified-account-daily-pool-exact-v1"]:
        return "specified-account-daily-pool-exact-v1"

    @property
    def research_only(self) -> Literal[True]:
        return True

    @property
    def adoption_eligible(self) -> Literal[False]:
        return False


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("tax timestamps must be timezone-aware")


def _label(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tax accounting IDs must be non-empty strings")


def _integer(value: int, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError("tax quantities and sequences must be integers in range")


def _money(value: Decimal, *, positive: bool = False) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError("tax prices/costs must be finite Decimal amounts in range")


def account_specified_tax_day(
    *,
    trading_date: date,
    opening_as_of: datetime,
    opening_available_at: datetime,
    known_at: datetime,
    opening_positions: Sequence[TaxBookPosition],
    fills: Sequence[TaxAcquisitionFill],
    source_snapshot_id: str,
) -> TaxAcquisitionDay:
    """Pool actual daily purchases, then allocate basis without monetary rounding.

    A later same-day purchase can alter a sale's final tax basis. The result is
    available only at known_at, never at an earlier decision. Execution sequence
    still prohibits selling unheld shares; the NAV ledger separately checks cash.
    Snapshot completeness and broker-specific policy are the caller's contract.
    """
    if type(trading_date) is not date:
        raise ValueError("tax trading_date must be a date")
    for at in (opening_as_of, opening_available_at, known_at):
        _aware(at)
    if opening_as_of.astimezone(JST).date() >= trading_date:
        raise ValueError("tax opening snapshot must precede the trading date in JST")
    if not opening_as_of <= opening_available_at <= known_at:
        raise ValueError("tax opening availability is outside its known time window")
    if known_at.astimezone(JST).date() < trading_date:
        raise ValueError("tax day cannot be finalized before its JST date")
    _label(source_snapshot_id)
    opening = tuple(opening_positions)
    actual = tuple(fills)
    quantities: dict[tuple[str, str], int] = {}
    pool_shares: dict[tuple[str, str], int] = {}
    pool_cost: dict[tuple[str, str], Fraction] = {}
    for position in opening:
        if not isinstance(position, TaxBookPosition):
            raise ValueError("tax opening position has an unsupported type")
        _label(position.account_bucket_id)
        _label(position.symbol)
        _integer(position.shares, 1)
        if not isinstance(position.book_cost, Fraction) or position.book_cost < 0:
            raise ValueError("tax opening book cost must be a nonnegative Fraction")
        if position.key in quantities:
            raise ValueError("duplicate opening tax position")
        quantities[position.key] = pool_shares[position.key] = position.shares
        pool_cost[position.key] = position.book_cost
    identities: set[str] = set()
    sequences: set[int] = set()
    for fill in actual:
        if not isinstance(fill, TaxAcquisitionFill):
            raise ValueError("tax fill has an unsupported type")
        for value in (fill.fill_id, fill.account_bucket_id, fill.symbol):
            _label(value)
        _integer(fill.execution_sequence, 0)
        _integer(fill.filled_shares, 1)
        _money(fill.price, positive=True)
        _money(fill.deductible_cost)
        if not isinstance(fill.side, TradeSide):
            raise ValueError("tax fill side must be an explicit TradeSide")
        _aware(fill.executed_at)
        _aware(fill.available_at)
        if fill.executed_at.astimezone(JST).date() != trading_date:
            raise ValueError("tax fills must belong to the requested JST trading date")
        if not fill.executed_at <= fill.available_at <= known_at:
            raise ValueError("tax fill availability is before execution or after known_at")
        if fill.fill_id in identities or fill.execution_sequence in sequences:
            raise ValueError("duplicate tax fill ID or sequence")
        identities.add(fill.fill_id)
        sequences.add(fill.execution_sequence)
    ordered = tuple(sorted(actual, key=lambda item: item.execution_sequence))
    previous = opening_as_of
    for fill in ordered:
        if fill.executed_at < previous:
            raise ValueError("tax execution sequence is not chronological")
        previous = fill.executed_at
        key = fill.key
        held = quantities.get(key, 0)
        if fill.side is TradeSide.BUY:
            quantities[key] = held + fill.filled_shares
            pool_shares[key] = pool_shares.get(key, 0) + fill.filled_shares
            pool_cost[key] = pool_cost.get(key, Fraction()) + (
                Fraction(fill.price) * fill.filled_shares + Fraction(fill.deductible_cost)
            )
        else:
            if fill.filled_shares > held:
                raise ValueError("tax accounting cannot sell shares before they are held")
            quantities[key] = held - fill.filled_shares
    sales: list[RealizedTaxSale] = []
    sold_basis: dict[tuple[str, str], Fraction] = {}
    for fill in ordered:
        if fill.side is not TradeSide.SELL:
            continue
        basis = pool_cost[fill.key] * Fraction(fill.filled_shares, pool_shares[fill.key])
        proceeds = Fraction(fill.price) * fill.filled_shares
        cost = Fraction(fill.deductible_cost)
        sales.append(
            RealizedTaxSale(
                fill.fill_id,
                fill.account_bucket_id,
                fill.symbol,
                fill.filled_shares,
                proceeds,
                cost,
                basis,
                proceeds - cost - basis,
            )
        )
        sold_basis[fill.key] = sold_basis.get(fill.key, Fraction()) + basis
    positions: list[TaxBookPosition] = []
    for key in sorted(pool_shares):
        remaining = quantities[key]
        book = pool_cost[key] * Fraction(remaining, pool_shares[key])
        if book + sold_basis.get(key, Fraction()) != pool_cost[key]:
            raise ArithmeticError("tax acquisition-basis conservation failed")
        if remaining:
            positions.append(TaxBookPosition(key[0], key[1], remaining, book))
    return TaxAcquisitionDay(
        trading_date,
        opening_as_of,
        opening_available_at,
        known_at,
        source_snapshot_id,
        tuple(fill.fill_id for fill in ordered),
        tuple(positions),
        tuple(sales),
    )
