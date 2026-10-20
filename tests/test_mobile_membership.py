from __future__ import annotations

import copy
import sqlite3
from datetime import datetime
from uuid import uuid4

import pytest
from mobile.python import market, membership, universe

from stock_ai.data.contracts import DatasetName
from tests.test_mobile_universe import CUTOFF, daily
from tests.test_mobile_universe import acquired as history_fixture


def observation(received="2026-02-03T02:00:00+00:00", *, symbols=2, business=True):
    value = daily(CUTOFF.date(), symbols)
    datasets = {name: value["datasets"][name] for name in ("security_master", "trading_calendar")}
    if not business:
        datasets["security_master"] = []
        datasets["trading_calendar"][0]["HolDiv"] = "0"
    return {"purpose": "membership", "status": 200, "date": str(CUTOFF.date()),
            "acquisitionId": str(uuid4()), "received_at": received, "datasets": datasets,
            "source_pages": [
                {"dataset": name, "page": 0, "row_count": len(rows),
                 "received_at": received, "sha256": "0" * 64}
                for name, rows in datasets.items()
            ]}


@pytest.fixture()
def device(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    membership.initialize(path)
    return path


@pytest.fixture()
def acquired(tmp_path):
    return history_fixture.__wrapped__(tmp_path)


def test_membership_before_cutoff_survives_reopen_without_changing_historical_inputs(device):
    payload = observation()
    status = membership.ingest(device, payload, CUTOFF)
    assert status["available_at_cutoff"] is True and status["is_business_day"] is True
    assert membership.snapshot(device, datetime.fromisoformat("2026-02-03T01:59:59Z")) is None
    membership.initialize(device)
    assert membership.status(device, CUTOFF) == status
    assert membership.ingest(device, payload, CUTOFF) == status
    with sqlite3.connect(device) as db:
        assert db.execute("SELECT COUNT(*) FROM mobile_membership").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM market_batches").fetchone()[0] == 0


def test_exact_boundary_is_allowed_but_later_receipt_never_backdates_or_replaces_it(device):
    exact = observation("2026-02-03T02:30:00Z")
    membership.ingest(device, exact, CUTOFF)
    late = observation("2026-02-03T02:30:00.000001Z")
    late["datasets"]["security_master"].pop()
    late["source_pages"][0]["row_count"] -= 1
    now = datetime.fromisoformat("2026-02-03T03:00:00Z")
    result = membership.ingest(device, late, now)
    assert result["eligible_acquisition_id"] == exact["acquisitionId"]
    assert result["eligible_received_at"] == exact["received_at"]
    assert result["acquisitionId"] == late["acquisitionId"]
    assert len(membership.snapshot(device, CUTOFF)["datasets"]["security_master"]) == 2
    assert len(membership.snapshot(device, now)["datasets"]["security_master"]) == 1


def test_only_late_observation_and_prior_day_cannot_claim_current_cutoff(device):
    late = observation("2026-02-03T02:30:00.000001Z")
    now = datetime.fromisoformat("2026-02-03T03:00:00Z")
    result = membership.ingest(device, late, now)
    assert result["available_at_cutoff"] is False
    assert result["latest_received_at"] == late["received_at"]
    assert membership.snapshot(device, CUTOFF) is None
    assert membership.status(device, datetime.fromisoformat("2026-02-04T01:00:00Z"))[
        "available_at_cutoff"
    ] is False


def test_native_nanosecond_receipt_is_never_truncated_into_1130_cutoff(device):
    value = observation("2026-02-03T02:30:00.000000001Z")
    result = membership.ingest(device, value, datetime.fromisoformat("2026-02-03T03:00:00Z"))
    assert result["available_at_cutoff"] is False
    assert membership.snapshot(device, CUTOFF) is None
    later = datetime.fromisoformat("2026-02-03T02:30:00.000001Z")
    assert membership.snapshot(device, later)["acquisitionId"] == value["acquisitionId"]


def test_changed_acquisition_and_tampered_receipt_index_are_rejected(device):
    payload = observation()
    membership.ingest(device, payload, CUTOFF)
    changed = copy.deepcopy(payload)
    changed["datasets"]["security_master"][0]["CoName"] = "changed fixture"
    with pytest.raises(ValueError, match="acquisition changed"):
        membership.ingest(device, changed, CUTOFF)
    with sqlite3.connect(device) as db:
        db.execute("UPDATE mobile_membership SET received_at='2026-02-03T00:00:00+00:00'")
    with pytest.raises(ValueError, match="reference changed"):
        membership.snapshot(device, CUTOFF)


def test_corrupted_compressed_observation_fails_without_publishing_new_data(device):
    membership.ingest(device, observation(), CUTOFF)
    with sqlite3.connect(device) as db:
        db.execute("UPDATE mobile_membership SET raw=?", (b"invalid zlib",))
    with pytest.raises(ValueError, match="observation changed"):
        membership.snapshot(device, CUTOFF)


def test_holiday_calendar_does_not_import_next_session_master(device):
    value = observation(business=False)
    assert membership.ingest(device, value, CUTOFF)["is_business_day"] is False
    selected = universe.select(device, CUTOFF, ("ZZZZ",), current_membership=True)
    assert selected["blocking_reasons"] == ["non_business_day"]
    assert selected["decision_symbols"] == ["ZZZZ"]
    value = observation(business=False)
    value["datasets"]["security_master"] = observation()["datasets"]["security_master"]
    with pytest.raises(ValueError):
        membership.ingest(device, value, CUTOFF)


@pytest.mark.parametrize("kind", [
    "wrong_date", "duplicate", "bad_page_count", "future_receipt", "no_master"
])
def test_invalid_membership_does_not_publish_any_observation(device, kind):
    value = observation()
    if kind == "wrong_date":
        value["datasets"]["security_master"][0]["Date"] = "2026-02-04"
    elif kind == "duplicate":
        value["datasets"]["security_master"] *= 2
    elif kind == "bad_page_count":
        value["source_pages"][0]["row_count"] = 999
    elif kind == "future_receipt":
        value["received_at"] = "2026-02-04T02:00:00Z"
    elif kind == "no_master":
        value["datasets"]["security_master"] = []
    with pytest.raises(ValueError):
        membership.ingest(device, value, CUTOFF)
    assert membership.snapshot(device, CUTOFF) is None


def test_current_membership_retains_delisted_holdings_and_historical_feature_members(acquired):
    path, _ = acquired
    membership.initialize(path)
    assert universe.select(path, CUTOFF, ("1000",), current_membership=True)[
        "blocking_reasons"
    ] == ["current_membership_missing"]
    value = observation(symbols=303)
    value["datasets"]["security_master"].pop(0)  # A formerly listed issue is absent today.
    value["datasets"]["security_master"][0]["Code"] = "186A0"  # New code: no invented history.
    value["source_pages"][0]["row_count"] -= 1
    before = market.SQLiteSource(path).point_in_time(
        DatasetName.SECURITY_MASTER, CUTOFF
    )
    membership.ingest(path, value, CUTOFF)
    result = universe.select(path, CUTOFF, ("1000", "186A", "ZZZZ"), current_membership=True)
    assert not result["blocking_reasons"] and result["membership_verified"] is True
    assert result["membership_source_date"] == "2026-02-03"
    assert result["new_candidates"][0]["symbol"] == "1002"
    assert result["held_only"] == ["1000", "186A", "ZZZZ"]
    after = market.SQLiteSource(path).point_in_time(DatasetName.SECURITY_MASTER, CUTOFF)
    assert before.equals(after)  # Today's master never removes historical broad feature members.
