"""Saved rankings and snapshot-bound manual ChatGPT ordering, without ledger writes."""

import json
from datetime import datetime, timedelta

from stock_ai.operations.chatgpt_manual import ExternalAiPermission
from stock_ai.operations.consultation import (
    CHATGPT_REPORT_MODE,
    ConsultationFindings,
    consultation_context,
    readable_consultation_prompt,
)
from stock_ai.operations.daily import content_id
from stock_ai.operations.manual_portfolio import strict_json

from . import forecasts, market


def _read(store, key):
    with store._connect() as db:
        row = db.execute("SELECT value FROM operational_metadata WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    record = json.loads(row[0])
    if content_id(record["payload"]) != record["sha256"]:
        raise ValueError("ランキングの保存内容を確認できません")
    return record["payload"]


def _write(store, key, payload):
    with store._connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO operational_metadata(key,value) VALUES (?,?)",
            (key, json.dumps({"payload": payload, "sha256": content_id(payload)})),
        )
        db.commit()


def _latest(path, store, now):
    snapshot = store.latest_archived_prediction(now)
    receipt = forecasts.latest(path)
    reference_result = forecasts.latest_reference_with_snapshot(path, now, saved_only=True)
    price_date = None
    if reference_result is not None:
        reference, candidate = reference_result
        if candidate is None:
            raise ValueError("Saved reference has no snapshot")
        if snapshot is None or candidate.generated_at > snapshot.generated_at:
            snapshot = candidate
            receipt = reference
            price_date = reference["scope"]["universe"]["latest_source_date"]
    return snapshot, receipt, price_date


def view(path, store, now, horizon):
    if horizon not in ("5d", "20d"):
        raise ValueError("5日または20日を選んでください")
    snapshot, receipt, price_date = _latest(path, store, now)
    if snapshot is None:
        return None
    universe = (
        receipt["scope"]["universe"]
        if receipt
        and receipt.get("snapshot")
        and receipt["snapshot"]["snapshot_id"] == snapshot.snapshot_id
        else {}
    )
    names = {r["symbol"]: r["company_name"] for r in universe.get("new_candidates", [])}
    price_date = price_date or universe.get("latest_source_date")
    symbols = set(snapshot.research_symbols())
    predictions = [p for p in snapshot.predictions if p.symbol in symbols]
    ranked = any(getattr(p, "rank_score_" + horizon, None) is not None for p in predictions)
    field = ("rank_score_" if ranked else "expected_return_") + horizon
    predictions.sort(
        key=lambda p: (getattr(p, field, None) is None, -(getattr(p, field, None) or 0), p.symbol)
    )
    rows = [
        {
            "symbol": p.symbol,
            "companyName": names.get(p.symbol, p.symbol),
            "modelRank": i + 1,
            "score": getattr(p, field, None),
            "expectedReturn": getattr(p, "expected_return_" + horizon),
        }
        for i, p in enumerate(predictions)
    ]
    identity = content_id({"snapshot": snapshot.snapshot_id, "horizon": horizon, "rows": rows})
    answer = _read(store, "ranking:answer:" + identity)
    portfolio = store.latest_portfolio()
    portfolio_id = None if portfolio is None else content_id(portfolio.model_dump(mode="json"))
    if (
        answer is not None
        and "checkedPortfolio" in answer
        and answer["checkedPortfolio"] != portfolio_id
    ):
        answer = None
    saved_input = _read(store, "ranking:input:" + identity)
    can_copy = False
    if saved_input is not None:
        try:
            ExternalAiPermission.model_validate(saved_input["permission"]).require(
                now, "manual_chatgpt"
            )
            can_copy = now <= datetime.fromisoformat(saved_input["expiresAt"])
            if saved_input.get("package"):
                can_copy = (
                    can_copy
                    and saved_input["package"]["consultation"]["portfolio_snapshot_id"]
                    == portfolio_id
                )
        except ValueError:
            pass
    history = _read(store, "ranking:latest-research:" + horizon)
    return {
        "id": identity,
        "snapshotId": snapshot.snapshot_id,
        "horizon": horizon,
        "generatedAt": snapshot.generated_at.isoformat(),
        "asOf": snapshot.as_of.isoformat(),
        "priceDate": price_date,
        "rows": rows,
        # Display metadata is outside the persisted consultation identity. Never
        # label the legacy return fallback in rows.score as a ranking score.
        "metrics": {
            p.symbol: {
                "return5d": p.expected_return_5d,
                "return20d": p.expected_return_20d,
                "rank20d": getattr(p, "rank_score_20d", None),
            }
            for p in predictions
        },
        "holdingSymbols": [] if portfolio is None else sorted({
            p.symbol for p in portfolio.positions if p.shares > 0
        }),
        "total": len(predictions),
        "answer": answer,
        "research": history,
        "savedInput": None
        if saved_input is None
        else {
            "id": saved_input.get("id", identity),
            "rankingId": identity,
            "prompt": saved_input["prompt"],
            "canCopy": can_copy,
            "expiresAt": saved_input["expiresAt"],
            "responseMode": saved_input.get("responseMode", "legacy-json"),
        },
    }


