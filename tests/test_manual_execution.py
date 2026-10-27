import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from stock_ai.operations.api import create_app
from stock_ai.operations.store import OperationalStore
from tests.conftest import AS_OF, portfolio
from tests.test_operations_store import _nisa_execution_store


def body(**changes):
    return {
        "executionId": "manual-test",
        "executedAt": (AS_OF + timedelta(hours=1)).isoformat(),
        "symbol": "7203",
        "accountBucketId": "bucket",
        "status": "filled",
        "side": "BUY",
        "orderedShares": 100,
        "filledShares": 100,
        "averageFillPrice": "1000.25",
        "actualCommission": "10.50",
        "actualOtherCost": "1.25",
        "taxWithheld": "0",
        **changes,
    }


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / "operations.sqlite3", clock=lambda: AS_OF + timedelta(hours=2))
    app.state.store.append_portfolio(portfolio(cash=Decimal("250000")), created_at=AS_OF)
    return app


def post(client, value):
    return client.post(
        "/api/v1/executions/manual", json=value, headers={"X-Stock-AI-Intent": "manual-record"}
    )


def test_no_proposal_or_decision_needed_atomic_fill_and_retry(app):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        context = client.get("/api/v1/execution-entry-context").json()
        assert context["accountLabels"]["bucket"]
        assert client.get("/api/v1/execution-context").json()["decision"] is None
        result = post(client, body())
        assert result.status_code == 201, result.text
        assert result.json()["applied"]
        assert result.json()["execution"]["decision_id"] is None
        store = app.state.store
        actual = store.latest_portfolio()
        assert actual.cash[0].available_cash == Decimal("149963.25")
        assert actual.positions[0].shares == 100
        assert actual.applied_execution_ids == ("manual-test",)
        assert post(client, body()).status_code == 201
        assert store.latest_portfolio() == actual
        assert len(store.executions()) == 1
        assert post(client, body(averageFillPrice="1001")).status_code == 409
        assert store.latest_portfolio() == actual
        counts = store.verify_integrity()
        assert counts["proposals"] == counts["user_decisions"] == 0
    reopened = OperationalStore(store.path)
    assert reopened.latest_portfolio() == actual
    assert reopened.executions()[0].decision_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"averageFillPrice": "999999"},
        {"side": "SELL"},
        {"accountBucketId": "missing"},
        {"executedAt": AS_OF.isoformat()},
        {"executedAt": (AS_OF + timedelta(days=1)).isoformat()},
        {"filledShares": 101},
    ],
)
def test_invalid_trade_cannot_partially_commit(app, changes):
    before = app.state.store.latest_portfolio()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = post(client, body(**changes))
        assert response.status_code == 422, response.text
    assert app.state.store.executions() == ()
    assert app.state.store.latest_portfolio() == before


def test_missing_initial_assets_is_actionable(tmp_path):
    app = create_app(tmp_path / "empty.sqlite3", clock=lambda: AS_OF + timedelta(hours=2))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/execution-entry-context").json()["portfolioId"] is None
        assert post(client, body()).status_code == 409
    assert app.state.store.executions() == ()


def test_old_schema_upgrade_preserves_existing_hashed_bytes(tmp_path):
    store, execution = _nisa_execution_store(tmp_path)
    store.append_execution(execution)
    with sqlite3.connect(store.path) as db:
        old = db.execute("SELECT * FROM portfolio_states").fetchall()
        old_fills = db.execute("SELECT * FROM executions").fetchall()
        db.execute("DROP TABLE executions")
        db.execute(
            "CREATE TABLE executions(execution_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, "
            "executed_at TEXT NOT NULL, payload TEXT NOT NULL, content_hash TEXT NOT NULL, "
            "FOREIGN KEY(decision_id) REFERENCES user_decisions(decision_id))"
        )
        db.executemany("INSERT INTO executions VALUES (?,?,?,?,?)", old_fills)
        db.execute("PRAGMA user_version=5")
    OperationalStore(store.path).verify_integrity()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT * FROM portfolio_states").fetchall() == old
        assert db.execute("SELECT * FROM executions").fetchall() == old_fills
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert (
            next(x for x in db.execute("PRAGMA table_info(executions)") if x[1] == "decision_id")[3]
            == 0
        )


def test_multiple_past_trades_can_be_entered_in_execution_order(app):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert post(client, body()).status_code == 201
        second = body(executionId="second", executedAt=(AS_OF + timedelta(minutes=90)).isoformat())
        assert post(client, second).status_code == 201
        current = app.state.store.latest_portfolio()
        assert current.positions[0].shares == 200
        assert current.cash[0].available_cash == Decimal("49926.50")
        assert current.applied_execution_ids == ("manual-test", "second")


def test_combined_context_reuses_current_manual_entry_and_keeps_legacy_response(app):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        legacy = client.get("/api/v1/execution-context").json()
        combined = client.get("/api/v1/execution-context?includeManual=1").json()
        assert "manualContext" not in legacy
        assert combined["decision"] is None
        assert combined["manualContext"] == client.get("/api/v1/execution-entry-context").json()
        assert {key: value for key, value in combined.items() if key != "manualContext"} == legacy
        assert post(client, body()).status_code == 201
        after = client.get("/api/v1/execution-context?includeManual=1").json()
        assert after["manualContext"] == client.get("/api/v1/execution-entry-context").json()
        assert after["manualContext"]["portfolioId"] != combined["manualContext"]["portfolioId"]
