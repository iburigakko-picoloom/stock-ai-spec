"""Explicit CPU checkpoint reuse across a reviewed, value-preserving code change.

This bridge accepts identical input/config identities only. It does not remap datasets,
approve GPU/thread changes, modify source artifacts, or declare formal adoption.
"""

from __future__ import annotations

import ast
import json
import math
import os
import sqlite3
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from importlib.metadata import version
from pathlib import Path
from typing import Any

import optuna
import pandas as pd

from stock_ai.ml.checkpoint import (
    ResearchCheckpointStore,
    _authenticate_metadata,
    _file_sha256,
    _load_json,
    _metadata_hash,
    checkpoint_id_for_provenance,
    stable_hash,
)

_PROOF_SCHEMA = "stock-ai-memory-equivalence-v1"
_LINEAGE_SCHEMA = "stock-ai-fold-import-v1"
_STUDY_LINEAGE_SCHEMA = "stock-ai-optuna-import-v1"
_ALLOWED_CHANGED = frozenset(
    {
        "_split_research_stages",
        "_run_advanced_research",
        "generate_oof_predictions",
        "oos_permutation_diagnostics",
        "bounded_optuna_search",
        "run_advanced_research",
    }
)
_ALLOWED_ADDED = frozenset(
    {
        "_select_rows_columnwise",
        "_take_rows_columnwise",
        "_prepare_fold_rows",
    }
)
_RUNTIME_PACKAGES = (
    "catboost",
    "lightgbm",
    "xgboost",
    "numpy",
    "pandas",
    "pyarrow",
    "optuna",
    "scikit-learn",
)


def _same_research_identity(source: Mapping[str, object], target: Mapping[str, object]) -> None:
    source_commit, target_commit = source.get("code_commit"), target.get("code_commit")
    for commit in (source_commit, target_commit):
        if (
            not isinstance(commit, str)
            or len(commit) != 40
            or any(char not in "0123456789abcdef" for char in commit)
        ):
            raise RuntimeError("checkpoint import requires explicit Git commit identities")
    if source_commit == target_commit:
        raise RuntimeError("cross-code import must use a different destination commit")
    if {key: value for key, value in source.items() if key != "code_commit"} != {
        key: value for key, value in target.items() if key != "code_commit"
    }:
        raise RuntimeError("checkpoint import changes data, feature order or research config")
    if source.get("locked_holdout_accessed") is not False:
        raise RuntimeError("checkpoint import requires unopened holdout")


def _definition_hashes(path: Path) -> tuple[dict[str, str], list[str], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    definitions: dict[str, str] = {}
    imports: list[str] = []
    other: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = stable_hash(ast.dump(node, include_attributes=False))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.dump(node, include_attributes=False))
        else:
            other.append(ast.dump(node, include_attributes=False))
    return definitions, imports, other


