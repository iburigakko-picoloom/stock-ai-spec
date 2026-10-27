from __future__ import annotations

import asyncio
import base64
import io
import json
import sqlite3
import zipfile
from contextlib import closing
from unittest.mock import Mock

import pytest
from mobile.python import runtime


@pytest.fixture()
def device(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "STATE", tmp_path / "state")
    runtime.initialize()
    return runtime


def run(device, method, path, body=None):
    return asyncio.run(device.request(method, path, json.dumps(body)))


def test_reference_request_is_explicit_and_today_projection_does_not_create_proposal(
    device, monkeypatch,
):
    calls = []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        return {"phase": "reference_saved" if kwargs else "blocked"}
    monkeypatch.setattr(runtime.forecasts, "generate", generate)
    endpoint = "/api/v1/mobile/daily/generate"
    assert run(device, "POST", endpoint, {})["status"] == 200
    assert run(device, "POST", endpoint, {"reference_only": True})["body"] == {
        "phase": "reference_saved"}
    for invalid in ({"reference_only": "true"}, {"reference_only": 1}, {"other": True}, None):
        assert run(device, "POST", endpoint, invalid)["status"] == 422
    assert calls == [{}, {"reference_only": True}]
    original = run(device, "GET", "/api/v1/today")["body"]
    reference = {"generatedAt": "2026-01-01T10:00:00+09:00", "readOnly": True,
                 "analysisKind": "latest_available_reference"}
    monkeypatch.setattr(runtime.forecasts, "reference_view", lambda *args: reference)
    updated = run(device, "GET", "/api/v1/today")["body"]
    assert updated == {**original, "savedAnalysis": reference}
    assert device._app.state.store.latest_prediction_snapshot() is None


def test_checked_startup_skips_unchanged_and_saves_only_changed_database(device, monkeypatch):
    assert device.initialize_checked() == {"persistence": "none"}
    initialize = device.initialize

    def ledger_migration():
        initialize()
        with closing(sqlite3.connect(device.STATE / "operations.sqlite3")) as db:
            db.execute("INSERT OR REPLACE INTO operational_metadata VALUES('startup_probe','v1')")
            db.commit()

    monkeypatch.setattr(device, "initialize", ledger_migration)
    assert device.initialize_checked() == {"persistence": "operations"}
    assert device.initialize_checked() == {"persistence": "none"}

    def market_migration():
        initialize()
        with closing(sqlite3.connect(device.STATE / "mobile.sqlite3")) as db:
            db.execute("CREATE TABLE startup_probe(id INTEGER PRIMARY KEY)")
            db.commit()

    monkeypatch.setattr(device, "initialize", market_migration)
    assert device.initialize_checked() == {"persistence": "full"}


def test_unchanged_startup_reuses_integrity_proof_for_first_read(device, monkeypatch):
    original_create = device.create_app
    verifiers = []
    def traced_create(*args, **kwargs):
        app = original_create(*args, **kwargs)
        verify = Mock(wraps=app.state.store.verify_integrity)
        monkeypatch.setattr(app.state.store, "verify_integrity", verify)
        verifiers.append(verify)
        return app
    monkeypatch.setattr(device, "create_app", traced_create)
    device.initialize()
    assert verifiers[-1].call_count == 1
    assert run(device, "GET", "/api/v1/today?includeSavedAnalysis=false")["status"] == 200
    assert verifiers[-1].call_count == 1


def test_startup_rechecks_and_rejects_corruption_during_reconciliation(device, monkeypatch):
    from stock_ai.operations.store import OperationalIntegrityError
    from tests.conftest import AS_OF, portfolio

    device._app.state.store.append_portfolio(portfolio(), created_at=AS_OF)
    initialize = device.personal.initialize
    def corrupt_after_initial_check(store, path, now):
        initialize(store, path, now)
        with closing(sqlite3.connect(store.path)) as db:
            db.execute("UPDATE portfolio_states SET content_hash='corrupt'")
            db.commit()
    monkeypatch.setattr(device.personal, "initialize", corrupt_after_initial_check)
    with pytest.raises(OperationalIntegrityError):
        device.initialize()


