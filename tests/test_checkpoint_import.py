"""Synthetic import/reload/tamper tests using two explicit code identities.

Both synthetic identities use the installed model implementation. Cross-version memory
patch equivalence is separately verified in the archived local 54-case comparison.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import optuna
import pandas.testing as pdt
import pytest

import stock_ai.ml.advanced as advanced
from stock_ai.features import V2_EXTENDED_MANIFEST
from stock_ai.ml.checkpoint import (
    ResearchCheckpointStore,
    _file_sha256,
    _metadata_hash,
    stable_hash,
)
from stock_ai.ml.checkpoint_import import (
    _study_provenance,
    _trial_payloads,
    authenticate_optuna_import_lineage,
    create_memory_equivalence_proof,
    import_authenticated_fold,
    import_authenticated_optuna_study,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


baseline = _load("stock_ai.ml.import_baseline", ROOT / "src/stock_ai/ml/advanced.py")
fixtures = _load("checkpoint_import_fixtures", ROOT / "tests/test_advanced_research.py")


def _files(root):
    return {
        str(path.relative_to(root)): _file_sha256(path)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    frame = fixtures._production_dataset()
    config = fixtures._config(model_families=("catboost",))
    provenance = {
        "code_commit": "1" * 40,
        "data_snapshot_id": "a" * 64,
        "feature_snapshot_id": "b" * 64,
        "feature_manifest_hash": V2_EXTENDED_MANIFEST.manifest_hash,
        "feature_names": list(fixtures._research_features()),
        "config": config.model_dump(mode="json"),
        "config_hash": config.config_hash,
        "locked_holdout_accessed": False,
    }
    monkeypatch.setattr(
        baseline, "_fit_predict", lambda **kwargs: np.arange(len(kwargs["validation_x"])) / 100
    )
    with ResearchCheckpointStore(tmp_path / "source", provenance=provenance) as source:
        kwargs = {
            "feature_names": fixtures._research_features(),
            "target_column": "target_return_1d",
            "label_end_column": "label_end_date_1d",
            "horizon": 1,
            "family": "catboost",
            "task": "regression",
            "seed": 17,
            "parameters": {"depth": 3, "learning_rate": 0.05, "l2": 1.0},
            "config": config,
            "checkpoint_scope": "outer-model-evaluation",
        }
        oof = baseline.generate_oof_predictions(frame, checkpoint_store=source, **kwargs)
        source_path = source.path
    target_provenance = {**provenance, "code_commit": "2" * 40}
    destination = ResearchCheckpointStore(tmp_path / "destination", provenance=target_provenance)
    # This XML is an input fixture for proof validation, not a production test report.
    report = tmp_path / "passing-report-input-fixture.xml"
    report.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0"/></testsuites>', encoding="utf-8"
    )
    proof = create_memory_equivalence_proof(
        source_checkpoint=source_path,
        destination_provenance=target_provenance,
        source_model_code=ROOT / "src/stock_ai/ml/advanced.py",
        destination_model_code=ROOT / "src/stock_ai/ml/advanced.py",
        source_lock=ROOT / "uv.lock",
        destination_lock=ROOT / "uv.lock",
        passing_fixture_reports=[report],
    )
    progress = json.loads((source_path / "progress.json").read_text(encoding="utf-8"))
    evidence = [
        unit["evidence"] for unit in progress["units"].values() if unit["status"] == "SUCCEEDED"
    ]
    yield frame, kwargs, source_path, destination, proof, evidence, oof
    destination.close()


def test_import_every_fold_reloads_with_lineage_and_never_fits_or_changes_source(
    setup, monkeypatch
):
    frame, kwargs, source, destination, proof, evidence_list, expected = setup
    before = _files(source)
    for evidence in evidence_list:
        path = import_authenticated_fold(
            source_checkpoint=source,
            destination=destination,
            evidence=evidence,
            equivalence_proof=proof,
            frame_hash=advanced._frame_hash,
        )
        assert path is not None
        metadata = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        lineage = metadata["import_lineage"]
        assert (
            lineage["equivalence_proof"]["source_namespace"]["provenance"]["code_commit"]
            == "1" * 40
        )
        assert lineage["equivalence_proof"]["destination_provenance"]["code_commit"] == "2" * 40
        assert lineage["effective_parameters"]["thread_count"] == 1
        assert (
            import_authenticated_fold(
                source_checkpoint=source,
                destination=destination,
                evidence=evidence,
                equivalence_proof=proof,
                frame_hash=advanced._frame_hash,
            )
            == path
        )

    def no_fit(**kwargs):
        raise AssertionError("an imported fold must not fit")

    monkeypatch.setattr(advanced, "_fit_predict", no_fit)
    observed = advanced.generate_oof_predictions(frame, checkpoint_store=destination, **kwargs)
    pdt.assert_frame_equal(observed, expected, check_exact=True)
    assert before == _files(source)


@pytest.mark.parametrize("change", ["indices", "parameters", "feature_order"])
def test_recomputed_evidence_mismatch_blocks_completed_fold_reuse(setup, change):
    _, _, source, destination, proof, evidence_list, _ = setup
    evidence = copy.deepcopy(evidence_list[0])
    if change == "indices":
        evidence["train_indices_sha256"] = "c" * 64
    elif change == "parameters":
        evidence["parameters"]["depth"] += 1
    else:
        evidence["feature_names"] = evidence["feature_names"][::-1]
    with pytest.raises(RuntimeError, match="recomputed split/parameters"):
        import_authenticated_fold(
            source_checkpoint=source,
            destination=destination,
            evidence=evidence,
            equivalence_proof=proof,
            frame_hash=advanced._frame_hash,
        )
    assert not (destination.path / "folds").exists()


def test_missing_source_fold_stays_pending(setup):
    _, _, source, destination, proof, evidence_list, _ = setup
    evidence = {**evidence_list[0], "fold": 999}
    assert (
        import_authenticated_fold(
            source_checkpoint=source,
            destination=destination,
            evidence=evidence,
            equivalence_proof=proof,
            frame_hash=advanced._frame_hash,
        )
        is None
    )


@pytest.mark.parametrize("change", ["data", "config", "holdout"])
def test_proof_rejects_research_condition_change(setup, change):
    _, _, source, destination, _, _, _ = setup
    provenance = copy.deepcopy(destination.provenance)
    if change == "data":
        provenance["data_snapshot_id"] = "d" * 64
    elif change == "config":
        provenance["config"]["estimator_count"] += 1
    else:
        provenance["locked_holdout_accessed"] = True
    with pytest.raises(RuntimeError, match="changes data"):
        create_memory_equivalence_proof(
            source_checkpoint=source,
            destination_provenance=provenance,
            source_model_code=ROOT / "src/stock_ai/ml/advanced.py",
            destination_model_code=ROOT / "src/stock_ai/ml/advanced.py",
            source_lock=ROOT / "uv.lock",
            destination_lock=ROOT / "uv.lock",
            passing_fixture_reports=[],
        )


def test_proof_rejects_model_thread_change(setup, tmp_path):
    _, _, source, destination, _, _, _ = setup
    changed = tmp_path / "changed.py"
    changed.write_text(
        (ROOT / "src/stock_ai/ml/advanced.py")
        .read_text(encoding="utf-8")
        .replace(
            "thread_count=1",
            "thread_count=2",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="outside reviewed memory helpers"):
        create_memory_equivalence_proof(
            source_checkpoint=source,
            destination_provenance=destination.provenance,
            source_model_code=ROOT / "src/stock_ai/ml/advanced.py",
            destination_model_code=changed,
            source_lock=ROOT / "uv.lock",
            destination_lock=ROOT / "uv.lock",
            passing_fixture_reports=[],
        )


def test_tampered_source_parquet_is_not_imported(setup):
    _, _, source, destination, proof, evidence_list, _ = setup
    evidence = evidence_list[0]
    source_id = stable_hash(
        {
            "schema_version": "advanced-research-fold-v1",
            "checkpoint_id": source.name,
            "evidence": evidence,
        }
    )
    parquet = source / "folds" / source_id / "oof.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tamper-fixture")
    with pytest.raises(RuntimeError, match="Parquet hash mismatch"):
        import_authenticated_fold(
            source_checkpoint=source,
            destination=destination,
            evidence=evidence,
            equivalence_proof=proof,
            frame_hash=advanced._frame_hash,
        )


def test_lineage_parameter_tamper_is_rejected_even_after_outer_metadata_rehash(setup):
    _, _, source, destination, proof, evidence_list, _ = setup
    evidence = evidence_list[0]
    path = import_authenticated_fold(
        source_checkpoint=source,
        destination=destination,
        evidence=evidence,
        equivalence_proof=proof,
        frame_hash=advanced._frame_hash,
    )
    metadata = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    metadata["import_lineage"]["effective_parameters"]["thread_count"] = 2
    metadata["import_lineage"]["metadata_hash"] = _metadata_hash(metadata["import_lineage"])
    metadata["metadata_hash"] = _metadata_hash(metadata)
    (path / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(RuntimeError, match="effective parameters mismatch"):
        destination.load_fold(evidence, frame_hash=advanced._frame_hash)


def _source_study(setup):
    _, kwargs, source, destination, _, _, _ = setup
    config = kwargs["config"]
    evidence = {
        "checkpoint_id": source.name,
        "horizon": 1,
        "model_family": "catboost",
        "target_column": "target_return_1d",
        "label_end_column": "label_end_date_1d",
        "feature_names": list(kwargs["feature_names"]),
        "config_hash": config.config_hash,
        "seed": 17,
    }
    storage = optuna.storages.RDBStorage(url=f"sqlite:///{(source / 'optuna.sqlite3').as_posix()}")
    study = optuna.create_study(
        study_name=f"advanced-{stable_hash(evidence)}", direction="maximize", storage=storage
    )
    study.set_user_attr("provenance", _study_provenance(evidence))
    trial = study.ask(
        fixed_distributions={
            "learning_rate": optuna.distributions.FloatDistribution(0.02, 0.15, log=True),
            "depth": optuna.distributions.IntDistribution(2, 6),
            "l2": optuna.distributions.FloatDistribution(0.001, 10.0, log=True),
        }
    )
    study.tell(trial, 0.25)
    trials = study.get_trials(deepcopy=True)
    storage.remove_session()
    storage.engine.dispose()
    return {**evidence, "checkpoint_id": destination.checkpoint_id}, trials


def test_optuna_copy_preserves_budget_trials_and_source_bytes(setup, monkeypatch):
    frame, kwargs, source, destination, proof, _, _ = setup
    evidence, original_trials = _source_study(setup)
    before = _files(source)
    path = import_authenticated_optuna_study(
        source_checkpoint=source,
        destination=destination,
        study_evidence=evidence,
        equivalence_proof=proof,
    )
    storage = optuna.storages.RDBStorage(url=f"sqlite:///{path.as_posix()}")
    study = optuna.load_study(study_name=f"advanced-{stable_hash(evidence)}", storage=storage)
    trials = study.get_trials(deepcopy=True)
    assert _trial_payloads(trials) == _trial_payloads(original_trials)
    lineage = study.user_attrs["import_lineage"]
    authenticate_optuna_import_lineage(
        lineage,
        destination_provenance=destination.provenance,
        study_evidence=evidence,
        trials=trials,
    )
    storage.remove_session()
    storage.engine.dispose()

    def no_new_trial(*args, **kwargs):
        raise AssertionError("one completed trial already exhausts this synthetic config")

    monkeypatch.setattr(advanced, "generate_oof_predictions", no_new_trial)
    result = advanced.bounded_optuna_search(
        frame,
        feature_names=kwargs["feature_names"],
        target_column=kwargs["target_column"],
        label_end_column=kwargs["label_end_column"],
        horizon=1,
        family="catboost",
        config=kwargs["config"],
        checkpoint_store=destination,
    )
    assert result.best_parameters == original_trials[0].params
    assert result.best_value == original_trials[0].value
    assert before == _files(source)


def test_optuna_lineage_rejects_changed_trial_duration(setup):
    _, _, source, destination, proof, _, _ = setup
    evidence, _ = _source_study(setup)
    path = import_authenticated_optuna_study(
        source_checkpoint=source,
        destination=destination,
        study_evidence=evidence,
        equivalence_proof=proof,
    )
    storage = optuna.storages.RDBStorage(url=f"sqlite:///{path.as_posix()}")
    study = optuna.load_study(study_name=f"advanced-{stable_hash(evidence)}", storage=storage)
    trials = study.get_trials(deepcopy=True)
    lineage = study.user_attrs["import_lineage"]
    trials[0].datetime_start = trials[0].datetime_complete
    with pytest.raises(RuntimeError, match="durations changed"):
        authenticate_optuna_import_lineage(
            lineage,
            destination_provenance=destination.provenance,
            study_evidence=evidence,
            trials=trials,
        )
    storage.remove_session()
    storage.engine.dispose()


def test_explicit_import_plan_reuses_folds_automatically_with_current_evidence(
    setup, monkeypatch, tmp_path
):
    frame, kwargs, source, destination, proof, _, expected = setup
    provenance = destination.provenance
    root = destination.path.parent
    destination.close()
    plan = {
        "schema_version": "advanced-checkpoint-import-plan-v1",
        "source_checkpoint_path": str(source.resolve()),
        "equivalence_proof": proof,
    }
    plan["metadata_hash"] = _metadata_hash(plan)
    plan_path = tmp_path / "import-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def no_fit(**kwargs):
        raise AssertionError("explicit plan must reuse exact completed folds")

    monkeypatch.setattr(advanced, "_fit_predict", no_fit)
    with ResearchCheckpointStore(root, provenance=provenance, import_plan=plan_path) as imported:
        observed = advanced.generate_oof_predictions(frame, checkpoint_store=imported, **kwargs)
        pdt.assert_frame_equal(observed, expected, check_exact=True)
        assert json.loads((imported.path / "import-plan.json").read_text(encoding="utf-8")) == plan


def test_explicit_plan_reuses_optuna_without_resetting_budget(setup, monkeypatch, tmp_path):
    frame, kwargs, source, destination, proof, _, _ = setup
    _, trials = _source_study(setup)
    provenance = destination.provenance
    root = destination.path.parent
    destination.close()
    plan = {
        "schema_version": "advanced-checkpoint-import-plan-v1",
        "source_checkpoint_path": str(source.resolve()),
        "equivalence_proof": proof,
    }
    plan["metadata_hash"] = _metadata_hash(plan)
    plan_path = tmp_path / "import-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def no_new_trial(*args, **kwargs):
        raise AssertionError("existing terminal trial exhausts the synthetic trial budget")

    monkeypatch.setattr(advanced, "generate_oof_predictions", no_new_trial)
    with ResearchCheckpointStore(root, provenance=provenance, import_plan=plan_path) as imported:
        result = advanced.bounded_optuna_search(
            frame,
            feature_names=kwargs["feature_names"],
            target_column=kwargs["target_column"],
            label_end_column=kwargs["label_end_column"],
            horizon=1,
            family="catboost",
            config=kwargs["config"],
            checkpoint_store=imported,
        )
        assert result.best_parameters == trials[0].params


def test_import_cli_option_is_explicit_and_invalid_path_is_rejected(tmp_path):
    from typer.testing import CliRunner

    from stock_ai.cli import app

    fixture = tmp_path / "unread-build-fixture.json"
    fixture.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "research",
            "advanced",
            "--build-manifest",
            str(fixture),
            "--code-commit",
            "2" * 40,
            "--checkpoint-import-plan",
            str(tmp_path / "missing-import-plan.json"),
        ],
        env={"COLUMNS": "240", "NO_COLOR": "1"},
    )
    assert result.exit_code == 2
    assert "does not exist" in result.output
