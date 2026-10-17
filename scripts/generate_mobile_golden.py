"""Synthetic PC-reference vectors only; never package these in the APK."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import zipfile
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from mobile.pc.export_model import export_model
from mobile.python.model_bundle import ModelBundle, encoded
from pytest import MonkeyPatch
from tests.conftest import AS_OF, candidate, decision_engine, portfolio
from tests.test_bounded_decision import large_scenario, propose
from tests.test_mobile_bundles import SELECTION
from tests.test_mobile_decisions import NOW
from tests.test_mobile_decisions import ready as decision_ready
from tests.test_mobile_features import timely_history
from xgboost import XGBClassifier, XGBRegressor

from stock_ai.domain import Position
from stock_ai.features import V2_EXTENDED_MANIFEST, FeatureEngine
from stock_ai.fixtures import market_fixture
from stock_ai.ml.advanced import FoldPreprocessor
from stock_ai.operations.api import _proposal_view
from stock_ai.operations.daily import OwnerAdoptionReview, canonical_json

root = Path(__file__).resolve().parents[1]
daily, market, sector, financials = market_fixture(270)
selection = json.loads(
    next((root / "artifacts/selections/goal3-features").glob("*/*.json")).read_text()
)["feature_selection"]
as_of = daily.available_at.max()
result = FeatureEngine(V2_EXTENDED_MANIFEST).latest_snapshot(
    daily, market, sector, financials=financials, as_of=as_of
)
inputs = {
    name: json.loads(frame.to_json(orient="records", date_format="iso"))
    for name, frame in [
        ("daily", daily),
        ("market", market),
        ("sector", sector),
        ("financials", financials),
    ]
}
inputs["as_of"] = as_of.isoformat()
expected = {
    str(item["horizon"]): json.loads(
        result[["symbol", "available_at", *item["feature_names"]]].to_json(
            orient="records", date_format="iso"
        )
    )
    for item in selection["horizons"]
}
destination = root / ".demo-artifacts/android/mobile-golden.json"
destination.parent.mkdir(parents=True, exist_ok=True)
index = np.arange(48, dtype=float)
model_frame = pd.DataFrame({"a": np.sin(index), "b": index / 48})
processor = FoldPreprocessor(
    ("a", "b"), lower_quantile=0.01, upper_quantile=0.99, correlation_threshold=0.95
).fit(model_frame)
transformed = processor.transform(model_frame)
regression = np.sin(index / 5) + index / 100
vectors = []
for task in ("regression", "large_loss", "quantile"):
    classification = task == "large_loss"
    quantile = task == "quantile"
    target = (regression > np.median(regression)).astype(int) if classification else regression
    estimators = {
        "lightgbm": (LGBMClassifier if classification else LGBMRegressor)(
            n_estimators=5, num_leaves=4, min_child_samples=2, n_jobs=1, verbosity=-1,
            **({"objective": "quantile", "alpha": .1} if quantile else {})
        ),
        "xgboost": (XGBClassifier if classification else XGBRegressor)(
            n_estimators=5, max_depth=2, n_jobs=1,
            **({"objective": "reg:quantileerror", "quantile_alpha": .1} if quantile else {})
        ),
        "catboost": (CatBoostClassifier if classification else CatBoostRegressor)(
            iterations=5, depth=2, thread_count=1, verbose=False, allow_writing_files=False,
            **({"loss_function": "Quantile:alpha=0.1"} if quantile else {})
        ),
    }
    for family, estimator in estimators.items():
        estimator.fit(transformed, target)
        reference = (
            estimator.predict_proba(transformed)[:, 1]
            if classification
            else estimator.predict(transformed)
        )
        vectors.append(
            {
                "family": family,
                "task": task,
                "model": export_model(estimator, processor, family, task=task),
                "rows": model_frame.to_dict(orient="records"),
                "expected": reference.tolist(),
            }
        )
# Rebind only synthetic test features to the actual frozen selection. This
# fixture is never an approval pin or an APK asset.
heads, bundle_rows, bundle_expected = [], {}, []
for horizon, task in ((5, "regression"), (20, "regression"), (20, "quantile"),
                      (20, "large_loss")):
    vector = next(x for x in vectors if x["family"] == "lightgbm" and x["task"] == task)
    names = next(x["feature_names"][:2] for x in selection["horizons"]
                 if x["horizon"] == horizon)
    rename = dict(zip(("a", "b"), names, strict=True))
    model = deepcopy(vector["model"])
    processor_value = model["preprocessor"]
    processor_value["retained"] = [rename[x] for x in processor_value["retained"]]
    for field in ("lower", "upper", "median"):
        processor_value[field] = {rename[k]: v for k, v in processor_value[field].items()}
    content = canonical_json(model)
    heads.append({"horizon": horizon, "task": task, "model_id": f"synthetic-{horizon}-{task}",
                  "sha256": hashlib.sha256(content.encode()).hexdigest(), "content": content})
    bundle_rows[str(horizon)] = [{rename[k]: v for k, v in row.items()}
                                 for row in vector["rows"]]
    bundle_expected.append({"horizon": horizon, "task": task, "values": vector["expected"]})
review = OwnerAdoptionReview.create(
    selection_id="c" * 64, holdout_report_id="d" * 64, evaluator_receipt_id="e" * 64,
    decision_policy_hash="f" * 64, reviewed_at=datetime.fromisoformat("2026-02-02T07:00:00Z"),
    decision="continue_paper", unresolved_gates=("synthetic-test-only",),
    acknowledged_limitations=("Never use fixture values as market data",),
    note="Synthetic offline parity fixture",
)
bundle = ModelBundle.create(
    created_at="2026-02-02T08:00:00Z", trained_at="2026-02-01T00:00:00Z",
    training_data_cutoff="2026-01-30T00:00:00Z",
    feature_selection_id=selection["feature_selection_id"],
    feature_manifest_hash=selection["feature_manifest_hash"], selection_id="c" * 64,
    adoption_review=review, calibration={"method": "received_past_only_20d_residual_rmse",
    "residual_rmse": .02, "rows": 40, "dates": 20,
    "latest_label_available_at": "2026-02-01T00:00:00Z", "fitted_at": "2026-02-01T01:00:00Z",
    "source_evidence_sha256": "1" * 64},
    large_loss_threshold=-.08, downside_quantile_alpha=.1, heads=heads,
)
bundle_content = encoded(bundle)
bounded_state, bounded_candidates, _, bounded_engine = large_scenario(with_costs=True)
bounded_expected = propose(bounded_engine, bounded_state, bounded_candidates)
bounded_fixture = {
    "synthetic_only": True, "portfolio": bounded_state.model_dump(mode="json"),
    "candidates": [x.model_dump(mode="json") for x in bounded_candidates],
    "config": bounded_engine.config.model_dump(mode="json"),
    "cost_policy": bounded_engine.cost_engine.policy.model_dump(mode="json"),
    "tax_policy": bounded_engine.tax_engine.policy.model_dump(mode="json"),
    "generated_at": bounded_expected.generated_at.isoformat(),
    "model_bundle_version": bounded_expected.model_bundle_version,
    "expected": bounded_expected.model_dump(mode="json"),
}
withholding_fixtures = []
for version, mixed in (("decision-engine-v1", False),
                       ("daily-decision-engine-v3-bounded", False),
                       ("daily-decision-engine-v3-bounded", True)):
    held = Position(symbol="A", account_bucket_id="bucket", shares=100,
                    average_acquisition_price=Decimal(900), market_price=Decimal(1000))
    positions = tuple(Position(
        symbol=symbol, account_bucket_id="bucket", shares=100,
        average_acquisition_price=Decimal(basis), market_price=Decimal(1000),
    ) for symbol, basis in (("A", 900), ("B", 900), ("C", 900), ("z-loss", 1200)))
    tax_state = portfolio(positions if mixed else (held,), cash=Decimal(0))
    tax_state = tax_state.model_copy(update={"tax_states": (
        tax_state.tax_states[0].model_copy(update={"loss_carryforward_user_input": Decimal(10000)}),
    )})
    tax_engine = decision_engine(tax_rate=Decimal(".20"))
    tax_engine.config = tax_engine.config.model_copy(update={
        "version": version, "horizon_weights": (Decimal(0), Decimal(0), Decimal(1)),
    })
    tax_candidates = (tuple(candidate(p.symbol, -.10) for p in positions) if mixed
                      else (candidate("A", -.10), candidate("B", .50)))
    expected_tax = tax_engine.propose(portfolio=tax_state, candidates=tax_candidates,
                                      generated_at=AS_OF, model_bundle_version="test-model-v1")
    assert expected_tax.estimated_cash_after["bucket"] == (398000 if mixed else 98000)
    assert next(x for x in expected_tax.lines if x.symbol == "B").recommended_shares == 0
    api_proposal = _proposal_view(expected_tax)
    api_proposal["isResearchOnly"] = True  # Explicit browser fixture, never a published proposal.
    withholding_fixtures.append({
        "synthetic_only": True, "portfolio": tax_state.model_dump(mode="json"),
        "candidates": [x.model_dump(mode="json") for x in tax_candidates],
        "config": tax_engine.config.model_dump(mode="json"),
        "cost_policy": tax_engine.cost_engine.policy.model_dump(mode="json"),
        "tax_policy": tax_engine.tax_engine.policy.model_dump(mode="json"),
        "generated_at": AS_OF.isoformat(), "model_bundle_version": "test-model-v1",
        "expected": expected_tax.model_dump(mode="json"),
        "today": {"businessDate": AS_OF.date().isoformat(), "pipelineState": "PROPOSAL_READY",
                  "isStale": False, "blockingReason": None, "runtimeMode": "fixture",
                  "proposal": api_proposal},
    })
with tempfile.TemporaryDirectory(dir=root / ".demo-artifacts") as temporary:
    with MonkeyPatch.context() as patch:
        device, path, store, _, policy = decision_ready.__wrapped__(Path(temporary), patch)
        decision_state = device.export_state()
        from mobile.python import decisions

        decision_fixture = {
            "synthetic_only": True, "state": decision_state, "policy": policy,
            "selection": SELECTION, "now": NOW.isoformat(),
            "expected": decisions.generate(path, store, NOW),
        }
with tempfile.TemporaryDirectory(dir=root / ".demo-artifacts") as temporary:
    from mobile.python import features, market

    path = Path(temporary) / "mobile.sqlite3"
    cutoff = timely_history(path)
    records = market.feature_inputs(path, cutoff)
    frames = market.feature_inputs(path, cutoff, True)
    feature_expected = features.calculate(records, selection)
    assert features.calculate(frames, selection) == feature_expected
    # The shipped Pandas v1 row identity includes hash(pd.NA): 64-bit PC and
    # wasm32 differ for the master's all-missing nullable round-lot column.
    # Predict the old wasm32 identity from the exact PC source, without
    # changing production identities or ignoring that column in the test.
    from pandas.core.util.hashing import combine_hash_arrays

    from stock_ai.data.contracts import DatasetName

    master = market.SQLiteSource(path).point_in_time(DatasetName.SECURITY_MASTER, cutoff)
    master = master.sort_values(["effective_date", "provider_code"]).reset_index(drop=True)
    assert str(master.round_lot_size.dtype) == "Int64" and master.round_lot_size.isna().all()
    hashes = [pd.util.hash_pandas_object(master[name], index=False).to_numpy() for name in master]
    wasm_na_hash = 2**31 - 1
    hashes[list(master).index("round_lot_size")][:] = wasm_na_hash
    schema = tuple((str(name), str(dtype)) for name, dtype in master.dtypes.items())
    metadata = json.dumps({"dataset": "security_master", "schema": schema}, sort_keys=True).encode()
    wasm_master_id = hashlib.sha256(
        metadata + combine_hash_arrays(iter(hashes), len(hashes)).tobytes()
    ).hexdigest()
    wasm_source_ids = [
        [name, wasm_master_id if name == "security_master" else digest]
        for name, digest in records["source_snapshot_ids"]
    ]
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(path, "mobile.sqlite3")
    feature_input_fixture = {
        "synthetic_only": True, "state": base64.b64encode(archive_bytes.getvalue()).decode(),
        "cutoff": cutoff.isoformat(), "selection": selection, "expected": feature_expected,
        "source_ids": records["source_snapshot_ids"], "daily_rows": len(frames["daily"]),
        "wasm_source_ids": wasm_source_ids, "wasm_na_hash": wasm_na_hash,
    }
destination.write_text(
    json.dumps(
        {"inputs": inputs, "expected": expected, "models": vectors,
         "bundle": {"content": bundle_content, "rows": bundle_rows,
                    "bundle_id": bundle.bundle_id,
                    "sha256": hashlib.sha256(bundle_content.encode()).hexdigest(),
                    "expected": bundle_expected}, "bounded": bounded_fixture,
         "decision": decision_fixture, "feature_inputs": feature_input_fixture,
         "withholding": withholding_fixtures},
        ensure_ascii=False,
        allow_nan=False,
    ),
    encoding="utf-8",
)
print(
    json.dumps(
        {
            "synthetic_only": True,
            "feature_columns": [41, 51],
            "symbols": len(result),
            "output": str(destination),
        }
    )
)
