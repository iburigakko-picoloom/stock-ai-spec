from __future__ import annotations

import asyncio
import base64
import io
import json
import sqlite3
import zipfile

import pytest
from mobile.python import runtime


@pytest.fixture()
def device(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "STATE", tmp_path / "state")
    runtime.initialize()
    return runtime


def run(device, method, path, body=None):
    return asyncio.run(device.request(method, path, json.dumps(body)))


def test_shared_api_runs_without_server_and_preserves_no_order_boundary(device):
    response = run(device, "GET", "/api/v1/health")
    assert response["status"] == 200
    assert response["body"]["orderSubmissionAvailable"] is False
    assert run(device, "POST", "/api/v1/orders", {})["status"] == 404
    assert run(device, "GET", "https://foreign.example/api/v1/health")["status"] == 400


def test_all_local_connections_close_before_repeated_backup_restore(device, monkeypatch):
    original = sqlite3.connect
    opened = []

    def track(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)  # Keep strong refs: do not rely on garbage collection.
        return connection

    monkeypatch.setattr(sqlite3, "connect", track)
    try:
        for _ in range(3):
            device.initialize(device.export_state())
            for endpoint in ("models", "daily", "market/plan", "market/membership",
                             "market/universe", "personal/settings"):
                assert run(device, "GET", "/api/v1/mobile/" + endpoint)["status"] == 200
            for connection in opened:
                with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                    connection.execute("SELECT 1")
    finally:
        for connection in opened:
            connection.close()


def test_bundle_probe_never_imports_approves_or_publishes_a_prediction(device, monkeypatch):
    from mobile.python.model_bundle import encoded

    from tests.test_mobile_bundles import SELECTION, fixture_bundle

    monkeypatch.setattr(runtime, "bundled_selection", lambda: SELECTION)
    def database_contents():
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(device.export_state()))) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    before = database_contents()
    bundle = fixture_bundle()
    response = run(device, "POST", "/api/v1/mobile/models/bundle/parity", {
        "content": encoded(bundle), "rows": {"5": [{"f1": .2}], "20": [{"f1": .3}]},
    })
    assert response["status"] == 200
    assert response["body"]["bundle_id"] == bundle.bundle_id
    assert response["body"]["persisted"] is False
    assert response["body"]["model_adopted"] is False
    assert len(response["body"]["heads"]) == 4
    assert response["body"]["heads"][0]["values"] == [.01]
    assert database_contents() == before
    for content, rows in ((None, {}), (encoded(bundle), {"5": "bad", "20": []}),
                          (encoded(bundle), {"5": [{}] * 1001, "20": []})):
        assert run(device, "POST", "/api/v1/mobile/models/bundle/parity", {
            "content": content, "rows": rows,
        })["status"] == 422


def test_market_plan_and_unknown_holdings_survive_portable_backup(device):
    plan = {"first_day": "2026-01-01", "last_day": "2026-01-06"}
    assert run(device, "POST", "/api/v1/mobile/market/plan", plan)["body"] == plan
    selected = run(device, "GET", "/api/v1/mobile/market/universe")["body"]
    assert selected["holdings_recorded"] is False
    assert selected["blocking_reasons"] == ["twenty_sessions_required"]
    encoded = device.export_state()
    device.initialize(encoded)
    assert run(device, "GET", "/api/v1/mobile/market/plan")["body"] == plan
    assert run(device, "POST", "/api/v1/mobile/market/plan", {
        "first_day": "2026-01-06", "last_day": "2026-01-01"
    })["status"] == 422


def test_current_membership_survives_backup_without_replacing_canonical_history(device):
    from mobile.python import membership

    from tests.test_mobile_membership import CUTOFF, observation

    payload = observation()
    assert run(device, "POST", "/api/v1/mobile/market/membership", payload)["status"] == 200
    before = membership.snapshot(device.STATE / "mobile.sqlite3", CUTOFF)
    encoded = device.export_state()
    device.initialize(encoded)
    assert membership.snapshot(device.STATE / "mobile.sqlite3", CUTOFF) == before
    assert run(device, "GET", "/api/v1/mobile/market")["body"]["completed_dates"] == []


def test_unknown_manual_inputs_survive_restart_and_exact_backup(device):
    value = {
        "schema_version": "manual-portfolio-v1",
        "holdings_status": "none",
        "investment_budget_yen": None,
        "maximum_drawdown_percent": None,
        "accounts": [],
        "holdings": [],
    }
    assert run(device, "POST", "/api/v1/mobile/portfolio", value)["status"] == 200
    before = run(device, "GET", "/api/v1/mobile/portfolio")["body"]
    backup = device.export_state()
    device.initialize(backup)
    after = run(device, "GET", "/api/v1/mobile/portfolio")["body"]
    assert before == after
    assert after["portfolio"]["investment_budget_yen"] is None
    assert "apiKey" not in backup


def test_invalid_input_does_not_publish_revision(device):
    assert (
        run(device, "POST", "/api/v1/mobile/portfolio", {"api_key": "never-store"})["status"] == 422
    )
    assert run(device, "GET", "/api/v1/mobile/portfolio")["body"] is None


def test_core_views_work_in_embedded_dispatch(device):
    for name in ("status", "home", "today", "settings", "ranking", "validation", "notifications"):
        assert run(device, "GET", "/api/v1/" + name)["status"] == 200, name


def test_unadopted_model_cannot_be_imported_or_generate_forecast(device):
    assert run(device, "GET", "/api/v1/mobile/models")["body"]["approved_count"] == 0
    assert run(device, "POST", "/api/v1/mobile/models/import", {"content": "{}"})["status"] == 422
    assert run(device, "POST", "/api/v1/mobile/models/infer", {})["status"] == 422
    assert run(device, "GET", "/api/v1/daily/latest")["body"]["snapshot"] is None
