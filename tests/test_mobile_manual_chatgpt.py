import json
from datetime import timedelta

import pytest
from mobile.python import decisions, manual_chatgpt, personal

from stock_ai.operations.chatgpt_manual import ExternalAiPermission
from stock_ai.operations.store import OperationalIntegrityError
from tests.test_mobile_decisions import NOW
from tests.test_mobile_decisions import ready as ready


def permission():
    return ExternalAiPermission(
        service="manual_chatgpt",
        checked_at=NOW,
        personal_analysis_only=True,
        training_disabled=True,
        private_input=True,
        private_output=True,
        data_entitlement_confirmed=True,
    ).model_dump(mode="json")


def export(ready):
    _, path, store, _, _ = ready
    decisions.generate(path, store, NOW)
    return manual_chatgpt.export(path, store, permission(), NOW)


def answer_for(exported):
    package = json.loads(exported["prompt"].split("\n入力:\n")[1])
    return dict(
        schema_version="chatgpt-target-shares-v1",
        input_snapshot_id=package["input_snapshot_id"],
        evidence_as_of=NOW.isoformat(),
        targets=[
            dict(
                symbol=x["symbol"],
                account=x["account"],
                target_shares=x["current_shares"],
                reason="未確認のため保有を維持",
                sources=[],
            )
            for x in package["required_targets"]
        ],
        unknowns=["実環境の試験ではありません"],
    )


def test_manual_exchange_restores_exact_json_and_never_updates_actual_state(ready):
    device, path, store, _, _ = ready
    exported = export(ready)
    before = store.latest_portfolio().model_dump_json()
    original = json.dumps(answer_for(exported), ensure_ascii=False, indent=2)
    result = manual_chatgpt.import_answer(
        path, store, {"input_record_id": exported["input_record_id"], "answer_json": original}, NOW
    )
    assert not result["review"]["applied_to_ledger"]
    assert store.latest_portfolio().model_dump_json() == before
    store.verify_integrity()
    saved = store.metadata("chatgpt-manual:answer:" + result["record_id"])
    assert json.loads(saved)["payload"]["original_json"] == original
    replay = manual_chatgpt.import_answer(
        path,
        store,
        {"input_record_id": exported["input_record_id"], "answer_json": original},
        NOW + timedelta(minutes=1),
    )
    assert replay == result
    assert store.metadata("chatgpt-manual:answer:" + result["record_id"]) == saved
    assert len(manual_chatgpt.status(path, store, NOW)["answers"]) == 1
    device.initialize(device.export_state())
    restored = device._app.state.store
    assert restored.metadata("chatgpt-manual:answer:" + result["record_id"]) == saved
    assert restored.latest_portfolio().model_dump_json() == before
    assert (
        manual_chatgpt.status(path, restored, NOW)["selected_input"] == exported["input_record_id"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing-permission",
        "stale",
        "changed-input",
        "wrong-id",
        "invalid-json",
        "wrong-answer-type",
    ],
)
def test_invalid_manual_exchanges_are_rejected_without_balance_changes(ready, change):
    _, path, store, _, _ = ready
    exported = export(ready)
    before = store.latest_portfolio().model_dump_json()
    body = {
        "input_record_id": exported["input_record_id"],
        "answer_json": json.dumps(answer_for(exported)),
    }
    now = NOW
    if change == "missing-permission":
        invalid = permission()
        invalid["data_entitlement_confirmed"] = False
        with pytest.raises(ValueError, match="PERMISSION_UNCONFIRMED"):
            manual_chatgpt.export(path, store, invalid, now)
        return
    if change == "stale":
        now += timedelta(minutes=16)
    elif change == "changed-input":
        saved = personal.portfolio_view(store)
        personal.save_portfolio(
            store, store.latest_manual_portfolio().portfolio, saved["revision_id"], NOW
        )
    elif change == "wrong-id":
        body["input_record_id"] = "0" * 64
    elif change == "wrong-answer-type":
        body["answer_json"] = None
    else:
        body["answer_json"] = "broken"
    with pytest.raises(ValueError):
        manual_chatgpt.import_answer(path, store, body, now)
    assert store.latest_portfolio().model_dump_json() == before
    assert not manual_chatgpt.status(path, store, now)["answers"]


def test_corrupt_manual_input_is_rejected_by_standard_backup_integrity_check(ready):
    _, _, store, _, _ = ready
    exported = export(ready)
    key = "chatgpt-manual:input:" + exported["input_record_id"]
    payload = json.loads(store.metadata(key))
    payload["payload"]["package"]["accounts"][0]["available_cash_yen"] = "999999999"
    store.set_metadata(key, json.dumps(payload))
    with pytest.raises(OperationalIntegrityError, match="manual ChatGPT exchange"):
        store.verify_integrity()