def export(path, store, now, horizon, body):
    permission = ExternalAiPermission.model_validate(body)
    permission.require(now, "manual_chatgpt")
    current = view(path, store, now, horizon)
    if current is None or not current["rows"]:
        raise ValueError("先にランキングを更新してください")
    snapshot, _, _ = _latest(path, store, now)
    context = consultation_context(
        snapshot,
        store.latest_portfolio(),
        now=now,
        market_evidence=market.consultation_evidence(path, now),
    )
    package = {
        "schema_version": "ranking-consultation-v2",
        "response_mode": CHATGPT_REPORT_MODE,
        "ranking_id": current["id"],
        "horizon": horizon,
        "consultation": context,
    }
    identity = content_id(package)
    package["id"] = identity
    expires = (now + timedelta(hours=24)).isoformat()
    prompt = readable_consultation_prompt(package)
    record = {
        "id": identity,
        "rankingId": current["id"],
        "package": package,
        "expiresAt": expires,
        "permission": permission.model_dump(mode="json"),
        "prompt": prompt,
        "responseMode": CHATGPT_REPORT_MODE,
    }
    _write(store, "ranking:research-input:" + identity, record)
    _write(store, "ranking:input:" + current["id"], record)
    return {
        "id": identity,
        "rankingId": current["id"],
        "prompt": prompt,
        "expiresAt": expires,
        "canCopy": True,
        "responseMode": CHATGPT_REPORT_MODE,
    }


def save_answer(path, store, now, horizon, body):
    if set(body) != {"id", "answer"} or not isinstance(body["answer"], str):
        raise ValueError("対応する入力と回答JSONを指定してください")
    record = _read(store, "ranking:research-input:" + body["id"])
    if record is None:
        return _save_legacy(store, now, horizon, body)
    package = record["package"]
    if package["horizon"] != horizon or package["id"] != content_id(
        {k: v for k, v in package.items() if k != "id"}
    ):
        raise ValueError("相談入力が一致しません")
    permission = ExternalAiPermission.model_validate(record["permission"])
    permission.require(permission.checked_at, "manual_chatgpt")
    if len(body["answer"].encode()) > 262144:
        raise ValueError("回答が大きすぎます")
    answer = strict_json(body["answer"])
    if (
        not isinstance(answer, dict)
        or set(answer) != {"id", "order", "research"}
        or answer["id"] != body["id"]
        or not isinstance(answer["order"], list)
    ):
        raise ValueError("このランキングに対応する回答JSONを貼り付けてください")
    expected = {r["symbol"] for r in package["consultation"]["securities"]}
    seen = set()
    for item in answer["order"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"symbol", "reason"}
            or not isinstance(item["symbol"], str)
            or item["symbol"] not in expected - seen
            or not isinstance(item["reason"], str)
            or not 1 <= len(item["reason"].strip()) <= 1000
        ):
            raise ValueError("銘柄の重複・対象外の銘柄・理由の不足を確認してください")
        seen.add(item["symbol"])
    if seen != expected:
        raise ValueError("回答に不足する銘柄があります。全銘柄の回答を貼り付けてください")
    research = ConsultationFindings.model_validate(answer["research"])
    research.check(expected, datetime.fromisoformat(package["consultation"]["research_as_of"]), now)
    identity = content_id(answer)
    saved = _read(store, "ranking:research:" + identity)
    if saved is None:
        saved = {**answer, "savedAt": now.isoformat(), "researchId": identity}
        _write(store, "ranking:research:" + identity, saved)
    _write(store, "ranking:latest-research:" + horizon, saved)
    return saved


