import json
from datetime import timedelta

import pytest
from mobile.python import forecasts, market, rankings

from stock_ai.operations.daily import PredictionSnapshot, content_id
from tests.test_consultation_context import findings
from tests.test_mobile_forecasts import NOW
from tests.test_mobile_forecasts import ready as forecast_ready


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    return forecast_ready.__wrapped__(tmp_path, monkeypatch)


def permission(now):
    return dict(
        service="manual_chatgpt",
        checked_at=now.isoformat(),
        personal_analysis_only=True,
        training_disabled=True,
        private_input=True,
        private_output=True,
        data_entitlement_confirmed=True,
    )


def prepare(ready):
    device, store, path, *_ = ready
    forecasts.generate(path, store, NOW)
    current = rankings.view(path, store, NOW + timedelta(days=2), "20d")
    assert current and current["rows"]
    now = NOW + timedelta(days=2)
    exported = rankings.export(path, store, now, "20d", permission(now))
    answer = {
        "id": exported["id"],
        "research": findings([r["symbol"] for r in current["rows"]], now),
        "order": [
            {"symbol": r["symbol"], "reason": "合成テストの比較理由"}
            for r in reversed(current["rows"])
        ],
    }
    return device, store, path, now, current, exported, answer


def test_display_all_predictions_preserves_consultation_identity(ready, monkeypatch):
    _, store, path, *_ = ready
    forecasts.generate(path, store, NOW)
    original = store.latest_prediction_snapshot()
    template = original.predictions[0]
    codes = [str(1000 + i) for i in range(25)]
    predictions = tuple(template.model_copy(update={
        "symbol": symbol, "expected_return_5d": (25 - index) / 1000,
        "expected_return_20d": (25 - index) / 500,
    }) for index, symbol in enumerate([*codes, "7203"]))
    snapshot = PredictionSnapshot.create(**{
        **{name: getattr(original, name) for name in type(original).model_fields
           if name != "snapshot_id"},
        "candidate_symbols": tuple(codes), "holding_symbols": ("7203",), "predictions": predictions,
    })
    monkeypatch.setattr(rankings, "_latest", lambda *_: (snapshot, None, None))
    result = rankings.view(path, store, NOW + timedelta(days=1), "5d")
    assert len(result["rows"]) == 21
    assert len(result["displayRows"]) == result["total"] == 26
    assert result["id"] == content_id({
        "snapshot": snapshot.snapshot_id, "horizon": "5d", "rows": result["rows"]
    })
    assert [row["symbol"] for row in result["displayRows"]] == [*codes, "7203"]
    assert result["metrics"]["1024"]["return5d"] == pytest.approx(.001)


def test_saved_ranking_any_time_consultation_restore_without_ledger_changes(ready):
    device, store, path, now, current, exported, answer = prepare(ready)
    ledger = store.latest_portfolio()
    forecast = store.latest_prediction_snapshot()
    saved = rankings.import_answer(
        path, store, now, "20d", {"id": exported["id"], "answer": json.dumps(answer)}
    )
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


def test_new_ranking_prompt_requests_readable_analysis_without_json_response(ready):
    _, store, *_ = ready
    before = store.latest_portfolio().model_dump_json()
    _, _, _, _, _, exported, _ = prepare(ready)
    assert exported["responseMode"] == "chatgpt-readable-report-v2"
    prompt = exported["prompt"]
    assert "日本語のMarkdown本文・表・出典リンク" in prompt
    assert "5日・20日それぞれの下落シナリオ" in prompt
    assert "根拠が足りなければ確率は不明" in prompt
    assert "次のJSON形式だけを返してください" not in prompt
    assert '"properties"' not in prompt
    package = json.loads(prompt.split("\n入力:\n")[1])
    assert package["response_mode"] == exported["responseMode"]
    assert package["consultation"]["securities"]
    assert store.latest_portfolio().model_dump_json() == before


