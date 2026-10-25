from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from stock_ai.operations import OperationalIntegrityError, OperationalStore
from stock_ai.operations.chatgpt_research import (
    ChatGPTResearchRecord,
    ResearchConfiguration,
    ResearchContext,
    ResearchPass,
    accept_response,
    comparison_request,
    create_record,
    independent_request,
    validate_context,
)
from stock_ai.operations.daily import (
    QUOTE_SESSION_LABEL,
    PredictionSnapshot,
    canonical_json,
    content_id,
)
from tests.test_daily_readiness import daily_snapshot


def context_for(snapshot: PredictionSnapshot) -> ResearchContext:
    return ResearchContext(
        prediction_snapshot_id=snapshot.snapshot_id,
        symbol="A",
        company_name="試験株式会社",
        numerical_as_of=snapshot.as_of,
        research_as_of=snapshot.generated_at + timedelta(minutes=4),
        configuration=ResearchConfiguration(model="account-selected-model", effort="high"),
    )


def test_legacy_label_cannot_start_new_numerical_research_context():
    source = daily_snapshot()
    legacy = PredictionSnapshot.create(**{
        **source.model_dump(exclude={"snapshot_id"}), "label_definition": QUOTE_SESSION_LABEL,
    })
    original = legacy.model_dump_json()
    with pytest.raises(ValueError, match="LABEL_DEFINITION_UNVERIFIED"):
        validate_context(context_for(legacy), legacy)
    assert legacy.model_dump_json() == original


def response_for(*, search: bool = True, citations: bool = True) -> dict[str, Any]:
    """Deterministic provider fixture; never used as production market research."""
    message = {
        "type": "message", "status": "completed", "role": "assistant",
        "content": [{
            "type": "output_text", "text": "事実・反対材料を比較。未確認事項は判断保留。",
            "annotations": [{
                "type": "url_citation", "url": "https://example.com/ir", "title": "公開IR",
                "start_index": 0, "end_index": 2,
            }] if citations else [],
        }],
    }
    return {
        "id": "resp-fixture", "model": "account-selected-model", "status": "completed",
        "output": ([{"type": "web_search_call", "status": "completed"}] if search else [])
        + [message],
    }


def pass_for(
    snapshot: PredictionSnapshot, context: ResearchContext,
    phase: Literal["independent", "comparison"] = "independent",
    independent: ResearchPass | None = None,
) -> ResearchPass:
    started_at = (
        context.research_as_of if independent is None else independent.completed_at
    ) + timedelta(seconds=1)
    return accept_response(
        context, phase, response_for(search=phase == "independent"),
        snapshot=snapshot, independent=independent,
        started_at=started_at, completed_at=started_at + timedelta(seconds=15),
    )


def record_for(snapshot: PredictionSnapshot) -> ChatGPTResearchRecord:
    context = context_for(snapshot)
    first = pass_for(snapshot, context)
    second = pass_for(snapshot, context, "comparison", first)
    return create_record(context, first, second, snapshot)


def test_independent_prompt_is_invariant_to_numerical_prediction_and_rank() -> None:
    snapshot = daily_snapshot()
    context = context_for(snapshot)
    original = independent_request(context)
    changed_prediction = snapshot.predictions[0].model_copy(update={"expected_return_5d": -0.3})
    values = snapshot.model_dump(exclude={"snapshot_id", "predictions"})
    changed = PredictionSnapshot.create(**values, predictions=(changed_prediction,))
    changed_context = context_for(changed)
    assert changed.snapshot_id != snapshot.snapshot_id
    assert independent_request(changed_context) == original
    target = json.loads(original["input"][0]["content"])  # type: ignore[index]
    assert set(target) == {"symbol", "company_name", "research_as_of", "market_evidence",
                           "market_topics", "web_research_needed"}
    for prohibited in ("expected_return", "rank", "holding", "balance", "BUY", "snapshot_id"):
        assert prohibited not in canonical_json(original)


