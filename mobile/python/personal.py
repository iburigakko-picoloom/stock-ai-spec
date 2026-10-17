"""Device-local revisions, reviewed initial balances and read-only comparison."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from stock_ai.domain import PortfolioState
from stock_ai.operations.daily import content_id
from stock_ai.operations.manual_portfolio import (
    ImportedManualPortfolio,
    ManualPortfolio,
    PortfolioExport,
    PortfolioRevision,
    digest,
    strict_json,
)
from stock_ai.operations.manual_settings import ManualPersonalSettings
from stock_ai.operations.personal import PersonalComparisonRequest, compare_stored_personal
from stock_ai.operations.store import OperationalConflictError, OperationalIntegrityError

from .market import SQLiteSource
from .storage import connect

JST = ZoneInfo("Asia/Tokyo")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def initialize(store, legacy_path, now):
    with connect(store.path) as db:
        db.executescript(
            "CREATE TABLE IF NOT EXISTS mobile_personal_settings("
            "sequence INTEGER PRIMARY KEY, revision_id TEXT NOT NULL UNIQUE,"
            "payload TEXT NOT NULL, content_hash TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS mobile_initial_previews("
            "preview_id TEXT PRIMARY KEY, payload TEXT NOT NULL, content_hash TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS mobile_initial_confirmations("
            "preview_id TEXT PRIMARY KEY, confirmed_at TEXT NOT NULL);"
        )
    # Preserve the original 0.1.11 input table verbatim. Migrate the latest input
    # into the shared revision store; never turn a draft into an account ledger.
    if store.latest_manual_portfolio() is None:
        with connect(legacy_path) as db:
            row = db.execute(
                "SELECT saved_at,payload FROM manual_inputs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is not None:
            saved_at = datetime.fromisoformat(row[0])
            if saved_at.tzinfo is None or saved_at > now:
                raise ValueError("Invalid legacy input timestamp")
            save_portfolio(store, ManualPortfolio.model_validate_json(row[1]), None, saved_at)
    settings = read_settings(store)
    if settings is not None:
        ManualPersonalSettings.model_validate(settings["settings"])


def portfolio_view(store):
    item = store.latest_manual_portfolio()
    return None if item is None else {
        "revision_id": item.export.revision_id,
        "saved_at": item.export.saved_at.isoformat(),
        "portfolio": item.portfolio.model_dump(mode="json"),
    }


def save_portfolio(store, profile, expected, now):
    previous = store.latest_manual_portfolio()
    if expected != (None if previous is None else previous.export.revision_id):
        raise OperationalConflictError("口座・保有が更新されています。読み直してください。")
    revision = PortfolioRevision(
        owner=(
            "android-local-" + str(uuid4()) if previous is None
            else previous.export.revision.owner
        ),
        parent=expected, portfolio=profile,
    )
    revision_json = canonical(revision.model_dump(mode="json"))
    exported = PortfolioExport(
        schema_version="manual-portfolio-export-v1", revision_id=digest(revision_json),
        revision_sequence=1 if previous is None else previous.export.revision_sequence + 1,
        saved_at=now, revision_json=revision_json,
    )
    export_json = canonical(exported.model_dump(mode="json"))
    store.import_manual_portfolio(ImportedManualPortfolio(
        export_sha256=digest(export_json), export_json=export_json, received_at=now,
    ))
    return portfolio_view(store)


def read_settings(store, connection=None):
    if connection is None:
        with connect(store.path) as db:
            return read_settings(store, db)
    rows = connection.execute(
        "SELECT sequence,revision_id,payload,content_hash "
        "FROM mobile_personal_settings ORDER BY sequence"
    ).fetchall()
    previous = None
    result = None
    for expected_sequence, (sequence, identity, payload, hashed) in enumerate(rows, 1):
        if digest(payload) != hashed or identity != hashed:
            raise OperationalIntegrityError("Saved personal settings changed")
        value = strict_json(payload)
        if (
            value["parent"] != previous or sequence != value["sequence"]
            or sequence != expected_sequence
        ):
            raise OperationalIntegrityError("Saved settings revision chain changed")
        ManualPersonalSettings.model_validate(value["settings"])
        result = {"revision_id": identity, **value}
        previous = identity
    return result


def settings_view(store):
    profile = portfolio_view(store)
    return {"saved": read_settings(store), "current_portfolio": profile}


def save_settings(store, settings, expected, now):
    profile = portfolio_view(store)
    if profile is None:
        raise ValueError("Save portfolio input first")
    settings.validate_portfolio(
        profile["revision_id"], ManualPortfolio.model_validate(profile["portfolio"])
    )
    with connect(store.path) as db:
        db.execute("BEGIN IMMEDIATE")
        current = read_settings(store, db)
        if expected != (None if current is None else current["revision_id"]):
            raise OperationalConflictError("補足設定が更新されています。読み直してください。")
        latest = db.execute(
            "SELECT revision_id FROM manual_portfolio_imports "
            "ORDER BY revision_sequence DESC LIMIT 1"
        ).fetchone()
        if latest[0] != settings.portfolio_revision_id:
            raise OperationalConflictError("口座・保有が更新されています。読み直してください。")
        value = {
            "parent": expected, "sequence": 1 if current is None else current["sequence"] + 1,
            "saved_at": now.isoformat(), "settings": settings.model_dump(mode="json"),
        }
        payload = canonical(value)
        db.execute("INSERT INTO mobile_personal_settings VALUES(?,?,?,?)", (
            value["sequence"], digest(payload), payload, digest(payload),
        ))
    return settings_view(store)


def input_state(store, now):
    profile = portfolio_view(store)
    saved = read_settings(store)
    gaps = []
    compiled = None
    if profile is None:
        gaps.append("manual_input")
    elif datetime.fromisoformat(profile["saved_at"]) > now:
        gaps.append("input_timestamp_future")
    if saved is None:
        gaps.append("personal_settings")
    elif datetime.fromisoformat(saved["saved_at"]) > now:
        gaps.append("input_timestamp_future")
    if profile is not None and saved is not None:
        settings = ManualPersonalSettings.model_validate(saved["settings"])
        portfolio = ManualPortfolio.model_validate(profile["portfolio"])
        if settings.portfolio_revision_id != profile["revision_id"]:
            gaps.append("settings_outdated")
        else:
            settings.validate_portfolio(profile["revision_id"], portfolio)
            gaps.extend(settings.missing_fields(portfolio))
            if settings.tax_year is not None and settings.tax_year != now.astimezone(JST).year:
                gaps.append("tax_year_outdated")
            effective = settings.tax_assumptions.effective_from
            if effective is not None and effective > now.astimezone(JST).date():
                gaps.append("tax_policy_future")
            if not gaps:
                compiled = settings.compile(profile["revision_id"], portfolio)
    elif profile is not None:
        gaps.extend(ManualPortfolio.model_validate(profile["portfolio"]).missing_fields)
    return profile, saved, tuple(sorted(set(gaps))), compiled


def reference_prices(market_path, symbols, now):
    if not symbols:
        return {"date": None, "prices": {}, "source_hash": None}
    frame = SQLiteSource(market_path).latest_closed_prices(now)
    if frame.empty:
        raise ValueError("held_prices_missing")
    frame = frame.loc[
        frame.provider_code.astype(str).str.fullmatch(r"[0-9A-Z]{4}0")
        & (pd.to_datetime(frame.trading_date).dt.date < now.astimezone(JST).date())
    ]
    if frame.empty:
        raise ValueError("held_prices_missing")
    day = pd.to_datetime(frame.trading_date).dt.date.max()
    if (now.astimezone(JST).date() - day).days > 5:
        raise ValueError("held_prices_stale")
    frame = frame.loc[pd.to_datetime(frame.trading_date).dt.date == day]
    prices = {}
    sources = []
    for symbol in symbols:
        rows = frame.loc[frame.symbol == symbol]
        if len(rows) != 1:
            raise ValueError("held_prices_missing")
        row = rows.iloc[0]
        price = Decimal(str(row.raw_close))
        if not price.is_finite() or price <= 0:
            raise ValueError("held_prices_missing")
        prices[symbol] = str(price)
        sources.append([symbol, str(row.source_record_hash), str(row.available_at)])
    return {"date": str(day), "prices": prices, "source_hash": content_id(sources)}


def preview_initial(store, market_path, now, *, persist):
    profile, saved, gaps, compiled = input_state(store, now)
    gaps = list(gaps)
    ledger_exists = store.latest_portfolio() is not None
    if ledger_exists:
        gaps.append("ledger_already_initialized")
    if store.executions():
        gaps.append("executions_already_recorded")
    prices = {"date": None, "prices": {}, "source_hash": None}
    if profile is not None and not ledger_exists:
        try:
            prices = reference_prices(
                market_path, ManualPortfolio.model_validate(profile["portfolio"]).holding_symbols,
                now,
            )
        except ValueError as error:
            reason = str(error)
            gaps.append(reason if reason.startswith("held_prices_") else "held_prices_invalid")
    ledger = None
    if not gaps:
        assert profile is not None and saved is not None and compiled is not None
        value = ManualPortfolio.model_validate(profile["portfolio"])
        supplements = ManualPersonalSettings.model_validate(saved["settings"])
        cash = []
        for account in value.accounts:
            extra = next(x for x in supplements.accounts if x.account_id == account.id)
            assert account.available_cash_yen is not None and extra.reserved_cash_yen is not None
            reserved = Decimal(extra.reserved_cash_yen)
            available = Decimal(account.available_cash_yen)
            if supplements.cash_basis == "deployable_after_reserved":
                available += reserved
            cash.append({"account_bucket_id": account.id,
                         "available_cash": str(available), "reserved_cash": str(reserved)})
        ledger = PortfolioState.model_validate({
            "portfolio_id": "initial-" + content_id({
                "profile": profile["revision_id"], "settings": saved["revision_id"],
                "prices": prices, "as_of": now.isoformat(),
            }),
            "as_of": now, "accounts": [
                {"account_id": x.id, "broker": "manual", "display_name": x.name}
                for x in value.accounts
            ],
            "account_buckets": [
                {"bucket_id": x.id, "account_id": x.id, "account_type": x.account_type,
                 "withholding_mode": x.withholding_mode,
                 "fee_policy_id": compiled.cost_policy.policy_id,
                 "tax_policy_id": compiled.tax_policy.policy_id} for x in value.accounts
            ],
            "positions": [
                {"symbol": x.symbol, "account_bucket_id": x.account_id, "shares": x.shares,
                 "average_acquisition_price": x.average_acquisition_price_yen,
                 "market_price": prices["prices"][x.symbol]} for x in value.holdings
            ],
            "cash": cash, "tax_states": [x.model_dump() for x in compiled.tax_inputs],
        }).model_dump(mode="json")
    value = {
        "created_at": now.isoformat(),
        "portfolio_revision_id": None if profile is None else profile["revision_id"],
        "settings_revision_id": None if saved is None else saved["revision_id"],
        "blocking_reasons": sorted(set(gaps)), "prices": prices,
        "portfolio": ledger, "research_only": True,
    }
    payload = canonical(value)
    preview_id = digest(payload)
    if persist:
        with connect(store.path) as db:
            db.execute("INSERT OR IGNORE INTO mobile_initial_previews VALUES(?,?,?)", (
                preview_id, payload, preview_id,
            ))
    return {"preview_id": preview_id, **value}


def confirm_initial(store, market_path, preview_id, confirmed, now):
    if confirmed is not True:
        raise ValueError("Explicit initial ledger confirmation required")
    with connect(store.path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT payload,content_hash FROM mobile_initial_previews WHERE preview_id=?",
            (preview_id,),
        ).fetchone()
        if row is None or digest(row[0]) != preview_id or row[1] != preview_id:
            raise ValueError("Invalid initial ledger preview")
        value = strict_json(row[0])
        if value["blocking_reasons"] or value["portfolio"] is None:
            raise ValueError("Incomplete initial ledger preview")
        if db.execute("SELECT 1 FROM mobile_initial_confirmations WHERE preview_id=?",
                      (preview_id,)).fetchone():
            return {"portfolio_id": value["portfolio"]["portfolio_id"], "already_confirmed": True}
        if db.execute("SELECT 1 FROM portfolio_states LIMIT 1").fetchone():
            raise OperationalConflictError("初回台帳は確定済みです。上書きできません。")
        created = datetime.fromisoformat(value["created_at"])
        if not timedelta(0) <= now - created <= timedelta(minutes=15):
            raise OperationalConflictError("確認内容の有効期限が切れました。作り直してください。")
        current = preview_initial(store, market_path, now, persist=False)
        if (
            current["blocking_reasons"]
            or current["portfolio_revision_id"] != value["portfolio_revision_id"]
            or current["settings_revision_id"] != value["settings_revision_id"]
            or current["prices"] != value["prices"]
        ):
            raise OperationalConflictError(
                "入力または価格が更新されています。確認し直してください。"
            )
        portfolio = PortfolioState.model_validate(value["portfolio"])
        rebuilt = {
            **current["portfolio"], "portfolio_id": portfolio.portfolio_id,
            "as_of": portfolio.as_of.isoformat().replace("+00:00", "Z"),
        }
        if portfolio.as_of != created or rebuilt != value["portfolio"]:
            raise OperationalConflictError("確認内容が入力と一致しません。作り直してください。")
        payload = canonical(portfolio.model_dump(mode="json"))
        db.execute("INSERT INTO portfolio_states VALUES(?,?,?,?,?)", (
            portfolio.portfolio_id, portfolio.as_of.isoformat(), digest(payload), payload,
            now.isoformat(),
        ))
        db.execute("INSERT INTO mobile_initial_confirmations VALUES(?,?)", (
            preview_id, now.isoformat(),
        ))
        db.execute("INSERT OR REPLACE INTO operational_metadata VALUES(?,?)", (
            "runtime_mode", "RESEARCH_ONLY",
        ))
    return {"portfolio_id": portfolio.portfolio_id, "already_confirmed": False}


def readiness(store, market_path, now):
    profile, saved, gaps, compiled = input_state(store, now)
    request = PersonalComparisonRequest(
        checked_at=now, maximum_input_age_hours=72, settings=compiled,
    )
    comparison = compare_stored_personal(store, request, now=now)
    return {
        "portfolio_revision_id": None if profile is None else profile["revision_id"],
        "settings_revision_id": None if saved is None else saved["revision_id"],
        "input_gaps": list(gaps), "comparison": comparison.model_dump(mode="json"),
        "initial_ledger": preview_initial(store, market_path, now, persist=False),
        "research_only": True, "order_submission": False,
    }


def initial_reference(store):
    ledger = store.latest_portfolio()
    if ledger is None:
        return None
    with connect(store.path) as db:
        rows = db.execute(
            "SELECT p.preview_id,p.payload,p.content_hash,c.confirmed_at "
            "FROM mobile_initial_previews p JOIN mobile_initial_confirmations c "
            "ON p.preview_id=c.preview_id"
        ).fetchall()
    for identity, payload, hashed, confirmed_at in rows:
        if digest(payload) != hashed or identity != hashed:
            raise OperationalIntegrityError("Initial ledger receipt changed")
        value = strict_json(payload)
        if value["portfolio"]["portfolio_id"] == ledger.portfolio_id:
            return {"confirmedAt": confirmed_at, "referencePriceDate": value["prices"]["date"]}
    return None
