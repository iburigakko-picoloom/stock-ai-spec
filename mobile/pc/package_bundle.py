"""Package already exported private heads; never fit, open holdout or approve a model."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from mobile.python.model_bundle import ModelBundle, encoded

from stock_ai.operations.daily import canonical_json, content_id, require_quote_close_label
from stock_ai.operations.manual_portfolio import strict_json


def package(metadata: dict, heads: list[dict], selection: dict) -> tuple[str, dict]:
    bundle = ModelBundle.create(**metadata, heads=heads)
    require_quote_close_label(bundle.label_definition)
    if any(getattr(bundle, key) != selection[key]
           for key in ("feature_selection_id", "feature_manifest_hash")):
        raise ValueError("Bundle differs from the frozen feature selection")
    for head in bundle.heads:
        head.decoded(selection)
    content = encoded(bundle)
    proposal = {
        "sha256": hashlib.sha256(content.encode()).hexdigest(), "bundle_id": bundle.bundle_id,
        "adoption_evidence_sha256": content_id(bundle.adoption_review.model_dump(mode="json")),
        "calibration_evidence_sha256": bundle.calibration.source_evidence_sha256,
        "pc_parity_evidence_sha256": None, "device_parity_evidence_sha256": None,
        "distribution_review": "pending",
    }
    return content, proposal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--heads", type=Path, required=True,
                        help="JSON list of horizon, task, model_id and path to an exported head")
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    metadata = strict_json(options.metadata.read_text(encoding="utf-8"))
    heads = []
    for source in strict_json(options.heads.read_text(encoding="utf-8")):
        path = Path(source["path"])
        if not path.is_absolute():
            path = options.heads.parent / path
        content = path.read_bytes().decode("utf-8")
        heads.append({"horizon": source["horizon"], "task": source["task"],
                      "model_id": source["model_id"], "content": content,
                      "sha256": hashlib.sha256(content.encode()).hexdigest()})
    selection = strict_json(options.selection.read_text(encoding="utf-8"))
    content, proposal = package(metadata, heads, selection.get("feature_selection", selection))
    proposal_path = options.output.with_suffix(".pin-proposal.json")
    if options.output.exists() or proposal_path.exists():
        raise FileExistsError("Keep existing model artifacts; choose a new output path")
    with options.output.open("x", encoding="utf-8") as output:
        output.write(content)
    with proposal_path.open("x", encoding="utf-8") as output:
        output.write(canonical_json(proposal))
    print("Private bundle and unapproved pin proposal saved; approval/parity gates remain.")


if __name__ == "__main__":
    main()
