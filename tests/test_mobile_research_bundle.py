"""Synthetic return-only integration; no invented market/adoption evidence."""

import copy
import hashlib
import json
from datetime import timedelta

import pytest
from mobile.python import decisions, forecasts, manual_chatgpt, models
from mobile.python.model_bundle import ResearchModelBundle, approved, encoded, reviewed

from stock_ai.domain.models import ReturnOnlyPrediction
from stock_ai.operations.daily import PredictionSnapshot, content_id, export_prediction_snapshot
from tests.test_mobile_bundles import CUTOFF, SELECTION, fixture_bundle
from tests.test_mobile_decisions import NOW, SETUP
from tests.test_mobile_decisions import ready as ready
from tests.test_mobile_manual_chatgpt import permission


def research_bundle(source=None):
    original = fixture_bundle() if source is None else source
    data = original.model_dump(exclude={
        "bundle_id", "adoption_review", "calibration", "large_loss_threshold",
        "downside_quantile_alpha", "heads", "schema_version",
    })
    return ResearchModelBundle.create(
        **data, schema_version="stockai-mobile-research-bundle-v1",
        source_evidence_sha256="7" * 64, heads=original.heads[:2],
    )


def research_pin(bundle):
    return dict(sha256=hashlib.sha256(encoded(bundle).encode()).hexdigest(),
                bundle_id=bundle.bundle_id, source_evidence_sha256=bundle.source_evidence_sha256,
                pc_parity_evidence_sha256="2" * 64, device_parity_evidence_sha256="3" * 64,
                distribution_review="private-research-import-approved", use="return-only-research")


@pytest.fixture
def research_ready(ready):
    device, path, store, _old_numerical, policy = ready
    bundle = research_bundle(models.load_bundle(path, CUTOFF)[0])
    policy["research_bundles"] = [research_pin(bundle)]
    models.import_bundle(path, encoded(bundle), SETUP + timedelta(minutes=1))
    numerical = forecasts.generate(path, store, NOW)
    return device, path, store, numerical, policy


def test_unadopted_two_head_forecast_and_manual_target_validation_preserve_ledger(research_ready):
    device, path, store, numerical, _ = research_ready
    before = store.latest_portfolio()
    snapshot = store.latest_prediction_snapshot()
    assert numerical["phase"] == "published" and numerical["outcome"] == "forecast"
    assert snapshot.mode == "research" and not snapshot.risk_available
    assert snapshot.risk_horizon is None and snapshot.large_loss_threshold is None
    assert snapshot.holding_symbols == ("7203",)
    assert all(isinstance(p, ReturnOnlyPrediction) and p.uncertainty is None
               for p in snapshot.predictions)
    status = models.status(path, store)
    assert status["bundle_ready"] and status["return_only_research"]
    assert not status["model_adopted"] and not status["risk_available"]
    decision = decisions.generate(path, store, NOW)
    assert decision["outcome"] == "blocked"
    assert decision["blocking_reasons"] == ["FORECAST_RISK_UNAVAILABLE"]
    assert decision["comparison"]["proposal"] is None
    exported = manual_chatgpt.export(path, store, permission(), NOW)
    package = json.loads(exported["prompt"].split("\n入力:\n")[1])
    assert not package["model_risk_available"]
    assert {s["symbol"] for s in package["securities"]} == set(snapshot.research_symbols())
    assert all(s["uncertainty"] is None and s["large_loss_probability"] is None
               and s["downside_quantile"] is None for s in package["securities"])
    answer = dict(schema_version="chatgpt-target-shares-v1",
                  input_snapshot_id=package["input_snapshot_id"], evidence_as_of=NOW.isoformat(),
                  targets=[dict(symbol=t["symbol"], account=t["account"],
                                target_shares=t["current_shares"],
                                reason="Synthetic hold", sources=[])
                           for t in package["required_targets"]], unknowns=["Risk unavailable"])
    result = manual_chatgpt.import_answer(path, store, {
        "input_record_id": exported["input_record_id"], "answer_json": json.dumps(answer),
    }, NOW)
    assert not result["review"]["model_risk_available"]
    assert all(line["share_difference"] == 0 for line in result["review"]["lines"])
    assert store.latest_portfolio() == before and store.latest_prediction_snapshot() == snapshot
    assert not result["review"]["applied_to_ledger"]
    assert "未提供" in export_prediction_snapshot(snapshot, format="markdown")
    store.verify_integrity()
    state = device.export_state()
    device.initialize(state)
    restored = device._app.state.store
    assert restored.latest_prediction_snapshot() == snapshot
    assert restored.latest_portfolio() == before
    status = manual_chatgpt.status(path, restored, NOW)
    assert status["selected_input"] == exported["input_record_id"]


