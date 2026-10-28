"""Create synthetic, current-day Android record fixtures in a fresh temporary state."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from mobile.python import runtime
from tests.conftest import candidate, decision_engine, decision_policy_snapshot, portfolio

from stock_ai.domain import Position, UserDecision, UserDecisionLine
from stock_ai.operations import create_app
from stock_ai.operations.models import AutomationJobRecord

INTENT = {"X-Stock-AI-Intent": "manual-record"}


def response(client: TestClient, path: str) -> object:
    value = client.get(path)
    if value.status_code != 200:
        raise RuntimeError(f"Synthetic fixture read failed: {path}, {value.status_code}")
    return value.json()


def create_linked(work: Path) -> dict[str, object]:
    runtime.STATE = work
    runtime.initialize()
    store = runtime._app.state.store
    now = (datetime.now(ZoneInfo("Asia/Tokyo")) - timedelta(seconds=20)).replace(microsecond=123456)
    state = portfolio(
        positions=(
            Position(
                symbol="B",
                account_bucket_id="bucket",
                shares=100,
                average_acquisition_price=Decimal("900.01"),
                market_price=Decimal("1000.00"),
            ),
        ),
        cash=Decimal("250000.75"),
    ).model_copy(update={"as_of": now})
    state = state.model_copy(
        update={
            "cash": tuple(
                row.model_copy(update={"reserved_cash": Decimal("10000.25")}) for row in state.cash
            )
        }
    )
    engine = decision_engine()
    proposal = engine.propose(
        portfolio=state,
        candidates=(candidate("B", 0.2),),
        generated_at=now,
        model_bundle_version="test-model-v1",
    )
    store.append_portfolio(state, created_at=now)
    store.archive_proposal(
        proposal, archived_at=now, decision_policy=decision_policy_snapshot(proposal, engine.config)
    )
    decision = UserDecision(
        decision_id="synthetic-record-reader",
        proposal_id=proposal.proposal_id,
        version=1,
        saved_at=now.astimezone(UTC),
        lines=tuple(
            UserDecisionLine(
                proposal_line_id=line.line_id, selected_target_shares=line.recommended_shares
            )
            for line in proposal.lines
        ),
    )
    store.save_decision(decision)
    note = store.save_stock_note(
        "7203", "SYNTHETIC_UI_TEST: 為替と決算\n非公開のメモ 📝", None, now
    )
    with TestClient(
        create_app(store.path, clock=lambda: now + timedelta(seconds=1)),
        base_url="http://127.0.0.1",
    ) as client:
        execution = response(client, "/api/v1/execution-context")
        fill = client.post(
            "/api/v1/decisions/synthetic-record-reader/executions",
            json={
                "executionId": "synthetic-record-fill",
                "executedAt": now.astimezone(UTC).isoformat(),
                "symbol": "B",
                "accountBucketId": "bucket",
                "side": "BUY",
                "status": "partially_filled",
                "orderedShares": 200,
                "filledShares": 100,
                "averageFillPrice": "1000.02",
                "actualCommission": "101.25",
                "actualOtherCost": "0.50",
                "taxWithheld": "0",
                "confirmDifference": True,
            },
            headers=INTENT,
        )
        if fill.status_code != 201:
            raise RuntimeError(f"Synthetic fill failed: {fill.status_code}")
        applied = client.post(
            "/api/v1/portfolio/apply-executions",
            json={
                "nextPortfolioId": "synthetic-after-fill",
                "nextAsOf": (now + timedelta(milliseconds=500)).astimezone(UTC).isoformat(),
            },
            headers=INTENT,
        )
        if applied.status_code != 200:
            raise RuntimeError(f"Synthetic fill application failed: {applied.status_code}")
        raw = json.dumps(
            {
                "portfolio_id": "synthetic-after-fill",
                "record": {
                    "date": now.date().isoformat(),
                    "kind": "correction",
                    "reason": "SYNTHETIC_UI_TEST: 調整理由",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        store.set_metadata(
            "account_edit_record:synthetic-after-fill",
            json.dumps({"payload": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest()}),
        )
        for i in range(2):
            start = (now - timedelta(minutes=i + 1)).astimezone(UTC)
            store.append_job(
                AutomationJobRecord(
                    run_id=f"synthetic-job-{i}",
                    idempotency_key=f"synthetic-job-{i}",
                    business_date=now.date(),
                    stage="prediction",
                    status="BLOCKED",
                    started_at=start,
                    finished_at=start + timedelta(seconds=1),
                    data_as_of=start,
                    reason_code="SYNTHETIC_UI_TEST",
                )
            )
        paths = (
            "/api/v1/home/ledger",
            "/api/v1/executions",
            "/api/v1/portfolio/history",
            "/api/v1/jobs",
        )
        views = {path: response(client, path) for path in paths}
        views["/api/v1/home/ledger"]["initialLedger"] = None
        state_archive = runtime.export_state()
        trade = {
            "executionId": "synthetic-overlay-second-fill",
            "executedAt": (now + timedelta(milliseconds=600)).isoformat(),
            "symbol": "B",
            "accountBucketId": "bucket",
            "side": "BUY",
            "status": "filled",
            "orderedShares": 100,
            "filledShares": 100,
            "averageFillPrice": "1000.02",
            "actualCommission": "1.25",
            "actualOtherCost": "0.50",
            "taxWithheld": "0",
            "confirmDifference": True,
        }
        apply = {
            "nextPortfolioId": "synthetic-overlay-after",
            "nextAsOf": (now + timedelta(milliseconds=800)).isoformat(),
        }
        trade_reply = client.post(
            "/api/v1/decisions/synthetic-record-reader/executions", json=trade, headers=INTENT
        )
        apply_reply = client.post("/api/v1/portfolio/apply-executions", json=apply, headers=INTENT)
        if trade_reply.status_code != 201 or apply_reply.status_code != 200:
            raise RuntimeError("Synthetic second fill failed")
        after = {path: response(client, path) for path in paths}
        after["/api/v1/home/ledger"]["initialLedger"] = None
        return {
            "synthetic_only": True,
            "state": state_archive,
            "expected_execution": execution,
            "expected_note": note,
            "expected_views": views,
            "trade_body": trade,
            "apply_body": apply,
            "expected_trade": trade_reply.json(),
            "expected_apply": apply_reply.json(),
            "expected_after": after,
        }


def create_manual(work: Path) -> dict[str, object]:
    runtime.STATE = work
    runtime.initialize()
    store = runtime._app.state.store
    now = datetime.now(UTC) - timedelta(minutes=5)
    state = portfolio(cash=Decimal("250000")).model_copy(update={"as_of": now})
    store.append_portfolio(state, created_at=now)
    with TestClient(
        create_app(store.path, clock=lambda: now + timedelta(minutes=3)),
        base_url="http://127.0.0.1",
    ) as client:
        value = {
            "synthetic_only": True,
            "state": runtime.export_state(),
            "context": response(client, "/api/v1/execution-entry-context"),
        }
        body = {
            "executionId": "native-manual",
            "executedAt": (now + timedelta(minutes=1)).isoformat(),
            "symbol": "7203",
            "accountBucketId": "bucket",
            "side": "BUY",
            "status": "filled",
            "orderedShares": 100,
            "filledShares": 100,
            "averageFillPrice": "1000.25",
            "actualCommission": "10.50",
            "actualOtherCost": "1.25",
            "taxWithheld": "0",
        }
        trade = client.post("/api/v1/executions/manual", json=body, headers=INTENT)
        if trade.status_code != 201:
            raise RuntimeError(f"Synthetic manual fill failed: {trade.status_code}")
        paths = ("/api/v1/home/ledger", "/api/v1/executions", "/api/v1/execution-entry-context")
        after = {path: response(client, path) for path in paths}
        after["/api/v1/home/ledger"]["initialLedger"] = None
        value.update(trade_body=body, expected_trade=trade.json(), expected_after=after)
        return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paths = [args.output / "record-reader-fixture.json", args.output / "manual-trade-fixture.json"]
    if any(path.exists() for path in paths):
        raise FileExistsError("Refusing to overwrite an existing fixture")
    with tempfile.TemporaryDirectory(prefix="stockai-synthetic-records-") as temp:
        root = Path(temp)
        data = (create_linked(root / "linked"), create_manual(root / "manual"))
        for path, value in zip(paths, data, strict=True):
            with path.open("x", encoding="utf-8") as output:
                json.dump(value, output, ensure_ascii=False)
    print("Created two synthetic Android record fixtures")


if __name__ == "__main__":
    main()
