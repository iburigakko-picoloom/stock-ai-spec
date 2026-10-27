"""Last-published-source debug APK -> current APK on the guarded disposable AVD.

Only metadata is uploaded. The fixture, capsules and databases are synthetic and
remain local to the test runner. Release signatures and Xiaomi remain separate.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import zipfile
from contextlib import closing
from pathlib import Path

from scripts.android_lifecycle_check import PACKAGE, RUNNER, Controller
from scripts.sqlite_evidence import table_snapshot

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "scripts/fixtures/android-upgrade-source.json"
FIXTURE = ROOT / "web/android/app/src/androidTest/assets/legacy-upgrade.json"
CURRENT_VERSION = 20000
# The manual-execution migration only makes decision_id optional. It preserves
# the original column order, every legacy row, and the original foreign key.
EXECUTIONS_OPTIONAL_SCHEMA = [
    "table",
    "executions",
    "executions",
    'CREATE TABLE "executions" (execution_id TEXT PRIMARY KEY, '
    "decision_id TEXT, executed_at TEXT NOT NULL, content_hash TEXT NOT NULL, "
    "payload TEXT NOT NULL, FOREIGN KEY(decision_id) REFERENCES user_decisions(decision_id))",
]
EXECUTIONS_OPTIONAL_COLUMNS = [
    [0, "execution_id", "TEXT", 0, None, 1],
    [1, "decision_id", "TEXT", 0, None, 0],
    [2, "executed_at", "TEXT", 1, None, 0],
    [3, "content_hash", "TEXT", 1, None, 0],
    [4, "payload", "TEXT", 1, None, 0],
]
REFERENCE_RUNS_SCHEMA = [
    "table",
    "mobile_reference_runs",
    "mobile_reference_runs",
    "CREATE TABLE mobile_reference_runs(sequence INTEGER PRIMARY KEY,run_id TEXT NOT NULL UNIQUE,"
    "scope_hash TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,"
    "content_hash TEXT NOT NULL,phase TEXT NOT NULL)",
]
REFERENCE_RUNS_COLUMNS = [
    [0, "sequence", "INTEGER", 0, None, 1],
    [1, "run_id", "TEXT", 1, None, 0],
    [2, "scope_hash", "TEXT", 1, None, 0],
    [3, "payload", "TEXT", 1, None, 0],
    [4, "content_hash", "TEXT", 1, None, 0],
    [5, "phase", "TEXT", 1, None, 0],
]


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fixture_bytes(encoded: bytes) -> dict:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    if len(encoded) > 2 * 1024**2 or digest(encoded) != pins["fixture_sha256"]:
        raise ValueError("Upgrade test fixture bytes changed")
    value = json.loads(encoded)
    if (
        value.get("format") != "legacy-android-upgrade-fixture-v1"
        or value.get("synthetic_only") is not True
        or value.get("no_market_data") is not True
        or value.get("models") != 0
        or value.get("source_commit") != pins["source_commit"]
        or value.get("source_sha256") != pins["source_sha256"]
        or not 3 * 256 * 1024 < value.get("characters", 0) < 4 * 1024**2
        or len(value["payload"]) != value["characters"]
        or digest(value["payload"].encode("ascii")) != value["payload_sha256"]
    ):
        raise ValueError("Invalid synthetic legacy upgrade fixture")
    return value


def isolated(path: Path) -> Path:
    result = path.resolve()
    if not result.is_relative_to(ROOT / ".demo-artifacts") or result == ROOT / ".demo-artifacts":
        raise ValueError("Use an isolated .demo-artifacts directory")
    return result


def prepare_base(destination: Path) -> dict:
    destination = isolated(destination)
    if destination.exists():
        raise ValueError("Refusing to overwrite an existing legacy source directory")
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    encoded = subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=" + ROOT.as_posix(),
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "archive",
            "--format=zip",
            pins["source_commit"],
            "src",
            "mobile",
            "web",
            "scripts",
            "pyproject.toml",
            "uv.lock",
            "artifacts/selections/goal3-features",
        ],
        cwd=ROOT,
    )
    destination.mkdir(parents=True)
    exported_files = {}
    with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
        for info in archive.infolist():
            path = (destination / info.filename).resolve()
            if (
                not path.is_relative_to(destination)
                or (info.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("Unsafe legacy archive member")
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    content = archive.read(info)
                    stream.write(content)
                    exported_files[info.filename] = digest(content)
    for name, expected in pins["source_sha256"].items():
        if digest((destination / name).read_bytes()) != expected:
            raise ValueError("Pinned legacy source differs: " + name)
    result = {
        "source_commit": pins["source_commit"],
        "archive_sha256": digest(encoded),
        "source_sha256": pins["source_sha256"],
        "files_sha256": exported_files,
    }
    (destination / "upgrade-source.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def verify_capsule(payload: bytes, fixture: dict, destination: Path) -> dict:
    """Read the native-exported files directly; do not repair them with initialize."""
    destination = isolated(destination)
    if destination.exists() or not 0 < len(payload) < 4 * 1024**2:
        raise ValueError("Use fresh, bounded capsule evidence")
    encoded = base64.b64decode(payload, validate=True)
    destination.mkdir(parents=True)
    result = {}
    with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
        names = [info.filename for info in archive.infolist()]
        if sorted(names) != ["mobile.sqlite3", "operations.sqlite3"]:
            raise ValueError("Upgrade capsule database names differ")
        for info in archive.infolist():
            if info.file_size > 16 * 1024**2:
                raise ValueError("Upgrade capsule database is too large")
            path = destination / info.filename
            with path.open("xb") as stream:
                stream.write(archive.read(info))
            actual = table_snapshot(path)
            expected = fixture["legacy_tables"][info.filename]["tables"]
            migrations = fixture["empty_table_schema_migrations"][info.filename]
            if any(expected[name]["rows"] != 0 for name in migrations):
                raise ValueError("This reviewed schema migration covers only empty legacy tables")
            if any(actual["tables"].get(name) != proof for name, proof in expected.items()):
                raise ValueError("A legacy table's typed cells changed")
            added = set(actual["tables"]) - set(expected)
            allowed_added = set(fixture["known_new_tables"][info.filename])
            if info.filename == "mobile.sqlite3":
                allowed_added.add("mobile_reference_runs")
            if added != allowed_added or any(
                actual["tables"][name]
                != fixture["new_table_initial_rows"][info.filename].get(
                    name, {"rows": 0, "typed_cells_sha256": digest(b"")}
                )
                for name in added
            ):
                raise ValueError("Unexpected new tables or automatic records after upgrade")
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                actual_schema = {
                    (row[0], row[1]): list(row)
                    for row in db.execute(
                        "SELECT type,name,tbl_name,sql FROM sqlite_master "
                        "WHERE name NOT LIKE 'sqlite_%'"
                    )
                }
                if info.filename == "mobile.sqlite3":
                    if (
                        actual_schema.get(("table", "mobile_reference_runs"))
                        != REFERENCE_RUNS_SCHEMA
                    ):
                        raise ValueError("Reviewed reference run schema changed")
                    if [
                        list(row) for row in db.execute("PRAGMA table_info(mobile_reference_runs)")
                    ] != REFERENCE_RUNS_COLUMNS:
                        raise ValueError("Reviewed reference run columns changed")
                for row in fixture["legacy_schema"][info.filename]:
                    if info.filename == "operations.sqlite3" and row[:2] == ["table", "executions"]:
                        expected_schema = EXECUTIONS_OPTIONAL_SCHEMA
                    elif row[0] == "table" and row[1] in migrations:
                        expected_schema = migrations[row[1]]["schema"]
                    else:
                        expected_schema = row
                    if actual_schema.get((row[0], row[1])) != expected_schema:
                        raise ValueError("Legacy schema objects changed")
                for table, columns in fixture["legacy_columns"][info.filename].items():
                    quoted = '"' + table.replace('"', '""') + '"'
                    if info.filename == "operations.sqlite3" and table == "executions":
                        expected_columns = EXECUTIONS_OPTIONAL_COLUMNS
                    else:
                        expected_columns = (
                            migrations[table]["columns"] if table in migrations else columns
                        )
                    if [
                        list(row) for row in db.execute(f"PRAGMA table_info({quoted})")
                    ] != expected_columns:
                        raise ValueError("Legacy table columns changed")
            result[info.filename] = actual
    return result


class UpgradeController(Controller):
    def instrument_upgrade(self, case: str, method: str, phase: str) -> dict:
        if not self.guarded:
            raise RuntimeError("Disposable emulator guard is required")
        result = self.shell(
            "am",
            "instrument",
            "-w",
            "-e",
            "class",
            case + "#" + method,
            "-e",
            "stockai.upgrade.confirm",
            "fresh-emulator-only",
            RUNNER,
            timeout=300,
        )
        (self.output / f"{phase}.txt").write_text(result, encoding="utf-8")
        if (
            "OK (1 test)" not in result
            or "FAILURES!!!" in result
            or "INSTRUMENTATION_FAILED" in result
        ):
            # The guarded emulator contains synthetic data only. Surface the
            # failing instrumentation output even if artifact upload fails.
            print(f"Upgrade phase {phase} instrumentation output:\n{result}")
            raise RuntimeError("Upgrade instrumentation did not pass")
        marker = self.adb("exec-out", "run-as", PACKAGE, "cat", "files/upgrade-proof.json")
        return json.loads(marker)

    def run_upgrade(self, base: Path, current: Path, tests: Path) -> dict:
        original = fixture_bytes(FIXTURE.read_bytes())
        expected_old = json.loads(PINS.read_text(encoding="utf-8"))["published_version_code"]
        paths = {"legacy": base, "current": current, "tests": tests}
        for name, path in paths.items():
            with zipfile.ZipFile(path) as archive:
                if name == "tests":
                    if archive.read("assets/legacy-upgrade.json") != FIXTURE.read_bytes():
                        raise ValueError("Instrumentation APK fixture differs")
                else:
                    if "assets/legacy-upgrade.json" in archive.namelist():
                        raise ValueError("Test fixture leaked into the application APK")
                    build = json.loads(archive.read("assets/public/python/build-info.json"))
                    commit = (
                        original["source_commit"]
                        if name == "legacy"
                        else os.environ.get("GITHUB_SHA")
                    )
                    if not commit or build["source_commit"] != commit:
                        raise ValueError("Upgrade APK source identity differs")
        self.guard()
        self.report = {
            "synthetic_only": True,
            "status": "running",
            "phases": [],
            "scope": "same debug signature upgrade on an emulator; release/Xiaomi unverified",
            "legacy_source_commit": original["source_commit"],
            "current_source_commit": os.environ["GITHUB_SHA"],
            "apk_sha256": {name: digest(path.read_bytes()) for name, path in paths.items()},
        }
        # Reset only before preparing the legacy state. No uninstall/clear is
        # permitted after this point; a failed replacement must remain a failure.
        self.adb("uninstall", PACKAGE + ".test", required=False)
        self.adb("uninstall", PACKAGE, required=False)
        self.adb("install", "-t", str(base), timeout=120)
        self.adb("install", "-t", str(tests), timeout=120)
        prepared = self.instrument_upgrade(
            "jp.stockai.app.LegacyUpgradeSeedTest", "seed", "legacy-seed"
        )
        if prepared.get("version_code") != expected_old or prepared.get("phase") != "legacy-seeded":
            raise ValueError("Legacy package was not seeded")
        self.report["phases"].append(prepared)
        self.shell("am", "force-stop", PACKAGE)
        self.adb("install", "-r", "-t", str(current), timeout=120)
        previous = prepared
        for phase in ["verify", "reopen"]:
            proof = self.instrument_upgrade("jp.stockai.app.UpgradeCompatibilityTest", phase, phase)
            if (
                proof.get("version_code") != CURRENT_VERSION
                or proof.get("phase") != phase
                or proof.get("uid") != prepared["uid"]
                or proof.get("signature_sha256") != prepared["signature_sha256"]
                or proof.get("generation") != previous["generation"] + 1
                or proof.get("credential_retained") is not True
            ):
                raise ValueError("Package identity, generation or retained key changed")
            payload = self.adb("exec-out", "run-as", PACKAGE, "cat", "files/upgrade-export.b64")
            if (
                len(payload) != proof["export_characters"]
                or digest(payload) != proof["export_sha256"]
            ):
                raise ValueError("Native exported upgrade state changed")
            tables = verify_capsule(payload, original, self.output / (phase + "-decoded"))
            self.report["phases"].append({**proof, "tables": tables})
            previous = proof
            self.shell("am", "force-stop", PACKAGE)
        self.report["status"] = "passed"
        self.write_upgrade_report()
        return self.report

    def write_upgrade_report(self) -> None:
        (self.output / "upgrade-report.json").write_text(
            json.dumps(self.report, indent=2), encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-base", type=Path)
    parser.add_argument("--base-apk", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".demo-artifacts/android-upgrade"))
    args = parser.parse_args()
    if args.prepare_base is not None:
        result = prepare_base(args.prepare_base)
        print(
            json.dumps(
                {
                    "source_commit": result["source_commit"],
                    "archive_sha256": result["archive_sha256"],
                    "verified_files": len(result["files_sha256"]),
                }
            )
        )
        return
    if args.base_apk is None:
        parser.error("--base-apk is required for the guarded device test")
    controller = UpgradeController(isolated(args.output))
    try:
        apks = ROOT / "web/android/app/build/outputs/apk"
        controller.run_upgrade(
            args.base_apk,
            apks / "debug/app-debug.apk",
            apks / "androidTest/debug/app-debug-androidTest.apk",
        )
    except Exception:
        controller.report["status"] = "failed"
        controller.write_upgrade_report()
        raise


if __name__ == "__main__":
    main()
