"""Read-only, snapshot-bound one-feature median replacement diagnostics."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from stock_ai.operations.daily import content_id

from . import forecasts, market, models
from .portable_model import predict
from .research_ensemble import ResearchEnsembleBundle
from .storage import connect


def _receipt(path, store, snapshot_id, now):
    matches = []
    with connect(path) as db:
        for table, phase in (
            ("mobile_forecast_runs", "published"),
            ("mobile_reference_runs", "reference_saved"),
        ):
            rows = db.execute(
                f"SELECT run_id,scope_hash,payload,content_hash,phase FROM {table} "
                "WHERE phase=? ORDER BY sequence",
                (phase,),
            )
            for row in rows:
                value, snapshot = forecasts._checked_with_snapshot(row)
                if snapshot is not None and snapshot.snapshot_id == snapshot_id:
                    if snapshot.generated_at > now:
                        raise ValueError("Forecast was generated after the current time")
                    if (
                        table == "mobile_forecast_runs"
                        and store.prediction_snapshot(snapshot_id) != snapshot
                    ):
                        raise ValueError("Forecast archive differs from receipt")
                    matches.append((value, snapshot))
    if len(matches) != 1:
        raise ValueError("Unique original forecast receipt is unavailable")
    return matches[0]


def _bundle(path, scope, cutoff, selection):
    digest = scope["bundle_sha256"]
    with connect(path) as db:
        row = db.execute(
            "SELECT payload,imported_at FROM mobile_model_bundles WHERE sha256=?", (digest,)
        ).fetchone()
    if row is None or hashlib.sha256(row[0].encode()).hexdigest() != digest:
        raise ValueError("Original bundle unavailable or changed")
    if datetime.fromisoformat(row[1]) > cutoff:
        raise ValueError("Original bundle was imported after the forecast")
    bundle, pin = models.reviewed(row[0], models.policy(), selection)
    if pin["sha256"] != digest or bundle.bundle_id != scope["bundle_id"]:
        raise ValueError("Original bundle identity differs")
    bundle.at(cutoff)
    return bundle


def _single_model(bundle, selection, horizon, role):
    if isinstance(bundle, ResearchEnsembleBundle):
        recipes = [x for x in bundle.outputs if x.horizon == horizon and x.role == role]
        if len(recipes) != 1:
            return None
        recipe = recipes[0]
        # Unsupported compositions must not be presented as if they were a
        # single model. Current selected three heads satisfy these conditions.
        if (
            recipe.transform != "identity"
            or recipe.calibration is not None
            or len(recipe.components) != 1
            or tuple(recipe.weights) != (1.0,)
        ):
            return None
        components = [x for x in bundle.components if x.model_id == recipe.components[0]]
        if len(components) != 1:
            raise ValueError("Original model component is missing")
        return components[0].decoded(selection)
    if role != "return":
        return None
    heads = [x for x in bundle.heads if x.horizon == horizon and x.task == "regression"]
    return None if len(heads) != 1 else heads[0].decoded(selection)


def _rank(symbol, candidate, peers):
    return 1 + sum(
        value > candidate or (value == candidate and name < symbol)
        for name, value in peers
        if name != symbol
    )


def sensitivity(model, row, expected, *, symbol=None, peers=None):
    """Hold other inputs fixed and replace one feature by its model median.

    Deltas describe local counterfactual sensitivity; they do not sum to the
    prediction, estimate causality, or provide SHAP values.
    """
    names = model["preprocessor"]["retained"]
    variants = [row, *[{**row, name: None} for name in names]]
    actual, *replacement = predict(model, variants)
    if actual != expected:
        raise ValueError("Replayed model output differs from saved prediction")
    before_rank = None if peers is None else _rank(symbol, actual, peers)
    entries = []
    for name, alternative in zip(names, replacement, strict=True):
        delta = actual - alternative
        if delta == 0:
            continue
        after_rank = None if peers is None else _rank(symbol, alternative, peers)
        entries.append(
            {
                "feature": name,
                "difference": delta,
                "rankChange": None if peers is None else after_rank - before_rank,
            }
        )
    return {
        "prediction": actual,
        "originalRank": before_rank,
        "positive": sorted(
            (x for x in entries if x["difference"] > 0),
            key=lambda x: (-x["difference"], x["feature"]),
        ),
        "negative": sorted(
            (x for x in entries if x["difference"] < 0),
            key=lambda x: (x["difference"], x["feature"]),
        ),
    }


def read(path: Path, store, symbol: str, snapshot_id: str, now: datetime):
    if (
        not re.fullmatch(r"[A-Z0-9]{4}", symbol)
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise ValueError("Invalid explanation request")
    receipt, snapshot = _receipt(path, store, snapshot_id, now)
    prediction = next((item for item in snapshot.predictions if item.symbol == symbol), None)
    if prediction is None:
        raise ValueError("Symbol was not in the saved prediction")
    scope, proof = receipt["scope"], receipt["data_proof"]
    cutoff = snapshot.as_of
    selection = forecasts.bundled_selection()
    bundle = _bundle(path, scope, cutoff, selection)
    decision_symbols = scope["universe"]["decision_symbols"]
    reference = scope.get("analysis_mode") == "latest_available_reference"
    # Read-only full source reconstruction: do not update the mutable input
    # cache while explaining a historical immutable prediction.
    inputs = market.feature_inputs(
        path,
        cutoff,
        True,
        decision_symbols=decision_symbols,
        **({"reference_only": True} if reference else {}),
    )
    if (
        inputs["as_of"] != cutoff.isoformat()
        or content_id(inputs["source_snapshot_ids"]) != content_id(proof["source_snapshot_ids"])
        or inputs["revision_policy"] != proof["revision_policy"]
    ):
        raise ValueError("Original market source cannot be reproduced")
    features = forecasts.calculate(inputs, selection)
    if (
        features["as_of"] != cutoff.isoformat()
        or content_id(features["features"]) != proof["feature_values_sha256"]
    ):
        raise ValueError("Original feature inputs cannot be reproduced")
    answers = []
    for horizon, role, field in (
        (5, "return", "expected_return_5d"),
        (20, "return", "expected_return_20d"),
        (20, "ranking", "rank_score_20d"),
    ):
        expected = getattr(prediction, field, None)
        model = _single_model(bundle, selection, horizon, role)
        if expected is None or model is None:
            answers.append({"horizon": horizon, "role": role, "available": False})
            continue
        rows = [x for x in features["features"][str(horizon)] if x.get("symbol") == symbol]
        if len(rows) != 1:
            raise ValueError("Original feature row is missing or duplicated")
        peers = None
        if role == "ranking":
            peers = [
                (p.symbol, p.rank_score_20d)
                for p in snapshot.predictions
                if getattr(p, "rank_score_20d", None) is not None
            ]
        answer = sensitivity(model, rows[0], expected, symbol=symbol, peers=peers)
        answers.append({"horizon": horizon, "role": role, "available": True, **answer})
    return {
        "symbol": symbol,
        "snapshotId": snapshot_id,
        "asOf": cutoff.isoformat(),
        "method": "one_feature_training_median_replacement_v1",
        "models": answers,
    }