def create_memory_equivalence_proof(
    *,
    source_checkpoint: Path,
    destination_provenance: Mapping[str, object],
    source_model_code: Path,
    destination_model_code: Path,
    source_lock: Path,
    destination_lock: Path,
    passing_fixture_reports: Sequence[Path],
) -> dict[str, object]:
    """Record reviewed code scope, unchanged lock/runtime and successful fixture evidence."""

    namespace = _load_json(source_checkpoint / "manifest.json", description="source checkpoint")
    _authenticate_metadata(namespace, description="source checkpoint")
    source_provenance = namespace.get("provenance")
    if not isinstance(source_provenance, dict):
        raise RuntimeError("source checkpoint provenance is invalid")
    if namespace.get("checkpoint_id") != checkpoint_id_for_provenance(source_provenance):
        raise RuntimeError("source checkpoint namespace identity mismatch")
    if source_checkpoint.name != namespace["checkpoint_id"]:
        raise RuntimeError("source checkpoint directory identity mismatch")
    _same_research_identity(source_provenance, destination_provenance)
    old, old_imports, old_other = _definition_hashes(source_model_code)
    new, new_imports, new_other = _definition_hashes(destination_model_code)
    added = new.keys() - old.keys()
    changed = {name for name in old.keys() & new.keys() if old[name] != new[name]}
    if old.keys() - new.keys() or not added <= _ALLOWED_ADDED or not changed <= _ALLOWED_CHANGED:
        raise RuntimeError("model code contains changes outside reviewed memory helpers")
    permitted_import = ast.dump(
        ast.ImportFrom(
            module="copy",
            names=[ast.alias(name="deepcopy")],
            level=0,
        ),
        include_attributes=False,
    )
    if (
        old_other != new_other
        or [item for item in new_imports if item != permitted_import]
        != [item for item in old_imports if item != permitted_import]
        or new_imports.count(permitted_import) < old_imports.count(permitted_import)
        or new_imports.count(permitted_import) > 1
    ):
        raise RuntimeError("model constants or imports changed outside the memory patch")
    if source_lock.read_bytes() != destination_lock.read_bytes():
        raise RuntimeError("checkpoint import dependency lock changed")
    locked = {
        package["name"]: package["version"]
        for package in tomllib.loads(destination_lock.read_text(encoding="utf-8"))["package"]
    }
    runtime = {name: version(name) for name in _RUNTIME_PACKAGES}
    if any(locked.get(name) != value for name, value in runtime.items()):
        raise RuntimeError("installed runtime differs from the unchanged dependency lock")
    if not passing_fixture_reports:
        raise RuntimeError("checkpoint import requires passing semantic fixture evidence")
    reports = []
    for path in passing_fixture_reports:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if not suites or any(
            int(suite.attrib.get("tests", "0")) < 1
            or int(suite.attrib.get("failures", "0")) != 0
            or int(suite.attrib.get("errors", "0")) != 0
            for suite in suites
        ):
            raise RuntimeError("checkpoint import fixture evidence is not successful")
        reports.append({"sha256": _file_sha256(path), "name": path.name})
    proof: dict[str, object] = {
        "schema_version": _PROOF_SCHEMA,
        "source_namespace": namespace,
        "destination_provenance": dict(destination_provenance),
        "source_model_code_sha256": _file_sha256(source_model_code),
        "destination_model_code_sha256": _file_sha256(destination_model_code),
        "unchanged_definition_hashes": {name: old[name] for name in old if name not in changed},
        "changed_definition_names": sorted(changed),
        "added_definition_names": sorted(added),
        "dependency_lock_sha256": _file_sha256(destination_lock),
        "runtime_versions": runtime,
        "passing_fixture_reports": reports,
    }
    proof["metadata_hash"] = _metadata_hash(proof)
    return proof


def _authenticate_proof(
    proof: Mapping[str, object],
    destination_provenance: Mapping[str, object],
) -> dict[str, Any]:
    _authenticate_metadata(proof, description="memory equivalence proof")
    if proof.get("schema_version") != _PROOF_SCHEMA:
        raise RuntimeError("unsupported memory equivalence proof")
    if proof.get("destination_provenance") != dict(destination_provenance):
        raise RuntimeError("memory equivalence proof destination mismatch")
    namespace = proof.get("source_namespace")
    if not isinstance(namespace, dict) or not isinstance(namespace.get("provenance"), dict):
        raise RuntimeError("memory equivalence proof source is invalid")
    _authenticate_metadata(namespace, description="import source namespace")
    source_provenance = namespace["provenance"]
    _same_research_identity(source_provenance, destination_provenance)
    if namespace.get("checkpoint_id") != checkpoint_id_for_provenance(source_provenance):
        raise RuntimeError("memory equivalence proof source namespace mismatch")
    if not isinstance(proof.get("runtime_versions"), dict) or not proof.get(
        "passing_fixture_reports"
    ):
        raise RuntimeError("memory equivalence proof lacks runtime/fixture evidence")
    return namespace


