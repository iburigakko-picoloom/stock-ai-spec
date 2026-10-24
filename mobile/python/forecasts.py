"""Device-local calibrated forecasts and recoverable immutable publication."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ai.domain import Prediction, PredictionUncertainty
from stock_ai.domain.models import ResearchEnsemblePrediction, ReturnOnlyPrediction
from stock_ai.operations.daily import PredictionSnapshot, canonical_json, content_id
from stock_ai.operations.store import OperationalConflictError

from . import market, models, universe
from .features import bundled_selection, calculate, predictability_code_sha256
from .model_bundle import ModelBundle
from .portable_model import predict
from .research_ensemble import (
    EnsembleOutput,
    FeaturePredictability,
    ResearchEnsembleBundle,
    average_percentile,
    inference,
)
from .storage import connect

JST = ZoneInfo("Asia/Tokyo")


def initialize(path: Path) -> None:
    with connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS mobile_forecast_runs("
            "sequence INTEGER PRIMARY KEY,run_id TEXT NOT NULL UNIQUE,scope_hash TEXT NOT NULL "
            "UNIQUE,payload TEXT NOT NULL,content_hash TEXT NOT NULL,phase TEXT NOT NULL)"
        )
        db.execute("CREATE TABLE IF NOT EXISTS mobile_forecast_selections("
                   "sequence INTEGER PRIMARY KEY,run_id TEXT NOT NULL,selected_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS mobile_reference_runs("
                   "sequence INTEGER PRIMARY KEY,run_id TEXT NOT NULL UNIQUE,"
                   "scope_hash TEXT NOT NULL "
                   "UNIQUE,payload TEXT NOT NULL,content_hash TEXT NOT NULL,phase TEXT NOT NULL)")


def _select(path, run_id, now):
    with connect(path) as db:
        previous = db.execute("SELECT run_id FROM mobile_forecast_selections "
                              "ORDER BY sequence DESC LIMIT 1").fetchone()
        if previous is None or previous[0] != run_id:
            db.execute("INSERT INTO mobile_forecast_selections VALUES(NULL,?,?)",
                       (run_id, now.isoformat()))


def _checked(row) -> dict:
    identity, scope_hash, payload, digest, phase = row
    value = json.loads(payload)
    if (content_id(value) != digest or value["run_id"] != identity
            or content_id({k: v for k, v in value.items() if k != "run_id"}) != identity
            or value["scope_hash"] != scope_hash or content_id(value["scope"]) != scope_hash):
        raise ValueError("Forecast run receipt changed")
    if value["snapshot"] is not None:
        snapshot = PredictionSnapshot.model_validate(value["snapshot"])
        scope, proof = value["scope"], value["data_proof"]
        if (snapshot.data_snapshot_id != content_id(proof) or proof["membership_and_universe"]
                != scope["universe"] or content_id(proof) != scope["data_proof_hash"]
                or snapshot.as_of.isoformat() != scope["as_of"]
                or snapshot.model_version != "mobile-bundle:" + scope["bundle_id"]
                or snapshot.feature_version != scope["feature_manifest_hash"]
                or snapshot.selection_id != scope["selection_id"]
                or snapshot.large_loss_threshold != scope["large_loss_threshold"]
                or snapshot.downside_quantile_alpha != scope["downside_quantile_alpha"]
                or snapshot.data_as_of != market.receipt_time(proof["latest_source_received_at"])
                or tuple(snapshot.holding_symbols) != tuple(scope["holding_symbols"])):
            raise ValueError("Forecast receipt lineage mismatch")
        if any(key in scope and getattr(snapshot, key) != scope[key]
               for key in ("label_definition", "price_semantics")):
            raise ValueError("Forecast label semantics differ from their receipt")
        if ("feature_calculation_symbols" in proof and proof["feature_calculation_symbols"]
                != sorted(set(scope["universe"]["decision_symbols"]))):
            raise ValueError("Forecast feature calculation scope differs from its universe")
        ensemble = "ensemble_outputs" in scope
        outputs = {(x["horizon"], x["role"] if ensemble else x["task"]): dict(x["values"])
                   for x in value["outputs"]}
        if len(outputs) != len(value["outputs"]):
            raise ValueError("Forecast has duplicate output roles")
        expected_symbols = {x.symbol for x in snapshot.predictions}
        excluded = {x["symbol"] for x in value["excluded_candidates"]}
        candidates = {x["symbol"] for x in scope["universe"]["new_candidates"]}
        if (set(snapshot.candidate_symbols) != candidates - excluded or not excluded <= candidates
                or any(set(output) != expected_symbols for output in outputs.values())):
            raise ValueError("Forecast symbol coverage changed")
        if ensemble:
            _check_ensemble_outputs(value, expected_symbols)
        for prediction in snapshot.predictions:
            if isinstance(prediction, ResearchEnsemblePrediction):
                fields = {(5, "return"): prediction.expected_return_5d,
                          (20, "return"): prediction.expected_return_20d,
                          (5, "ranking"): prediction.rank_score_5d,
                          (20, "ranking"): prediction.rank_score_20d,
                          (20, "quantile"): prediction.downside_quantile,
                          (20, "large_loss"): prediction.large_loss_probability}
                if not ensemble or any(
                    (fields.get(key) is None or values[prediction.symbol] != fields[key])
                    for key, values in outputs.items()
                ) or {key for key, number in fields.items() if number is not None} != set(outputs):
                    raise ValueError("Ensemble forecast differs from preserved output")
                continue
            required = {(5, "regression"), (20, "regression")}
            values = [prediction.expected_return_5d, prediction.expected_return_20d]
            keys = [(5, "regression"), (20, "regression")]
            if isinstance(prediction, Prediction):
                required |= {(20, "quantile"), (20, "large_loss")}
                keys += [(20, "quantile"), (20, "large_loss")]
                values += [prediction.downside_quantile, prediction.large_loss_probability]
                if prediction.uncertainty.standard_error != scope["calibration"]["residual_rmse"]:
                    raise ValueError("Forecast uncertainty differs from calibration")
            elif scope["calibration"] is not None:
                raise ValueError("Return-only forecast cannot invent calibration")
            if set(outputs) != required or [outputs[k][prediction.symbol] for k in keys] != values:
                raise ValueError("Forecast differs from the preserved numerical output")
    return {**value, "phase": phase}


def _predictability_contract(population, evidence):
    return {"rule_version": population.rule_version, "evidence_sha256": evidence,
            **{name: getattr(population, name) for name in (
                "calculation_code_sha256", "feature_selection_id", "feature_manifest_hash",
                "required_history_sessions", "eligible_sha256", "predictable_sha256")}}


def _checked_predictability(value, recipes):
    scope, proof = value["scope"], value["data_proof"]
    population = FeaturePredictability.model_validate(proof["feature_predictability"])
    pins = {(recipe.predictability_rule_version, recipe.predictability_evidence_sha256)
            for recipe in recipes if recipe.rank_universe == "predictable_decision_symbols"}
    evidence = proof["predictability_evidence_sha256"]
    if (pins != {(population.rule_version, evidence)}
            or population.as_of != datetime.fromisoformat(scope["as_of"])
            or population.eligible_symbols != tuple(sorted(scope["universe"]["decision_symbols"]))
            or dict(population.source_snapshot_ids) != dict(proof["source_snapshot_ids"])
            or population.feature_manifest_hash != scope["feature_manifest_hash"]
            or scope["predictability_contract"] != _predictability_contract(population, evidence)
            or set(scope["holding_symbols"]) - set(population.predictable_symbols)):
        raise ValueError("Saved predictable population provenance or held coverage changed")
    abstentions = {symbol for symbol, _ in population.abstentions}
    if ({item["symbol"] for item in value["excluded_candidates"]} != abstentions
            or any(item["reason"] != "FEATURE_HISTORY_UNAVAILABLE"
                   for item in value["excluded_candidates"])):
        raise ValueError("Saved predictable abstentions changed")
    return population


def _check_ensemble_outputs(value, expected_symbols):
    """Recheck the saved composition without rerunning models or changing state."""
    scope = value["scope"]
    recipes = [EnsembleOutput.model_validate(raw) for raw in scope["ensemble_outputs"]]
    predictable = (_checked_predictability(value, recipes) if any(
        recipe.rank_universe == "predictable_decision_symbols" for recipe in recipes) else None)
    if any(recipe.transform != "identity" and (
        recipe.rank_universe not in ("decision_symbols", "predictable_decision_symbols")
        or expected_symbols != set(predictable.predictable_symbols if
            recipe.rank_universe == "predictable_decision_symbols" and predictable is not None
            else scope["universe"]["decision_symbols"])
    ) for recipe in recipes):
        raise ValueError("Saved ensemble ranking population is incomplete")
    components = value.get("component_outputs", [])
    by_id = {item["model_id"]: item for item in components}
    if len(by_id) != len(components) or set(by_id) != set(scope["ensemble_components"]):
        raise ValueError("Saved ensemble components differ from manifest")
    symbols = sorted(expected_symbols)
    for name, item in by_id.items():
        spec = scope["ensemble_components"][name]
        if any(item[key] != spec[key] for key in ("sha256", "horizon", "task")):
            raise ValueError("Saved ensemble component lineage mismatch")
        if [pair[0] for pair in item["values"]] != symbols:
            raise ValueError("Saved ensemble population is incomplete")
    if len(value["outputs"]) != len(scope["ensemble_outputs"]):
        raise ValueError("Saved ensemble outputs are incomplete")
    for recipe, saved in zip(recipes, value["outputs"], strict=True):
        if any(saved[key] != getattr(recipe, key) for key in (
            "horizon", "role", "output_id", "unit", "recipe_version", "rank_universe"
        )):
            raise ValueError("Saved ensemble recipe mismatch")
        if recipe.rank_universe == "predictable_decision_symbols" and any(
            saved.get(key) != getattr(recipe, key) for key in
            ("predictability_rule_version", "predictability_evidence_sha256")
        ):
            raise ValueError("Saved predictable recipe pin changed")
        arrays = [[pair[1] for pair in by_id[name]["values"]] for name in recipe.components]
        if recipe.transform != "identity":
            if saved["rank_universe_sha256"] != content_id(symbols):
                raise ValueError("Saved ensemble ranking population changed")
            arrays = [average_percentile(numbers) for numbers in arrays]
        calculated = [sum(w * numbers[i] for w, numbers in
                          zip(recipe.weights, arrays, strict=True)) for i in range(len(symbols))]
        if recipe.calibration is not None:
            calculated = [recipe.calibration.apply(number) for number in calculated]
        if [list(pair) for pair in saved["values"]] != [list(pair) for pair in
                zip(symbols, calculated, strict=True)]:
            raise ValueError("Saved ensemble composition changed")


def _publish(path: Path, store, value: dict) -> dict:
    if value["scope"].get("analysis_mode") == "latest_available_reference":
        raise ValueError("Reference analysis cannot become an active forecast")
    if value["snapshot"] is not None:
        snapshot = PredictionSnapshot.model_validate(value["snapshot"])
        # An intent is saved first. A crash between the two databases can retry
        # this immutable append without retimestamping or recomputing output.
        store.append_prediction_snapshot(
            snapshot, expected_manual_revision_id=value["scope"]["manual_revision_id"],
            expected_portfolio_id=value["scope"]["ledger_portfolio_id"],
            mobile_run_id=value["run_id"],
        )
        with connect(path) as db:
            db.execute("UPDATE mobile_forecast_runs SET phase='published' WHERE run_id=?",
                       (value["run_id"],))
        value["phase"] = "published"
    else:
        store.select_mobile_numerical_without_snapshot(
            value["run_id"], datetime.fromisoformat(value["scope"]["as_of"]),
            value["scope"]["manual_revision_id"], value["scope"]["ledger_portfolio_id"],
        )
    return value


def _save(path: Path, store, scope: dict, now: datetime, *, snapshot=None,
          outputs=(), excluded=(), blocks=(), proof=None, outcome="blocked",
          component_outputs=None) -> dict:
    scope_hash = content_id(scope)
    body = {"schema_version": "mobile-forecast-run-v1", "scope": scope,
            "scope_hash": scope_hash, "checked_at": now.isoformat(), "outcome": outcome,
            "snapshot": None if snapshot is None else snapshot.model_dump(mode="json"),
            "outputs": list(outputs), "excluded_candidates": list(excluded),
            "blocking_reasons": list(blocks), "data_proof": proof,
            "research_only": True, "order_submission": False}
    if component_outputs is not None:
        body["component_outputs"] = component_outputs
    body["run_id"] = content_id(body)
    reference = scope.get("analysis_mode") == "latest_available_reference"
    table = "mobile_reference_runs" if reference else "mobile_forecast_runs"
    with connect(path) as db:
        db.execute(f"INSERT OR IGNORE INTO {table} VALUES(NULL,?,?,?,?,?)", (
            body["run_id"], scope_hash, canonical_json(body), content_id(body),
            ("reference_saved" if reference else "computed") if snapshot is not None else outcome,
        ))
        row = db.execute(
            f"SELECT run_id,scope_hash,payload,content_hash,phase FROM {table} "
            "WHERE scope_hash=?", (scope_hash,)
        ).fetchone()
    value = _checked(row)
    if reference:
        return value
    _select(path, value["run_id"], now)
    return _publish(path, store, value)


def latest(path: Path) -> dict | None:
    with connect(path) as db:
        selected = db.execute("SELECT run_id FROM mobile_forecast_selections "
                              "ORDER BY sequence DESC LIMIT 1").fetchone()
        row = db.execute(
            "SELECT run_id,scope_hash,payload,content_hash,phase FROM mobile_forecast_runs "
            + ("WHERE run_id=?" if selected is not None else "ORDER BY sequence DESC LIMIT 1"),
            () if selected is None else (selected[0],),
        ).fetchone()
        if selected is not None and row is None:
            raise ValueError("Selected numerical receipt missing")
    return None if row is None else _checked(row)


def latest_reference(path: Path, now: datetime, *, saved_only=False) -> dict | None:
    with connect(path) as db:
        rows = db.execute(
            "SELECT run_id,scope_hash,payload,content_hash,phase FROM mobile_reference_runs "
            + ("WHERE phase='reference_saved' " if saved_only else "")
            + "ORDER BY sequence DESC"
        )
        for row in rows:
            value = _checked(row)
            if value["scope"].get("analysis_mode") != "latest_available_reference":
                raise ValueError("Reference run mode changed")
            if datetime.fromisoformat(value["checked_at"]) <= now:
                return value
    return None


def reference_view(path: Path, now: datetime) -> dict | None:
    value = latest_reference(path, now, saved_only=True)
    if value is None:
        return None
    snapshot = PredictionSnapshot.model_validate(value["snapshot"])
    predictions = {item.symbol: item for item in snapshot.predictions}
    return {"snapshotId": snapshot.snapshot_id, "asOf": snapshot.as_of.isoformat(),
            "generatedAt": snapshot.generated_at.isoformat(),
            "dataAsOf": snapshot.data_as_of.isoformat(),
            "modelVersion": snapshot.model_version, "readOnly": True,
            "analysisKind": "latest_available_reference",
            "priceDate": value["scope"]["universe"]["latest_source_date"],
            "holdingSymbols": snapshot.holding_symbols,
            "predictions": [predictions[s].model_dump(mode="json")
                            for s in snapshot.research_symbols()]}


def reconcile_publications(path: Path, store) -> None:
    with connect(path) as db:
        rows = db.execute(
            "SELECT run_id,scope_hash,payload,content_hash,phase FROM mobile_forecast_runs "
            "WHERE phase='computed' ORDER BY sequence"
        ).fetchall()
        for row in rows:
            value = _checked(row)
            snapshot = PredictionSnapshot.model_validate(value["snapshot"])
            try:
                saved = store.prediction_snapshot(snapshot.snapshot_id)
            except KeyError:
                continue
            if saved != snapshot:
                raise ValueError("Published forecast differs from its computation receipt")
            db.execute("UPDATE mobile_forecast_runs SET phase='published' WHERE run_id=?",
                       (value["run_id"],))


    selected = latest(path)
    if selected is None:
        return
    try:
        if selected["phase"] == "published":
            # Recover selection only from an identical existing archive. Never
            # turn an uncommitted computation into a new snapshot on startup.
            snapshot = PredictionSnapshot.model_validate(selected["snapshot"])
            if store.prediction_snapshot(snapshot.snapshot_id) != snapshot:
                raise ValueError("Selected forecast archive differs from receipt")
            store.append_prediction_snapshot(
                snapshot, expected_manual_revision_id=selected["scope"]["manual_revision_id"],
                expected_portfolio_id=selected["scope"]["ledger_portfolio_id"],
                mobile_run_id=selected["run_id"],
            )
        else:
            store.select_mobile_numerical_without_snapshot(
                selected["run_id"], datetime.fromisoformat(selected["scope"]["as_of"]),
                selected["scope"]["manual_revision_id"], selected["scope"]["ledger_portfolio_id"],
            )
    except OperationalConflictError:
        # Historical receipts remain restorable after personal inputs change.
        # Their proposal guard independently prevents current use.
        pass


def generate(path: Path, store, now: datetime, *, reference_only=False) -> dict:
    if now.tzinfo is None:
        raise ValueError("Aware forecast execution time required")
    cutoff = (now.astimezone(JST) if reference_only else
              now.astimezone(JST).replace(hour=11, minute=30, second=0, microsecond=0))
    manual, ledger = store.latest_manual_portfolio(), store.latest_portfolio()
    scope = {"as_of": cutoff.isoformat(),
             "manual_revision_id": None if manual is None else manual.export.revision_id,
             "ledger_portfolio_id": None if ledger is None else ledger.portfolio_id}
    if reference_only:
        scope["analysis_mode"] = "latest_available_reference"
    def blocked(code):
        return _save(path, store, {**scope, "blocked": code}, now, blocks=(code,))
    if now < cutoff:
        return blocked("ALPHA_CUTOFF_OPEN")
    if manual is None or ledger is None or manual.portfolio.holdings_status == "unrecorded":
        return blocked("PERSONAL_HOLDINGS_UNCONFIRMED")
    if max(manual.received_at, manual.export.saved_at, ledger.as_of) > cutoff:
        return blocked("PERSONAL_INPUT_AFTER_ALPHA_CUTOFF")
    with connect(store.path) as db:
        receipt = db.execute("SELECT created_at FROM portfolio_states WHERE portfolio_id=?",
                             (ledger.portfolio_id,)).fetchone()
    if receipt is None or datetime.fromisoformat(receipt[0]) > cutoff:
        return blocked("LEDGER_RECEIVED_AFTER_ALPHA_CUTOFF")
    held = sorted({p.symbol for p in ledger.positions if p.shares > 0})
    if set(held) != set(manual.portfolio.holding_symbols):
        return blocked("HOLDINGS_NEED_RECONCILIATION")
    scope["holding_symbols"] = held
    selection = universe.select(path, cutoff, held, **(
        {"reference_only": True} if reference_only else {"current_membership": True}))
    scope["universe"] = selection
    if selection["blocking_reasons"]:
        return blocked("UNIVERSE_" + selection["blocking_reasons"][0].upper())
    try:
        bundle, pin = models.load_bundle(path, cutoff)
    except (ValueError, KeyError, TypeError):
        return blocked("CALIBRATED_MODEL_BUNDLE_UNAVAILABLE")
    scope.update(bundle_sha256=pin["sha256"], bundle_id=bundle.bundle_id,
                 selection_id=bundle.selection_id, large_loss_threshold=bundle.large_loss_threshold,
                 downside_quantile_alpha=bundle.downside_quantile_alpha,
                 label_definition=bundle.label_definition, price_semantics=bundle.price_semantics,
                 feature_manifest_hash=bundle.feature_manifest_hash,
                 calibration=(None if bundle.calibration is None else
                              bundle.calibration.model_dump(mode="json")))
    if isinstance(bundle, ResearchEnsembleBundle):
        if any(recipe.rank_universe == "all_market_symbols" for recipe in bundle.outputs):
            # The candidate-only feature cache cannot certify an all-market rank.
            return blocked("ENSEMBLE_REQUIRES_ALL_MARKET_FEATURES")
        if any(recipe.rank_universe is not None and recipe.universe_rule_version
               != selection["policy"] for recipe in bundle.outputs):
            return blocked("ENSEMBLE_UNIVERSE_RULE_MISMATCH")
        if any(recipe.horizon != 20 and recipe.role in ("quantile", "large_loss")
               for recipe in bundle.outputs):
            return blocked("ENSEMBLE_UNSUPPORTED_RISK_HORIZON")
        scope["ensemble_outputs"] = [recipe.model_dump(mode="json") for recipe in bundle.outputs]
        scope["ensemble_components"] = {
            component.model_id: {key: getattr(component, key)
                                 for key in ("sha256", "horizon", "task")}
            for component in bundle.components
        }
    if not selection["decision_symbols"]:
        return _save(path, store, scope, now, outcome="cash_only")
    options = ({"preselected": True}
               if selection.get("policy") == "jquants-scalecat-topix500-v1" else {})
    if reference_only:
        options["reference_only"] = True
    inputs = market.feature_inputs(path, now, True,
                                   decision_symbols=selection["decision_symbols"], **options)
    if reference_only and inputs.get("reference_price_date") != selection["latest_source_date"]:
        return blocked("REFERENCE_MARKET_DATE_MISMATCH")
    predictable_recipes = ([recipe for recipe in bundle.outputs
                           if recipe.rank_universe == "predictable_decision_symbols"]
                          if isinstance(bundle, ResearchEnsembleBundle) else [])
    features = calculate(inputs, bundled_selection(),
                         **({"include_predictability": True} if predictable_recipes else {}))
    if inputs["as_of"] != cutoff.isoformat() or features["as_of"] != cutoff.isoformat():
        raise ValueError("Feature cutoff mismatch")
    maps = {}
    decision_symbols = set(selection["decision_symbols"])
    for horizon in (5, 20):
        rows = features["features"][str(horizon)]
        by_symbol = {row["symbol"]: row for row in rows}
        if len(by_symbol) != len(rows):
            raise ValueError("Feature provenance mismatch")
        for row in rows:
            feature_as_of = datetime.fromisoformat(row["available_at"].replace("Z", "+00:00"))
            # Retained history can include securities outside today's frozen
            # candidates/holdings. Preserve its hash, without treating its last
            # quote as a current decision or allowing future/naive timestamps.
            if (feature_as_of.tzinfo is None or feature_as_of > cutoff
                    or (row["symbol"] in decision_symbols and feature_as_of != cutoff)):
                raise ValueError("Feature provenance mismatch")
        maps[horizon] = by_symbol
    proof = {"source_snapshot_ids": inputs["source_snapshot_ids"],
             "security_master_sources": market.master_references(path, cutoff),
             "revision_policy": inputs["revision_policy"],
             "feature_values_sha256": content_id(features["features"]),
             "membership_and_universe": selection}
    if "input_cache" in inputs:
        proof["input_preparation"] = {
            key: inputs["input_cache"][key]
            for key in ("code_version", "cache_schema_version", "common_population")
        }
    if "decision_symbols" in inputs:
        if inputs["decision_symbols"] != sorted(decision_symbols):
            raise ValueError("Feature calculation domain mismatch")
        proof["feature_calculation_symbols"] = inputs["decision_symbols"]
    source_ids = dict(inputs["source_snapshot_ids"])
    if (len(source_ids) != 5 or set(source_ids) != {x.value for x in market.DatasetName}
            or any(not re.fullmatch(r"[0-9a-f]{64}", x) for x in source_ids.values())):
        raise ValueError("Complete feature source lineage required")
    membership_received = selection.get("membership_received_at")
    if reference_only and membership_received is None:
        membership_received = max(x["received_at"] for x in selection["sources"])
    data_as_of = max(market.receipt_time(inputs["latest_source_received_at"]),
                     market.receipt_time(membership_received))
    if data_as_of > cutoff:
        raise ValueError("Source receipt after alpha cutoff")
    proof["latest_source_received_at"] = data_as_of.isoformat()
    population = None
    if predictable_recipes:
        try:
            population = FeaturePredictability.model_validate(features["predictability_proof"])
            if (population.as_of != cutoff
                    or population.eligible_symbols != tuple(sorted(decision_symbols))
                    or population.feature_selection_id != bundle.feature_selection_id
                    or population.feature_manifest_hash != bundle.feature_manifest_hash
                    or population.calculation_code_sha256 != predictability_code_sha256()
                    or population.required_history_sessions != features["required_history_sessions"]
                    or dict(population.source_snapshot_ids) != dict(inputs["source_snapshot_ids"])):
                raise ValueError("ENSEMBLE_PREDICTABILITY_PROOF_INVALID")
            if set(maps[5]) != set(maps[20]):
                raise ValueError("ENSEMBLE_PREDICTABLE_HORIZON_POPULATIONS_DIFFER")
            if set(maps[5]) != set(population.predictable_symbols):
                raise ValueError("ENSEMBLE_FEATURE_POPULATION_MISMATCH")
        except (KeyError, TypeError, ValueError) as error:
            code = (str(error) if str(error).startswith("ENSEMBLE_") else
                    "ENSEMBLE_PREDICTABILITY_PROOF_INVALID")
            return _save(path, store, scope, now, proof=proof, blocks=[code], component_outputs=[])
        evidence = predictable_recipes[0].predictability_evidence_sha256
        proof["feature_predictability"] = population.model_dump(mode="json")
        proof["predictability_evidence_sha256"] = evidence
        scope["predictability_contract"] = _predictability_contract(population, evidence)
    scope["data_proof_hash"] = content_id(proof)
    table = "mobile_reference_runs" if reference_only else "mobile_forecast_runs"
    with connect(path) as db:
        existing = db.execute(
            f"SELECT run_id,scope_hash,payload,content_hash,phase FROM {table} "
            "WHERE scope_hash=?", (content_id(scope),)
        ).fetchone()
    if existing is not None:
        if reference_only:
            return _checked(existing)
        _select(path, existing[0], now)
        return _publish(path, store, _checked(existing))
    usable = set(maps[5]) & set(maps[20]) & set(selection["decision_symbols"])
    missing_held = sorted(set(held) - usable)
    excluded = [{"symbol": x["symbol"], "reason": "FEATURE_HISTORY_UNAVAILABLE"}
                for x in selection["new_candidates"] if x["symbol"] not in usable]
    symbols = sorted(usable)
    outputs, component_outputs = [], None
    if predictable_recipes and missing_held:
        return _save(path, store, scope, now, excluded=excluded, proof=proof,
                     blocks=["HELD_FORECAST_MISSING:" + s for s in missing_held],
                     component_outputs=[])
    if isinstance(bundle, ResearchEnsembleBundle) and not symbols:
        return _save(path, store, scope, now, excluded=excluded, proof=proof,
                     outcome="cash_only" if not excluded and not missing_held else "blocked",
                     blocks=(["HELD_FORECAST_MISSING:" + s for s in missing_held]
                             or (["NO_USABLE_FORECAST"] if excluded else [])),
                     component_outputs=[])
    if (isinstance(bundle, ResearchEnsembleBundle) and usable != decision_symbols
            and any(recipe.rank_universe == "decision_symbols" for recipe in bundle.outputs)):
        # The recipe names the frozen decision population. A feature abstention
        # cannot silently redefine every peer's percentile score.
        return _save(path, store, scope, now, excluded=excluded, proof=proof,
                     blocks=["ENSEMBLE_RANK_POPULATION_INCOMPLETE",
                             *["HELD_FORECAST_MISSING:" + s for s in missing_held]],
                     component_outputs=[])
    if isinstance(bundle, ResearchEnsembleBundle):
        populations = {str(h): {"decision_symbols": sorted(decision_symbols)} for h in (5, 20)}
        if population is not None:
            for declared in populations.values():
                declared.update(predictable_decision_symbols=list(population.predictable_symbols),
                                predictability_proof=population.model_dump(mode="json"),
                                predictability_evidence_sha256=proof["predictability_evidence_sha256"])
        try:
            result = inference(bundle, {str(h): [maps[h][s] for s in symbols] for h in (5, 20)},
                               bundled_selection(), rank_universes=populations)
        except (ValueError, KeyError, TypeError):
            if not predictable_recipes:
                raise
            return _save(path, store, scope, now, excluded=excluded, proof=proof,
                         blocks=["ENSEMBLE_COMPONENT_PREDICTION_INVALID"], component_outputs=[])
        outputs, component_outputs = result["outputs"], result["components"]
    else:
        for head in bundle.heads:
            rows = [maps[head.horizon][symbol] for symbol in symbols]
            values = predict(head.decoded(bundled_selection()), rows)
            outputs.append({"model_id": head.model_id, "sha256": head.sha256,
                            "horizon": head.horizon, "task": head.task,
                            "values": list(zip(symbols, values, strict=True))})
    if missing_held:
        return _save(path, store, scope, now, outputs=outputs, excluded=excluded,
                     blocks=["HELD_FORECAST_MISSING:" + x for x in missing_held], proof=proof,
                     component_outputs=component_outputs)
    if not symbols:
        return _save(path, store, scope, now, outputs=outputs, excluded=excluded, proof=proof,
                     outcome="cash_only" if not excluded else "blocked",
                     blocks=() if not excluded else ("NO_USABLE_FORECAST",))
    heads = {(x["horizon"], x["role"] if isinstance(bundle, ResearchEnsembleBundle) else x["task"]):
             dict(x["values"]) for x in outputs}
    model_version = "mobile-bundle:" + bundle.bundle_id
    predictions = []
    for symbol in symbols:
        if isinstance(bundle, ResearchEnsembleBundle):
            def number(horizon, role, current_symbol=symbol):
                return heads.get((horizon, role), {}).get(current_symbol)
            predictions.append(ResearchEnsemblePrediction(
                symbol=symbol, as_of=cutoff, model_version=model_version,
                feature_version=bundle.feature_manifest_hash, data_snapshot_id=content_id(proof),
                expected_return_5d=number(5, "return"), expected_return_20d=number(20, "return"),
                rank_score_5d=number(5, "ranking"), rank_score_20d=number(20, "ranking"),
                downside_quantile=number(20, "quantile"),
                large_loss_probability=number(20, "large_loss"),
                risk_horizon=20 if bundle.large_loss_threshold is not None or
                bundle.downside_quantile_alpha is not None else None,
            ))
            continue
        common = dict(
            symbol=symbol, as_of=cutoff,
            expected_return_5d=heads[5, "regression"][symbol],
            expected_return_20d=heads[20, "regression"][symbol],
            model_version=model_version, feature_version=bundle.feature_manifest_hash,
            data_snapshot_id=content_id(proof),
        )
        if isinstance(bundle, ModelBundle):
            predictions.append(Prediction(
                **common, schema_version=2, active_horizons=(5, 20), risk_horizon=20,
                expected_return_1d=None, downside_quantile=heads[20, "quantile"][symbol],
                large_loss_probability=heads[20, "large_loss"][symbol],
                uncertainty=PredictionUncertainty(
                    standard_error=bundle.calibration.residual_rmse, model_disagreement=0,
                    coverage_warning="Received past-only 20d residual RMSE; not a "
                    "confidence interval; single candidate per horizon",
                ),
            ))
        else:
            predictions.append(ReturnOnlyPrediction(**common))
    snapshot = PredictionSnapshot.create(
        **({"schema_version": "daily-prediction-snapshot-v2"}
           if isinstance(bundle, ResearchEnsembleBundle) else {}),
        as_of=cutoff, generated_at=now, data_as_of=data_as_of,
        selection_id=bundle.selection_id, model_version=model_version,
        feature_version=bundle.feature_manifest_hash, data_snapshot_id=content_id(proof),
        label_definition=bundle.label_definition, price_semantics=bundle.price_semantics,
        large_loss_threshold=bundle.large_loss_threshold,
        downside_quantile_alpha=bundle.downside_quantile_alpha,
        risk_horizon=20 if (isinstance(bundle, ModelBundle)
                            or bundle.large_loss_threshold is not None
                            or bundle.downside_quantile_alpha is not None) else None,
        candidate_symbols=tuple(sorted(
            {x["symbol"] for x in selection["new_candidates"]} & usable
        )),
        holding_symbols=tuple(held), predictions=tuple(predictions),
    )
    # The shared store rechecks immutability; concurrent input changes must not
    # publish a snapshot with a different set of holdings than the frozen scope.
    if store.latest_manual_portfolio() != manual or store.latest_portfolio() != ledger:
        raise ValueError("Forecast personal inputs changed during calculation")
    return _save(path, store, scope, now, snapshot=snapshot, outputs=outputs,
                 excluded=excluded, proof=proof, outcome="forecast",
                 component_outputs=component_outputs)
