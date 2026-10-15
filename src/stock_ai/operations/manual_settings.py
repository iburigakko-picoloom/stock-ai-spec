"""Incomplete owner-entered settings, separate from confirmed account ledgers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from stock_ai.decision.costs import CostPolicy
from stock_ai.decision.engine import DecisionEngineConfig
from stock_ai.decision.tax import TaxPolicy
from stock_ai.operations.daily import content_id
from stock_ai.operations.manual_portfolio import (
    Digest,
    Identifier,
    InputModel,
    ManualPortfolio,
    Money,
)
from stock_ai.operations.personal import AccountBinding, ExplicitTaxState, PersonalSettings


class AccountSettings(InputModel):
    account_id: Identifier
    reserved_cash_yen: Money | None
    pending_activity: Literal["unknown", "none", "pending"]
    realized_gain_ytd: Money | None
    realized_loss_ytd: Money | None
    loss_carryforward_user_input: Money | None
    nisa_annual_capacity_user_input: Money | None
    nisa_lifetime_capacity_user_input: Money | None


class CostAssumptions(InputModel):
    commission_fixed_yen: Money | None
    commission_bps: Money | None
    minimum_commission_yen: Money | None
    zero_commission_confirmed: StrictBool
    full_spread_bps: Money | None
    slippage_bps: Money | None
    impact_bps_at_full_adv: Money | None

    @model_validator(mode="after")
    def explicit_commission(self) -> Self:
        amounts = (self.commission_fixed_yen, self.commission_bps, self.minimum_commission_yen)
        if all(x is not None and Decimal(x) == 0 for x in amounts):
            if not self.zero_commission_confirmed:
                raise ValueError("zero commission requires explicit confirmation")
        if self.zero_commission_confirmed and any(
            x is not None and Decimal(x) != 0 for x in amounts
        ):
            raise ValueError("commission confirmation contradicts input")
        return self


class TaxAssumptions(InputModel):
    effective_from: date | None
    taxable_rate_percent: Money | None
    nisa_opportunity_cost_percent: Money | None

    @model_validator(mode="after")
    def rates_in_range(self) -> Self:
        if any(
            x is not None and Decimal(x) > 100
            for x in (self.taxable_rate_percent, self.nisa_opportunity_cost_percent)
        ):
            raise ValueError("tax assumption percent exceeds 100")
        return self


class ManualPersonalSettings(InputModel):
    """Matches manual-personal-settings-v1; unknown values remain null."""

    schema_version: Literal["manual-personal-settings-v1"]
    portfolio_revision_id: Digest
    cash_basis: Literal["total_including_reserved", "deployable_after_reserved"] | None
    budget_basis: Literal["maximum_total_equity_market_value"] | None
    nisa_capacity_basis: Literal["remaining_purchase_notional_no_same_day_sale_restore"]
    tax_year: Annotated[StrictInt, Field(ge=2000, le=2200)] | None
    accounts: Annotated[tuple[AccountSettings, ...], Field(max_length=30)]
    cost_assumptions: CostAssumptions
    tax_assumptions: TaxAssumptions
    research_decision_policy: Literal["daily-decision-engine-v2"]
    research_conditions_reviewed: StrictBool

    @model_validator(mode="after")
    def unique_accounts(self) -> Self:
        ids = [x.account_id for x in self.accounts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate settings account")
        return self

    def validate_portfolio(self, revision_id: str, portfolio: ManualPortfolio) -> None:
        if self.portfolio_revision_id != revision_id:
            raise ValueError("settings reference an outdated portfolio revision")
        accounts = {x.id: x for x in portfolio.accounts}
        if set(accounts) != {x.account_id for x in self.accounts}:
            raise ValueError("settings must include every and only current account")
        for item in self.accounts:
            source = accounts[item.account_id]
            if source.account_type != "nisa" and (
                item.nisa_annual_capacity_user_input is not None
                or item.nisa_lifetime_capacity_user_input is not None
            ):
                raise ValueError("NISA capacity supplied for a non-NISA account")
            if (
                self.cash_basis == "total_including_reserved"
                and source.available_cash_yen is not None
                and item.reserved_cash_yen is not None
                and Decimal(item.reserved_cash_yen) > Decimal(source.available_cash_yen)
            ):
                raise ValueError("reserved cash exceeds total cash")

    def missing_fields(self, portfolio: ManualPortfolio) -> tuple[str, ...]:
        gaps = set(portfolio.missing_fields)
        if self.cash_basis is None:
            gaps.add("cash_basis")
        if self.budget_basis is None:
            gaps.add("budget_basis")
        if self.tax_year is None:
            gaps.add("tax_year")
        for account in portfolio.accounts:
            item = next((x for x in self.accounts if x.account_id == account.id), None)
            if item is None:
                gaps.add("account_settings")
                continue
            if item.reserved_cash_yen is None:
                gaps.add("reserved_cash_yen")
            if item.pending_activity != "none":
                gaps.add("pending_activity")
            if any(
                x is None for x in (
                    item.realized_gain_ytd, item.realized_loss_ytd,
                    item.loss_carryforward_user_input,
                )
            ):
                gaps.add("realized_tax_state")
            if account.account_type == "nisa" and (
                item.nisa_annual_capacity_user_input is None
                or item.nisa_lifetime_capacity_user_input is None
            ):
                gaps.add("nisa_remaining_capacity")
        if any(
            value is None for key, value in self.cost_assumptions.model_dump().items()
            if key != "zero_commission_confirmed"
        ):
            gaps.add("cost_assumptions")
        if any(value is None for value in self.tax_assumptions.model_dump().values()):
            gaps.add("tax_assumptions")
        if not self.research_conditions_reviewed:
            gaps.add("research_conditions_reviewed")
        return tuple(sorted(gaps))

    def compile(self, revision_id: str, portfolio: ManualPortfolio) -> PersonalSettings:
        """Compile only fully explicit inputs; never use policy numeric defaults."""
        self.validate_portfolio(revision_id, portfolio)
        if self.missing_fields(portfolio):
            raise ValueError("personal settings are incomplete")
        costs = self.cost_assumptions
        taxes = self.tax_assumptions
        assert taxes.effective_from is not None and self.tax_year is not None
        assert self.cash_basis is not None and self.budget_basis is not None
        assert portfolio.maximum_drawdown_percent is not None

        def amount(value: str | None) -> Decimal:
            assert value is not None
            return Decimal(value)

        return PersonalSettings(
            version="manual-" + content_id(self.model_dump(mode="json")),
            bindings=tuple(
                AccountBinding(manual_account_id=x.id, ledger_bucket_id=x.id)
                for x in portfolio.accounts
            ),
            cash_basis=self.cash_basis,
            budget_basis=self.budget_basis,
            nisa_capacity_basis=self.nisa_capacity_basis,
            reviewed_drawdown_preference_percent=portfolio.maximum_drawdown_percent,
            tax_inputs=tuple(
                ExplicitTaxState(
                    account_bucket_id=x.account_id,
                    tax_year=self.tax_year,
                    realized_gain_ytd=amount(x.realized_gain_ytd),
                    realized_loss_ytd=amount(x.realized_loss_ytd),
                    loss_carryforward_user_input=amount(x.loss_carryforward_user_input),
                    nisa_annual_capacity_user_input=(
                        None if x.nisa_annual_capacity_user_input is None
                        else Decimal(x.nisa_annual_capacity_user_input)
                    ),
                    nisa_lifetime_capacity_user_input=(
                        None if x.nisa_lifetime_capacity_user_input is None
                        else Decimal(x.nisa_lifetime_capacity_user_input)
                    ),
                ) for x in self.accounts
            ),
            cost_policy=CostPolicy(
                policy_id="manual-cost-" + content_id(costs.model_dump(mode="json")),
                version="manual-v1",
                commission_fixed=amount(costs.commission_fixed_yen),
                commission_bps=amount(costs.commission_bps),
                minimum_commission=amount(costs.minimum_commission_yen),
                zero_commission_confirmed=costs.zero_commission_confirmed,
                full_spread_bps=amount(costs.full_spread_bps),
                slippage_bps=amount(costs.slippage_bps),
                impact_bps_at_full_adv=amount(costs.impact_bps_at_full_adv),
            ),
            tax_policy=TaxPolicy(
                policy_id="manual-tax-" + content_id(taxes.model_dump(mode="json")),
                version="manual-v1", effective_from=taxes.effective_from,
                taxable_rate=amount(taxes.taxable_rate_percent) / 100,
                nisa_opportunity_cost_rate=amount(taxes.nisa_opportunity_cost_percent) / 100,
            ),
            decision_policy=DecisionEngineConfig.daily(),
        )
