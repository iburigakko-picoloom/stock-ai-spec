"""Pre-push secret/data review: report paths only, never matching secret values."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
tracked = (
    subprocess.run(
        ["git", "-c", "safe.directory=" + root.as_posix(), "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    .stdout.decode("utf-8")
    .split("\0")
)
patterns = [
    rb"gh[pousr]_[A-Za-z0-9]{30,}",
    rb"github_pat_[A-Za-z0-9_]{40,}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]
live_key = os.environ.get("JQUANTS_API_KEY", "").encode()
problems = []
for name in tracked:
    if not name or not (root / name).is_file():
        continue
    data = (root / name).read_bytes()
    if name.lower().endswith(
        (
            ".jks",
            ".p12",
            ".pfx",
            ".keystore",
            ".parquet",
            ".cbm",
            ".onnx",
            ".pkl",
            ".joblib",
            ".sqlite",
            ".sqlite3",
        )
    ):
        problems.append(name)
    elif any(re.search(pattern, data) for pattern in patterns) or (
        len(live_key) >= 8 and live_key in data
    ):
        problems.append(name)
if problems:
    print(json.dumps({"status": "BLOCKED", "paths": sorted(set(problems))}, ensure_ascii=False))
    raise SystemExit(1)
print(
    json.dumps(
        {"status": "PASS", "tracked_files": len(tracked) - 1, "private_keys_models_market_files": 0}
    )
)
