from __future__ import annotations

import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from scripts.android_record_fixtures import main


def test_android_record_fixtures_are_synthetic_and_preserve_trade_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "assets"
    monkeypatch.setattr(sys, "argv", ["android_record_fixtures", "--output", str(output)])
    main()
    linked = json.loads((output / "record-reader-fixture.json").read_text(encoding="utf-8"))
    manual = json.loads((output / "manual-trade-fixture.json").read_text(encoding="utf-8"))
    for item in (linked, manual):
        assert item["synthetic_only"] is True
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(item["state"], validate=True))) as archive:
            assert set(archive.namelist()) == {"mobile.sqlite3", "operations.sqlite3"}
            assert archive.read("operations.sqlite3").startswith(b"SQLite format 3\0")
    assert linked["expected_execution"]["decision"]["decision_id"] == "synthetic-record-reader"
    assert len(linked["expected_views"]["/api/v1/executions"]["records"]) == 1
    assert len(linked["expected_after"]["/api/v1/executions"]["records"]) == 2
    assert manual["context"]["holdings"] == []
    assert manual["expected_after"]["/api/v1/execution-entry-context"]["holdings"] == [
        {"symbol": "7203", "accountBucketId": "bucket", "shares": 100}
    ]
    assert manual["expected_after"]["/api/v1/home/ledger"]["portfolio"]["cashValue"] == "149963.25"
    with pytest.raises(FileExistsError):
        main()
