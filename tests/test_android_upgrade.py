"""Legacy source fixture and controller proofs; actual device proof is separate."""

import base64
import io
import json
import os
import sqlite3
import subprocess
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from mobile.python import personal, runtime
from scripts.android_upgrade_check import (
    CURRENT_VERSION,
    FIXTURE,
    PINS,
    UpgradeController,
    fixture_bytes,
    prepare_base,
    verify_capsule,
)


@pytest.fixture
def legacy():
    return fixture_bytes(FIXTURE.read_bytes())


def test_failed_upgrade_instrumentation_keeps_diagnostics_and_fails(tmp_path, monkeypatch, capsys):
    controller = UpgradeController(tmp_path / "evidence")
    controller.guarded = True
    monkeypatch.setattr(
        controller, "shell", lambda *args, **kwargs: "FAILURES!!!\nsynthetic failure"
    )
    with pytest.raises(RuntimeError, match="instrumentation did not pass"):
        controller.instrument_upgrade("SyntheticTest", "verify", "verify")
    assert (controller.output / "verify.txt").read_text(
        encoding="utf-8"
    ) == "FAILURES!!!\nsynthetic failure"
    assert "Upgrade phase verify instrumentation output" in capsys.readouterr().out


@pytest.fixture
def migrated(legacy, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "STATE", tmp_path / "state")
    runtime.initialize(legacy["payload"])
    return legacy, runtime.STATE


def test_exact_legacy_fixture_restores_all_typed_rows_settings_and_applied_fills(
    migrated,
    tmp_path,
    monkeypatch,
):
    legacy, _ = migrated
    store = runtime._app.state.store
    store.verify_integrity()
    assert personal.portfolio_view(store) == legacy["profile"]
    assert personal.settings_view(store) == legacy["settings"]
    assert store.latest_portfolio().applied_execution_ids == (legacy["applied_execution_id"],)
    assert len(store.executions()) == 1
    payload = runtime.export_state().encode("ascii")
    before = verify_capsule(payload, legacy, tmp_path / "first-proof")
    monkeypatch.setattr(runtime, "STATE", tmp_path / "reopened")
    runtime.initialize(payload.decode("ascii"))
    assert (
        verify_capsule(runtime.export_state().encode("ascii"), legacy, tmp_path / "reopen-proof")
        == before
    )
    assert len(runtime._app.state.store.executions()) == 1
    assert fixture_bytes(FIXTURE.read_bytes()) == legacy


@pytest.mark.parametrize(
    "column,value",
    [
        ("i", 18),
        ("f", 0.25),
        ("s", "changed"),
        ("b", b"changed"),
        ("n", "null is not text"),
    ],
)
def test_same_counts_with_changed_typed_cells_never_count_as_preserved(
    migrated,
    tmp_path,
    column,
    value,
):
    legacy, state = migrated
    with closing(sqlite3.connect(state / "mobile.sqlite3")) as db:
        db.execute(f'UPDATE TEST_ONLY_upgrade_typed_cells SET "{column}"=?', (value,))
        db.commit()
    with pytest.raises(ValueError, match="typed cells"):
        verify_capsule(runtime.export_state().encode("ascii"), legacy, tmp_path / "changed")


def test_schema_changes_and_automatic_records_are_not_accepted(migrated, tmp_path):
    legacy, state = migrated
    with closing(sqlite3.connect(state / "mobile.sqlite3")) as db:
        db.execute("ALTER TABLE TEST_ONLY_upgrade_typed_cells RENAME COLUMN s TO renamed")
        db.commit()
    with pytest.raises(ValueError, match=r"schema objects|columns"):
        verify_capsule(runtime.export_state().encode("ascii"), legacy, tmp_path / "schema")
    with closing(sqlite3.connect(state / "mobile.sqlite3")) as db:
        db.execute("ALTER TABLE TEST_ONLY_upgrade_typed_cells RENAME COLUMN renamed TO s")
        db.execute("CREATE TABLE unexpected_auto_records(value TEXT)")
        db.execute("INSERT INTO unexpected_auto_records VALUES('not a reviewed migration')")
        db.commit()
    with pytest.raises(ValueError, match="Unexpected new tables"):
        verify_capsule(runtime.export_state().encode("ascii"), legacy, tmp_path / "unexpected")


@pytest.mark.parametrize("column", ["decision_id", "content_hash", "payload"])
def test_nonempty_execution_migration_still_rejects_changed_legacy_cells(
    migrated, tmp_path, column
):
    legacy, state = migrated
    with closing(sqlite3.connect(state / "operations.sqlite3")) as db:
        db.execute(f'UPDATE executions SET "{column}"=?', ("synthetic-tampering",))
        db.commit()
    with pytest.raises(ValueError, match="typed cells"):
        verify_capsule(
            runtime.export_state().encode("ascii"), legacy, tmp_path / "executions-changed"
        )


