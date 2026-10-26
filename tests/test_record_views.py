from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from stock_ai.domain import UserDecision, UserDecisionLine
from stock_ai.operations import OperationalIntegrityError, OperationalStore, create_app
from tests.conftest import AS_OF
from tests.test_operations_api import _client

HEADERS = {"X-Stock-AI-Intent": "manual-record"}


def test_execution_context_reads_saved_judgment_without_forecasts_or_recalculation(
    tmp_path, monkeypatch
):
    original, proposal = _client(tmp_path)
    store = original.app.state.store
    decision = UserDecision(
        decision_id="saved-fill-context",
        proposal_id=proposal.proposal_id,
        version=1,
        saved_at=AS_OF + timedelta(minutes=2),
        lines=tuple(
            UserDecisionLine(
                proposal_line_id=line.line_id, selected_target_shares=line.recommended_shares
            )
            for line in proposal.lines
        ),
    )
    store.save_decision(decision)
    client = TestClient(
        create_app(store.path, clock=lambda: AS_OF + timedelta(minutes=5)),
        base_url="http://127.0.0.1",
    )
    current = client.app.state.store
    before = current.latest_portfolio().model_dump_json()

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Execution input must not load predictions or validate planning inputs"
        )

    for method in [
        "latest_prediction_snapshot",
        "latest_archived_prediction",
        "proposal_inputs_current",
    ]:
        monkeypatch.setattr(current, method, forbidden)
    payload = client.get("/api/v1/execution-context").json()
    assert payload["decision"]["decision_id"] == decision.decision_id
    assert payload["proposal"]["proposalId"] == proposal.proposal_id
    assert {line["lineId"] for line in payload["proposal"]["lines"]} == {
        line.line_id for line in proposal.lines
    }
    assert all(
        set(line)
        == {"lineId", "symbol", "companyName", "accountBucketId", "currentShares", "referencePrice"}
        for line in payload["proposal"]["lines"]
    )
    assert current.latest_portfolio().model_dump_json() == before
    tomorrow = TestClient(
        create_app(store.path, clock=lambda: AS_OF + timedelta(days=1)), base_url="http://127.0.0.1"
    )
    assert tomorrow.get("/api/v1/execution-context").json()["proposal"] is None


def test_note_preserves_text_survives_reopen_backup_and_does_not_change_finances(tmp_path):
    client, _ = _client(tmp_path)
    store = client.app.state.store
    before = store.latest_portfolio().model_dump_json()
    url = "/api/v1/stocks/7203/note"
    assert client.get(url).json() == {
        "symbol": "7203",
        "text": "",
        "revision": None,
        "updatedAt": None,
    }
    text = "  決算を確認する\n配当と為替の影響 📝\n"
    saved = client.post(url, json={"text": text, "expectedRevision": None}, headers=HEADERS)
    assert saved.status_code == 200
    note = saved.json()
    assert note["text"] == text
    assert len(note["revision"]) == 64
    assert client.get("/api/v1/stocks/6758/note").json()["text"] == ""
    assert (
        client.post(url, json={"text": text, "expectedRevision": None}, headers=HEADERS).json()
        == note
    )
    assert store.latest_portfolio().model_dump_json() == before
    assert OperationalStore(store.path).stock_note("7203") == note
    backup = store.backup(tmp_path / "notes-backup.sqlite3")
    target = tmp_path / "restored.sqlite3"
    OperationalStore.restore_backup(backup, target, confirm_replace=True)
    assert OperationalStore(target).stock_note("7203") == note


def test_note_conflict_and_clear_keep_revision_and_reject_corruption(tmp_path):
    client, _ = _client(tmp_path)
    url = "/api/v1/stocks/7203/note"
    first = client.post(url, json={"text": "最初のメモ"}, headers=HEADERS).json()
    conflict = client.post(
        url, json={"text": "古い画面の入力", "expectedRevision": None}, headers=HEADERS
    )
    assert conflict.status_code == 409
    assert client.get(url).json() == first
    cleared = client.post(
        url, json={"text": "", "expectedRevision": first["revision"]}, headers=HEADERS
    ).json()
    assert cleared["text"] == "" and cleared["revision"] != first["revision"]
    assert (
        client.post(
            url,
            json={"text": "古い画面の入力", "expectedRevision": first["revision"]},
            headers=HEADERS,
        ).status_code
        == 409
    )
    store = client.app.state.store
    store.set_metadata("stock-note:7203", '{"payload_json":"{}","sha256":"invalid"}')
    with pytest.raises(OperationalIntegrityError):
        store.stock_note("7203")
    with pytest.raises(OperationalIntegrityError):
        store.verify_integrity()


@pytest.mark.parametrize("text", ["x" * 5001, "a\x00b"], ids=["too-long", "nul"])
def test_note_rejects_invalid_text_and_requires_manual_intent(tmp_path, text):
    client, _ = _client(tmp_path)
    assert client.post("/api/v1/stocks/7203/note", json={"text": "hello"}).status_code == 428
    assert (
        client.post("/api/v1/stocks/7203/note", json={"text": text}, headers=HEADERS).status_code
        == 422
    )
    assert client.get("/api/v1/stocks/7203/note").json()["revision"] is None
