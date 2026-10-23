from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from stock_ai.operations.api import create_app
from stock_ai.operations.daily import PredictionSnapshot
from tests.conftest import AS_OF
from tests.test_daily_readiness import daily_snapshot


def test_saved_analysis_survives_blocked_active_selection_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    morning = AS_OF + timedelta(days=1, hours=-3)
    app = create_app(path, clock=lambda: morning)
    store = app.state.store
    original = daily_snapshot()
    saved = PredictionSnapshot.create(**{
        **original.model_dump(exclude={"snapshot_id"}), "blocking_reasons": (),
    })
    store.append_prediction_snapshot(saved)
    store.select_mobile_numerical_without_snapshot("a" * 64, morning, None, None)
    assert store.latest_prediction_snapshot() is None
    for server in (app, create_app(path, clock=lambda: morning)):
        client = TestClient(server, base_url="http://127.0.0.1")
        response = client.get("/api/v1/today")
        assert response.status_code == 200
        view = response.json()
        assert view["proposal"] is None
        assert view["savedAnalysis"]["snapshotId"] == saved.snapshot_id
        assert view["savedAnalysis"]["readOnly"] is True
        assert view["savedAnalysis"]["asOf"] == saved.as_of.isoformat()
        assert view["savedAnalysis"]["predictions"][0]["symbol"] == "A"
        assert server.state.store.latest_prediction_snapshot() is None
    assert store.prediction_snapshot(saved.snapshot_id) == saved


def test_archive_excludes_future_and_changes_only_after_committed_snapshot(tmp_path: Path) -> None:
    now = AS_OF + timedelta(minutes=2)
    app = create_app(tmp_path / "history.sqlite3", clock=lambda: now)
    client = TestClient(app, base_url="http://127.0.0.1")
    store = app.state.store
    assert client.get("/api/v1/today").json()["savedAnalysis"] is None
    original = daily_snapshot()
    first = PredictionSnapshot.create(**{
        **original.model_dump(exclude={"snapshot_id"}), "blocking_reasons": (),
    })
    store.append_prediction_snapshot(first)
    later = PredictionSnapshot.create(**{
        **first.model_dump(exclude={"snapshot_id"}),
        "generated_at": now + timedelta(minutes=1),
    })
    store.append_prediction_snapshot(later)
    assert client.get("/api/v1/today").json()["savedAnalysis"]["snapshotId"] == first.snapshot_id
    now += timedelta(minutes=2)
    assert client.get("/api/v1/today").json()["savedAnalysis"]["snapshotId"] == later.snapshot_id
    with store._connect() as db:
        db.execute("UPDATE prediction_snapshots SET content_hash=? WHERE snapshot_id=?",
                   ("0" * 64, later.snapshot_id))
        db.commit()
    assert client.get("/api/v1/today").status_code == 503
