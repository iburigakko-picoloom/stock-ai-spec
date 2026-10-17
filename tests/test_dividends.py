"""Synthetic J-Quants notices and independent cash/NAV arithmetic; no live requests."""

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from stock_ai.cli import app
from stock_ai.ml.dividends import (
    DividendNotice,
    DividendPayment,
    DividendRequest,
    DividendShareBasis,
    NoticeAvailability,
    project_dividends,
    write_dividend_projection,
)
from stock_ai.ml.market_nav import PinnedEvidence
from stock_ai.ml.nav import (
    JST,
    NavAction,
    NavCash,
    NavInput,
    NavPosition,
    NavPrice,
    NavSession,
    evaluate_daily_nav,
    fixed_bps_policy,
)


def at(day, hour=10):
    return datetime(2025, 1, day, hour, tzinfo=JST)


def notice(ref="root", **changes):
    return dict(PubDate="2025-01-01", PubTime="09:00", Code="72030", RefNo=ref,
                CARefNo=ref, StatCode="1", FRCode="1", IFCode="2", IFTerm="2025-01",
                DivRate="5", RecDate="2025-01-08", ExDate="2025-01-06",
                PayDate="2025-01-08", **changes)


@pytest.fixture
def request_factory(tmp_path, monkeypatch):
    monkeypatch.setattr("stock_ai.ml.dividends.load_development_feature_selection",
                        lambda _: SimpleNamespace(locked_holdout_start="2025-02-01"))
    evidence_path = tmp_path / "TEST_ONLY-evidence.txt"
    evidence_path.write_text("SYNTHETIC availability and actual payment evidence")
    evidence = PinnedEvidence(path=evidence_path, sha256=hashlib.sha256(
        evidence_path.read_bytes()).hexdigest())

    def make(rows=None, *, availability=True, payments=True, as_of=None):
        rows = [notice()] if rows is None else rows
        source = tmp_path / "source.json"
        source.write_text(json.dumps({"data": rows}), encoding="utf-8")
        return DividendRequest(
            feature_selection_path=tmp_path / "features.json",
            source=PinnedEvidence(
                path=source, sha256=hashlib.sha256(source.read_bytes()).hexdigest()
            ),
            source_publication_start=date(2025, 1, 1), source_publication_end=date(2025, 1, 31),
            received_at=at(31), as_of=as_of or at(9),
            availability=tuple(NoticeAvailability(
                ref_no=row["RefNo"], available_at=DividendNotice.model_validate(row).published_at
                + timedelta(minutes=1), evidence=evidence,
            ) for row in {r["RefNo"]: r for r in rows}.values()) if availability else (),
            payments=tuple(DividendPayment(notice_ref_no=row["RefNo"], payment_at=at(8, 9),
                                            evidence=evidence)
                           for row in {r["RefNo"]: r for r in rows}.values()) if payments else (),
            share_basis=tuple(DividendShareBasis(
                notice_ref_no=row["RefNo"],
                record_date_share_units_equal_entitlement_units=True, evidence=evidence,
            ) for row in {r["RefNo"]: r for r in rows}.values()),
        )
    return make


def rewrite(request, **changes):
    value = json.loads(request.source.path.read_bytes())
    value.update(changes)
    request.source.path.write_text(json.dumps(value), encoding="utf-8")
    source = request.source.model_copy(update={
        "sha256": hashlib.sha256(request.source.path.read_bytes()).hexdigest()
    })
    return request.model_copy(update={"source": source})


