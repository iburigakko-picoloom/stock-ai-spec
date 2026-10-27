"""Recoverable personal share proposals from one immutable numerical forecast."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from stock_ai.domain import ExecutionRecord, ExecutionStatus, PortfolioState
from stock_ai.domain.models import PersonalInputReferences, PersonalPublicationGuard
from stock_ai.operations.daily import PredictionSnapshot, canonical_json, content_id
from stock_ai.operations.manual_portfolio import ImportedManualPortfolio
from stock_ai.operations.models import DailyOperationStatus, DecisionPolicySnapshot, PipelineState
from stock_ai.operations.personal import (
    PersonalComparison,
    PersonalComparisonRequest,
    _reconcile,
    compare_stored_personal,
    implementation_hashes,
)
from stock_ai.operations.store import OperationalConflictError

from . import decision_market, forecasts, models, personal
from .market import receipt_time
from .model_bundle import ResearchModelBundle
from .research_ensemble import ResearchEnsembleBundle
from .storage import connect


def initialize(path: Path) -> None:
    with connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS mobile_decision_runs("
                   "sequence INTEGER PRIMARY KEY,run_id TEXT NOT NULL UNIQUE,"
                   "scope_hash TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,"
                   "content_hash TEXT NOT NULL,phase TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS mobile_decision_selections("
                   "sequence INTEGER PRIMARY KEY,run_id TEXT NOT NULL,selected_at TEXT NOT NULL)")


def _select(path, identity, now):
    with connect(path) as db:
        previous = db.execute("SELECT run_id FROM mobile_decision_selections "
                              "ORDER BY sequence DESC LIMIT 1").fetchone()
        if previous is None or previous[0] != identity:
            db.execute("INSERT INTO mobile_decision_selections VALUES(NULL,?,?)",
                       (identity, now.isoformat()))


def _checked(row) -> dict:
    identity, scope_hash, payload, digest, phase = row
    value = json.loads(payload)
    if (content_id(value) != digest or value["run_id"] != identity
            or content_id({k: v for k, v in value.items() if k != "run_id"}) != identity
            or value["scope_hash"] != scope_hash or content_id(value["scope"]) != scope_hash
            or phase not in ("computed", "published", "blocked")):
        raise ValueError("Decision computation receipt changed")
    outcome = value["outcome"]
    if (value["schema_version"] != "mobile-decision-run-v1"
            or outcome not in ("proposal", "cash_only", "blocked")
            or (phase == "blocked") != (outcome == "blocked")
            or value["research_only"] is not True or value["order_submission"] is not False):
        raise ValueError("Invalid decision receipt state")
    cutoff = datetime.fromisoformat(value["scope"]["as_of"])
    checked = datetime.fromisoformat(value["checked_at"])
    status = DailyOperationStatus.model_validate(value["publication_status"])
    if (cutoff.tzinfo is None or checked.tzinfo is None or status.updated_at != checked
            or status.business_date != cutoff.date()
            or status.is_stale != (outcome == "blocked")
            or bool(value["blocking_reasons"]) != (outcome == "blocked")
            or status.blocking_reason != next(iter(value["blocking_reasons"]), None)):
        raise ValueError("Decision publication status changed")
    comparison = value["comparison"]
    frozen = value["frozen_inputs"]
    if outcome != "blocked" and frozen is None:
        raise ValueError("Published decision requires frozen personal inputs")
    if outcome == "proposal" and comparison is None:
        raise ValueError("Share proposal requires comparison")
    if outcome != "proposal" and (status.proposal_id is not None
                                  or value["decision_policy"] is not None):
        raise ValueError("Non-proposal receipt contains a proposal reference")
    if outcome == "cash_only" and (comparison is not None or value["market"] is not None
                                   or status.pipeline_state is not PipelineState.CASH_ONLY):
        raise ValueError("Cash-only receipt contains security calculations")
    if frozen is not None:
        manual = ImportedManualPortfolio.model_validate(frozen["manual"])
        ledger = PortfolioState.model_validate(frozen["ledger"])
        for execution in frozen["executions"]:
            ExecutionRecord.model_validate(execution)
        refs = PersonalInputReferences.model_validate(value["scope"]["personal_refs"])
        if (refs.manual_revision_id != manual.export.revision_id
                or refs.ledger_portfolio_id != ledger.portfolio_id
                or refs.executions_sha256 != content_id(frozen["executions"])):
            raise ValueError("Decision personal references differ from frozen inputs")
        if comparison is not None:
            parsed = PersonalComparison.model_validate(comparison)
            snapshot = PredictionSnapshot.model_validate(frozen["forecast"])
            expected = content_id({"request": parsed.request.model_dump(mode="json"), **frozen})
            if (parsed.inputs_sha256 != expected
                    or parsed.manual_revision_id != refs.manual_revision_id
                    or parsed.ledger_portfolio_id != ledger.portfolio_id
                    or parsed.forecast_snapshot_id != snapshot.snapshot_id
                    or parsed.request.market is None
                    or parsed.request.market.model_dump(mode="json")
                    != value["market"]["evidence"]):
                raise ValueError("Decision comparison differs from frozen evidence")
            if parsed.proposal is not None:
                proposal = parsed.proposal
                policy = DecisionPolicySnapshot.model_validate(value["decision_policy"])
                if (outcome != "proposal"
                        or status.pipeline_state is not PipelineState.PROPOSAL_READY
                        or status.proposal_id != proposal.proposal_id
                        or proposal.generated_at != checked or proposal.as_of != cutoff
                        or policy.proposal_id != proposal.proposal_id
                        or policy.captured_at != proposal.generated_at
                        or policy.config != parsed.request.settings.decision_policy):
                    raise ValueError("Decision policy or publication identity changed")
                audit = parsed.proposal.daily_audit
                guard = parsed.proposal.personal_guard
                if (audit is None or guard is None
                        or audit.forecast_content_sha256 != content_id(frozen["forecast"])
                        or audit.market_content_sha256 != content_id(value["market"]["evidence"])
                        or guard.forecast_snapshot_id != snapshot.snapshot_id
                        or guard.model_dump(exclude={"forecast_snapshot_id"})
                        != refs.model_dump()):
                    raise ValueError("Decision proposal lineage changed")
            elif outcome == "proposal":
                raise ValueError("Decision comparison has no proposal")
        elif value["outcome"] == "cash_only" and (
            frozen["forecast"] is not None or any(x.shares > 0 for x in ledger.positions)
        ):
            raise ValueError("Cash-only receipt cannot contain held securities or fake forecasts")
    return {**value, "phase": phase}


def _proposal(value):
    return None if value["comparison"] is None else PersonalComparison.model_validate(
        value["comparison"]
    ).proposal


def _cash_marker(value):
    return canonical_json({"receipt_id": value["run_id"], "guard": value["scope"]["personal_refs"],
                           "status": value["publication_status"],
                           "numerical_run_id": value["scope"]["numerical_run_id"]})


def _published_in_store(store, value):
    if value["outcome"] == "cash_only":
        marker = store.metadata("mobile-cash-receipt:" + value["run_id"])
        if marker is None:
            return False
        if marker != _cash_marker(value):
            raise ValueError("Cash-only publication differs from computation")
        return True
    proposal = _proposal(value)
    if proposal is None:
        return False
    try:
        existing = store.proposal(proposal.proposal_id)
    except KeyError:
        return False
    policy = DecisionPolicySnapshot.model_validate(value["decision_policy"])
    if existing != proposal or store.decision_policy_snapshot(proposal.proposal_id) != policy:
        raise ValueError("Published proposal differs from computation")
    if store.daily_status(proposal.as_of.date()) is None:
        raise ValueError("Published proposal has no atomic daily status")
    return True


def _publish(path, store, value, now=None):
    if value["outcome"] == "blocked":
        return value
    _linked_inputs(store, value)
    if not _published_in_store(store, value):
        status = DailyOperationStatus.model_validate(value["publication_status"])
        if value["outcome"] == "cash_only":
            store.publish_cash_only(value["run_id"], PersonalInputReferences.model_validate(
                value["scope"]["personal_refs"]), status,
                numerical_run_id=value["scope"]["numerical_run_id"])
        else:
            proposal = _proposal(value)
            store.archive_proposal(
                proposal, archived_at=status.updated_at,
                decision_policy=DecisionPolicySnapshot.model_validate(value["decision_policy"]),
                publication_status=status,
            )
    elif now is not None:
        status = DailyOperationStatus.model_validate(value["publication_status"]).model_copy(
            update={"updated_at": now}
        )
        if value["outcome"] == "cash_only":
            store.recheck_cash_publication(value["run_id"], status)
        else:
            store.recheck_personal_publication(_proposal(value), status)
    with connect(path) as db:
        db.execute("UPDATE mobile_decision_runs SET phase='published' WHERE run_id=?",
                   (value["run_id"],))
    return {**value, "phase": "published"}


def reconcile(path: Path, store, *, integrity_guard=None) -> None:
    if integrity_guard is not None:
        # A preexisting proof covers every execution. Refresh it only before
        # taking the reusable snapshot, never during reconciliation.
        integrity_guard.verify()
        if not integrity_guard.proof_is_current():
            raise OperationalConflictError("判断記録の確認中にデータが更新されました。")
    actual = None
    with connect(path) as db:
        rows = db.execute("SELECT run_id,scope_hash,payload,content_hash,phase "
                          "FROM mobile_decision_runs ORDER BY sequence").fetchall()
        for row in rows:
            value = _checked(row)
            if integrity_guard is not None and value["frozen_inputs"] is not None:
                if not integrity_guard.proof_is_current():
                    raise OperationalConflictError("判断記録の確認中にデータが更新されました。")
                if actual is None:
                    actual = {x.execution_id: x for x in store.executions()}
                if not integrity_guard.proof_is_current():
                    raise OperationalConflictError("判断記録の確認中にデータが更新されました。")
            _linked_inputs(store, value, actual=actual)
            if value["phase"] == "published" and not _published_in_store(store, value):
                raise ValueError("Published decision archive missing")
            if value["phase"] == "computed" and _published_in_store(store, value):
                db.execute("UPDATE mobile_decision_runs SET phase='published' WHERE run_id=?",
                           (value["run_id"],))
        if integrity_guard is not None and not integrity_guard.proof_is_current():
            raise OperationalConflictError("判断記録の確認中にデータが更新されました。")


def _linked_inputs(store, value, *, actual=None):
    frozen = value["frozen_inputs"]
    if frozen is None:
        return
    refs = value["scope"]["personal_refs"]
    if (store.portfolio(refs["ledger_portfolio_id"])
            != PortfolioState.model_validate(frozen["ledger"])):
        raise ValueError("Frozen ledger differs from original")
    with connect(store.path) as db:
        row = db.execute("SELECT content_hash FROM manual_portfolio_imports WHERE revision_id=?",
                         (refs["manual_revision_id"],)).fetchone()
    if row is None or row[0] != content_id(frozen["manual"]):
        raise ValueError("Frozen manual input differs from original")
    if frozen["forecast"] is not None:
        snapshot = PredictionSnapshot.model_validate(frozen["forecast"])
        if store.prediction_snapshot(snapshot.snapshot_id) != snapshot:
            raise ValueError("Frozen forecast differs from original")
    if actual is None:
        actual = {x.execution_id: x for x in store.executions()}
    if any(actual.get(x["execution_id"]) != ExecutionRecord.model_validate(x)
           for x in frozen["executions"]):
        raise ValueError("Frozen execution differs from original")


def latest(path: Path, store=None) -> dict | None:
    with connect(path) as db:
        selected = db.execute("SELECT run_id FROM mobile_decision_selections "
                              "ORDER BY sequence DESC LIMIT 1").fetchone()
        row = db.execute("SELECT run_id,scope_hash,payload,content_hash,phase "
                         "FROM mobile_decision_runs " + (
                             "WHERE run_id=?" if selected else "ORDER BY sequence DESC LIMIT 1"
                         ), () if selected is None else (selected[0],)).fetchone()
        if selected is not None and row is None:
            raise ValueError("Selected decision receipt missing")
    if row is None:
        return None
    value = _checked(row)
    if store is not None:
        _linked_inputs(store, value)
        if value["phase"] == "published" and not _published_in_store(store, value):
            raise ValueError("Published decision archive missing")
    return value


def view(path: Path, store) -> dict | None:
    value = latest(path, store)
    if value is None:
        return None
    day = datetime.fromisoformat(value["scope"]["as_of"]).date()
    status = store.daily_status(day)
    active = value["phase"] == "published" and status is not None and not status.is_stale
    if active and value["outcome"] == "cash_only":
        active = (status.pipeline_state is PipelineState.CASH_ONLY
                  and store.cash_only_inputs_current(day))
    elif active:
        proposal = _proposal(value)
        active = proposal is not None and status.proposal_id == proposal.proposal_id
        active = active and store.proposal_inputs_current(proposal)
    return {**value, "is_active": bool(active)}


def _save(path, store, scope, now, *, comparison=None, market=None, frozen=None, blocks=(),
          outcome="blocked", data_as_of=None):
    proposal = None if comparison is None else comparison.proposal
    status = DailyOperationStatus(
        business_date=datetime.fromisoformat(scope["as_of"]).date(), updated_at=now,
        data_as_of=data_as_of if frozen is None or frozen["forecast"] is None else
        PredictionSnapshot.model_validate(frozen["forecast"]).data_as_of,
        pipeline_state=(PipelineState.CASH_ONLY if outcome == "cash_only" else
                        PipelineState.PROPOSAL_READY if proposal is not None else
                        PipelineState.STALE_DATA),
        proposal_id=None if proposal is None else proposal.proposal_id,
        blocking_reason=blocks[0] if blocks else None, is_stale=outcome == "blocked",
    )
    body = {"schema_version": "mobile-decision-run-v1", "scope": scope,
            "scope_hash": content_id(scope), "checked_at": now.isoformat(), "outcome": outcome,
            "comparison": None if comparison is None else comparison.model_dump(mode="json"),
            "frozen_inputs": frozen, "market": market, "blocking_reasons": list(blocks),
            "publication_status": status.model_dump(mode="json"), "decision_policy": None,
            "research_only": True, "order_submission": False}
    if proposal is not None:
        body["decision_policy"] = DecisionPolicySnapshot(
            proposal_id=proposal.proposal_id, captured_at=proposal.generated_at,
            config=comparison.request.settings.decision_policy,
        ).model_dump(mode="json")
    body["run_id"] = content_id(body)
    with connect(path) as db:
        db.execute("INSERT OR IGNORE INTO mobile_decision_runs VALUES(NULL,?,?,?,?,?)", (
            body["run_id"], body["scope_hash"], canonical_json(body), content_id(body),
            "blocked" if outcome == "blocked" else "computed",
        ))
        row = db.execute("SELECT run_id,scope_hash,payload,content_hash,phase "
                         "FROM mobile_decision_runs WHERE scope_hash=?", (body["scope_hash"],)
                         ).fetchone()
    saved = _checked(row)
    _select(path, saved["run_id"], now)
    if outcome == "blocked":
        store.set_daily_status(DailyOperationStatus.model_validate(saved["publication_status"]))
        return saved
    return _publish(path, store, saved, now)


def generate(path: Path, store, now: datetime, numerical=None, *,
             refresh_consultation=False) -> dict:
    if now.tzinfo is None:
        raise ValueError("Aware decision execution time required")
    cutoff = now.astimezone(forecasts.JST).replace(hour=11, minute=30, second=0, microsecond=0)
    numerical = forecasts.latest(path) if numerical is None else numerical
    manual, ledger = store.latest_manual_portfolio(), store.latest_portfolio()
    _profile, saved, gaps, compiled = personal.input_state(store, now)
    executions = sorted(store.executions(), key=lambda x: x.execution_id)
    scope = {"as_of": cutoff.isoformat(),
             "numerical_run_id": None if numerical is None else numerical["run_id"],
             "personal_refs": {
                 "manual_revision_id": None if manual is None else manual.export.revision_id,
                 "ledger_portfolio_id": None if ledger is None else ledger.portfolio_id,
                 "settings_revision_id": None if saved is None else saved["revision_id"],
                 "executions_sha256": content_id([x.model_dump(mode="json") for x in executions])},
             "implementation": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()
                                                      ).hexdigest() for name in
                                ("decisions.py", "decision_market.py", "personal.py")},
             "shared_implementation": implementation_hashes(compiled)}
    def blocked(code):
        return _save(path, store, {**scope, "blocking_scope": code}, now, blocks=(code,))
    if now < cutoff:
        return blocked("ALPHA_CUTOFF_OPEN")
    if numerical is None or numerical["phase"] not in ("published", "cash_only"):
        return blocked("NUMERICAL_FORECAST_INCOMPLETE")
    if datetime.fromisoformat(numerical["scope"]["as_of"]) != cutoff:
        return blocked("NUMERICAL_FORECAST_NOT_CURRENT_DAY")
    if manual is None or ledger is None or saved is None or compiled is None or gaps:
        return blocked("PERSONAL_INPUTS_INCOMPLETE")
    if (scope["personal_refs"]["manual_revision_id"] != numerical["scope"]["manual_revision_id"]
            or ledger.portfolio_id != numerical["scope"]["ledger_portfolio_id"]):
        return blocked("PERSONAL_INPUTS_DIFFER_FROM_NUMERICAL")
    if datetime.fromisoformat(saved["saved_at"]) > cutoff:
        return blocked("PERSONAL_SETTINGS_AFTER_ALPHA_CUTOFF")
    if (max(manual.received_at, manual.export.saved_at, ledger.as_of) > cutoff
            or cutoff - min(manual.export.saved_at, ledger.as_of) > timedelta(hours=72)):
        return blocked("PERSONAL_INPUTS_STALE_OR_AFTER_FORECAST")
    if datetime.fromisoformat(numerical["checked_at"]) > now:
        return blocked("NUMERICAL_FORECAST_FROM_FUTURE")
    try:
        bundle, pin = models.load_bundle(path, cutoff)
    except (ValueError, KeyError, TypeError):
        return blocked("CALIBRATED_MODEL_BUNDLE_UNAVAILABLE")
    if (bundle.bundle_id != numerical["scope"]["bundle_id"]
            or pin["sha256"] != numerical["scope"]["bundle_sha256"]):
        return blocked("MODEL_SELECTION_DIFFERS_FROM_NUMERICAL")
    scope["bundle_pin_sha256"] = content_id(pin)
    if refresh_consultation or isinstance(bundle, (ResearchModelBundle, ResearchEnsembleBundle)):
        # A fresh explicit calculation can renew the consultation context while
        # preserving the original forecast, prices and expired exchanges.
        elapsed = now - datetime.fromisoformat(numerical["checked_at"])
        scope["consultation_window"] = int(elapsed.total_seconds() // (15 * 60))
    with connect(path) as db:
        existing = db.execute("SELECT run_id,scope_hash,payload,content_hash,phase "
                              "FROM mobile_decision_runs WHERE scope_hash=?", (content_id(scope),)
                              ).fetchone()
    if existing is not None:
        _select(path, existing[0], now)
        return _publish(path, store, _checked(existing), now)
    frozen = {"manual": manual.model_dump(mode="json"), "ledger": ledger.model_dump(mode="json"),
              "forecast": numerical["snapshot"],
              "executions": [x.model_dump(mode="json") for x in executions]}
    if numerical["outcome"] == "cash_only":
        if (any(x.shares > 0 for x in ledger.positions) or manual.portfolio.holding_symbols
                or numerical["scope"]["universe"]["decision_symbols"]):
            return blocked("CASH_ONLY_INPUTS_DIFFER")
        issues = []
        _reconcile(manual, ledger, compiled,
                   lambda code, account=None, symbol=None: issues.append(code))
        known = {x.execution_id for x in executions}
        if set(ledger.applied_execution_ids) - known or any(
            x.executed_at > cutoff
            or x.status in (ExecutionStatus.OPEN, ExecutionStatus.PARTIALLY_FILLED)
            or (x.filled_shares and x.execution_id not in ledger.applied_execution_ids)
            or (x.execution_id in ledger.applied_execution_ids and x.executed_at > ledger.as_of)
            for x in executions
        ):
            issues.append("CASH_EXECUTIONS_UNRECONCILED")
        if issues:
            return blocked(issues[0])
        selected = numerical["scope"]["universe"]
        received = max([receipt_time(selected["membership_received_at"]),
                        *(receipt_time(x["received_at"]) for x in selected["sources"])])
        return _save(path, store, scope, now, frozen=frozen, outcome="cash_only",
                     data_as_of=received)
    try:
        market = decision_market.prepare(path, numerical)
    except (ValueError, KeyError, TypeError) as error:
        return blocked(str(error) if isinstance(error, decision_market.EvidenceUnavailable)
                       else "FROZEN_MARKET_EVIDENCE_INVALID")
    snapshot = PredictionSnapshot.model_validate(numerical["snapshot"])
    guard = PersonalPublicationGuard(**scope["personal_refs"],
                                     forecast_snapshot_id=snapshot.snapshot_id)
    request = PersonalComparisonRequest(checked_at=now, maximum_input_age_hours=72,
                                        settings=compiled, market=market["evidence"])
    comparison = compare_stored_personal(
        store, request, now=now, forecast_snapshot_id=snapshot.snapshot_id, publication_guard=guard,
    )
    expected_inputs = content_id({"request": request.model_dump(mode="json"), **frozen})
    if comparison.inputs_sha256 != expected_inputs:
        raise OperationalConflictError("decision personal inputs changed during computation")
    if comparison.proposal is None:
        blocks = tuple(x.code for x in comparison.blocking_reasons)
        return _save(path, store, {**scope, "blocking_scope": blocks}, now, comparison=comparison,
                     market=market, frozen=frozen, blocks=blocks)
    if forecasts.latest(path)["run_id"] != numerical["run_id"]:
        raise OperationalConflictError("numerical forecast changed during computation")
    return _save(path, store, scope, now, comparison=comparison, market=market, frozen=frozen,
                 outcome="proposal")
