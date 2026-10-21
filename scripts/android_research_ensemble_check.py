"""Opt-in synthetic native ensemble proof on the existing disposable CI emulator.

Does not build, start, reset, install or clear a device. APKs must already be
installed by the guarded CI job. --prepare-only never invokes adb.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

from mobile.python.model_bundle import parity
from scripts.android_history_check import renderer_diagnostics
from scripts.android_lifecycle_check import PACKAGE, RUNNER, Controller

from stock_ai.operations.daily import PredictionSnapshot, canonical_json

ROOT = Path(__file__).resolve().parents[1]
CASE = "jp.stockai.app.ResearchEnsembleComputeTest"


def validate_apks(folder: Path, *, require_workflow_commit: bool) -> dict:
    folder = folder.resolve()
    if not folder.is_relative_to(ROOT / ".demo-artifacts"):
        raise ValueError("Use the already installed CI APKs under .demo-artifacts")
    paths = {
        "application": folder / "debug/app-debug.apk",
        "tests": folder / "androidTest/debug/app-debug-androidTest.apk",
    }
    digests = {}
    build = None
    for name, path in paths.items():
        if not path.is_file() or not path.resolve().is_relative_to(folder):
            raise ValueError("Both pinned application and instrumentation APKs are required")
        with path.open("rb") as source:
            digests[name] = hashlib.file_digest(source, "sha256").hexdigest()
        with zipfile.ZipFile(path) as archive:
            if any("research-ensemble-golden" in entry.lower() for entry in archive.namelist()):
                raise ValueError("Synthetic golden must be transferred separately from APKs")
            if name == "application":
                build = json.loads(archive.read("assets/public/python/build-info.json"))
    commit = build.get("source_commit") if isinstance(build, dict) else None
    if not commit or (
        require_workflow_commit
        and (not os.environ.get("GITHUB_SHA") or commit != os.environ["GITHUB_SHA"])
    ):
        raise ValueError("APK does not belong to this workflow source")
    return {"source_commit": commit, "apk_sha256": digests}


def validate_fixture(path: Path) -> tuple[dict, str]:
    path = path.resolve()
    if (
        not path.is_relative_to(ROOT / ".demo-artifacts")
        or not 0 < path.stat().st_size <= 512 * 1024
    ):
        raise ValueError("Use a bounded synthetic golden under .demo-artifacts")
    original = path.read_bytes()
    fixture = json.loads(original)
    if (
        fixture.get("schema_version") != "SYNTHETIC-research-ensemble-golden-v2"
        or any(
            fixture.get(k) is not True
            for k in ("synthetic_only", "no_market_data", "no_private_models")
        )
        or fixture.get("fitted_models") != 0
        or fixture.get("owner_approval_created") is not False
        or {v["name"] for v in fixture["variants"]} != {"rank_only", "return_and_rank"}
        or len(fixture["variants"]) != 2
        or set(fixture["rows"]) != {"5", "20"}
        or any(len(rows) != 27 for rows in fixture["rows"].values())
    ):
        raise ValueError("Not the bounded, unadopted synthetic ensemble golden")
    sources = sorted((ROOT / "artifacts/selections/goal3-features").glob("*/*.json"))
    if len(sources) != 1:
        raise ValueError("Exactly one frozen feature selection required")
    selection = json.loads(sources[0].read_text(encoding="utf-8"))["feature_selection"]
    for variant in fixture["variants"]:
        content = json.loads(variant["content"])
        if any(not c["model_id"].startswith("SYNTHETIC-") for c in content["components"]):
            raise ValueError("Never transfer private inference models as a test fixture")
        calculated = parity(
            variant["content"], fixture["rows"], selection, rank_universes=fixture["rank_universes"]
        )
        if json.loads(canonical_json(calculated)) != variant["expected"]:
            raise ValueError("PC reference differs from the current composition runtime")
        snapshot = PredictionSnapshot.model_validate(variant["snapshot"])
        if (
            snapshot.mode != "research"
            or snapshot.adoption_review_id is not None
            or snapshot.risk_available
            or snapshot.research_symbols() != tuple(variant["research_symbols"])
            or len(snapshot.predictions) != 27
            or len(snapshot.research_symbols()) != 22
        ):
            raise ValueError("Invalid synthetic snapshot population or approval")
        if any(
            p.downside_quantile is not None
            or p.large_loss_probability is not None
            or p.uncertainty is not None
            for p in snapshot.predictions
        ):
            raise ValueError("This fixture tests explicitly unavailable optional risk")
    return fixture, hashlib.sha256(original).hexdigest()


def validate_proof(proof: dict, fixture: dict, digest: str) -> None:
    if (
        proof.get("schema_version") != "synthetic-native-ensemble-proof-v1"
        or proof.get("synthetic_only") is not True
        or proof.get("actual_android_device") is not True
        or proof.get("xiaomi_verified") is not False
        or proof.get("model_adopted") is not False
        or proof.get("phase") != "verified"
        or proof.get("fixture_sha256") != digest
        or proof.get("sdk") != 35
        or proof.get("maximum_absolute_error") != 0
        or not 0 < proof.get("elapsed_seconds", 0) <= 600
        or proof.get("source_commit") != os.environ.get("GITHUB_SHA")
    ):
        raise ValueError("Native ensemble proof is incomplete or belongs to another source")
    variants = proof.get("variants", [])
    if len(variants) != 2 or {v["name"] for v in variants} != {"rank_only", "return_and_rank"}:
        raise ValueError("Both ensemble variants must complete")
    expected = {v["name"]: v for v in fixture["variants"]}
    for result in variants:
        if (
            result.get("basic_prediction_rows") != 216
            or result.get("symbols_per_horizon") != 27
            or result.get("bundle_sha256") != expected[result["name"]]["expected"]["sha256"]
            or result.get("top20_plus_all_holdings") != expected[result["name"]]["research_symbols"]
            or any(
                result.get(key) is not True
                for key in (
                    "exact_pc_match",
                    "partial_population_rejected",
                    "snapshot_restored_exactly",
                    "optional_risk_null",
                    "model_policy_unchanged",
                    "personal_state_unchanged",
                )
            )
        ):
            raise ValueError(
                "Native component, composition, population or restore check is missing"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--apks", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    options = parser.parse_args()
    if Path.cwd().resolve() != ROOT:
        raise ValueError("Run from the repository root")
    output = options.output.resolve()
    if (
        not output.is_relative_to(ROOT / ".demo-artifacts")
        or output == ROOT / ".demo-artifacts"
        or output.exists()
    ):
        raise ValueError("Use a new isolated .demo-artifacts evidence directory")
    fixture, digest = validate_fixture(options.fixture)
    if not options.prepare_only and options.apks is None:
        raise ValueError("Pass the same --apks directory installed by android_history_check")
    apk = (
        validate_apks(options.apks, require_workflow_commit=not options.prepare_only)
        if options.apks
        else {}
    )
    remote = f"/data/local/tmp/stockai-research-ensemble-{digest}.json"
    controller = Controller(output)
    instrument = [
        "shell",
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        CASE,
        "-e",
        "stockai.ensemble.confirm",
        "fresh-emulator-only",
        "-e",
        "stockai.ensemble.path",
        remote,
        "-e",
        "stockai.ensemble.sha256",
        digest,
        RUNNER,
    ]
    controller.report.update(
        schema_version="synthetic-native-ensemble-controller-v1",
        fixture_sha256=digest,
        actual_android_device=False,
        model_adopted=False,
        instrument_arguments=instrument,
    )
    controller.report.update(apk)
    if options.prepare_only:
        controller.report.update(status="prepared_not_executed", adb_invoked=False)
        (output / "report.json").write_text(canonical_json(controller.report), encoding="utf-8")
        print(canonical_json(controller.report))
        return
    try:
        # Existing CI-only/AVD-home/API35/qemu/primary-user guard. No device
        # install, reset or default-owner database access is added here.
        controller.guard()
        controller.adb("push", str(options.fixture.resolve()), remote, timeout=60)
        if controller.shell("sha256sum", remote).split()[0] != digest:
            raise ValueError("Synthetic fixture transfer changed")
        text = controller.adb(*instrument, timeout=660).decode(errors="replace")
        (output / "instrumentation.txt").write_text(text, encoding="utf-8")
        if "OK (1 test)" not in text or "FAILURES!!!" in text or "INSTRUMENTATION_FAILED" in text:
            raise RuntimeError("Native ensemble instrumentation did not pass")
        proof = json.loads(
            controller.adb(
                "exec-out",
                "run-as",
                PACKAGE,
                "cat",
                f"files/research-ensemble-proof-{digest}.json",
            )
        )
        validate_proof(proof, fixture, digest)
        if proof.get("source_commit") != apk["source_commit"]:
            raise ValueError("Installed application differs from the supplied APK source")
        if hashlib.sha256(options.fixture.read_bytes()).hexdigest() != digest:
            raise ValueError("Original synthetic golden changed")
        controller.report.update(
            status="passed", actual_android_device=True, native=proof, source_fixture_unchanged=True
        )
    except Exception as error:
        controller.report.update(status="failed", error_type=type(error).__name__, code=str(error))
        raise
    finally:
        if controller.guarded:
            try:
                if controller.report["status"] != "passed":
                    partial = controller.adb(
                        "exec-out",
                        "run-as",
                        PACKAGE,
                        "cat",
                        f"files/research-ensemble-proof-{digest}.json",
                        required=False,
                    )
                    if partial:
                        controller.report["partial_native"] = json.loads(partial)
                lines = controller.adb("logcat", "-d", "-v", "brief", required=False).decode(
                    errors="replace"
                )
                (output / "renderer-memory.txt").write_text(
                    renderer_diagnostics(lines), encoding="utf-8"
                )
            except Exception as diagnostic_error:
                controller.report["diagnostic_error_type"] = type(diagnostic_error).__name__
        (output / "report.json").write_text(canonical_json(controller.report), encoding="utf-8")


if __name__ == "__main__":
    main()
