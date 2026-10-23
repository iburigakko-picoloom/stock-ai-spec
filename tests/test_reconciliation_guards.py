from datetime import timedelta

import pytest

from stock_ai.operations import OperationalConflictError, OperationalStore
from tests.conftest import AS_OF
from tests.test_operations_store import _nisa_execution_store, _proposal_store


def csv_positions():
    return (
        "as_of,record_type,symbol,account_bucket_id,shares,average_acquisition_price,"
        "market_price,available_cash,reserved_cash\n"
        f"{(AS_OF + timedelta(hours=4)).isoformat()},CASH,,bucket,,,,500000,0\n"
    )


def preview(store):
    return store.preview_position_reconciliation_csv(
        csv_positions(), preview_id="guard", created_at=AS_OF + timedelta(hours=4),
    )


def confirm(store, identity="result"):
    return store.confirm_position_reconciliation(
        "guard", next_portfolio_id=identity, confirm_all_differences=True,
        created_at=AS_OF + timedelta(hours=4),
    )


def test_changed_base_refuses_old_preview_without_mutation(tmp_path):
    store, _ = _proposal_store(tmp_path)
    old = preview(store)
    current = store.latest_portfolio()
    newer = current.model_copy(update={"portfolio_id": "new", "as_of": AS_OF + timedelta(hours=1)})
    store.append_portfolio(newer, created_at=newer.as_of)
    with pytest.raises(OperationalConflictError, match="BASE_CHANGED"):
        confirm(store)
    assert store.position_reconciliation("guard") == old
    assert store.latest_portfolio() == newer


def test_confirm_retry_returns_original_even_after_later_ledger(tmp_path):
    store, _ = _proposal_store(tmp_path)
    preview(store)
    result = confirm(store, " result ")
    newer = result.model_copy(update={"portfolio_id": "later", "as_of": AS_OF + timedelta(days=1)})
    store.append_portfolio(newer, created_at=newer.as_of)
    counts = store.verify_integrity()
    assert confirm(store) == result
    assert store.verify_integrity() == counts
    assert store.latest_portfolio() == newer
    with pytest.raises(OperationalConflictError, match="ALREADY_CONFIRMED"):
        confirm(store, "different")
    restored = OperationalStore(store.path).position_reconciliation("guard")
    assert restored.confirmed_portfolio_id == "result"


def test_new_fill_invalidates_preview_and_unapplied_fill_blocks_repreview(tmp_path):
    store, execution = _nisa_execution_store(tmp_path)
    original = preview(store)
    store.append_execution(execution)
    with pytest.raises(OperationalConflictError, match="EXECUTIONS_CHANGED"):
        confirm(store)
    assert store.position_reconciliation("guard") == original
    with pytest.raises(OperationalConflictError, match="UNAPPLIED_EXECUTIONS"):
        store.preview_position_reconciliation_csv(
            csv_positions(), preview_id="retry", created_at=AS_OF + timedelta(hours=4),
        )