def test_startup_rechecks_after_legitimate_store_change(device, monkeypatch):
    original_create = device.create_app
    verifiers = []
    def traced_create(*args, **kwargs):
        app = original_create(*args, **kwargs)
        verify = Mock(wraps=app.state.store.verify_integrity)
        monkeypatch.setattr(app.state.store, "verify_integrity", verify)
        verifiers.append(verify)
        return app
    initialize = device.personal.initialize
    def change_after_initial_check(store, path, now):
        initialize(store, path, now)
        with closing(sqlite3.connect(store.path)) as db:
            db.execute("INSERT INTO operational_metadata VALUES('startup_probe','v1')")
            db.commit()
    monkeypatch.setattr(device, "create_app", traced_create)
    monkeypatch.setattr(device.personal, "initialize", change_after_initial_check)
    device.initialize()
    assert verifiers[-1].call_count == 2
    assert run(device, "GET", "/api/v1/today?includeSavedAnalysis=false")["status"] == 200
    assert verifiers[-1].call_count == 2


def test_split_startup_overlay_preserves_market_and_rejects_market_in_overlay(device):
    from scripts.mobile_native_history_fixture import table_snapshot

    market_before = table_snapshot(device.STATE / "mobile.sqlite3")
    operations = device.StateExport(operations_only=True)
    fragments = []
    while (fragment := operations.read_next()) is not None:
        fragments.append(fragment)
    stream = device.StateImport(sum(map(len, fragments)))
    for index, fragment in enumerate(fragments):
        stream.append(index, fragment)
    assert stream.finish(initialize_runtime=False, operations_only=True) == {}
    assert table_snapshot(device.STATE / "mobile.sqlite3") == market_before
    assert device.initialize_checked()["persistence"] == "none"
    full = device.export_state()
    # Legacy compaction is part of export, before the rejected import starts.
    before_rejected_import = table_snapshot(device.STATE / "mobile.sqlite3")
    stream = device.StateImport(len(full))
    for index, start in enumerate(range(0, len(full), 256 * 1024)):
        stream.append(index, full[start:start + 256 * 1024])
    with pytest.raises(ValueError, match="operations overlay"):
        stream.finish(initialize_runtime=False, operations_only=True)
    assert table_snapshot(device.STATE / "mobile.sqlite3") == before_rejected_import


def test_operations_export_does_not_copy_or_compact_market_database(device, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A small ledger save must not compact market history")

    monkeypatch.setattr(runtime.market, "compact_legacy", forbidden)
    original = runtime.sqlite3.connect
    opened = []

    def connect(path, *args, **kwargs):
        opened.append(str(path))
        assert not str(path).endswith("mobile.sqlite3")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(runtime.sqlite3, "connect", connect)
    stream = device.StateExport(operations_only=True)
    fragments = []
    while (fragment := stream.read_next()) is not None:
        fragments.append(fragment)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode("".join(fragments)))) as archive:
        assert archive.namelist() == ["operations.sqlite3"]
        assert archive.read("operations.sqlite3").startswith(b"SQLite format 3\x00")
    assert any(path.endswith("operations.sqlite3") for path in opened)


