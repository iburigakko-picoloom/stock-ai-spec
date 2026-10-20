from pathlib import Path

import pytest

from stock_ai.features import V0_MANIFEST, V2_EXTENDED_MANIFEST
from stock_ai.ml.candidate_registry import build_candidate_registry
from stock_ai.ml.selection import freeze_development_features, write_development_feature_selection
from tests.test_research_selection import _build_marker, _campaign, _family_features


@pytest.fixture
def registry_input(tmp_path):
    build_id, build_path = _build_marker(tmp_path)
    args = dict(build_id=build_id, build_path=build_path, horizons=(5, 20))
    ablation = _campaign(
        tmp_path,
        name="ablation",
        families=("lightgbm",),
        features=V2_EXTENDED_MANIFEST.feature_names,
        run_ablations=True,
        **args,
    )
    selected = tuple(
        n
        for n in V2_EXTENDED_MANIFEST.feature_names
        if n in {*V0_MANIFEST.feature_names, *_family_features("F1")}
    )
    candidate = _campaign(
        tmp_path,
        name="candidate",
        families=("lightgbm", "xgboost", "catboost"),
        features=selected,
        run_ablations=False,
        **args,
    )
    import json

    exclusion = tmp_path / "synthetic-one-day-exclusion.json"
    exclusion.write_text(
        json.dumps(
            {
                "schema_version": "goal3-one-day-screen-decision-v1",
                "criteria_version": "D080",
                "build_id": build_id,
                "decision": "EXCLUDE_FROM_FULL_ABLATION_AND_FINAL",
                "screen_report_ids": ["d" * 64],
                "locked_holdout_accessed": False,
            }
        )
    )
    feature_path = write_development_feature_selection(
        freeze_development_features(
            ablation_campaign_paths=(ablation,), one_day_decision_path=exclusion
        ),
        tmp_path / "features",
    )
    return feature_path, candidate


def test_registry_authenticates_full_matrix_without_fitting_or_claiming_final_access(
    registry_input,
):
    features, campaign = registry_input
    result = build_candidate_registry(features, [campaign])
    assert result["status"] == "AUTHENTICATED_OOF"
    assert len(result["candidates"]) == 18
    assert result["training_performed"] is False and result["holdout_opened"] is False
    assert result["training_models_certified"] is False
    assert all(len(r["authenticated_reports"]) == 1 for r in result["candidates"])
    assert all(r["attempts"] for r in result["candidates"])
    assert all(Path(p).exists() for p in result["pinned_files"])


def test_registry_retains_missing_rows_instead_of_reporting_smaller_success(registry_input):
    features, _ = registry_input
    result = build_candidate_registry(features, [])
    assert result["status"] == "HOLD"
    assert len(result["candidates"]) == 18
    assert all(r["status"] == "MISSING_AUTHENTICATED_SUCCESS" for r in result["candidates"])


def test_registry_refuses_changed_oof_and_keeps_failure_row(registry_input):
    import json

    features, campaign = registry_input
    manifest = json.loads(campaign.read_text())
    oof = Path(manifest["batches"][0]["oof_path"])
    oof.write_bytes(oof.read_bytes() + b"changed")
    result = build_candidate_registry(features, [campaign])
    assert result["status"] == "HOLD"
    bad = [r for r in result["candidates"] if r["problems"]]
    assert len(bad) == 1 and "hash mismatch" in bad[0]["problems"][0]
