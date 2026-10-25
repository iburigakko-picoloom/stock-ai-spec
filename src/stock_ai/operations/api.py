"""Local-only FastAPI surface for the mobile PWA.

The mutation surface records user intent and actual fills.  It deliberately has
no broker connection, order submission, order cancellation, or order amendment
endpoint.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stock_ai.domain import (
    ExecutionRecord,
    PortfolioProposal,
    UserDecision,
    UserDecisionLine,
)
from stock_ai.operations.chatgpt_manual import (
    ExternalAiPermission,
    permission_record,
    read_permission_record,
)
from stock_ai.operations.chatgpt_research import ResearchConfiguration
from stock_ai.operations.daily import (
    DAILY_NEXT_SESSION_CLOSE_LABEL,
    CompanyResearchRecord,
    OwnerAdoptionReview,
    PredictionSnapshot,
    content_id,
    export_prediction_snapshot,
    prediction_score,
    validate_research_link,
)
from stock_ai.operations.models import (
    DailyOperationStatus,
    PaperReadoutPeriod,
    PipelineState,
)
from stock_ai.operations.personal import PersonalComparisonRequest, compare_stored_personal
from stock_ai.operations.store import (
    OperationalConflictError,
    OperationalIntegrityError,
    OperationalStorageBusyError,
    OperationalStore,
    PortfolioBaseConflictError,
    ReconciliationConflictError,
)

JST = ZoneInfo("Asia/Tokyo")
MANUAL_INTENT_HEADER = "manual-record"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
PROPOSAL_DISPLAY_STATES = frozenset(
    {
        PipelineState.PROPOSAL_READY,
        PipelineState.USER_DECISION_SAVED,
        PipelineState.EXECUTION_PENDING,
        PipelineState.EXECUTION_RECORDED,
        PipelineState.MARKET_CLOSED,
    }
)
PROPOSAL_ACTION_STATES = frozenset(
    {PipelineState.PROPOSAL_READY, PipelineState.USER_DECISION_SAVED}
)


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class DecisionLineInput(ApiModel):
    proposal_line_id: str = Field(min_length=1)
    selected_target_shares: int = Field(ge=0)
    note: str | None = None


class DecisionReviewInput(ApiModel):
    selected_targets: Mapping[str, int]


class SaveDecisionInput(ApiModel):
    decision_id: str = Field(default_factory=lambda: f"decision-{uuid4()}")
    version: int = Field(ge=1)
    saved_at: datetime
    lines: tuple[DecisionLineInput, ...]
    confirms_manual_order_only: bool = True


class ExecutionInput(ApiModel):
    execution_id: str = Field(default_factory=lambda: f"execution-{uuid4()}")
    executed_at: datetime
    symbol: str = Field(min_length=1)
    account_bucket_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    side: str = Field(min_length=1)
    ordered_shares: int = Field(ge=0)
    filled_shares: int = Field(ge=0)
    average_fill_price: Decimal | None = Field(default=None, ge=0)
    actual_commission: Decimal = Field(default=Decimal("0"), ge=0)
    actual_other_cost: Decimal = Field(default=Decimal("0"), ge=0)
    tax_withheld: Decimal = Field(default=Decimal("0"), ge=0)
    confirm_difference: bool = False


class ApplyExecutionsInput(ApiModel):
    next_as_of: datetime
    next_portfolio_id: str = Field(min_length=1)


class ResearchStartInput(ApiModel):
    configuration: ResearchConfiguration
    rerun_previous_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ResearchClaimInput(ApiModel):
    retry: bool = Field(default=False, strict=True)


class ResearchReceiptInput(ApiModel):
    response: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{1,100}$")
    interrupted: bool = Field(default=False, strict=True)


class CsvPreviewInput(ApiModel):
    csv_text: str = Field(min_length=1)
    preview_id: str = Field(default_factory=lambda: f"import-{uuid4()}")


class ConfirmImportInput(ApiModel):
    accepted_conflict_ids: tuple[str, ...] = ()


class ConfirmPositionReconciliationInput(ApiModel):
    next_portfolio_id: str = Field(min_length=1)
    confirm_all_differences: bool = False


class DailyImportInput(ApiModel):
    json_text: str = Field(min_length=1, max_length=2_000_000)
    confirmation_hash: str | None = None


def _daily_import(
    body: DailyImportInput,
) -> PredictionSnapshot | CompanyResearchRecord | OwnerAdoptionReview:
    try:
        raw = json.loads(body.json_text)
        if not isinstance(raw, dict):
            raise ValueError("JSON object required")
        if raw.get("schema_version") in (
            "daily-prediction-snapshot-v1", "daily-prediction-snapshot-v2"
        ):
            return PredictionSnapshot.model_validate(raw)
        if raw.get("schema_version") == "company-research-v1":
            return CompanyResearchRecord.model_validate(raw)
        if raw.get("schema_version") == "owner-adoption-review-v1":
            return OwnerAdoptionReview.model_validate(raw)
        raise ValueError("unsupported daily import schema")
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="invalid daily import: " + str(exc)) from exc


def _require_manual_intent(
    intent: Annotated[str | None, Header(alias="X-Stock-AI-Intent")] = None,
) -> None:
    if intent != MANUAL_INTENT_HEADER:
        raise HTTPException(
            status_code=428,
            detail="manual record confirmation header is required; this does not submit an order",
        )


def _line_view(line: Any) -> dict[str, object]:
    return {
        "lineId": line.line_id,
        "symbol": line.symbol,
        "companyName": line.company_name,
        "accountBucketId": line.account_bucket_id,
        "currentShares": line.current_shares,
        "recommendedShares": line.recommended_shares,
        "shareDifference": line.share_difference,
        "action": line.action.value,
        "referencePrice": str(line.reference_price),
        "currentMarketValue": str(line.current_market_value),
        "recommendedMarketValue": str(line.recommended_market_value),
        "estimatedRequiredOrReleasedCash": str(line.estimated_cash_required_or_released),
        "holdExpectedValue": str(line.hold_expected_value),
        "proposedExpectedValue": str(line.proposed_expected_value),
        "estimatedTransactionCost": str(line.transaction_cost.total),
        "estimatedTaxEffect": str(line.estimated_tax_effect),
        "estimatedTaxCashWithholding": str(line.estimated_tax_cash_withholding),
        "netExpectedImprovement": str(line.net_expected_improvement),
        "downsideLevel": line.downside_risk,
        "uncertaintyLevel": line.uncertainty,
        "positiveReasons": list(line.human_readable_reasons[:3]),
        "negativeReasons": list(line.human_readable_reasons[3:6]),
    }


def _proposal_view(proposal: PortfolioProposal) -> dict[str, object]:
    lines = [_line_view(line) for line in proposal.lines]
    changed = [line for line in proposal.lines if line.share_difference != 0]
    estimated_sell = sum(
        (
            -line.estimated_cash_required_or_released
            for line in proposal.lines
            if line.share_difference < 0
        ),
        Decimal("0"),
    )
    estimated_buy = sum(
        (
            line.estimated_cash_required_or_released
            for line in proposal.lines
            if line.share_difference > 0
        ),
        Decimal("0"),
    )
    return {
        "proposalId": proposal.proposal_id,
        "asOf": proposal.as_of.isoformat(),
        "generatedAt": proposal.generated_at.isoformat(),
        "modelBundleVersion": proposal.model_bundle_version,
        "decisionEngineVersion": proposal.decision_engine_version,
        "status": "RESEARCH_ONLY" if proposal.is_research_only else "READY",
        "isResearchOnly": proposal.is_research_only,
        "isOrderInstruction": False,
        "lines": lines,
        "estimatedSellValue": str(estimated_sell),
        "estimatedBuyValue": str(estimated_buy),
        "estimatedTransactionCost": str(
            sum((line.transaction_cost.total for line in proposal.lines), Decimal("0"))
        ),
        "estimatedTaxEffect": str(
            sum((line.estimated_tax_effect for line in proposal.lines), Decimal("0"))
        ),
        "estimatedTaxCashWithholding": str(
            sum((line.estimated_tax_cash_withholding for line in proposal.lines), Decimal("0"))
        ),
        "estimatedCashAfter": {
            key: str(value) for key, value in proposal.estimated_cash_after.items()
        },
        "changeCount": len(changed),
        "holdExpectedValue": str(proposal.hold_utility),
        "proposedExpectedValue": str(proposal.proposed_utility),
        "netImprovement": str(proposal.net_improvement),
        "noTradeReason": proposal.no_trade_reason,
    }


def _active_proposal(
    store: OperationalStore, business_date: date, *, actionable: bool = False
) -> PortfolioProposal | None:
    status = store.daily_status(business_date)
    if status is None or status.is_stale:
        return None
    allowed = PROPOSAL_ACTION_STATES if actionable else PROPOSAL_DISPLAY_STATES
    if status.pipeline_state not in allowed:
        return None
    if status.proposal_id is None:
        raise OperationalIntegrityError("active daily status has no proposal identity")
    try:
        proposal = store.proposal(status.proposal_id)
    except KeyError as exc:
        raise OperationalIntegrityError("daily status references a missing proposal") from exc
    if proposal.as_of.astimezone(JST).date() != business_date:
        raise OperationalIntegrityError("daily status proposal belongs to another business date")
    if not store.proposal_inputs_current(proposal):
        return None
    return proposal


def _require_active_proposal(
    store: OperationalStore, proposal_id: str, *, actionable: bool
) -> PortfolioProposal:
    try:
        proposal = store.proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="proposal not found") from exc
    business_date = proposal.as_of.astimezone(JST).date()
    active = _active_proposal(store, business_date, actionable=actionable)
    if active is None or active.proposal_id != proposal_id:
        raise OperationalConflictError("proposal is not active for its business date")
    return proposal


def _today(store: OperationalStore, business_date: date) -> dict[str, object]:
    status = store.daily_status(business_date)
    proposal = _active_proposal(store, business_date)
    if status is None:
        state = PipelineState.PRE_MARKET
        blocking_reason = None
        is_stale = False
    else:
        state = status.pipeline_state
        blocking_reason = status.blocking_reason
        is_stale = status.is_stale
        if (not is_stale and proposal is None and status.pipeline_state in PROPOSAL_DISPLAY_STATES):
            state, is_stale = PipelineState.STALE_DATA, True
            blocking_reason = "PERSONAL_INPUTS_CHANGED"
        if state is PipelineState.CASH_ONLY and not store.cash_only_inputs_current(business_date):
            state, is_stale = PipelineState.STALE_DATA, True
            blocking_reason = "PERSONAL_INPUTS_CHANGED"
    return {
        "businessDate": business_date.isoformat(),
        "pipelineState": state.value,
        "isStale": is_stale,
        "blockingReason": blocking_reason,
        "runtimeMode": store.metadata("runtime_mode") or "UNCONFIGURED",
        "proposal": (_proposal_view(proposal) if proposal is not None else None),
    }


def create_app(
    database_path: Path,
    *,
    static_dir: Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    store = OperationalStore(database_path)

    def current_time() -> datetime:
        value = datetime.now(JST) if clock is None else clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("operational API clock must be timezone-aware")
        return value.astimezone(JST)

    app = FastAPI(
        title="Stock AI Decision Support",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        description="Local decision-support API. It cannot submit securities orders.",
    )
    app.state.store = store

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        host = request.url.hostname
        if host is None or host.lower() not in LOCAL_HOSTS:
            return JSONResponse(status_code=421, content={"detail": "local host required"})
        origin = request.headers.get("origin")
        if origin is not None and request.method not in {"GET", "HEAD", "OPTIONS"}:
            parsed_origin = urlsplit(origin)
            if (
                parsed_origin.scheme not in {"http", "https"}
                or parsed_origin.hostname is None
                or parsed_origin.hostname.lower() not in LOCAL_HOSTS
            ):
                return JSONResponse(status_code=403, content={"detail": "local origin required"})
        if request.url.path.startswith("/api/"):
            try:
                store.verify_integrity()
            except OperationalIntegrityError:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": (
                            "operational data integrity check failed; proposal display stopped"
                        )
                    },
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(OperationalConflictError)
    async def conflict_handler(_request: Request, exc: OperationalConflictError) -> JSONResponse:
        if isinstance(exc, (PortfolioBaseConflictError, ReconciliationConflictError)):
            return JSONResponse(status_code=409, content={"detail": str(exc), "code": exc.code})
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(OperationalStorageBusyError)
    async def busy_handler(_request: Request, _exc: OperationalStorageBusyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"code": "STORAGE_BUSY", "detail": "保存処理中です。再試行してください。"},
        )

    @app.exception_handler(OperationalIntegrityError)
    async def integrity_handler(_request: Request, _exc: OperationalIntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "operational data integrity check failed; proposal display stopped"},
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        counts = store.verify_integrity()
        return {
            "status": "ok",
            "orderSubmissionAvailable": False,
            "runtimeMode": store.metadata("runtime_mode") or "UNCONFIGURED",
            "records": sum(counts.values()),
        }

    @app.get("/api/v1/status")
    def status(
        business_date: Annotated[date | None, Query(alias="businessDate")] = None,
    ) -> dict[str, object]:
        selected = business_date or current_time().date()
        payload = _today(store, selected)
        proposal = _active_proposal(store, selected) if payload["proposal"] is not None else None
        portfolio = store.latest_portfolio()
        daily = store.daily_status(selected)
        return {
            "businessDate": selected.isoformat(),
            "marketState": "UNKNOWN",
            "pipelineState": payload["pipelineState"],
            "dataAsOf": None if daily is None or daily.data_as_of is None else daily.data_as_of,
            "morningDataAsOf": (
                None
                if daily is None or daily.morning_data_as_of is None
                else daily.morning_data_as_of
            ),
            "proposalGeneratedAt": None if proposal is None else proposal.generated_at,
            "portfolioUpdatedAt": None if portfolio is None else portfolio.as_of,
            "modelBundleVersion": None if proposal is None else proposal.model_bundle_version,
            "isStale": payload["isStale"],
            "blockingReason": payload["blockingReason"],
            "orderSubmissionAvailable": False,
        }

    @app.get("/api/v1/daily/latest")
    def daily_latest() -> dict[str, object]:
        snapshot = store.latest_prediction_snapshot()
        if snapshot is None:
            return {"snapshot": None, "research": [], "chatgpt_research": [], "is_stale": True}
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "research": [
                item.model_dump(mode="json")
                for item in store.company_research(snapshot.snapshot_id)
            ],
            "is_stale": snapshot.as_of.astimezone(JST).date() != current_time().date(),
            "research_symbols": snapshot.research_symbols(),
            "chatgpt_research": [
                item.model_dump(mode="json")
                for item in store.chatgpt_research(snapshot.snapshot_id)
            ],
        }

    @app.get("/api/v1/research/{snapshot_id}")
    def research_runs(snapshot_id: str) -> object:
        try:
            snapshot = store.prediction_snapshot(snapshot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="snapshot not found") from exc
        return {"runs": store.research_runs(snapshot.snapshot_id)}

    @app.post("/api/v1/research/{snapshot_id}/{symbol}/start")
    def research_start(
        snapshot_id: str, symbol: str, body: ResearchStartInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        try:
            snapshot = store.prediction_snapshot(snapshot_id)
            # A source-backed company name may not yet be available. Preserve
            # the verified symbol instead of accepting a caller's invented name.
            proposal = _active_proposal(store, snapshot.as_of.astimezone(JST).date())
            company_name = next((
                item.company_name for item in (() if proposal is None else proposal.lines)
                if item.symbol == symbol
            ), f"証券コード {symbol}")
            return store.begin_research(
                snapshot_id, symbol, body.configuration, company_name=company_name,
                now=current_time(), rerun_previous_id=body.rerun_previous_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="snapshot not found") from exc
        except OperationalConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/research/permission")
    def research_permission(
        body: ExternalAiPermission,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        try:
            body.require(current_time(), "account_codex")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # This is an owner's dated attestation, not provider verification.
        store.set_metadata("external-ai-permission:account_codex", permission_record(body))
        return {
            "service": body.service,
            "checked_at": body.checked_at,
            "basis": "owner_attestation",
            "expires_after_hours": 24,
        }

    @app.post("/api/v1/research/{run_id}/claim")
    def research_claim(
        run_id: str, body: ResearchClaimInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        try:
            saved = store.research_run(run_id)
            if saved["record"] is not None:
                # Reading a completed receipt does not send a provider request.
                return {"state": "completed", **saved}
            permission = store.metadata("external-ai-permission:account_codex")
            if permission is None:
                raise ValueError(
                    "EXTERNAL_AI_PERMISSION_UNCONFIRMED: 外部送信の利用条件を確認してください"
                )
            try:
                read_permission_record(permission).require(current_time(), "account_codex")
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(status_code=422, detail=(
                    "EXTERNAL_AI_PERMISSION_UNCONFIRMED: "
                    "連携先の利用条件・契約・設定を確認してください"
                )) from exc
            return store.claim_research(run_id, now=current_time(), retry=body.retry)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="research run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/research/{attempt_id}/receipt")
    def research_receipt(
        attempt_id: str, body: ResearchReceiptInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        if (body.error_code is not None and any(item is not None for item in (
            body.response, body.started_at, body.completed_at,
        ))) or (body.error_code is None and body.interrupted):
            raise HTTPException(status_code=422, detail="use one research outcome only")
        try:
            return store.finish_research(
                attempt_id, now=current_time(), response=body.response,
                started_at=body.started_at, completed_at=body.completed_at,
                error_code=body.error_code, interrupted=body.interrupted,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="research attempt not found") from exc
        except OperationalConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/personal/readiness")
    def personal_readiness() -> object:
        request = PersonalComparisonRequest(checked_at=current_time(), maximum_input_age_hours=72)
        return compare_stored_personal(store, request, now=current_time()).model_dump(mode="json")

    @app.post("/api/v1/personal/compare")
    def personal_compare(
        body: PersonalComparisonRequest,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        return compare_stored_personal(store, body, now=current_time()).model_dump(mode="json")

    @app.get("/api/v1/daily/{snapshot_id}/export")
    def export_daily(snapshot_id: str, format: str = "json") -> Response:
        try:
            snapshot = store.prediction_snapshot(snapshot_id)
            data = export_prediction_snapshot(snapshot, format=format)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="snapshot not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        media = {"json": "application/json", "csv": "text/csv", "markdown": "text/markdown"}
        return Response(data, media_type=media[format], headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/daily/import/preview")
    def preview_daily_import(body: DailyImportInput) -> dict[str, object]:
        item = _daily_import(body)
        if isinstance(item, CompanyResearchRecord):
            try:
                validate_research_link(item, store.prediction_snapshot(item.prediction_snapshot_id))
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="invalid prediction reference") from exc
        return {
            "confirmation_hash": content_id(item.model_dump(mode="json")),
            "record": item.model_dump(mode="json"),
            "writes_performed": False,
        }

    @app.post("/api/v1/daily/import/confirm")
    def confirm_daily_import(
        body: DailyImportInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> dict[str, object]:
        item = _daily_import(body)
        if body.confirmation_hash != content_id(item.model_dump(mode="json")):
            raise HTTPException(status_code=409, detail="preview confirmation hash mismatch")
        try:
            if isinstance(item, PredictionSnapshot):
                inserted = store.append_prediction_snapshot(item)
            elif isinstance(item, CompanyResearchRecord):
                inserted = store.append_company_research(item)
            else:
                inserted = store.append_adoption_review(item)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"inserted": inserted, "record": item.model_dump(mode="json")}

    @app.get("/api/v1/home")
    def home(
        business_date: Annotated[date | None, Query(alias="businessDate")] = None,
    ) -> dict[str, object]:
        selected = business_date or current_time().date()
        portfolio = store.latest_portfolio()
        if portfolio is None:
            return {"portfolio": None, "holdings": [], "blockingReason": "保有未登録"}
        proposal = _active_proposal(store, selected)
        proposal_lines = (
            {(line.symbol, line.account_bucket_id): line for line in proposal.lines}
            if proposal is not None
            else {}
        )
        holdings = []
        for position in portfolio.positions:
            line = proposal_lines.get(position.key)
            holdings.append(
                {
                    "symbol": position.symbol,
                    "companyName": line.company_name if line is not None else position.symbol,
                    "accountBucketId": position.account_bucket_id,
                    "shares": position.shares,
                    "averageAcquisitionPrice": str(position.average_acquisition_price),
                    "currentPrice": str(position.market_price),
                    "marketValue": str(position.market_value),
                    "unrealizedPnlAmount": str(position.market_value - position.book_value),
                    "latestAction": None if line is None else line.action.value,
                    "recommendedShares": None if line is None else line.recommended_shares,
                    "proposalId": None if proposal is None else proposal.proposal_id,
                }
            )
        cash_value = sum((item.available_cash for item in portfolio.cash), Decimal("0"))
        equity_value = sum((item.market_value for item in portfolio.positions), Decimal("0"))
        return {
            "runtimeMode": store.metadata("runtime_mode") or "UNCONFIGURED",
            "portfolio": {
                "asOf": portfolio.as_of,
                "totalAssets": str(cash_value + equity_value),
                "cashValue": str(cash_value),
                "reservedCash": str(sum(
                    (item.reserved_cash for item in portfolio.cash), Decimal("0"))),
                "buyingPower": str(sum(
                    (item.deployable_cash for item in portfolio.cash), Decimal("0"))),
                "equityValue": str(equity_value),
                "holdingsCount": len(portfolio.positions),
            },
            "holdings": holdings,
            "blockingReason": None,
        }

    @app.get("/api/v1/today")
    def today(
        business_date: Annotated[date | None, Query(alias="businessDate")] = None,
    ) -> dict[str, object]:
        now = current_time()
        selected_date = business_date or now.date()
        payload = _today(store, selected_date)
        end = now.replace(year=selected_date.year, month=selected_date.month,
                          day=selected_date.day, hour=23, minute=59, second=59)
        snapshot = store.latest_archived_prediction(min(now, end))
        payload["savedAnalysis"] = None
        if snapshot is not None:
            symbols = snapshot.research_symbols()
            predictions = {item.symbol: item for item in snapshot.predictions}
            payload["savedAnalysis"] = {
                "snapshotId": snapshot.snapshot_id,
                "asOf": snapshot.as_of.isoformat(),
                "generatedAt": snapshot.generated_at.isoformat(),
                "dataAsOf": snapshot.data_as_of.isoformat(),
                "modelVersion": snapshot.model_version,
                "readOnly": True,
                "holdingSymbols": snapshot.holding_symbols,
                "predictions": [predictions[symbol].model_dump(mode="json") for symbol in symbols],
            }
        return payload

    @app.get("/api/v1/proposals/{proposal_id}")
    def get_proposal(proposal_id: str) -> dict[str, object]:
        return _proposal_view(_require_active_proposal(store, proposal_id, actionable=False))

    @app.post("/api/v1/proposals/{proposal_id}/review")
    def review_decision(
        proposal_id: str,
        body: DecisionReviewInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        _require_active_proposal(store, proposal_id, actionable=True)
        return jsonable_encoder(
            store.review_decision(proposal_id, body.selected_targets), by_alias=True
        )

    @app.post("/api/v1/proposals/{proposal_id}/decisions", status_code=201)
    def save_decision(
        proposal_id: str,
        body: SaveDecisionInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        proposal = _require_active_proposal(store, proposal_id, actionable=True)
        business_date = proposal.as_of.astimezone(JST).date()
        if body.saved_at.astimezone(JST).date() != business_date:
            raise OperationalConflictError(
                "decision timestamp must match the proposal business date"
            )
        decision = UserDecision(
            decision_id=body.decision_id,
            proposal_id=proposal_id,
            version=body.version,
            saved_at=body.saved_at,
            lines=tuple(
                UserDecisionLine(
                    proposal_line_id=line.proposal_line_id,
                    selected_target_shares=line.selected_target_shares,
                    note=line.note,
                )
                for line in body.lines
            ),
            confirms_manual_order_only=body.confirms_manual_order_only,
        )
        store.save_decision(decision)
        previous = store.daily_status(business_date)
        store.set_daily_status(
            DailyOperationStatus(
                business_date=business_date,
                pipeline_state=PipelineState.USER_DECISION_SAVED,
                updated_at=decision.saved_at,
                data_as_of=None if previous is None else previous.data_as_of,
                morning_data_as_of=None if previous is None else previous.morning_data_as_of,
                proposal_id=proposal_id,
            )
        )
        return jsonable_encoder(decision, by_alias=True)

    @app.get("/api/v1/proposals/{proposal_id}/decision")
    def latest_decision(proposal_id: str) -> object:
        _require_active_proposal(store, proposal_id, actionable=False)
        decision = store.latest_decision(proposal_id)
        return None if decision is None else jsonable_encoder(decision, by_alias=True)

    @app.post("/api/v1/decisions/{decision_id}/executions", status_code=201)
    def record_execution(
        decision_id: str,
        body: ExecutionInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        if body.executed_at.utcoffset() is None or body.executed_at > current_time():
            raise HTTPException(
                status_code=422,
                detail="約定日時はタイムゾーンを含む現在以前の日時を指定してください。",
            )
        try:
            execution = ExecutionRecord.model_validate(
                {
                    **body.model_dump(exclude={"confirm_difference"}),
                    "decision_id": decision_id,
                    "source": "manual",
                }
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail="実約定の状態・数量・金額を確認してください。",
            ) from exc
        store.append_execution(
            execution, confirm_difference=body.confirm_difference, update_daily_status=True,
        )
        return jsonable_encoder(execution, by_alias=True)

    @app.get("/api/v1/decisions/{decision_id}/executions")
    def executions(decision_id: str) -> object:
        return jsonable_encoder(store.executions(decision_id=decision_id), by_alias=True)

    @app.post("/api/v1/portfolio/apply-executions")
    def apply_recorded_executions(
        body: ApplyExecutionsInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        now = current_time()
        if body.next_as_of.utcoffset() is None or body.next_as_of > now:
            raise HTTPException(
                status_code=422,
                detail="反映日時はタイムゾーンを含む現在以前の日時を指定してください。",
            )
        try:
            state = store.apply_unapplied_executions(
                next_as_of=body.next_as_of,
                next_portfolio_id=body.next_portfolio_id,
                created_at=now,
            )
        except PortfolioBaseConflictError:
            raise
        except OperationalConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail="保存済みの実保有と競合しています。保存内容を確認し、現在の実保有より後の反映日時を指定してください。",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="約定の日時・数量・金額と反映日時を確認してください。記録済みの約定をすべて含む日時が必要です。",
            ) from exc
        return jsonable_encoder(state, by_alias=True)

    @app.post("/api/v1/imports/executions/preview")
    def preview_import(
        body: CsvPreviewInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        preview = store.preview_execution_csv(
            body.csv_text,
            preview_id=body.preview_id,
            created_at=current_time(),
        )
        return jsonable_encoder(preview, by_alias=True)

    @app.post("/api/v1/imports/executions/{preview_id}/confirm")
    def confirm_import(
        preview_id: str,
        body: ConfirmImportInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> dict[str, int]:
        imported, skipped = store.confirm_execution_import(
            preview_id, accepted_conflict_ids=body.accepted_conflict_ids
        )
        return {"imported": imported, "skipped": skipped}

    @app.post("/api/v1/imports/positions/preview")
    def preview_positions(
        body: CsvPreviewInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        preview = store.preview_position_reconciliation_csv(
            body.csv_text,
            preview_id=body.preview_id,
            created_at=current_time(),
        )
        return jsonable_encoder(preview, by_alias=True)

    @app.post("/api/v1/imports/positions/{preview_id}/confirm")
    def confirm_positions(
        preview_id: str,
        body: ConfirmPositionReconciliationInput,
        _intent: Annotated[None, Depends(_require_manual_intent)],
    ) -> object:
        state = store.confirm_position_reconciliation(
            preview_id,
            next_portfolio_id=body.next_portfolio_id,
            confirm_all_differences=body.confirm_all_differences,
            created_at=current_time(),
        )
        return jsonable_encoder(state, by_alias=True)

    @app.get("/api/v1/ranking")
    def ranking(
        rank_type: Annotated[str, Query(alias="rankType")] = "overall",
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> object:
        records = store.latest_rankings(rank_type, limit=limit)
        snapshot = store.latest_prediction_snapshot()
        if (snapshot is not None and rank_type in ("overall", "5d", "20d")
                and (not records or snapshot.as_of > max(item.as_of for item in records)
                     or (snapshot.schema_version == "daily-prediction-snapshot-v2"
                         and snapshot.as_of == max(item.as_of for item in records)))):
            horizon: Literal[5, 20] = 5 if rank_type == "5d" else 20
            ordered = sorted(snapshot.predictions, key=lambda item: (
                -prediction_score(item, horizon), item.symbol,
            ))
            names = {item.symbol: item.company_name for item in records}
            # Read-only projection of the original numerical snapshot. Overall
            # uses the 20d priority; it never adds the two horizons or creates orders.
            return [{
                "ranking_id": content_id({"snapshot": snapshot.snapshot_id,
                                          "rank_type": rank_type, "symbol": item.symbol}),
                "as_of": snapshot.as_of, "symbol": item.symbol,
                "company_name": names.get(item.symbol, item.symbol), "rank_type": rank_type,
                "rank": index + 1, "total_universe": len(ordered),
                "percentile": (index + 1) / len(ordered),
                "candidate_status": "保有" if item.symbol in snapshot.holding_symbols else "候補",
                "portfolio_action": None, "model_bundle_version": snapshot.model_version,
                "data_snapshot_id": snapshot.data_snapshot_id,
            } for index, item in enumerate(ordered[:limit])]
        return [
            {
                **jsonable_encoder(item, by_alias=True),
                "percentile": item.rank / item.total_universe,
            }
            for item in records
        ]

    @app.get("/api/v1/stocks/{symbol}")
    def stock_detail(
        symbol: str,
        business_date: Annotated[date | None, Query(alias="businessDate")] = None,
    ) -> dict[str, object]:
        portfolio = store.latest_portfolio()
        proposal_date = business_date or current_time().date()
        today_proposal = _active_proposal(store, proposal_date)
        positions = (
            []
            if portfolio is None
            else [
                jsonable_encoder(item, by_alias=True)
                for item in portfolio.positions
                if item.symbol == symbol
            ]
        )
        lines = (
            []
            if today_proposal is None
            else [_line_view(item) for item in today_proposal.lines if item.symbol == symbol]
        )
        snapshot = store.latest_prediction_snapshot()
        if snapshot is not None and snapshot.as_of.astimezone(JST).date() > proposal_date:
            snapshot = None
        prediction = next((
            item for item in (() if snapshot is None else snapshot.predictions)
            if item.symbol == symbol
        ), None)
        if not positions and not lines and prediction is None:
            raise HTTPException(status_code=404, detail="symbol not found")
        return {
            "symbol": symbol,
            "positions": positions,
            "proposalLines": lines,
            "proposal": None if today_proposal is None else _proposal_view(today_proposal),
            "forecast": None if prediction is None or snapshot is None else {
                "snapshotId": snapshot.snapshot_id, "asOf": snapshot.as_of,
                "generatedAt": snapshot.generated_at,
                "isStale": snapshot.as_of.astimezone(JST).date() != proposal_date,
                "mode": snapshot.mode, "blockingReasons": snapshot.blocking_reasons,
                "labelDefinition": snapshot.label_definition,
                "labelDefinitionSupported": (
                    snapshot.label_definition == DAILY_NEXT_SESSION_CLOSE_LABEL
                ),
                "prediction": prediction.model_dump(mode="json"),
                "researchEligible": (symbol in snapshot.research_symbols()
                                     and snapshot.label_definition
                                     == DAILY_NEXT_SESSION_CLOSE_LABEL),
            },
            "researchRuns": [] if snapshot is None else store.research_runs(
                snapshot.snapshot_id, symbol,
            ),
            "chatgptResearch": [] if snapshot is None else [
                item.model_dump(mode="json")
                for item in store.chatgpt_research(snapshot.snapshot_id)
                if item.context.symbol == symbol
            ],
        }

    @app.get("/api/v1/validation")
    def validation(
        mode: Annotated[str, Query(pattern="^(paper|live|historical)$")] = "paper",
    ) -> object:
        if mode == "paper":
            summary = jsonable_encoder(store.paper_summary(), by_alias=True)
            summary["weekly_readouts"] = jsonable_encoder(
                store.paper_readouts(PaperReadoutPeriod.WEEKLY), by_alias=True
            )
            summary["monthly_readouts"] = jsonable_encoder(
                store.paper_readouts(PaperReadoutPeriod.MONTHLY), by_alias=True
            )
            summary["series"] = jsonable_encoder(store.paper_series(), by_alias=True)
            summary["horizon_sessions"] = 1
            return summary
        if mode == "live":
            executions_count = len(store.executions())
            return {
                "mode": "live",
                "observations": executions_count,
                "blockingReason": (None if executions_count else "実運用データはまだありません"),
            }
        return {
            "mode": "historical",
            "blockingReason": "認証済み研究reportを運用台帳へ登録してください",
        }

    @app.get("/api/v1/notifications")
    def notifications() -> object:
        return jsonable_encoder(store.notifications(), by_alias=True)

    @app.get("/api/v1/settings")
    def settings() -> dict[str, object]:
        portfolio = store.latest_portfolio()
        proposal = _active_proposal(store, current_time().date())
        policy_snapshot = (
            None if proposal is None else store.decision_policy_snapshot(proposal.proposal_id)
        )
        decision_config = None if policy_snapshot is None else policy_snapshot.config
        tax_states = {} if portfolio is None else portfolio.tax_state_map()
        return {
            "runtime": {"remoteAccess": "LOCALHOST_ONLY", "orderSubmission": "OUT_OF_SCOPE"},
            "runtimeMode": store.metadata("runtime_mode") or "UNCONFIGURED",
            "data": {
                "jQuantsApiKeyConfigured": bool(os.environ.get("JQUANTS_API_KEY")),
                "credentialValueExposed": False,
            },
            "capital": {
                "availableCash": None
                if portfolio is None
                else str(sum((item.available_cash for item in portfolio.cash), Decimal("0"))),
                "reservedCash": None
                if portfolio is None
                else str(sum((item.reserved_cash for item in portfolio.cash), Decimal("0"))),
                "asOf": None if portfolio is None else portfolio.as_of,
                "minimumCashRatio": (
                    None if decision_config is None else str(decision_config.minimum_cash_ratio)
                ),
                "dailyProposalLimit": None,
            },
            "accounts": []
            if portfolio is None
            else [
                {
                    "bucketId": item.bucket_id,
                    "accountId": item.account_id,
                    "accountType": item.account_type.value,
                    "withholdingMode": item.withholding_mode.value,
                    "feePolicyId": item.fee_policy_id,
                    "taxPolicyId": item.tax_policy_id,
                    "taxYear": tax_states[item.bucket_id].tax_year,
                    "realizedGainYtd": str(tax_states[item.bucket_id].realized_gain_ytd),
                    "realizedLossYtd": str(tax_states[item.bucket_id].realized_loss_ytd),
                    "lossCarryforward": str(
                        tax_states[item.bucket_id].loss_carryforward_user_input
                    ),
                    "nisaAnnualCapacity": (
                        None
                        if tax_states[item.bucket_id].nisa_annual_capacity_user_input is None
                        else str(tax_states[item.bucket_id].nisa_annual_capacity_user_input)
                    ),
                    "nisaLifetimeCapacity": (
                        None
                        if tax_states[item.bucket_id].nisa_lifetime_capacity_user_input is None
                        else str(tax_states[item.bucket_id].nisa_lifetime_capacity_user_input)
                    ),
                }
                for item in portfolio.account_buckets
            ],
            "decisionPolicies": {
                "decisionEngineVersion": None
                if proposal is None
                else proposal.decision_engine_version,
                "costPolicyId": None if proposal is None else proposal.cost_policy_id,
                "costPolicyVersion": None if proposal is None else proposal.cost_policy_version,
                "taxPolicyId": None if proposal is None else proposal.tax_policy_id,
                "taxPolicyVersion": None if proposal is None else proposal.tax_policy_version,
                "roundLotShares": 100 if decision_config is None else decision_config.lot_size,
                "maximumPositions": (
                    None if decision_config is None else decision_config.maximum_positions
                ),
                "maximumSymbolWeight": (
                    None if decision_config is None else str(decision_config.maximum_symbol_weight)
                ),
                "maximumSectorWeight": (
                    None if decision_config is None else str(decision_config.maximum_sector_weight)
                ),
                "maximumTurnoverRatio": (
                    None if decision_config is None else str(decision_config.maximum_turnover_ratio)
                ),
                "maximumTradeAdvRatio": (
                    None
                    if decision_config is None
                    else str(decision_config.maximum_trade_adv_ratio)
                ),
                "minimumImprovementYen": (
                    None
                    if decision_config is None
                    else str(decision_config.minimum_improvement_yen)
                ),
                "uncertaintyBufferYen": (
                    None if decision_config is None else str(decision_config.uncertainty_buffer_yen)
                ),
            },
            "notifications": {
                "inApp": "AVAILABLE",
                "webPush": "BLOCKED_BY_CONFIGURATION",
            },
            "model": {
                "morningChampion": "BLOCKED_BY_DATA_CAPABILITY",
                "trainedAt": None,
                "trainingDataEnd": None,
                "validationStatus": "BLOCKED_BY_DATA_CAPABILITY",
                "automaticPromotion": False,
            },
            "decision": {
                "freezeTime": "11:30 JST",
                "recommendedTradeTime": "12:30 JST 後場寄り",
                "method": "Daily Portfolio Decision Engine",
            },
        }

    if static_dir is not None and static_dir.resolve().is_dir():
        resolved_static = static_dir.resolve()
        assets = resolved_static / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def pwa_fallback(full_path: str) -> FileResponse:
            requested = (resolved_static / full_path).resolve()
            if requested.is_relative_to(resolved_static) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(resolved_static / "index.html")

    return app