def review_saved(path, store, now, horizon, body):
    if set(body) != {"researchId"}:
        raise ValueError("保存した調査結果を選んでください")
    saved = _read(store, "ranking:research:" + body["researchId"])
    if saved is None:
        raise ValueError("保存した調査結果が見つかりません")
    identity_fields = {k: v for k, v in saved.items() if k not in {"savedAt", "researchId"}}
    if content_id(identity_fields) != body["researchId"]:
        raise ValueError("保存した調査結果が一致しません")
    if saved.get("legacy"):
        current = view(path, store, now, horizon)
        record = _read(store, "ranking:input:" + saved["id"])
        if current is None or current["id"] != saved["id"]:
            raise ValueError("調査結果は保存済みです。ランキングが更新されています")
        ExternalAiPermission.model_validate(record["permission"]).require(now, "manual_chatgpt")
        if now > datetime.fromisoformat(record["expiresAt"]):
            raise ValueError("旧形式の相談期限が切れました。最新の相談文を作成してください")
        _write(store, "ranking:answer:" + current["id"], saved)
        return saved
    record = _read(store, "ranking:research-input:" + saved["id"])
    if record is None or record["package"]["id"] != content_id(
        {k: v for k, v in record["package"].items() if k != "id"}
    ):
        raise ValueError("保存した相談入力が一致しません")
    current = view(path, store, now, horizon)
    context = record["package"]["consultation"]
    portfolio = store.latest_portfolio()
    portfolio_id = None if portfolio is None else content_id(portfolio.model_dump(mode="json"))
    if (
        current is None
        or current["id"] != record["rankingId"]
        or record["package"]["horizon"] != horizon
        or context["portfolio_snapshot_id"] != portfolio_id
    ):
        raise ValueError(
            "調査結果は保存済みです。予測・保有が更新されたため、最新の内容で相談し直してください"
        )
    if any(row["forecast_missing"] for row in context["securities"]):
        raise ValueError("調査結果は保存済みです。未予測の保有株を含むため、予測を更新してください")
    result = {**saved, "checkedPortfolio": portfolio_id}
    _write(store, "ranking:answer:" + current["id"], result)
    return result


def import_answer(path, store, now, horizon, body):
    saved = save_answer(path, store, now, horizon, body)
    return review_saved(path, store, now, horizon, {"researchId": saved["researchId"]})


def _save_legacy(store, now, horizon, body):
    """Keep already copied v1 prompts usable without inventing missing research."""
    record = _read(store, "ranking:input:" + body["id"])
    if record is None or record.get("package"):
        raise ValueError("回答に対応する相談入力が見つかりません")
    package = strict_json(record["prompt"].rsplit("\n", 1)[-1])
    if package["id"] != body["id"] or package["horizon"] != horizon:
        raise ValueError("相談入力が一致しません")
    if len(body["answer"].encode()) > 262144:
        raise ValueError("回答が大きすぎます")
    answer = strict_json(body["answer"])
    if (
        not isinstance(answer, dict)
        or set(answer) != {"id", "order"}
        or answer["id"] != body["id"]
        or not isinstance(answer["order"], list)
    ):
        raise ValueError("相談入力と回答を確認してください")
    expected = {r["symbol"] for r in package["rows"]}
    seen = set()
    for item in answer["order"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"symbol", "reason"}
            or not isinstance(item["symbol"], str)
            or item["symbol"] not in expected - seen
            or not isinstance(item["reason"], str)
            or not 1 <= len(item["reason"].strip()) <= 1000
        ):
            raise ValueError("銘柄の重複・対象外の銘柄・理由の不足を確認してください")
        seen.add(item["symbol"])
    if seen != expected:
        raise ValueError("回答に不足する銘柄があります")
    payload = {**answer, "legacy": True}
    identity = content_id(payload)
    saved = _read(store, "ranking:research:" + identity)
    if saved is None:
        saved = {**payload, "savedAt": now.isoformat(), "researchId": identity}
        _write(store, "ranking:research:" + identity, saved)
    _write(store, "ranking:latest-research:" + horizon, saved)
    return saved