@pytest.mark.parametrize("field", ["pc_parity_evidence_sha256", "device_parity_evidence_sha256",
                                  "source_evidence_sha256", "distribution_review"])
def test_research_import_requires_real_applicable_review_and_does_not_bypass_approved(field):
    bundle = research_bundle()
    pin = research_pin(bundle)
    pin[field] = None
    with pytest.raises(ValueError):
        reviewed(encoded(bundle), {"research_bundles": [pin]}, SELECTION)
    with pytest.raises(ValueError):
        approved(encoded(bundle), {"approved_bundles": [research_pin(bundle)]}, SELECTION)


@pytest.mark.parametrize("field,value", [("calibration", {}), ("adoption_review", {}),
                                         ("large_loss_threshold", -.08)])
def test_research_bundle_cannot_invent_calibration_risk_or_adoption(field, value):
    data = research_bundle().model_dump(exclude={"bundle_id"})
    data[field] = value
    with pytest.raises(ValueError):
        ResearchModelBundle.create(**data)


@pytest.mark.parametrize("change", ["approval_removed", "late_selection", "tampered_model"])
def test_selected_research_model_never_falls_back_to_older_reviewed_model(research_ready, change):
    _, path, store, numerical, policy = research_ready
    if change == "approval_removed":
        policy["research_bundles"] = []
    elif change == "late_selection":
        bundle = research_bundle()
        policy["research_bundles"].append(research_pin(bundle))
        models.import_bundle(path, encoded(bundle), NOW)
    else:
        from mobile.python.storage import connect
        with connect(path) as db:
            db.execute("UPDATE mobile_model_bundles SET payload='{}' WHERE sha256=?",
                       (numerical["scope"]["bundle_sha256"],))
    result = forecasts.generate(path, store, NOW + timedelta(seconds=1))
    assert result["outcome"] == "blocked" and store.latest_prediction_snapshot() is None


def test_missing_risk_cannot_be_relabelled_zero_or_owner_approved(research_ready):
    _, _, store, _, _ = research_ready
    snapshot = store.latest_prediction_snapshot()
    data = snapshot.model_dump(exclude={"snapshot_id"})
    for change in ({"mode": "paper"}, {"mode": "owner_approved", "adoption_review_id": "a" * 64}):
        with pytest.raises(ValueError):
            PredictionSnapshot.create(**{**data, **change})
    forged = copy.deepcopy(data)
    forged["predictions"][0]["large_loss_probability"] = 0.0
    with pytest.raises(ValueError):
        PredictionSnapshot.create(**forged)


def test_manual_return_only_context_rejects_changed_account_content(research_ready):
    from stock_ai.operations.chatgpt_manual import _context
    from stock_ai.operations.personal import PersonalComparison
    _, path, store, _, _ = research_ready
    value = decisions.generate(path, store, NOW)
    comparison = PersonalComparison.model_validate(value["comparison"])
    portfolio = store.latest_portfolio()
    forged = portfolio.model_copy(update={
        "cash": tuple(c.model_copy(update={"available_cash": c.available_cash + 1})
                      for c in portfolio.cash),
    })
    with pytest.raises(ValueError, match="SNAPSHOT_MISMATCH"):
        _context(comparison, forged, store.latest_prediction_snapshot(), NOW)
    payload = comparison.model_dump(mode="json", exclude={"comparison_id"})
    assert comparison.comparison_id == content_id(payload)


def test_expired_exchange_requires_new_context_without_retiming_original_forecast(research_ready):
    _, path, store, numerical, _ = research_ready
    decisions.generate(path, store, NOW)
    first = manual_chatgpt.export(path, store, permission(), NOW)
    later = NOW + timedelta(minutes=16)
    assert not manual_chatgpt.status(path, store, later)["ready"]
    assert forecasts.generate(path, store, later) == numerical
    refreshed = decisions.generate(path, store, later)
    assert refreshed["comparison"]["checked_at"] != numerical["checked_at"]
    second = manual_chatgpt.export(
        path, store, {**permission(), "checked_at": later.isoformat()}, later,
    )
    assert second["input_record_id"] != first["input_record_id"]
    assert forecasts.latest(path) == numerical
    assert manual_chatgpt.status(path, store, later)["saved_input"] == second
