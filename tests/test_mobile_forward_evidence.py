import asyncio
import sqlite3
from datetime import timedelta

import pytest
from mobile.python import forecasts, forward_evidence

from stock_ai.operations.store import OperationalIntegrityError
from tests.test_mobile_forecasts import NOW

pytest_plugins = ("tests.test_mobile_forecasts",)


def test_inventory_reads_checked_daily_receipt_without_modifying_ledger(ready):
    _, store, path, *_ = ready
    saved = forecasts.generate(path, store, NOW)
    before = store.latest_portfolio().model_dump_json()
    result = forward_evidence.inventory(path, store, now=NOW + timedelta(seconds=1))
    assert len(result["runs"]) == 1
    run = result["runs"][0]
    assert run["run_id"] == saved["run_id"]
    assert run["snapshot_id"] == saved["snapshot"]["snapshot_id"]
    assert run["prediction_count"] == len(saved["snapshot"]["predictions"])
    assert run["data_proof_hash"] == saved["snapshot"]["data_snapshot_id"]
    assert run["has_5d_return"] and run["has_20d_return"]
    assert not run["outcomes_scored"] and not run["forward_registration_verified"]
    assert not result["formal_evaluation"]
    assert store.latest_portfolio().model_dump_json() == before


def test_inventory_rejects_tampered_snapshot_and_future_read(ready):
    _, store, path, *_ = ready
    forecasts.generate(path, store, NOW)
    with pytest.raises(ValueError, match="future"):
        forward_evidence.inventory(path, store, now=NOW - timedelta(seconds=1))
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE prediction_snapshots SET content_hash=?", ("0" * 64,))
    with pytest.raises(OperationalIntegrityError, match="content hash mismatch"):
        forward_evidence.inventory(path, store, now=NOW + timedelta(seconds=1))


def test_inventory_api_uses_saved_receipts_and_rejects_corruption(ready, monkeypatch):
    device, store, path, *_ = ready
    forecasts.generate(path, store, NOW)

    class FixedDatetime(type(NOW)):
        @classmethod
        def now(cls, tz=None):
            current = NOW + timedelta(seconds=1)
            return current if tz is None else current.astimezone(tz)

    monkeypatch.setattr(device, "datetime", FixedDatetime)
    url = "/api/v1/mobile/forward-evidence"
    response = asyncio.run(device.request("GET", url))
    assert response["status"] == 200 and len(response["body"]["runs"]) == 1
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE prediction_snapshots SET content_hash=?", ("0" * 64,))
    response = asyncio.run(device.request("GET", url))
    assert response["status"] == 422
