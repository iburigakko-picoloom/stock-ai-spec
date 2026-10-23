"""Create new, synthetic-only PC/WASM parity input; never fit or read owner data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from mobile.python.model_bundle import encoded, parity
from mobile.python.research_ensemble import ResearchEnsembleBundle, average_percentile

from stock_ai.domain.models import ResearchEnsemblePrediction
from stock_ai.operations.daily import PredictionSnapshot, canonical_json, content_id

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".demo-artifacts/android/research-ensemble-golden-v2.json"


def tree(low: int, high: int, scale: float, bias: float,
         permutation: tuple[int, ...] | None = None) -> dict:
    if low == high:
        return {"leaf": (low if permutation is None else permutation[low + 4]) * scale + bias}
    middle = (low + high) // 2
    return {"feature": 0, "threshold": middle + .5, "operator": "<=", "missing_left": True,
            "left": tree(low, middle, scale, bias, permutation),
            "right": tree(middle + 1, high, scale, bias, permutation)}


def generate() -> dict:
    files = sorted((ROOT / "artifacts/selections/goal3-features").glob("*/*.json"))
    if len(files) != 1:
        raise ValueError("Select the unique reviewed feature selection explicitly")
    selected = json.loads(files[0].read_text(encoding="utf-8"))["feature_selection"]
    selection = {key: selected[key] for key in (
        "feature_selection_id", "feature_manifest_hash", "horizons",
    )}
    source_commit = os.environ.get("GITHUB_SHA") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    components, outputs, rows = [], [], {}
    symbols = [str(1000 + index) for index in range(27)]
    for horizon in (5, 20):
        feature = next(h["feature_names"][0] for h in selection["horizons"]
                       if h["horizon"] == horizon)
        rows[str(horizon)] = [{"symbol": symbol, feature: None if i == 5 else float(i // 3 - 4)}
                              for i, symbol in enumerate(symbols)]
        names = []
        for number, task in enumerate(("regression", "regression", "ranking", "ranking")):
            # Different component and horizon orderings make wrong weights and
            # accidentally crossed 5d/20d heads observable, while retaining ties.
            permutations = ((-4, -3, -1, -2, 0, 2, 1, 4, 3),
                            (-4, -3, -2, 1, -1, 0, 3, 2, 4)) if horizon == 5 else (
                            (-4, -3, 0, -1, -2, 3, 2, 1, 4),
                            (-4, -3, -1, 0, 2, -2, 4, 3, 1))
            permutation = permutations[number - 2] if task == "ranking" else None
            scale = (.01 if task == "regression" else 1.) * (number + 1)
            scale *= 1. if horizon == 5 else 1.5
            model = {"schema_version": "stockai-portable-tree-v1", "family": "lightgbm",
                     "task": task, "preprocessor": {"retained": [feature],
                     "lower": {feature: -4.}, "upper": {feature: 4.}, "median": {feature: 0.}},
                     "base_score": 0., "link": "identity", "research_only": True,
                     "trees": [tree(-4, 4, scale, number * .002, permutation)]}
            content = canonical_json(model)
            name = f"SYNTHETIC-h{horizon}-{task}-{number}"
            names.append(name)
            components.append(dict(horizon=horizon, task=task, model_id=name, seed=17,
                                   content=content,
                                   sha256=hashlib.sha256(content.encode()).hexdigest(),
                                   preprocessing_sha256=content_id(model["preprocessor"])))
        outputs.extend([
            dict(horizon=horizon, role="return", output_id=f"return-{horizon}",
                 recipe_version="research-composition-v1", components=names[:2], weights=[.25, .75],
                 weight_source="learned", transform="identity", unit="fractional_return"),
            dict(horizon=horizon, role="ranking", output_id=f"rank-{horizon}",
                 recipe_version="research-composition-v1", components=names,
                 weights=[.1, .2, .3, .4], weight_source="learned",
                 transform="within_date_average_percentile_v1", unit="rank_score",
                 rank_universe="decision_symbols",
                 universe_rule_version="SYNTHETIC-topix-plus-held",
                 universe_evidence_sha256=content_id({"synthetic_symbols": symbols})),
        ])
    populations = {str(h): {"decision_symbols": symbols} for h in (5, 20)}
    metadata = dict(
        created_at="2026-02-02T08:00:00Z", trained_at="2026-02-01T00:00:00Z",
        training_data_cutoff="2026-01-30T00:00:00Z",
        feature_selection_id=selection["feature_selection_id"],
        feature_manifest_hash=selection["feature_manifest_hash"],
        selection_id=content_id({"SYNTHETIC": "ensemble parity selection"}),
        data_snapshot_id=content_id({"SYNTHETIC": "no market data"}),
        source_code_commit=source_commit,
        source_evidence_sha256=content_id({"SYNTHETIC": "manually defined trees, no fitting"}),
        evaluation_receipt_id=content_id({"SYNTHETIC": "arithmetic only, no adoption evidence"}),
        components=components,
    )
    variants = []
    for rank_only in (False, True):
        recipes = [o for o in outputs if not rank_only or o["role"] == "ranking"]
        bundle = ResearchEnsembleBundle.create(**metadata, outputs=recipes)
        content = encoded(bundle)
        expected = parity(content, rows, selection, rank_universes=populations)
        lookup = {(o["horizon"], o["role"]): dict(o["values"]) for o in expected["outputs"]}
        for horizon in (5, 20):
            ranked = [average_percentile([value for _, value in c["values"]])
                      for c in expected["components"] if c["horizon"] == horizon]
            equal = [sum(values[i] for values in ranked) / len(ranked)
                     for i in range(len(symbols))]
            if not any(abs(lookup[horizon, "ranking"][symbol] - equal[i]) > 1e-8
                       for i, symbol in enumerate(symbols)):
                raise AssertionError("Fixture must detect replacing learned rank weights by equal")
        if lookup[5, "ranking"] == lookup[20, "ranking"]:
            raise AssertionError("Fixture must detect crossed horizon outputs")
        predictions = tuple(ResearchEnsemblePrediction(
            symbol=symbol, as_of="2026-02-03T11:30:00+09:00",
            expected_return_5d=lookup.get((5, "return"), {}).get(symbol),
            expected_return_20d=lookup.get((20, "return"), {}).get(symbol),
            rank_score_5d=lookup[5, "ranking"][symbol],
            rank_score_20d=lookup[20, "ranking"][symbol],
            model_version="mobile-bundle:" + bundle.bundle_id,
            feature_version=bundle.feature_manifest_hash, data_snapshot_id=bundle.data_snapshot_id,
        ) for symbol in symbols)
        snapshot = PredictionSnapshot.create(
            schema_version="daily-prediction-snapshot-v2", as_of=predictions[0].as_of,
            generated_at=datetime.fromisoformat("2026-02-03T11:40:00+09:00"),
            data_as_of=datetime.fromisoformat("2026-02-03T10:00:00+09:00"),
            selection_id=bundle.selection_id, model_version=predictions[0].model_version,
            feature_version=bundle.feature_manifest_hash, data_snapshot_id=bundle.data_snapshot_id,
            risk_horizon=None, large_loss_threshold=None, downside_quantile_alpha=None,
            candidate_symbols=tuple(symbols), holding_symbols=("1000", "1001"),
            predictions=predictions,
        )
        research = snapshot.research_symbols()
        if len(research) != 22 or not {"1000", "1001"}.isdisjoint(research[:20]):
            raise AssertionError("Fixture must exercise holdings outside the candidate top20")
        variants.append(dict(name="rank_only" if rank_only else "return_and_rank", content=content,
                             expected=expected, snapshot=snapshot.model_dump(mode="json"),
                             research_symbols=research,
                             ranking_symbols=sorted(
                                 symbols, key=lambda s: (-lookup[20, "ranking"][s], s))))
    return dict(schema_version="SYNTHETIC-research-ensemble-golden-v2", synthetic_only=True,
                no_market_data=True, no_private_models=True, fitted_models=0,
                owner_approval_created=False,
                feature_selection_id=selection["feature_selection_id"],
                feature_manifest_hash=selection["feature_manifest_hash"], rows=rows,
                rank_universes=populations, variants=variants)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args()
    output = options.output.resolve()
    if not output.is_relative_to(ROOT / ".demo-artifacts"):
        raise ValueError("Synthetic golden must remain under .demo-artifacts")
    if output.exists():
        raise FileExistsError("Preserve the existing golden; choose a new --output path")
    value = canonical_json(generate()) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(value)
    written = output.read_bytes()
    print(canonical_json({"path": str(output), "bytes": len(written),
                          "sha256": hashlib.sha256(written).hexdigest(),
                          "synthetic_only": True, "fitted_models": 0}))


if __name__ == "__main__":
    main()