def test_stream_restore_closes_live_integrity_observer_before_replacing_database(device):
    value = {"schema_version": "manual-portfolio-v1", "holdings_status": "none",
             "investment_budget_yen": "1000", "maximum_drawdown_percent": None,
             "accounts": [], "holdings": []}
    saved = run(device, "POST", "/api/v1/mobile/portfolio", value)["body"]
    export = device.StateExport(operations_only=True)
    pieces = []
    while (piece := export.read_next()) is not None:
        pieces.append(piece)
    assert run(device, "GET", "/api/v1/health")["status"] == 200
    changed = {**value, "investment_budget_yen": "2000"}
    assert run(device, "POST", "/api/v1/mobile/portfolio", {
        "expected_revision_id": saved["revision_id"], "portfolio": changed,
    })["status"] == 200
    assert run(device, "GET", "/api/v1/health")["status"] == 200
    assert device._app.state.integrity_guard._observer is not None
    stream = device.StateImport(sum(map(len, pieces)))
    for index, piece in enumerate(pieces):
        stream.append(index, piece)
    stream.finish(operations_only=True)
    assert run(device, "GET", "/api/v1/mobile/portfolio")["body"] == saved
    assert run(device, "GET", "/api/v1/health")["status"] == 200


def test_decision_and_execution_overlay_survive_restore_without_market_rewrite(device):
    from datetime import timedelta

    from scripts.mobile_native_history_fixture import table_snapshot

    from stock_ai.operations import bootstrap_goal5_fixture, create_app
    from tests.conftest import AS_OF

    store = device._app.state.store
    proposal_id = bootstrap_goal5_fixture(store, as_of=AS_OF)
    proposal = store.proposal(proposal_id)
    device._app.state.integrity_guard.close()
    device._app = create_app(store.path, clock=lambda: AS_OF + timedelta(hours=2))
    base = device.export_state()
    market_before = table_snapshot(device.STATE / "mobile.sqlite3")
    operations_before = table_snapshot(store.path)
    targets = {line.line_id: line.recommended_shares for line in proposal.lines}
    assert run(device, "POST", f"/api/v1/proposals/{proposal_id}/review", {
        "selectedTargets": targets,
    })["status"] == 200
    assert table_snapshot(store.path) == operations_before  # Review really is read-only.
    assert run(device, "POST", f"/api/v1/proposals/{proposal_id}/decisions", {
        "decisionId": "overlay-decision", "version": 1,
        "savedAt": (proposal.generated_at + timedelta(minutes=1)).isoformat(),
        "lines": [{"proposalLineId": key, "selectedTargetShares": value}
                  for key, value in targets.items()],
    })["status"] == 201
    line = next(item for item in proposal.lines if item.share_difference != 0)
    assert run(device, "POST", "/api/v1/decisions/overlay-decision/executions", {
        "executionId": "overlay-fill", "executedAt": (AS_OF + timedelta(hours=1)).isoformat(),
        "symbol": line.symbol, "accountBucketId": line.account_bucket_id,
        "status": "not_ordered", "side": "BUY" if line.share_difference > 0 else "SELL",
        "orderedShares": abs(line.share_difference), "filledShares": 0,
        "averageFillPrice": None, "actualCommission": "0", "actualOtherCost": "0",
        "taxWithheld": "0",
    })["status"] == 201
    assert table_snapshot(device.STATE / "mobile.sqlite3") == market_before
    expected = table_snapshot(store.path)
    export = device.StateExport(operations_only=True)
    pieces = []
    while (piece := export.read_next()) is not None:
        pieces.append(piece)
    device.initialize(base)
    importer = device.StateImport(sum(map(len, pieces)))
    for index, piece in enumerate(pieces):
        importer.append(index, piece)
    importer.finish(initialize_runtime=False, operations_only=True)
    importer.close()
    device.initialize()
    assert table_snapshot(device.STATE / "mobile.sqlite3") == market_before
    assert table_snapshot(device.STATE / "operations.sqlite3") == expected
    assert len(device._app.state.store.executions(decision_id="overlay-decision")) == 1


def test_preselection_is_opt_in_and_policy_survives_archive_restore(device):
    path = "/api/v1/mobile/market/universe-policy"
    assert run(device, "GET", path)["body"]["mode"] == "legacy300"
    assert run(device, "POST", path, {"mode": "topix500-preview"})["status"] == 200
    device.initialize(device.export_state())
    assert run(device, "GET", path)["body"]["mode"] == "topix500-preview"
    assert run(device, "POST", path, {"mode": "unknown"})["status"] == 422
    assert run(device, "GET", path)["body"]["mode"] == "topix500-preview"
    assert run(device, "POST", path, {"mode": "legacy300"})["body"]["experimental"] is False


