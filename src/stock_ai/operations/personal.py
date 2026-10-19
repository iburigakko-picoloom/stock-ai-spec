"""Read-only personal research comparison against the existing portfolio ledger.

App input never replaces execution/cash/tax records. A successful research
comparison is not model adoption, a live recommendation or an order.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from stock_ai.decision.costs import CostPolicy, TransactionCostEngine
from stock_ai.decision.engine import (
    DailyPortfolioDecisionEngine,
    DecisionCandidate,
    DecisionEngineConfig,
    SearchSpaceTooLarge,
)
from stock_ai.decision.tax import SimpleJapanTaxEngine, TaxPolicy
from stock_ai.domain import (
    ExecutionRecord,
    ExecutionStatus,
    MarketSnapshot,
    PortfolioProposal,
    PortfolioState,
    Security,
    TaxState,
)
from stock_ai.domain.models import DailyDecisionAudit, PersonalPublicationGuard, Prediction
from stock_ai.operations.daily import DAILY_NEXT_SESSION_CLOSE_LABEL, PredictionSnapshot, content_id
from stock_ai.operations.manual_portfolio import (
    Digest,
    Identifier,
    ImportedManualPortfolio,
    InputModel,
)

if TYPE_CHECKING:
    from stock_ai.operations.store import OperationalStore

JST = ZoneInfo("Asia/Tokyo")
Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class AccountBinding(InputModel):
    manual_account_id: Identifier
    ledger_bucket_id: str = Field(min_length=1)


class ExplicitTaxState(InputModel):
    """All amounts are required: omitted tax inputs must never become zero."""

    account_bucket_id: str = Field(min_length=1)
    tax_year: int = Field(ge=2000, le=2200)
    realized_gain_ytd: Amount
    realized_loss_ytd: Amount
    loss_carryforward_user_input: Amount
    nisa_annual_capacity_user_input: Amount | None
    nisa_lifetime_capacity_user_input: Amount | None


class PersonalSettings(InputModel):
    version: str = Field(min_length=1)
    bindings: tuple[AccountBinding, ...]
    cash_basis: Literal["total_including_reserved", "deployable_after_reserved"]
    budget_basis: Literal["maximum_total_equity_market_value"]
    nisa_capacity_basis: Literal["remaining_purchase_notional_no_same_day_sale_restore"]
    reviewed_drawdown_preference_percent: float = Field(gt=0, le=100)
    tax_inputs: tuple[ExplicitTaxState, ...]
    cost_policy: CostPolicy
    tax_policy: TaxPolicy
    decision_policy: DecisionEngineConfig

    @model_validator(mode="after")
    def unique_bindings_and_daily_policy(self) -> Self:
        for keys in (
            [x.manual_account_id for x in self.bindings],
            [x.ledger_bucket_id for x in self.bindings],
            [x.account_bucket_id for x in self.tax_inputs],
        ):
            if len(keys) != len(set(keys)):
                raise ValueError("personal account bindings and tax inputs must be unique")
        if self.decision_policy.horizon_weights != (Decimal(0), Decimal(0), Decimal(1)):
            raise ValueError("personal daily comparison requires the frozen 20d policy")
        return self


class PersonalMarket(InputModel):
    market: MarketSnapshot
    observed_at: AwareDatetime
    securities: tuple[Security, ...]
    # A tuple gives an immutable representation and lets validation reject duplicates.
    average_daily_trading_values: tuple[tuple[str, Annotated[Decimal, Field(gt=0)]], ...]

    @model_validator(mode="after")
    def unique_evidence(self) -> Self:
        for keys in (
            [x.symbol for x in self.securities],
            [x[0] for x in self.average_daily_trading_values],
        ):
            if len(keys) != len(set(keys)):
                raise ValueError("personal market evidence must be unique by symbol")
        return self


class PersonalComparisonRequest(InputModel):
    """Explicit research scenario; production state is always loaded from the store."""

    checked_at: AwareDatetime
    maximum_input_age_hours: int = Field(gt=0, le=120)
    settings: PersonalSettings | None = None
    market: PersonalMarket | None = None


class ComparisonBlock(InputModel):
    code: str
    account_id: str | None = None
    symbol: str | None = None


class PersonalComparison(InputModel):
    schema_version: Literal["personal-research-comparison-v1"] = "personal-research-comparison-v1"
    comparison_id: Digest
    checked_at: AwareDatetime
    inputs_sha256: Digest
    request: PersonalComparisonRequest
    implementation_sha256: tuple[tuple[str, Digest], ...]
    manual_revision_id: Digest | None
    owner_scope_hash: Digest | None
    ledger_portfolio_id: str | None
    forecast_snapshot_id: Digest | None
    holding_symbols: tuple[str, ...]
    blocking_reasons: tuple[ComparisonBlock, ...]
    proposal: PortfolioProposal | None
    investment_budget_yen: Amount | None
    selected_equity_value_yen: Amount | None
    budget_exceeded_by_existing_holdings: bool
    drawdown_preference_is_guarantee: Literal[False] = False
    research_only: Literal[True] = True
    adoption_eligible: Literal[False] = False
    applied_to_ledger: Literal[False] = False
    manual_context_sha256: Digest | None = Field(default=None, exclude_if=lambda v: v is None)
    warnings: tuple[str, ...] = (
        "RISK_PREFERENCE_RECORDED_NOT_A_DRAWDOWN_BOUND",
        "RESEARCH_PRICE_COST_TAX_ASSUMPTIONS_NOT_LIVE_EXECUTION_EVIDENCE",
        "MODEL_ADOPTION_AND_FINAL_EVALUATION_STILL_REQUIRED",
    )

    @model_validator(mode="after")
    def identity_and_state(self) -> Self:
        if self.comparison_id != content_id(
            self.model_dump(mode="json", exclude={"comparison_id"})
        ):
            raise ValueError("personal comparison identity mismatch")
        if (self.proposal is None) != bool(self.blocking_reasons):
            raise ValueError("blocked comparisons must not contain a proposal")
        if self.proposal is not None and (
            not self.proposal.is_research_only or self.proposal.is_order_instruction
        ):
            raise ValueError("personal comparison must remain research only")
        return self


def manual_context_digest(
    portfolio: PortfolioState, forecast: PredictionSnapshot, request: PersonalComparisonRequest,
) -> str:
    """Bind a research consultation to the same price-marked ledger and inputs."""
    if request.market is None or request.settings is None:
        raise ValueError("Complete market and personal settings required")
    marked = portfolio.model_copy(update={
        "as_of": forecast.as_of,
        "positions": tuple(
            p.model_copy(update={"market_price": request.market.market.prices[p.symbol]})
            for p in portfolio.positions if p.shares > 0
        ),
    })
    return content_id({"forecast": forecast.model_dump(mode="json"),
                       "portfolio": marked.model_dump(mode="json"),
                       "request": request.model_dump(mode="json")})


def implementation_hashes(settings: PersonalSettings | None) -> tuple[tuple[str, str], ...]:
    names: tuple[str, ...] = (
        "operations/personal.py", "operations/manual_portfolio.py", "operations/daily.py",
        "domain/models.py", "decision/engine.py", "decision/costs.py", "decision/tax.py",
    )
    if (settings is not None
            and settings.decision_policy.version == "daily-decision-engine-v3-bounded"):
        names += ("decision/bounded.py",)
    root = Path(__file__).resolve().parents[1]
    return tuple((name, hashlib.sha256((root / name).read_bytes()).hexdigest()) for name in names)


def compare_personal(
    request: PersonalComparisonRequest,
    *,
    manual: ImportedManualPortfolio | None,
    ledger: PortfolioState | None,
    forecast: PredictionSnapshot | None,
    executions: tuple[ExecutionRecord, ...],
    publication_guard: PersonalPublicationGuard | None = None,
) -> PersonalComparison:
    """Reconcile every account/holding and run the existing cost/tax/HOLD engine."""
    # Revalidate even constructed/model_copy values before using them in a proposal.
    request = PersonalComparisonRequest.model_validate_json(request.model_dump_json())
    manual = (
        None
        if manual is None
        else ImportedManualPortfolio.model_validate_json(manual.model_dump_json())
    )
    ledger = (
        None if ledger is None else PortfolioState.model_validate_json(ledger.model_dump_json())
    )
    forecast = (
        None
        if forecast is None
        else PredictionSnapshot.model_validate_json(forecast.model_dump_json())
    )
    executions = tuple(
        sorted(
            (ExecutionRecord.model_validate_json(x.model_dump_json()) for x in executions),
            key=lambda x: x.execution_id,
        )
    )
    inputs_hash = content_id(
        {
            "request": request.model_dump(mode="json"),
            "manual": None if manual is None else manual.model_dump(mode="json"),
            "ledger": None if ledger is None else ledger.model_dump(mode="json"),
            "forecast": None if forecast is None else forecast.model_dump(mode="json"),
            "executions": [
                x.model_dump(mode="json") for x in sorted(executions, key=lambda x: x.execution_id)
            ],
        }
    )
    blocks: list[ComparisonBlock] = []

    def block(code: str, account: str | None = None, symbol: str | None = None) -> None:
        item = ComparisonBlock(code=code, account_id=account, symbol=symbol)
        if item not in blocks:
            blocks.append(item)

    for name, value in (
        ("MANUAL_INPUT", manual),
        ("LEDGER", ledger),
        ("FORECAST", forecast),
        ("SETTINGS", request.settings),
        ("MARKET", request.market),
    ):
        if value is None:
            block(name + "_MISSING")
    profile = None if manual is None else manual.portfolio
    holdings = () if profile is None else profile.holding_symbols
    budget = (
        None
        if profile is None or profile.investment_budget_yen is None
        else Decimal(profile.investment_budget_yen)
    )
    if profile is not None:
        for field in profile.missing_fields:
            block("INPUT_MISSING_" + field.upper())
    as_of = request.checked_at if forecast is None else forecast.as_of
    age = timedelta(hours=request.maximum_input_age_hours)
    if forecast is not None:
        if forecast.label_definition != DAILY_NEXT_SESSION_CLOSE_LABEL:
            block("FORECAST_LABEL_DEFINITION_UNVERIFIED")
        cutoff = as_of.astimezone(JST)
        if (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) != (11, 30, 0, 0):
            block("FORECAST_NOT_1130_FREEZE")
        if (
            as_of > request.checked_at
            or as_of.astimezone(JST).date() != request.checked_at.astimezone(JST).date()
        ):
            block("FORECAST_NOT_CURRENT_DAY")
        if forecast.generated_at > request.checked_at or as_of - forecast.data_as_of > age:
            block("FORECAST_DATA_STALE_OR_NOT_RECEIVED")
        for reason in forecast.blocking_reasons:
            block("FORECAST_BLOCKED_" + reason)
        if set(holdings) != set(forecast.holding_symbols):
            block("FORECAST_HOLDINGS_DIFFER")
        for symbol in sorted(set(holdings) - {x.symbol for x in forecast.predictions}):
            block("HELD_FORECAST_MISSING", symbol=symbol)
    if manual is not None and (manual.received_at > as_of or as_of - manual.export.saved_at > age):
        block("MANUAL_INPUT_STALE_OR_AFTER_FORECAST")
    if ledger is not None and (ledger.as_of > as_of or as_of - ledger.as_of > age):
        block("LEDGER_STALE_OR_AFTER_FORECAST")
    settings = request.settings
    if profile is not None and settings is not None:
        if settings.reviewed_drawdown_preference_percent != profile.maximum_drawdown_percent:
            block("RISK_PREFERENCE_CHANGED")
    if manual is not None and ledger is not None and settings is not None:
        _reconcile(manual, ledger, settings, block)
    if ledger is not None:
        if len({x.execution_id for x in executions}) != len(executions):
            block("DUPLICATE_EXECUTION")
        by_id = {x.execution_id: x for x in executions}
        if set(ledger.applied_execution_ids) - set(by_id):
            block("APPLIED_EXECUTION_RECORD_MISSING")
        for execution in executions:
            if execution.executed_at > as_of:
                block("EXECUTION_AFTER_FORECAST")
            if (
                execution.filled_shares
                and execution.execution_id not in ledger.applied_execution_ids
            ):
                block("UNAPPLIED_EXECUTION", execution.account_bucket_id, execution.symbol)
            if (
                execution.execution_id in ledger.applied_execution_ids
                and execution.executed_at > ledger.as_of
            ):
                block("APPLIED_EXECUTION_AFTER_LEDGER")
            if execution.status in (ExecutionStatus.OPEN, ExecutionStatus.PARTIALLY_FILLED):
                block("OPEN_EXECUTION", execution.account_bucket_id, execution.symbol)
        if any(x.tax_year != as_of.astimezone(JST).year for x in ledger.tax_states):
            block("TAX_YEAR_MISMATCH")
    evidence = request.market
    if evidence is not None:
        if evidence.market.as_of != as_of:
            block("MARKET_CUTOFF_MISMATCH")
        if evidence.observed_at > as_of or as_of - evidence.observed_at > age:
            block("MARKET_STALE_OR_FUTURE")
        if evidence.observed_at > evidence.market.available_at:
            block("MARKET_OBSERVED_AFTER_AVAILABILITY")
        if forecast is not None:
            securities = {x.symbol: x for x in evidence.securities}
            adv = dict(evidence.average_daily_trading_values)
            for symbol in sorted(set(forecast.candidate_symbols) | set(holdings)):
                if (
                    symbol not in securities
                    or evidence.market.prices.get(symbol, Decimal(0)) <= 0
                    or symbol not in adv
                ):
                    block("MARKET_EVIDENCE_MISSING", symbol=symbol)
    manual_context = None
    if forecast is not None and not forecast.risk_available:
        if not blocks:
            assert ledger is not None
            manual_context = manual_context_digest(ledger, forecast, request)
        block("FORECAST_RISK_UNAVAILABLE")
    proposal = None
    selected_value = None
    if not blocks:
        assert ledger is not None and forecast is not None and settings is not None
        assert evidence is not None and budget is not None
        current = PortfolioState.model_validate(
            {
                **ledger.model_dump(),
                "as_of": as_of,
                "positions": tuple(
                    x.model_copy(update={"market_price": evidence.market.prices[x.symbol]})
                    for x in ledger.positions
                    if x.shares > 0
                ),
            }
        )
        securities = {x.symbol: x for x in evidence.securities}
        adv = dict(evidence.average_daily_trading_values)
        candidates = tuple(
            DecisionCandidate(
                security=securities[p.symbol],
                account_bucket_id=b.bucket_id,
                price=evidence.market.prices[p.symbol],
                prediction=p,
                average_daily_trading_value=adv[p.symbol],
            )
            for b in current.account_buckets
            for p in forecast.predictions
            if isinstance(p, Prediction)
        )
        engine = DailyPortfolioDecisionEngine(
            config=settings.decision_policy,
            cost_engine=TransactionCostEngine(settings.cost_policy),
            tax_engine=SimpleJapanTaxEngine(settings.tax_policy),
        )
        try:
            result = engine.propose(
                portfolio=current,
                candidates=candidates,
                generated_at=request.checked_at,
                model_bundle_version=forecast.model_version,
                maximum_invested_value=budget,
                purchase_limits={
                    state.account_bucket_id: min(
                        state.nisa_annual_capacity_user_input or Decimal(0),
                        state.nisa_lifetime_capacity_user_input or Decimal(0),
                    )
                    for state in current.tax_states
                    if next(
                        b for b in current.account_buckets if b.bucket_id == state.account_bucket_id
                    ).account_type.value
                    == "nisa"
                },
            )
        except SearchSpaceTooLarge:
            block("SEARCH_CAP_EXCEEDED")
        except ValueError:
            block("DECISION_INPUT_INCOMPATIBLE")
        else:
            audit = DailyDecisionAudit(
                as_of=as_of,
                forecast_content_sha256=content_id(forecast.model_dump(mode="json")),
                market_content_sha256=content_id(evidence.model_dump(mode="json")),
                portfolio_content_sha256=content_id(current.model_dump(mode="json")),
                candidate_evidence_sha256=content_id(
                    [x.model_dump(mode="json") for x in candidates]
                ),
                source_report_ids=(),
            )
            proposal = PortfolioProposal.model_validate(
                {
                    **result.model_dump(),
                    "proposal_id": result.proposal_id + "-personal-" + inputs_hash[:16],
                    "daily_audit": audit,
                    "is_research_only": True,
                    "personal_guard": publication_guard,
                }
            )
            selected_value = sum(
                (x.target_shares * evidence.market.prices[x.symbol] for x in proposal.targets),
                Decimal(0),
            )
    values = dict(
        checked_at=request.checked_at,
        inputs_sha256=inputs_hash,
        request=request,
        implementation_sha256=implementation_hashes(request.settings),
        manual_revision_id=None if manual is None else manual.export.revision_id,
        owner_scope_hash=None if manual is None else manual.owner_scope_hash,
        ledger_portfolio_id=None if ledger is None else ledger.portfolio_id,
        forecast_snapshot_id=None if forecast is None else forecast.snapshot_id,
        holding_symbols=holdings,
        blocking_reasons=tuple(blocks),
        proposal=proposal,
        manual_context_sha256=manual_context,
        investment_budget_yen=budget,
        selected_equity_value_yen=selected_value,
        budget_exceeded_by_existing_holdings=selected_value is not None
        and budget is not None
        and selected_value > budget,
    )
    provisional = PersonalComparison.model_construct(
        _fields_set=set(values), comparison_id="0" * 64, **values
    )
    payload = provisional.model_dump(mode="json", exclude={"comparison_id"})
    return PersonalComparison.model_validate({**payload, "comparison_id": content_id(payload)})


class _Blocker(Protocol):
    def __call__(
        self, code: str, account: str | None = None, symbol: str | None = None
    ) -> None: ...


def _reconcile(
    manual: ImportedManualPortfolio,
    ledger: PortfolioState,
    settings: PersonalSettings,
    block: _Blocker,
) -> None:
    profile = manual.portfolio
    mapping = {x.manual_account_id: x.ledger_bucket_id for x in settings.bindings}
    buckets = {x.bucket_id: x for x in ledger.account_buckets}
    if set(mapping) != {x.id for x in profile.accounts} or set(mapping.values()) != set(buckets):
        block("ACCOUNT_MAPPING_INCOMPLETE")
        return
    for account in profile.accounts:
        bucket = buckets[mapping[account.id]]
        if (account.account_type, account.withholding_mode) != (
            bucket.account_type,
            bucket.withholding_mode,
        ):
            block("ACCOUNT_CLASSIFICATION_DIFFERS", account.id)
        cash = ledger.cash_map()[bucket.bucket_id]
        expected_cash = (
            cash.available_cash
            if settings.cash_basis == "total_including_reserved"
            else cash.deployable_cash
        )
        if (
            account.available_cash_yen is None
            or Decimal(account.available_cash_yen) != expected_cash
        ):
            block("CASH_DIFFERS", account.id)
    positions = ledger.position_map()
    manual_positions = {(x.symbol, mapping[x.account_id]): x for x in profile.holdings}
    nonzero = {key: value for key, value in positions.items() if value.shares > 0}
    for key in sorted(set(nonzero) | set(manual_positions)):
        actual, stated = nonzero.get(key), manual_positions.get(key)
        if actual is None or stated is None or actual.shares != stated.shares:
            block("HOLDING_SHARES_DIFFER", key[1], key[0])
        elif (
            stated.average_acquisition_price_yen is None
            or actual.average_acquisition_price != Decimal(stated.average_acquisition_price_yen)
        ):
            block("ACQUISITION_PRICE_DIFFERS", key[1], key[0])
    tax = {
        x.account_bucket_id: TaxState.model_validate(x.model_dump()) for x in settings.tax_inputs
    }
    if tax != ledger.tax_state_map():
        block("TAX_STATE_NOT_RECONCILED")
    for bucket in ledger.account_buckets:
        if (bucket.fee_policy_id, bucket.tax_policy_id) != (
            settings.cost_policy.policy_id,
            settings.tax_policy.policy_id,
        ):
            block("COST_TAX_POLICY_DIFFERS", bucket.bucket_id)
        if bucket.account_type.value == "nisa":
            state = ledger.tax_state_map()[bucket.bucket_id]
            if (
                state.nisa_annual_capacity_user_input is None
                or state.nisa_lifetime_capacity_user_input is None
            ):
                block("NISA_CAPACITY_UNKNOWN", bucket.bucket_id)


def compare_stored_personal(
    store: OperationalStore,
    request: PersonalComparisonRequest,
    *,
    now: datetime | None = None,
    forecast_snapshot_id: str | None = None,
    publication_guard: PersonalPublicationGuard | None = None,
) -> PersonalComparison:
    """Read authoritative records twice; concurrent input changes invalidate the result."""

    def read_inputs() -> tuple[
        ImportedManualPortfolio | None,
        PortfolioState | None,
        PredictionSnapshot | None,
        tuple[ExecutionRecord, ...],
    ]:
        return (
            store.latest_manual_portfolio(),
            store.latest_portfolio(),
            (store.latest_prediction_snapshot() if forecast_snapshot_id is None
             else store.prediction_snapshot(forecast_snapshot_id)),
            store.executions(),
        )

    request = request.model_copy(update={"checked_at": now or datetime.now(UTC)})
    before = read_inputs()
    result = compare_personal(
        request, manual=before[0], ledger=before[1], forecast=before[2], executions=before[3],
        publication_guard=publication_guard,
    )
    if read_inputs() != before:
        from stock_ai.operations.store import OperationalConflictError

        raise OperationalConflictError("personal comparison inputs changed; recompute")
    return result
