from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from stock_ai.operations.chatgpt_manual import (
    ExternalAiPermission,
    _target_rows,
    input_package,
    manual_prompt,
    parse_answer,
    review_answer,
)
from stock_ai.operations.personal import compare_personal
from tests.conftest import AS_OF
from tests.test_personal_comparison import scenario


@pytest.fixture
def context():
    request, inputs = scenario()
    comparison = compare_personal(request, **inputs)
    assert comparison.proposal is not None
    permission = ExternalAiPermission(
        service="manual_chatgpt",
        checked_at=AS_OF,
        personal_analysis_only=True,
        training_disabled=True,
        private_input=True,
        private_output=True,
        data_entitlement_confirmed=True,
    )
    now = AS_OF + timedelta(minutes=3)
    package = input_package(
        comparison, inputs["ledger"], inputs["forecast"], now=now, permission=permission
    )
    answer = dict(
        schema_version="chatgpt-target-shares-v1",
        input_snapshot_id=package["input_snapshot_id"],
        evidence_as_of=now.isoformat(),
        targets=[
            dict(
                symbol=x["symbol"],
                account=x["account"],
                target_shares=x["current_shares"],
                reason="未確認事項が残るため保有を維持",
                sources=[],
            )
            for x in package["required_targets"]
        ],
        unknowns=["公開情報による裏付けは未確認"],
    )
    return comparison, inputs, permission, now, package, answer


def review(context, answer=None, **kwargs):
    comparison, inputs, permission, now, package, original = context
    return review_answer(
        json.dumps(original if answer is None else answer),
        package,
        comparison,
        inputs["ledger"],
        inputs["forecast"],
        now=now,
        permission=permission,
        **kwargs,
    )


def test_complete_hold_is_valid_without_mutating_originals(context):
    comparison, inputs, _, _, package, _ = context
    before = {k: v.model_dump_json() for k, v in inputs.items() if k != "executions"}
    result = review(context)
    assert all(x["share_difference"] == 0 for x in result["lines"])
    assert result["estimated_cash_after"] == {"A1": "200000"}
    assert result["estimated_cost_yen"] == "0"
    assert result["applied_to_ledger"] is False and result["order_submitted"] is False
    assert before == {k: v.model_dump_json() for k, v in inputs.items() if k != "executions"}
    assert comparison.proposal is not None
    assert {x["symbol"] for x in package["securities"]} == {"1001", "1002"}
    assert next(x for x in package["securities"] if x["symbol"] == "1001")["holding"]


def test_target_shares_are_converted_by_app_and_exact_cost_is_reused(context):
    answer = context[-1]
    answer["targets"][0]["target_shares"] = 100  # new candidate
    answer["targets"][1]["target_shares"] = 0  # held position
    result = review(context)
    assert {x["symbol"]: x["share_difference"] for x in result["lines"]} == {
        "1001": -100,
        "1002": 100,
    }
    # Two 100,000-yen notionals at the fixture's explicit 100bps cost;
    # 20% withholding on (10,000 minus deductible commission0) = 2,000.
    assert Decimal(result["estimated_cost_yen"]) == 2000
    assert Decimal(result["estimated_cash_after"]["A1"]) == 196000


@pytest.mark.parametrize(
    "field",
    [
        "personal_analysis_only",
        "training_disabled",
        "private_input",
        "private_output",
        "data_entitlement_confirmed",
    ],
)
def test_each_external_permission_condition_is_required(context, field):
    c, inputs, permission, now, _, _ = context
    with pytest.raises(ValueError, match="PERMISSION_UNCONFIRMED"):
        input_package(
            c,
            inputs["ledger"],
            inputs["forecast"],
            now=now,
            permission=permission.model_copy(update={field: False}),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"checked_at": AS_OF + timedelta(days=1)},
        {"checked_at": AS_OF - timedelta(days=2)},
        {"service": "account_codex"},
    ],
)
def test_permission_is_service_bound_and_dated(context, change):
    c, inputs, permission, now, _, _ = context
    with pytest.raises(ValueError, match="PERMISSION_UNCONFIRMED"):
        input_package(
            c,
            inputs["ledger"],
            inputs["forecast"],
            now=now,
            permission=permission.model_copy(update=change),
        )


@pytest.mark.parametrize(
    "text",
    [
        "broken",
        "[]",
        '{"x":1,"x":2}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        "```json\n{}\n```",
        "x" * 262145,
        None,
        123,
        {},
        "\ud800",
    ],
    ids=[
        "syntax",
        "array",
        "duplicate",
        "nan",
        "inf",
        "minus-inf",
        "fenced",
        "oversize",
        "null-input",
        "integer-input",
        "object-input",
        "invalid-unicode",
    ],
)
def test_invalid_json_never_gets_silently_repaired(text):
    with pytest.raises(ValueError):
        parse_answer(text)


@pytest.mark.parametrize("value", [True, 100.5, "100", -100, 100000001])
def test_target_quantity_requires_bounded_integer(context, value):
    context[-1]["targets"][0]["target_shares"] = value
    with pytest.raises(ValueError):
        review(context)