def test_comparison_preserves_original_research_and_exact_numerical_prediction() -> None:
    snapshot = daily_snapshot()
    before = snapshot.model_dump_json()
    record = record_for(snapshot)
    request = comparison_request(record.context, record.independent, snapshot)
    target = json.loads(request["input"][0]["content"])  # type: ignore[index]
    assert target["independent_research"] == record.independent.text
    assert target["numerical_prediction"] == snapshot.predictions[0].model_dump(mode="json")
    assert record.comparison.independent_pass_id == record.independent.pass_id
    assert record.affects_numerical_proposal is False
    assert snapshot.model_dump_json() == before
    assert record.independent.sources[0].published_at is None


@pytest.mark.parametrize("status", ["in_progress", "incomplete", "failed", "cancelled"])
def test_partial_response_is_never_success(status: str) -> None:
    snapshot = daily_snapshot()
    context = context_for(snapshot)
    response = response_for()
    response["status"] = status
    with pytest.raises(ValueError, match="completed"):
        accept_response(
            context, "independent", response, snapshot=snapshot,
            started_at=context.research_as_of, completed_at=context.research_as_of,
        )


@pytest.mark.parametrize("search,citations", [(False, True), (True, False), (False, False)])
def test_independent_research_requires_observed_search_and_citations(
    search: bool, citations: bool,
) -> None:
    snapshot = daily_snapshot()
    context = context_for(snapshot)
    with pytest.raises(ValueError, match="search and sources"):
        accept_response(
            context, "independent", response_for(search=search, citations=citations),
            snapshot=snapshot, started_at=context.research_as_of,
            completed_at=context.research_as_of,
        )


@pytest.mark.parametrize("case", ["refusal", "empty", "http", "credential", "partial", "error"])
def test_invalid_or_refused_output_is_not_completed_research(case: str) -> None:
    snapshot = daily_snapshot()
    context = context_for(snapshot)
    response = response_for()
    message = response["output"][-1]
    part = message["content"][0]
    if case == "refusal":
        message["content"].append({"type": "refusal", "refusal": "調査できません"})
    elif case == "empty":
        part["text"] = " "
    elif case in {"http", "credential"}:
        part["annotations"][0]["url"] = (
            "http://example.com/ir" if case == "http" else "https://user:secret@example.com/ir"
        )
    elif case == "partial":
        message["status"] = "incomplete"
    else:
        response["error"] = {"code": "subscription_sharing_usage_limit_exceeded"}
    with pytest.raises(ValueError):
        accept_response(
            context, "independent", response, snapshot=snapshot,
            started_at=context.research_as_of, completed_at=context.research_as_of,
        )


def test_pass_order_snapshot_and_content_identity_are_enforced() -> None:
    snapshot = daily_snapshot()
    context = context_for(snapshot)
    first = pass_for(snapshot, context)
    with pytest.raises(ValueError, match="requires completed"):
        pass_for(snapshot, context, "comparison")
    with pytest.raises(ValueError, match="cannot start"):
        accept_response(
            context, "comparison", response_for(), snapshot=snapshot, independent=first,
            started_at=first.started_at, completed_at=first.completed_at,
        )
    with pytest.raises(ValueError, match="another numerical snapshot"):
        validate_context(context.model_copy(update={"prediction_snapshot_id": "a" * 64}), snapshot)
    with pytest.raises(ValueError, match="predates"):
        validate_context(context.model_copy(update={"research_as_of": snapshot.as_of}), snapshot)
    with pytest.raises(ValidationError, match="identity mismatch"):
        ResearchPass.model_validate_json(
            first.model_copy(update={"text": "改変"}).model_dump_json()
        )
    second = pass_for(snapshot, context, "comparison", first)
    wrong_request = second.model_dump(mode="json", exclude={"pass_id"})
    wrong_request["request_sha256"] = "b" * 64
    forged = ResearchPass.model_validate({**wrong_request, "pass_id": content_id(wrong_request)})
    with pytest.raises(ValueError, match="comparison request differs"):
        create_record(context, first, forged, snapshot)