def test_shared_api_runs_without_server_and_preserves_no_order_boundary(device):
    response = run(device, "GET", "/api/v1/health")
    assert response["status"] == 200
    assert response["body"]["orderSubmissionAvailable"] is False
    assert run(device, "POST", "/api/v1/orders", {})["status"] == 404
    assert run(device, "GET", "https://foreign.example/api/v1/health")["status"] == 400


def test_native_import_restores_typed_tables_without_full_string_or_deserialize(
    device, monkeypatch,
):
    import random

    from scripts.mobile_native_history_fixture import table_snapshot

    with closing(sqlite3.connect(device.STATE / "mobile.sqlite3")) as db:
        db.execute("CREATE TABLE imported_types(i INTEGER, f REAL, s TEXT, b BLOB, n)")
        db.execute("INSERT INTO imported_types VALUES(?, ?, ?, ?, ?)",
                   (7, 0.25, "日本語", random.Random(42).randbytes(600_000), None))
        db.commit()
    payload = device.export_state()
    expected = table_snapshot(device.STATE / "mobile.sqlite3")
    monkeypatch.setattr(device, "STATE", device.STATE.parent / "native-import")
    # Neither native import nor snapshot validation may assemble a full state
    # string or deserialize a second copy of the complete SQLite file.
    original = device.base64.b64decode
    seen = []

    def bounded_decode(value, **kwargs):
        assert len(value) <= 256 * 1024
        seen.append(len(value))
        return original(value, **kwargs)

    monkeypatch.setattr(device.base64, "b64decode", bounded_decode)
    original_connect = sqlite3.connect

    class FileOnly(sqlite3.Connection):
        def deserialize(self, *args, **kwargs):
            raise AssertionError("native restore must validate the SQLite file on disk")

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw:
                        original_connect(*a, **kw, factory=FileOnly))
    stream = device.StateImport(len(payload))
    for index, start in enumerate(range(0, len(payload), 256 * 1024)):
        stream.append(index, payload[start:start + 256 * 1024])
    stream.finish()
    assert len(seen) > 2
    assert table_snapshot(device.STATE / "mobile.sqlite3") == expected
    assert not list(device.STATE.glob("state-import-*"))
    assert stream._archive.closed
    assert run(device, "GET", "/api/v1/health")["body"]["orderSubmissionAvailable"] is False


@pytest.mark.parametrize("failure", [
    "order", "short", "nonascii", "invalid", "early-padding", "missing", "extra",
])
def test_native_import_rejects_invalid_fragments_and_cleans_quarantine(device, failure):
    from scripts.mobile_native_history_fixture import table_snapshot

    before = table_snapshot(device.STATE / "mobile.sqlite3")
    stream = device.StateImport(2 * 256 * 1024)
    with pytest.raises((ValueError, UnicodeError)):
        if failure == "missing":
            stream.finish()
        elif failure == "extra":
            stream.append(0, "A" * (256 * 1024))
            stream.append(1, "A" * (256 * 1024))
            stream.append(2, "AAAA")
        else:
            fragments = {"short": "AAAA", "nonascii": "あ" * (256 * 1024),
                         "invalid": "!" * (256 * 1024),
                         "early-padding": "A" * (256 * 1024 - 2) + "=="}
            fragment = fragments.get(failure, "A" * (256 * 1024))
            stream.append(1 if failure == "order" else 0, fragment)
    assert stream._archive.closed
    assert table_snapshot(device.STATE / "mobile.sqlite3") == before
    assert not list(device.STATE.glob("state-import-*"))