def test_nonempty_execution_migration_rejects_unreviewed_schema_changes(migrated, tmp_path):
    legacy, state = migrated
    with closing(sqlite3.connect(state / "operations.sqlite3")) as db:
        db.execute("ALTER TABLE executions RENAME COLUMN decision_id TO changed_decision")
        db.commit()
    with pytest.raises(ValueError, match=r"schema objects|columns"):
        verify_capsule(
            runtime.export_state().encode("ascii"), legacy, tmp_path / "executions-schema"
        )


def test_new_reference_runs_must_be_empty_and_match_reviewed_schema(migrated, tmp_path):
    legacy, state = migrated
    with closing(sqlite3.connect(state / "mobile.sqlite3")) as db:
        db.execute("INSERT INTO mobile_reference_runs VALUES (1,'test','test','{}','test','test')")
        db.commit()
    with pytest.raises(ValueError, match="automatic records"):
        verify_capsule(runtime.export_state().encode("ascii"), legacy, tmp_path / "reference-data")
    with closing(sqlite3.connect(state / "mobile.sqlite3")) as db:
        db.execute("DELETE FROM mobile_reference_runs")
        db.execute("ALTER TABLE mobile_reference_runs ADD COLUMN unexpected TEXT")
        db.commit()
    with pytest.raises(ValueError, match=r"reference run schema|reference run columns"):
        verify_capsule(
            runtime.export_state().encode("ascii"), legacy, tmp_path / "reference-schema"
        )


def test_already_migrated_execution_layout_and_rows_survive_reopen(migrated, tmp_path, monkeypatch):
    _, state = migrated
    with closing(sqlite3.connect(state / "operations.sqlite3")) as db:
        db.execute(
            "CREATE TABLE executions_previous (execution_id TEXT PRIMARY KEY, "
            "decision_id TEXT, executed_at TEXT NOT NULL, payload TEXT NOT NULL, "
            "content_hash TEXT NOT NULL, "
            "FOREIGN KEY(decision_id) REFERENCES user_decisions(decision_id))"
        )
        db.execute(
            "INSERT INTO executions_previous SELECT "
            "execution_id,decision_id,executed_at,payload,content_hash FROM executions"
        )
        db.execute("DROP TABLE executions")
        db.execute("ALTER TABLE executions_previous RENAME TO executions")
        db.commit()
        original_columns = list(db.execute("PRAGMA table_info(executions)"))
        original_rows = list(db.execute("SELECT * FROM executions ORDER BY execution_id"))
    payload = runtime.export_state()
    monkeypatch.setattr(runtime, "STATE", tmp_path / "previous-layout-reopened")
    runtime.initialize(payload)
    runtime._app.state.store.verify_integrity()
    with closing(sqlite3.connect(runtime.STATE / "operations.sqlite3")) as db:
        assert list(db.execute("PRAGMA table_info(executions)")) == original_columns
        assert list(db.execute("SELECT * FROM executions ORDER BY execution_id")) == original_rows


def test_unpinned_or_non_synthetic_fixture_cannot_reach_a_device(tmp_path, monkeypatch):
    encoded = FIXTURE.read_bytes()
    with pytest.raises(ValueError, match="fixture bytes changed"):
        fixture_bytes(encoded + b" ")
    pins = json.loads(PINS.read_text())
    value = json.loads(encoded)
    value["models"] = 1
    revised = json.dumps(value).encode()
    import scripts.android_upgrade_check as module

    pins["fixture_sha256"] = module.digest(revised)
    path = tmp_path / "pins.json"
    path.write_text(json.dumps(pins))
    monkeypatch.setattr(module, "PINS", path)
    with pytest.raises(ValueError, match="Invalid synthetic"):
        fixture_bytes(revised)


@pytest.mark.parametrize("column", ["sequence", "valuation_sequence"])
def test_new_technical_cursor_cannot_create_unreviewed_progress(migrated, tmp_path, column):
    legacy, _ = migrated
    source = runtime.export_state()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(source))) as original:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as revised:
            for name in original.namelist():
                data = original.read(name)
                if name == "mobile.sqlite3":
                    with closing(sqlite3.connect(":memory:")) as db:
                        db.deserialize(data)
                        db.execute(f'UPDATE market_compaction SET "{column}"=1')
                        db.commit()
                        data = db.serialize()
                revised.writestr(name, data)
    with pytest.raises(ValueError, match="automatic records"):
        verify_capsule(base64.b64encode(output.getvalue()), legacy, tmp_path / "cursor")


def apk(path, commit, *, fixture=False):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "assets/public/python/build-info.json", json.dumps({"source_commit": commit})
        )
        if fixture:
            archive.writestr("assets/legacy-upgrade.json", FIXTURE.read_bytes())
    return path