def test_top20_limit_keeps_all_holdings() -> None:
    original = daily_snapshot()
    symbols = tuple(f"S{index:02}" for index in range(25))
    values = original.model_dump(exclude={"snapshot_id", "predictions", "candidate_symbols"})
    values["holding_symbols"] = (symbols[-1],)
    predictions = tuple(
        original.predictions[0].model_copy(update={"symbol": symbol}) for symbol in symbols
    )
    snapshot = PredictionSnapshot.create(
        **values, candidate_symbols=symbols, predictions=predictions,
    )
    context = context_for(snapshot)
    validate_context(context.model_copy(update={"symbol": symbols[-1]}), snapshot)
    with pytest.raises(ValueError, match="top20"):
        validate_context(context.model_copy(update={"symbol": symbols[21]}), snapshot)


def test_two_passes_resume_idempotently_and_survive_backup_without_changing_forecast(
    tmp_path: Path,
) -> None:
    store = OperationalStore(tmp_path / "ledger.sqlite")
    snapshot = daily_snapshot()
    record = record_for(snapshot)
    store.append_prediction_snapshot(snapshot)
    with pytest.raises(OperationalIntegrityError, match="missing a saved"):
        store.append_chatgpt_pass(record.comparison)
    assert store.append_chatgpt_pass(record.independent)
    assert not store.append_chatgpt_pass(record.independent)
    assert store.chatgpt_research(snapshot.snapshot_id) == ()
    resumed = OperationalStore(store.path)
    assert resumed.chatgpt_passes(snapshot.snapshot_id) == (record.independent,)
    assert resumed.append_chatgpt_pass(record.comparison)
    assert resumed.append_chatgpt_research(record)
    assert not resumed.append_chatgpt_research(record)
    assert resumed.prediction_snapshot(snapshot.snapshot_id) == snapshot
    counts = resumed.verify_integrity()
    assert counts["chatgpt_research_passes"] == 2
    assert counts["chatgpt_research_records"] == 1
    backup = resumed.backup(tmp_path / "backup.sqlite")
    restored = OperationalStore.restore_backup(
        backup, tmp_path / "restored.sqlite", confirm_replace=True,
    )
    assert OperationalStore(restored).chatgpt_research(snapshot.snapshot_id) == (record,)


def test_backup_rejects_rehashed_research_with_wrong_numerical_lineage(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "ledger.sqlite")
    snapshot = daily_snapshot()
    record = record_for(snapshot)
    store.append_prediction_snapshot(snapshot)
    store.append_chatgpt_pass(record.independent)
    store.append_chatgpt_pass(record.comparison)
    store.append_chatgpt_research(record)
    raw = record.model_dump(mode="json", exclude={"research_id"})
    raw["numerical_prediction_sha256"] = "f" * 64
    forged = {**raw, "research_id": content_id(raw)}
    payload = canonical_json(forged)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE chatgpt_research_records SET research_id = ?, payload = ?, content_hash = ?",
            (forged["research_id"], payload, hashlib.sha256(payload.encode()).hexdigest()),
        )
    with pytest.raises(OperationalIntegrityError, match="record lineage"):
        store.verify_integrity()
    with pytest.raises(OperationalIntegrityError):
        store.backup(tmp_path / "invalid-backup.sqlite")
    assert not (tmp_path / "invalid-backup.sqlite").exists()


def test_schema3_backup_migrates_without_research_or_forecast_loss(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "legacy.sqlite")
    snapshot = daily_snapshot()
    store.append_prediction_snapshot(snapshot)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE chatgpt_research_records")
        connection.execute("DROP TABLE chatgpt_research_passes")
        connection.execute("PRAGMA user_version=3")
    restored_path = OperationalStore.restore_backup(
        store.path, tmp_path / "restored.sqlite", confirm_replace=True,
    )
    migrated = OperationalStore(restored_path)
    assert migrated.prediction_snapshot(snapshot.snapshot_id) == snapshot
    assert migrated.chatgpt_research(snapshot.snapshot_id) == ()
    assert migrated.verify_integrity()["chatgpt_research_passes"] == 0
    with sqlite3.connect(restored_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
