from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from scripts.android_history_check import HistoryController, validate_fixture
from scripts.mobile_native_history_fixture import FORMAT, ROOT, isolated, prepare, table_snapshot


def test_table_proof_covers_schema_types_all_cells_and_input_immutability(tmp_path) -> None:
    path = tmp_path / "synthetic.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE one (value, other)")
        db.execute("INSERT INTO one VALUES(?,?)", (None, b"\x00\xff"))
        db.execute("INSERT INTO one VALUES(?,?)", (1, 1.25))
        db.execute("CREATE TABLE empty (value TEXT)")
    before = path.read_bytes()
    first = table_snapshot(path)
    assert path.read_bytes() == before
    assert first == table_snapshot(path)
    assert first["tables"]["one"]["rows"] == 2
    assert first["tables"]["empty"]["rows"] == 0
    with sqlite3.connect(path) as db:
        db.execute("UPDATE one SET value='1' WHERE rowid=2")
    second = table_snapshot(path)
    assert first["schema_sha256"] == second["schema_sha256"]
    assert first["tables"]["one"] != second["tables"]["one"]
    with sqlite3.connect(path) as db:
        db.execute("CREATE INDEX synthetic_index ON one(other)")
    third = table_snapshot(path)
    assert second["schema_sha256"] != third["schema_sha256"]
    assert second["tables"] == third["tables"]


def test_table_proof_uses_stable_cell_order_instead_of_implicit_rowids(tmp_path) -> None:
    path = tmp_path / "synthetic.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sample (key TEXT PRIMARY KEY, value BLOB)")
        db.executemany("INSERT INTO sample VALUES(?,?)", [("B", b"2"), ("A", b"1")])
    before = table_snapshot(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE sample SET rowid=rowid+20")
    assert table_snapshot(path) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("format", "foreign"),
        ("synthetic_only", False),
        ("status", "running"),
        ("symbols", 4999),
        ("sessions", 519),
        ("models", 1),
        ("characters", 0),
    ],
)
def test_native_fixture_rejects_incomplete_or_foreign_metadata_before_device_access(
    tmp_path,
    monkeypatch,
    field,
    value,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    report = {
        "format": FORMAT,
        "synthetic_only": True,
        "status": "passed",
        "symbols": 5000,
        "sessions": 520,
        "models": 0,
        "characters": 90_000_000,
    }
    report[field] = value
    (fixture / "report.json").write_text(json.dumps(report))
    monkeypatch.chdir(tmp_path)
    controller = HistoryController(tmp_path / "evidence")
    monkeypatch.setattr(controller, "guard", lambda: pytest.fail("device guard called too early"))
    with pytest.raises(ValueError, match="Invalid synthetic"):
        controller.run_history(fixture, tmp_path / "no-apks")
    assert not controller.guarded
    with pytest.raises(ValueError, match="Invalid synthetic"):
        validate_fixture(fixture)


def test_native_stream_requires_the_existing_disposable_device_guard(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    controller = HistoryController(tmp_path / "evidence")
    with pytest.raises(RuntimeError, match="guard is required"):
        controller.stream(["shell", "never-run"])
    with pytest.raises(RuntimeError, match="restricted to GitHub CI"):
        controller.guard()


def test_native_fixture_preparation_refuses_paths_outside_isolated_workspace() -> None:
    # CI deliberately places pytest's basetemp inside .demo-artifacts.
    outside = ROOT.parent / "stockai-native-outside-isolated-test"
    with pytest.raises(ValueError, match="isolated"):
        isolated(outside)
    with pytest.raises(ValueError, match="isolated"):
        prepare(outside, Path("."))
    with pytest.raises(ValueError, match="isolated"):
        isolated(ROOT / ".demo-artifacts")
    inside = ROOT / ".demo-artifacts/native-path-contract-only"
    assert isolated(inside) == inside.resolve()


def test_native_fixture_rejects_arbitrary_source_paths_without_reading_payload(tmp_path) -> None:
    report = {
        "format": FORMAT,
        "synthetic_only": True,
        "status": "passed",
        "symbols": 5000,
        "sessions": 520,
        "models": 0,
        "characters": 90_000_000,
        "mobile": {"tables": {str(index): {} for index in range(17)}},
        "source_sha256": {"../../outside": "0" * 64},
    }
    (tmp_path / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Invalid synthetic"):
        validate_fixture(tmp_path)


def test_renderer_diagnostics_keep_fixed_stages_and_system_memory_events_only() -> None:
    from scripts.android_history_check import renderer_diagnostics

    phase = "I/StockAIComputeStage( 123): phase=state java_used=100 available=200 low_memory=false"
    killed = (
        "I/lmkd( 12): Killing 'com.android.webview:sandboxed_process0' (123), oom_score_adj=900"
    )
    output = "\n".join([
        phase, killed,
        'I/chromium(123): [INFO:CONSOLE] "private account out of memory"',
        "I/StockAIComputeStage(123): phase=private-account",
        "I/StockAI(123): private-account",
    ])
    assert renderer_diagnostics(output).splitlines() == [phase, killed]
    assert len(renderer_diagnostics("\n".join([phase] * 501)).splitlines()) == 500


@pytest.mark.parametrize("changed", [
    {"portable_backup": None}, {"portable_backup": {}}, {"phase": "initializing-owner"},
    {"max_java_heap_bytes": 193 * 1024 * 1024}, {"characters": 1},
    {"portable_backup": {"status": "exported"}},
    {"portable_backup": {"native_preview_payload_absent": False}},
    {"portable_backup": {"profile_recovered": False}},
    {"portable_backup": {"envelope_bytes": 128 * 1024 * 1024 + 1}},
])
def test_native_full_history_requires_portable_restore_evidence(changed) -> None:
    from scripts.android_history_check import validate_native_evidence

    evidence = {
        "synthetic_only": True, "phase": "verified", "characters": 96_781_956,
        "max_java_heap_bytes": 192 * 1024 * 1024,
        "portable_backup": {
            "format": "STOCKAIB1", "status": "restored", "characters": 96_781_956,
            "envelope_bytes": 96_782_100, "native_preview_payload_absent": True,
            "profile_recovered": True,
        },
    }
    validate_native_evidence(evidence, 96_781_956)
    for key, value in changed.items():
        if key == "portable_backup" and value:
            evidence[key].update(value)
        else:
            evidence[key] = value
    with pytest.raises(ValueError, match="evidence"):
        validate_native_evidence(evidence, 96_781_956)
