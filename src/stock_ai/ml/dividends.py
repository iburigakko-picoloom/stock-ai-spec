"""Audit J-Quants V2 dividend notice chains without backdating availability."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from stock_ai.ml.evaluation_audit import write_audit_receipt
from stock_ai.ml.market_nav import PinnedEvidence
from stock_ai.ml.nav import JST, NavAction, NavModel
from stock_ai.ml.selection import load_development_feature_selection

Amount = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class DividendNotice(BaseModel):
    """Provider field names; unknown new fields require an explicit schema review."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    PubDate: date
    PubTime: str = Field(pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    Code: str = Field(pattern=r"^[0-9A-Z]{5}$")
    RefNo: str = Field(min_length=1)
    CARefNo: str = Field(min_length=1)
    StatCode: Literal["1", "2", "3"]
    FRCode: Literal["1", "2"]
    IFCode: Literal["1", "2"]
    IFTerm: str
    BoardDate: date | None = None
    RecDate: date | None = None
    ExDate: date | None = None
    ActRecDate: date | None = None
    PayDate: date | None = None
    DivRate: Amount | None = None
    DistAmt: Amount | None = None
    RetEarn: Amount | None = None
    DeemDiv: Amount | None = None
    DeemCapGains: Amount | None = None
    NetAssetDecRatio: Amount | None = None
    CommSpecCode: Literal["0", "1", "2", "3"] = "0"
    CommDivRate: Amount | None = None
    SpecDivRate: Amount | None = None

    @field_validator("PubTime")
    @classmethod
    def valid_clock(cls, value: str) -> str:
        time.fromisoformat(value)
        return value

    @field_validator(
        "BoardDate", "RecDate", "ExDate", "ActRecDate", "PayDate", "DivRate", "DistAmt",
        "RetEarn", "DeemDiv", "DeemCapGains", "NetAssetDecRatio", "CommDivRate", "SpecDivRate",
        mode="before",
    )
    @classmethod
    def unspecified(cls, value: object) -> object:
        return None if value in ("", "-", None) else value

    @property
    def published_at(self) -> datetime:
        return datetime.combine(self.PubDate, time.fromisoformat(self.PubTime), JST)


class NoticeAvailability(NavModel):
    ref_no: str
    available_at: datetime
    # An archived receipt/publication evidence, never PubDate/PubTime alone.
    evidence: PinnedEvidence


class DividendPayment(NavModel):
    notice_ref_no: str
    payment_at: datetime
    # PayDate is scheduled and contains no time; an actual release needs evidence.
    evidence: PinnedEvidence


class DividendShareBasis(NavModel):
    notice_ref_no: str
    record_date_share_units_equal_entitlement_units: Literal[True]
    evidence: PinnedEvidence


class DividendRequest(NavModel):
    schema_version: Literal["dividend-projection-input-v1"] = "dividend-projection-input-v1"
    feature_selection_path: Path
    source: PinnedEvidence
    source_publication_start: date
    source_publication_end: date
    received_at: datetime
    as_of: datetime
    availability: tuple[NoticeAvailability, ...] = ()
    payments: tuple[DividendPayment, ...] = ()
    share_basis: tuple[DividendShareBasis, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.source_publication_start > self.source_publication_end:
            raise ValueError("reversed dividend source publication window")
        if len({a.ref_no for a in self.availability}) != len(self.availability):
            raise ValueError("duplicate notice availability")
        if len({p.notice_ref_no for p in self.payments}) != len(self.payments):
            raise ValueError("duplicate dividend payment")
        if len({b.notice_ref_no for b in self.share_basis}) != len(self.share_basis):
            raise ValueError("duplicate dividend share basis")
        return self


def _active_notices(
    notices: tuple[DividendNotice, ...], availability: dict[str, datetime], as_of: datetime,
) -> tuple[list[DividendNotice], list[str], list[str]]:
    groups: dict[tuple[str, str, str], list[DividendNotice]] = defaultdict(list)
    for notice in notices:
        if notice.published_at <= as_of:
            groups[(notice.Code, notice.FRCode, notice.CARefNo)].append(notice)
    active: list[DividendNotice] = []
    blockers: list[str] = []
    deleted: list[str] = []
    for (_, _, root), chain in sorted(groups.items()):
        known: list[DividendNotice] = []
        unknown = False
        for notice in chain:
            at = availability.get(notice.RefNo)
            if at is None:
                unknown = True
            elif at <= as_of:
                known.append(notice)
        if unknown:
            blockers.append(f"{root}:NOTICE_AVAILABILITY_NOT_PROVEN")
            continue
        if not known:
            continue
        known.sort(key=lambda n: n.published_at)
        roots = [n for n in known if n.StatCode == "1" and n.RefNo == root]
        if len(roots) != 1 or known[0] != roots[0]:
            blockers.append(f"{root}:MISSING_OR_LATE_CHAIN_ROOT")
            continue
        if len({n.published_at for n in known}) != len(known):
            blockers.append(f"{root}:AMBIGUOUS_PUBLICATION_ORDER")
            continue
        # RefNo is an identifier, not a publication-order key. A deletion closes
        # this series; any subsequent new notice must start its own root.
        if any(n.StatCode in ("1", "3") for n in known[1:-1]) or (
            len(known) > 1 and known[-1].StatCode == "1"
        ):
            blockers.append(f"{root}:INVALID_NOTICE_CHAIN")
        elif known[-1].StatCode == "3":
            deleted.append(root)
        else:
            active.append(known[-1])
    return active, blockers, deleted


def project_dividends(request: DividendRequest) -> dict[str, Any]:
    """Project known decided cash dividends; never infer full corporate coverage.

    Corrections are selected at the requested information time, then checked
    again at entitlement. A future correction, forecast or scheduled payment
    cannot become an earlier realized cash entitlement.
    """
    request = DividendRequest.model_validate(request.model_dump())
    features = load_development_feature_selection(request.feature_selection_path)
    boundary = date.fromisoformat(features.locked_holdout_start)
    if (request.source_publication_end >= boundary
            or request.as_of.astimezone(JST).date() >= boundary):
        raise ValueError("dividend projection reaches locked holdout")
    payload = json.loads(request.source.read())
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("invalid J-Quants V2 dividend response envelope")
    if payload.get("pagination_key") not in (None, ""):
        raise ValueError("dividend pagination is incomplete")
    by_id: dict[str, DividendNotice] = {}
    for raw in payload["data"]:
        notice = DividendNotice.model_validate(raw)
        if not request.source_publication_start <= notice.PubDate <= request.source_publication_end:
            raise ValueError("dividend notice outside pinned publication window")
        if notice.published_at > request.received_at:
            raise ValueError("notice publication follows actual receipt")
        if notice.StatCode == "1" and notice.RefNo != notice.CARefNo:
            raise ValueError("new dividend notice must reference itself")
        if notice.StatCode != "1" and notice.RefNo == notice.CARefNo:
            raise ValueError("correction/deletion needs a distinct root reference")
        if notice.RefNo in by_id and by_id[notice.RefNo] != notice:
            raise ValueError("conflicting dividend notice identity")
        by_id[notice.RefNo] = notice
    availability: dict[str, datetime] = {}
    for availability_item in request.availability:
        availability_item.evidence.read()
        available_notice = by_id.get(availability_item.ref_no)
        if available_notice is None or not (
            available_notice.published_at <= availability_item.available_at <= request.received_at
        ):
            raise ValueError("invalid notice availability or unknown reference")
        availability[availability_item.ref_no] = availability_item.available_at
    payments: dict[str, DividendPayment] = {}
    for payment_item in request.payments:
        payment_item.evidence.read()
        if (payment_item.notice_ref_no not in by_id
                or payment_item.payment_at > request.received_at):
            raise ValueError("payment refers to an unknown notice or unobserved future payment")
        payments[payment_item.notice_ref_no] = payment_item
    share_basis = set()
    for basis in request.share_basis:
        basis.evidence.read()
        if basis.notice_ref_no not in by_id:
            raise ValueError("share basis refers to an unknown dividend notice")
        share_basis.add(basis.notice_ref_no)
    notices = tuple(by_id.values())
    decisions, blockers, deleted = _active_notices(
        tuple(n for n in notices if n.FRCode == "1"), availability, request.as_of
    )
    forecasts, forecast_diagnostics, _ = _active_notices(
        tuple(n for n in notices if n.FRCode == "2"), availability, request.as_of
    )
    # A later deletion or changed ex-date must not erase an earlier entitlement.
    # Such changes need a dated ledger adjustment, which this adapter cannot
    # synthesize by replacing the original event.
    decided_chains: dict[tuple[str, str], list[DividendNotice]] = defaultdict(list)
    for candidate in notices:
        if candidate.FRCode == "1" and candidate.published_at <= request.as_of:
            decided_chains[(candidate.Code, candidate.CARefNo)].append(candidate)
    current = {(n.Code, n.CARefNo): n.RefNo for n in decisions}
    for chain_key, history in decided_chains.items():
        for ex_date in {n.ExDate for n in history if n.ExDate is not None}:
            effective = datetime.combine(ex_date, time(), JST)
            if effective > request.as_of:
                continue
            entitled, _, _ = _active_notices(tuple(history), availability, effective)
            if any(n.ExDate == ex_date and current.get(chain_key) != n.RefNo for n in entitled):
                blockers.append(
                    f"{chain_key[1]}:POST_ENTITLEMENT_REVISION_REQUIRES_LEDGER_UPDATE"
                )
    seen_entitlements: set[tuple[str, date | None, date | None]] = set()
    actions: list[NavAction] = []
    pending: list[str] = []
    for notice in decisions:
        key = notice.Code, notice.ExDate, notice.RecDate
        if key in seen_entitlements:
            blockers.append(f"{notice.RefNo}:DUPLICATE_DECIDED_ENTITLEMENT")
            continue
        seen_entitlements.add(key)
        if not re.fullmatch(r"[0-9A-Z]{4}0", notice.Code):
            blockers.append(f"{notice.RefNo}:NONSTANDARD_SECURITY_CODE")
            continue
        if notice.DivRate is None or notice.ExDate is None or notice.RecDate is None:
            blockers.append(f"{notice.RefNo}:INCOMPLETE_DIVIDEND_TERMS")
            continue
        if any(value not in (None, Decimal(0)) for value in (
            notice.DistAmt, notice.RetEarn, notice.DeemDiv,
            notice.DeemCapGains, notice.NetAssetDecRatio,
        )):
            blockers.append(f"{notice.RefNo}:UNSUPPORTED_CAPITAL_DISTRIBUTION")
            continue
        effective = datetime.combine(notice.ExDate, time(), JST)
        if effective > request.as_of:
            pending.append(notice.RefNo)
            continue
        if notice.ExDate > notice.RecDate:
            blockers.append(f"{notice.RefNo}:INVALID_ENTITLEMENT_DATES")
            continue
        chain = tuple(n for n in notices if (n.Code, n.FRCode, n.CARefNo) == (
            notice.Code, notice.FRCode, notice.CARefNo
        ))
        known_at_entitlement, earlier_blocks, _ = _active_notices(chain, availability, effective)
        if earlier_blocks or notice not in known_at_entitlement:
            blockers.append(f"{notice.RefNo}:TERMS_NOT_KNOWN_AT_ENTITLEMENT")
            continue
        if notice.RefNo not in share_basis:
            blockers.append(f"{notice.RefNo}:ENTITLEMENT_SHARE_BASIS_NOT_PROVEN")
            continue
        payment = payments.get(notice.RefNo)
        if payment is None:
            blockers.append(f"{notice.RefNo}:ACTUAL_PAYMENT_TIME_NOT_PROVEN")
            continue
        actions.append(NavAction(
            event_id=f"jquants-dividend:{notice.RefNo}", symbol=notice.Code[:-1], kind="dividend",
            effective_at=effective, available_at=availability[notice.RefNo],
            source_id=f"{request.source.sha256}:{notice.RefNo}",
            cash_per_share=notice.DivRate, payment_at=payment.payment_at,
        ))
    # Partial actions are diagnostic only. A blocked projection never provides
    # an apparently complete event list for a NAV run.
    return {
        "schema_version": "dividend-projection-result-v1",
        "status": "BLOCKED" if blockers else "COMPLETE",
        "input": request.model_dump(mode="json"), "research_only": True,
        "adoption_eligible": False, "corporate_action_coverage_verified": False,
        "holdout_rows_read": False, "no_order_sent": True,
        "unique_notices": len(notices), "active_decided_notices": len(decisions),
        "ignored_forecast_ids": [n.RefNo for n in forecasts], "deleted_series": deleted,
        "forecast_series_diagnostics": forecast_diagnostics,
        "pending_entitlement_ids": pending,
        "blockers": sorted(set(blockers)),
        "actions": [] if blockers else [a.model_dump(mode="json") for a in actions],
        "diagnostic_action_count": len(actions),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "PubDate/PubTime is not J-Quants availability; independent evidence is required.",
            "PayDate is scheduled and has no clock time; it is not actual buying-power release.",
            "No split/cash-conversion/other-rights completeness or no-event coverage is asserted.",
            "DivRate uses record-date shares; matching entitlement units require evidence.",
            "Post-entitlement finalizations/corrections require additional receivable accounting.",
        ],
    }


def write_dividend_projection(request: DividendRequest, root: Path) -> Path:
    return write_audit_receipt(project_dividends(request), root)