def authenticate_checkpoint_import_plan(
    plan: Mapping[str, object],
    destination_provenance: Mapping[str, object],
) -> None:
    """Validate an explicit local recovery plan before enabling any automatic reuse."""

    _authenticate_metadata(plan, description="checkpoint import plan")
    if plan.get("schema_version") != "advanced-checkpoint-import-plan-v1":
        raise RuntimeError("unsupported checkpoint import plan")
    proof = plan.get("equivalence_proof")
    source_path = plan.get("source_checkpoint_path")
    if not isinstance(proof, dict) or not isinstance(source_path, str):
        raise RuntimeError("checkpoint import plan is invalid")
    namespace = _authenticate_proof(proof, destination_provenance)
    path = Path(source_path)
    if not path.is_absolute() or path.name != namespace["checkpoint_id"]:
        raise RuntimeError("checkpoint import plan requires the exact source namespace path")
    if _load_json(path / "manifest.json", description="source namespace") != namespace:
        raise RuntimeError("checkpoint import plan source metadata changed")


def _effective_parameters(
    evidence: Mapping[str, object], provenance: Mapping[str, object]
) -> dict[str, object]:
    from stock_ai.ml.advanced import AdvancedResearchConfig, _model_parameters

    config = AdvancedResearchConfig.model_validate(provenance.get("config"))
    if (
        config.config_hash != provenance.get("config_hash")
        or evidence.get("config_hash") != config.config_hash
    ):
        raise RuntimeError("fold import config hash mismatch")
    if config.model_families != ("catboost",) or evidence.get("model_family") != "catboost":
        raise RuntimeError("this bridge is restricted to the fixed CatBoost CPU recovery")
    if evidence.get("seed") not in config.seeds or evidence.get("horizon") not in config.horizons:
        raise RuntimeError("fold import seed/horizon mismatch")
    if evidence.get("feature_names") != provenance.get("feature_names"):
        raise RuntimeError("fold import ordered feature identity mismatch")
    task = evidence.get("task")
    losses = {
        "ranking": "YetiRank",
        "regression": "RMSE",
        "large_loss": "Logloss",
        "quantile": f"Quantile:alpha={config.quantile_alpha}",
    }
    if task not in losses:
        raise RuntimeError("fold import task is unsupported")
    parameters = evidence.get("parameters")
    if not isinstance(parameters, dict) or any(
        not isinstance(value, (int, float)) or not math.isfinite(value)
        for value in parameters.values()
    ):
        raise RuntimeError("fold import parameters are invalid")
    return {
        "model_family": "catboost",
        "task": task,
        "loss_function": losses[task],
        "iterations": config.estimator_count,
        "random_seed": evidence["seed"],
        "thread_count": 1,
        "task_type": "CPU",
        "verbose": False,
        "allow_writing_files": False,
        "model_input_precision": "float32-existing-preprocessor",
        **_model_parameters("catboost", parameters),
    }


def authenticate_fold_import_lineage(
    lineage: Mapping[str, object],
    *,
    destination_provenance: Mapping[str, object],
    evidence: Mapping[str, object],
    frame_sha256: str,
) -> None:
    """Authenticate the complete source-to-destination receipt on publication and reload."""

    _authenticate_metadata(lineage, description="fold import lineage")
    if lineage.get("schema_version") != _LINEAGE_SCHEMA:
        raise RuntimeError("unsupported fold import lineage")
    proof, source_metadata = lineage.get("equivalence_proof"), lineage.get("source_fold_metadata")
    if not isinstance(proof, dict) or not isinstance(source_metadata, dict):
        raise RuntimeError("fold import lineage evidence is invalid")
    namespace = _authenticate_proof(proof, destination_provenance)
    _authenticate_metadata(source_metadata, description="import source fold metadata")
    source_checkpoint_id = namespace["checkpoint_id"]
    expected_source_unit = stable_hash(
        {
            "schema_version": "advanced-research-fold-v1",
            "checkpoint_id": source_checkpoint_id,
            "evidence": dict(evidence),
        }
    )
    if (
        source_metadata.get("schema_version") != "advanced-research-fold-v1"
        or source_metadata.get("status") != "SUCCEEDED"
        or source_metadata.get("checkpoint_id") != source_checkpoint_id
        or source_metadata.get("unit_id") != expected_source_unit
        or source_metadata.get("evidence") != dict(evidence)
        or source_metadata.get("frame_sha256") != frame_sha256
        or "import_lineage" in source_metadata
    ):
        raise RuntimeError("fold import source data/split/parameter/output identity mismatch")
    if lineage.get("destination_checkpoint_id") != checkpoint_id_for_provenance(
        destination_provenance
    ):
        raise RuntimeError("fold import destination namespace mismatch")
    effective = _effective_parameters(evidence, destination_provenance)
    if lineage.get("effective_parameters") != effective:
        raise RuntimeError("fold import effective parameters mismatch")
    if lineage.get("effective_parameters_sha256") != stable_hash(effective):
        raise RuntimeError("fold import effective parameter hash mismatch")