def test_confirm_insert_failure_rolls_back_preview_status(tmp_path, monkeypatch):
    store, _ = _proposal_store(tmp_path)
    original = preview(store)
    insert = store._insert_immutable
    def fail(connection, **kwargs):
        if kwargs["table"] == "portfolio_states":
            raise RuntimeError("interrupted")
        return insert(connection, **kwargs)
    monkeypatch.setattr(store, "_insert_immutable", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        confirm(store)
    assert store.position_reconciliation("guard") == original
    monkeypatch.setattr(store, "_insert_immutable", insert)
    assert confirm(store).portfolio_id == "result"


def test_legacy_preview_requires_repreview_without_rewriting_original(tmp_path):
    from stock_ai.operations.models import ImportStatus
    from stock_ai.operations.store import _canonical_payload, _payload_hash
    store, _ = _proposal_store(tmp_path)
    original = preview(store)
    legacy = original.model_copy(update={"base_reference": None})
    payload = _canonical_payload(legacy)
    with store._connect() as connection:
        connection.execute("UPDATE position_reconciliations SET payload=?, content_hash=?",
                           (payload, _payload_hash(payload)))
        connection.commit()
    store.verify_integrity()
    with pytest.raises(OperationalConflictError, match="REPREVIEW_REQUIRED"):
        confirm(store)
    assert store.position_reconciliation("guard").status is ImportStatus.PREVIEW
    assert store.position_reconciliation("guard").base_reference is None


def test_post_cutoff_execution_does_not_invalidate_fingerprint(tmp_path):
    store, execution = _nisa_execution_store(tmp_path)
    preview(store)
    store.append_execution(execution.model_copy(update={"executed_at": AS_OF + timedelta(days=1)}))
    result = confirm(store)
    assert execution.execution_id not in result.applied_execution_ids
    assert result.tax_states == store.portfolio("portfolio").tax_states


def test_future_import_and_blank_result_id_are_rejected(tmp_path, monkeypatch):
    store, _ = _proposal_store(tmp_path)
    monkeypatch.setattr("stock_ai.operations.store._now_utc", lambda: AS_OF + timedelta(hours=2))
    with pytest.raises(OperationalConflictError, match="IN_FUTURE"):
        preview(store)
    monkeypatch.setattr("stock_ai.operations.store._now_utc", lambda: AS_OF + timedelta(days=1))
    preview(store)
    with pytest.raises(ValueError, match="blank"):
        confirm(store, " ")


def test_execution_import_batch_failure_is_atomic_and_retry_has_stable_receipt(
    tmp_path, monkeypatch,
):
    from stock_ai.domain import ExecutionStatus
    from stock_ai.operations.models import ExecutionImportPreview
    from stock_ai.operations.store import _canonical_payload
    store, execution = _nisa_execution_store(tmp_path)
    first = execution.model_copy(update={
        "execution_id": "fill-1", "filled_shares": 40, "status": ExecutionStatus.PARTIALLY_FILLED,
    })
    second = execution.model_copy(update={
        "execution_id": "fill-2", "filled_shares": 60, "status": ExecutionStatus.PARTIALLY_FILLED,
    })
    store._save_import_preview(ExecutionImportPreview(
        preview_id="batch", source_hash="a" * 64, created_at=AS_OF + timedelta(hours=2),
        execution_payloads=tuple(_canonical_payload(x) for x in (first, second)), conflicts=(),
    ))
    insert = store._insert_immutable
    def fail_second(connection, **kwargs):
        if kwargs["identity"] == "fill-2":
            raise RuntimeError("synthetic interruption")
        return insert(connection, **kwargs)
    monkeypatch.setattr(store, "_insert_immutable", fail_second)
    with pytest.raises(RuntimeError, match="interruption"):
        store.confirm_execution_import("batch")
    assert store.executions() == ()
    assert store.import_preview("batch").confirmed_counts is None
    monkeypatch.setattr(store, "_insert_immutable", insert)
    assert store.confirm_execution_import("batch") == (2, 0)
    assert store.confirm_execution_import("batch") == (2, 0)
    assert len(store.executions()) == 2


def test_sqlite_busy_is_retryable_not_integrity_failure(tmp_path, monkeypatch):
    import sqlite3

    from stock_ai.operations.store import OperationalStorageBusyError
    store, _ = _proposal_store(tmp_path)
    original_connect = sqlite3.connect
    class ShortWait(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == "PRAGMA busy_timeout=30000":
                sql = "PRAGMA busy_timeout=1"
            return super().execute(sql, parameters)
    with original_connect(store.path) as holder:
        holder.execute("BEGIN IMMEDIATE")
        monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs:
                            original_connect(*args, **kwargs, factory=ShortWait))
        with pytest.raises(OperationalStorageBusyError, match="STORAGE_BUSY"):
            preview(store)
    assert store.verify_integrity()["position_reconciliations"] == 0
