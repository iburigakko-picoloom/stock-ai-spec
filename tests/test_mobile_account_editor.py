import copy
from datetime import timedelta
from decimal import Decimal

import pytest
from mobile.python import account_editor, personal, runtime

from stock_ai.operations.store import OperationalConflictError, OperationalIntegrityError
from tests.test_mobile_personal import ACCOUNT, NOW, preview, setup
from tests.test_mobile_runtime import run


@pytest.fixture()
def device(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "STATE", tmp_path / "state")
    runtime.initialize()
    return runtime


def prepared(device):
    store, _ = setup(device)
    value = preview(device, store)
    personal.confirm_initial(store, device.STATE / "mobile.sqlite3", value["preview_id"], True, NOW)
    current = account_editor.view(store)
    request = {
        "base_ledger_id": current["ledger"]["portfolio_id"],
        "base_revision_id": current["profile"]["revision_id"],
        "base_settings_id": current["settings"]["revision_id"],
        "as_of": (NOW + timedelta(minutes=1)).isoformat(),
        "group": "cash",
        "changes": [{"account_bucket_id": ACCOUNT, "total": "1040000", "buying_power": "600000"}],
    }
    return store, request


def test_cash_correction_appends_shared_current_state_preserving_history(device):
    store, request = prepared(device)
    old = store.latest_portfolio()
    old_input = store.latest_manual_portfolio()
    value = account_editor.edit(store, request, NOW + timedelta(minutes=1))
    assert store.latest_portfolio() == old  # Preview never changes balances.
    assert value["after"]["cash"][0]["reserved_cash"] == "440000"
    result = account_editor.edit(store, request, NOW + timedelta(minutes=1), confirm=True)
    latest = store.latest_portfolio()
    assert latest.cash[0].available_cash == Decimal("1040000")
    assert latest.cash[0].deployable_cash == Decimal("600000")
    home = run(device, "GET", "/api/v1/home")["body"]["portfolio"]
    assert (home["cashValue"], home["reservedCash"], home["buyingPower"]) == (
        "1040000",
        "440000",
        "600000",
    )
    assert latest.applied_execution_ids == old.applied_execution_ids
    assert store.latest_manual_portfolio().portfolio.accounts[0].available_cash_yen == "1040000"
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM portfolio_states").fetchone()[0] == 2
        assert db.execute(
            "SELECT payload FROM manual_portfolio_imports WHERE export_sha256=?",
            (old_input.export_sha256,),
        ).fetchone()[0] == personal.canonical(old_input.model_dump(mode="json"))
    assert account_editor.edit(store, request, NOW + timedelta(minutes=2), confirm=True)[
        "already_confirmed"
    ]
    assert store.latest_portfolio().portfolio_id == result["portfolio_id"]
    device.initialize(device.export_state())
    assert device._app.state.store.latest_portfolio() == latest


def test_correction_note_is_previewed_appended_once_restored_and_hash_checked(device):
    store, request = prepared(device)
    request["record"] = {"date": "2026-10-19", "reason": "SBI残高との照合", "kind": "correction"}
    before = store.latest_portfolio()
    account_editor.edit(store, request, NOW + timedelta(minutes=1))
    assert store.latest_portfolio() == before
    result = account_editor.edit(store, request, NOW + timedelta(minutes=1), confirm=True)
    assert store.portfolio_edit_record(result["portfolio_id"]) == request["record"]
    assert account_editor.edit(store, request, NOW + timedelta(minutes=2), confirm=True)[
        "already_confirmed"
    ]
    device.initialize(device.export_state())
    restored = device._app.state.store
    assert restored.portfolio_edit_record(result["portfolio_id"]) == request["record"]
    with restored._connect() as db:
        db.execute(
            "UPDATE operational_metadata SET value=? WHERE key=?",
            (
                '{"payload":"changed","sha256":"bad"}',
                "account_edit_record:" + result["portfolio_id"],
            ),
        )
        db.commit()
    with pytest.raises(OperationalIntegrityError):
        restored.portfolio_edit_record(result["portfolio_id"])