def test_display_metrics_preserve_identity_and_do_not_invent_rank_scores(ready):
    _, store, path, now, current, _, _ = prepare(ready)
    assert current["id"] == content_id({
        "snapshot": current["snapshotId"], "horizon": "20d", "rows": current["rows"],
    })
    snapshot, _, _ = rankings._latest(path, store, now)
    for prediction in snapshot.predictions:
        if prediction.symbol in current["metrics"]:
            assert current["metrics"][prediction.symbol] == {
                "return5d": prediction.expected_return_5d,
                "return20d": prediction.expected_return_20d,
                "rank20d": getattr(prediction, "rank_score_20d", None),
            }
    assert current["holdingSymbols"] == sorted({
        p.symbol for p in store.latest_portfolio().positions if p.shares > 0
    })


def test_display_names_use_verified_master_without_changing_ranking_identity(ready):
    from tests.test_mobile_market import payload
    from tests.test_mobile_runtime import run

    device, store, path, now, before, exported, _ = prepare(ready)
    names = rankings.display_names(path, store, now, "20d")
    assert names["snapshotId"] == before["snapshotId"]
    assert names["names"]["1000"] == "Synthetic fixture"
    assert names["names"]["7203"] == "synthetic fixture"
    response = run(device, "GET", "/api/v1/mobile/ranking/20d/names")
    assert response["status"] == 200
    assert response["body"] == names
    later = payload()
    later["received_at"] = (now + timedelta(days=1)).isoformat()
    later["datasets"]["security_master"][0]["CoName"] = "future correction"
    market.ingest(path, later)
    after_names = rankings.display_names(path, store, now + timedelta(days=2), "20d")
    assert after_names["names"]["7203"] == "synthetic fixture"
    after = rankings.view(path, store, now + timedelta(days=2), "20d")
    assert after["id"] == before["id"]
    assert after["rows"] == before["rows"]
    assert after["savedInput"]["id"] == exported["id"]


def test_display_names_rejects_tampered_master(ready):
    from mobile.python.storage import connect

    _, store, path, now, *_ = prepare(ready)
    with connect(path) as db:
        db.execute("UPDATE market_batches SET payload_hash=? WHERE dataset='security_master'",
                   ("0" * 64,))
    with pytest.raises(ValueError, match="Stored candidate source changed"):
        rankings.display_names(path, store, now, "20d")


def test_display_names_uses_the_forecast_frozen_membership(ready, monkeypatch):
    _, store, path, now, *_ = prepare(ready)
    snapshot, receipt, _ = rankings._latest(path, store, now)
    receipt["scope"]["universe"]["membership_acquisition_id"] = "frozen-membership"
    monkeypatch.setattr(rankings, "_latest", lambda *args: (snapshot, receipt, None))
    calls = []
    def reference(source_path, acquisition, cutoff):
        calls.append((source_path, acquisition, cutoff))
        return {"datasets": {"security_master": [{"Code": "72030", "CoName": "Frozen name"}]}}
    monkeypatch.setattr(rankings.membership, "reference", reference)
    result = rankings.display_names(path, store, now, "20d")
    assert result["names"]["7203"] == "Frozen name"
    assert calls == [(path, "frozen-membership", snapshot.as_of)]


@pytest.mark.parametrize("case", ["duplicate", "missing", "unknown", "wrong_id"])
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
    with pytest.raises(ValueError):
        rankings.import_answer(
            path, store, now, "20d", {"id": exported["id"], "answer": json.dumps(answer)}
        )
    assert rankings.view(path, store, now, "20d")["answer"] is None


