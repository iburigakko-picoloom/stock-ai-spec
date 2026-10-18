"""Snapshot-bound manual ChatGPT packages and read-only share proposal review.

No network, order, optimization or ledger mutation is performed here. Callers
must obtain the frozen comparison from their authenticated local receipt.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from stock_ai.decision.costs import TransactionCostEngine
from stock_ai.decision.engine import DailyPortfolioDecisionEngine, DecisionCandidate
from stock_ai.decision.tax import SimpleJapanTaxEngine
from stock_ai.domain import PortfolioState, Position
from stock_ai.operations.daily import PredictionSnapshot, canonical_json, content_id
from stock_ai.operations.personal import PersonalComparison, implementation_hashes

JST = ZoneInfo("Asia/Tokyo")
TERMS_URL = "https://jpx-jquants.com/ja/help/usage"
TERMS_REVIEW: Literal["jquants-generative-ai-four-conditions-20261018-v1"] = (
    "jquants-generative-ai-four-conditions-20261018-v1"
)
MAX_JSON_BYTES = 262144


class ManualModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ExternalAiPermission(ManualModel):
    service: Literal["manual_chatgpt", "account_codex"]
    terms_review: Literal["jquants-generative-ai-four-conditions-20261018-v1"] = TERMS_REVIEW
    checked_at: AwareDatetime
    personal_analysis_only: bool
    training_disabled: bool
    private_input: bool
    private_output: bool
    data_entitlement_confirmed: bool = False

    def require(self, now: datetime, service: str) -> None:
        if (
            now.utcoffset() is None
            or self.service != service
            or not self.checked_at <= now <= self.checked_at + timedelta(hours=24)
            or not all(
                (
                    self.personal_analysis_only,
                    self.training_disabled,
                    self.private_input,
                    self.private_output,
                    self.data_entitlement_confirmed,
                )
            )
        ):
            raise ValueError(
                "EXTERNAL_AI_PERMISSION_UNCONFIRMED: 利用条件と非学習・非公開設定を確認してください"
            )


class TargetSuggestion(ManualModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{1,10}$")
    account: str = Field(pattern=r"^A[1-9][0-9]*$")
    target_shares: Annotated[int, Field(strict=True, ge=0, le=100000000)]
    reason: str = Field(min_length=1, max_length=4000)
    sources: tuple[str, ...] = Field(max_length=20)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class ManualAnswer(ManualModel):
    schema_version: Literal["chatgpt-target-shares-v1"]
    input_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_as_of: AwareDatetime
    targets: tuple[TargetSuggestion, ...] = Field(min_length=1, max_length=1000)
    unknowns: tuple[str, ...] = Field(max_length=100)


def parse_answer(text: str) -> ManualAnswer:
    if not isinstance(text, str):
        raise ValueError("INVALID_JSON: 回答JSONは文字列で指定してください")
    try:
        byte_count = len(text.encode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("INVALID_JSON: 回答JSONの文字コードを確認してください") from exc
    if byte_count > MAX_JSON_BYTES:
        raise ValueError("INVALID_JSON: 回答が大きすぎます")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("INVALID_JSON: JSONのキーが重複しています")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("INVALID_JSON: 非有限の数値は使えません")

    try:
        return ManualAnswer.model_validate(
            json.loads(
                text,
                object_pairs_hook=pairs,
                parse_constant=invalid_constant,
            )
        )
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        if type(exc) is ValueError and str(exc).startswith("INVALID_JSON:"):
            raise
        raise ValueError("INVALID_JSON: 回答JSONの形式を確認してください") from exc


def _context(
    comparison: PersonalComparison,
    portfolio: PortfolioState,
    forecast: PredictionSnapshot,
    now: datetime,
) -> tuple[PersonalComparison, PortfolioState, PredictionSnapshot]:
    comparison = PersonalComparison.model_validate_json(comparison.model_dump_json())
    portfolio = PortfolioState.model_validate_json(portfolio.model_dump_json())
    forecast = PredictionSnapshot.model_validate_json(forecast.model_dump_json())
    if (
        now.utcoffset() is None
        or comparison.proposal is None
        or comparison.request.settings is None
        or comparison.request.market is None
        or comparison.ledger_portfolio_id != portfolio.portfolio_id
        or comparison.forecast_snapshot_id != forecast.snapshot_id
        or set(forecast.holding_symbols) != {p.symbol for p in portfolio.positions if p.shares}
        or not forecast.generated_at <= comparison.checked_at <= now
        or forecast.as_of.astimezone(JST).date() != now.astimezone(JST).date()
        or now > comparison.checked_at + timedelta(minutes=15)
        or comparison.implementation_sha256 != implementation_hashes(comparison.request.settings)
    ):
        raise ValueError("STALE_CONTEXT: 最新の原予測・口座・設定を照合し直してください")
    audit = comparison.proposal.daily_audit
    market = comparison.request.market
    assert market is not None
    marked = PortfolioState.model_validate(
        {
            **portfolio.model_dump(),
            "as_of": forecast.as_of,
            "positions": tuple(
                p.model_copy(update={"market_price": market.market.prices[p.symbol]})
                for p in portfolio.positions
                if p.shares
                if p.shares
            ),
        }
    )
    if (
        audit is None
        or audit.forecast_content_sha256 != content_id(forecast.model_dump(mode="json"))
        or audit.portfolio_content_sha256 != content_id(marked.model_dump(mode="json"))
        or audit.market_content_sha256 != content_id(market.model_dump(mode="json"))
    ):
        raise ValueError("SNAPSHOT_MISMATCH: 原予測の内容が一致しません")
    return comparison, portfolio, forecast


def _target_rows(
    symbols: tuple[str, ...],
    candidates: tuple[str, ...],
    positions: Mapping[tuple[str, str], Position],
    aliases: Mapping[str, str],
) -> list[dict[str, Any]]:
    # research_symbols() already puts the top20 candidates before extra holdings.
    top = set([s for s in symbols if s in candidates][:20])
    return [
        {
            "symbol": s,
            "account": alias,
            "current_shares": positions[(s, bucket)].shares if (s, bucket) in positions else 0,
        }
        for s in symbols
        for bucket, alias in aliases.items()
        if s in top or ((s, bucket) in positions and positions[(s, bucket)].shares > 0)
    ]


def input_package(
    comparison: PersonalComparison,
    portfolio: PortfolioState,
    forecast: PredictionSnapshot,
    *,
    now: datetime,
    permission: ExternalAiPermission,
) -> dict[str, Any]:
    """Project only required fields; never dump credentials/account identifiers."""
    permission.require(now, "manual_chatgpt")
    comparison, portfolio, forecast = _context(comparison, portfolio, forecast, now)
    settings, market = comparison.request.settings, comparison.request.market
    assert settings is not None and market is not None
    aliases = {
        b.bucket_id: f"A{i}"
        for i, b in enumerate(
            sorted(portfolio.account_buckets, key=lambda x: x.bucket_id),
            1,
        )
    }
    prices = market.market.prices
    securities = {s.symbol: s for s in market.securities}
    symbols = forecast.research_symbols()
    if set(symbols) - set(securities) or set(symbols) - set(prices):
        raise ValueError("MARKET_INCOMPLETE: 全候補と全保有の価格・単元が必要です")
    accounts = [
        {
            "account": aliases[b.bucket_id],
            "account_type": b.account_type.value,
            "available_cash_yen": str(portfolio.cash_map()[b.bucket_id].deployable_cash),
            "nisa_annual_remaining_yen": portfolio.tax_state_map()[
                b.bucket_id
            ].nisa_annual_capacity_user_input,
            "nisa_lifetime_remaining_yen": portfolio.tax_state_map()[
                b.bucket_id
            ].nisa_lifetime_capacity_user_input,
        }
        for b in sorted(portfolio.account_buckets, key=lambda x: x.bucket_id)
    ]
    forecasts = {p.symbol: p for p in forecast.predictions}
    rows = [
        {
            "symbol": s,
            "candidate": s in forecast.candidate_symbols,
            "holding": s in forecast.holding_symbols,
            "lot_size": securities[s].lot_size,
            "reference_price_yen": str(prices[s]),
            "forecast_5d": {"value": forecasts[s].expected_return_5d, "unit": "fractional_return"},
            "forecast_20d": {
                "value": forecasts[s].expected_return_20d,
                "unit": "fractional_return",
            },
            "risk_horizon": 20,
            "downside_quantile": forecasts[s].downside_quantile,
            "large_loss_probability": forecasts[s].large_loss_probability,
            "uncertainty": forecasts[s].uncertainty.model_dump(mode="json"),
        }
        for s in symbols
    ]
    positions = portfolio.position_map()
    required_targets = _target_rows(symbols, forecast.candidate_symbols, positions, aliases)
    body = {
        "schema_version": "chatgpt-manual-input-v1",
        "validation_version": "manual-target-review-v1",
        "validation_sha256": content_id(
            {
                "manual": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "comparison": dict(comparison.implementation_sha256),
            }
        ),
        "prediction_snapshot_id": forecast.snapshot_id,
        "account_snapshot_id": content_id(portfolio.model_dump(mode="json")),
        "settings_snapshot_id": content_id(settings.model_dump(mode="json")),
        "manual_revision_id": comparison.manual_revision_id,
        "comparison_id": comparison.comparison_id,
        "created_at": comparison.checked_at.isoformat(),
        "expires_at": (comparison.checked_at + timedelta(minutes=15)).isoformat(),
        "prediction_as_of": forecast.as_of.isoformat(),
        "data_as_of": forecast.data_as_of.isoformat(),
        "model_version": forecast.model_version,
        "data_snapshot_id": forecast.data_snapshot_id,
        "label_definition": forecast.label_definition,
        "price_semantics": forecast.price_semantics,
        "large_loss_threshold": forecast.large_loss_threshold,
        "downside_quantile_alpha": forecast.downside_quantile_alpha,
        "research_only": True,
        "adoption_eligible": False,
        "blocking_reasons": forecast.blocking_reasons,
        "accounts": accounts,
        "securities": rows,
        "required_targets": required_targets,
        "investment_budget_yen": str(comparison.investment_budget_yen),
        "constraints": settings.decision_policy.model_dump(mode="json"),
        "cost_policy": settings.cost_policy.model_dump(mode="json"),
        "drawdown_preference_percent": settings.reviewed_drawdown_preference_percent,
        "drawdown_preference_is_guarantee": False,
        "external_permission": {
            "terms_review": permission.terms_review,
            "source": TERMS_URL,
            "checked_at": permission.checked_at.isoformat(),
        },
    }
    # Normalize Decimal values without exposing source models or their account IDs.
    body = json.loads(canonical_json(json.loads(json.dumps(body, default=str))))
    return {**body, "input_snapshot_id": content_id(body)}


def manual_prompt(package: dict[str, Any]) -> str:
    if package.get("input_snapshot_id") != content_id(
        {k: v for k, v in package.items() if k != "input_snapshot_id"}
    ):
        raise ValueError("SNAPSHOT_MISMATCH")
    return (
        "本人用の日本株判断支援です。外部公開せず、学習利用をoffにした会話で扱ってください。\n"
        "企業IR等を独立に調べ、数値モデルに同調せず、反対材料・不明点も示してください。"
        "入力外の重要論点も自由に検討できます。確率や未確認事実を作らず、事実と推論を分けてください。\n"
        "5日/20日はそれぞれの期間の予測です。足し合わせないでください。順位scoreは期待returnではありません。"
        "研究用・未採用の制約と各根拠の時点を尊重してください。\n"
        "required_targetsの全銘柄/口座を一度ずつ、目標保有株数(target_shares)で回答してください。"
        "売買差分・費用・税・実台帳の確定はアプリが行います。原予測を変更しないでください。\n"
        "回答は次のschemaのJSONだけ。reasonは根拠/反対材料を含め、sourcesは確認したHTTPS URL、"
        "未確認はunknownsへ。evidence_as_ofは調べた情報の締切日時です。\n"
        + canonical_json(ManualAnswer.model_json_schema())
        + "\n入力:\n"
        + canonical_json(package)
    )


def review_answer(
    text: str,
    package: dict[str, Any],
    comparison: PersonalComparison,
    portfolio: PortfolioState,
    forecast: PredictionSnapshot,
    *,
    now: datetime,
    permission: ExternalAiPermission,
) -> dict[str, Any]:
    expected = input_package(comparison, portfolio, forecast, now=now, permission=permission)
    if package != expected:
        raise ValueError("SNAPSHOT_MISMATCH: 入力snapshotが変化しています")
    answer = parse_answer(text)
    if answer.input_snapshot_id != package["input_snapshot_id"]:
        raise ValueError("SNAPSHOT_MISMATCH: 別の入力への回答です")
    if not comparison.checked_at <= answer.evidence_as_of <= now:
        raise ValueError("STALE_EVIDENCE: 根拠の時点が入力前または未来です")
    keys = [(t.symbol, t.account) for t in answer.targets]
    required = {(x["symbol"], x["account"]) for x in package["required_targets"]}
    if len(keys) != len(set(keys)) or set(keys) != required:
        raise ValueError("TARGET_UNIVERSE: 全対象/全口座を重複なく指定してください")
    from urllib.parse import urlsplit

    for suggestion in answer.targets:
        for url in suggestion.sources:
            p = urlsplit(url)
            if len(url) > 2000 or p.scheme != "https" or not p.hostname or p.username or p.password:
                raise ValueError("INVALID_SOURCE: 根拠URLは認証情報のないHTTPSにしてください")
    settings, market = comparison.request.settings, comparison.request.market
    assert settings is not None and market is not None
    aliases = {
        f"A{i}": b.bucket_id
        for i, b in enumerate(
            sorted(portfolio.account_buckets, key=lambda x: x.bucket_id),
            1,
        )
    }
    current = portfolio.position_map()
    prices = market.market.prices
    securities = {s.symbol: s for s in market.securities}
    predictions = {p.symbol: p for p in forecast.predictions}
    adv = dict(market.average_daily_trading_values)
    targets = {(t.symbol, aliases[t.account]): t.target_shares for t in answer.targets}
    candidates = {}
    lines = []
    for (symbol, bucket), target in targets.items():
        held = current[(symbol, bucket)].shares if (symbol, bucket) in current else 0
        delta = target - held
        if delta % securities[symbol].lot_size:
            raise ValueError("LOT_SIZE: 売買差分が単元に一致しません")
        if delta and bucket not in portfolio.tax_state_map():
            raise ValueError("ACCOUNT_CONSTRAINT: 税・口座情報が不足しています")
        if (
            delta > 0
            and next(
                b for b in portfolio.account_buckets if b.bucket_id == bucket
            ).account_type.value
            == "unknown_manual"
        ):
            raise ValueError("ACCOUNT_CONSTRAINT: 未確認口座で買付できません")
        candidates[(symbol, bucket)] = DecisionCandidate(
            security=securities[symbol],
            account_bucket_id=bucket,
            price=prices[symbol],
            prediction=predictions[symbol],
            average_daily_trading_value=adv.get(symbol),
        )
        lines.append(
            {
                "symbol": symbol,
                "account": next(a for a, b in aliases.items() if b == bucket),
                "current_shares": held,
                "target_shares": target,
                "share_difference": delta,
            }
        )
    marked = portfolio.model_copy(
        update={
            "as_of": forecast.as_of,
            "positions": tuple(
                p.model_copy(update={"market_price": prices[p.symbol]}) for p in portfolio.positions
            ),
        }
    )
    wealth = sum((p.market_value for p in marked.positions), Decimal(0)) + sum(
        (c.deployable_cash for c in marked.cash),
        Decimal(0),
    )
    limits = {
        b.bucket_id: min(
            portfolio.tax_state_map()[b.bucket_id].nisa_annual_capacity_user_input or Decimal(0),
            portfolio.tax_state_map()[b.bucket_id].nisa_lifetime_capacity_user_input or Decimal(0),
        )
        for b in portfolio.account_buckets
        if b.account_type.value == "nisa"
    }
    engine = DailyPortfolioDecisionEngine(
        config=settings.decision_policy,
        cost_engine=TransactionCostEngine(settings.cost_policy),
        tax_engine=SimpleJapanTaxEngine(settings.tax_policy),
    )
    violations: list[str] = []
    result = engine._evaluate(
        targets=targets,
        portfolio=marked,
        candidates=candidates,
        buckets={b.bucket_id: b for b in portfolio.account_buckets},
        total_wealth=wealth,
        enforce_trade_constraints=any(x["share_difference"] for x in lines),
        maximum_invested_value=comparison.investment_budget_yen,
        purchase_limits=limits,
        constraint_violations=violations,
    )
    if result is None:
        explanations = {
            "LIQUIDITY_UNKNOWN": "流動性の根拠が不足しています",
            "ADV_LIMIT": "売買代金が設定した出来高上限を超えています",
            "INSUFFICIENT_CASH_AFTER_COST_TAX": "費用・税の見込みを含めると口座の現金が不足します",
            "ACCOUNT_PURCHASE_LIMIT": "口座の購入残枠を超えています",
            "INVESTMENT_BUDGET": "設定した投資予算を超えています",
            "POSITION_LIMIT": "設定した保有銘柄数を超えています",
            "SYMBOL_WEIGHT_LIMIT": "設定した銘柄の集中上限を超えています",
            "SECTOR_WEIGHT_LIMIT": "設定した業種の集中上限を超えています",
            "CASH_RESERVE_LIMIT": "設定した最低現金を確保できません",
            "TURNOVER_LIMIT": "設定した回転率の上限を超えています",
        }
        code = next(iter(violations), "CONSTRAINT_VIOLATION")
        raise ValueError(f"{code}: {explanations.get(code, '保有数量の制約を満たしません')}")
    # An unfilled sale does not prove immediately reusable buying power. Until a
    # dated broker release policy is supplied, fund buys from existing cash only.
    for bucket in aliases.values():
        required_cash = sum(
            (
                candidates[key].price * (value - (current[key].shares if key in current else 0))
                + result.costs[key].total
                for key, value in targets.items()
                if key[1] == bucket and value > (current[key].shares if key in current else 0)
            ),
            Decimal(0),
        )
        if required_cash > portfolio.cash_map()[bucket].deployable_cash:
            raise ValueError("BUYING_POWER: 未約定売却代金を買付資金に使うことはできません")
    return {
        "schema_version": "chatgpt-manual-review-v1",
        "answer": answer.model_dump(mode="json"),
        "answer_id": content_id(answer.model_dump(mode="json")),
        "validation_sha256": package["validation_sha256"],
        "lines": lines,
        "estimated_cash_after": {a: str(result.cash_after[b]) for a, b in aliases.items()},
        "estimated_cost_yen": str(sum((x.total for x in result.costs.values()), Decimal(0))),
        "research_only": True,
        "applied_to_ledger": False,
        "order_submitted": False,
    }


def save_record(connection: sqlite3.Connection, kind: str, payload: dict[str, Any]) -> str:
    """Append an immutable exchange to existing backup-covered local metadata."""
    if kind not in {"input", "answer"}:
        raise ValueError("unknown manual exchange record")
    identity = _record_identity(kind, payload)
    key = f"chatgpt-manual:{kind}:{identity}"
    encoded = canonical_json({"payload": payload, "sha256": content_id(payload)})
    row = connection.execute(
        "SELECT value FROM operational_metadata WHERE key=?", (key,)
    ).fetchone()
    if row is not None and row[0] != encoded:
        if kind != "answer" or _record_identity(kind, read_record(row[0])) != identity:
            raise ValueError("Manual exchange identity conflict")
        # Preserve the first acceptance time on an exact answer replay.
        return identity
    connection.execute(
        "INSERT OR IGNORE INTO operational_metadata(key,value) VALUES(?,?)", (key, encoded)
    )
    if kind == "input":
        connection.execute(
            "INSERT OR REPLACE INTO operational_metadata(key,value) VALUES(?,?)",
            ("chatgpt-manual:selected", identity),
        )
    return identity


def verify_exchange_records(connection: sqlite3.Connection) -> None:
    for key, encoded in connection.execute(
        "SELECT key,value FROM operational_metadata WHERE key LIKE 'external-ai-permission:%'"
    ):
        permission = read_permission_record(encoded)
        if key != "external-ai-permission:" + permission.service:
            raise ValueError("External permission service changed")
    records = {}
    for key, value in connection.execute(
        "SELECT key,value FROM operational_metadata WHERE key LIKE 'chatgpt-manual:%'"
    ):
        if key == "chatgpt-manual:selected":
            continue
        kind, identity = key.removeprefix("chatgpt-manual:").split(":", 1)
        payload = read_record(value)
        if kind not in {"input", "answer"} or identity != _record_identity(kind, payload):
            raise ValueError("Manual exchange content changed")
        if kind == "input":
            manual_prompt(payload["package"])
            ExternalAiPermission.model_validate(payload["permission"])
        else:
            answer = parse_answer(payload["original_json"])
            if answer.model_dump(mode="json") != payload["review"]["answer"]:
                raise ValueError("Manual answer differs from its saved review")
            if payload["review"]["applied_to_ledger"] is not False:
                raise ValueError("Manual proposal cannot update the ledger")
        records[(kind, identity)] = payload
    selected = connection.execute(
        "SELECT value FROM operational_metadata WHERE key=?", ("chatgpt-manual:selected",)
    ).fetchone()
    if selected is not None and ("input", selected[0]) not in records:
        raise ValueError("Manual input selection is missing")
    for (kind, _), payload in records.items():
        if kind == "answer":
            source = records.get(("input", payload["input_record_id"]))
            if (
                source is None
                or payload["review"]["answer"]["input_snapshot_id"]
                != source["package"]["input_snapshot_id"]
            ):
                raise ValueError("Manual answer input reference changed")


def _record_identity(kind: str, payload: dict[str, Any]) -> str:
    # Timing remains in the stored envelope; it does not create a second copy
    # when an unchanged response is submitted after a lost acknowledgment.
    return content_id({k: v for k, v in payload.items() if kind != "answer" or k != "checked_at"})


def read_record(encoded: str) -> dict[str, Any]:
    envelope = json.loads(encoded)
    payload = envelope["payload"]
    if set(envelope) != {"payload", "sha256"} or envelope["sha256"] != content_id(payload):
        raise ValueError("Manual exchange envelope changed")
    if not isinstance(payload, dict):
        raise ValueError("Manual exchange payload must be an object")
    return payload


def permission_record(permission: ExternalAiPermission) -> str:
    payload = permission.model_dump(mode="json")
    return canonical_json({"permission": payload, "sha256": content_id(payload)})


def read_permission_record(encoded: str) -> ExternalAiPermission:
    envelope = json.loads(encoded)
    payload = envelope["permission"]
    if set(envelope) != {"permission", "sha256"} or envelope["sha256"] != content_id(payload):
        raise ValueError("External permission content changed")
    return ExternalAiPermission.model_validate(payload)
