"""Manual exchanges reuse the verified decision receipt and encrypted owner."""

from stock_ai.domain import PortfolioState
from stock_ai.operations.chatgpt_manual import (
    ExternalAiPermission,
    _context,
    input_package,
    manual_prompt,
    read_record,
    review_answer,
    save_record,
    verify_exchange_records,
)
from stock_ai.operations.daily import PredictionSnapshot
from stock_ai.operations.personal import PersonalComparison

from . import decisions


def _current(path, store, now):
    value = decisions.view(path, store)
    if (
        not value
        or not value["is_active"]
        or value["outcome"] != "proposal"
        or value["comparison"] is None
    ):
        raise ValueError(
            "最新の原予測・口座・設定の照合を完了してください。未採用モデルは研究用です。"
        )
    frozen = value["frozen_inputs"]
    comparison = PersonalComparison.model_validate(value["comparison"])
    portfolio = PortfolioState.model_validate(frozen["ledger"])
    forecast = PredictionSnapshot.model_validate(frozen["forecast"])
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
        answers = [
            read_record(row[0])["review"]
            for row in db.execute(
                "SELECT value FROM operational_metadata WHERE key LIKE 'chatgpt-manual:answer:%' "
                "ORDER BY rowid DESC LIMIT 20"
            )
        ]
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
        "answers": answers,
        "account_labels": labels,
    }


def export(path, store, body, now):
    permission = ExternalAiPermission.model_validate(body)
    value, comparison, portfolio, forecast = _current(path, store, now)
    package = input_package(comparison, portfolio, forecast, now=now, permission=permission)
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
    return {
        "input_record_id": identity,
        "input_snapshot_id": package["input_snapshot_id"],
        "expires_at": package["expires_at"],
        "prompt": manual_prompt(package),
    }


def import_answer(path, store, body, now):
    if set(body) != {"input_record_id", "answer_json"}:
        raise ValueError("回答JSONと対応する入力を指定してください")
    value, comparison, portfolio, forecast = _current(path, store, now)
    with store._connect() as db:
        verify_exchange_records(db)
        selected = db.execute(
            "SELECT value FROM operational_metadata WHERE key=?", ("chatgpt-manual:selected",)
        ).fetchone()
        if selected is None or selected[0] != body["input_record_id"]:
            raise ValueError("別の入力への回答です。最新の入力で確認してください")
        row = db.execute(
            "SELECT value FROM operational_metadata WHERE key=?",
            ("chatgpt-manual:input:" + selected[0],),
        ).fetchone()
    record = read_record(row[0])
    if record["decision_run_id"] != value["run_id"]:
        raise ValueError("口座・原予測のsnapshotが更新されています")
    permission = ExternalAiPermission.model_validate(record["permission"])
    reviewed = review_answer(
        body["answer_json"],
        record["package"],
        comparison,
        portfolio,
        forecast,
        now=now,
        permission=permission,
    )
    receipt = {
        "input_record_id": body["input_record_id"],
        "original_json": body["answer_json"],
        "review": reviewed,
        "checked_at": now.isoformat(),
    }
    with store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        verify_exchange_records(db)
        # The native owner serializes writes; still compare the selected input in
        # this transaction rather than silently replacing a newer exchange.
        selected = db.execute(
            "SELECT value FROM operational_metadata WHERE key=?", ("chatgpt-manual:selected",)
        ).fetchone()
        if selected is None or selected[0] != body["input_record_id"]:
            raise ValueError("入力が更新されました。最新の入力を確認してください")
        identity = save_record(db, "answer", receipt)
        db.commit()
    return {"record_id": identity, "review": reviewed}