def import_authenticated_fold(
    *,
    source_checkpoint: Path,
    destination: ResearchCheckpointStore,
    evidence: Mapping[str, object],
    equivalence_proof: Mapping[str, object],
    frame_hash: Callable[[pd.DataFrame], str],
) -> Path | None:
    """Reuse one completed fold with explicit lineage; never write to the source namespace."""

    namespace = _authenticate_proof(equivalence_proof, destination.provenance)
    actual_namespace = _load_json(
        source_checkpoint / "manifest.json", description="source checkpoint"
    )
    _authenticate_metadata(actual_namespace, description="source checkpoint")
    if actual_namespace != namespace or source_checkpoint.name != namespace["checkpoint_id"]:
        raise RuntimeError("fold import source namespace does not match the approved proof")
    if source_checkpoint.resolve() == destination.path.resolve():
        raise RuntimeError("fold import source and destination must be separate")
    progress_path = source_checkpoint / "progress.json"
    progress_bytes = progress_path.read_bytes()
    progress = _load_json(progress_path, description="source checkpoint progress")
    _authenticate_metadata(progress, description="source checkpoint progress")
    if progress.get("checkpoint_id") != namespace["checkpoint_id"]:
        raise RuntimeError("fold import source progress namespace mismatch")
    source_unit_id = stable_hash(
        {
            "schema_version": "advanced-research-fold-v1",
            "checkpoint_id": namespace["checkpoint_id"],
            "evidence": dict(evidence),
        }
    )
    units = progress.get("units")
    if not isinstance(units, dict):
        raise RuntimeError("source checkpoint units are invalid")
    unit = units.get(source_unit_id)
    if unit is None:
        identity_keys = ("checkpoint_scope", "fold", "horizon", "model_family", "task", "seed")
        for prior in units.values():
            if not isinstance(prior, dict) or prior.get("status") != "SUCCEEDED":
                continue
            prior_evidence = prior.get("evidence")
            if isinstance(prior_evidence, dict) and all(
                prior_evidence.get(key) == evidence.get(key) for key in identity_keys
            ):
                raise RuntimeError("completed source fold differs from recomputed split/parameters")
        return None
    if not isinstance(unit, dict):
        raise RuntimeError("source checkpoint unit is invalid")
    if unit.get("status") != "SUCCEEDED":
        return None
    artifact = source_checkpoint / "folds" / source_unit_id
    if (
        unit.get("evidence") != dict(evidence)
        or Path(unit.get("artifact", "")).resolve() != artifact.resolve()
    ):
        raise RuntimeError("source fold progress evidence or path mismatch")
    source_metadata = _load_json(artifact / "manifest.json", description="source fold")
    reader = object.__new__(ResearchCheckpointStore)
    reader.checkpoint_id, reader.provenance = namespace["checkpoint_id"], namespace["provenance"]
    frame = reader._authenticate_fold(
        artifact,
        unit_id=source_unit_id,
        evidence=evidence,
        frame_hash=frame_hash,
    )
    lineage: dict[str, object] = {
        "schema_version": _LINEAGE_SCHEMA,
        "source_fold_metadata": source_metadata,
        "equivalence_proof": dict(equivalence_proof),
        "destination_checkpoint_id": destination.checkpoint_id,
        "effective_parameters": _effective_parameters(evidence, destination.provenance),
    }
    lineage["effective_parameters_sha256"] = stable_hash(lineage["effective_parameters"])
    lineage["metadata_hash"] = _metadata_hash(lineage)
    if progress_path.read_bytes() != progress_bytes:
        raise RuntimeError("source checkpoint changed during import; retry at a safe boundary")
    return destination.publish_fold(
        evidence,
        frame,
        frame_hash=frame_hash,
        import_lineage=lineage,
    )


