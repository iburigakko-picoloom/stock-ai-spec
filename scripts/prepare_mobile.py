"""Build an offline runtime from explicit source/package allowlists, never user data."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web/public/python"
SOURCE_FILES = [
    "__init__.py",
    "domain/__init__.py",
    "domain/models.py",
    "data/contracts.py",
    "data/point_in_time.py",
    "data/morning.py",
    "data/normalize.py",
    "data/quality.py",
    "data/production.py",
    "features/__init__.py",
    "features/catalog.py",
    "features/registry.py",
    "features/indicators.py",
    "features/engine.py",
    "features/morning.py",
    "decision/__init__.py",
    "decision/costs.py",
    "decision/tax.py",
    "decision/engine.py",
    "decision/bounded.py",
    "decision/simulator.py",
    "operations/models.py",
    "operations/store.py",
    "operations/daily.py",
    "operations/chatgpt_research.py",
    "operations/chatgpt_manual.py",
    "operations/consultation.py",
    "operations/manual_portfolio.py",
    "operations/manual_settings.py",
    "operations/personal.py",
    "operations/api.py",
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
            raise ValueError(
                "Pinned runtime changed; review/update runtime-integrity.json explicitly"
            )
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
        archive.writestr(
            "stock_ai/data/__init__.py",
            '"""Mobile data namespace; no desktop ingestion imports."""\n',
        )
        archive.writestr(
            "stock_ai/operations/__init__.py",
            '"""Mobile operations namespace; no fixture bootstrap imports."""\n',
        )
        archive.writestr("stock_ai/mobile/__init__.py", "")
        for path in sorted((ROOT / "mobile/python").glob("*.py")):
            archive.writestr("stock_ai/mobile/" + path.name, path.read_bytes())
    selection = next((ROOT / "artifacts/selections/goal3-features").glob("*/*.json"))
    original = json.loads(selection.read_text(encoding="utf-8"))["feature_selection"]
    decision = {
        key: original[key] for key in ("feature_selection_id", "feature_manifest_hash", "horizons")
    }
    with zipfile.ZipFile(OUTPUT / "stock_ai.zip", "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("feature-selection.json", json.dumps(decision, ensure_ascii=False))
        archive.writestr("model-policy.json", (ROOT / "mobile/model-policy.json").read_bytes())
    (OUTPUT / "source-integrity.json").write_text(
        json.dumps(source_hashes, indent=2) + "\n", encoding="utf-8"
    )
    source_commit = os.environ.get("GITHUB_SHA")
    if not source_commit:
        source_commit = subprocess.run(
            ["git", "-c", "safe.directory=" + ROOT.as_posix(), "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    (OUTPUT / "build-info.json").write_text(
        json.dumps({"source_commit": source_commit, "shared_sources": source_hashes}) + "\n",
        encoding="utf-8",
    )
    notices = [
        "StockAI third-party notices. Bundled interpreter/runtime files are unmodified.\n"
        "Pyodide 0.29.3 source: https://github.com/pyodide/pyodide/tree/0.29.3\n"
        "CPython 3.13.2 source: https://github.com/python/cpython/tree/v3.13.2\n"
        "Pyodide dependency recipes/source URLs: "
        "https://github.com/pyodide/pyodide/tree/0.29.3/packages\n"
        "Individual package versions/hashes are in the bundled pyodide-lock.json."
    ]
    for license_file in sorted((ROOT / "mobile/licenses").glob("*.txt")):
        notices.append(license_file.name + "\n" + license_file.read_text(encoding="utf-8"))
    for package in (
        "react",
        "react-dom",
        "scheduler",
        "react-router",
        "react-router-dom",
        "@capacitor/core",
    ):
        package_root = ROOT / "web/node_modules" / package
        candidates = list(package_root.glob("LICENSE*"))
        if not candidates:
            raise ValueError("Missing license notice: " + package)
        notices.append(package + "\n" + candidates[0].read_text(encoding="utf-8"))
    for filename in pin["sha256"]:
        if not filename.endswith(".whl"):
            continue
        with zipfile.ZipFile(OUTPUT / filename) as wheel:
            for name in wheel.namelist():
                if not name.endswith("/") and any(
                    word in Path(name).name.lower() for word in ("license", "copying", "notice")
                ):
                    notices.append(filename + "/" + name + "\n" + wheel.read(name).decode("utf-8"))
    notice_text = "\n\n".join(notices)
    (OUTPUT / "THIRD_PARTY_NOTICES.txt").write_text(notice_text, encoding="utf-8")
    (OUTPUT / "licenses.html").write_text(
        '<!doctype html><html lang="ja"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>StockAI オープンソースの表示</title>"
        '<h1>オープンソースの表示</h1><pre style="white-space:pre-wrap">'
        + html.escape(notice_text)
        + "</pre></html>",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "offline_packages": len(pin["packages"]),
                "shared_python_files": len(source_hashes),
                "models_included": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
