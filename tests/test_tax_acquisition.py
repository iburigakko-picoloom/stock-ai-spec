from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest

from stock_ai.domain import TradeSide
from stock_ai.ml.tax_acquisition import (
    TaxAcquisitionDay,
    TaxAcquisitionFill,
    TaxBookPosition,
    account_specified_tax_day,
)

JST = ZoneInfo("Asia/Tokyo")
DAY = date(2026, 1, 6)
OPEN = datetime(2026, 1, 5, 15, 30, tzinfo=JST)
KNOWN = datetime(2026, 1, 6, 17, tzinfo=JST)


def fill(
    sequence: int,
    side: TradeSide,
    shares: int,
    price: str,
    fee: str = "0",
    *,
    bucket: str = "taxable",
    symbol: str = "A",
) -> TaxAcquisitionFill:
    at = datetime(2026, 1, 6, 10, tzinfo=JST) + timedelta(minutes=sequence)
    return TaxAcquisitionFill(
        f"fill-{sequence}",
        sequence,
        at,
        at + timedelta(seconds=1),
        bucket,
        symbol,
        side,
        shares,
        Decimal(price),
        Decimal(fee),
    )


def run(
    positions: tuple[TaxBookPosition, ...],
    fills: tuple[TaxAcquisitionFill, ...],
    *,
    opening_as_of: datetime = OPEN,
    opening_available_at: datetime = OPEN,
    known_at: datetime = KNOWN,
    source: str = "synthetic:daily-tax-book",
) -> TaxAcquisitionDay:
    return account_specified_tax_day(
        trading_date=DAY,
        opening_as_of=opening_as_of,
        opening_available_at=opening_available_at,
        known_at=known_at,
        opening_positions=positions,
        fills=fills,
        source_snapshot_id=source,
    )


def test_same_day_repurchase_uses_the_complete_buy_pool_without_changing_inputs() -> None:
    opening = TaxBookPosition("taxable", "A", 300, Fraction(210000))
    actual = (fill(0, TradeSide.SELL, 200, "900"), fill(1, TradeSide.BUY, 100, "800"))
    result = run((opening,), actual)
    assert result.positions == (TaxBookPosition("taxable", "A", 200, Fraction(145000)),)
    assert result.positions[0].unit_cost == 725
    assert result.sales[0].allocated_basis == 145000
    assert result.sales[0].realized_pnl == 35000
    assert result.sales[0].proceeds == 180000
    assert result.input_fill_ids == ("fill-0", "fill-1")
    assert opening.book_cost == 210000 and actual[0].filled_shares == 200
    assert result.known_at == KNOWN and result.source_snapshot_id == "synthetic:daily-tax-book"
    assert result.research_only and not result.adoption_eligible
    assert result.method == "specified-account-daily-pool-exact-v1"


@pytest.mark.parametrize("buy_first", [True, False])
def test_daily_tax_basis_is_independent_of_valid_execution_order_and_includes_fees(
    buy_first: bool,
) -> None:
    opening = (TaxBookPosition("taxable", "A", 100, Fraction(100000)),)
    buy = fill(0 if buy_first else 1, TradeSide.BUY, 100, "1200", "200")
    sale = fill(1 if buy_first else 0, TradeSide.SELL, 100, "1300", "100")
    result = run(opening, (sale, buy))
    assert result.positions[0].shares == 100
    assert result.positions[0].book_cost == 110100
    assert result.positions[0].unit_cost == 1101
    assert result.sales[0].allocated_basis == 110100
    assert result.sales[0].realized_pnl == 19800


def test_fractional_basis_is_conserved_exactly_and_does_not_use_decimal_context() -> None:
    opening = (TaxBookPosition("taxable", "A", 3, Fraction(10001, 100)),)
    actual = (fill(0, TradeSide.SELL, 1, "40", "0.01"), fill(1, TradeSide.SELL, 1, "45", "0.02"))
    expected = run(opening, actual)
    with localcontext() as context:
        context.prec = 3
        assert run(opening, tuple(reversed(actual))) == expected
    assert expected.positions[0].book_cost == Fraction(10001, 300)
    assert expected.sales[0].realized_pnl == Fraction(499, 75)
    assert expected.sales[1].realized_pnl == Fraction(3493, 300)
    assert sum((s.allocated_basis for s in expected.sales), Fraction()) + (
        expected.positions[0].book_cost
    ) == Fraction(10001, 100)


