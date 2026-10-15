"""Create monotonic Android metadata without modifying main or exposing secrets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def verify_signing_identity(output: str, expected: str) -> None:
    # New build-tools can report a signer per supported SDK range. All ranges
    # must use the one pinned certificate; a source stamp is a separate key.
    counts = re.findall(r"(?im)^\s*Number of signers:\s*(\d+)\s*$", output)
    digests = re.findall(
        r"(?im)^\s*(?:V\d+(?:\.\d+)?\s+)?Signer[^\r\n]*?certificate SHA-256 digest:"
        r"\s*([0-9a-f:]+)\s*$",
        output,
    )
    actual = {value.replace(":", "").lower() for value in digests}
    if counts != ["1"] or actual != {expected.lower()}:
        raise ValueError("APK signing identity changed or could not be verified")


def main() -> None:
    root = Path(__file__).resolve().parents[1]

    folder = root / "release"
    version = os.environ["STOCKAI_VERSION_NAME"]
    code = int(os.environ["STOCKAI_VERSION_CODE"])
    if not 1 <= code <= 2_100_000_000:
        raise ValueError("Invalid Android versionCode")
    config = json.loads((root / "mobile/version.json").read_text())
    apk = folder / "StockAI.apk"
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    expected_certificate = json.loads((root / "mobile/signing-certificate.json").read_text())[
        "certificate_sha256"
    ]
    signing_output = (folder / "signature.txt").read_text()
    print(signing_output)  # Public certificate metadata only.
    verify_signing_identity(signing_output, expected_certificate)
    notes = "\n".join(
        [
            f"StockAI {version} — 研究用Android APK",
            "",
            "端末内Python計算、口座・保有の保存、APIキー暗号化、GitHub更新確認。",
            "モデル最終採用前です。未採用モデル、履歴不足、API403では最新予測や推奨を表示しません。",
            "実機での導入・更新は未確認。初回台帳・個人比較の接続と最終モデル採用は準備中です。",
            "保有・設定・履歴は同じ署名の更新で維持します。実注文機能はありません。",
            "",
            "このリリースの変更:",
        ]
    )
    previous = subprocess.run(
        ["git", "tag", "--list", "android-v*", "--sort=-version:refname"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    try:
        latest_url = (
            f"https://github.com/{config['releaseRepository']}/releases/latest/download/update.json"
        )
        with urllib.request.urlopen(latest_url, timeout=30) as response:
            latest = json.load(response)
        if code <= int(latest["versionCode"]):
            raise ValueError("Refusing non-increasing published versionCode")
    except urllib.error.HTTPError as error:
        if error.code != 404 or previous:
            raise
    revision_range = f"{previous[0]}..HEAD" if previous else "-10"
    changes = subprocess.run(
        [
            "git",
            "log",
            "--format=- %s (%h)",
            revision_range,
            "--",
            "web",
            "mobile",
            ".github/workflows/android-apk.yml",
            "scripts",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    notes += (
        "\n"
        + changes
        + f"\nSource: {os.environ['GITHUB_SHA']}\nversionCode: {code}\nSHA-256: {digest}\n"
    )
    (folder / "CHANGELOG.md").write_text(notes, encoding="utf-8")
    (folder / "SHA256SUMS").write_text(f"{digest}  StockAI.apk\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1,
        "applicationId": config["applicationId"],
        "versionName": version,
        "versionCode": code,
        "notes": notes,
        "sha256": digest,
        "size": apk.stat().st_size,
        "url": f"https://github.com/{config['releaseRepository']}/releases/download/android-v{version}/StockAI.apk",
        "commit": os.environ["GITHUB_SHA"],
        "researchOnly": True,
    }
    (folder / "update.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"version": version, "versionCode": code, "sha256": digest}))


if __name__ == "__main__":
    main()
