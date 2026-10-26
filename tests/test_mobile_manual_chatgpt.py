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


def test_new_prompt_is_for_reading_in_chatgpt_and_preserves_source_inputs(ready):
    _, _, store, _, _ = ready
    before = store.latest_portfolio().model_dump_json()
    exported = export(ready)
    assert exported["response_mode"] == "chatgpt-readable-report-v1"
    prompt = exported["prompt"]
    assert "日本語のMarkdown本文・表・出典リンク" in prompt
    assert "アプリへの回答の貼り戻しは行いません" in prompt
    assert "回答JSON・機械取込用schema" in prompt
    assert "出力しないでください" in prompt
    assert "回答は次のschemaのJSONだけ" not in prompt
    assert "chatgpt-target-shares-v1" not in prompt
    assert "全保有" in prompt and "5営業日・20営業日" in prompt
    assert "実約定による損益の再現ではありません" in prompt
    assert "未約定売却代金" in prompt and "元の数値予測" in prompt
    package = json.loads(prompt.split("\n入力:\n")[1])
    assert package["input_snapshot_id"] == exported["input_snapshot_id"]
    assert package["consultation"]["securities"]
    assert store.latest_portfolio().model_dump_json() == before
    store.verify_integrity()


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
    context = json.loads(exported["prompt"].split("\n入力:\n")[1])["consultation"]
    status = manual_chatgpt.status(path, store, NOW)
    assert status["research"][0]["consultation"] == context
    assert status["decision_source"]["recordId"] == result["record_id"]
    assert status["decision_source"]["checkedAt"] == NOW.isoformat()
    assert all(
        line["accountBucketId"]
        in {bucket.bucket_id for bucket in store.latest_portfolio().account_buckets}
        for line in status["decision_source"]["lines"]
    )
    assert [
        (line["symbol"], line["currentShares"], line["targetShares"])
        for line in status["decision_source"]["lines"]
    ] == [
        (line["symbol"], line["current_shares"], line["target_shares"])
        for line in result["review"]["lines"]
    ]
    assert status["current_shares"] == {
        symbol: sum(
            item.shares for item in store.latest_portfolio().positions if item.symbol == symbol
        )
        for symbol in {item.symbol for item in store.latest_portfolio().positions}
    }
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
    status = manual_chatgpt.status(path, store, now)
    assert not status["answers"]
    if change in {"stale", "changed-input"}:
        assert status["saved_input"] is None


def test_corrupt_manual_input_is_rejected_by_standard_backup_integrity_check(ready):
    _, _, store, _, _ = ready
    exported = export(ready)
    key = "chatgpt-manual:input:" + exported["input_record_id"]
    payload = json.loads(store.metadata(key))
    payload["payload"]["package"]["accounts"][0]["available_cash_yen"] = "999999999"
    store.set_metadata(key, json.dumps(payload))
    with pytest.raises(OperationalIntegrityError, match="manual ChatGPT exchange"):
        store.verify_integrity()


def test_saved_prompt_survives_owner_restart_without_new_export_or_balance_changes(ready):
    device, path, store, _, _ = ready
    exported = export(ready)
    ledger = store.latest_portfolio().model_dump_json()
    original = store.metadata("chatgpt-manual:input:" + exported["input_record_id"])
    device.initialize(device.export_state())
    restored = device._app.state.store
    resumed = manual_chatgpt.status(path, restored, NOW + timedelta(minutes=1))
    assert resumed["ready"]
    assert resumed["saved_input"] == exported
    assert resumed["saved_input_reason"] is None
    assert restored.metadata("chatgpt-manual:input:" + exported["input_record_id"]) == original
    assert restored.latest_portfolio().model_dump_json() == ledger
    with restored._connect() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM operational_metadata WHERE key LIKE 'chatgpt-manual:input:%'"
            ).fetchone()[0]
            == 1
        )


def test_expired_permission_does_not_make_saved_prompt_copyable_or_delete_it(ready):
    _, path, store, _, _ = ready
    decisions.generate(path, store, NOW)
    checked = permission()
    checked["checked_at"] = (NOW - timedelta(hours=23, minutes=50)).isoformat()
    exported = manual_chatgpt.export(path, store, checked, NOW)
    key = "chatgpt-manual:input:" + exported["input_record_id"]
    original = store.metadata(key)
    result = manual_chatgpt.status(path, store, NOW + timedelta(minutes=11))
    assert result["ready"]
    assert result["saved_input"] is None
    assert result["saved_input_reason"]
    assert result["selected_input"] == exported["input_record_id"]
    assert store.metadata(key) == original


def test_expired_comparison_keeps_history_but_never_reoffers_saved_prompt(ready):
    _, path, store, _, _ = ready
    exported = export(ready)
    manual_chatgpt.import_answer(
        path,
        store,
        {
            "input_record_id": exported["input_record_id"],
            "answer_json": json.dumps(answer_for(exported)),
        },
        NOW,
    )
    expired = manual_chatgpt.status(path, store, NOW + timedelta(minutes=16))
    assert not expired["ready"]
    assert expired["saved_input"] is None
    assert len(expired["answers"]) == 1


def test_long_research_is_saved_then_rechecked_against_fresh_conditions(ready):
    device, path, store, _, _ = ready
    exported = export(ready)
    original = json.dumps(answer_for(exported))
    before = store.latest_portfolio()
    later = NOW + timedelta(hours=2)
    saved = manual_chatgpt.save_answer(path, store, {
        "input_record_id": exported["input_record_id"], "answer_json": original,
    }, later)
    assert saved["saved"] and not saved["reviewed"]
    assert not manual_chatgpt.status(path, store, later)["answers"]
    device.initialize(device.export_state())
    store = device._app.state.store
    assert manual_chatgpt.status(path, store, later)["research"][0]["original_json"] == original
    result = manual_chatgpt.review_saved(path, store, {
        "research_record_id": saved["research_record_id"],
    }, later)
    assert result["review"]["checked_comparison_id"]
    assert not result["review"]["order_submitted"]
    assert store.latest_portfolio() == before


def test_expired_send_permission_does_not_discard_returned_research(ready):
    _, path, store, _, _ = ready
    exported = export(ready)
    saved = manual_chatgpt.save_answer(path, store, {
        "input_record_id": exported["input_record_id"],
        "answer_json": json.dumps(answer_for(exported)),
    }, NOW + timedelta(days=2))
    assert saved["saved"]
    assert manual_chatgpt.status(path, store, NOW + timedelta(days=2))["saved_input"] is None
    with pytest.raises(ValueError):
        manual_chatgpt.review_saved(path, store, {
            "research_record_id": saved["research_record_id"],
        }, NOW + timedelta(days=2))
    store.verify_integrity()
