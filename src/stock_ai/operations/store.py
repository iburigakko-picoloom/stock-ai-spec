"""SQLite WAL ledger for proposals, decisions, executions, and Paper outcomes."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from stock_ai.decision import apply_executions
from stock_ai.domain import (
    CashState,
    ExecutionRecord,
    ExecutionStatus,
    PortfolioProposal,
    PortfolioState,
    Position,
    TaxState,
    TradeSide,
    UserDecision,
)
from stock_ai.domain.models import PersonalInputReferences, PersonalPublicationGuard
from stock_ai.operations.chatgpt_research import (
    ChatGPTResearchRecord,
    ResearchAttempt,
    ResearchConfiguration,
    ResearchContext,
    ResearchPass,
    ResearchRun,
    accept_response,
    comparison_request,
    create_record,
    independent_request,
    validate_context,
)
from stock_ai.operations.daily import (
    CompanyResearchRecord,
    OwnerAdoptionReview,
    PredictionSnapshot,
    canonical_json,
    content_id,
    validate_research_link,
)
from stock_ai.operations.manual_portfolio import ImportedManualPortfolio
from stock_ai.operations.models import (
    AutomationJobRecord,
    AutomationStage,
    CashDifference,
    DailyOperationStatus,
    DecisionPolicySnapshot,
    DecisionReview,
    ExecutionImportPreview,
    ImportConflict,
    ImportStatus,
    JobStatus,
    ModelDriftStatus,
    NotificationRecord,
    PaperCalendarSnapshot,
    PaperOutcome,
    PaperReadout,
    PaperReadoutPeriod,
    PaperSeriesPoint,
    PaperSummary,
    PipelineState,
    PositionDifference,
    PositionReconciliationBase,
    PositionReconciliationPreview,
    RankingRecord,
)


class OperationalIntegrityError(RuntimeError):
    """Raised when an immutable operational record is inconsistent."""


class OperationalConflictError(RuntimeError):
    """Raised when a caller attempts an unconfirmed state conflict."""


class ReconciliationConflictError(OperationalConflictError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class OperationalStorageBusyError(RuntimeError):
    pass


class OperationalTimelineError(OperationalConflictError):
    """Raised for an impossible immutable event ordering."""


class PortfolioBaseConflictError(OperationalConflictError):
    """A valid ledger history cannot identify an unambiguous current base."""

    def __init__(self, code: Literal["PORTFOLIO_BASE_AMBIGUOUS", "PORTFOLIO_BASE_IN_FUTURE"]):
        self.code = code
        super().__init__(code)


def _canonical_payload(model: BaseModel) -> str:
    parsed = json.loads(model.model_dump_json())
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _checked_payload_values(payload_value: object, hash_value: object, table: str) -> str:
    payload = str(payload_value)
    if _payload_hash(payload) != hash_value:
        raise OperationalIntegrityError(f"content hash mismatch in {table}")
    return payload


def _checked_payload(row: sqlite3.Row, table: str) -> str:
    return _checked_payload_values(row["payload"], row["content_hash"], table)


def _parse_model[ModelT: BaseModel](model: type[ModelT], payload: str) -> ModelT:
    return model.model_validate_json(payload)


def _now_utc() -> datetime:
    return datetime.now(UTC)


_HASHED_TABLES = (
    "portfolio_states",
    "proposals",
    "proposal_archives",
    "decision_policy_snapshots",
    "user_decisions",
    "executions",
    "daily_status",
    "automation_jobs",
    "notifications",
    "rankings",
    "paper_calendars",
    "paper_outcomes",
    "import_previews",
    "position_reconciliations",
    "prediction_snapshots",
    "company_research",
    "adoption_reviews",
    "manual_portfolio_imports",
    "chatgpt_research_passes",
    "chatgpt_research_records",
    "chatgpt_research_runs",
    "chatgpt_research_attempts",
)
JST = ZoneInfo("Asia/Tokyo")


def _require_catalog_value(table: str, field: str, actual: object, expected: object) -> None:
    if str(actual) != str(expected):
        raise OperationalIntegrityError(f"catalog identity mismatch in {table}.{field}")


def _verify_hashed_row(table: str, row: sqlite3.Row) -> BaseModel | None:
    payload = _checked_payload(row, table)
    item: Any = None
    try:
        if table == "chatgpt_research_runs":
            item = _parse_model(ResearchRun, payload)
            expected = {"run_id": item.run_id, "snapshot_id": item.context.prediction_snapshot_id,
                        "symbol": item.context.symbol}
        elif table == "chatgpt_research_attempts":
            item = _parse_model(ResearchAttempt, payload)
            expected = {"attempt_id": item.attempt_id, "run_id": item.run_id,
                        "phase": item.phase, "status": item.status}
        elif table in {"chatgpt_research_passes", "chatgpt_research_records"}:
            item = (
                _parse_model(ResearchPass, payload)
                if table == "chatgpt_research_passes"
                else _parse_model(ChatGPTResearchRecord, payload)
            )
            expected = {
                "snapshot_id": item.context.prediction_snapshot_id,
                "symbol": item.context.symbol,
            }
            if isinstance(item, ResearchPass):
                expected["pass_id"] = item.pass_id
            else:
                expected["research_id"] = item.research_id
        elif table == "manual_portfolio_imports":
            item = _parse_model(ImportedManualPortfolio, payload)
            expected = {
                "export_sha256": item.export_sha256,
                "revision_id": item.export.revision_id,
                "revision_sequence": item.export.revision_sequence,
                "owner_scope_hash": item.owner_scope_hash,
            }
        elif table == "adoption_reviews":
            item = _parse_model(OwnerAdoptionReview, payload)
            expected = {"review_id": item.review_id, "selection_id": item.selection_id}
        elif table == "prediction_snapshots":
            item = _parse_model(PredictionSnapshot, payload)
            expected = {"snapshot_id": item.snapshot_id, "as_of": item.as_of.isoformat()}
        elif table == "company_research":
            item = _parse_model(CompanyResearchRecord, payload)
            expected = {
                "research_id": item.research_id,
                "prediction_snapshot_id": item.prediction_snapshot_id,
                "symbol": item.symbol,
                "reviewed_at": item.reviewed_at.isoformat(),
            }
        elif table == "portfolio_states":
            item = _parse_model(PortfolioState, payload)
            expected = {
                "portfolio_id": item.portfolio_id,
                "as_of": item.as_of.isoformat(),
            }
        elif table == "proposals":
            item = _parse_model(PortfolioProposal, payload)
            expected = {
                "proposal_id": item.proposal_id,
                "business_date": item.as_of.astimezone(JST).date().isoformat(),
                "as_of": item.as_of.isoformat(),
                "generated_at": item.generated_at.isoformat(),
                "current_portfolio_id": item.current_portfolio_id,
            }
        elif table == "proposal_archives":
            parsed = json.loads(payload)
            expected = {
                "proposal_id": parsed["proposal_id"],
                "archived_at": parsed["archived_at"],
            }
        elif table == "user_decisions":
            item = _parse_model(UserDecision, payload)
            expected = {
                "decision_id": item.decision_id,
                "proposal_id": item.proposal_id,
                "version": item.version,
                "saved_at": item.saved_at.isoformat(),
            }
        elif table == "decision_policy_snapshots":
            item = _parse_model(DecisionPolicySnapshot, payload)
            expected = {
                "proposal_id": item.proposal_id,
                "captured_at": item.captured_at.isoformat(),
                "engine_version": item.config.version,
            }
        elif table == "executions":
            item = _parse_model(ExecutionRecord, payload)
            expected = {
                "execution_id": item.execution_id,
                "decision_id": item.decision_id,
                "executed_at": item.executed_at.isoformat(),
            }
        elif table == "daily_status":
            item = _parse_model(DailyOperationStatus, payload)
            expected = {
                "business_date": item.business_date.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
        elif table == "automation_jobs":
            item = _parse_model(AutomationJobRecord, payload)
            expected = {
                "run_id": item.run_id,
                "idempotency_key": item.idempotency_key,
                "business_date": item.business_date.isoformat(),
                "stage": item.stage.value,
                "status": item.status.value,
            }
        elif table == "notifications":
            item = _parse_model(NotificationRecord, payload)
            expected = {
                "notification_id": item.notification_id,
                "proposal_id": item.proposal_id,
                "status": item.status.value,
                "created_at": item.created_at.isoformat(),
            }
        elif table == "rankings":
            item = _parse_model(RankingRecord, payload)
            expected = {
                "ranking_id": item.ranking_id,
                "as_of": item.as_of.isoformat(),
                "rank_type": item.rank_type,
                "rank": item.rank,
            }
        elif table == "paper_outcomes":
            item = _parse_model(PaperOutcome, payload)
            expected = {
                "outcome_id": item.outcome_id,
                "proposal_id": item.proposal_id,
                "observed_at": item.observed_at.isoformat(),
            }
        elif table == "paper_calendars":
            item = _parse_model(PaperCalendarSnapshot, payload)
            expected = {
                "calendar_snapshot_id": item.calendar_snapshot_id,
                "source_snapshot_id": item.source_snapshot_id,
                "created_at": item.created_at.isoformat(),
            }
        elif table == "import_previews":
            item = _parse_model(ExecutionImportPreview, payload)
            expected = {
                "preview_id": item.preview_id,
                "source_hash": item.source_hash,
                "status": item.status.value,
                "created_at": item.created_at.isoformat(),
            }
        elif table == "position_reconciliations":
            item = _parse_model(PositionReconciliationPreview, payload)
            expected = {
                "preview_id": item.preview_id,
                "source_hash": item.source_hash,
                "status": item.status.value,
                "created_at": item.created_at.isoformat(),
            }
        else:  # pragma: no cover - guarded by the fixed table list
            raise OperationalIntegrityError(f"unknown hashed table {table}")
        for field, expected_value in expected.items():
            _require_catalog_value(table, field, row[field], expected_value)
        return item if isinstance(item, BaseModel) else None
    except OperationalIntegrityError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise OperationalIntegrityError(f"invalid authenticated record in {table}") from exc


def _reconciliation_base(
    connection: sqlite3.Connection,
    portfolio: PortfolioState,
    cutoff: datetime,
) -> tuple[PositionReconciliationBase, set[str]]:
    row = connection.execute(
        "SELECT * FROM portfolio_states WHERE portfolio_id = ?",
        (portfolio.portfolio_id,),
    ).fetchone()
    _verify_hashed_row("portfolio_states", row)
    records = []
    ids = set()
    for record in connection.execute("SELECT * FROM executions ORDER BY execution_id"):
        _verify_hashed_row("executions", record)
        execution = _parse_model(ExecutionRecord, _checked_payload(record, "executions"))
        if execution.filled_shares > 0 and execution.executed_at <= cutoff:
            ids.add(execution.execution_id)
            records.append([execution.execution_id, record["content_hash"]])
    fingerprint = json.dumps(
        {
            "schema_version": "position-reconciliation-executions-v1",
            "imported_as_of": cutoff.astimezone(UTC).isoformat(),
            "executions": records,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return PositionReconciliationBase(
        portfolio_id=portfolio.portfolio_id,
        portfolio_sha256=row["content_hash"],
        relevant_executions_sha256=_payload_hash(fingerprint),
    ), ids


def _confirmed_reconciliation_result(
    connection: sqlite3.Connection,
    preview: PositionReconciliationPreview,
) -> PortfolioState:
    row = connection.execute(
        "SELECT * FROM portfolio_states WHERE portfolio_id = ?",
        (preview.confirmed_portfolio_id,),
    ).fetchone()
    if row is None:
        raise OperationalIntegrityError("reconciliation result missing")
    _verify_hashed_row("portfolio_states", row)
    result = _parse_model(PortfolioState, _checked_payload(row, "portfolio_states"))
    expected = _parse_model(PortfolioState, preview.portfolio_payload).model_copy(
        update={"portfolio_id": preview.confirmed_portfolio_id},
    )
    if result != expected:
        raise OperationalIntegrityError("reconciliation result differs from confirmed preview")
    return result


def _latest_portfolio_connection(connection: sqlite3.Connection) -> PortfolioState | None:
    """Verify originals before choosing by exact UTC instant on this connection.

    Ties are history, not an ID-based ordering rule. Current operations stop;
    explicit history-ID reads remain available. No source bytes are rewritten.
    """
    latest: PortfolioState | None = None
    ambiguous = False
    for row in connection.execute("SELECT * FROM portfolio_states"):
        verified = _verify_hashed_row("portfolio_states", row)
        if not isinstance(verified, PortfolioState):
            raise OperationalIntegrityError("invalid verified portfolio type")
        item = verified
        instant = item.as_of.astimezone(UTC)
        if latest is None or instant > latest.as_of.astimezone(UTC):
            latest, ambiguous = item, False
        elif instant == latest.as_of.astimezone(UTC):
            ambiguous = True
    if latest is not None and latest.as_of.astimezone(UTC) > _now_utc():
        raise PortfolioBaseConflictError("PORTFOLIO_BASE_IN_FUTURE")
    if ambiguous:
        raise PortfolioBaseConflictError("PORTFOLIO_BASE_AMBIGUOUS")
    return latest


def _verify_database_connection(connection: sqlite3.Connection) -> dict[str, int]:
    connection.row_factory = sqlite3.Row
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise OperationalIntegrityError("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise OperationalIntegrityError("SQLite foreign-key integrity check failed")
    counts: dict[str, int] = {}
    metadata_rows = connection.execute("SELECT key FROM operational_metadata").fetchall()
    counts["operational_metadata"] = len(metadata_rows)
    schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in _HASHED_TABLES:
        if (
            table in {"chatgpt_research_runs", "chatgpt_research_attempts"}
            and schema_version < 5
            and table not in tables
        ):
            counts[table] = 0
            continue
        if (
            table in {"chatgpt_research_passes", "chatgpt_research_records"}
            and schema_version < 4
            and table not in tables
        ):
            counts[table] = 0
            continue
        if table == "manual_portfolio_imports" and schema_version < 3 and table not in tables:
            counts[table] = 0
            continue
        if (
            schema_version < 2
            and table not in tables
            and table in {"prediction_snapshots", "company_research", "adoption_reviews"}
        ):
            counts[table] = 0
            continue  # Previous-version backups remain verifiable before migration.
        rows = connection.execute(f"SELECT * FROM {table}").fetchall()
        for row in rows:
            _verify_hashed_row(table, row)
        counts[table] = len(rows)
    for row in connection.execute("SELECT * FROM position_reconciliations"):
        preview = _parse_model(
            PositionReconciliationPreview, _checked_payload(row, "position_reconciliations")
        )
        if preview.base_reference is not None:
            base = connection.execute(
                "SELECT * FROM portfolio_states WHERE portfolio_id = ?",
                (preview.base_reference.portfolio_id,),
            ).fetchone()
            if base is None or base["content_hash"] != preview.base_reference.portfolio_sha256:
                raise OperationalIntegrityError("reconciliation historical base missing or changed")
        if preview.confirmed_portfolio_id is not None:
            _confirmed_reconciliation_result(connection, preview)
    archive_links = connection.execute(
        """
        SELECT proposal.proposal_id, proposal.archived_at,
               archive.payload, archive.content_hash
        FROM proposals AS proposal
        LEFT JOIN proposal_archives AS archive
          ON archive.proposal_id = proposal.proposal_id
        """
    ).fetchall()
    for row in archive_links:
        if row["payload"] is None:
            raise OperationalIntegrityError("proposal is missing archive evidence")
        payload = _checked_payload(row, "proposal_archives")
        parsed = json.loads(payload)
        _require_catalog_value(
            "proposal_archives", "proposal_id", parsed.get("proposal_id"), row["proposal_id"]
        )
        _require_catalog_value(
            "proposal_archives", "archived_at", parsed.get("archived_at"), row["archived_at"]
        )
    policy_links = connection.execute(
        """
        SELECT proposal.proposal_id,
               policy.payload AS policy_payload,
               policy.content_hash AS policy_hash,
               proposal.payload AS proposal_payload,
               proposal.content_hash AS proposal_hash
        FROM proposals AS proposal
        LEFT JOIN decision_policy_snapshots AS policy
          ON policy.proposal_id = proposal.proposal_id
        """
    ).fetchall()
    for row in policy_links:
        if row["policy_payload"] is None:
            raise OperationalIntegrityError("proposal is missing its decision policy snapshot")
        snapshot = _parse_model(
            DecisionPolicySnapshot,
            _checked_payload_values(
                row["policy_payload"],
                row["policy_hash"],
                "decision_policy_snapshots",
            ),
        )
        proposal = _parse_model(
            PortfolioProposal,
            _checked_payload_values(
                row["proposal_payload"],
                row["proposal_hash"],
                "proposals",
            ),
        )
        _validate_decision_policy_snapshot(snapshot, proposal)
    status_rows = connection.execute("SELECT payload, content_hash FROM daily_status").fetchall()
    for row in status_rows:
        status = _parse_model(DailyOperationStatus, _checked_payload(row, "daily_status"))
        _validate_status_proposal(connection, status)
    if "company_research" in tables:
        for row in connection.execute("SELECT payload, content_hash FROM company_research"):
            research = _parse_model(
                CompanyResearchRecord, _checked_payload(row, "company_research")
            )
            linked = connection.execute(
                "SELECT payload, content_hash FROM prediction_snapshots WHERE snapshot_id = ?",
                (research.prediction_snapshot_id,),
            ).fetchone()
            if linked is None:
                raise OperationalIntegrityError("research is missing its original prediction")
            original_prediction = _parse_model(
                PredictionSnapshot, _checked_payload(linked, "prediction_snapshots")
            )
            try:
                validate_research_link(research, original_prediction)
            except ValueError as exc:
                raise OperationalIntegrityError("invalid research-to-prediction link") from exc
    if "prediction_snapshots" in tables:
        for row in connection.execute("SELECT payload, content_hash FROM prediction_snapshots"):
            original = _parse_model(
                PredictionSnapshot, _checked_payload(row, "prediction_snapshots")
            )
            _validate_snapshot_approval(connection, original)
    if "chatgpt_research_passes" in tables:
        for row in connection.execute("SELECT * FROM chatgpt_research_passes"):
            item = _parse_model(ResearchPass, _checked_payload(row, "chatgpt_research_passes"))
            _validate_chatgpt_pass(connection, item)
    if "chatgpt_research_records" in tables:
        for row in connection.execute("SELECT * FROM chatgpt_research_records"):
            record = _parse_model(
                ChatGPTResearchRecord, _checked_payload(row, "chatgpt_research_records")
            )
            _validate_chatgpt_record(connection, record)
    if "chatgpt_research_runs" in tables:
        for row in connection.execute("SELECT * FROM chatgpt_research_runs"):
            run = _parse_model(ResearchRun, _checked_payload(row, "chatgpt_research_runs"))
            validate_context(
                run.context,
                _chatgpt_snapshot(
                    connection,
                    run.context.prediction_snapshot_id,
                ),
            )
    if "chatgpt_research_attempts" in tables:
        for row in connection.execute("SELECT * FROM chatgpt_research_attempts"):
            attempt = _parse_model(
                ResearchAttempt, _checked_payload(row, "chatgpt_research_attempts")
            )
            _validate_chatgpt_attempt(connection, attempt)
    _mobile_numerical_selection(connection)
    for row in connection.execute(
        "SELECT key,value FROM operational_metadata WHERE key LIKE 'mobile-cash-receipt:%'"
    ):
        _cash_receipt(row[1], row[0].removeprefix("mobile-cash-receipt:"))
    for row in connection.execute(
        "SELECT key,value FROM operational_metadata WHERE key LIKE 'mobile-cash-active:%'"
    ):
        linked = connection.execute(
            "SELECT value FROM operational_metadata WHERE key=?", ("mobile-cash-receipt:" + row[1],)
        ).fetchone()
        if linked is None:
            raise OperationalIntegrityError("cash-only publication receipt missing")
        value = _cash_receipt(linked[0], row[1])
        if value["status"]["business_date"] != row[0].removeprefix("mobile-cash-active:"):
            raise OperationalIntegrityError("cash-only publication date changed")
    from stock_ai.operations.chatgpt_manual import verify_exchange_records

    try:
        verify_exchange_records(connection)
    except (ValueError, KeyError, TypeError) as exc:
        raise OperationalIntegrityError("manual ChatGPT exchange integrity check failed") from exc
    return counts


def _chatgpt_snapshot(connection: sqlite3.Connection, snapshot_id: str) -> PredictionSnapshot:
    row = connection.execute(
        "SELECT * FROM prediction_snapshots WHERE snapshot_id = ?", (snapshot_id,)
    ).fetchone()
    if row is None:
        raise OperationalIntegrityError("ChatGPT research is missing its original prediction")
    _verify_hashed_row("prediction_snapshots", row)
    return _parse_model(PredictionSnapshot, row["payload"])


def _chatgpt_pass(connection: sqlite3.Connection, pass_id: str) -> ResearchPass:
    row = connection.execute(
        "SELECT * FROM chatgpt_research_passes WHERE pass_id = ?", (pass_id,)
    ).fetchone()
    if row is None:
        raise OperationalIntegrityError("ChatGPT research is missing a saved research pass")
    _verify_hashed_row("chatgpt_research_passes", row)
    return _parse_model(ResearchPass, row["payload"])


def _chatgpt_run(connection: sqlite3.Connection, run_id: str) -> ResearchRun:
    row = connection.execute(
        "SELECT * FROM chatgpt_research_runs WHERE run_id = ?", (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(run_id)
    _verify_hashed_row("chatgpt_research_runs", row)
    return _parse_model(ResearchRun, row["payload"])


def _require_research_receipt_times(
    attempt: ResearchAttempt, started_at: datetime, completed_at: datetime, now: datetime,
) -> None:
    if any(item.tzinfo is None or item.utcoffset() is None for item in (
        started_at, completed_at, now,
    )) or not attempt.started_at <= started_at <= completed_at <= now + timedelta(seconds=60):
        raise ValueError("research receipt times do not match the durable attempt")


def _validate_chatgpt_attempt(connection: sqlite3.Connection, attempt: ResearchAttempt) -> None:
    run = _chatgpt_run(connection, attempt.run_id)
    if attempt.started_at < run.context.research_as_of:
        raise OperationalIntegrityError("research attempt predates its context")
    if attempt.phase == "comparison":
        rows = connection.execute(
            "SELECT * FROM chatgpt_research_passes WHERE snapshot_id = ? AND symbol = ?",
            (run.context.prediction_snapshot_id, run.context.symbol),
        ).fetchall()
        previous = [
            _parse_model(ResearchPass, _checked_payload(row, "chatgpt_research_passes"))
            for row in rows
        ]
        if not any(
            item.context == run.context and item.phase == "independent"
            and item.completed_at <= attempt.started_at for item in previous
        ):
            raise OperationalIntegrityError("comparison attempt lacks prior independent research")
    if attempt.pass_id is not None:
        item = _chatgpt_pass(connection, attempt.pass_id)
        if (
            item.context != run.context or item.phase != attempt.phase
            or item.started_at < attempt.started_at or item.completed_at != attempt.finished_at
        ):
            raise OperationalIntegrityError("research attempt differs from saved pass")


def _validate_chatgpt_pass(connection: sqlite3.Connection, item: ResearchPass) -> None:
    snapshot = _chatgpt_snapshot(connection, item.context.prediction_snapshot_id)
    try:
        validate_context(item.context, snapshot)
        if item.phase == "independent":
            request = independent_request(item.context)
        else:
            assert item.independent_pass_id is not None
            independent = _chatgpt_pass(connection, item.independent_pass_id)
            request = comparison_request(item.context, independent, snapshot)
            if independent.completed_at > item.started_at:
                raise ValueError("comparison began before independent research completed")
        if content_id(request) != item.request_sha256:
            raise ValueError("research request differs from fixed prompt and numerical snapshot")
    except ValueError as exc:
        raise OperationalIntegrityError("invalid ChatGPT research pass lineage") from exc


def _validate_chatgpt_record(
    connection: sqlite3.Connection, record: ChatGPTResearchRecord
) -> None:
    snapshot = _chatgpt_snapshot(connection, record.context.prediction_snapshot_id)
    for item in (record.independent, record.comparison):
        saved = _chatgpt_pass(connection, item.pass_id)
        if saved != item:
            raise OperationalIntegrityError("ChatGPT record differs from saved research pass")
        _validate_chatgpt_pass(connection, saved)
    try:
        verified = create_record(record.context, record.independent, record.comparison, snapshot)
        if verified != record:
            raise ValueError("record does not match original numerical prediction")
    except ValueError as exc:
        raise OperationalIntegrityError("invalid ChatGPT research record lineage") from exc


def _validate_snapshot_approval(
    connection: sqlite3.Connection, snapshot: PredictionSnapshot
) -> None:
    if snapshot.adoption_review_id is None:
        return
    row = connection.execute(
        "SELECT payload, content_hash FROM adoption_reviews WHERE review_id = ?",
        (snapshot.adoption_review_id,),
    ).fetchone()
    if row is None:
        raise OperationalIntegrityError("snapshot requires a saved owner adoption review")
    review = _parse_model(OwnerAdoptionReview, _checked_payload(row, "adoption_reviews"))
    if (
        review.decision != "adopt"
        or review.selection_id != snapshot.selection_id
        or review.reviewed_at > snapshot.generated_at
    ):
        raise OperationalIntegrityError("snapshot does not match owner adoption review")


def _validate_status_proposal(connection: sqlite3.Connection, status: DailyOperationStatus) -> None:
    if status.proposal_id is None:
        return
    row = connection.execute(
        "SELECT payload, content_hash FROM proposals WHERE proposal_id = ?",
        (status.proposal_id,),
    ).fetchone()
    if row is None:
        raise OperationalIntegrityError("daily status references a missing proposal")
    proposal = _parse_model(PortfolioProposal, _checked_payload(row, "proposals"))
    if proposal.as_of.astimezone(JST).date() != status.business_date:
        raise OperationalIntegrityError("daily status proposal does not match its business date")
    archive = connection.execute(
        "SELECT payload, content_hash FROM proposal_archives WHERE proposal_id = ?",
        (status.proposal_id,),
    ).fetchone()
    if archive is None:
        raise OperationalIntegrityError("daily status proposal is not archived")
    _checked_payload(archive, "proposal_archives")


def _validate_decision_policy_snapshot(
    snapshot: DecisionPolicySnapshot, proposal: PortfolioProposal
) -> None:
    if snapshot.proposal_id != proposal.proposal_id:
        raise OperationalIntegrityError("decision policy references a different proposal")
    if snapshot.captured_at != proposal.generated_at:
        raise OperationalIntegrityError(
            "decision policy capture time must match proposal generation"
        )
    if snapshot.config.version != proposal.decision_engine_version:
        raise OperationalIntegrityError("decision policy engine version does not match proposal")


def _write_daily_status(connection: sqlite3.Connection, status: DailyOperationStatus) -> None:
    _validate_status_proposal(connection, status)
    payload = _canonical_payload(status)
    connection.execute(
        "INSERT INTO daily_status(business_date,payload,content_hash,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(business_date) DO UPDATE SET payload=excluded.payload,"
        "content_hash=excluded.content_hash,updated_at=excluded.updated_at",
        (status.business_date.isoformat(), payload, _payload_hash(payload),
         status.updated_at.isoformat()),
    )


def _hash_reference(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        x in "0123456789abcdef" for x in value
    )


def _mobile_numerical_selection(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute("SELECT value FROM operational_metadata "
                             "WHERE key='mobile-numerical-active'").fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
        if set(value) != {"run_id", "as_of", "snapshot_id"} or not _hash_reference(value["run_id"]):
            raise ValueError("invalid numerical reference")
        cutoff = datetime.fromisoformat(value["as_of"])
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("naive numerical reference")
        if value["snapshot_id"] is not None:
            if not _hash_reference(value["snapshot_id"]):
                raise ValueError("invalid snapshot reference")
            snapshot_row = connection.execute(
                "SELECT payload,content_hash FROM prediction_snapshots WHERE snapshot_id=?",
                (value["snapshot_id"],),
            ).fetchone()
            if snapshot_row is None:
                raise ValueError("missing selected snapshot")
            snapshot = _parse_model(PredictionSnapshot,
                                    _checked_payload(snapshot_row, "prediction_snapshots"))
            if snapshot.as_of != cutoff:
                raise ValueError("selected cutoff changed")
        return dict(value)
    except (ValueError, TypeError, KeyError) as exc:
        raise OperationalIntegrityError("invalid active numerical reference") from exc


def _cash_receipt(payload: str, identity: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
        if (set(value) != {"receipt_id", "guard", "status", "numerical_run_id"}
                or value["receipt_id"] != identity or not _hash_reference(identity)
                or not _hash_reference(value["numerical_run_id"])):
            raise ValueError("invalid cash reference")
        PersonalInputReferences.model_validate(value["guard"])
        status = DailyOperationStatus.model_validate(value["status"])
        if (status.pipeline_state is not PipelineState.CASH_ONLY or status.is_stale
                or status.proposal_id is not None or status.blocking_reason is not None):
            raise ValueError("invalid cash status")
        return dict(value)
    except (ValueError, TypeError, KeyError) as exc:
        raise OperationalIntegrityError("invalid cash-only publication receipt") from exc


def _guard_personal_references(
    connection: sqlite3.Connection,
    guard: PersonalInputReferences,
) -> PortfolioState:
    manual = connection.execute(
        "SELECT revision_id FROM manual_portfolio_imports ORDER BY revision_sequence DESC LIMIT 1"
    ).fetchone()
    ledger = _latest_portfolio_connection(connection)
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='mobile_personal_settings' AND type='table'"
        ).fetchone()
        is None
    ):
        raise OperationalConflictError("frozen personal settings missing")
    settings = connection.execute(
        "SELECT revision_id,payload,content_hash "
        "FROM mobile_personal_settings ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    executions = tuple(
        _parse_model(ExecutionRecord, _checked_payload(row, "executions"))
        for row in connection.execute(
            "SELECT payload,content_hash FROM executions ORDER BY execution_id"
        )
    )
    if (
        manual is None
        or ledger is None
        or settings is None
        or manual[0] != guard.manual_revision_id
        or ledger.portfolio_id != guard.ledger_portfolio_id
        or settings[0] != guard.settings_revision_id
        or _payload_hash(settings[1]) != settings[2]
        or settings[0] != settings[2]
        or content_id([x.model_dump(mode="json") for x in executions]) != guard.executions_sha256
    ):
        raise OperationalConflictError("frozen proposal personal inputs changed")
    return ledger


def _guard_personal_publication(
    connection: sqlite3.Connection, guard: PersonalPublicationGuard, proposal: PortfolioProposal,
) -> None:
    _guard_personal_references(connection, guard)
    selected = _mobile_numerical_selection(connection)
    if selected is None or selected["snapshot_id"] != guard.forecast_snapshot_id:
        raise OperationalConflictError("active numerical forecast changed")
    row = connection.execute("SELECT payload,content_hash FROM prediction_snapshots "
                             "WHERE snapshot_id=?", (guard.forecast_snapshot_id,)).fetchone()
    if row is None:
        raise OperationalIntegrityError("frozen proposal forecast missing")
    snapshot = _parse_model(PredictionSnapshot, _checked_payload(row, "prediction_snapshots"))
    if (proposal.daily_audit is None or not proposal.is_research_only
            or snapshot.as_of != proposal.as_of
            or snapshot.model_version != proposal.model_bundle_version
            or proposal.current_portfolio_id != guard.ledger_portfolio_id
            or proposal.daily_audit.forecast_content_sha256
            != content_id(snapshot.model_dump(mode="json"))):
        raise OperationalIntegrityError("frozen proposal forecast differs")


def _verify_database_path(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise OperationalIntegrityError("SQLite backup does not exist")
    uri = f"file:{path.as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.execute("PRAGMA query_only=ON")
        return _verify_database_connection(connection)
    except sqlite3.DatabaseError as exc:
        raise OperationalIntegrityError("SQLite backup verification failed") from exc
    finally:
        if connection is not None:
            connection.close()


class OperationalStore:
    """Durable, local-only operational source of truth.

    The ledger is append-only for proposals, decisions, executions, rankings,
    notifications, and Paper observations.  A mutable pointer is never used in
    place of immutable content; "latest" is derived from timestamps.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", 0) & 0xFF in (
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            ):
                raise OperationalStorageBusyError("STORAGE_BUSY") from exc
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolio_states (
                    portfolio_id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_portfolio_as_of ON portfolio_states(as_of);

                CREATE TABLE IF NOT EXISTS operational_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS prediction_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS adoption_reviews (
                    review_id TEXT PRIMARY KEY,
                    selection_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prediction_as_of ON prediction_snapshots(as_of);
                CREATE TABLE IF NOT EXISTS company_research (
                    research_id TEXT PRIMARY KEY,
                    prediction_snapshot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(prediction_snapshot_id) REFERENCES prediction_snapshots(snapshot_id)
                );
                CREATE TABLE IF NOT EXISTS manual_portfolio_imports (
                    export_sha256 TEXT PRIMARY KEY,
                    revision_id TEXT NOT NULL UNIQUE,
                    revision_sequence INTEGER NOT NULL UNIQUE,
                    owner_scope_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chatgpt_research_passes (
                    pass_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES prediction_snapshots(snapshot_id)
                );
                CREATE TABLE IF NOT EXISTS chatgpt_research_records (
                    research_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES prediction_snapshots(snapshot_id)
                );
                CREATE TABLE IF NOT EXISTS chatgpt_research_runs (
                    run_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    payload TEXT NOT NULL, content_hash TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES prediction_snapshots(snapshot_id)
                );
                CREATE TABLE IF NOT EXISTS chatgpt_research_attempts (
                    attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, phase TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, content_hash TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES chatgpt_research_runs(run_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chatgpt_active_attempt
                    ON chatgpt_research_attempts(run_id) WHERE status = 'running';
                PRAGMA user_version=5;

                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    business_date TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    current_portfolio_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    FOREIGN KEY(current_portfolio_id) REFERENCES portfolio_states(portfolio_id)
                );
                CREATE INDEX IF NOT EXISTS idx_proposal_date
                ON proposals(business_date, generated_at);
                CREATE TABLE IF NOT EXISTS proposal_archives (
                    proposal_id TEXT PRIMARY KEY,
                    archived_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
                );
                CREATE TABLE IF NOT EXISTS decision_policy_snapshots (
                    proposal_id TEXT PRIMARY KEY,
                    captured_at TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
                );

                CREATE TABLE IF NOT EXISTS user_decisions (
                    decision_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    saved_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(proposal_id, version),
                    FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
                );

                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES user_decisions(decision_id)
                );

                CREATE TABLE IF NOT EXISTS daily_status (
                    business_date TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS automation_jobs (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    business_date TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS process_locks (
                    lock_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
                );

                CREATE TABLE IF NOT EXISTS rankings (
                    ranking_id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    rank_type TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_outcomes (
                    outcome_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
                );

                CREATE TABLE IF NOT EXISTS paper_calendars (
                    calendar_snapshot_id TEXT PRIMARY KEY,
                    source_snapshot_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS import_previews (
                    preview_id TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS position_reconciliations (
                    preview_id TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                """
            )
            connection.commit()

    @staticmethod
    def _insert_immutable(
        connection: sqlite3.Connection,
        *,
        table: str,
        identity_column: str,
        identity: str,
        columns: Mapping[str, object],
        payload: str,
    ) -> bool:
        existing = connection.execute(
            f"SELECT payload, content_hash FROM {table} WHERE {identity_column} = ?",
            (identity,),
        ).fetchone()
        digest = _payload_hash(payload)
        if existing is not None:
            if existing["payload"] != payload or existing["content_hash"] != digest:
                raise OperationalConflictError(
                    f"immutable {table} identity already exists with different content"
                )
            return False
        names = [identity_column, *columns, "payload", "content_hash"]
        values = [identity, *columns.values(), payload, digest]
        placeholders = ",".join("?" for _ in names)
        connection.execute(
            f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})",
            values,
        )
        return True

    def import_manual_portfolio(self, item: ImportedManualPortfolio) -> ImportedManualPortfolio:
        """Append a verified input without modifying balances or recorded executions."""
        item = ImportedManualPortfolio.model_validate_json(item.model_dump_json())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM manual_portfolio_imports ORDER BY revision_sequence DESC"
            ).fetchall()
            for row in rows:
                _verify_hashed_row("manual_portfolio_imports", row)
                previous = _parse_model(ImportedManualPortfolio, row["payload"])
                if previous.owner_scope_hash != item.owner_scope_hash:
                    raise OperationalConflictError(
                        "manual portfolio owner differs from pinned owner"
                    )
            if rows:
                latest = _parse_model(ImportedManualPortfolio, rows[0]["payload"])
                if item.export.revision_sequence < latest.export.revision_sequence:
                    raise OperationalConflictError("manual portfolio revision rollback refused")
                if item.export_sha256 == latest.export_sha256:
                    return latest  # Preserve the first receipt time, including ACK retries.
                if item.export.revision_sequence == latest.export.revision_sequence:
                    raise OperationalConflictError("manual portfolio revision identity conflict")
                if item.export.saved_at < latest.export.saved_at:
                    raise OperationalConflictError("manual portfolio saved time rollback refused")
                if item.export.revision_id in {row["revision_id"] for row in rows}:
                    raise OperationalConflictError("manual portfolio revision replay conflict")
            self._insert_immutable(
                connection,
                table="manual_portfolio_imports",
                identity_column="export_sha256",
                identity=item.export_sha256,
                columns={
                    "revision_id": item.export.revision_id,
                    "revision_sequence": item.export.revision_sequence,
                    "owner_scope_hash": item.owner_scope_hash,
                },
                payload=_canonical_payload(item),
            )
            connection.commit()
            return item

    def latest_manual_portfolio(self) -> ImportedManualPortfolio | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM manual_portfolio_imports ORDER BY revision_sequence DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            item = _verify_hashed_row("manual_portfolio_imports", row)
            if not isinstance(item, ImportedManualPortfolio):
                raise OperationalIntegrityError("invalid verified manual portfolio type")
            return item

    def append_prediction_snapshot(
        self,
        snapshot: PredictionSnapshot,
        *,
        expected_manual_revision_id: str | None = None,
        expected_portfolio_id: str | None = None,
        mobile_run_id: str | None = None,
    ) -> bool:
        snapshot = PredictionSnapshot.model_validate_json(snapshot.model_dump_json())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if (expected_manual_revision_id is None) != (expected_portfolio_id is None):
                raise ValueError("Both frozen personal references are required")
            existing = connection.execute(
                "SELECT 1 FROM prediction_snapshots WHERE snapshot_id=?", (snapshot.snapshot_id,)
            ).fetchone()
            if expected_manual_revision_id is not None and (existing is None or mobile_run_id):
                manual = connection.execute(
                    "SELECT revision_id FROM manual_portfolio_imports "
                    "ORDER BY revision_sequence DESC LIMIT 1"
                ).fetchone()
                ledger = _latest_portfolio_connection(connection)
                if (
                    manual is None
                    or ledger is None
                    or manual[0] != expected_manual_revision_id
                    or ledger.portfolio_id != expected_portfolio_id
                ):
                    raise OperationalConflictError("frozen forecast personal inputs changed")
            _validate_snapshot_approval(connection, snapshot)
            inserted = self._insert_immutable(
                connection,
                table="prediction_snapshots",
                identity_column="snapshot_id",
                identity=snapshot.snapshot_id,
                columns={"as_of": snapshot.as_of.isoformat()},
                payload=_canonical_payload(snapshot),
            )
            if mobile_run_id is not None:
                connection.execute(
                    "INSERT OR REPLACE INTO operational_metadata VALUES(?,?)",
                    (
                        "mobile-numerical-active",
                        canonical_json(
                            {
                                "run_id": mobile_run_id,
                                "as_of": snapshot.as_of.isoformat(),
                                "snapshot_id": snapshot.snapshot_id,
                            }
                        ),
                    ),
                )
            connection.commit()
            return inserted

    def select_mobile_numerical_without_snapshot(
        self,
        run_id: str,
        as_of: datetime,
        manual_revision_id: str | None,
        ledger_portfolio_id: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            manual = connection.execute(
                "SELECT revision_id FROM manual_portfolio_imports "
                "ORDER BY revision_sequence DESC LIMIT 1"
            ).fetchone()
            ledger = _latest_portfolio_connection(connection)
            if (None if manual is None else manual[0]) != manual_revision_id or (
                None if ledger is None else ledger.portfolio_id
            ) != ledger_portfolio_id:
                raise OperationalConflictError("numerical selection personal inputs changed")
            connection.execute(
                "INSERT OR REPLACE INTO operational_metadata VALUES(?,?)",
                (
                    "mobile-numerical-active",
                    canonical_json(
                        {"run_id": run_id, "as_of": as_of.isoformat(), "snapshot_id": None}
                    ),
                ),
            )
            connection.commit()

    def append_adoption_review(self, review: OwnerAdoptionReview) -> bool:
        review = OwnerAdoptionReview.model_validate_json(review.model_dump_json())
        # A manually supplied report ID is not authenticated evaluation evidence.
        # Until the release gate consumes the actual final selection, holdout and
        # evaluator artifacts, record paper/reject reviews but never promote.
        if review.decision == "adopt":
            raise ValueError(
                "adoption is blocked: authenticated evaluator/holdout evidence "
                "and personal execution settings are not connected"
            )
        with self._connect() as connection:
            inserted = self._insert_immutable(
                connection,
                table="adoption_reviews",
                identity_column="review_id",
                identity=review.review_id,
                columns={"selection_id": review.selection_id},
                payload=_canonical_payload(review),
            )
            connection.commit()
            return inserted

    def adoption_review(self, review_id: str) -> OwnerAdoptionReview:
        return self._load_one("adoption_reviews", "review_id", review_id, OwnerAdoptionReview)

    def prediction_snapshot(self, snapshot_id: str) -> PredictionSnapshot:
        return self._load_one(
            "prediction_snapshots", "snapshot_id", snapshot_id, PredictionSnapshot
        )

    def latest_archived_prediction(self, before: datetime) -> PredictionSnapshot | None:
        """Read-only history, independent of the active proposal/forecast selection."""
        if before.tzinfo is None or before.utcoffset() is None:
            raise ValueError("archive cutoff must be timezone-aware")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload,content_hash FROM prediction_snapshots "
                "WHERE julianday(as_of)<=julianday(?) "
                "ORDER BY julianday(as_of) DESC, "
                "julianday(json_extract(payload,'$.generated_at')) DESC,snapshot_id DESC",
                (before.isoformat(),),
            )
            for row in rows:
                snapshot = _parse_model(
                    PredictionSnapshot, _checked_payload(row, "prediction_snapshots")
                )
                if snapshot.generated_at <= before and not snapshot.blocking_reasons:
                    return snapshot
        return None

    def latest_prediction_snapshot(self) -> PredictionSnapshot | None:
        with self._connect() as connection:
            reference = _mobile_numerical_selection(connection)
            if reference is not None:
                if reference["snapshot_id"] is None:
                    return None
                snapshot = self.prediction_snapshot(reference["snapshot_id"])
                return snapshot
            row = connection.execute(
                "SELECT snapshot_id FROM prediction_snapshots "
                "ORDER BY julianday(as_of) DESC, snapshot_id DESC LIMIT 1"
            ).fetchone()
        return self.prediction_snapshot(row[0]) if row else None

    def append_company_research(self, research: CompanyResearchRecord) -> bool:
        research = CompanyResearchRecord.model_validate_json(research.model_dump_json())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, content_hash FROM prediction_snapshots WHERE snapshot_id = ?",
                (research.prediction_snapshot_id,),
            ).fetchone()
            if row is None:
                raise OperationalConflictError("original prediction snapshot must exist first")
            snapshot = _parse_model(
                PredictionSnapshot, _checked_payload(row, "prediction_snapshots")
            )
            validate_research_link(research, snapshot)
            inserted = self._insert_immutable(
                connection,
                table="company_research",
                identity_column="research_id",
                identity=research.research_id,
                columns={
                    "prediction_snapshot_id": research.prediction_snapshot_id,
                    "symbol": research.symbol,
                    "reviewed_at": research.reviewed_at.isoformat(),
                },
                payload=_canonical_payload(research),
            )
            connection.commit()
            return inserted

    def company_research(self, snapshot_id: str) -> tuple[CompanyResearchRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM company_research WHERE prediction_snapshot_id = ? "
                "ORDER BY julianday(reviewed_at), research_id",
                (snapshot_id,),
            ).fetchall()
        return tuple(
            _parse_model(CompanyResearchRecord, _checked_payload(row, "company_research"))
            for row in rows
        )

    def append_chatgpt_pass(self, item: ResearchPass) -> bool:
        """Persist each phase so an interrupted comparison can resume its first phase."""
        item = ResearchPass.model_validate_json(item.model_dump_json())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _validate_chatgpt_pass(connection, item)
            inserted = self._insert_immutable(
                connection,
                table="chatgpt_research_passes",
                identity_column="pass_id",
                identity=item.pass_id,
                columns={
                    "snapshot_id": item.context.prediction_snapshot_id,
                    "symbol": item.context.symbol,
                },
                payload=_canonical_payload(item),
            )
            connection.commit()
            return inserted

    def chatgpt_passes(self, snapshot_id: str) -> tuple[ResearchPass, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chatgpt_research_passes WHERE snapshot_id = ? ORDER BY pass_id",
                (snapshot_id,),
            ).fetchall()
            result = []
            for row in rows:
                _verify_hashed_row("chatgpt_research_passes", row)
                item = _parse_model(ResearchPass, row["payload"])
                _validate_chatgpt_pass(connection, item)
                result.append(item)
        return tuple(sorted(result, key=lambda item: (item.started_at, item.pass_id)))

    def append_chatgpt_research(self, record: ChatGPTResearchRecord) -> bool:
        record = ChatGPTResearchRecord.model_validate_json(record.model_dump_json())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _validate_chatgpt_record(connection, record)
            inserted = self._insert_immutable(
                connection,
                table="chatgpt_research_records",
                identity_column="research_id",
                identity=record.research_id,
                columns={
                    "snapshot_id": record.context.prediction_snapshot_id,
                    "symbol": record.context.symbol,
                },
                payload=_canonical_payload(record),
            )
            connection.commit()
            return inserted

    def chatgpt_research(self, snapshot_id: str) -> tuple[ChatGPTResearchRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chatgpt_research_records WHERE snapshot_id = ? ORDER BY research_id",
                (snapshot_id,),
            ).fetchall()
            result = []
            for row in rows:
                _verify_hashed_row("chatgpt_research_records", row)
                record = _parse_model(ChatGPTResearchRecord, row["payload"])
                _validate_chatgpt_record(connection, record)
                result.append(record)
        return tuple(sorted(result, key=lambda item: (
            item.comparison.completed_at, item.research_id,
        )))

    @staticmethod
    def _research_view(connection: sqlite3.Connection, run: ResearchRun) -> dict[str, Any]:
        snapshot_id = run.context.prediction_snapshot_id
        validate_context(run.context, _chatgpt_snapshot(connection, snapshot_id))
        passes = []
        for row in connection.execute(
            "SELECT * FROM chatgpt_research_passes WHERE snapshot_id = ? AND symbol = ?",
            (snapshot_id, run.context.symbol),
        ):
            _verify_hashed_row("chatgpt_research_passes", row)
            item = _parse_model(ResearchPass, row["payload"])
            if item.context == run.context:
                _validate_chatgpt_pass(connection, item)
                passes.append(item)
        attempts = []
        for row in connection.execute(
            "SELECT * FROM chatgpt_research_attempts WHERE run_id = ?", (run.run_id,),
        ):
            _verify_hashed_row("chatgpt_research_attempts", row)
            attempt = _parse_model(ResearchAttempt, row["payload"])
            _validate_chatgpt_attempt(connection, attempt)
            attempts.append(attempt)
        records = []
        for row in connection.execute(
            "SELECT * FROM chatgpt_research_records WHERE snapshot_id = ? AND symbol = ?",
            (snapshot_id, run.context.symbol),
        ):
            _verify_hashed_row("chatgpt_research_records", row)
            record = _parse_model(ChatGPTResearchRecord, row["payload"])
            if record.context == run.context:
                _validate_chatgpt_record(connection, record)
                records.append(record)
        return {
            "run": run.model_dump(mode="json"),
            "passes": [item.model_dump(mode="json") for item in sorted(
                passes, key=lambda item: (item.started_at, item.pass_id),
            )],
            "attempts": [item.model_dump(mode="json") for item in sorted(
                attempts, key=lambda item: (item.started_at, item.attempt_id),
            )],
            "record": None if not records else records[-1].model_dump(mode="json"),
        }

    def research_runs(
        self, snapshot_id: str, symbol: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chatgpt_research_runs WHERE snapshot_id = ?", (snapshot_id,),
            ).fetchall()
            runs = []
            for row in rows:
                _verify_hashed_row("chatgpt_research_runs", row)
                run = _parse_model(ResearchRun, row["payload"])
                if symbol is None or run.context.symbol == symbol:
                    runs.append(run)
            return tuple(self._research_view(connection, run) for run in sorted(
                runs, key=lambda run: (run.context.revision, run.run_id),
            ))

    def research_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            return self._research_view(connection, _chatgpt_run(connection, run_id))

    def begin_research(
        self, snapshot_id: str, symbol: str, configuration: ResearchConfiguration,
        *, company_name: str, now: datetime, rerun_previous_id: str | None = None,
        market_evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        configuration = ResearchConfiguration.model_validate_json(configuration.model_dump_json())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = _chatgpt_snapshot(connection, snapshot_id)
            rows = connection.execute(
                "SELECT * FROM chatgpt_research_runs WHERE snapshot_id = ? AND symbol = ?",
                (snapshot_id, symbol),
            ).fetchall()
            existing = []
            for row in rows:
                _verify_hashed_row("chatgpt_research_runs", row)
                existing.append(_parse_model(ResearchRun, row["payload"]))
            existing.sort(key=lambda item: item.context.revision)
            matching = [item for item in existing if item.context.configuration == configuration]
            if rerun_previous_id is None and matching:
                return self._research_view(connection, matching[-1])
            if rerun_previous_id is not None:
                if not matching or matching[-1].run_id != rerun_previous_id:
                    raise OperationalConflictError("research changed; reload before rerunning")
                previous = self._research_view(connection, matching[-1])
                if any(item["status"] == "running" for item in previous["attempts"]):
                    raise OperationalConflictError("research is still running")
            if any(
                connection.execute(
                    "SELECT 1 FROM chatgpt_research_attempts "
                    "WHERE run_id = ? AND status = 'running'",
                    (item.run_id,),
                ).fetchone() is not None for item in existing
            ):
                raise OperationalConflictError(
                    "research is still running with another configuration"
                )
            from stock_ai.operations.consultation import consultation_context

            context = ResearchContext(
                prediction_snapshot_id=snapshot_id, symbol=symbol, company_name=company_name,
                numerical_as_of=snapshot.as_of, research_as_of=now, configuration=configuration,
                revision=max((item.context.revision for item in existing), default=0) + 1,
                consultation=(consultation_context(snapshot, self.latest_portfolio(), now=now,
                                                  market_evidence=market_evidence)
                              if configuration.prompt_version == "market-portfolio-research-v2"
                              else None),
            )
            validate_context(context, snapshot)
            run = ResearchRun.create(context)
            self._insert_immutable(
                connection, table="chatgpt_research_runs", identity_column="run_id",
                identity=run.run_id, columns={"snapshot_id": snapshot_id, "symbol": symbol},
                payload=_canonical_payload(run),
            )
            result = self._research_view(connection, run)
            connection.commit()
            return result

    def claim_research(
        self, run_id: str, *, now: datetime, retry: bool = False,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = _chatgpt_run(connection, run_id)
            view = self._research_view(connection, run)
            if view["record"] is not None:
                return {"state": "completed", **view}
            first = next((
                ResearchPass.model_validate(item) for item in view["passes"]
                if item["phase"] == "independent"
            ), None)
            for attempt in view["attempts"]:
                if attempt["status"] == "running":
                    if attempt["phase"] == "independent":
                        request = independent_request(run.context)
                    else:
                        if first is None:
                            raise OperationalIntegrityError(
                                "Comparison missing independent research"
                            )
                        request = comparison_request(
                            run.context, first,
                            _chatgpt_snapshot(connection, run.context.prediction_snapshot_id),
                        )
                    return {"state": "running", "attempt": attempt, **view,
                            "request_sha256": content_id(request)}
            phase: Literal["independent", "comparison"] = (
                "independent" if first is None else "comparison"
            )
            failed = [item for item in view["attempts"] if item["phase"] == phase]
            if failed and not retry:
                return {"state": "blocked", "attempt": failed[-1], **view}
            item = ResearchAttempt(
                attempt_id=uuid4().hex, run_id=run_id, phase=phase, started_at=now,
            )
            _validate_chatgpt_attempt(connection, item)
            request = independent_request(run.context) if first is None else comparison_request(
                run.context, first,
                _chatgpt_snapshot(connection, run.context.prediction_snapshot_id),
            )
            self._insert_immutable(
                connection, table="chatgpt_research_attempts", identity_column="attempt_id",
                identity=item.attempt_id, columns={
                    "run_id": run_id, "phase": phase, "status": "running",
                }, payload=_canonical_payload(item),
            )
            connection.commit()
            return {
                "state": "ready", **view, "attempt": item.model_dump(mode="json"),
                "request_json": canonical_json(request), "request_sha256": content_id(request),
            }

    def finish_research(
        self, attempt_id: str, *, now: datetime, response: dict[str, Any] | None = None,
        started_at: datetime | None = None, completed_at: datetime | None = None,
        error_code: str | None = None, interrupted: bool = False,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM chatgpt_research_attempts WHERE attempt_id = ?", (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            _verify_hashed_row("chatgpt_research_attempts", row)
            attempt = _parse_model(ResearchAttempt, row["payload"])
            run = _chatgpt_run(connection, attempt.run_id)
            view = self._research_view(connection, run)
            if error_code is not None:
                finished = ResearchAttempt.model_validate({
                    **attempt.model_dump(), "status": "interrupted" if interrupted else "failed",
                    "error_code": error_code, "finished_at": now,
                })
            else:
                if response is None or started_at is None or completed_at is None:
                    raise ValueError("completed research requires a response and execution times")
                _require_research_receipt_times(attempt, started_at, completed_at, now)
                first = next((
                    ResearchPass.model_validate(item) for item in view["passes"]
                    if item["phase"] == "independent"
                ), None)
                try:
                    accepted = accept_response(
                        run.context, attempt.phase, response, snapshot=_chatgpt_snapshot(
                            connection, run.context.prediction_snapshot_id,
                        ), started_at=started_at, completed_at=completed_at,
                        independent=first if attempt.phase == "comparison" else None,
                    )
                except (ValueError, KeyError, TypeError, AttributeError):
                    if attempt.status != "running":
                        raise OperationalConflictError(
                            "research attempt is already terminal"
                        ) from None
                    finished = ResearchAttempt.model_validate({
                        **attempt.model_dump(), "status": "failed",
                        "error_code": "INVALID_RESEARCH_RESPONSE", "finished_at": completed_at,
                    })
                else:
                    if attempt.status == "completed" and attempt.pass_id == accepted.pass_id:
                        return view
                    if attempt.status != "running":
                        raise OperationalConflictError("research attempt is already terminal")
                    _validate_chatgpt_pass(connection, accepted)
                    self._insert_immutable(
                        connection, table="chatgpt_research_passes", identity_column="pass_id",
                        identity=accepted.pass_id, columns={
                            "snapshot_id": run.context.prediction_snapshot_id,
                            "symbol": run.context.symbol,
                        }, payload=_canonical_payload(accepted),
                    )
                    if attempt.phase == "comparison":
                        assert first is not None
                        record = create_record(run.context, first, accepted, _chatgpt_snapshot(
                            connection, run.context.prediction_snapshot_id,
                        ))
                        _validate_chatgpt_record(connection, record)
                        self._insert_immutable(
                            connection, table="chatgpt_research_records",
                            identity_column="research_id", identity=record.research_id,
                            columns={"snapshot_id": run.context.prediction_snapshot_id,
                                     "symbol": run.context.symbol},
                            payload=_canonical_payload(record),
                        )
                    finished = ResearchAttempt.model_validate({
                        **attempt.model_dump(), "status": "completed", "pass_id": accepted.pass_id,
                        "finished_at": completed_at,
                    })
            if attempt.status != "running":
                if (attempt.status, attempt.error_code) == (finished.status, finished.error_code):
                    return view
                raise OperationalConflictError("research attempt is already terminal")
            _validate_chatgpt_attempt(connection, finished)
            payload = _canonical_payload(finished)
            connection.execute(
                "UPDATE chatgpt_research_attempts SET status = ?, payload = ?, content_hash = ? "
                "WHERE attempt_id = ? AND status = 'running'",
                (finished.status, payload, _payload_hash(payload), attempt_id),
            )
            result = self._research_view(connection, run)
            connection.commit()
            return result

    def append_portfolio(self, portfolio: PortfolioState, *, created_at: datetime) -> bool:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        payload = _canonical_payload(portfolio)
        with self._connect() as connection:
            inserted = self._insert_immutable(
                connection,
                table="portfolio_states",
                identity_column="portfolio_id",
                identity=portfolio.portfolio_id,
                columns={
                    "as_of": portfolio.as_of.isoformat(),
                    "created_at": created_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()
        return inserted

    def set_metadata(self, key: str, value: str) -> None:
        if not key or not value:
            raise ValueError("operational metadata key/value cannot be blank")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO operational_metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
            connection.commit()

    def metadata(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM operational_metadata WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def portfolio(self, portfolio_id: str) -> PortfolioState:
        return self._load_one("portfolio_states", "portfolio_id", portfolio_id, PortfolioState)

    def latest_portfolio(self) -> PortfolioState | None:
        with self._connect() as connection:
            return _latest_portfolio_connection(connection)

    def portfolio_history(self, *, limit: int = 100) -> tuple[PortfolioState, ...]:
        """Read immutable ledger versions with the same integrity check as current state."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, content_hash FROM portfolio_states "
                "ORDER BY created_at DESC, portfolio_id DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return tuple(
            _parse_model(PortfolioState, _checked_payload(row, "portfolio_states"))
            for row in rows
        )

    def portfolio_edit_record(self, portfolio_id: str) -> dict[str, str] | None:
        raw = self.metadata("account_edit_record:" + portfolio_id)
        if raw is None:
            return None
        try:
            envelope = json.loads(raw)
            payload = _checked_payload_values(
                envelope["payload"], envelope["sha256"], "account_edit_record"
            )
            value = json.loads(payload)
            if value["portfolio_id"] != portfolio_id or not isinstance(value["record"], dict):
                raise ValueError("invalid correction record")
            return dict(value["record"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OperationalIntegrityError("invalid correction record") from exc

    def archive_proposal(
        self,
        proposal: PortfolioProposal,
        *,
        archived_at: datetime,
        decision_policy: DecisionPolicySnapshot,
        publication_status: DailyOperationStatus | None = None,
    ) -> bool:
        if archived_at.tzinfo is None or archived_at.utcoffset() is None:
            raise ValueError("archived_at must be timezone-aware")
        if archived_at < proposal.generated_at:
            raise ValueError("proposal cannot be archived before generation")
        _validate_decision_policy_snapshot(decision_policy, proposal)
        if publication_status is not None and (
            publication_status.pipeline_state is not PipelineState.PROPOSAL_READY
            or publication_status.proposal_id != proposal.proposal_id
            or publication_status.updated_at != archived_at
            or publication_status.is_stale or publication_status.blocking_reason is not None
        ):
            raise ValueError("proposal publication status must describe this archive")
        payload = _canonical_payload(proposal)
        business_date = proposal.as_of.astimezone(JST).date()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT 1 FROM proposals WHERE proposal_id=?",
                                          (proposal.proposal_id,)).fetchone()
            if proposal.personal_guard is not None and existing is None:
                _guard_personal_publication(connection, proposal.personal_guard, proposal)
            if (
                connection.execute(
                    "SELECT 1 FROM portfolio_states WHERE portfolio_id = ?",
                    (proposal.current_portfolio_id,),
                ).fetchone()
                is None
            ):
                raise OperationalIntegrityError("proposal references an unarchived portfolio")
            later_proposal = connection.execute(
                """
                SELECT 1 FROM paper_outcomes AS outcome
                JOIN proposals AS existing ON existing.proposal_id = outcome.proposal_id
                WHERE existing.business_date = ? AND existing.proposal_id != ? LIMIT 1
                """,
                (business_date.isoformat(), proposal.proposal_id),
            ).fetchone()
            if later_proposal is not None:
                raise OperationalConflictError(
                    "a business date with a Paper outcome cannot accept a later proposal"
                )
            inserted = self._insert_immutable(
                connection,
                table="proposals",
                identity_column="proposal_id",
                identity=proposal.proposal_id,
                columns={
                    "business_date": business_date.isoformat(),
                    "as_of": proposal.as_of.isoformat(),
                    "generated_at": proposal.generated_at.isoformat(),
                    "current_portfolio_id": proposal.current_portfolio_id,
                    "archived_at": archived_at.isoformat(),
                },
                payload=payload,
            )
            archive_row = connection.execute(
                "SELECT payload, content_hash FROM proposal_archives WHERE proposal_id = ?",
                (proposal.proposal_id,),
            ).fetchone()
            if archive_row is None:
                stored = connection.execute(
                    "SELECT archived_at FROM proposals WHERE proposal_id = ?",
                    (proposal.proposal_id,),
                ).fetchone()
                if stored is None:
                    raise OperationalIntegrityError("archived proposal disappeared")
                stored_archived_at = str(stored["archived_at"])
                archive_payload = json.dumps(
                    {
                        "archived_at": stored_archived_at,
                        "proposal_id": proposal.proposal_id,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self._insert_immutable(
                    connection,
                    table="proposal_archives",
                    identity_column="proposal_id",
                    identity=proposal.proposal_id,
                    columns={"archived_at": stored_archived_at},
                    payload=archive_payload,
                )
            else:
                parsed_archive = json.loads(_checked_payload(archive_row, "proposal_archives"))
                if parsed_archive.get("proposal_id") != proposal.proposal_id:
                    raise OperationalIntegrityError("proposal archive identity mismatch")
            self._insert_immutable(
                connection,
                table="decision_policy_snapshots",
                identity_column="proposal_id",
                identity=decision_policy.proposal_id,
                columns={
                    "captured_at": decision_policy.captured_at.isoformat(),
                    "engine_version": decision_policy.config.version,
                },
                payload=_canonical_payload(decision_policy),
            )
            if publication_status is not None and inserted:
                _write_daily_status(connection, publication_status)
            connection.commit()
        return inserted

    def proposal(self, proposal_id: str) -> PortfolioProposal:
        return self._load_one("proposals", "proposal_id", proposal_id, PortfolioProposal)

    def proposal_inputs_current(self, proposal: PortfolioProposal) -> bool:
        if proposal.personal_guard is None:
            return True
        with self._connect() as connection:
            try:
                _guard_personal_publication(connection, proposal.personal_guard, proposal)
            except OperationalConflictError:
                return False
        return True

    def recheck_personal_publication(
        self, proposal: PortfolioProposal, status: DailyOperationStatus,
    ) -> None:
        if (proposal.personal_guard is None
                or status.pipeline_state is not PipelineState.PROPOSAL_READY
                or status.proposal_id != proposal.proposal_id or status.is_stale):
            raise ValueError("guarded proposal recheck required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _guard_personal_publication(connection, proposal.personal_guard, proposal)
            row = connection.execute("SELECT payload,content_hash FROM daily_status "
                                     "WHERE business_date=?", (status.business_date.isoformat(),)
                                     ).fetchone()
            if row is None:
                raise OperationalIntegrityError("published proposal daily status missing")
            previous = _parse_model(DailyOperationStatus, _checked_payload(row, "daily_status"))
            if (previous.proposal_id == proposal.proposal_id and not previous.is_stale
                    and previous.pipeline_state in {PipelineState.PROPOSAL_READY,
                        PipelineState.USER_DECISION_SAVED, PipelineState.EXECUTION_PENDING,
                        PipelineState.EXECUTION_RECORDED, PipelineState.MARKET_CLOSED}):
                return
            decision = connection.execute(
                "SELECT payload,content_hash FROM user_decisions WHERE proposal_id=? "
                "ORDER BY version DESC LIMIT 1", (proposal.proposal_id,),
            ).fetchone()
            if decision is not None:
                _parse_model(UserDecision, _checked_payload(decision, "user_decisions"))
                status = status.model_copy(update={
                    "pipeline_state": PipelineState.USER_DECISION_SAVED,
                })
            _write_daily_status(connection, status)
            connection.commit()

    def publish_cash_only(
        self, receipt_id: str, guard: PersonalInputReferences, status: DailyOperationStatus,
        *, numerical_run_id: str,
    ) -> None:
        if (len(receipt_id) != 64 or any(x not in "0123456789abcdef" for x in receipt_id)
                or status.pipeline_state is not PipelineState.CASH_ONLY or status.proposal_id
                or status.is_stale):
            raise ValueError("valid cash-only publication required")
        marker = canonical_json({"receipt_id": receipt_id, "guard": guard.model_dump(mode="json"),
                                 "status": status.model_dump(mode="json"),
                                 "numerical_run_id": numerical_run_id})
        key = "mobile-cash-receipt:" + receipt_id
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT value FROM operational_metadata WHERE key=?",
                                          (key,)).fetchone()
            if previous is not None:
                if previous[0] != marker:
                    raise OperationalIntegrityError("cash-only receipt changed")
                return  # An ACK retry must not reactivate or retimestamp an old result.
            ledger = _guard_personal_references(connection, guard)
            selected = _mobile_numerical_selection(connection)
            if (selected is None or selected["run_id"] != numerical_run_id
                    or selected["snapshot_id"] is not None
                    or datetime.fromisoformat(selected["as_of"]).astimezone(JST).date()
                    != status.business_date):
                raise OperationalConflictError("cash-only numerical receipt changed")
            if any(position.shares > 0 for position in ledger.positions):
                raise OperationalConflictError("cash-only publication has current holdings")
            connection.execute("INSERT INTO operational_metadata VALUES(?,?)", (key, marker))
            connection.execute("INSERT OR REPLACE INTO operational_metadata VALUES(?,?)", (
                "mobile-cash-active:" + status.business_date.isoformat(), receipt_id,
            ))
            _write_daily_status(connection, status)
            connection.commit()

    def cash_only_inputs_current(self, business_date: date) -> bool:
        identity = self.metadata("mobile-cash-active:" + business_date.isoformat())
        marker = None if identity is None else self.metadata("mobile-cash-receipt:" + identity)
        if marker is None or identity is None:
            raise OperationalIntegrityError("cash-only publication receipt missing")
        value = _cash_receipt(marker, identity)
        guard = PersonalInputReferences.model_validate(value["guard"])
        status = DailyOperationStatus.model_validate(value["status"])
        if value["receipt_id"] != identity or status.business_date != business_date:
            raise OperationalIntegrityError("cash-only publication reference changed")
        with self._connect() as connection:
            selected = _mobile_numerical_selection(connection)
            if (selected is None or selected["run_id"] != value["numerical_run_id"]
                    or selected["snapshot_id"] is not None):
                return False
            try:
                ledger = _guard_personal_references(connection, guard)
            except OperationalConflictError:
                return False
        return not any(position.shares > 0 for position in ledger.positions)

    def recheck_cash_publication(self, receipt_id: str, status: DailyOperationStatus) -> None:
        marker = self.metadata("mobile-cash-receipt:" + receipt_id)
        if marker is None:
            raise OperationalIntegrityError("cash-only publication receipt missing")
        value = _cash_receipt(marker, receipt_id)
        guard = PersonalInputReferences.model_validate(value["guard"])
        if (status.pipeline_state is not PipelineState.CASH_ONLY
                or status.business_date.isoformat() != value["status"]["business_date"]
                or status.is_stale or status.proposal_id is not None):
            raise ValueError("valid cash-only recheck required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            ledger = _guard_personal_references(connection, guard)
            selected = _mobile_numerical_selection(connection)
            if (any(x.shares > 0 for x in ledger.positions) or selected is None
                    or selected["run_id"] != value["numerical_run_id"]
                    or selected["snapshot_id"] is not None):
                raise OperationalConflictError("cash-only recheck inputs changed")
            previous = connection.execute(
                "SELECT payload,content_hash FROM daily_status WHERE business_date=?",
                (status.business_date.isoformat(),),
            ).fetchone()
            if previous is not None:
                prior = _parse_model(DailyOperationStatus,
                                     _checked_payload(previous, "daily_status"))
                active = connection.execute("SELECT value FROM operational_metadata WHERE key=?",
                                            ("mobile-cash-active:" +
                                             status.business_date.isoformat(),)).fetchone()
                if (prior.pipeline_state is PipelineState.CASH_ONLY and not prior.is_stale
                        and active is not None and active[0] == receipt_id):
                    return
            connection.execute("INSERT OR REPLACE INTO operational_metadata VALUES(?,?)", (
                "mobile-cash-active:" + status.business_date.isoformat(), receipt_id,
            ))
            _write_daily_status(connection, status)
            connection.commit()

    def decision_policy_snapshot(self, proposal_id: str) -> DecisionPolicySnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload, content_hash FROM decision_policy_snapshots
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
        return (
            None
            if row is None
            else _parse_model(
                DecisionPolicySnapshot,
                _checked_payload(row, "decision_policy_snapshots"),
            )
        )

    def latest_proposal(self, business_date: date) -> PortfolioProposal | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload, content_hash FROM proposals
                WHERE business_date = ? ORDER BY generated_at DESC, proposal_id DESC LIMIT 1
                """,
                (business_date.isoformat(),),
            ).fetchone()
        return (
            None
            if row is None
            else _parse_model(PortfolioProposal, _checked_payload(row, "proposals"))
        )

    def review_decision(
        self,
        proposal_id: str,
        selected_targets: Mapping[str, int],
    ) -> DecisionReview:
        proposal = self.proposal(proposal_id)
        portfolio = self.portfolio(proposal.current_portfolio_id)
        expected_line_ids = {line.line_id for line in proposal.lines}
        if set(selected_targets) != expected_line_ids:
            raise OperationalConflictError("decision must cover every proposal line exactly once")
        cash_after = {
            item.account_bucket_id: item.available_cash - item.reserved_cash
            for item in portfolio.cash
        }
        estimated_buy = Decimal("0")
        estimated_sell = Decimal("0")
        estimated_cost = Decimal("0")
        estimated_tax = Decimal("0")
        violations: list[str] = []
        resulting_positions = 0
        normalized_targets: dict[str, int] = {}
        all_current = all(
            selected_targets[line.line_id] == line.current_shares for line in proposal.lines
        )
        for line in proposal.lines:
            target = selected_targets[line.line_id]
            if target < 0:
                raise ValueError("selected target shares cannot be negative")
            delta = target - line.current_shares
            if delta % 100 != 0:
                violations.append(f"{line.line_id}: 売買差分は100株単位で指定してください")
            if target not in {line.current_shares, line.recommended_shares}:
                violations.append(
                    f"{line.line_id}: この株数は再最適化されていないため保存できません"
                )
            if line.share_difference < 0 and target == line.current_shares and not all_current:
                violations.append(f"{line.line_id}: 売却だけの取消は全体再最適化が必要です")
            normalized_targets[line.line_id] = target
            resulting_positions += int(target > 0)
            if delta == 0:
                continue
            notional = line.reference_price * abs(delta)
            exact_recommendation = target == line.recommended_shares
            base_delta = abs(line.share_difference)
            scale = (
                Decimal("1")
                if exact_recommendation
                else Decimal(abs(delta)) / Decimal(base_delta or 100)
            )
            line_cost = line.transaction_cost.total * scale
            line_tax_cash = line.estimated_tax_cash_withholding * scale
            line_tax_effect = line.estimated_tax_effect * scale
            estimated_cost += line_cost
            estimated_tax += line_tax_effect
            if delta > 0:
                estimated_buy += notional
                cash_after[line.account_bucket_id] -= notional + line_cost + line_tax_cash
            else:
                estimated_sell += notional
                cash_after[line.account_bucket_id] += notional - line_cost - line_tax_cash
        for bucket_id, value in sorted(cash_after.items()):
            if value < 0:
                violations.append(f"{bucket_id}: 利用可能現金を{-value}円超えています")
        maximum_endpoint_positions = max(
            len(portfolio.positions),
            sum(line.recommended_shares > 0 for line in proposal.lines),
        )
        if resulting_positions > maximum_endpoint_positions:
            violations.append("選択の組合せは保有銘柄数の再最適化が必要です")
        return DecisionReview(
            proposal_id=proposal_id,
            selected_targets=normalized_targets,
            estimated_cash_after=cash_after,
            estimated_buy_value=estimated_buy,
            estimated_sell_value=estimated_sell,
            estimated_transaction_cost=estimated_cost,
            estimated_tax_effect=estimated_tax,
            resulting_positions=resulting_positions,
            constraint_violations=tuple(violations),
        )

    def save_decision(self, decision: UserDecision) -> bool:
        proposal = self.proposal(decision.proposal_id)
        if decision.saved_at < proposal.generated_at:
            raise ValueError("decision cannot be saved before proposal generation")
        selected = {line.proposal_line_id: line.selected_target_shares for line in decision.lines}
        review = self.review_decision(decision.proposal_id, selected)
        if review.constraint_violations:
            raise OperationalConflictError("decision has unresolved constraint violations")
        payload = _canonical_payload(decision)
        with self._connect() as connection:
            last = connection.execute(
                "SELECT MAX(version) AS version FROM user_decisions WHERE proposal_id = ?",
                (decision.proposal_id,),
            ).fetchone()
            last_version = 0 if last is None or last["version"] is None else int(last["version"])
            existing = connection.execute(
                "SELECT payload, content_hash FROM user_decisions WHERE decision_id = ?",
                (decision.decision_id,),
            ).fetchone()
            if existing is None and decision.version != last_version + 1:
                raise OperationalConflictError("decision version must be sequential")
            inserted = self._insert_immutable(
                connection,
                table="user_decisions",
                identity_column="decision_id",
                identity=decision.decision_id,
                columns={
                    "proposal_id": decision.proposal_id,
                    "version": decision.version,
                    "saved_at": decision.saved_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()
        return inserted

    def decision(self, decision_id: str) -> UserDecision:
        return self._load_one("user_decisions", "decision_id", decision_id, UserDecision)

    def latest_decision(self, proposal_id: str) -> UserDecision | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload, content_hash FROM user_decisions
                WHERE proposal_id = ? ORDER BY version DESC LIMIT 1
                """,
                (proposal_id,),
            ).fetchone()
        return (
            None
            if row is None
            else _parse_model(UserDecision, _checked_payload(row, "user_decisions"))
        )

    def append_execution(
        self,
        execution: ExecutionRecord,
        *,
        confirm_difference: bool = False,
        update_daily_status: bool = False,
    ) -> bool:
        payload = _canonical_payload(execution)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mismatch = self._execution_differs_from_decision(execution, connection=connection)
            if mismatch and not confirm_difference:
                raise OperationalConflictError(
                    "execution differs from the saved decision; explicit confirmation is required"
                )
            inserted = self._insert_immutable(
                connection,
                table="executions",
                identity_column="execution_id",
                identity=execution.execution_id,
                columns={
                    "decision_id": execution.decision_id,
                    "executed_at": execution.executed_at.isoformat(),
                },
                payload=payload,
            )
            if inserted and update_daily_status:
                proposal = self.proposal(self.decision(execution.decision_id).proposal_id)
                day = proposal.as_of.astimezone(JST).date()
                previous = self.daily_status(day)
                execution_state = (
                    PipelineState.EXECUTION_PENDING
                    if execution.status in {
                        ExecutionStatus.NOT_ORDERED, ExecutionStatus.OPEN,
                        ExecutionStatus.PARTIALLY_FILLED,
                    }
                    else PipelineState.EXECUTION_RECORDED
                )
                _write_daily_status(connection, DailyOperationStatus(
                    business_date=day, pipeline_state=execution_state,
                    updated_at=execution.executed_at,
                    data_as_of=None if previous is None else previous.data_as_of,
                    morning_data_as_of=None if previous is None else previous.morning_data_as_of,
                    proposal_id=proposal.proposal_id,
                ))
            connection.commit()
        return inserted

    def _execution_differs_from_decision(
        self,
        execution: ExecutionRecord,
        *,
        additional_filled_shares: int = 0,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        def load[ModelT: BaseModel](
            table: str, key: str, identity: str, model: type[ModelT]
        ) -> ModelT:
            if connection is None:
                return self._load_one(table, key, identity, model)
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {key} = ?", (identity,)
            ).fetchone()
            if row is None:
                raise KeyError(identity)
            _verify_hashed_row(table, row)
            return _parse_model(model, _checked_payload(row, table))

        decision = load("user_decisions", "decision_id", execution.decision_id, UserDecision)
        if execution.executed_at < decision.saved_at:
            raise OperationalTimelineError("execution timestamp cannot precede the saved decision")
        proposal = load("proposals", "proposal_id", decision.proposal_id, PortfolioProposal)
        decision_targets = {
            item.proposal_line_id: item.selected_target_shares for item in decision.lines
        }
        matching = next(
            (
                line
                for line in proposal.lines
                if line.symbol == execution.symbol
                and line.account_bucket_id == execution.account_bucket_id
            ),
            None,
        )
        if matching is None:
            raise OperationalConflictError("execution does not match a decided proposal line")
        intended_delta = decision_targets[matching.line_id] - matching.current_shares
        intended_side = TradeSide.BUY if intended_delta > 0 else TradeSide.SELL
        mismatch = (
            intended_delta == 0
            or execution.side is not intended_side
            or execution.ordered_shares != abs(intended_delta)
        )
        existing_executions = (
            self.executions(decision_id=execution.decision_id)
            if connection is None
            else tuple(
                load("executions", "execution_id", row[0], ExecutionRecord)
                for row in connection.execute(
                    "SELECT execution_id FROM executions WHERE decision_id = ?",
                    (execution.decision_id,),
                )
            )
        )
        existing_filled = sum(
            item.filled_shares
            for item in existing_executions
            if item.execution_id != execution.execution_id
            and item.symbol == execution.symbol
            and item.account_bucket_id == execution.account_bucket_id
            and item.side is execution.side
        )
        mismatch = mismatch or (
            existing_filled + additional_filled_shares + execution.filled_shares
            > abs(intended_delta)
        )
        return mismatch

    def executions(self, *, decision_id: str | None = None) -> tuple[ExecutionRecord, ...]:
        query = "SELECT payload, content_hash FROM executions"
        params: tuple[object, ...] = ()
        if decision_id is not None:
            query += " WHERE decision_id = ?"
            params = (decision_id,)
        query += " ORDER BY executed_at, execution_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(
            _parse_model(ExecutionRecord, _checked_payload(row, "executions")) for row in rows
        )

    def apply_unapplied_executions(
        self,
        *,
        next_as_of: datetime,
        next_portfolio_id: str,
        created_at: datetime,
    ) -> PortfolioState:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if next_as_of.tzinfo is None or next_as_of.utcoffset() is None:
            raise ValueError("next_as_of must be timezone-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            portfolio = _latest_portfolio_connection(connection)
            if portfolio is None:
                raise OperationalIntegrityError("cannot apply executions without a portfolio")
            if next_as_of <= portfolio.as_of:
                raise OperationalConflictError(
                    "next_as_of must be later than the current portfolio as_of"
                )
            unapplied = tuple(
                item
                for item in self.executions()
                if item.execution_id not in portfolio.applied_execution_ids
                and item.filled_shares > 0
            )
            next_state = apply_executions(
                portfolio,
                unapplied,
                next_as_of=next_as_of,
                next_portfolio_id=next_portfolio_id,
            )
            payload = _canonical_payload(next_state)
            self._insert_immutable(
                connection,
                table="portfolio_states",
                identity_column="portfolio_id",
                identity=next_state.portfolio_id,
                columns={
                    "as_of": next_state.as_of.isoformat(),
                    "created_at": created_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()
        return next_state

    def set_daily_status(self, status: DailyOperationStatus) -> None:
        with self._connect() as connection:
            _write_daily_status(connection, status)
            connection.commit()

    def daily_status(self, business_date: date) -> DailyOperationStatus | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, content_hash FROM daily_status WHERE business_date = ?",
                (business_date.isoformat(),),
            ).fetchone()
        return (
            None
            if row is None
            else _parse_model(DailyOperationStatus, _checked_payload(row, "daily_status"))
        )

    def append_job(self, job: AutomationJobRecord) -> bool:
        payload = _canonical_payload(job)
        with self._connect() as connection:
            inserted = self._insert_immutable(
                connection,
                table="automation_jobs",
                identity_column="run_id",
                identity=job.run_id,
                columns={
                    "idempotency_key": job.idempotency_key,
                    "business_date": job.business_date.isoformat(),
                    "stage": job.stage.value,
                    "status": job.status.value,
                },
                payload=payload,
            )
            connection.commit()
        return inserted

    def finish_job(
        self,
        job: AutomationJobRecord,
        *,
        required_lock: tuple[str, str, datetime] | None = None,
    ) -> None:
        if job.status is JobStatus.RUNNING:
            raise ValueError("finished automation job must be terminal")
        payload = _canonical_payload(job)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if required_lock is not None:
                lock_name, owner, checked_at = required_lock
                lock_row = connection.execute(
                    "SELECT owner, expires_at FROM process_locks WHERE lock_name = ?",
                    (lock_name,),
                ).fetchone()
                if (
                    lock_row is None
                    or str(lock_row["owner"]) != owner
                    or datetime.fromisoformat(str(lock_row["expires_at"])) <= checked_at
                ):
                    raise OperationalConflictError(
                        "automation success requires current workflow lock ownership"
                    )
            row = connection.execute(
                "SELECT payload, content_hash FROM automation_jobs WHERE run_id = ?",
                (job.run_id,),
            ).fetchone()
            if row is None:
                raise OperationalIntegrityError("automation job was not durably started")
            started = _parse_model(AutomationJobRecord, _checked_payload(row, "automation_jobs"))
            if (
                started.status is not JobStatus.RUNNING
                or started.idempotency_key != job.idempotency_key
                or started.business_date != job.business_date
                or started.stage is not job.stage
                or started.started_at != job.started_at
            ):
                raise OperationalConflictError("automation job transition is inconsistent")
            connection.execute(
                """
                UPDATE automation_jobs
                SET status = ?, payload = ?, content_hash = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    job.status.value,
                    payload,
                    _payload_hash(payload),
                    job.run_id,
                    JobStatus.RUNNING.value,
                ),
            )
            if connection.total_changes != 1:
                raise OperationalConflictError("automation job was already finished")
            connection.commit()

    def job_for_key(self, idempotency_key: str) -> AutomationJobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, content_hash FROM automation_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return (
            None
            if row is None
            else _parse_model(AutomationJobRecord, _checked_payload(row, "automation_jobs"))
        )

    def jobs(
        self,
        *,
        business_date: date | None = None,
        stage: AutomationStage | None = None,
    ) -> tuple[AutomationJobRecord, ...]:
        clauses: list[str] = []
        params: list[object] = []
        if business_date is not None:
            clauses.append("business_date = ?")
            params.append(business_date.isoformat())
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage.value)
        query = "SELECT payload, content_hash FROM automation_jobs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY run_id"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return tuple(
            _parse_model(AutomationJobRecord, _checked_payload(row, "automation_jobs"))
            for row in rows
        )

    def acquire_lock(
        self,
        lock_name: str,
        *,
        owner: str,
        now: datetime,
        ttl: timedelta = timedelta(minutes=30),
    ) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("lock time must be timezone-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner, expires_at FROM process_locks WHERE lock_name = ?",
                (lock_name,),
            ).fetchone()
            if row is not None and datetime.fromisoformat(str(row["expires_at"])) > now:
                connection.rollback()
                return str(row["owner"]) == owner
            connection.execute(
                """
                INSERT INTO process_locks(lock_name, owner, expires_at) VALUES (?, ?, ?)
                ON CONFLICT(lock_name) DO UPDATE SET
                    owner=excluded.owner, expires_at=excluded.expires_at
                """,
                (lock_name, owner, (now + ttl).isoformat()),
            )
            connection.commit()
        return True

    def release_lock(self, lock_name: str, *, owner: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM process_locks WHERE lock_name = ? AND owner = ?",
                (lock_name, owner),
            )
            connection.commit()

    def refresh_lock(
        self,
        lock_name: str,
        *,
        owner: str,
        now: datetime,
        ttl: timedelta = timedelta(minutes=30),
    ) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("lock time must be timezone-aware")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE process_locks SET expires_at = ?
                WHERE lock_name = ? AND owner = ? AND expires_at > ?
                """,
                ((now + ttl).isoformat(), lock_name, owner, now.isoformat()),
            )
            refreshed = connection.total_changes == 1
            connection.commit()
        return refreshed

    def append_notification(self, notification: NotificationRecord) -> bool:
        payload = _canonical_payload(notification)
        with self._connect() as connection:
            inserted = self._insert_immutable(
                connection,
                table="notifications",
                identity_column="notification_id",
                identity=notification.notification_id,
                columns={
                    "proposal_id": notification.proposal_id,
                    "status": notification.status.value,
                    "created_at": notification.created_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()
        return inserted

    def notifications(self, *, limit: int = 50) -> tuple[NotificationRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, content_hash FROM notifications ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(
            _parse_model(NotificationRecord, _checked_payload(row, "notifications")) for row in rows
        )

    def append_rankings(self, rankings: Iterable[RankingRecord]) -> int:
        inserted_count = 0
        with self._connect() as connection:
            for ranking in rankings:
                payload = _canonical_payload(ranking)
                inserted_count += int(
                    self._insert_immutable(
                        connection,
                        table="rankings",
                        identity_column="ranking_id",
                        identity=ranking.ranking_id,
                        columns={
                            "as_of": ranking.as_of.isoformat(),
                            "rank_type": ranking.rank_type,
                            "rank": ranking.rank,
                        },
                        payload=payload,
                    )
                )
            connection.commit()
        return inserted_count

    def latest_rankings(self, rank_type: str, *, limit: int = 50) -> tuple[RankingRecord, ...]:
        with self._connect() as connection:
            latest = connection.execute(
                "SELECT MAX(as_of) AS as_of FROM rankings WHERE rank_type = ?", (rank_type,)
            ).fetchone()
            if latest is None or latest["as_of"] is None:
                return ()
            rows = connection.execute(
                """
                SELECT payload, content_hash FROM rankings WHERE rank_type = ? AND as_of = ?
                ORDER BY rank LIMIT ?
                """,
                (rank_type, str(latest["as_of"]), limit),
            ).fetchall()
        return tuple(_parse_model(RankingRecord, _checked_payload(row, "rankings")) for row in rows)

    def append_paper_calendar(self, calendar: PaperCalendarSnapshot) -> bool:
        payload = _canonical_payload(calendar)
        with self._connect() as connection:
            inserted = self._insert_immutable(
                connection,
                table="paper_calendars",
                identity_column="calendar_snapshot_id",
                identity=calendar.calendar_snapshot_id,
                columns={
                    "source_snapshot_id": calendar.source_snapshot_id,
                    "created_at": calendar.created_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()
        return inserted

    def paper_calendar(self, calendar_snapshot_id: str) -> PaperCalendarSnapshot:
        return self._load_one(
            "paper_calendars",
            "calendar_snapshot_id",
            calendar_snapshot_id,
            PaperCalendarSnapshot,
        )

    def append_paper_outcome(self, outcome: PaperOutcome) -> bool:
        proposal = self.proposal(outcome.proposal_id)
        if outcome.champion_version != proposal.model_bundle_version:
            raise OperationalConflictError(
                "Paper champion version must match the archived proposal model bundle"
            )
        try:
            archive = json.loads(
                self._load_payload("proposal_archives", "proposal_id", outcome.proposal_id)
            )
            archived_at = datetime.fromisoformat(str(archive["archived_at"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationalIntegrityError("proposal archive evidence is invalid") from exc
        if archive.get("proposal_id") != outcome.proposal_id:
            raise OperationalIntegrityError("proposal archive evidence identity mismatch")
        if archived_at.tzinfo is None or archived_at.utcoffset() is None:
            raise OperationalIntegrityError("proposal archive timestamp is not timezone-aware")
        if outcome.observed_at < archived_at:
            raise ValueError("Paper outcome cannot be observed before proposal archival")
        if archived_at >= outcome.label_end_at:
            raise ValueError("Paper proposal must be archived before its outcome endpoint")
        business_date = proposal.as_of.astimezone(JST).date()
        try:
            calendar = self.paper_calendar(outcome.calendar_snapshot_id)
        except KeyError as exc:
            raise OperationalIntegrityError(
                "Paper outcome requires an authenticated calendar snapshot"
            ) from exc
        if calendar.source_snapshot_id not in outcome.source_snapshot_ids:
            raise OperationalIntegrityError(
                "Paper outcome must preserve the calendar source snapshot lineage"
            )
        if calendar.created_at > archived_at:
            raise ValueError("Paper calendar must be frozen before proposal archival")
        try:
            proposal_position = calendar.session_dates.index(business_date)
        except ValueError as exc:
            raise OperationalIntegrityError(
                "proposal business date is absent from the authenticated calendar"
            ) from exc
        expected_sessions = calendar.session_dates[
            proposal_position + 1 : proposal_position + 1 + outcome.horizon_sessions
        ]
        if (
            len(expected_sessions) != outcome.horizon_sessions
            or expected_sessions != outcome.horizon_session_dates
        ):
            raise ValueError("Paper outcome session path must match the authenticated JPX calendar")
        payload = _canonical_payload(outcome)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = self.latest_proposal(business_date)
            if latest is None or latest.proposal_id != outcome.proposal_id:
                raise OperationalConflictError(
                    "Paper outcome must reference the final archived proposal for its business date"
                )
            existing_horizons = connection.execute(
                "SELECT payload, content_hash FROM paper_outcomes",
            ).fetchall()
            for row in existing_horizons:
                existing = _parse_model(PaperOutcome, _checked_payload(row, "paper_outcomes"))
                if existing.outcome_id == outcome.outcome_id:
                    continue
                existing_proposal = self.proposal(existing.proposal_id)
                existing_date = existing_proposal.as_of.astimezone(JST).date()
                if existing_date == business_date and (
                    existing.horizon_sessions == outcome.horizon_sessions
                ):
                    raise OperationalConflictError(
                        "a business date can have only one immutable Paper outcome per horizon"
                    )
            inserted = self._insert_immutable(
                connection,
                table="paper_outcomes",
                identity_column="outcome_id",
                identity=outcome.outcome_id,
                columns={
                    "proposal_id": outcome.proposal_id,
                    "observed_at": outcome.observed_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()
        return inserted

    def paper_outcomes(self, *, horizon_sessions: int | None = None) -> tuple[PaperOutcome, ...]:
        if horizon_sessions is not None and horizon_sessions <= 0:
            raise ValueError("paper horizon must be positive")
        with self._connect() as connection:
            rows = connection.execute("SELECT payload, content_hash FROM paper_outcomes").fetchall()
        outcomes = tuple(
            sorted(
                (
                    _parse_model(PaperOutcome, _checked_payload(row, "paper_outcomes"))
                    for row in rows
                ),
                key=lambda item: (item.label_end_at.astimezone(JST), item.outcome_id),
            )
        )
        if horizon_sessions is None:
            return outcomes
        return tuple(item for item in outcomes if item.horizon_sessions == horizon_sessions)

    def paper_summary(
        self,
        *,
        minimum_observations: int = 20,
        drift_window: int = 10,
        drift_degradation_ratio: float = 1.25,
    ) -> PaperSummary:
        if minimum_observations <= 0:
            raise ValueError("minimum_observations must be positive")
        if drift_window <= 0:
            raise ValueError("drift_window must be positive")
        if not math.isfinite(drift_degradation_ratio) or drift_degradation_ratio <= 1:
            raise ValueError("drift_degradation_ratio must be finite and greater than one")
        outcomes = self.paper_outcomes(horizon_sessions=1)
        if not outcomes:
            return PaperSummary(
                observations=0,
                proposal_return=None,
                benchmark_return=None,
                excess_return=None,
                maximum_drawdown=None,
                mean_cost_error=None,
                mean_tax_error=None,
                champion_mean_absolute_error=None,
                challenger_mean_absolute_error=None,
                challenger_better_rate=None,
                champion_version=None,
                champion_observations=0,
                challenger_version=None,
                challenger_observations=0,
                drift_status=ModelDriftStatus.INSUFFICIENT_OBSERVATIONS,
                drift_ratio=None,
                drift_window=drift_window,
                minimum_observation_count=minimum_observations,
                is_decision_ready=False,
                model_monitoring_ready=False,
                updated_at=None,
            )
        proposal_value = 1.0
        benchmark_value = 1.0
        peak = 1.0
        maximum_drawdown = 0.0
        cost_errors: list[Decimal] = []
        tax_errors: list[Decimal] = []
        for item in outcomes:
            proposal_value *= 1.0 + item.proposal_return
            benchmark_value *= 1.0 + item.benchmark_return
            peak = max(peak, proposal_value)
            maximum_drawdown = min(maximum_drawdown, proposal_value / peak - 1.0)
            if item.actual_cost is not None:
                cost_errors.append(item.actual_cost - item.estimated_cost)
            if item.audited_tax_effect is not None:
                tax_errors.append(item.audited_tax_effect - item.estimated_tax_effect)
        proposal_return = proposal_value - 1.0
        benchmark_return = benchmark_value - 1.0
        champion_version = outcomes[-1].champion_version
        champion_cohort_reversed: list[PaperOutcome] = []
        for item in reversed(outcomes):
            if item.champion_version != champion_version:
                break
            champion_cohort_reversed.append(item)
        champion_cohort = tuple(reversed(champion_cohort_reversed))
        champion_errors = [item.champion_absolute_error for item in champion_cohort]
        challenger_version = champion_cohort[-1].challenger_version
        challenger_pairs_reversed: list[tuple[float, float]] = []
        if challenger_version is not None:
            for item in reversed(champion_cohort):
                if (
                    item.challenger_version != challenger_version
                    or item.challenger_absolute_error is None
                ):
                    break
                challenger_pairs_reversed.append(
                    (item.champion_absolute_error, float(item.challenger_absolute_error))
                )
        challenger_pairs = list(reversed(challenger_pairs_reversed))
        drift_status = ModelDriftStatus.INSUFFICIENT_OBSERVATIONS
        drift_ratio: float | None = None
        if len(champion_errors) >= drift_window * 2:
            prior = sum(champion_errors[-drift_window * 2 : -drift_window]) / drift_window
            recent = sum(champion_errors[-drift_window:]) / drift_window
            if prior == 0:
                drift_ratio = 1.0 if recent == 0 else None
                drift_status = ModelDriftStatus.STABLE if recent == 0 else ModelDriftStatus.DEGRADED
            else:
                drift_ratio = recent / prior
                drift_status = (
                    ModelDriftStatus.DEGRADED
                    if drift_ratio > drift_degradation_ratio
                    else ModelDriftStatus.STABLE
                )
        return PaperSummary(
            observations=len(outcomes),
            proposal_return=proposal_return,
            benchmark_return=benchmark_return,
            excess_return=proposal_return - benchmark_return,
            maximum_drawdown=maximum_drawdown,
            mean_cost_error=(sum(cost_errors, Decimal("0")) / len(cost_errors))
            if cost_errors
            else None,
            mean_tax_error=(sum(tax_errors, Decimal("0")) / len(tax_errors))
            if tax_errors
            else None,
            champion_mean_absolute_error=sum(champion_errors) / len(champion_errors),
            challenger_mean_absolute_error=(
                sum(pair[1] for pair in challenger_pairs) / len(challenger_pairs)
                if challenger_pairs
                else None
            ),
            challenger_better_rate=(
                sum(challenger < champion for champion, challenger in challenger_pairs)
                / len(challenger_pairs)
                if challenger_pairs
                else None
            ),
            champion_version=champion_version,
            champion_observations=len(champion_cohort),
            challenger_version=challenger_version,
            challenger_observations=len(challenger_pairs),
            drift_status=drift_status,
            drift_ratio=drift_ratio,
            drift_window=drift_window,
            minimum_observation_count=minimum_observations,
            is_decision_ready=len(champion_cohort) >= minimum_observations,
            model_monitoring_ready=(
                len(champion_cohort) >= minimum_observations
                and challenger_version is not None
                and len(challenger_pairs) >= minimum_observations
            ),
            updated_at=outcomes[-1].observed_at,
        )

    def paper_readouts(
        self,
        period: PaperReadoutPeriod,
        *,
        limit: int = 12,
    ) -> tuple[PaperReadout, ...]:
        if limit <= 0:
            raise ValueError("paper readout limit must be positive")
        grouped: dict[str, list[PaperOutcome]] = {}
        bounds: dict[str, tuple[date, date]] = {}
        for outcome in self.paper_outcomes(horizon_sessions=1):
            observed_date = outcome.label_end_at.astimezone(JST).date()
            if period is PaperReadoutPeriod.WEEKLY:
                iso_year, iso_week, _ = observed_date.isocalendar()
                period_key = f"{iso_year}-W{iso_week:02d}"
                period_start = observed_date - timedelta(days=observed_date.weekday())
                period_end = period_start + timedelta(days=6)
            else:
                period_key = observed_date.strftime("%Y-%m")
                period_start = observed_date.replace(day=1)
                next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
                period_end = next_month - timedelta(days=1)
            grouped.setdefault(period_key, []).append(outcome)
            bounds[period_key] = (period_start, period_end)

        readouts: list[PaperReadout] = []
        for period_key in sorted(grouped, reverse=True)[:limit]:
            outcomes = grouped[period_key]
            proposal_value = math.prod(1.0 + item.proposal_return for item in outcomes)
            benchmark_value = math.prod(1.0 + item.benchmark_return for item in outcomes)
            cost_errors = [
                item.actual_cost - item.estimated_cost
                for item in outcomes
                if item.actual_cost is not None
            ]
            tax_errors = [
                item.audited_tax_effect - item.estimated_tax_effect
                for item in outcomes
                if item.audited_tax_effect is not None
            ]
            challenger_pairs = [
                (item.champion_absolute_error, item.challenger_absolute_error)
                for item in outcomes
                if item.challenger_absolute_error is not None
            ]
            period_start, period_end = bounds[period_key]
            readouts.append(
                PaperReadout(
                    period=period,
                    period_key=period_key,
                    period_start=period_start,
                    period_end=period_end,
                    observations=len(outcomes),
                    proposal_return=proposal_value - 1.0,
                    benchmark_return=benchmark_value - 1.0,
                    excess_return=proposal_value - benchmark_value,
                    mean_cost_error=(
                        sum(cost_errors, Decimal("0")) / len(cost_errors) if cost_errors else None
                    ),
                    mean_tax_error=(
                        sum(tax_errors, Decimal("0")) / len(tax_errors) if tax_errors else None
                    ),
                    champion_mean_absolute_error=(
                        sum(item.champion_absolute_error for item in outcomes) / len(outcomes)
                    ),
                    challenger_mean_absolute_error=(
                        sum(float(pair[1]) for pair in challenger_pairs) / len(challenger_pairs)
                        if challenger_pairs
                        else None
                    ),
                    challenger_better_rate=(
                        sum(float(pair[1]) < pair[0] for pair in challenger_pairs)
                        / len(challenger_pairs)
                        if challenger_pairs
                        else None
                    ),
                    champion_versions=tuple(
                        dict.fromkeys(item.champion_version for item in outcomes)
                    ),
                    challenger_versions=tuple(
                        dict.fromkeys(
                            item.challenger_version
                            for item in outcomes
                            if item.challenger_version is not None
                        )
                    ),
                    updated_at=outcomes[-1].observed_at,
                )
            )
        return tuple(readouts)

    def paper_series(self) -> tuple[PaperSeriesPoint, ...]:
        proposal_value = 1.0
        benchmark_value = 1.0
        points: list[PaperSeriesPoint] = []
        for observations, outcome in enumerate(self.paper_outcomes(horizon_sessions=1), start=1):
            proposal_value *= 1.0 + outcome.proposal_return
            benchmark_value *= 1.0 + outcome.benchmark_return
            points.append(
                PaperSeriesPoint(
                    observed_at=outcome.label_end_at,
                    observations=observations,
                    proposal_return=proposal_value - 1.0,
                    benchmark_return=benchmark_value - 1.0,
                    excess_return=proposal_value - benchmark_value,
                )
            )
        return tuple(points)

    def preview_execution_csv(
        self,
        csv_text: str,
        *,
        preview_id: str,
        created_at: datetime,
    ) -> ExecutionImportPreview:
        source_hash = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        required = {
            "execution_id",
            "decision_id",
            "executed_at",
            "symbol",
            "account_bucket_id",
            "status",
            "side",
            "ordered_shares",
            "filled_shares",
        }
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or ()))
            raise ValueError(f"execution CSV missing required columns: {missing}")
        payloads: list[str] = []
        conflicts: list[ImportConflict] = []
        seen: set[str] = set()
        preview_filled: dict[tuple[str, str, str, TradeSide], int] = {}
        for row_number, row in enumerate(reader, start=2):
            try:
                execution = ExecutionRecord(
                    execution_id=row["execution_id"],
                    decision_id=row["decision_id"],
                    executed_at=datetime.fromisoformat(row["executed_at"]),
                    symbol=row["symbol"],
                    account_bucket_id=row["account_bucket_id"],
                    status=ExecutionStatus(str(row["status"])),
                    side=TradeSide(str(row["side"])),
                    ordered_shares=int(row["ordered_shares"]),
                    filled_shares=int(row["filled_shares"]),
                    average_fill_price=(
                        Decimal(str(row["average_fill_price"]))
                        if row.get("average_fill_price")
                        else None
                    ),
                    actual_commission=Decimal(str(row.get("actual_commission") or "0")),
                    actual_other_cost=Decimal(str(row.get("actual_other_cost") or "0")),
                    tax_withheld=Decimal(str(row.get("tax_withheld") or "0")),
                    source="csv_import",
                )
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                conflicts.append(
                    ImportConflict(
                        conflict_id=f"row-{row_number}-invalid",
                        row_number=row_number,
                        code="INVALID_ROW",
                        message=str(exc),
                        record_identity=str(row.get("execution_id") or f"row-{row_number}"),
                    )
                )
                continue
            payload = _canonical_payload(execution)
            if execution.execution_id in seen:
                conflicts.append(
                    ImportConflict(
                        conflict_id=f"row-{row_number}-duplicate",
                        row_number=row_number,
                        code="DUPLICATE_IN_FILE",
                        message="同じexecution_idがCSV内に複数あります",
                        record_identity=execution.execution_id,
                    )
                )
                continue
            seen.add(execution.execution_id)
            try:
                existing = self._load_payload("executions", "execution_id", execution.execution_id)
            except KeyError:
                existing = None
            if existing is not None:
                code = "ALREADY_IMPORTED" if existing == payload else "IDENTITY_CONFLICT"
                conflicts.append(
                    ImportConflict(
                        conflict_id=f"row-{row_number}-{code.lower()}",
                        row_number=row_number,
                        code=code,
                        message="既存の実約定レコードと照合が必要です",
                        record_identity=execution.execution_id,
                    )
                )
            try:
                self.decision(execution.decision_id)
            except KeyError:
                conflicts.append(
                    ImportConflict(
                        conflict_id=f"row-{row_number}-unknown-decision",
                        row_number=row_number,
                        code="UNKNOWN_DECISION",
                        message="対応する保存済みユーザー判断がありません",
                        record_identity=execution.execution_id,
                    )
                )
                continue
            fill_key = (
                execution.decision_id,
                execution.symbol,
                execution.account_bucket_id,
                execution.side,
            )
            try:
                decision_mismatch = self._execution_differs_from_decision(
                    execution,
                    additional_filled_shares=preview_filled.get(fill_key, 0),
                )
            except OperationalTimelineError:
                conflicts.append(
                    ImportConflict(
                        conflict_id=f"row-{row_number}-invalid-timeline",
                        row_number=row_number,
                        code="INVALID_TIMELINE",
                        message="約定日時は保存済み判断より後である必要があります",
                        record_identity=execution.execution_id,
                    )
                )
                continue
            except OperationalConflictError:
                decision_mismatch = True
            if decision_mismatch:
                conflicts.append(
                    ImportConflict(
                        conflict_id=f"row-{row_number}-decision-mismatch",
                        row_number=row_number,
                        code="DECISION_MISMATCH",
                        message="保存済みユーザー判断との差異を明示確認してください",
                        record_identity=execution.execution_id,
                    )
                )
            preview_filled[fill_key] = preview_filled.get(fill_key, 0) + execution.filled_shares
            payloads.append(payload)
        preview = ExecutionImportPreview(
            preview_id=preview_id,
            source_hash=source_hash,
            created_at=created_at,
            execution_payloads=tuple(payloads),
            conflicts=tuple(conflicts),
        )
        self._save_import_preview(preview)
        return preview

    def confirm_execution_import(
        self,
        preview_id: str,
        *,
        accepted_conflict_ids: Iterable[str] = (),
    ) -> tuple[int, int]:
        accepted = tuple(sorted(set(accepted_conflict_ids)))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _verify_database_connection(connection)
            row = connection.execute(
                "SELECT * FROM import_previews WHERE preview_id = ?", (preview_id,)
            ).fetchone()
            if row is None:
                raise KeyError(preview_id)
            preview = _parse_model(ExecutionImportPreview, _checked_payload(row, "import_previews"))
            if preview.status is ImportStatus.CONFIRMED:
                if preview.confirmed_counts is None or preview.accepted_conflict_ids != accepted:
                    raise OperationalConflictError(
                        "import already confirmed with different or legacy receipt"
                    )
                return preview.confirmed_counts
            if preview.status is not ImportStatus.PREVIEW:
                raise OperationalConflictError("import preview is not pending")
            conflict_ids = {item.conflict_id for item in preview.conflicts}
            if not set(accepted).issubset(conflict_ids):
                raise ValueError("accepted conflict ID does not belong to the preview")
            if conflict_ids - set(accepted):
                raise OperationalConflictError("import conflicts require explicit review")
            imported = 0
            skipped = len(
                {
                    item.row_number
                    for item in preview.conflicts
                    if item.code
                    in {
                        "INVALID_ROW",
                        "DUPLICATE_IN_FILE",
                        "UNKNOWN_DECISION",
                        "INVALID_TIMELINE",
                    }
                }
            )
            for payload in preview.execution_payloads:
                execution = _parse_model(ExecutionRecord, payload)
                conflicts = {
                    item.code
                    for item in preview.conflicts
                    if item.record_identity == execution.execution_id
                }
                existing = connection.execute(
                    "SELECT * FROM executions WHERE execution_id = ?", (execution.execution_id,)
                ).fetchone()
                if existing is not None:
                    _verify_hashed_row("executions", existing)
                    if (
                        _checked_payload(existing, "executions") == payload
                        or "IDENTITY_CONFLICT" in conflicts
                    ):
                        skipped += 1
                        continue
                    raise OperationalConflictError("execution changed after preview; review again")
                if (
                    self._execution_differs_from_decision(execution, connection=connection)
                    and "DECISION_MISMATCH" not in conflicts
                ):
                    raise OperationalConflictError(
                        "execution differs after preview; explicit review required"
                    )
                self._insert_immutable(
                    connection,
                    table="executions",
                    identity_column="execution_id",
                    identity=execution.execution_id,
                    columns={
                        "decision_id": execution.decision_id,
                        "executed_at": execution.executed_at.isoformat(),
                    },
                    payload=payload,
                )
                imported += 1
            confirmed = preview.model_copy(
                update={
                    "status": ImportStatus.CONFIRMED,
                    "confirmed_counts": (imported, skipped),
                    "accepted_conflict_ids": accepted,
                }
            )
            payload = _canonical_payload(confirmed)
            cursor = connection.execute(
                "UPDATE import_previews SET status=?, payload=?, content_hash=? "
                "WHERE preview_id=? AND status=? AND content_hash=?",
                (
                    ImportStatus.CONFIRMED.value,
                    payload,
                    _payload_hash(payload),
                    preview_id,
                    ImportStatus.PREVIEW.value,
                    row["content_hash"],
                ),
            )
            if cursor.rowcount != 1:
                raise OperationalConflictError("import preview changed")
            connection.commit()
            return imported, skipped

    def import_preview(self, preview_id: str) -> ExecutionImportPreview:
        return self._load_one("import_previews", "preview_id", preview_id, ExecutionImportPreview)

    def preview_position_reconciliation_csv(
        self,
        csv_text: str,
        *,
        preview_id: str,
        created_at: datetime,
    ) -> PositionReconciliationPreview:
        required = {
            "as_of",
            "record_type",
            "symbol",
            "account_bucket_id",
            "shares",
            "average_acquisition_price",
            "market_price",
            "available_cash",
            "reserved_cash",
        }
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or ()))
            raise ValueError(f"position CSV missing required columns: {missing}")
        rows = list(reader)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = _latest_portfolio_connection(connection)
            if current is None:
                raise OperationalIntegrityError(
                    "position reconciliation requires a current portfolio"
                )
            return self._preview_positions_locked(
                connection,
                rows,
                csv_text,
                preview_id,
                created_at,
                current,
            )

    def _preview_positions_locked(
        self,
        connection: sqlite3.Connection,
        rows: list[dict[str, str]],
        csv_text: str,
        preview_id: str,
        created_at: datetime,
        current: PortfolioState,
    ) -> PositionReconciliationPreview:
        positions: list[Position] = []
        imported_times: set[datetime] = set()
        keys: set[tuple[str, str]] = set()
        bucket_ids = {item.bucket_id for item in current.account_buckets}
        current_cash = current.cash_map()
        imported_cash: dict[str, CashState] = {}
        for row_number, row in enumerate(rows, start=2):
            imported_as_of = datetime.fromisoformat(str(row["as_of"]))
            if imported_as_of.tzinfo is None or imported_as_of.utcoffset() is None:
                raise ValueError(f"position row {row_number} as_of must be timezone-aware")
            imported_times.add(imported_as_of)
            account_bucket_id = str(row["account_bucket_id"])
            if account_bucket_id not in bucket_ids:
                raise ValueError(f"position row {row_number} references an unknown account bucket")
            record_type = str(row["record_type"]).strip().upper()
            if record_type == "CASH":
                if account_bucket_id in imported_cash:
                    raise ValueError(f"cash row {row_number} duplicates an account bucket")
                imported_cash[account_bucket_id] = CashState(
                    account_bucket_id=account_bucket_id,
                    available_cash=Decimal(str(row["available_cash"])),
                    reserved_cash=Decimal(str(row["reserved_cash"])),
                )
                continue
            if record_type != "POSITION":
                raise ValueError(f"position row {row_number} has an unknown record_type")
            position = Position(
                symbol=str(row["symbol"]),
                account_bucket_id=account_bucket_id,
                shares=int(str(row["shares"])),
                average_acquisition_price=Decimal(str(row["average_acquisition_price"])),
                market_price=Decimal(str(row["market_price"])),
            )
            if position.key in keys:
                raise ValueError(f"position row {row_number} duplicates a symbol/account bucket")
            keys.add(position.key)
            if position.shares > 0:
                positions.append(position)
        if len(imported_times) != 1:
            raise ValueError("position reconciliation requires one common as_of")
        missing_cash = sorted(bucket_ids - set(imported_cash))
        if missing_cash:
            raise ValueError(
                f"account reconciliation requires one CASH row per bucket; missing {missing_cash}"
            )
        imported_as_of = imported_times.pop()
        if imported_as_of <= current.as_of:
            raise ValueError("position reconciliation as_of must be later than current state")
        if imported_as_of > _now_utc():
            raise ReconciliationConflictError("RECONCILIATION_IN_FUTURE")
        base_reference, relevant_ids = _reconciliation_base(connection, current, imported_as_of)
        if relevant_ids - set(current.applied_execution_ids):
            raise ReconciliationConflictError("RECONCILIATION_UNAPPLIED_EXECUTIONS")
        applied_ids = set(current.applied_execution_ids)
        tax_year = imported_as_of.astimezone(JST).year
        tax_states = tuple(
            state
            if state.tax_year == tax_year
            else TaxState(
                account_bucket_id=state.account_bucket_id,
                tax_year=tax_year,
                loss_carryforward_user_input=state.loss_carryforward_user_input,
                nisa_annual_capacity_user_input=state.nisa_annual_capacity_user_input,
                nisa_lifetime_capacity_user_input=state.nisa_lifetime_capacity_user_input,
            )
            for state in current.tax_states
        )
        proposed = PortfolioState(
            portfolio_id=f"reconciliation-preview-{preview_id}",
            as_of=imported_as_of,
            accounts=current.accounts,
            account_buckets=current.account_buckets,
            positions=tuple(sorted(positions, key=lambda item: item.key)),
            cash=tuple(imported_cash[key] for key in sorted(imported_cash)),
            tax_states=tax_states,
            applied_execution_ids=tuple(sorted(applied_ids)),
        )
        current_map = current.position_map()
        imported_map = proposed.position_map()
        differences: list[PositionDifference] = []
        for key in sorted(set(current_map) | set(imported_map)):
            ledger = current_map.get(key)
            imported = imported_map.get(key)
            if ledger == imported:
                continue
            differences.append(
                PositionDifference(
                    symbol=key[0],
                    account_bucket_id=key[1],
                    ledger_shares=0 if ledger is None else ledger.shares,
                    imported_shares=0 if imported is None else imported.shares,
                    ledger_average_price=None
                    if ledger is None
                    else ledger.average_acquisition_price,
                    imported_average_price=None
                    if imported is None
                    else imported.average_acquisition_price,
                    ledger_market_price=None if ledger is None else ledger.market_price,
                    imported_market_price=None if imported is None else imported.market_price,
                )
            )
        imported_cash_map = proposed.cash_map()
        cash_differences = tuple(
            CashDifference(
                account_bucket_id=bucket_id,
                ledger_available_cash=current_cash[bucket_id].available_cash,
                imported_available_cash=imported_cash_map[bucket_id].available_cash,
                ledger_reserved_cash=current_cash[bucket_id].reserved_cash,
                imported_reserved_cash=imported_cash_map[bucket_id].reserved_cash,
            )
            for bucket_id in sorted(bucket_ids)
            if current_cash[bucket_id].available_cash != imported_cash_map[bucket_id].available_cash
            or current_cash[bucket_id].reserved_cash != imported_cash_map[bucket_id].reserved_cash
        )
        preview = PositionReconciliationPreview(
            preview_id=preview_id,
            base_reference=base_reference,
            source_hash=hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
            created_at=created_at,
            imported_as_of=imported_as_of,
            portfolio_payload=_canonical_payload(proposed),
            differences=tuple(differences),
            cash_differences=cash_differences,
        )
        self._insert_immutable(
            connection,
            table="position_reconciliations",
            identity_column="preview_id",
            identity=preview.preview_id,
            columns={
                "source_hash": preview.source_hash,
                "status": preview.status.value,
                "created_at": preview.created_at.isoformat(),
            },
            payload=_canonical_payload(preview),
        )
        connection.commit()
        return preview

    def position_reconciliation(self, preview_id: str) -> PositionReconciliationPreview:
        return self._load_one(
            "position_reconciliations",
            "preview_id",
            preview_id,
            PositionReconciliationPreview,
        )

    def confirm_position_reconciliation(
        self,
        preview_id: str,
        *,
        next_portfolio_id: str,
        confirm_all_differences: bool,
        created_at: datetime,
    ) -> PortfolioState:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        next_portfolio_id = next_portfolio_id.strip()
        if not next_portfolio_id:
            raise ValueError("next_portfolio_id must not be blank")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _verify_database_connection(connection)
            row = connection.execute(
                "SELECT * FROM position_reconciliations WHERE preview_id = ?",
                (preview_id,),
            ).fetchone()
            if row is None:
                raise KeyError(preview_id)
            preview = _parse_model(
                PositionReconciliationPreview, _checked_payload(row, "position_reconciliations")
            )
            if preview.status is ImportStatus.CONFIRMED:
                if preview.confirmed_portfolio_id != next_portfolio_id:
                    raise ReconciliationConflictError("RECONCILIATION_ALREADY_CONFIRMED")
                return _confirmed_reconciliation_result(connection, preview)
            if preview.status is not ImportStatus.PREVIEW or preview.base_reference is None:
                raise ReconciliationConflictError("RECONCILIATION_REPREVIEW_REQUIRED")
            current = _latest_portfolio_connection(connection)
            if current is None:
                raise ReconciliationConflictError("RECONCILIATION_BASE_CHANGED")
            base, relevant_ids = _reconciliation_base(connection, current, preview.imported_as_of)
            if (base.portfolio_id, base.portfolio_sha256) != (
                preview.base_reference.portfolio_id,
                preview.base_reference.portfolio_sha256,
            ):
                raise ReconciliationConflictError("RECONCILIATION_BASE_CHANGED")
            if base.relevant_executions_sha256 != preview.base_reference.relevant_executions_sha256:
                raise ReconciliationConflictError("RECONCILIATION_EXECUTIONS_CHANGED")
            if not current.as_of < preview.imported_as_of <= _now_utc():
                raise ReconciliationConflictError("RECONCILIATION_REPREVIEW_REQUIRED")
            if relevant_ids - set(current.applied_execution_ids):
                raise ReconciliationConflictError("RECONCILIATION_UNAPPLIED_EXECUTIONS")
            if (preview.differences or preview.cash_differences) and not confirm_all_differences:
                raise OperationalConflictError(
                    "all position differences require manual confirmation"
                )
            proposed = _parse_model(PortfolioState, preview.portfolio_payload).model_copy(
                update={"portfolio_id": next_portfolio_id},
            )
            confirmed = preview.model_copy(
                update={
                    "status": ImportStatus.CONFIRMED,
                    "confirmed_portfolio_id": next_portfolio_id,
                }
            )
            payload = _canonical_payload(confirmed)
            cursor = connection.execute(
                "UPDATE position_reconciliations SET status = ?, payload = ?, content_hash = ? "
                "WHERE preview_id = ? AND status = ? AND content_hash = ?",
                (
                    ImportStatus.CONFIRMED.value,
                    payload,
                    _payload_hash(payload),
                    preview_id,
                    ImportStatus.PREVIEW.value,
                    row["content_hash"],
                ),
            )
            if cursor.rowcount != 1:
                raise ReconciliationConflictError("RECONCILIATION_ALREADY_CONFIRMED")
            self._insert_immutable(
                connection,
                table="portfolio_states",
                identity_column="portfolio_id",
                identity=proposed.portfolio_id,
                columns={"as_of": proposed.as_of.isoformat(), "created_at": created_at.isoformat()},
                payload=_canonical_payload(proposed),
            )
            connection.commit()
        return proposed

    def _save_position_reconciliation(self, preview: PositionReconciliationPreview) -> None:
        payload = _canonical_payload(preview)
        with self._connect() as connection:
            self._insert_immutable(
                connection,
                table="position_reconciliations",
                identity_column="preview_id",
                identity=preview.preview_id,
                columns={
                    "source_hash": preview.source_hash,
                    "status": preview.status.value,
                    "created_at": preview.created_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()

    def _save_import_preview(self, preview: ExecutionImportPreview) -> None:
        payload = _canonical_payload(preview)
        with self._connect() as connection:
            self._insert_immutable(
                connection,
                table="import_previews",
                identity_column="preview_id",
                identity=preview.preview_id,
                columns={
                    "source_hash": preview.source_hash,
                    "status": preview.status.value,
                    "created_at": preview.created_at.isoformat(),
                },
                payload=payload,
            )
            connection.commit()

    def _replace_import_preview(self, preview: ExecutionImportPreview) -> None:
        payload = _canonical_payload(preview)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE import_previews SET status = ?, payload = ?, content_hash = ?
                WHERE preview_id = ? AND status = ?
                """,
                (
                    preview.status.value,
                    payload,
                    _payload_hash(payload),
                    preview.preview_id,
                    ImportStatus.PREVIEW.value,
                ),
            )
            if connection.total_changes != 1:
                raise OperationalConflictError("import preview is not pending")
            connection.commit()

    def backup(self, destination: Path) -> Path:
        destination = destination.resolve()
        if destination == self.path:
            raise OperationalConflictError("backup destination must differ from the live ledger")
        if destination.exists():
            raise OperationalConflictError("backup destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        os.close(descriptor)
        temp_path = Path(temp_name)
        try:
            target = sqlite3.connect(temp_path)
            try:
                with self._connect() as source:
                    source.backup(target)
                    target.commit()
            finally:
                target.close()
            _verify_database_path(temp_path)
            try:
                os.link(temp_path, destination)
            except FileExistsError as exc:
                raise OperationalConflictError("backup destination already exists") from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return destination

    @classmethod
    def restore_backup(
        cls,
        backup_path: Path,
        destination: Path,
        *,
        confirm_replace: bool,
    ) -> Path:
        """Restore a verified backup to an explicitly confirmed local ledger path."""

        if not confirm_replace:
            raise OperationalConflictError("restore requires explicit replacement confirmation")
        source_path = backup_path.resolve()
        target_path = destination.resolve()
        if source_path == target_path:
            raise OperationalConflictError("backup and restore destination must differ")
        _verify_database_path(source_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{target_path.name}.", suffix=".restore.tmp", dir=target_path.parent
        )
        os.close(descriptor)
        temp_path = Path(temp_name)
        try:
            source = sqlite3.connect(
                f"file:{source_path.as_posix()}?mode=ro", uri=True, timeout=30.0
            )
            target = sqlite3.connect(temp_path, timeout=30.0)
            try:
                source.backup(target)
                target.commit()
            finally:
                target.close()
                source.close()
            _verify_database_path(temp_path)
            if target_path.exists():
                with sqlite3.connect(target_path, timeout=5.0) as current:
                    current.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            os.replace(temp_path, target_path)
            Path(f"{target_path}-wal").unlink(missing_ok=True)
            Path(f"{target_path}-shm").unlink(missing_ok=True)
            _verify_database_path(target_path)
        except (OSError, sqlite3.DatabaseError) as exc:
            raise OperationalIntegrityError("verified backup restore failed") from exc
        finally:
            temp_path.unlink(missing_ok=True)
        return target_path

    def verify_integrity(self) -> dict[str, int]:
        with self._connect() as connection:
            return _verify_database_connection(connection)

    def _load_payload(self, table: str, key: str, identity: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload, content_hash FROM {table} WHERE {key} = ?", (identity,)
            ).fetchone()
        if row is None:
            raise KeyError(identity)
        payload = str(row["payload"])
        if _payload_hash(payload) != row["content_hash"]:
            raise OperationalIntegrityError(f"content hash mismatch in {table}")
        return payload

    def _load_one[ModelT: BaseModel](
        self,
        table: str,
        key: str,
        identity: str,
        model: type[ModelT],
    ) -> ModelT:
        return _parse_model(model, self._load_payload(table, key, identity))


def finite_float(value: object) -> float:
    """Parse an imported metric without accepting NaN or infinities."""
    parsed = float(str(value))
    if not math.isfinite(parsed):
        raise ValueError("value must be finite")
    return parsed
