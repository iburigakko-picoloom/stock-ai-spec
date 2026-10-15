"""Fail closed if a release contains private data, credentials or test fixtures."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

from prepare_mobile import ROOT, SOURCE_FILES


def audit_shared_archive(content: bytes) -> None:
    expected = {"stock_ai/" + name for name in SOURCE_FILES}
    expected.update(
        {
            "stock_ai/data/__init__.py",
            "stock_ai/operations/__init__.py",
            "stock_ai/mobile/__init__.py",
            "feature-selection.json",
            "model-policy.json",
        }
    )
    expected.update(
        "stock_ai/mobile/" + file.name for file in (ROOT / "mobile/python").glob("*.py")
    )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise SystemExit("Unexpected or duplicate files in shared Python archive")
        for name in SOURCE_FILES:
            if archive.read("stock_ai/" + name) != (ROOT / "src/stock_ai" / name).read_bytes():
                raise SystemExit("Shared PC source differs: " + name)
        for file in (ROOT / "mobile/python").glob("*.py"):
            if archive.read("stock_ai/mobile/" + file.name) != file.read_bytes():
                raise SystemExit("Mobile adapter differs: " + file.name)
        if archive.read("model-policy.json") != (ROOT / "mobile/model-policy.json").read_bytes():
            raise SystemExit("Model policy differs from reviewed policy")
        selection = json.loads(archive.read("feature-selection.json"))
        if set(selection) != {"feature_selection_id", "feature_manifest_hash", "horizons"}:
            raise SystemExit("Unexpected feature metadata")


pin = json.loads((ROOT / "mobile/runtime-integrity.json").read_text())

for argument in sys.argv[1:]:
    path = Path(argument)
    if path.is_dir():
        names = [file.relative_to(path).as_posix() for file in path.rglob("*") if file.is_file()]

        def read_file(name, directory=path):
            return (directory / name).read_bytes()
    else:
        package_archive = zipfile.ZipFile(path)
        names = package_archive.namelist()
        read_file = package_archive.read
    shared = [name for name in names if name.split("/")[-2:] == ["python", "stock_ai.zip"]]
    if len(shared) != 1:
        raise SystemExit("Missing or duplicate offline Python package")
    audit_shared_archive(read_file(shared[0]))
    prefix = shared[0].removesuffix("stock_ai.zip")
    for file, digest in pin["sha256"].items():
        if hashlib.sha256(read_file(prefix + file)).hexdigest() != digest:
            raise SystemExit("Bundled runtime hash mismatch: " + file)
    forbidden = [
        name
        for name in names
        if any(
            part in name.lower().split("/")
            for part in (".env", "data", "artifacts", "fixtures", "test-results", "android-signing")
        )
        or name.lower().endswith(
            (
                ".jks",
                ".keystore",
                ".p12",
                ".pfx",
                ".sqlite",
                ".sqlite3",
                ".parquet",
                ".cbm",
                ".onnx",
                ".joblib",
                ".pkl",
            )
        )
    ]
    if forbidden:
        raise SystemExit("Forbidden release paths: " + ", ".join(forbidden))
    print(json.dumps({"package": str(path), "entries": len(names), "private_path_check": "PASS"}))