def test_decided_dividend_replays_cash_and_ex_date_nav_exactly_once(request_factory, tmp_path):
    request = request_factory()
    result = project_dividends(request)
    assert result["status"] == "COMPLETE" and len(result["actions"]) == 1
    assert result["corporate_action_coverage_verified"] is False
    action = NavAction.model_validate(result["actions"][0])
    assert action.cash_per_share == 5 and action.effective_at == at(6, 0)
    sessions = tuple(NavSession(
        trading_date=at(i).date(), execution_at=at(i, 12), close_at=at(i, 15),
        sale_cash_available_at=at(i, 15), prices=(NavPrice(
            symbol="7203", execution_price=None, close_price=D(95), buy_status="suspended",
            sell_status="suspended", capacity_shares=0, tick_size=D(1), source_id="TEST_ONLY",
        ),),
    ) for i in (6, 7, 8))
    data = NavInput(
        data_mode="fixture", source_snapshot_id="TEST_ONLY", calendar_id="TEST_ONLY",
        calendar_dates=tuple(s.trading_date for s in sessions), price_basis="unadjusted",
        execution_semantics="observed_execution_window", initial_as_of=at(3, 15),
        cash=(NavCash(bucket="cash", amount=D(0)),), positions=(NavPosition(
            symbol="7203", bucket="cash", shares=100, unit_cost=D(100),
            last_price=D(100), last_price_at=at(3, 15),
        ),), sessions=sessions, actions=(action,), cost_policy=fixed_bps_policy(D(20)),
    )
    nav = evaluate_daily_nav(data)
    assert [d.nav for d in nav.days] == [10000, 10000, 10000]
    assert [d.cash[0].amount for d in nav.days] == [0, 0, 500]
    assert [sum(r.amount for r in d.receivables) for d in nav.days] == [500, 500, 0]
    assert json.loads(write_dividend_projection(request, tmp_path / "out").read_bytes())[
        "status"] == "COMPLETE"


def test_correction_root_order_is_publication_not_lexical_reference(request_factory):
    rows = [notice("z"), {**notice("0"), "CARefNo": "z", "StatCode": "2",
                           "PubDate": "2025-01-02", "DivRate": "7"}]
    result = project_dividends(request_factory(rows))
    assert result["status"] == "COMPLETE"
    assert result["actions"][0]["cash_per_share"] == "7"
    assert result["actions"][0]["event_id"].endswith(":0")


def test_future_correction_cannot_change_earlier_projection(request_factory):
    rows = [notice(), {**notice("later"), "CARefNo": "root", "StatCode": "2",
                      "PubDate": "2025-01-10", "DivRate": "999"}]
    request = request_factory(rows, as_of=at(9))
    result = project_dividends(request)
    assert result["status"] == "COMPLETE"
    assert result["actions"][0]["cash_per_share"] == "5"
    late = project_dividends(request.model_copy(update={"as_of": at(11)}))
    assert late["status"] == "BLOCKED" and late["actions"] == []
    assert "later:TERMS_NOT_KNOWN_AT_ENTITLEMENT" in late["blockers"]


def test_known_later_availability_keeps_the_previous_notice(request_factory):
    rows = [notice(), {**notice("later"), "CARefNo": "root", "StatCode": "2",
                      "PubDate": "2025-01-02", "DivRate": "999"}]
    request = request_factory(rows)
    availability = (request.availability[0], request.availability[1].model_copy(update={
        "available_at": at(10)
    }))
    result = project_dividends(request.model_copy(update={"availability": availability}))
    assert result["actions"][0]["cash_per_share"] == "5"


def test_deletion_and_fresh_series_do_not_double_count(request_factory):
    rows = [notice(), {**notice("delete"), "CARefNo": "root", "StatCode": "3",
                       "PubDate": "2025-01-02"},
            {**notice("fresh"), "PubDate": "2025-01-03", "DivRate": "8"}]
    result = project_dividends(request_factory(rows))
    assert result["status"] == "COMPLETE" and result["deleted_series"] == ["root"]
    assert len(result["actions"]) == 1 and result["actions"][0]["cash_per_share"] == "8"


@pytest.mark.parametrize("change", [
    {"StatCode": "3"},
    {"StatCode": "2", "ExDate": "2025-01-08", "RecDate": "2025-01-10"},
])
def test_late_deletion_or_ex_date_change_cannot_erase_original_entitlement(request_factory, change):
    rows = [notice(), {**notice("late"), "CARefNo": "root", "PubDate": "2025-01-07",
                       **change}]
    result = project_dividends(request_factory(rows))
    assert result["status"] == "BLOCKED" and result["actions"] == []
    assert "root:POST_ENTITLEMENT_REVISION_REQUIRES_LEDGER_UPDATE" in result["blockers"]


def test_forecast_and_final_are_distinct_and_breakdowns_are_not_added(request_factory):
    rows = [{**notice("forecast"), "FRCode": "2", "DivRate": "999"},
            {**notice("final"), "CommSpecCode": "3", "CommDivRate": "1", "SpecDivRate": "2"}]
    result = project_dividends(request_factory(rows))
    assert result["status"] == "COMPLETE"
    assert result["ignored_forecast_ids"] == ["forecast"]
    assert len(result["actions"]) == 1 and result["actions"][0]["cash_per_share"] == "5"