@pytest.mark.parametrize("change", ["duplicate", "missing", "symbol", "account", "snapshot"])
def test_scope_or_snapshot_mismatch_is_rejected(context, change):
    answer = context[-1]
    if change == "duplicate":
        answer["targets"].append(answer["targets"][0])
    elif change == "missing":
        answer["targets"].pop()
    elif change in {"symbol", "account"}:
        answer["targets"][0][change] = "9999" if change == "symbol" else "A2"
    else:
        answer["input_snapshot_id"] = "0" * 64
    with pytest.raises(ValueError, match=r"TARGET_UNIVERSE|SNAPSHOT_MISMATCH"):
        review(context)


@pytest.mark.parametrize("change", ["lot", "budget", "future", "old", "extra"])
def test_constraints_and_evidence_times_are_checked(context, change):
    answer = context[-1]
    if change in {"lot", "budget"}:
        answer["targets"][0]["target_shares"] = 1 if change == "lot" else 1000
    elif change in {"future", "old"}:
        answer["evidence_as_of"] = (
            AS_OF + timedelta(days=1) if change == "future" else AS_OF
        ).isoformat()
    else:
        answer["confidence"] = 0.99
    with pytest.raises(ValueError):
        review(context)


@pytest.mark.parametrize(
    "url", ["http://example.com", "https://user:secret@example.com", "file:///x"]
)
def test_invalid_source_urls_are_rejected(context, url):
    context[-1]["targets"][0]["sources"] = [url]
    with pytest.raises(ValueError, match="INVALID_SOURCE"):
        review(context)


def test_stale_package_and_altered_ledger_are_rejected(context):
    c, inputs, permission, now, package, answer = context
    with pytest.raises(ValueError, match="STALE_CONTEXT"):
        review_answer(
            json.dumps(answer),
            package,
            c,
            inputs["ledger"],
            inputs["forecast"],
            now=now + timedelta(minutes=16),
            permission=permission,
        )
    altered = inputs["ledger"].model_copy(
        update={
            "cash": tuple(
                x.model_copy(update={"available_cash": Decimal(9999999)})
                for x in inputs["ledger"].cash
            )
        }
    )
    with pytest.raises(ValueError, match="SNAPSHOT_MISMATCH"):
        input_package(c, altered, inputs["forecast"], now=now, permission=permission)


@pytest.mark.parametrize("change", ["symbol-space", "account-space", "blank-reason", "deep-json"])
def test_invalid_fields_are_rejected_without_silent_normalization(context, change):
    if change == "deep-json":
        with pytest.raises(ValueError, match="INVALID_JSON"):
            parse_answer("[" * 1100 + "0" + "]" * 1100)
        return
    target = context[-1]["targets"][0]
    if change == "symbol-space":
        target["symbol"] += " "
    elif change == "account-space":
        target["account"] += " "
    else:
        target["reason"] = "   "
    with pytest.raises(ValueError):
        review(context)


@pytest.mark.parametrize(
    "shares,reason",
    [
        (100, "INVESTMENT_BUDGET"),
        (1000, "INSUFFICIENT_CASH_AFTER_COST_TAX"),
    ],
)
def test_funds_and_budget_rejections_identify_the_actual_constraint(context, shares, reason):
    context[-1]["targets"][0]["target_shares"] = shares
    with pytest.raises(ValueError, match=reason):
        review(context)


def test_maximum_owner_holdings_and_accounts_keep_all_positions_without_empty_cross_product():
    from stock_ai.domain import Position

    candidates = tuple(f"N{i:03}" for i in range(20))
    holdings = tuple(f"H{i:03}" for i in range(200))
    aliases = {f"bucket{i}": f"A{i + 1}" for i in range(30)}
    positions = {
        (s, f"bucket{i % 30}"): Position(
            symbol=s,
            account_bucket_id=f"bucket{i % 30}",
            shares=100,
            average_acquisition_price=100,
            market_price=100,
        )
        for i, s in enumerate(holdings)
    }
    rows = _target_rows((*candidates, *holdings), candidates, positions, aliases)
    assert len(rows) == 800  # 20 new x 30 accounts + all 200 held positions
    assert sum(x["current_shares"] for x in rows) == 20000
    assert len({(x["symbol"], x["account"]) for x in rows}) == 800
    for (symbol, bucket), position in positions.items():
        assert {
            "symbol": symbol,
            "account": aliases[bucket],
            "current_shares": position.shares,
        } in rows


def test_export_projection_omits_raw_account_identifiers_and_secrets(context):
    package = context[-2]
    text = manual_prompt(package)
    for forbidden in [
        "account_bucket_id",
        '"broker"',
        '"account_id"',
        '"bucket"',
        "api_key",
        "access_token",
        "refresh_token",
        "average_acquisition_price",
    ]:
        assert forbidden not in text
    assert "input_snapshot_id" in text and "fractional_return" in text
    assert "反対材料" in text and "足し合わせない" in text
    package["accounts"][0]["available_cash_yen"] = "9999999"
    with pytest.raises(ValueError, match="SNAPSHOT_MISMATCH"):
        manual_prompt(package)
