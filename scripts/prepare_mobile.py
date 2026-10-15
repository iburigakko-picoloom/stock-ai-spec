"""Build an offline runtime from explicit source/package allowlists, never user data."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web/public/python"
SOURCE_FILES = [
    "__init__.py", "domain/__init__.py", "domain/models.py",
    "data/contracts.py", "data/point_in_time.py", "data/morning.py",
    "features/__init__.py", "features/catalog.py", "features/registry.py",
    "features/indicators.py", "features/engine.py", "features/morning.py",
    "decision/__init__.py", "decision/costs.py", "decision/tax.py",
    "decision/engine.py", "decision/simulator.py",
    "operations/models.py", "operations/store.py", "operations/daily.py",
    "operations/manual_portfolio.py", "operations/personal.py", "operations/api.py",
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(name: str, base: str, expected: str | None = None) -> bytes:
    path = OUTPUT / name
    if path.exists() and expected and sha(path.read_bytes()) == expected:
        return path.read_bytes()
    with urllib.request.urlopen(base + name, timeout=120) as response:
        data = response.read()
    if expected and sha(data) != expected:
        raise ValueError("Runtime download hash mismatch: " + name)
    path.write_bytes(data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "mobile/runtime-packages.json").read_text())
    if args.download:
        lock_data = fetch("pyodide-lock.json", config["indexURL"])
        lock = json.loads(lock_data)
        selected: set[str] = set()

        def include(name: str) -> None:
            key = name.replace("_", "-").lower()
            if key in selected:
                return
            selected.add(key)
            for dep in lock["packages"][key]["depends"]:
                include(dep)

        for name in config["packages"]:
            include(name)
        hashes = {"pyodide-lock.json": sha(lock_data)}
        for name in ("pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip"):
            hashes[name] = sha(fetch(name, config["indexURL"]))
        for key in sorted(selected):
            package = lock["packages"][key]
            data = fetch(package["file_name"], config["indexURL"], package["sha256"])
            hashes[package["file_name"]] = sha(data)
        manifest = {"version": config["version"], "packages": sorted(selected), "sha256": hashes}
        # Pin the trust root/core hashes in Git. All later builds must match them.
        pin_path = ROOT / "mobile/runtime-integrity.json"
        if pin_path.exists() and json.loads(pin_path.read_text()) != manifest:
            raise ValueError("Pinned runtime changed; review/update runtime-integrity.json explicitly")
        pin_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    pin = json.loads((ROOT / "mobile/runtime-integrity.json").read_text())
    for name, expected in pin["sha256"].items():
        if sha((OUTPUT / name).read_bytes()) != expected:
            raise ValueError("Offline runtime is incomplete or altered: " + name)
    source_hashes = {}
    with zipfile.ZipFile(OUTPUT / "stock_ai.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in SOURCE_FILES:
            content = (ROOT / "src/stock_ai" / name).read_bytes()
            archive.writestr("stock_ai/" + name, content)
            source_hashes[name] = sha(content)
        # The desktop data facade eagerly imports DuckDB/Arrow ingestion. The
        # mobile package imports the exact concrete calculation modules instead.
        archive.writestr("stock_ai/data/__init__.py", '"""Mobile data namespace; no desktop ingestion imports."""\n')
        archive.writestr("stock_ai/operations/__init__.py", '"""Mobile operations namespace; no fixture bootstrap imports."""\n')
        archive.writestr("stock_ai/mobile/__init__.py", "")
        for path in sorted((ROOT / "mobile/python").glob("*.py")):
            archive.writestr("stock_ai/mobile/" + path.name, path.read_bytes())
    selection = next((ROOT / "artifacts/selections/goal3-features").glob("*/*.json"))
    original = json.loads(selection.read_text(encoding="utf-8"))["feature_selection"]
    decision = {key: original[key] for key in ("feature_selection_id", "feature_manifest_hash", "horizons")}
    with zipfile.ZipFile(OUTPUT / "stock_ai.zip", "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("feature-selection.json", json.dumps(decision, ensure_ascii=False))
    (OUTPUT / "source-integrity.json").write_text(json.dumps(source_hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"offline_packages": len(pin["packages"]), "shared_python_files": len(source_hashes), "models_included": 0}))


if __name__ == "__main__":
    main()
