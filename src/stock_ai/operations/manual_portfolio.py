"""Verified manual app inputs, separate from the execution and cash ledgers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, model_validator

Money = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$", strict=True)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]
Identifier = Annotated[
    str, Field(pattern=r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", strict=True)
]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ManualAccount(InputModel):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=60, strict=True)]
    account_type: Literal["unknown_manual", "taxable_specified", "taxable_general", "nisa"]
    withholding_mode: Literal["unknown", "withholding", "no_withholding", "not_applicable"]
    available_cash_yen: Money | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.name != self.name.strip():
            raise ValueError("account name must be normalized")
        if (self.account_type == "nisa") != (self.withholding_mode == "not_applicable"):
            raise ValueError("NISA withholding mismatch")
        if self.withholding_mode == "withholding" and self.account_type != "taxable_specified":
            raise ValueError("withholding requires specified taxable account")
        return self


class ManualHolding(InputModel):
    account_id: Identifier
    symbol: Annotated[str, Field(pattern=r"^[0-9A-Z]{4,5}$", strict=True)]
    shares: Annotated[StrictInt, Field(gt=0, le=1_000_000_000)]
    average_acquisition_price_yen: Money | None


class ManualPortfolio(InputModel):
    schema_version: Literal["manual-portfolio-v1"]
    holdings_status: Literal["unrecorded", "none", "recorded"]
    investment_budget_yen: Money | None
    maximum_drawdown_percent: Annotated[float, Field(gt=0, le=100, strict=True)] | None
    accounts: Annotated[tuple[ManualAccount, ...], Field(max_length=30)]
    holdings: Annotated[tuple[ManualHolding, ...], Field(max_length=200)]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        accounts = {account.id for account in self.accounts}
        keys = {(holding.account_id, holding.symbol) for holding in self.holdings}
        if len(accounts) != len(self.accounts) or len(keys) != len(self.holdings):
            raise ValueError("duplicate account or holding")
        if any(holding.account_id not in accounts for holding in self.holdings):
            raise ValueError("holding references unknown account")
        if (self.holdings_status == "recorded") != bool(self.holdings):
            raise ValueError("holding status differs from recorded holdings")
        return self

    @property
    def holding_symbols(self) -> tuple[str, ...]:
        return tuple(sorted({item.symbol for item in self.holdings}))

    @property
    def missing_fields(self) -> tuple[str, ...]:
        """Input gaps only; an empty list does not approve a model or a proposal."""
        gaps = []
        if self.holdings_status == "unrecorded":
            gaps.append("holdings_status")
        if self.investment_budget_yen is None:
            gaps.append("investment_budget_yen")
        if self.maximum_drawdown_percent is None:
            gaps.append("maximum_drawdown_percent")
        if not self.accounts:
            gaps.append("accounts")
        for account in self.accounts:
            if account.available_cash_yen is None:
                gaps.append("available_cash_yen")
            if account.account_type == "unknown_manual" or account.withholding_mode == "unknown":
                gaps.append("account_classification")
        if any(item.average_acquisition_price_yen is None for item in self.holdings):
            gaps.append("average_acquisition_price_yen")
        return tuple(sorted(set(gaps)))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strict_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(value: str) -> None:
        raise ValueError("non-finite JSON number")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


class PortfolioRevision(InputModel):
    owner: Annotated[str, Field(min_length=1, max_length=300, strict=True)]
    parent: Digest | None
    portfolio: ManualPortfolio


class PortfolioExport(InputModel):
    schema_version: Literal["manual-portfolio-export-v1"]
    revision_id: Digest
    revision_sequence: Annotated[StrictInt, Field(gt=0)]
    saved_at: AwareDatetime
    revision_json: Annotated[str, Field(max_length=150_000, strict=True)]

    @model_validator(mode="after")
    def verify_revision(self) -> Self:
        if digest(self.revision_json) != self.revision_id:
            raise ValueError("manual portfolio revision hash mismatch")
        PortfolioRevision.model_validate(strict_json(self.revision_json))
        return self

    @property
    def revision(self) -> PortfolioRevision:
        return PortfolioRevision.model_validate(strict_json(self.revision_json))


class ImportedManualPortfolio(InputModel):
    schema_version: Literal["imported-manual-portfolio-v1"] = "imported-manual-portfolio-v1"
    export_sha256: Digest
    export_json: Annotated[str, Field(max_length=200_000, strict=True)]
    received_at: AwareDatetime

    @model_validator(mode="after")
    def verified(self) -> Self:
        if digest(self.export_json) != self.export_sha256:
            raise ValueError("manual portfolio export hash mismatch")
        if self.export.saved_at > self.received_at:
            raise ValueError("manual portfolio saved after receipt")
        return self

    @property
    def export(self) -> PortfolioExport:
        return PortfolioExport.model_validate(strict_json(self.export_json))

    @property
    def owner_scope_hash(self) -> str:
        return digest(self.export.revision.owner)

    @property
    def portfolio(self) -> ManualPortfolio:
        return self.export.revision.portfolio

    @classmethod
    def from_response(cls, response: object, *, received_at: datetime) -> Self:
        if not isinstance(response, dict) or set(response) != {"export_sha256", "export_json"}:
            raise ValueError("invalid manual portfolio envelope")
        return cls.model_validate({**response, "received_at": received_at})