def _study_provenance(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": "advanced-optuna-study-v1",
        "study_identity": stable_hash(evidence),
        "evidence": dict(evidence),
    }


def _trial_payloads(trials: Sequence[optuna.trial.FrozenTrial]) -> list[dict[str, object]]:
    return [
        {
            "number": trial.number,
            "state": trial.state.name,
            "values": trial.values,
            "parameters": trial.params,
            "distributions": {
                name: json.loads(optuna.distributions.distribution_to_json(distribution))
                for name, distribution in trial.distributions.items()
            },
            "user_attrs": trial.user_attrs,
            "system_attrs": trial.system_attrs,
            "datetime_start": None
            if trial.datetime_start is None
            else trial.datetime_start.isoformat(),
            "datetime_complete": (
                None if trial.datetime_complete is None else trial.datetime_complete.isoformat()
            ),
        }
        for trial in trials
    ]


def authenticate_optuna_import_lineage(
    lineage: Mapping[str, object],
    *,
    destination_provenance: Mapping[str, object],
    study_evidence: Mapping[str, object],
    trials: Sequence[optuna.trial.FrozenTrial],
) -> None:
    """Require exactly preserved terminal trials, dates, distributions and tuning budgets."""

    _authenticate_metadata(lineage, description="Optuna import lineage")
    if lineage.get("schema_version") != _STUDY_LINEAGE_SCHEMA:
        raise RuntimeError("unsupported Optuna import lineage")
    proof = lineage.get("equivalence_proof")
    if not isinstance(proof, dict):
        raise RuntimeError("Optuna import proof is invalid")
    namespace = _authenticate_proof(proof, destination_provenance)
    source_evidence = {**study_evidence, "checkpoint_id": namespace["checkpoint_id"]}
    if lineage.get("source_study_provenance") != _study_provenance(source_evidence):
        raise RuntimeError("Optuna import source study identity mismatch")
    if study_evidence.get("checkpoint_id") != checkpoint_id_for_provenance(destination_provenance):
        raise RuntimeError("Optuna import destination study identity mismatch")
    source_trials = lineage.get("source_trials")
    if not isinstance(source_trials, list) or not source_trials or len(trials) < len(source_trials):
        raise RuntimeError("Optuna import lacks the complete source trial prefix")
    imported_trials = trials[: len(source_trials)]
    payload = _trial_payloads(imported_trials)
    if lineage.get("source_trials") != payload or lineage.get(
        "source_trials_sha256"
    ) != stable_hash(payload):
        raise RuntimeError("Optuna import trial values/parameters/distributions/durations changed")
    if not trials or any(
        trial.state
        not in {
            optuna.trial.TrialState.COMPLETE,
            optuna.trial.TrialState.PRUNED,
            optuna.trial.TrialState.FAIL,
        }
        for trial in imported_trials
    ):
        raise RuntimeError("Optuna import requires terminal immutable trial evidence")


