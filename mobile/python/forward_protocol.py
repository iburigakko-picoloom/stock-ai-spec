"""Device-local research registration and immutable, source-linked outcome snapshots.

These records do not authenticate the device clock or independently preregister a
study. They cannot authorize adoption, trading, or retrospective evaluation.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_ai.operations.daily import DAILY_NEXT_SESSION_CLOSE_LABEL, canonical_json, content_id

from . import forecasts, market, models, stock_chart, universe
from .storage import connect

JST = ZoneInfo("Asia/Tokyo")
_PROTOCOL = "local-forward-observation-v1"


def _aware(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("A timezone-aware time is required")
    return now.astimezone(UTC)


def _exists(db, table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (table,)).fetchone()


def _init(db):
    db.execute("CREATE TABLE IF NOT EXISTS forward_registrations("
               "registration_id TEXT PRIMARY KEY,model_version TEXT NOT NULL UNIQUE,"
               "payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS forward_observations("
               "observation_id TEXT PRIMARY KEY,evidence_hash TEXT NOT NULL UNIQUE,"
               "registration_id TEXT NOT NULL,"
               "run_id TEXT NOT NULL,horizon INTEGER NOT NULL,payload TEXT NOT NULL)")


def _checked(identity, payload):
    value = json.loads(payload)
    if content_id(value) != identity:
        raise ValueError("Forward evidence changed")
    return value


def registrations(path: Path):
    with connect(path) as db:
        if not _exists(db, "forward_registrations"):
            return []
        rows = db.execute("SELECT registration_id,payload FROM forward_registrations "
                          "ORDER BY rowid").fetchall()
    return [{"registration_id": identity, **_checked(identity, payload)}
            for identity, payload in rows]


def observations(path: Path):
    with connect(path) as db:
        if not _exists(db, "forward_observations"):
            return []
        rows = db.execute("SELECT observation_id,evidence_hash,payload FROM forward_observations "
                          "ORDER BY rowid DESC LIMIT 20").fetchall()
    result = []
    for identity, digest, payload in rows:
        record = _checked(identity, payload)
        evidence = record["evidence"]
        if content_id(evidence) != digest:
            raise ValueError("Forward observation changed")
        result.append({"observation_id": identity, "observed_at": record["observed_at"],
                       **{key: evidence[key] for key in ("registration_id", "run_id", "horizon",
                          "count", "scored_count", "mean_absolute_error", "rank_scored_count",
                          "conditional_rank_correlation")}})
    return result


def observation(path: Path, identity: str):
    with connect(path) as db:
        if not _exists(db, "forward_observations"):
            raise ValueError("Forward observation not found")
        row = db.execute("SELECT evidence_hash,payload FROM forward_observations "
                         "WHERE observation_id=?", (identity,)).fetchone()
    if row is None:
        raise ValueError("Forward observation not found")
    digest, payload = row
    record = _checked(identity, payload)
    if content_id(record["evidence"]) != digest:
        raise ValueError("Forward observation changed")
    return {"observation_id": identity, **record}


def register(path: Path, now: datetime):
    """Fix the currently selected reviewed bundle before future local-day forecasts."""
    now = _aware(now)
    bundle, entry = models.load_bundle(path, now)
    if bundle.label_definition != DAILY_NEXT_SESSION_CLOSE_LABEL:
        raise ValueError("Unsupported prediction target")
    model_version = "mobile-bundle:" + bundle.bundle_id
    local_next_day = now.astimezone(JST).date() + timedelta(days=1)
    starts = datetime.combine(local_next_day, time.min, JST).astimezone(UTC)
    record = {
        "schema_version": _PROTOCOL,
        "registered_at": now.isoformat(),
        "eligible_from": starts.isoformat(),
        "model_version": model_version,
        "bundle_sha256": entry["sha256"],
        "selection_id": bundle.selection_id,
        "feature_manifest_hash": bundle.feature_manifest_hash,
        "label_definition": bundle.label_definition,
        "horizons": [5, 20],
        "metrics": ["absolute_error", "coverage", "conditional_spearman_20d"],
        "price_revision_policy": "latest_received_at_observation",
        "costs_taxes_dividends_included": False,
        "external_time_authenticated": False,
        "formal_evaluation": False,
    }
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        _init(db)
        previous = db.execute("SELECT registration_id,payload FROM forward_registrations "
                              "WHERE model_version=?", (model_version,)).fetchone()
        if previous:
            old = _checked(*previous)
            if _aware(datetime.fromisoformat(old["registered_at"])) > now:
                raise ValueError("Device clock moved backwards")
            if (old["bundle_sha256"] != entry["sha256"]
                    or old["selection_id"] != bundle.selection_id
                    or old["feature_manifest_hash"] != bundle.feature_manifest_hash):
                raise ValueError("Registered model identity changed")
            return {"registration_id": previous[0], **old}
        identity = content_id(record)
        db.execute("INSERT INTO forward_registrations VALUES(?,?,?)",
                   (identity, model_version, canonical_json(record)))
    return {"registration_id": identity, **record}


def _run(path, store, registration, run_id, horizon, now):
    if horizon not in (5, 20):
        raise ValueError("Unsupported horizon")
    with connect(path) as db:
        row = db.execute("SELECT run_id,scope_hash,payload,content_hash,phase "
                         "FROM mobile_forecast_runs WHERE run_id=? AND phase='published'",
                         (run_id,)).fetchone()
    if row is None:
        raise ValueError("Published daily forecast is unavailable")
    receipt, snapshot = forecasts._checked_with_snapshot(row)
    if snapshot is None or store.prediction_snapshot(snapshot.snapshot_id) != snapshot:
        raise ValueError("Daily forecast archive changed")
    starts = _aware(datetime.fromisoformat(registration["eligible_from"]))
    if (snapshot.as_of < starts or snapshot.generated_at < starts or snapshot.generated_at > now
            or snapshot.model_version != registration["model_version"]
            or snapshot.selection_id != registration["selection_id"]
            or snapshot.feature_version != registration["feature_manifest_hash"]
            or snapshot.label_definition != registration["label_definition"]):
        raise ValueError("Forecast is outside the registered protocol")
    price_day = date.fromisoformat(receipt["scope"]["universe"]["latest_source_date"])
    last = now.astimezone(JST).date() - timedelta(days=1)
    if price_day > last or (last - price_day).days > 730:
        raise ValueError("Forecast price date is outside the available window")
    # Bound one read; normal 20-session windows fit, and an unusually prolonged
    # closure remains pending instead of scanning an unbounded market history.
    return receipt, snapshot, price_day, min(last, price_day + timedelta(days=90))


def _spearman(pairs):
    """Spearman correlation with average ranks for ties; undefined stays null."""
    if len(pairs) < 2:
        return None

    def ranks(values):
        order = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            mean_rank = (start + 1 + end) / 2
            for index in order[start:end]:
                result[index] = mean_rank
            start = end
        return result

    left = ranks([p[0] for p in pairs])
    right = ranks([p[1] for p in pairs])
    center = (len(pairs) + 1) / 2
    a = [value - center for value in left]
    b = [value - center for value in right]
    denominator = math.sqrt(sum(value * value for value in a) * sum(value * value for value in b))
    if denominator == 0:
        return None
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b, strict=True)) / denominator))


def observe(path: Path, store, registration_id: str, run_id: str, horizon: int, now: datetime):
    """Snapshot observed outcomes and source versions without changing forecasts or holdings."""
    now = _aware(now)
    items = registrations(path)
    registration = next((x for x in items if x["registration_id"] == registration_id), None)
    if registration is None:
        raise ValueError("Forward registration not found")
    if now < _aware(datetime.fromisoformat(registration["registered_at"])):
        raise ValueError("Device clock moved backwards")
    receipt, snapshot, price_day, last = _run(path, store, registration, run_id, horizon, now)
    first = price_day + timedelta(days=1)
    calendar, calendar_sources, calendar_divisions = {}, {}, {}
    for _, rows, source in universe._observations(
        path, "trading_calendar", first - timedelta(days=21), last, now
    ):
        for row in rows:
            day = date.fromisoformat(row["Date"])
            if first <= day <= last:
                division = str(row["HolDiv"])
                if division not in {"0", "1", "2", "3"}:
                    raise ValueError("Unknown trading calendar division")
                calendar[str(day)] = division in {"1", "2"}
                calendar_sources[str(day)] = source
                calendar_divisions[str(day)] = division
    symbols = {p.symbol for p in snapshot.predictions}
    prices = {symbol: {} for symbol in symbols}
    price_sources = {}
    for day, rows, source in universe._observations(path, "daily_prices", first, last, now):
        if any(row.get("Date") != day for row in rows):
            raise ValueError("Daily source date mismatch")
        # A session's close cannot have been received before it occurred.
        close_time = datetime.combine(date.fromisoformat(day), time(15, 30), JST)
        if market.receipt_time(source["received_at"]) < close_time:
            raise ValueError("Price source predates the session close")
        seen = set()
        for row in rows:
            code = row.get("Code")
            symbol = code[:-1] if isinstance(code, str) and code.endswith("0") else None
            if symbol not in symbols:
                continue
            if symbol in seen:
                raise ValueError("Duplicate symbol in daily source")
            seen.add(symbol)
            prices[symbol][day] = {
                "adjustedClose": stock_chart._number(row.get("AdjC"), positive=True),
                "adjustmentFactor": stock_chart._number(row.get("AdjFactor"), positive=True),
                "exRightsType": row.get("ExRT") or None,
            }
        price_sources[day] = source
    results = []
    rank_pairs = []
    for prediction in snapshot.predictions:
        value = prediction.expected_return_5d if horizon == 5 else prediction.expected_return_20d
        outcome = stock_chart.realized(
            price_day, horizon, last, calendar, prices[prediction.symbol]
        )
        if outcome["entryDate"] is not None:
            entry_close = datetime.combine(
                date.fromisoformat(outcome["entryDate"]), time(15, 30), JST
            )
            if calendar_divisions[outcome["entryDate"]] != "1":
                outcome = {**outcome, "status": "entry_close_unverified", "return": None}
            elif snapshot.generated_at >= entry_close:
                outcome = {**outcome, "status": "forecast_after_entry_close", "return": None}
        actual = outcome["return"]
        rank_score = getattr(prediction, "rank_score_20d", None) if horizon == 20 else None
        if rank_score is not None and actual is not None:
            rank_pairs.append((rank_score, actual))
        error = None if actual is None or value is None else abs(actual - value)
        if error is not None and not math.isfinite(error):
            raise ValueError("Non-finite forecast error")
        results.append({"symbol": prediction.symbol, "expected_return": value,
                        "rank_score": rank_score,
                        "return_prediction_missing": value is None,
                        "actual_return": actual, "absolute_error": error, **{
                            "status": outcome["status"], "entry_date": outcome["entryDate"],
                            "exit_date": outcome["exitDate"]}})
    errors = [x["absolute_error"] for x in results if x["absolute_error"] is not None]
    evidence = {
        "schema_version": "local-forward-outcome-v1", "registration_id": registration_id,
        "run_id": run_id, "snapshot_id": snapshot.snapshot_id, "horizon": horizon,
        "forecast_generated_at": snapshot.generated_at.isoformat(), "price_date": str(price_day),
        "last_closed_date": str(last), "source_calendar": calendar_sources,
        "source_prices": price_sources, "results": results,
        "candidate_exclusions": receipt["excluded_candidates"],
        "count": len(results), "scored_count": len(errors),
        "mean_absolute_error": sum(errors) / len(errors) if errors else None,
        "rank_scored_count": len(rank_pairs),
        "conditional_rank_correlation": _spearman(rank_pairs) if horizon == 20 else None,
        "formal_evaluation": False,
        "execution_return": False, "external_time_authenticated": False,
    }
    # The first observation of a particular exact evidence state is immutable;
    # later source corrections create a separate version rather than replacing it.
    digest = content_id(evidence)
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        _init(db)
        previous = db.execute("SELECT observation_id,payload FROM forward_observations "
                              "WHERE evidence_hash=?", (digest,)).fetchone()
        if previous is not None:
            identity = previous[0]
            record = _checked(*previous)
            if content_id(record["evidence"]) != digest:
                raise ValueError("Forward observation changed")
        else:
            record = {"observed_at": now.isoformat(), "evidence": evidence}
            identity = content_id(record)
            db.execute("INSERT INTO forward_observations VALUES(?,?,?,?,?,?)",
                       (identity, digest, registration_id, run_id, horizon, canonical_json(record)))
    return {"observation_id": identity, **record}
