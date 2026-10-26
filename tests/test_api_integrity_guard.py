from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from stock_ai.operations.api import create_app
from stock_ai.operations.integrity import IntegrityGuard
from stock_ai.operations.store import OperationalIntegrityError, OperationalStore
from tests.conftest import AS_OF, portfolio


def test_unchanged_proof_reused_and_external_wal_commit_invalidates(tmp_path, monkeypatch):
    store = OperationalStore(tmp_path / "ledger.sqlite3")
    store.append_portfolio(portfolio(), created_at=AS_OF)
    verify = Mock(wraps=store.verify_integrity)
    monkeypatch.setattr(store, "verify_integrity", verify)
    guard = IntegrityGuard(store)
    try:
        assert guard.verify()["portfolio_states"] == 1
        for _ in range(5):
            assert guard.verify()["portfolio_states"] == 1
        assert verify.call_count == 1
        # Keep the writer open so the change exists in WAL, not the base file.
        with sqlite3.connect(store.path) as writer:
            writer.execute("UPDATE portfolio_states SET content_hash='corrupt'")
            writer.commit()
            with pytest.raises(OperationalIntegrityError):
                guard.verify()
        with pytest.raises(OperationalIntegrityError):
            guard.verify()
        assert verify.call_count == 3
    finally:
        guard.close()


def test_file_replacement_and_failed_proofs_are_never_reused(tmp_path, monkeypatch):
    store = OperationalStore(tmp_path / "ledger.sqlite3")
    guard = IntegrityGuard(store)
    try:
        guard.verify()
        replacement = OperationalStore(tmp_path / "replacement.sqlite3")
        replacement.append_portfolio(portfolio(), created_at=AS_OF)
        # Fully checkpoint before replacement, then remove stale sidecars.
        guard.close()
        for path in (store.path, replacement.path):
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        guard.verify()
        if os.name == "nt":
            # Windows prevents replacing an open SQLite file. Verify that OS
            # protection, then follow the runtime's close-before-restore path.
            with pytest.raises(PermissionError):
                os.replace(replacement.path, store.path)
            guard.close()
        os.replace(replacement.path, store.path)
        assert guard.verify()["portfolio_states"] == 1
        fail = Mock(side_effect=OperationalIntegrityError("synthetic failure"))
        monkeypatch.setattr(store, "verify_integrity", fail)
        with sqlite3.connect(store.path) as db:
            db.execute("INSERT INTO operational_metadata VALUES('changed','1')")
        for _ in range(2):
            with pytest.raises(OperationalIntegrityError, match="synthetic failure"):
                guard.verify()
        assert fail.call_count == 2
    finally:
        guard.close()


def test_commit_during_verification_does_not_cache_an_older_proof(tmp_path, monkeypatch):
    store = OperationalStore(tmp_path / "concurrent.sqlite3")
    original = store.verify_integrity
    guard = IntegrityGuard(store)

    def concurrent_commit():
        counts = original()
        store.append_portfolio(portfolio(), created_at=AS_OF)
        return counts

    try:
        monkeypatch.setattr(store, "verify_integrity", concurrent_commit)
        assert guard.verify()["portfolio_states"] == 0
        verify = Mock(wraps=original)
        monkeypatch.setattr(store, "verify_integrity", verify)
        assert guard.verify()["portfolio_states"] == 1
        assert verify.call_count == 1
        assert guard.verify()["portfolio_states"] == 1
        assert verify.call_count == 1
    finally:
        guard.close()


def test_api_health_verifies_once_and_light_input_route_omits_prediction_history(
    tmp_path, monkeypatch,
):
    app = create_app(tmp_path / "api.sqlite3", clock=lambda: AS_OF)
    store = app.state.store
    verify = Mock(wraps=store.verify_integrity)
    monkeypatch.setattr(store, "verify_integrity", verify)
    monkeypatch.setattr(store, "latest_archived_prediction", Mock(
        side_effect=AssertionError("unused prediction history"),
    ))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        result = client.get("/api/v1/execution-context")
        assert result.status_code == 200
        assert result.json()["decision"] is None
        assert "savedAnalysis" not in result.json()
        assert client.get("/api/v1/today?includeSavedAnalysis=false").status_code == 200
        assert verify.call_count == 1
    assert app.state.integrity_guard._observer is None


@pytest.mark.parametrize("kind", ["positions", "executions"])
def test_invalid_csv_is_a_validation_response_and_preserves_existing_state(tmp_path, kind):
    app = create_app(tmp_path / "csv.sqlite3", clock=lambda: AS_OF)
    app.state.store.append_portfolio(portfolio(), created_at=AS_OF)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        before = app.state.store.verify_integrity()
        reply = client.post(f"/api/v1/imports/{kind}/preview", json={"csvText": "invalid csv"},
                            headers={"X-Stock-AI-Intent": "manual-record"})
        assert reply.status_code == 422
        assert "missing required columns" in reply.json()["detail"]
        assert app.state.store.verify_integrity() == before
        assert app.state.store.latest_portfolio() == portfolio()