def test_newer_reference_used_and_old_answer_not_applied(ready, monkeypatch):
    _, store, path, now, old, exported, answer = prepare(ready)
    value = forecasts.latest(path)
    snapshot = dict(value["snapshot"])
    snapshot["generated_at"] = (NOW + timedelta(hours=1)).isoformat()
    snapshot["snapshot_id"] = content_id({k: v for k, v in snapshot.items() if k != "snapshot_id"})
    monkeypatch.setattr(
        forecasts,
        "latest_reference_with_snapshot",
        lambda *a, **k: ({
            "snapshot": snapshot,
            "scope": {"universe": {"latest_source_date": "2026-10-23"}},
        }, PredictionSnapshot.model_validate(snapshot)),
    )
    current = rankings.view(path, store, now, "20d")
    assert current["id"] != old["id"] and current["priceDate"] == "2026-10-23"
    with pytest.raises(ValueError, match="更新"):
        rankings.import_answer(
            path, store, now, "20d", {"id": exported["id"], "answer": json.dumps(answer)}
        )


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
        created = await device.request(
            "POST", route + "/export", json.dumps(permission(datetime.now(UTC)))
        )
        assert created["status"] == 200
        identity = created["body"]["id"]
        answer = {
            "id": identity,
            "order": [
                {"symbol": row["symbol"], "reason": "合成の理由"}
                for row in reversed(result["body"]["rows"])
            ],
        }
        answer["research"] = findings(
            [r["symbol"] for r in result["body"]["rows"]], datetime.now(UTC)
        )
        applied = await device.request(
            "POST", route + "/answer", json.dumps({"id": identity, "answer": json.dumps(answer)})
        )
        assert applied["status"] == 200
        restored = await device.request("GET", route)
        assert restored["body"]["answer"]["order"] == answer["order"]
        assert (await device.request("POST", route + "/unknown", "{}"))["status"] == 422

    asyncio.run(run())


def test_delayed_research_saved_and_restored_before_separate_latest_review(ready):
    device, store, path, now, current, exported, answer = prepare(ready)
    later = now + timedelta(days=2)
    saved = rankings.save_answer(
        path, store, later, "20d", {"id": exported["id"], "answer": json.dumps(answer)}
    )
    assert rankings.view(path, store, later, "20d")["answer"] is None
    assert rankings.view(path, store, later, "20d")["savedInput"]["canCopy"] is False
    device.initialize(device.export_state())
    restored = device._app.state.store
    assert rankings.view(path, restored, later, "20d")["research"] == saved
    applied = rankings.review_saved(
        path, restored, later, "20d", {"researchId": saved["researchId"]}
    )
    assert applied["order"] == answer["order"]
    assert rankings.view(path, restored, later, "20d")["rows"] == current["rows"]


def test_latest_portfolio_change_blocks_apply_without_losing_saved_research(ready, monkeypatch):
    _, store, path, now, _, exported, answer = prepare(ready)
    saved = rankings.save_answer(
        path, store, now, "20d", {"id": exported["id"], "answer": json.dumps(answer)}
    )
    before = store.latest_portfolio()
    changed = before.model_copy(update={"portfolio_id": "changed"})
    monkeypatch.setattr(store, "latest_portfolio", lambda: changed)
    with pytest.raises(ValueError, match="保存済み"):
        rankings.review_saved(path, store, now, "20d", {"researchId": saved["researchId"]})
    assert rankings.view(path, store, now, "20d")["research"] == saved


def test_old_copied_prompt_and_answer_remain_usable(ready):
    _, store, path, now, current, _, _ = prepare(ready)
    package = {k: current[k] for k in ("id", "horizon", "asOf", "priceDate", "rows")}
    rankings._write(
        store,
        "ranking:input:" + current["id"],
        {
            "prompt": "Old prompt\n" + json.dumps(package),
            "permission": permission(now),
            "expiresAt": (now + timedelta(hours=24)).isoformat(),
        },
    )
    answer = {
        "id": current["id"],
        "order": [{"symbol": r["symbol"], "reason": "旧形式の回答"} for r in current["rows"]],
    }
    result = rankings.import_answer(
        path, store, now, "20d", {"id": current["id"], "answer": json.dumps(answer)}
    )
    assert result["legacy"] and result["order"] == answer["order"]
