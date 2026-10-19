"""Device-local calibrated forecasts and recoverable immutable publication."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ai.domain import Prediction, PredictionUncertainty
from stock_ai.operations.daily import PredictionSnapshot, canonical_json, content_id
from stock_ai.operations.store import OperationalConflictError

from . import market, models, universe
from .features import bundled_selection, calculate
from .portable_model import predict
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
        outputs = {(x["horizon"], x["task"]): dict(x["values"]) for x in value["outputs"]}
        expected_symbols = {x.symbol for x in snapshot.predictions}
        excluded = {x["symbol"] for x in value["excluded_candidates"]}
        candidates = {x["symbol"] for x in scope["universe"]["new_candidates"]}
        if (set(snapshot.candidate_symbols) != candidates - excluded or not excluded <= candidates
                or any(set(output) != expected_symbols for output in outputs.values())):
            raise ValueError("Forecast symbol coverage changed")
        for prediction in snapshot.predictions:
            expected = [outputs[key][prediction.symbol] for key in (
                (5, "regression"), (20, "regression"), (20, "quantile"), (20, "large_loss")
            )]
            if expected != [prediction.expected_return_5d, prediction.expected_return_20d,
                            prediction.downside_quantile, prediction.large_loss_probability]:
                raise ValueError("Forecast differs from the preserved numerical output")
            if prediction.uncertainty.standard_error != scope["calibration"]["residual_rmse"]:
                raise ValueError("Forecast uncertainty differs from calibration")
    return {**value, "phase": phase}


def _publish(path: Path, store, value: dict) -> dict:
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
          outputs=(), excluded=(), blocks=(), proof=None, outcome="blocked") -> dict:
    scope_hash = content_id(scope)
    body = {"schema_version": "mobile-forecast-run-v1", "scope": scope,
            "scope_hash": scope_hash, "checked_at": now.isoformat(), "outcome": outcome,
            "snapshot": None if snapshot is None else snapshot.model_dump(mode="json"),
            "outputs": list(outputs), "excluded_candidates": list(excluded),
            "blocking_reasons": list(blocks), "data_proof": proof,
            "research_only": True, "order_submission": False}
    body["run_id"] = content_id(body)
    with connect(path) as db:
        db.execute("INSERT OR IGNORE INTO mobile_forecast_runs VALUES(NULL,?,?,?,?,?)", (
            body["run_id"], scope_hash, canonical_json(body), content_id(body),
            "computed" if snapshot is not None else outcome,
        ))
        row = db.execute(
            "SELECT run_id,scope_hash,payload,content_hash,phase FROM mobile_forecast_runs "
            "WHERE scope_hash=?", (scope_hash,)
        ).fetchone()
    value = _checked(row)
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


def generate(path: Path, store, now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("Aware forecast execution time required")
    cutoff = now.astimezone(JST).replace(hour=11, minute=30, second=0, microsecond=0)
    manual, ledger = store.latest_manual_portfolio(), store.latest_portfolio()
    scope = {"as_of": cutoff.isoformat(),
             "manual_revision_id": None if manual is None else manual.export.revision_id,
             "ledger_portfolio_id": None if ledger is None else ledger.portfolio_id}
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
    selection = universe.select(path, cutoff, held, current_membership=True)
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
                 calibration=bundle.calibration.model_dump(mode="json"))
    if not selection["decision_symbols"]:
        return _save(path, store, scope, now, outcome="cash_only")
    inputs = market.feature_inputs(path, now, True)
    features = calculate(inputs, bundled_selection())
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
    source_ids = dict(inputs["source_snapshot_ids"])
    if (len(source_ids) != 5 or set(source_ids) != {x.value for x in market.DatasetName}
            or any(not re.fullmatch(r"[0-9a-f]{64}", x) for x in source_ids.values())):
        raise ValueError("Complete feature source lineage required")
    data_as_of = max(market.receipt_time(inputs["latest_source_received_at"]),
                     market.receipt_time(selection["membership_received_at"]))
    if data_as_of > cutoff:
        raise ValueError("Source receipt after alpha cutoff")
    proof["latest_source_received_at"] = data_as_of.isoformat()
    scope["data_proof_hash"] = content_id(proof)
    with connect(path) as db:
        existing = db.execute(
            "SELECT run_id,scope_hash,payload,content_hash,phase FROM mobile_forecast_runs "
            "WHERE scope_hash=?", (content_id(scope),)
        ).fetchone()
    if existing is not None:
        _select(path, existing[0], now)
        return _publish(path, store, _checked(existing))
    usable = set(maps[5]) & set(maps[20]) & set(selection["decision_symbols"])
    missing_held = sorted(set(held) - usable)
    excluded = [{"symbol": x["symbol"], "reason": "FEATURE_HISTORY_UNAVAILABLE"}
                for x in selection["new_candidates"] if x["symbol"] not in usable]
    symbols = sorted(usable)
    outputs = []
    for head in bundle.heads:
        rows = [maps[head.horizon][symbol] for symbol in symbols]
        values = predict(head.decoded(bundled_selection()), rows)
        outputs.append({"model_id": head.model_id, "sha256": head.sha256,
                        "horizon": head.horizon, "task": head.task,
                        "values": list(zip(symbols, values, strict=True))})
    if missing_held:
        return _save(path, store, scope, now, outputs=outputs, excluded=excluded,
                     blocks=["HELD_FORECAST_MISSING:" + x for x in missing_held], proof=proof)
    if not symbols:
        return _save(path, store, scope, now, outputs=outputs, excluded=excluded, proof=proof,
                     outcome="cash_only" if not excluded else "blocked",
                     blocks=() if not excluded else ("NO_USABLE_FORECAST",))
    heads = {(x["horizon"], x["task"]): dict(x["values"]) for x in outputs}
    model_version = "mobile-bundle:" + bundle.bundle_id
    snapshot = PredictionSnapshot.create(
        as_of=cutoff, generated_at=now, data_as_of=data_as_of,
        selection_id=bundle.selection_id, model_version=model_version,
        feature_version=bundle.feature_manifest_hash, data_snapshot_id=content_id(proof),
        label_definition=bundle.label_definition, price_semantics=bundle.price_semantics,
        large_loss_threshold=bundle.large_loss_threshold,
        downside_quantile_alpha=bundle.downside_quantile_alpha,
        candidate_symbols=tuple(sorted(
            {x["symbol"] for x in selection["new_candidates"]} & usable
        )),
        holding_symbols=tuple(held), predictions=tuple(
            Prediction(schema_version=2, active_horizons=(5, 20), risk_horizon=20,
                       symbol=symbol, as_of=cutoff, expected_return_1d=None,
                       expected_return_5d=heads[5, "regression"][symbol],
                       expected_return_20d=heads[20, "regression"][symbol],
                       downside_quantile=heads[20, "quantile"][symbol],
                       large_loss_probability=heads[20, "large_loss"][symbol],
                       uncertainty=PredictionUncertainty(
                           standard_error=bundle.calibration.residual_rmse,
                           model_disagreement=0,
                           coverage_warning="Received past-only 20d residual RMSE; not a "
                           "confidence interval; single candidate per horizon",
                       ), model_version=model_version, feature_version=bundle.feature_manifest_hash,
                       data_snapshot_id=content_id(proof))
            for symbol in symbols
        ),
    )
    # The shared store rechecks immutability; concurrent input changes must not
    # publish a snapshot with a different set of holdings than the frozen scope.
    if store.latest_manual_portfolio() != manual or store.latest_portfolio() != ledger:
        raise ValueError("Forecast personal inputs changed during calculation")
    return _save(path, store, scope, now, snapshot=snapshot, outputs=outputs,
                 excluded=excluded, proof=proof, outcome="forecast")