@pytest.mark.parametrize("length", [-4, 3, 256 * 1024 * 1024 + 4, True])
def test_native_import_rejects_invalid_length_before_allocating(length):
    with pytest.raises(ValueError, match="length"):
        runtime.StateImport(length)


@pytest.mark.parametrize("length", [128 * 1024 * 1024 + 4, 256 * 1024 * 1024])
def test_native_import_can_start_large_stream_without_allocating_whole_state(length):
    stream = runtime.StateImport(length)
    try:
        assert stream._archive.tell() == 0
        with pytest.raises(ValueError, match="Incomplete"):
            stream.finish()
        assert stream._archive.closed
    finally:
        stream.close()


@pytest.mark.parametrize("failure", [
    "second-database", "duplicate", "path", "truncated", "database-limit",
])
def test_native_import_authenticates_every_snapshot_before_replacing_any(
    device, monkeypatch, failure,
):
    before = {name: (device.STATE / name).read_bytes()
              for name in ("operations.sqlite3", "mobile.sqlite3")}
    candidate = device.STATE.parent / "candidate.sqlite3"
    with closing(sqlite3.connect(candidate)) as db:
        db.execute("CREATE TABLE must_not_replace_current(value)")
        db.commit()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("operations.sqlite3", candidate.read_bytes())
        member = "../outside.sqlite3" if failure == "path" else "mobile.sqlite3"
        content = (b"invalid second snapshot" if failure == "second-database"
                   else before["mobile.sqlite3"])
        archive.writestr(member, content)
        if failure == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate"):
                archive.writestr("operations.sqlite3", candidate.read_bytes())
    raw = output.getvalue()[:-10] if failure == "truncated" else output.getvalue()
    payload = base64.b64encode(raw).decode("ascii")
    if failure == "database-limit":
        monkeypatch.setattr(device, "MAX_DATABASE_BYTES", 1)
    stream = device.StateImport(len(payload))
    for index, start in enumerate(range(0, len(payload), 256 * 1024)):
        stream.append(index, payload[start:start + 256 * 1024])
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        stream.finish()
    assert stream._archive.closed
    assert before == {name: (device.STATE / name).read_bytes() for name in before}
    assert not list(device.STATE.glob("state-import-*"))
    assert not (device.STATE.parent / "outside.sqlite3").exists()


def test_aborted_native_import_closes_and_cannot_resume(device):
    stream = device.StateImport(4)
    stream.close()
    stream.close()
    with pytest.raises(ValueError):
        stream.append(0, "AAAA")
    assert stream._archive.closed
    assert run(device, "GET", "/api/v1/health")["status"] == 200


def test_native_export_chunks_preserve_exact_snapshots_and_restore(device, monkeypatch):
    import random

    from scripts.mobile_native_history_fixture import table_snapshot

    content = random.Random(20261017).randbytes(600_000)
    with closing(sqlite3.connect(device.STATE / "mobile.sqlite3")) as db:
        db.execute("CREATE TABLE stream_test (id INTEGER PRIMARY KEY, payload BLOB)")
        db.execute("INSERT INTO stream_test VALUES(1, ?)", (content,))
        db.commit()
    starting = device.export_state()
    parent = device.STATE.parent
    names = ("operations.sqlite3", "mobile.sqlite3")
    before = {name: table_snapshot(device.STATE / name) for name in names}
    # Each export performs the existing legacy compaction transaction. Start
    # both paths from identical SQLite bytes so file change-counters also match.
    for folder in ("legacy-source", "stream-source"):
        target = parent / folder
        target.mkdir()
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(starting))) as archive:
            for name in names:
                (target / name).write_bytes(archive.read(name))
    monkeypatch.setattr(device, "STATE", parent / "legacy-source")
    original = device.export_state()
    monkeypatch.setattr(device, "STATE", parent / "stream-source")
    stream = device.StateExport()
    pieces = []
    while (piece := stream.read_next()) is not None:
        assert 0 < len(piece) <= 256 * 1024
        pieces.append(piece)
    assert len(pieces) > 2 and all(len(piece) == 256 * 1024 for piece in pieces[:-1])
    encoded = "".join(pieces)
    assert len(encoded) == stream.length
    stream.close()
    assert stream.read_next() is None
    assert before == {name: table_snapshot(device.STATE / name) for name in before}
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(original))) as old:
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded, validate=True))) as new:
            assert new.namelist() == old.namelist() == ["operations.sqlite3", "mobile.sqlite3"]
            assert {name: new.read(name) for name in new.namelist()} == {
                name: old.read(name) for name in old.namelist()
            }
    monkeypatch.setattr(device, "STATE", parent / "stream-restored")
    device.initialize(encoded)
    assert before == {name: table_snapshot(device.STATE / name) for name in before}
    with closing(sqlite3.connect(device.STATE / "mobile.sqlite3")) as db:
        assert db.execute("SELECT payload FROM stream_test").fetchone()[0] == content
    assert run(device, "GET", "/api/v1/health")["body"]["orderSubmissionAvailable"] is False


