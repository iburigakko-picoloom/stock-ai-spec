from __future__ import annotations

import copy
import sqlite3
import zlib
from datetime import datetime, timedelta

import pytest
from mobile.python import market, membership, preselection, universe

from tests.test_mobile_membership import observation
from tests.test_mobile_universe import CUTOFF


def master_observation(count=305):
    value = observation(symbols=count)
    for row in value["datasets"]["security_master"]:
        row.update(ProdCat="011", ScaleCat="TOPIX Mid400")
    return value


def test_explicit_topix500_policy_uses_all_members_and_holdings_with_frozen_provenance(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    membership.initialize(path)
    assert preselection.policy(path)["mode"] == "legacy300"
    value = master_observation()
    membership.ingest(path, value, CUTOFF)
    preselection.policy(path, preselection.MODE)
    result = universe.select(path, CUTOFF, ("ZZZZ", "1000"), current_membership=True)
    assert len(result["new_candidates"]) == 305  # no ADV/cap/top300 requirement
    assert result["held_only"] == ["ZZZZ"] and "ZZZZ" in result["decision_symbols"]
    frozen = result["preselection"]
    assert frozen["source"]["received_at"] == value["received_at"]
    assert frozen["source"]["observation_id"] == value["acquisitionId"]
    assert datetime.fromisoformat(frozen["effective_at"]) == CUTOFF
    assert len(frozen["list_hash"]) == 64 and len(frozen["diff"]["added"]) == 305
    assert result["excluded"] == [
        {"symbol": "ZZZZ", "reason": "HELD_INSTRUMENT_UNSUPPORTED_OR_NOT_LISTED"}
    ]
    assert universe.select(path, CUTOFF, ("ZZZZ", "1000"), current_membership=True) == result
    assert not preselection.policy(path, preselection.LEGACY)["experimental"]


def test_late_correction_cannot_replace_frozen_list_and_missing_day_stops(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    membership.initialize(path)
    value = master_observation(4)
    membership.ingest(path, value, CUTOFF)
    before = preselection.select(path, CUTOFF)
    changed = master_observation(4)
    changed["received_at"] = (CUTOFF + timedelta(seconds=1)).isoformat()
    changed["datasets"]["security_master"][0]["ScaleCat"] = "TOPIX Small 1"
    membership.ingest(path, changed, CUTOFF + timedelta(minutes=10))
    assert preselection.select(path, CUTOFF) == before
    later = preselection.select(path, CUTOFF + timedelta(minutes=10))
    assert later["preselection"]["diff"]["removed"] == ["1000"]
    assert later["preselection"]["previous_list_hash"] == before["preselection"]["list_hash"]
    assert preselection.select(path, CUTOFF + timedelta(days=1))["blocking_reasons"] == [
        "current_membership_missing_no_verified_fallback"
    ]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE mobile_preselection_lists SET payload=?", (b"bad",))
    with pytest.raises((ValueError, zlib.error)):
        preselection.select(path, CUTOFF)


def test_unsupported_members_are_explicit_and_never_fill_the_target_count(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    membership.initialize(path)
    value = master_observation(4)
    value["datasets"]["security_master"][1]["ProdCat"] = "012"
    value["datasets"]["security_master"][2]["ScaleCat"] = "TOPIX Small 2"
    value["datasets"]["security_master"][3]["ProdCat"] = None
    membership.ingest(path, value, CUTOFF)
    result = preselection.select(path, CUTOFF, ("1001", "1002"))
    assert [x["symbol"] for x in result["new_candidates"]] == ["1000"]
    assert result["decision_symbols"] == ["1000", "1001", "1002"]
    assert len(result["preselection"]["unsupported"]) == 2
    original = copy.deepcopy(result)
    assert preselection.select(path, CUTOFF, ("1001", "1002")) == original


def test_monthly_review_preserves_prior_list_without_fabricating_membership(tmp_path):
    path = tmp_path / "mobile.sqlite3"
    market.initialize(path)
    membership.initialize(path)
    membership.ingest(path, master_observation(4), CUTOFF)
    first = preselection.select(path, CUTOFF)
    later = CUTOFF + timedelta(days=28)
    value = master_observation(4)
    value["date"] = str(later.date())
    value["received_at"] = (later - timedelta(hours=1)).isoformat()
    for rows in value["datasets"].values():
        for row in rows:
            row["Date"] = str(datetime.fromisoformat(row["Date"]).date() + timedelta(days=28))
    for page in value["source_pages"]:
        page["received_at"] = value["received_at"]
    membership.ingest(path, value, later)
    reviewed = preselection.select(path, later)
    assert reviewed["preselection"]["review_reason"] == "monthly"
    assert reviewed["preselection"]["list_hash"] != first["preselection"]["list_hash"]
    assert reviewed["preselection"]["diff"] == {"added": [], "removed": [], "changed": []}
    assert preselection.select(path, CUTOFF) == first
