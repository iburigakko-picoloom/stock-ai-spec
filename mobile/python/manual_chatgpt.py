"""Manual exchanges reuse the verified decision receipt and encrypted owner."""

from stock_ai.domain import PortfolioState
from stock_ai.operations.chatgpt_manual import (
    ExternalAiPermission,
    _context,
    input_package,
    manual_prompt,
    parse_answer,
    read_record,
    review_answer,
    save_record,
    validate_saved_answer,
    verify_exchange_records,
)
from stock_ai.operations.consultation import (
    CHATGPT_REPORT_MODE,
    consultation_context,
    readable_consultation_prompt,
)
from stock_ai.operations.daily import PredictionSnapshot, content_id
from stock_ai.operations.personal import PersonalComparison

from . import decisions, forecasts, market, models, personal


def _current(path, store, now):
    value = decisions.view(path, store)
    return_only = bool(
        value
        and value["outcome"] == "blocked"
        and value["comparison"] is not None
        and value["blocking_reasons"] == ["FORECAST_RISK_UNAVAILABLE"]
        and value["comparison"].get("manual_context_sha256")
    )
    if (
        not value
        or (not return_only and (not value["is_active"] or value["outcome"] != "proposal"))
        or value["comparison"] is None
    ):
        raise ValueError(
            "最新の原予測・口座・設定の照合を完了してください。未採用モデルは研究用です。"
        )
    frozen = value["frozen_inputs"]
    comparison = PersonalComparison.model_validate(value["comparison"])
    portfolio = PortfolioState.model_validate(frozen["ledger"])
    forecast = PredictionSnapshot.model_validate(frozen["forecast"])
    if return_only:
        manual, ledger = store.latest_manual_portfolio(), store.latest_portfolio()
        _profile, saved, gaps, compiled = personal.input_state(store, now)
        numerical = forecasts.latest(path)
        refs = value["scope"]["personal_refs"]
        _bundle, pin = models.load_bundle(path, forecast.as_of)
        if (
            manual is None
            or ledger != portfolio
            or saved is None
            or gaps
            or compiled != comparison.request.settings
            or manual.export.revision_id != refs["manual_revision_id"]
            or saved["revision_id"] != refs["settings_revision_id"]
            or numerical is None
            or numerical["phase"] != "published"
            or numerical["run_id"] != value["scope"]["numerical_run_id"]
            or content_id(pin) != value["scope"]["bundle_pin_sha256"]
            or content_id(
                [
                    x.model_dump(mode="json")
                    for x in sorted(
                        store.executions(),
                        key=lambda x: x.execution_id,
                    )
                ]
            )
            != refs["executions_sha256"]
        ):
            raise ValueError("口座・原予測・設定が変わりました。最新の条件で照合してください")
    _context(comparison, portfolio, forecast, now)
    return value, comparison, portfolio, forecast


def status(path, store, now):
    ready, reason = True, None
    current = None
    try:
        current = _current(path, store, now)
    except ValueError as error:
        ready, reason = False, str(error)
    with store._connect() as db:
        verify_exchange_records(db)
        selected = db.execute(
            "SELECT value FROM operational_metadata WHERE key=?", ("chatgpt-manual:selected",)
        ).fetchone()
        saved = (
            None
            if selected is None
            else read_record(
                db.execute(
                    "SELECT value FROM operational_metadata WHERE key=?",
                    ("chatgpt-manual:input:" + selected[0],),
                ).fetchone()[0]
            )
        )
        answer_records = [
            (row[0].removeprefix("chatgpt-manual:answer:"), read_record(row[1]))
            for row in db.execute(
                "SELECT key,value FROM operational_metadata "
                "WHERE key LIKE 'chatgpt-manual:answer:%' "
                "ORDER BY rowid DESC LIMIT 20"
            )
        ]
        answers = [receipt["review"] for _, receipt in answer_records]
        decision_source = None
        if current is not None and answer_records:
            record_id, receipt = answer_records[0]
            row = db.execute(
                "SELECT value FROM operational_metadata WHERE key=?",
                ("chatgpt-manual:input:" + receipt["input_record_id"],),
            ).fetchone()
            package = {} if row is None else read_record(row[0])["package"]
            portfolio = current[2]
            aliases = {
                f"A{i}": b.bucket_id
                for i, b in enumerate(
                    sorted(portfolio.account_buckets, key=lambda b: b.bucket_id), 1
                )
            }
            if (
                package.get("comparison_id") == current[1].comparison_id
                and package.get("prediction_snapshot_id") == current[3].snapshot_id
                and package.get("account_snapshot_id")
                == content_id(portfolio.model_dump(mode="json"))
                and all(line["account"] in aliases for line in receipt["review"]["lines"])
            ):
                decision_source = {
                    "recordId": record_id,
                    "checkedAt": receipt["checked_at"],
                    "lines": [
                        {
                            "symbol": line["symbol"],
                            "accountBucketId": aliases[line["account"]],
                            "currentShares": line["current_shares"],
                            "targetShares": line["target_shares"],
                        }
                        for line in receipt["review"]["lines"]
                    ],
                }
        research = [
            {"record_id": row[0].removeprefix("chatgpt-manual:research:"), **read_record(row[1])}
            for row in db.execute(
                "SELECT key,value FROM operational_metadata "
                "WHERE key LIKE 'chatgpt-manual:research:%' "
                "ORDER BY rowid DESC LIMIT 20"
            )
        ]
        for item in research:
            source = db.execute(
                "SELECT value FROM operational_metadata WHERE key=?",
                ("chatgpt-manual:input:" + item["input_record_id"],),
            ).fetchone()
            item["consultation"] = (
                None if source is None else read_record(source[0])["package"].get("consultation")
            )
    saved_input, saved_input_reason = None, None
    if saved is not None and current is not None:
        value, comparison, portfolio, forecast = current
        try:
            package = input_package(
                comparison,
                portfolio,
                forecast,
                now=now,
                permission=ExternalAiPermission.model_validate(saved["permission"]),
                market_evidence=saved["package"].get("consultation", {}).get("market_evidence"),
            )
            if saved["decision_run_id"] != value["run_id"] or saved["package"] != package:
                raise ValueError("saved input changed")
            saved_input = _input_view(selected[0], package)
        except (ValueError, KeyError, TypeError):
            saved_input_reason = (
                "保存済み入力の期限・送信許可・照合情報を確認できません。"
                "最新の入力を作成してください。"
            )
    portfolio = store.latest_portfolio()
    for item in research:
        item["answer"] = parse_answer(item["original_json"]).model_dump(mode="json")
    accounts = {} if portfolio is None else {a.account_id: a for a in portfolio.accounts}
    labels = (
        {}
        if portfolio is None
        else {
            f"A{i}": f"{accounts[b.account_id].display_name} / {b.account_type.value}"
            for i, b in enumerate(sorted(portfolio.account_buckets, key=lambda b: b.bucket_id), 1)
        }
    )
    return {
        "ready": ready,
        "reason": reason,
        "selected_input": None if selected is None else selected[0],
        "saved_input": saved_input,
        "saved_input_reason": saved_input_reason,
        "research": research,
        "reply_input": None if saved is None else {"input_record_id": selected[0]},
        "answers": answers,
        "decision_source": decision_source,
        "account_labels": labels,
        "current_context": None
        if current is None
        else consultation_context(current[3], current[2], now=current[1].checked_at),
        "current_shares": {}
        if portfolio is None
        else {
            symbol: sum(p.shares for p in portfolio.positions if p.symbol == symbol)
            for symbol in {p.symbol for p in portfolio.positions}
        },
    }


