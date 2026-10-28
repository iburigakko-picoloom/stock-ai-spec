"""Explicit current-balance corrections, appended without rewriting history."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from stock_ai.domain import PortfolioState
from stock_ai.operations.manual_portfolio import (
    ImportedManualPortfolio,
    ManualHolding,
    ManualPortfolio,
    PortfolioExport,
    PortfolioRevision,
    digest,
)
from stock_ai.operations.manual_settings import ManualPersonalSettings
from stock_ai.operations.store import (
    OperationalConflictError,
    _latest_portfolio_connection,
    _reconciliation_base,
    _verify_hashed_row,
)

from . import personal


def view(store):
    ledger = store.latest_portfolio()
    profile = personal.portfolio_view(store)
    settings = personal.read_settings(store)
    return {
        "ledger": None if ledger is None else ledger.model_dump(mode="json"),
        "profile": profile,
        "settings": settings,
    }


def _money(value):
    # Use the existing exact, bounded decimal input contract.
    from pydantic import TypeAdapter

    from stock_ai.operations.manual_portfolio import Money

    return Decimal(TypeAdapter(Money).validate_python(value))


def edit(store, request, now, *, confirm=False):
    required = {
        "base_ledger_id",
        "base_revision_id",
        "base_settings_id",
        "as_of",
        "group",
        "changes",
    }
    if not isinstance(request, dict) or set(request) not in (required, required | {"record"}):
        raise ValueError("Invalid balance edit")
    record = request.get("record")
    if record is not None:
        if (
            not isinstance(record, dict)
            or set(record) != {"date", "reason", "kind"}
            or not isinstance(record["date"], str)
            or not isinstance(record["reason"], str)
            or len(record["reason"]) > 500
            or record["kind"] not in ("deposit", "withdrawal", "correction")
        ):
            raise ValueError("Invalid correction record")
        date.fromisoformat(record["date"])
    identity = "account-edit-" + digest(personal.canonical(request))
    with store._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT * FROM portfolio_states WHERE portfolio_id=?", (identity,)
        ).fetchone()
        if existing is not None and confirm:
            _verify_hashed_row("portfolio_states", existing)
            return {"portfolio_id": identity, "already_confirmed": True}
        current = _latest_portfolio_connection(db)
        profile = store.latest_manual_portfolio()
        saved = personal.read_settings(store, db)
        if current is None or profile is None or saved is None:
            raise ValueError("先に初回残高を登録してください。")
        if (current.portfolio_id, profile.export.revision_id, saved["revision_id"]) != (
            request["base_ledger_id"],
            request["base_revision_id"],
            request["base_settings_id"],
        ):
            raise OperationalConflictError("残高または設定が更新されています。読み直してください。")
        as_of = datetime.fromisoformat(request["as_of"])
        if as_of.utcoffset() is None or not timedelta(0) <= now - as_of <= timedelta(minutes=15):
            raise OperationalConflictError("確認内容の期限が切れました。読み直してください。")
        if as_of <= current.as_of or as_of < profile.export.saved_at:
            raise OperationalConflictError("更新日時を確認して読み直してください。")
        _, executions = _reconciliation_base(db, current, now)
        if executions - set(current.applied_execution_ids):
            raise OperationalConflictError("未反映の約定があります。先に約定を反映してください。")
        value = current.model_dump(mode="json")
        changes = request["changes"]
        buckets = {b["bucket_id"]: b for b in value["account_buckets"]}
        new_accounts = []
        if request["group"] == "cash":
            if not isinstance(changes, list) or len(changes) != len(buckets):
                raise ValueError("全区分の残高を確認してください。")
            cash = []
            for item in changes:
                if (
                    set(item) != {"account_bucket_id", "total", "buying_power"}
                    or item["account_bucket_id"] not in buckets
                ):
                    raise ValueError("Invalid cash bucket")
                total, buying = _money(item["total"]), _money(item["buying_power"])
                if buying > total:
                    raise ValueError("買付余力は現金残高以下の金額を入力してください。")
                cash.append(
                    {
                        "account_bucket_id": item["account_bucket_id"],
                        "available_cash": str(total),
                        "reserved_cash": str(total - buying),
                    }
                )
            value["cash"] = cash
        elif request["group"] == "holdings":
            if not isinstance(changes, list) or len(changes) > 200:
                raise ValueError("Invalid holdings")
            positions = []
            for item in changes:
                if set(item) != {
                    "symbol",
                    "account_bucket_id",
                    "shares",
                    "average_acquisition_price",
                    "market_price",
                }:
                    raise ValueError("Invalid holding")
                if item["account_bucket_id"] not in buckets:
                    classifications = {
                        "new:specified": ("taxable_specified", "withholding"),
                        "new:specified_no": ("taxable_specified", "no_withholding"),
                        "new:general": ("taxable_general", "no_withholding"),
                        "new:nisa": ("nisa", "not_applicable"),
                    }
                    if item["account_bucket_id"] not in classifications:
                        raise ValueError("口座区分を確認してください。")
                    kind, withholding = classifications[item["account_bucket_id"]]
                    matched = next(
                        (
                            b
                            for b in buckets.values()
                            if (b["account_type"], b["withholding_mode"]) == (kind, withholding)
                        ),
                        None,
                    )
                    if matched is None:
                        bucket_id = str(
                            uuid5(
                                NAMESPACE_URL,
                                profile.export.revision.owner + ":" + kind + ":" + withholding,
                            )
                        )
                        template = value["account_buckets"][0]
                        matched = {
                            **template,
                            "bucket_id": bucket_id,
                            "account_type": kind,
                            "withholding_mode": withholding,
                        }
                        value["account_buckets"].append(matched)
                        buckets[bucket_id] = matched
                        value["cash"].append(
                            {
                                "account_bucket_id": bucket_id,
                                "available_cash": "0",
                                "reserved_cash": "0",
                            }
                        )
                        value["tax_states"].append(
                            {
                                "account_bucket_id": bucket_id,
                                "tax_year": now.astimezone(personal.JST).year,
                            }
                        )
                        new_accounts.append(
                            {
                                "id": bucket_id,
                                "name": "SBI証券",
                                "account_type": kind,
                                "withholding_mode": withholding,
                                "available_cash_yen": "0",
                            }
                        )
                    item = {**item, "account_bucket_id": matched["bucket_id"]}
                if type(item["shares"]) is not int or not 0 < item["shares"] <= 1_000_000_000:
                    raise ValueError("株数は正の整数で入力してください。")
                _money(item["average_acquisition_price"])
                _money(item["market_price"])
                ManualHolding.model_validate(
                    {
                        "account_id": item["account_bucket_id"],
                        "symbol": item["symbol"],
                        "shares": item["shares"],
                        "average_acquisition_price_yen": item["average_acquisition_price"],
                    }
                )
                positions.append(item)
            value["positions"] = positions
        elif request["group"] == "nisa":
            if not isinstance(changes, list):
                raise ValueError("Invalid NISA values")
            ids = {b["bucket_id"] for b in buckets.values() if b["account_type"] == "nisa"}
            if len(changes) != len(ids) or {x["account_bucket_id"] for x in changes} != ids:
                raise ValueError("NISAの区分を確認してください。")
            for item in changes:
                if set(item) != {"account_bucket_id", "annual", "lifetime"}:
                    raise ValueError("Invalid NISA fields")
                if _money(item["annual"]) > 2_400_000 or _money(item["lifetime"]) > 12_000_000:
                    raise ValueError("成長投資枠の残枠は年間240万円・保有限度1200万円以内です。")
                tax = next(
                    x
                    for x in value["tax_states"]
                    if x["account_bucket_id"] == item["account_bucket_id"]
                )
                tax.update(
                    nisa_annual_capacity_user_input=item["annual"],
                    nisa_lifetime_capacity_user_input=item["lifetime"],
                )
            if (
                sum((_money(x["annual"]) for x in changes), Decimal(0)) > 2_400_000
                or sum((_money(x["lifetime"]) for x in changes), Decimal(0)) > 12_000_000
            ):
                raise ValueError("成長投資枠の残枠合計を確認してください。")
        else:
            raise ValueError("Unknown edit group")
        if record is not None and record["kind"] != "correction":
            if request["group"] != "cash":
                raise ValueError("入出金は現金の変更から記録してください。")
            difference = sum(
                (_money(x["available_cash"]) for x in value["cash"]), Decimal(0)
            ) - sum((x.available_cash for x in current.cash), Decimal(0))
            if (record["kind"] == "deposit" and difference <= 0) or (
                record["kind"] == "withdrawal" and difference >= 0
            ):
                raise ValueError("入出金の種別と金額を確認してください。")
        value.update(portfolio_id=identity, as_of=as_of.isoformat())
        updated = PortfolioState.model_validate(value)
        if not confirm:
            return {
                "before": current.model_dump(mode="json"),
                "after": updated.model_dump(mode="json"),
                "request": request,
            }

        # Keep old manual revisions, initial ledger and executions byte-for-byte.
        # Append matching current inputs and settings in the SAME transaction.
        manual = profile.portfolio.model_dump(mode="json")
        manual["accounts"].extend(new_accounts)
        if {x["id"] for x in manual["accounts"]} != set(buckets):
            raise OperationalConflictError("登録口座と台帳の対応を確認してください。")
        cash_map = updated.cash_map()
        if request["group"] == "cash":
            manual["accounts"] = [
                {**x, "available_cash_yen": str(cash_map[x["id"]].available_cash)}
                for x in manual["accounts"]
            ]
        if request["group"] == "holdings":
            manual["holdings"] = [
                {
                    "account_id": x.account_bucket_id,
                    "symbol": x.symbol,
                    "shares": x.shares,
                    "average_acquisition_price_yen": str(x.average_acquisition_price),
                }
                for x in updated.positions
            ]
            manual["holdings_status"] = "recorded" if updated.positions else "none"
        revision = PortfolioRevision(
            owner=profile.export.revision.owner,
            parent=profile.export.revision_id,
            portfolio=ManualPortfolio.model_validate(manual),
        )
        revision_json = personal.canonical(revision.model_dump(mode="json"))
        exported = PortfolioExport(
            schema_version="manual-portfolio-export-v1",
            revision_id=digest(revision_json),
            revision_sequence=profile.export.revision_sequence + 1,
            saved_at=now,
            revision_json=revision_json,
        )
        export_json = personal.canonical(exported.model_dump(mode="json"))
        imported = ImportedManualPortfolio(
            export_sha256=digest(export_json), export_json=export_json, received_at=now
        )
        settings = {**saved["settings"], "portfolio_revision_id": exported.revision_id}
        settings["accounts"] = [
            *settings["accounts"],
            *[
                {
                    "account_id": x["id"],
                    "reserved_cash_yen": "0",
                    "pending_activity": "unknown",
                    "realized_gain_ytd": None,
                    "realized_loss_ytd": None,
                    "loss_carryforward_user_input": None,
                    "nisa_annual_capacity_user_input": None,
                    "nisa_lifetime_capacity_user_input": None,
                }
                for x in new_accounts
            ],
        ]
        tax_map = updated.tax_state_map()
        if request["group"] == "cash":
            settings["cash_basis"] = "total_including_reserved"
            settings["accounts"] = [
                {**x, "reserved_cash_yen": str(cash_map[x["account_id"]].reserved_cash)}
                for x in settings["accounts"]
            ]
        if request["group"] == "nisa":
            settings["accounts"] = [
                {
                    **x,
                    "nisa_annual_capacity_user_input": tax_map[x["account_id"]].model_dump(
                        mode="json"
                    )["nisa_annual_capacity_user_input"],
                    "nisa_lifetime_capacity_user_input": tax_map[x["account_id"]].model_dump(
                        mode="json"
                    )["nisa_lifetime_capacity_user_input"],
                }
                for x in settings["accounts"]
            ]
        checked = ManualPersonalSettings.model_validate(settings)
        checked.validate_portfolio(exported.revision_id, revision.portfolio)
        if request["group"] == "nisa" and "nisa_capacity_out_of_range" in checked.missing_fields(
            revision.portfolio
        ):
            raise ValueError("成長投資枠の残枠合計は年間240万円・保有限度1200万円以内です。")
        settings_value = {
            "parent": saved["revision_id"],
            "sequence": saved["sequence"] + 1,
            "saved_at": now.isoformat(),
            "settings": checked.model_dump(mode="json"),
        }
        payload = personal.canonical(settings_value)
        store._insert_immutable(
            db,
            table="manual_portfolio_imports",
            identity_column="export_sha256",
            identity=imported.export_sha256,
            columns={
                "revision_id": exported.revision_id,
                "revision_sequence": exported.revision_sequence,
                "owner_scope_hash": imported.owner_scope_hash,
            },
            payload=personal.canonical(imported.model_dump(mode="json")),
        )
        db.execute(
            "INSERT INTO mobile_personal_settings VALUES(?,?,?,?)",
            (settings_value["sequence"], digest(payload), payload, digest(payload)),
        )
        store._insert_immutable(
            db,
            table="portfolio_states",
            identity_column="portfolio_id",
            identity=identity,
            columns={"as_of": as_of.isoformat(), "created_at": now.isoformat()},
            payload=personal.canonical(updated.model_dump(mode="json")),
        )
        if record is not None:
            payload = personal.canonical({"portfolio_id": identity, "record": record})
            db.execute(
                "INSERT INTO operational_metadata(key,value) VALUES(?,?)",
                (
                    "account_edit_record:" + identity,
                    personal.canonical({"payload": payload, "sha256": digest(payload)}),
                ),
            )
        db.commit()
        return {"portfolio_id": identity, "already_confirmed": False}
