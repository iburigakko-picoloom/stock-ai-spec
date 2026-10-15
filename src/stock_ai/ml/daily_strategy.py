"""Causal, pre-tax research decisions replayed through the daily accounting ledger."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Context, Decimal, localcontext
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from stock_ai.decision import DailyPortfolioDecisionEngine
from stock_ai.decision.costs import TransactionCostEngine
from stock_ai.decision.engine import DecisionEngineConfig, SearchSpaceTooLarge
from stock_ai.decision.tax import SimpleJapanTaxEngine, TaxPolicy
from stock_ai.domain import (
    Account,
    AccountBucket,
    AccountType,
    CashState,
    MarketSnapshot,
    PortfolioProposal,
    PortfolioState,
    Position,
    Security,
    TaxState,
    TradeSide,
    WithholdingMode,
)
from stock_ai.ml.daily_oof import DailyOofDay, propose_daily_oof
from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.nav import (
    JST,
    NavDecisionState,
    NavInput,
    NavModel,
    NavOrder,
    NavResult,
    evaluate_daily_nav,
    evaluate_stateful_nav,
)
from stock_ai.operations.daily import content_id

ZERO = Decimal(0)


class DailySecurityEvidence(NavModel):
    security: Security
    average_daily_trading_value: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)] | None


class DailyDecisionObservation(NavModel):
    forecasts: DailyOofDay
    market: MarketSnapshot
    reference_price_at: datetime
    security_evidence_available_at: datetime
    securities: tuple[DailySecurityEvidence, ...]
    candidate_symbols: tuple[str, ...]
    price_basis: Literal["unadjusted"]

    @model_validator(mode="after")
    def coherent_observation(self) -> Self:
        at = self.forecasts.as_of
        if self.market.as_of != at:
            raise ValueError("decision observation timestamps must agree")
        local = at.astimezone(JST)
        if (local.hour, local.minute, local.second, local.microsecond) != (11, 30, 0, 0):
            raise ValueError("daily strategy requires the exact 11:30 JST freeze")
        if self.reference_price_at > self.market.available_at:
            raise ValueError("reference price observation follows its availability")
        if self.security_evidence_available_at > at:
            raise ValueError("security/liquidity evidence is newer than the decision")
        symbols = [item.security.symbol for item in self.securities]
        if len(symbols) != len(set(symbols)):
            raise ValueError("security evidence must be unique")
        if len(self.candidate_symbols) != len(set(self.candidate_symbols)) or any(
            not symbol for symbol in self.candidate_symbols
        ):
            raise ValueError("candidate symbols must be unique and nonempty")
        return self


class DailyStrategyInput(NavModel):
    schema_version: Literal["daily-strategy-input-v1"] = "daily-strategy-input-v1"
    strategy_id: str = Field(min_length=1)
    accounting: NavInput
    observations: tuple[DailyDecisionObservation, ...]
    decision_policy: DecisionEngineConfig
    tax_mode: Literal["pre_tax"] = "pre_tax"

    @model_validator(mode="after")
    def coherent_strategy(self) -> Self:
        if self.accounting.orders:
            raise ValueError("strategy input must not contain fixed orders")
        if self.decision_policy.horizon_weights != (ZERO, ZERO, Decimal(1)):
            raise ValueError("daily strategy requires the 20d decision policy")
        if self.decision_policy.lot_size != self.accounting.lot_size:
            raise ValueError("strategy and execution lot sizes must agree")
        if (
            tuple(o.forecasts.as_of.astimezone(JST).date() for o in self.observations)
            != self.accounting.calendar_dates
        ):
            raise ValueError("observations must cover the entire ordered accounting calendar")
        identities = {
            (
                o.forecasts.model_version,
                o.forecasts.feature_version,
                o.forecasts.data_snapshot_id,
                o.forecasts.source_report_ids,
            )
            for o in self.observations
        }
        if len(identities) != 1:
            raise ValueError("daily strategy must use one frozen forecast pair")
        return self


class DailyStrategyDecision(NavModel):
    state: NavDecisionState
    evaluated_symbols: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    proposal: PortfolioProposal | None
    orders: tuple[NavOrder, ...]


class DailyStrategyResult(NavModel):
    schema_version: Literal["daily-strategy-result-v1"] = "daily-strategy-result-v1"
    input_sha256: str
    research_only: Literal[True] = True
    adoption_eligible: Literal[False] = False
    decisions_complete: bool
    decisions: tuple[DailyStrategyDecision, ...]
    execution_input: NavInput
    strategy: NavResult
    hold: NavResult
    daily_nav_difference: tuple[Decimal | None, ...]


def evaluate_daily_strategy(request: DailyStrategyInput) -> DailyStrategyResult:
    """Use current simulated holdings, never requested target shares, on the next day.

    Receivables stay in NAV and outside deployable decision wealth until paid.
    Synthetic pre-tax account metadata is explicit research plumbing, not the
    owner's account classification, tax estimate, or NISA capacity model.
    """
    request = DailyStrategyInput.model_validate(request.model_dump())
    tax = TaxPolicy(
        policy_id="research-pre-tax",
        version="research-pre-tax-v1",
        effective_from=request.accounting.initial_as_of.date(),
        taxable_rate=ZERO,
        nisa_opportunity_cost_rate=ZERO,
    )
    engine = DailyPortfolioDecisionEngine(
        config=request.decision_policy,
        cost_engine=TransactionCostEngine(request.accounting.cost_policy),
        tax_engine=SimpleJapanTaxEngine(tax),
    )
    observations = {o.forecasts.as_of: o for o in request.observations}
    previous_closes = dict(
        zip(
            observations,
            (
                request.accounting.initial_as_of,
                *(s.close_at for s in request.accounting.sessions[:-1]),
            ),
            strict=True,
        )
    )
    actions = {event.event_id: event for event in request.accounting.actions}
    decisions: list[DailyStrategyDecision] = []

    def decide(state: NavDecisionState) -> tuple[NavOrder, ...]:
        observation = observations[state.as_of]
        required = tuple(
            sorted({p.symbol for p in state.positions} | set(observation.candidate_symbols))
        )
        predictions = {p.symbol for p in observation.forecasts.predictions}
        securities = {item.security.symbol: item for item in observation.securities}
        blocks: list[str] = []
        for symbol in required:
            if symbol not in predictions:
                reason = next(
                    (b.reason for b in observation.forecasts.blocked if b.symbol == symbol),
                    "MISSING_DAILY_FORECAST",
                )
                blocks.append(f"{symbol}: {reason}")
            if symbol not in securities or symbol not in observation.market.prices:
                blocks.append(f"{symbol}: MISSING_DECISION_MARKET_EVIDENCE")
            elif observation.market.prices[symbol] <= 0:
                blocks.append(f"{symbol}: INVALID_REFERENCE_PRICE")
            elif securities[symbol].average_daily_trading_value is None:
                blocks.append(f"{symbol}: MISSING_LIQUIDITY_EVIDENCE")
        if required and observation.reference_price_at < previous_closes[state.as_of]:
            blocks.append("STALE_REFERENCE_PRICE")
        for event_id in state.applied_event_ids:
            event = actions[event_id]
            if (
                event.symbol in required
                and event.kind in ("split", "cash_conversion")
                and observation.reference_price_at < event.effective_at
            ):
                blocks.append(f"{event.symbol}: REFERENCE_PRECEDES_CORPORATE_ACTION")
        proposal = None
        orders: tuple[NavOrder, ...] = ()
        if not blocks:
            portfolio = PortfolioState(
                portfolio_id="research-state:" + content_id(state.model_dump(mode="json")),
                as_of=state.as_of,
                accounts=(
                    Account(
                        account_id="research",
                        broker="RESEARCH_PRE_TAX",
                        display_name="Research accounting",
                    ),
                ),
                account_buckets=tuple(
                    AccountBucket(
                        bucket_id=c.bucket,
                        account_id="research",
                        account_type=AccountType.TAXABLE_GENERAL,
                        withholding_mode=WithholdingMode.NO_WITHHOLDING,
                        fee_policy_id=request.accounting.cost_policy.policy_id,
                        tax_policy_id=tax.policy_id,
                    )
                    for c in state.cash
                ),
                cash=tuple(
                    CashState(
                        account_bucket_id=c.bucket,
                        available_cash=c.amount,
                        reserved_cash=c.reserved,
                    )
                    for c in state.cash
                ),
                positions=tuple(
                    Position(
                        symbol=p.symbol,
                        account_bucket_id=p.bucket,
                        shares=p.shares,
                        average_acquisition_price=p.unit_cost,
                        market_price=observation.market.prices[p.symbol],
                    )
                    for p in state.positions
                ),
                tax_states=tuple(
                    TaxState(account_bucket_id=c.bucket, tax_year=state.as_of.year)
                    for c in state.cash
                ),
            )
            try:
                proposal = propose_daily_oof(
                    observation.forecasts,
                    portfolio=portfolio,
                    candidate_symbols=observation.candidate_symbols,
                    securities={symbol: item.security for symbol, item in securities.items()},
                    market=observation.market,
                    average_daily_trading_values={
                        symbol: item.average_daily_trading_value
                        for symbol, item in securities.items()
                        if item.average_daily_trading_value is not None
                    },
                    engine=engine,
                    generated_at=state.as_of,
                )
            except SearchSpaceTooLarge as exc:
                blocks.append(f"SEARCH_SPACE_TOO_LARGE: {exc}")
            if proposal is not None:
                orders = tuple(
                    NavOrder(
                        order_id=f"{state.as_of.isoformat()}:{line.account_bucket_id}:{line.symbol}",
                        trading_date=state.as_of.astimezone(JST).date(),
                        decided_at=state.as_of,
                        symbol=line.symbol,
                        bucket=line.account_bucket_id,
                        side=TradeSide.BUY if line.share_difference > 0 else TradeSide.SELL,
                        shares=abs(line.share_difference),
                    )
                    for line in proposal.lines
                    if line.share_difference
                )
        decisions.append(
            DailyStrategyDecision(
                state=state,
                evaluated_symbols=required,
                blocked_reasons=tuple(blocks),
                proposal=proposal,
                orders=orders,
            )
        )
        return orders

    with localcontext(Context(prec=28)):
        execution_input, strategy = evaluate_stateful_nav(
            request.accounting,
            decision_times=tuple(observations),
            decide=decide,
        )
        hold = evaluate_daily_nav(request.accounting)
        differences = tuple(
            a.nav - b.nav if a.nav is not None and b.nav is not None else None
            for a, b in zip(strategy.days, hold.days, strict=True)
        )
    return DailyStrategyResult(
        input_sha256=content_id(request.model_dump(mode="json")),
        decisions_complete=not any(day.blocked_reasons for day in decisions),
        decisions=tuple(decisions),
        execution_input=execution_input,
        strategy=strategy,
        hold=hold,
        daily_nav_difference=differences,
    )


def write_daily_strategy(request: DailyStrategyInput, root: Path) -> Path:
    result = evaluate_daily_strategy(request)
    package = Path(__file__).parents[1]
    files = (
        "ml/daily_strategy.py",
        "ml/daily_oof.py",
        "ml/nav.py",
        "decision/engine.py",
        "decision/costs.py",
        "decision/tax.py",
        "domain/models.py",
    )
    return write_audit_receipt(
        {
            "input": request.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "source_sha256": {
                name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in files
            },
            "pydantic_version": version("pydantic"),
            "decimal_precision": 28,
            "limitations": [
                "pre-tax research only; not personal account settings",
                "market/security/candidate evidence requires independent source authentication",
                "receivables are in NAV, excluded from deployable decision wealth until payment",
                "blocked decisions retain holdings; incomplete decisions cannot support adoption",
                "no final model selection, holdout evaluation or actual order",
            ],
        },
        root,
    )