def test_account_and_symbol_books_remain_separate_and_losses_are_signed() -> None:
    opening = (
        TaxBookPosition("first", "A", 100, Fraction(100000)),
        TaxBookPosition("second", "A", 100, Fraction(200000)),
        TaxBookPosition("first", "B", 37, Fraction(3700)),
    )
    result = run(
        opening,
        (
            fill(0, TradeSide.BUY, 100, "1000", "200", bucket="first"),
            fill(1, TradeSide.SELL, 100, "1100", bucket="first"),
            fill(2, TradeSide.SELL, 100, "1800", bucket="second"),
        ),
    )
    assert [s.realized_pnl for s in result.sales] == [9900, -20000]
    assert result.positions == (
        TaxBookPosition("first", "A", 100, Fraction(100100)),
        TaxBookPosition("first", "B", 37, Fraction(3700)),
    )


def test_all_sold_after_repurchase_preserves_total_basis_and_no_phantom_position() -> None:
    result = run(
        (TaxBookPosition("taxable", "A", 100, Fraction(100000)),),
        (
            fill(0, TradeSide.SELL, 100, "1200"),
            fill(1, TradeSide.BUY, 100, "1100"),
            fill(2, TradeSide.SELL, 100, "1150"),
        ),
    )
    assert result.positions == ()
    assert [s.realized_pnl for s in result.sales] == [15000, 10000]
    assert sum(s.allocated_basis for s in result.sales) == 210000


def test_empty_day_and_purchases_only_preserve_the_declared_tax_book() -> None:
    opening = (TaxBookPosition("taxable", "A", 137, Fraction(12345)),)
    assert run(opening, ()).positions == opening
    assert run((), ()).positions == ()
    bought = run((), (fill(0, TradeSide.BUY, 100, "1000", "50"),))
    assert bought.positions[0].book_cost == 100050
    assert bought.positions[0].unit_cost == Fraction(2001, 2)
    assert bought.sales == ()


def test_daily_result_can_seed_the_next_day_without_losing_basis() -> None:
    first = run(
        (TaxBookPosition("taxable", "A", 300, Fraction(210000)),),
        (
            fill(0, TradeSide.SELL, 200, "900"),
            fill(1, TradeSide.BUY, 100, "800"),
        ),
    )
    next_day = DAY + timedelta(days=1)
    next_at = datetime(2026, 1, 7, 10, tzinfo=JST)
    second = account_specified_tax_day(
        trading_date=next_day,
        opening_as_of=KNOWN,
        opening_available_at=KNOWN,
        known_at=next_at + timedelta(hours=7),
        opening_positions=first.positions,
        fills=(
            replace(
                fill(0, TradeSide.SELL, 100, "1000"), executed_at=next_at, available_at=next_at
            ),
        ),
        source_snapshot_id="synthetic:next-day",
    )
    assert second.sales[0].allocated_basis == 72500
    assert second.sales[0].realized_pnl == 27500
    assert second.positions[0].book_cost == 72500


def test_utc_and_jst_instants_match_and_results_are_immutable() -> None:
    actual = fill(0, TradeSide.BUY, 100, "1000")
    expected = run((), (actual,))
    utc = replace(
        actual,
        executed_at=actual.executed_at.astimezone(UTC),
        available_at=actual.available_at.astimezone(UTC),
    )
    assert (
        run(
            (),
            (utc,),
            opening_as_of=OPEN.astimezone(UTC),
            opening_available_at=OPEN.astimezone(UTC),
            known_at=KNOWN.astimezone(UTC),
        )
        == expected
    )
    with pytest.raises(FrozenInstanceError):
        expected.positions[0].shares = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"filled_shares": 0},
        {"filled_shares": -1},
        {"filled_shares": True},
        {"execution_sequence": -1},
        {"execution_sequence": False},
        {"price": Decimal("0")},
        {"price": Decimal("NaN")},
        {"price": Decimal("Infinity")},
        {"price": 1000},
        {"deductible_cost": Decimal("-1")},
        {"deductible_cost": Decimal("NaN")},
        {"fill_id": ""},
        {"account_bucket_id": " "},
        {"symbol": ""},
        {"side": "BUY"},
    ],
)
def test_invalid_fill_input_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        run((), (replace(fill(0, TradeSide.BUY, 100, "1000"), **changes),))