@pytest.mark.parametrize("limit", ["archive", "database"])
def test_failed_native_export_preserves_state_and_cleans_snapshot(device, monkeypatch, limit):
    import random

    from scripts.mobile_native_history_fixture import table_snapshot

    with closing(sqlite3.connect(device.STATE / "mobile.sqlite3")) as db:
        db.execute("CREATE TABLE stream_limit (payload BLOB)")
        db.execute("INSERT INTO stream_limit VALUES(?)", (random.Random(42).randbytes(100_000),))
        db.commit()
    # Normalize the existing compaction cursor before testing a later failure.
    device.export_state()
    before = {name: table_snapshot(device.STATE / name)
              for name in ("operations.sqlite3", "mobile.sqlite3")}
    if limit == "archive":
        monkeypatch.setattr(device, "_MAX_NATIVE_STATE_CHARACTERS", 16 * 1024)
    else:
        monkeypatch.setattr(device, "MAX_DATABASE_BYTES", 1)
    with pytest.raises(ValueError, match="exceeds"):
        device.StateExport()
    assert not (device.STATE / "export.sqlite3").exists()
    assert before == {name: table_snapshot(device.STATE / name)
                      for name in before}
    assert run(device, "GET", "/api/v1/health")["status"] == 200


def test_aborted_native_export_closes_cleanly_and_keeps_the_runtime(device):
    stream = device.StateExport()
    assert stream.read_next()
    stream.close()
    stream.close()
    assert stream.read_next() is None
    assert not (device.STATE / "export.sqlite3").exists()
    assert run(device, "GET", "/api/v1/health")["status"] == 200


def test_all_local_connections_close_before_repeated_backup_restore(device, monkeypatch):
    original = sqlite3.connect
    opened = []

    def track(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)  # Keep strong refs: do not rely on garbage collection.
        return connection

    monkeypatch.setattr(sqlite3, "connect", track)
    try:
        for _ in range(3):
            device.initialize(device.export_state())
            for endpoint in ("models", "daily", "market/plan", "market/membership",
                             "market/universe", "personal/settings"):
                assert run(device, "GET", "/api/v1/mobile/" + endpoint)["status"] == 200
            for connection in opened:
                with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                    connection.execute("SELECT 1")
    finally:
        for connection in opened:
            connection.close()