def export(path, store, body, now):
    permission = ExternalAiPermission.model_validate(body)
    value, comparison, portfolio, forecast = _current(path, store, now)
    package = input_package(
        comparison,
        portfolio,
        forecast,
        now=now,
        permission=permission,
        market_evidence=market.consultation_evidence(path, comparison.checked_at),
    )
    record = {
        "package": package,
        "permission": permission.model_dump(mode="json"),
        "decision_run_id": value["run_id"],
    }
    with store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        verify_exchange_records(db)
        identity = save_record(db, "input", record)
        db.commit()
    return _input_view(identity, package)


def _input_view(identity, package):
    # Keep legacy package validation and exchange identities; only the reading view changes.
    manual_prompt(package)
    return {
        "input_record_id": identity,
        "input_snapshot_id": package["input_snapshot_id"],
        "expires_at": package["expires_at"],
        "prompt": readable_consultation_prompt(package),
        "response_mode": CHATGPT_REPORT_MODE,
    }


def save_answer(path, store, body, now):
    if set(body) != {"input_record_id", "answer_json"}:
        raise ValueError("回答JSONと対応する入力を指定してください")
    with store._connect() as db:
        verify_exchange_records(db)
        row = db.execute(
            "SELECT value FROM operational_metadata WHERE key=?",
            ("chatgpt-manual:input:" + body["input_record_id"],),
        ).fetchone()
    if row is None:
        raise ValueError("回答に対応する保存済みの相談入力がありません")
    record = read_record(row[0])
    permission = ExternalAiPermission.model_validate(record["permission"])
    permission.require(permission.checked_at, "manual_chatgpt")
    answer = validate_saved_answer(body["answer_json"], record["package"], now)
    with store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        identity = save_record(
            db,
            "research",
            {
                "input_record_id": body["input_record_id"],
                "original_json": body["answer_json"],
                "saved_at": now.isoformat(),
            },
        )
        db.commit()
    return {
        "research_record_id": identity,
        "saved": True,
        "reviewed": False,
        "answer": answer.model_dump(mode="json"),
    }


def review_saved(path, store, body, now, *, refresh=True):
    if set(body) != {"research_record_id"}:
        raise ValueError("保存した調査結果を指定してください")
    with store._connect() as db:
        verify_exchange_records(db)
        row = db.execute(
            "SELECT value FROM operational_metadata WHERE key=?",
            ("chatgpt-manual:research:" + body["research_record_id"],),
        ).fetchone()
        if row is None:
            raise ValueError("保存した調査結果が見つかりません")
        research = read_record(row[0])
        source = db.execute(
            "SELECT value FROM operational_metadata WHERE key=?",
            ("chatgpt-manual:input:" + research["input_record_id"],),
        ).fetchone()
        record = read_record(source[0])
    if refresh:
        decisions.generate(path, store, now, refresh_consultation=True)
    _value, comparison, portfolio, forecast = _current(path, store, now)
    permission = ExternalAiPermission.model_validate(record["permission"])
    reviewed = review_answer(
        research["original_json"],
        record["package"],
        comparison,
        portfolio,
        forecast,
        now=now,
        permission=permission,
        saved_research=True,
    )
    receipt = {
        "input_record_id": research["input_record_id"],
        "original_json": research["original_json"],
        "review": reviewed,
        "checked_at": now.isoformat(),
    }
    with store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        verify_exchange_records(db)
        identity = save_record(db, "answer", receipt)
        db.commit()
    return {"record_id": identity, "review": reviewed}


def import_answer(path, store, body, now):
    saved = save_answer(path, store, body, now)
    return review_saved(
        path, store, {"research_record_id": saved["research_record_id"]}, now, refresh=False
    )