def import_authenticated_optuna_study(
    *,
    source_checkpoint: Path,
    destination: ResearchCheckpointStore,
    study_evidence: Mapping[str, object],
    equivalence_proof: Mapping[str, object],
) -> Path:
    """Clone one fixed study through a read-only SQLite snapshot into a new namespace.

    Original trial dates/durations stay intact, so remaining trial/time budgets do not
    reset. The destination database and complete lineage become visible atomically.
    """

    namespace = _authenticate_proof(equivalence_proof, destination.provenance)
    actual_namespace = _load_json(
        source_checkpoint / "manifest.json", description="source checkpoint"
    )
    if actual_namespace != namespace or source_checkpoint.name != namespace["checkpoint_id"]:
        raise RuntimeError("Optuna import source namespace mismatch")
    if destination.optuna_database_path.exists():
        raise RuntimeError("Optuna import destination database already exists")
    if study_evidence.get("checkpoint_id") != destination.checkpoint_id:
        raise RuntimeError("Optuna import target namespace mismatch")
    source_evidence = {**study_evidence, "checkpoint_id": namespace["checkpoint_id"]}
    source_provenance = _study_provenance(source_evidence)
    source_progress = (source_checkpoint / "progress.json").read_bytes()
    progress = _load_json(source_checkpoint / "progress.json", description="source progress")
    _authenticate_metadata(progress, description="source progress")
    if progress.get("checkpoint_id") != namespace["checkpoint_id"]:
        raise RuntimeError("Optuna import source progress identity mismatch")
    source_database = source_checkpoint / "optuna.sqlite3"
    with tempfile.TemporaryDirectory(prefix=".optuna-import-", dir=destination.path) as temporary:
        folder = Path(temporary)
        snapshot = folder / "source.sqlite3"
        with closing(
            sqlite3.connect(
                f"{source_database.resolve().as_uri()}?mode=ro",
                uri=True,
            )
        ) as original:
            with closing(sqlite3.connect(snapshot)) as backup:
                original.backup(backup)
        source_storage = optuna.storages.RDBStorage(url=f"sqlite:///{snapshot.as_posix()}")
        try:
            source_study = optuna.load_study(
                study_name=f"advanced-{source_provenance['study_identity']}",
                storage=source_storage,
            )
            if source_study.user_attrs != {"provenance": source_provenance}:
                raise RuntimeError("Optuna import source study provenance mismatch")
            if source_study.direction is not optuna.study.StudyDirection.MAXIMIZE:
                raise RuntimeError("Optuna import study direction changed")
            trials = source_study.get_trials(deepcopy=True)
            if not trials or any(
                trial.state
                not in {
                    optuna.trial.TrialState.COMPLETE,
                    optuna.trial.TrialState.PRUNED,
                    optuna.trial.TrialState.FAIL,
                }
                for trial in trials
            ):
                raise RuntimeError("Optuna import source has unfinished trials")
        finally:
            source_storage.remove_session()
            source_storage.engine.dispose()
        lineage: dict[str, object] = {
            "schema_version": _STUDY_LINEAGE_SCHEMA,
            "equivalence_proof": dict(equivalence_proof),
            "source_study_provenance": source_provenance,
            "source_database_snapshot_sha256": _file_sha256(snapshot),
            "source_trials": _trial_payloads(trials),
        }
        lineage["source_trials_sha256"] = stable_hash(lineage["source_trials"])
        lineage["metadata_hash"] = _metadata_hash(lineage)
        authenticate_optuna_import_lineage(
            lineage,
            destination_provenance=destination.provenance,
            study_evidence=study_evidence,
            trials=trials,
        )
        pending = folder / "destination.sqlite3"
        storage = optuna.storages.RDBStorage(url=f"sqlite:///{pending.as_posix()}")
        try:
            target = optuna.create_study(
                study_name=f"advanced-{stable_hash(study_evidence)}",
                direction="maximize",
                storage=storage,
            )
            target.add_trials(trials)
            target.set_user_attr("provenance", _study_provenance(study_evidence))
            target.set_user_attr("import_lineage", lineage)
            authenticate_optuna_import_lineage(
                lineage,
                destination_provenance=destination.provenance,
                study_evidence=study_evidence,
                trials=target.get_trials(deepcopy=False),
            )
        finally:
            storage.remove_session()
            storage.engine.dispose()
        if (source_checkpoint / "progress.json").read_bytes() != source_progress:
            raise RuntimeError("source checkpoint changed while importing the study")
        os.replace(pending, destination.optuna_database_path)
    return destination.optuna_database_path