def test_bundle_probe_never_imports_approves_or_publishes_a_prediction(device, monkeypatch):
    from mobile.python.model_bundle import encoded

    from tests.test_mobile_bundles import SELECTION, fixture_bundle

    monkeypatch.setattr(runtime, "bundled_selection", lambda: SELECTION)
    def database_contents():
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(device.export_state()))) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    before = database_contents()
    bundle = fixture_bundle()
    response = run(device, "POST", "/api/v1/mobile/models/bundle/parity", {
        "content": encoded(bundle), "rows": {"5": [{"f1": .2}], "20": [{"f1": .3}]},
    })
    assert response["status"] == 200
    assert response["body"]["bundle_id"] == bundle.bundle_id
    assert response["body"]["persisted"] is False
    assert response["body"]["model_adopted"] is False
    assert len(response["body"]["heads"]) == 4
    assert response["body"]["heads"][0]["values"] == [.01]
    assert database_contents() == before
    for content, rows in ((None, {}), (encoded(bundle), {"5": "bad", "20": []}),
                          (encoded(bundle), {"5": [{}] * 1001, "20": []})):
        assert run(device, "POST", "/api/v1/mobile/models/bundle/parity", {
            "content": content, "rows": rows,
        })["status"] == 422


def test_market_plan_and_unknown_holdings_survive_portable_backup(device):
    plan = {"first_day": "2026-01-01", "last_day": "2026-01-06"}
    assert run(device, "POST", "/api/v1/mobile/market/plan", plan)["body"] == plan
    selected = run(device, "GET", "/api/v1/mobile/market/universe")["body"]
    assert selected["holdings_recorded"] is False
    assert selected["blocking_reasons"] == ["twenty_sessions_required"]
    encoded = device.export_state()
    device.initialize(encoded)
    assert run(device, "GET", "/api/v1/mobile/market/plan")["body"] == plan
    assert run(device, "POST", "/api/v1/mobile/market/plan", {
        "first_day": "2026-01-06", "last_day": "2026-01-01"
    })["status"] == 422


def test_current_membership_survives_backup_without_replacing_canonical_history(device):
    from mobile.python import membership

    from tests.test_mobile_membership import CUTOFF, observation

    payload = observation()
    assert run(device, "POST", "/api/v1/mobile/market/membership", payload)["status"] == 200
    before = membership.snapshot(device.STATE / "mobile.sqlite3", CUTOFF)
    encoded = device.export_state()
    device.initialize(encoded)
    assert membership.snapshot(device.STATE / "mobile.sqlite3", CUTOFF) == before
    assert run(device, "GET", "/api/v1/mobile/market")["body"]["completed_dates"] == []


def test_unknown_manual_inputs_survive_restart_and_exact_backup(device):
    value = {
        "schema_version": "manual-portfolio-v1",
        "holdings_status": "none",
        "investment_budget_yen": None,
        "maximum_drawdown_percent": None,
        "accounts": [],
        "holdings": [],
    }
    assert run(device, "POST", "/api/v1/mobile/portfolio", value)["status"] == 200
    before = run(device, "GET", "/api/v1/mobile/portfolio")["body"]
    backup = device.export_state()
    device.initialize(backup)
    after = run(device, "GET", "/api/v1/mobile/portfolio")["body"]
    assert before == after
    assert after["portfolio"]["investment_budget_yen"] is None
    assert "apiKey" not in backup


def test_invalid_input_does_not_publish_revision(device):
    assert (
        run(device, "POST", "/api/v1/mobile/portfolio", {"api_key": "never-store"})["status"] == 422
    )
    assert run(device, "GET", "/api/v1/mobile/portfolio")["body"] is None


def test_core_views_work_in_embedded_dispatch(device):
    for name in ("status", "home", "today", "settings", "ranking", "validation", "notifications"):
        assert run(device, "GET", "/api/v1/" + name)["status"] == 200, name


def test_unadopted_model_cannot_be_imported_or_generate_forecast(device):
    assert run(device, "GET", "/api/v1/mobile/models")["body"]["approved_count"] == 0
    assert run(device, "POST", "/api/v1/mobile/models/import", {"content": "{}"})["status"] == 422
    assert run(device, "POST", "/api/v1/mobile/models/infer", {})["status"] == 422
    assert run(device, "GET", "/api/v1/daily/latest")["body"]["snapshot"] is None
