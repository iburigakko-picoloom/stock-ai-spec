"""Generate a test-only capsule using the pinned legacy implementation.

Run in an exported legacy source tree, with its src/ and root on PYTHONPATH.
Only a new directory under this checkout's .demo-artifacts is writable. There
are no provider requests, real accounts, fitted models or real executions.
"""

import asyncio
import faulthandler
import hashlib
import json
import random
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mobile.python import runtime

from stock_ai.domain import (
    ExecutionRecord,
    ExecutionStatus,
    TradeSide,
    UserDecision,
    UserDecisionLine,
)
from stock_ai.operations.fixture import bootstrap_goal5_fixture

destination = Path(sys.argv[1]).resolve()
task_root = Path(__file__).resolve().parents[2]
allowed = task_root / ".demo-artifacts"
if not destination.is_relative_to(allowed) or destination == allowed or destination.exists():
    raise ValueError("Use a fresh isolated fixture output under .demo-artifacts")
pins = json.loads((task_root / "scripts/fixtures/android-upgrade-source.json").read_text())
legacy_root = Path.cwd().resolve()
if Path(runtime.__file__).resolve() != legacy_root / "mobile/python/runtime.py":
    raise ValueError("Only the pinned legacy runtime may generate this fixture")
for name, expected in pins["source_sha256"].items():
    if hashlib.sha256((legacy_root / name).read_bytes()).hexdigest() != expected:
        raise ValueError("Legacy source bytes changed: " + name)
source_receipt = json.loads((legacy_root / "upgrade-source.json").read_text())
if source_receipt["source_commit"] != pins["source_commit"]:
    raise ValueError("Legacy source commit differs")
for name, expected in source_receipt["files_sha256"].items():
    if hashlib.sha256((legacy_root / name).read_bytes()).hexdigest() != expected:
        raise ValueError("Exported legacy source bytes changed: " + name)