@pytest.mark.parametrize("value", ["-", "", None])
def test_unknown_amount_never_becomes_zero(request_factory, value):
    result = project_dividends(request_factory([{**notice(), "DivRate": value}]))
    assert result["status"] == "BLOCKED" and result["actions"] == []
    assert "root:INCOMPLETE_DIVIDEND_TERMS" in result["blockers"]


def test_zero_is_an_explicit_amount(request_factory):
    result = project_dividends(request_factory([{**notice(), "DivRate": "0"}]))
    assert result["status"] == "COMPLETE" and result["actions"][0]["cash_per_share"] == "0"


def test_record_date_amount_cannot_use_unverified_pre_split_share_units(request_factory):
    request = request_factory().model_copy(update={"share_basis": ()})
    result = project_dividends(request)
    assert result["actions"] == []
    assert "root:ENTITLEMENT_SHARE_BASIS_NOT_PROVEN" in result["blockers"]


@pytest.mark.parametrize("availability,payments,reason", [
    (False, True, "NOTICE_AVAILABILITY_NOT_PROVEN"),
    (True, False, "ACTUAL_PAYMENT_TIME_NOT_PROVEN"),
])
def test_publication_and_scheduled_payment_never_supply_missing_evidence(
    request_factory, availability, payments, reason,
):
    result = project_dividends(request_factory(availability=availability, payments=payments))
    assert result["status"] == "BLOCKED" and result["actions"] == []
    assert any(reason in issue for issue in result["blockers"])


def test_orphan_and_ambiguous_notice_order_block(request_factory):
    orphan = {**notice("correction"), "CARefNo": "missing", "StatCode": "2"}
    result = project_dividends(request_factory([orphan]))
    assert "missing:MISSING_OR_LATE_CHAIN_ROOT" in result["blockers"]
    same_time = {**notice("correction"), "CARefNo": "root", "StatCode": "2"}
    result = project_dividends(request_factory([notice(), same_time]))
    assert "root:AMBIGUOUS_PUBLICATION_ORDER" in result["blockers"]


def test_duplicates_and_conflicting_reference(request_factory):
    result = project_dividends(request_factory([notice(), notice()]))
    assert result["unique_notices"] == 1 and len(result["actions"]) == 1
    with pytest.raises(ValueError, match="conflicting dividend"):
        project_dividends(request_factory([notice(), {**notice(), "DivRate": "9"}]))


@pytest.mark.parametrize("change,reason", [
    ({"DistAmt": "10"}, "UNSUPPORTED_CAPITAL_DISTRIBUTION"),
    ({"Code": "72031"}, "NONSTANDARD_SECURITY_CODE"),
    ({"ExDate": "2025-01-09"}, "INVALID_ENTITLEMENT_DATES"),
])
def test_unsupported_or_inconsistent_terms_block(request_factory, change, reason):
    result = project_dividends(request_factory([{**notice(), **change}]))
    assert result["actions"] == [] and any(reason in issue for issue in result["blockers"])


def test_future_entitlement_is_pending_without_future_selection(request_factory):
    result = project_dividends(request_factory(as_of=at(2)))
    assert result["status"] == "COMPLETE" and result["actions"] == []
    assert result["pending_entitlement_ids"] == ["root"]


def test_boundary_rejection_precedes_source_open(request_factory):
    request = request_factory()
    request.source.path.unlink()
    with pytest.raises(ValueError, match="locked holdout"):
        project_dividends(request.model_copy(update={"source_publication_end": date(2025, 2, 1)}))


def test_pagination_tamper_and_unknown_provider_fields(request_factory):
    request = request_factory()
    with pytest.raises(ValueError, match="pagination is incomplete"):
        project_dividends(rewrite(request, pagination_key="more"))
    request = request_factory()
    request.source.path.write_text("changed")
    with pytest.raises(ValueError, match="evidence bytes changed"):
        project_dividends(request)
    with pytest.raises(ValueError, match="Extra inputs"):
        project_dividends(request_factory([{**notice(), "NewField": "unknown"}]))


def test_cli_persists_blocked_projection(request_factory, tmp_path):
    request = request_factory(availability=False)
    path = tmp_path / "input.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    result = CliRunner().invoke(app, ["research", "project-dividends", "--input", str(path),
                                     "--output-root", str(tmp_path / "out")])
    assert result.exit_code == 2 and '"status": "BLOCKED"' in result.stdout
    assert len(list((tmp_path / "out").glob("*.json"))) == 1