@pytest.mark.parametrize(
    "changes",
    [
        {"shares": 0},
        {"shares": True},
        {"book_cost": Fraction(-1)},
        {"book_cost": Decimal("100")},
        {"symbol": ""},
        {"account_bucket_id": ""},
    ],
)
def test_invalid_opening_book_is_rejected(changes: dict[str, object]) -> None:
    position = TaxBookPosition("taxable", "A", 100, Fraction(100000))
    with pytest.raises(ValueError):
        run((replace(position, **changes),), ())


def test_duplicate_ids_sequences_and_opening_keys_are_rejected() -> None:
    actual = fill(0, TradeSide.BUY, 100, "1000")
    for other in (replace(actual, execution_sequence=1), replace(actual, fill_id="another")):
        with pytest.raises(ValueError, match="duplicate"):
            run((), (actual, other))
    position = TaxBookPosition("taxable", "A", 100, Fraction(100000))
    with pytest.raises(ValueError, match="duplicate"):
        run((position, position), ())


def test_tax_pool_never_reorders_unheld_sales_or_inconsistent_execution_times() -> None:
    with pytest.raises(ValueError, match="before they are held"):
        run((), (fill(0, TradeSide.SELL, 100, "1000"), fill(1, TradeSide.BUY, 100, "900")))
    later = fill(0, TradeSide.BUY, 100, "1000")
    earlier = replace(
        fill(1, TradeSide.SELL, 100, "1100"), executed_at=later.executed_at - timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="chronological"):
        run((), (later, earlier))


def test_unavailable_fills_and_naive_or_incomplete_day_snapshots_are_rejected() -> None:
    actual = fill(0, TradeSide.BUY, 100, "1000")
    with pytest.raises(ValueError, match="known_at"):
        run((), (replace(actual, available_at=KNOWN + timedelta(seconds=1)),))
    with pytest.raises(ValueError, match="availability"):
        run((), (replace(actual, available_at=actual.executed_at - timedelta(seconds=1)),))
    with pytest.raises(ValueError, match="timezone-aware"):
        run((), (replace(actual, executed_at=actual.executed_at.replace(tzinfo=None)),))
    with pytest.raises(ValueError, match="precede"):
        run((), (actual,), opening_as_of=actual.executed_at - timedelta(minutes=1))
    with pytest.raises(ValueError, match="opening availability"):
        run((), (), opening_available_at=KNOWN + timedelta(seconds=1))
    with pytest.raises(ValueError, match="non-empty"):
        run((), (), source="")


def test_trading_day_is_checked_in_jst_rather_than_utc() -> None:
    next_jst_day = datetime(2026, 1, 6, 16, tzinfo=UTC)
    actual = replace(
        fill(0, TradeSide.BUY, 100, "1000"), executed_at=next_jst_day, available_at=next_jst_day
    )
    with pytest.raises(ValueError, match="JST trading date"):
        run((), (actual,), known_at=next_jst_day + timedelta(hours=1))


@pytest.mark.parametrize("invalid", ["datetime_day", "before_day", "naive_known", "early_open"])
def test_invalid_day_headers_cannot_backdate_tax_accounting(invalid: str) -> None:
    arguments = {
        "trading_date": KNOWN if invalid == "datetime_day" else DAY,
        "opening_as_of": OPEN,
        "opening_available_at": OPEN - timedelta(seconds=1) if invalid == "early_open" else OPEN,
        "known_at": (
            OPEN
            if invalid == "before_day"
            else KNOWN.replace(tzinfo=None)
            if invalid == "naive_known"
            else KNOWN
        ),
        "opening_positions": (),
        "fills": (),
        "source_snapshot_id": "synthetic:bad-header",
    }
    with pytest.raises(ValueError):
        account_specified_tax_day(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", ["position", "fill"])
def test_unsupported_record_types_are_rejected_before_bookkeeping(invalid: str) -> None:
    with pytest.raises(ValueError, match="unsupported type"):
        run(
            (object(),) if invalid == "position" else (),  # type: ignore[arg-type]
            (object(),) if invalid == "fill" else (),
        )  # type: ignore[arg-type]
