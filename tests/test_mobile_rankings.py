import json
from datetime import timedelta

import pytest
from mobile.python import forecasts, rankings

from stock_ai.operations.daily import content_id
from tests.test_mobile_forecasts import NOW
from tests.test_mobile_forecasts import ready as forecast_ready


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    return forecast_ready.__wrapped__(tmp_path, monkeypatch)


def permission(now):
    return dict(service="manual_chatgpt", checked_at=now.isoformat(),
                personal_analysis_only=True, training_disabled=True,
                private_input=True, private_output=True, data_entitlement_confirmed=True)


def prepare(ready):
    device, store, path, *_ = ready
    forecasts.generate(path, store, NOW)
    current = rankings.view(path, store, NOW + timedelta(days=2), "20d")
    assert current and current["rows"]
    now = NOW + timedelta(days=2)
    exported = rankings.export(path, store, now, "20d", permission(now))
    answer = {"id": current["id"], "order": [
        {"symbol": r["symbol"], "reason": "合成テストの比較理由"}
        for r in reversed(current["rows"])]}
    return device, store, path, now, current, exported, answer


def test_saved_ranking_any_time_consultation_restore_without_ledger_changes(ready):
    device, store, path, now, current, exported, answer = prepare(ready)
    ledger = store.latest_portfolio()
    forecast = store.latest_prediction_snapshot()
    saved = rankings.import_answer(path, store, now, "20d", {
        "id": exported["id"], "answer": json.dumps(answer)})
    assert rankings.view(path, store, now, "20d")["answer"] == saved
    assert rankings.view(path, store, now, "5d")["answer"] is None
    assert store.latest_portfolio() == ledger
    assert store.latest_prediction_snapshot() == forecast
    assert "available_cash" not in exported["prompt"]
    capsule = device.export_state()
    device.initialize(capsule)
    restored = rankings.view(path, device._app.state.store, now, "20d")
    assert restored["answer"] == saved and restored["rows"] == current["rows"]
    assert restored["savedInput"]["prompt"] == exported["prompt"]


@pytest.mark.parametrize("case", ["duplicate", "missing", "unknown", "wrong_id", "expired"])
def test_bad_or_old_answers_never_replace_rankings(ready, case):
    _, store, path, now, _current, exported, answer = prepare(ready)
    if case == "duplicate":
        answer["order"].append(answer["order"][0])
    elif case == "missing":
        answer["order"].pop()
    elif case == "unknown":
        answer["order"][0]["symbol"] = "UNKNOWN"
    elif case == "wrong_id":
        answer["id"] = "0" * 64
    else:
        now += timedelta(days=2)
    with pytest.raises(ValueError):
        rankings.import_answer(path, store, now, "20d", {
            "id": exported["id"], "answer": json.dumps(answer)})
    assert rankings.view(path, store, now, "20d")["answer"] is None


def test_newer_reference_used_and_old_answer_not_applied(ready, monkeypatch):
    _, store, path, now, old, exported, answer = prepare(ready)
    value = forecasts.latest(path)
    snapshot = dict(value["snapshot"])
    snapshot["generated_at"] = (NOW + timedelta(hours=1)).isoformat()
    snapshot["snapshot_id"] = content_id({k: v for k, v in snapshot.items() if k != "snapshot_id"})
    monkeypatch.setattr(forecasts, "latest_reference", lambda *a, **k: {
        "snapshot": snapshot, "scope": {"universe": {"latest_source_date": "2026-10-23"}}})
    current = rankings.view(path, store, now, "20d")
    assert current["id"] != old["id"] and current["priceDate"] == "2026-10-23"
    with pytest.raises(ValueError, match="更新"):
        rankings.import_answer(path, store, now, "20d", {
            "id": exported["id"], "answer": json.dumps(answer)})


def test_no_snapshot_and_permission_required(ready):
    _, store, path, *_ = ready
    assert rankings.view(path, store, NOW, "20d") is None
    with pytest.raises(ValueError):
        rankings.export(path, store, NOW, "20d", permission(NOW))
    forecasts.generate(path, store, NOW)
    denied = {**permission(NOW), "data_entitlement_confirmed": False}
    with pytest.raises(ValueError):
        rankings.export(path, store, NOW, "20d", denied)


def test_runtime_routes_prepare_and_apply_answer(ready):
    import asyncio
    from datetime import UTC, datetime

    device, store, path, *_ = ready
    forecasts.generate(path, store, NOW)
    async def run():
        route = "/api/v1/mobile/ranking/20d"
        result = await device.request("GET", route)
        assert result["status"] == 200 and result["body"]["rows"]
        created = await device.request("POST", route + "/export", json.dumps(
            permission(datetime.now(UTC))))
        assert created["status"] == 200
        identity = created["body"]["id"]
        answer = {"id": identity, "order": [
            {"symbol": row["symbol"], "reason": "合成の理由"}
            for row in reversed(result["body"]["rows"])]}
        applied = await device.request("POST", route + "/answer", json.dumps({
            "id": identity, "answer": json.dumps(answer)}))
        assert applied["status"] == 200
        restored = await device.request("GET", route)
        assert restored["body"]["answer"]["order"] == answer["order"]
        assert (await device.request("POST", route + "/unknown", "{}"))["status"] == 422
    asyncio.run(run())