def test_deposit_direction_must_match_the_exact_cash_difference(device):
    store, request = prepared(device)
    before = store.latest_portfolio()
    request["record"] = {"date": "2026-10-19", "reason": "入金", "kind": "deposit"}
    request["changes"][0].update(
        total=str(before.cash[0].available_cash - Decimal("0.1")),
        buying_power=str(before.cash[0].deployable_cash - Decimal("0.1")),
    )
    with pytest.raises(ValueError, match="種別"):
        account_editor.edit(store, request, NOW + timedelta(minutes=1), confirm=True)
    assert store.latest_portfolio() == before
    request["changes"][0].update(
        total=str(before.cash[0].available_cash + Decimal("0.1")),
        buying_power=str(before.cash[0].deployable_cash + Decimal("0.1")),
    )
    account_editor.edit(store, request, NOW + timedelta(minutes=1), confirm=True)
    assert store.latest_portfolio().cash[0].available_cash - before.cash[
        0
    ].available_cash == Decimal("0.1")
    assert store.latest_portfolio().cash[0].reserved_cash == before.cash[0].reserved_cash


def test_holdings_changes_use_tax_bucket_and_do_not_change_cash(device):
    store, request = prepared(device)
    cash = store.latest_portfolio().cash
    request.update(
        group="holdings",
        changes=[
            {
                "symbol": "7203",
                "account_bucket_id": "new:nisa",
                "shares": 100,
                "average_acquisition_price": "1000",
                "market_price": "1200",
            }
        ],
    )
    account_editor.edit(store, request, NOW + timedelta(minutes=1), confirm=True)
    latest = store.latest_portfolio()
    assert latest.cash[0] == cash[0]
    holding = latest.positions[0]
    bucket = next(x for x in latest.account_buckets if x.bucket_id == holding.account_bucket_id)
    assert bucket.account_type == "nisa"
    assert bucket.account_id == latest.account_buckets[0].account_id
    assert len(latest.accounts) == 1
    assert store.latest_manual_portfolio().portfolio.holdings[0].account_id == bucket.bucket_id
    assert (
        personal.read_settings(store)["settings"]["accounts"][-1]["nisa_annual_capacity_user_input"]
        is None
    )


def test_invalid_or_stale_corrections_leave_every_record_unchanged(device):
    store, request = prepared(device)
    before = store.latest_portfolio()
    invalid = copy.deepcopy(request)
    invalid["changes"][0]["buying_power"] = "1040001"
    with pytest.raises(ValueError):
        account_editor.edit(store, invalid, NOW + timedelta(minutes=1), confirm=True)
    invalid = {**request, "base_revision_id": "0" * 64}
    with pytest.raises(OperationalConflictError):
        account_editor.edit(store, invalid, NOW + timedelta(minutes=1), confirm=True)
    assert store.latest_portfolio() == before
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM manual_portfolio_imports").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM mobile_personal_settings").fetchone()[0] == 1


def test_nisa_limit_does_not_rewrite_old_values_and_rejects_new_four_million(device):
    store, valid = setup(device, nisa=True)
    invalid = valid.model_copy(
        update={
            "accounts": (
                valid.accounts[0].model_copy(update={"nisa_annual_capacity_user_input": "4000000"}),
            )
        }
    )
    # Historic data can still be read; it cannot be compiled into a valid proposal.
    assert invalid.model_validate_json(invalid.model_dump_json()) == invalid
    assert "nisa_capacity_out_of_range" in invalid.missing_fields(
        store.latest_manual_portfolio().portfolio
    )
    before = personal.read_settings(store)
    with pytest.raises(ValueError, match="240"):
        personal.save_settings(store, invalid, before["revision_id"], NOW + timedelta(minutes=1))
    assert personal.read_settings(store) == before