def test_replacement_failure_never_clears_or_reinstalls_the_prepared_state(
    legacy,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("GITHUB_SHA", "TEST_ONLY-CURRENT")
    base = apk(tmp_path / "base.apk", legacy["source_commit"])
    current = apk(tmp_path / "current.apk", "TEST_ONLY-CURRENT")
    tests = apk(tmp_path / "tests.apk", None, fixture=True)
    controller = UpgradeController(tmp_path / "evidence")
    calls = []

    def guarded():
        controller.guarded = True

    def adb(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("install", "-r"):
            raise RuntimeError("TEST_ONLY replacement rejected")
        return b"Success"

    prepared = {
        "version_code": 10012,
        "phase": "legacy-seeded",
        "generation": 1,
        "uid": 12345,
        "signature_sha256": "TEST_ONLY",
    }
    monkeypatch.setattr(controller, "guard", guarded)
    monkeypatch.setattr(controller, "adb", adb)
    monkeypatch.setattr(controller, "instrument_upgrade", lambda *args: prepared)
    with pytest.raises(RuntimeError, match="replacement rejected"):
        controller.run_upgrade(base, current, tests)
    assert [args[0] for args in calls].count("uninstall") == 2
    assert [args for args in calls if args[:2] == ("install", "-r")] == [
        ("install", "-r", "-t", str(current))
    ]
    assert all("clear" not in args for args in calls)
    assert controller.report["status"] == "running"  # Never claims success after failure.


def test_changed_identity_or_generation_fails_without_a_reset(legacy, tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "TEST_ONLY-CURRENT")
    paths = [
        apk(tmp_path / "base.apk", legacy["source_commit"]),
        apk(tmp_path / "current.apk", "TEST_ONLY-CURRENT"),
        apk(tmp_path / "tests.apk", None, fixture=True),
    ]
    controller = UpgradeController(tmp_path / "proof")
    calls = []
    monkeypatch.setattr(controller, "guard", lambda: setattr(controller, "guarded", True))
    monkeypatch.setattr(controller, "adb", lambda *args, **kwargs: calls.append(args) or b"Success")
    prepared = {
        "version_code": 10012,
        "phase": "legacy-seeded",
        "generation": 1,
        "uid": 12345,
        "signature_sha256": "TEST_ONLY",
    }
    changed = {
        **prepared,
        "version_code": CURRENT_VERSION,
        "phase": "verify",
        "uid": 99999,
        "generation": 2,
        "credential_retained": True,
    }
    markers = iter([prepared, changed])
    monkeypatch.setattr(controller, "instrument_upgrade", lambda *args: next(markers))
    with pytest.raises(ValueError, match="identity, generation"):
        controller.run_upgrade(*paths)
    assert sum(args[0] == "uninstall" for args in calls) == 2
    assert controller.report["status"] != "passed"


def test_leaked_fixture_or_non_ci_device_refused_before_any_install(legacy, tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GITHUB_SHA", "TEST_ONLY-CURRENT")
    base = apk(tmp_path / "base.apk", legacy["source_commit"])
    current = apk(tmp_path / "current.apk", "TEST_ONLY-CURRENT", fixture=True)
    tests = apk(tmp_path / "tests.apk", None, fixture=True)
    controller = UpgradeController(tmp_path / "evidence")
    monkeypatch.setattr(controller, "adb", lambda *args, **kwargs: pytest.fail("device accessed"))
    with pytest.raises(ValueError, match="leaked"):
        controller.run_upgrade(base, current, tests)
    current = apk(current, "TEST_ONLY-CURRENT")
    with pytest.raises(RuntimeError, match="restricted to GitHub CI"):
        controller.run_upgrade(base, current, tests)


def test_legacy_export_and_capsule_paths_never_overwrite_existing_state(tmp_path, legacy):
    with pytest.raises(ValueError, match="isolated"):
        prepare_base(Path.cwd().parent / "outside-upgrade")
    with pytest.raises(ValueError, match="overwrite"):
        prepare_base(tmp_path)
    with pytest.raises(ValueError, match="fresh"):
        verify_capsule(legacy["payload"].encode(), legacy, tmp_path)
    value = io.BytesIO()
    with zipfile.ZipFile(value, "w") as archive:
        archive.writestr("../operations.sqlite3", b"test")
    with pytest.raises(ValueError, match="database names"):
        verify_capsule(base64.b64encode(value.getvalue()), legacy, tmp_path / "bad-members")


def test_legacy_archive_has_git_blob_bytes_under_both_checkout_line_endings(tmp_path, monkeypatch):
    from scripts.android_upgrade_check import ROOT, digest

    pins = json.loads(PINS.read_text())
    for name, expected in pins["source_sha256"].items():
        original = subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=" + ROOT.as_posix(),
                "show",
                pins["source_commit"] + ":" + name,
            ],
            cwd=ROOT,
        )
        assert digest(original) == expected, name
    receipts = []
    count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    for index, (autocrlf, eol) in enumerate((("true", "crlf"), ("false", "lf"))):
        monkeypatch.setenv("GIT_CONFIG_COUNT", str(count + 2))
        for offset, (key, value) in enumerate((("core.autocrlf", autocrlf), ("core.eol", eol))):
            monkeypatch.setenv(f"GIT_CONFIG_KEY_{count + offset}", key)
            monkeypatch.setenv(f"GIT_CONFIG_VALUE_{count + offset}", value)
        receipts.append(prepare_base(tmp_path / f"source-{index}"))
    assert receipts[0] == receipts[1]