faulthandler.dump_traceback_later(60)
runtime.STATE = destination
runtime.initialize()
instant = datetime(2026, 2, 12, 11, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
store = runtime._app.state.store
proposal_id = bootstrap_goal5_fixture(store, as_of=instant)
proposal = store.proposal(proposal_id)
decision = UserDecision(
    decision_id="TEST_ONLY-upgrade-decision",
    proposal_id=proposal_id,
    version=1,
    saved_at=instant + timedelta(minutes=10),
    lines=tuple(
        UserDecisionLine(
            proposal_line_id=line.line_id, selected_target_shares=line.recommended_shares
        )
        for line in proposal.lines
    ),
)
store.save_decision(decision)
line = next(line for line in proposal.lines if line.share_difference < 0)
execution = ExecutionRecord(
    execution_id="TEST_ONLY-upgrade-fill",
    decision_id=decision.decision_id,
    executed_at=instant + timedelta(hours=1),
    symbol=line.symbol,
    account_bucket_id=line.account_bucket_id,
    status=ExecutionStatus.FILLED,
    side=TradeSide.SELL,
    ordered_shares=-line.share_difference,
    filled_shares=-line.share_difference,
    average_fill_price=line.reference_price,
    source="manual",
)
store.append_execution(execution)
store.apply_unapplied_executions(
    next_as_of=instant + timedelta(days=1),
    next_portfolio_id="TEST_ONLY-upgrade-next-day",
    created_at=instant + timedelta(days=1, minutes=1),
)
taxable, nisa = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
profile = {
    "schema_version": "manual-portfolio-v1",
    "holdings_status": "recorded",
    "investment_budget_yen": "1000000",
    "maximum_drawdown_percent": 20.0,
    "accounts": [
        {
            "id": taxable,
            "name": "TEST_ONLY課税口座",
            "account_type": "taxable_specified",
            "withholding_mode": "withholding",
            "available_cash_yen": "500000",
        },
        {
            "id": nisa,
            "name": "TEST_ONLY非課税口座",
            "account_type": "nisa",
            "withholding_mode": "not_applicable",
            "available_cash_yen": "500000",
        },
    ],
    "holdings": [
        {
            "account_id": taxable,
            "symbol": "7203",
            "shares": 100,
            "average_acquisition_price_yen": "2500.0",
        },
        {
            "account_id": nisa,
            "symbol": "9432",
            "shares": 100,
            "average_acquisition_price_yen": "150.0",
        },
    ],
}
response = asyncio.run(runtime.request("POST", "/api/v1/mobile/portfolio", json.dumps(profile)))
assert response["status"] == 200, response
settings = {
    "schema_version": "manual-personal-settings-v1",
    "portfolio_revision_id": response["body"]["revision_id"],
    "cash_basis": "deployable_after_reserved",
    "budget_basis": "maximum_total_equity_market_value",
    "nisa_capacity_basis": "remaining_purchase_notional_no_same_day_sale_restore",
    "tax_year": 2026,
    "accounts": [
        {
            "account_id": account,
            "reserved_cash_yen": "10000",
            "pending_activity": "none",
            "realized_gain_ytd": "12345" if i == 0 else None,
            "realized_loss_ytd": "5432" if i == 0 else None,
            "loss_carryforward_user_input": "1000" if i == 0 else None,
            "nisa_annual_capacity_user_input": "1000000" if i == 1 else None,
            "nisa_lifetime_capacity_user_input": "10000000" if i == 1 else None,
        }
        for i, account in enumerate([taxable, nisa])
    ],
    "cost_assumptions": {
        "commission_fixed_yen": "0",
        "commission_bps": "0",
        "minimum_commission_yen": "0",
        "zero_commission_confirmed": True,
        "full_spread_bps": "8",
        "slippage_bps": "4",
        "impact_bps_at_full_adv": "10",
    },
    "tax_assumptions": {
        "effective_from": "2026-01-01",
        "taxable_rate_percent": "20.315",
        "nisa_opportunity_cost_percent": "1.5",
    },
    "research_decision_policy": "daily-decision-engine-v2",
    "research_conditions_reviewed": False,
}
settings_response = asyncio.run(
    runtime.request(
        "POST",
        "/api/v1/mobile/personal/settings",
        json.dumps({"expected_revision_id": None, "settings": settings}),
    )
)
assert settings_response["status"] == 200, settings_response
with closing(sqlite3.connect(destination / "mobile.sqlite3")) as database:
    database.execute(
        "CREATE TABLE TEST_ONLY_upgrade_typed_cells ("
        "k TEXT PRIMARY KEY,i INTEGER,f REAL,s TEXT,b BLOB,n)"
    )
    database.execute(
        "INSERT INTO TEST_ONLY_upgrade_typed_cells VALUES(?,?,?,?,?,?)",
        ("sentinel", 17, 0.125, "保存確認 😀", random.Random(1729).randbytes(600000), None),
    )
    database.commit()
store.verify_integrity()
with closing(sqlite3.connect(destination / "mobile.sqlite3")) as database:
    for table in ("market_batches", "market_days", "mobile_models"):
        if database.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0] != 0:
            raise ValueError("Only empty market/model stores are allowed in the upgrade fixture")
payload = runtime.export_state()
output = destination / "legacy-input.b64"
output.write_text(payload, encoding="ascii")
assert 3 * 256 * 1024 < len(payload) < 4 * 1024 * 1024
metadata = {
    "synthetic_only": True,
    "model_count": 0,
    "characters": len(payload),
    "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    "proposal_id": proposal_id,
    "decision_id": decision.decision_id,
    "execution_id": execution.execution_id,
    "execution_applied_once": True,
    "portfolio": response["body"],
    "settings": settings_response["body"],
    "stock_ai_source": __import__("stock_ai").__file__,
    "runtime_source": runtime.__file__,
}
(destination / "legacy-input.json").write_text(
    json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({"synthetic_only": True, "characters": len(payload), "model_count": 0}))
faulthandler.cancel_dump_traceback_later()
