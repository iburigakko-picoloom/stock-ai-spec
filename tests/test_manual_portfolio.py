from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from stock_ai.operations.cloud import (
    PRIVATE_SITE_ORIGIN,
    portfolio_access_token,
    pull_private_portfolio,
)
from stock_ai.operations.manual_portfolio import (
    ImportedManualPortfolio,
    ManualPortfolio,
    digest,
    strict_json,
)
from stock_ai.operations.store import (
    OperationalConflictError,
    OperationalIntegrityError,
    OperationalStore,
)

NOW = datetime(2026, 1, 2, tzinfo=UTC)
EMPTY = {
    "schema_version": "manual-portfolio-v1",
    "holdings_status": "none",
    "investment_budget_yen": None,
    "maximum_drawdown_percent": None,
    "accounts": [],
    "holdings": [],
}
ACCOUNT = {
    "id": "00000000-0000-4000-8000-000000000001",
    "name": "試験用口座",
    "account_type": "taxable_specified",
    "withholding_mode": "withholding",
    "available_cash_yen": "0",
}
HOLDING = {
    "account_id": ACCOUNT["id"],
    "symbol": "285A0",
    "shares": 1,
    "average_acquisition_price_yen": "1234.5678",
}


def packed(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def envelope(
    *,
    sequence: int = 1,
    owner: str = "test-owner",
    portfolio: dict | None = None,
    parent: str | None = None,
    saved_at: str = "2026-01-01T00:00:00.000Z",
) -> dict:
    raw = packed({"owner": owner, "parent": parent, "portfolio": portfolio or EMPTY})
    exported = packed(
        {
            "schema_version": "manual-portfolio-export-v1",
            "revision_id": digest(raw),
            "revision_sequence": sequence,
            "saved_at": saved_at,
            "revision_json": raw,
        }
    )
    return {"export_sha256": digest(exported), "export_json": exported}


def item(**kwargs) -> ImportedManualPortfolio:
    return ImportedManualPortfolio.from_response(envelope(**kwargs), received_at=NOW)


def test_empty_preserves_unknowns_and_zero() -> None:
    profile = item().portfolio
    assert profile.holding_symbols == ()
    assert profile.investment_budget_yen is None
    assert set(profile.missing_fields) == {
        "accounts",
        "investment_budget_yen",
        "maximum_drawdown_percent",
    }
    assert (
        item(portfolio={**EMPTY, "investment_budget_yen": "0"}).portfolio.investment_budget_yen
        == "0"
    )
    profile = item(
        portfolio={
            **EMPTY,
            "accounts": [
                {
                    **ACCOUNT,
                    "available_cash_yen": None,
                    "account_type": "unknown_manual",
                    "withholding_mode": "unknown",
                }
            ],
            "holdings_status": "unrecorded",
        }
    ).portfolio
    assert {"holdings_status", "available_cash_yen", "account_classification"} <= set(
        profile.missing_fields
    )


def test_decimal_odd_lot_and_all_holdings_across_accounts() -> None:
    second = {
        **ACCOUNT,
        "id": "00000000-0000-4000-8000-000000000002",
        "account_type": "nisa",
        "withholding_mode": "not_applicable",
    }
    profile = item(
        portfolio={
            **EMPTY,
            "accounts": [ACCOUNT, second],
            "holdings_status": "recorded",
            "holdings": [
                HOLDING,
                {**HOLDING, "account_id": second["id"], "average_acquisition_price_yen": None},
            ],
        }
    ).portfolio
    assert profile.holding_symbols == ("285A0",)
    assert profile.holdings[0].shares == 1
    assert profile.holdings[0].average_acquisition_price_yen == "1234.5678"
    assert "average_acquisition_price_yen" in profile.missing_fields


@pytest.mark.parametrize(
    "change",
    [
        {"investment_budget_yen": 0},
        {"investment_budget_yen": "1e8"},
        {"investment_budget_yen": "-1"},
        {"investment_budget_yen": "1.00001"},
        {"investment_budget_yen": "01"},
        {"investment_budget_yen": "1\uff11\uff12\uff13"},
        {"maximum_drawdown_percent": True},
        {"maximum_drawdown_percent": 0},
        {"maximum_drawdown_percent": 101},
        {"maximum_drawdown_percent": "10"},
        {"maximum_drawdown_percent": float("nan")},
        {"password": "forbidden"},
        {"holdings_status": "recorded"},
        {"accounts": [ACCOUNT, ACCOUNT]},
        {"accounts": [{**ACCOUNT, "account_type": "nisa"}]},
        {"accounts": [{**ACCOUNT, "account_type": "taxable_general"}]},
        {"accounts": [{**ACCOUNT, "name": " "}]},
    ],
)
def test_invalid_profile(change: dict) -> None:
    with pytest.raises(ValueError):
        ManualPortfolio.model_validate({**EMPTY, **change})


@pytest.mark.parametrize(
    "holdings,accounts",
    [
        ([HOLDING], []),
        ([HOLDING, HOLDING], [ACCOUNT]),
        ([{**HOLDING, "shares": True}], [ACCOUNT]),
        ([{**HOLDING, "shares": 0}], [ACCOUNT]),
        ([{**HOLDING, "shares": 1.1}], [ACCOUNT]),
    ],
)
def test_invalid_holdings(holdings: list, accounts: list) -> None:
    with pytest.raises(ValueError):
        item(
            portfolio={
                **EMPTY,
                "holdings_status": "recorded",
                "holdings": holdings,
                "accounts": accounts,
            }
        )


def test_exact_bytes_and_tamper_detection() -> None:
    raw = envelope(portfolio={**EMPTY, "maximum_drawdown_percent": 0.0000001})
    # Equivalent number spellings must be hashed as received, not reserialized in Python.
    original = json.loads(raw["export_json"])
    original["revision_json"] = original["revision_json"].replace("1e-07", "1e-7")
    original["revision_id"] = digest(original["revision_json"])
    raw["export_json"] = packed(original)
    raw["export_sha256"] = digest(raw["export_json"])
    assert (
        ImportedManualPortfolio.from_response(
            raw, received_at=NOW
        ).portfolio.maximum_drawdown_percent
        == 1e-7
    )
    with pytest.raises(ValueError, match="export hash"):
        ImportedManualPortfolio.from_response(
            {**raw, "export_json": raw["export_json"] + " "}, received_at=NOW
        )
    original["revision_json"] += " "
    changed = packed(original)
    with pytest.raises(ValueError, match="revision hash"):
        ImportedManualPortfolio.from_response(
            {"export_json": changed, "export_sha256": digest(changed)}, received_at=NOW
        )
    for invalid in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}']:
        with pytest.raises(ValueError):
            strict_json(invalid)
    with pytest.raises(ValueError):
        ImportedManualPortfolio.from_response({**raw, "owner": "override"}, received_at=NOW)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sequence": True},
        {"sequence": 0},
        {"saved_at": "2026-01-01T00:00:00"},
        {"saved_at": "2026-01-03T00:00:00Z"},
    ],
)
def test_time_and_sequence_validation(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        item(**kwargs)


def test_append_pin_replay_rollback_and_backup(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "ledger.sqlite3")
    assert store.latest_manual_portfolio() is None
    first = store.import_manual_portfolio(item())
    later = first.model_copy(update={"received_at": NOW + timedelta(days=1)})
    assert store.import_manual_portfolio(later) == first
    for conflicting in [
        item(owner="another-owner"),
        item(portfolio={**EMPTY, "investment_budget_yen": "1"}),
    ]:
        with pytest.raises(OperationalConflictError):
            store.import_manual_portfolio(conflicting)
    second = item(
        sequence=3,
        parent=first.export.revision_id,
        portfolio={**EMPTY, "investment_budget_yen": "0"},
    )
    store.import_manual_portfolio(second)
    with pytest.raises(OperationalConflictError, match="rollback"):
        store.import_manual_portfolio(first)
    with pytest.raises(OperationalConflictError, match="time rollback"):
        store.import_manual_portfolio(
            item(sequence=4, parent=second.export.revision_id, saved_at="2025-01-01T00:00:00Z")
        )
    with pytest.raises(OperationalConflictError, match="replay conflict"):
        store.import_manual_portfolio(item(sequence=4))
    assert store.latest_manual_portfolio() == second
    counts = store.verify_integrity()
    assert counts["manual_portfolio_imports"] == 2
    assert counts["portfolio_states"] == counts["executions"] == counts["prediction_snapshots"] == 0
    backup = store.backup(tmp_path / "backup.sqlite3")
    restored = tmp_path / "restored.sqlite3"
    OperationalStore.restore_backup(backup, restored, confirm_replace=True)
    assert OperationalStore(restored).latest_manual_portfolio() == second
    with sqlite3.connect(restored) as connection:
        connection.execute(
            "UPDATE manual_portfolio_imports SET revision_sequence=9 WHERE revision_sequence=3"
        )
    with pytest.raises(OperationalIntegrityError, match="catalog identity"):
        OperationalStore(restored).verify_integrity()


def test_prior_schema_backup_and_payload_corruption(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "ledger.sqlite3")
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE manual_portfolio_imports")
        connection.execute("PRAGMA user_version=2")
    assert store.verify_integrity()["manual_portfolio_imports"] == 0
    store = OperationalStore(store.path)
    store.import_manual_portfolio(item())
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE manual_portfolio_imports SET payload='{}'")
    with pytest.raises(OperationalIntegrityError, match="content hash"):
        store.latest_manual_portfolio()


def test_transport_commit_before_ack_and_retry(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "ledger.sqlite3")
    ack_fail = True

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "stock-ai-private-daily.manato0618.chatgpt.site"
        assert request.headers["OAI-Sites-Authorization"] == "Bearer test-secret"
        assert request.headers["X-Stock-AI-Portfolio-Access"] == portfolio_access_token(
            "test-secret"
        )
        if request.method == "GET":
            return httpx.Response(200, json=envelope())
        current = store.latest_manual_portfolio()
        assert current is not None  # Durable before any cloud acknowledgment.
        body = json.loads(request.content)
        assert body["imported_at"] == current.received_at.isoformat()
        return httpx.Response(503 if ack_fail else 200, json={**body, "acknowledged": True})

    transport = httpx.MockTransport(handle)
    with pytest.raises(RuntimeError, match="local records were retained"):
        pull_private_portfolio(store, bearer_token="test-secret", transport=transport)
    original = store.latest_manual_portfolio()
    ack_fail = False
    assert (
        pull_private_portfolio(store, bearer_token="test-secret", transport=transport) == original
    )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://evil.invalid"}),
        httpx.Response(200, content=b"x" * 500_001),
        httpx.Response(200, json={"error": "test-secret"}),
        httpx.Response(200, content=b"\xff"),
        httpx.Response(401),
    ],
)
def test_transport_refuses_redirects_invalid_or_oversize_without_leaking(
    tmp_path: Path, response: httpx.Response
) -> None:
    store = OperationalStore(tmp_path / "ledger.sqlite3")
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response

    with pytest.raises(RuntimeError) as error:
        pull_private_portfolio(
            store, bearer_token="test-secret", transport=httpx.MockTransport(handle)
        )
    assert "test-secret" not in str(error.value)
    assert len(calls) == 1
    assert store.latest_manual_portfolio() is None
    with pytest.raises(ValueError):
        pull_private_portfolio(store, bearer_token="test-secret", origin=PRIVATE_SITE_ORIGIN + "/")


def test_cli_failure_redacts_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from stock_ai import cli

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("test-secret")

    monkeypatch.setenv("STOCK_AI_PRIVATE_SITE_TOKEN", "test-secret")
    monkeypatch.setattr(cli, "pull_private_portfolio", fail)
    result = CliRunner().invoke(
        cli.app, ["ops", "pull-private-portfolio", "--database", str(tmp_path / "ledger.sqlite3")]
    )
    assert result.exit_code == 1
    assert "test-secret" not in result.output
    assert "local records were retained" in result.output
