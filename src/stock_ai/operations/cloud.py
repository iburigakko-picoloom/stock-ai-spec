"""Minimal result projection and verified, idempotent owner-private Sites sync."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from stock_ai.operations.daily import (
    CompanyResearchRecord,
    PredictionSnapshot,
    canonical_json,
    validate_research_link,
)

PRIVATE_SITE_ORIGIN = "https://stock-ai-private-daily.manato0618.chatgpt.site"


def cloud_projection(
    snapshot: PredictionSnapshot,
    research: Sequence[CompanyResearchRecord],
    *,
    training_completed: int,
) -> dict[str, Any]:
    """Project top candidates and all holdings, without accounts, raw data or secrets."""
    if not 0 <= training_completed <= 18:
        raise ValueError("invalid completed training count")
    symbols = set(snapshot.research_symbols())
    for record in research:
        validate_research_link(record, snapshot)
    return {
        "schema_version": "daily-cloud-v1",
        "kind": "predictions",
        "source_snapshot_id": snapshot.snapshot_id,
        "as_of": snapshot.as_of.isoformat(),
        "generated_at": snapshot.generated_at.isoformat(),
        "data_as_of": snapshot.data_as_of.isoformat(),
        "mode": snapshot.mode,
        "model_version": snapshot.model_version,
        "feature_version": snapshot.feature_version,
        "unit": snapshot.unit,
        "risk_horizon": snapshot.risk_horizon,
        "price_semantics": snapshot.price_semantics,
        "label_definition": snapshot.label_definition,
        "large_loss_threshold": snapshot.large_loss_threshold,
        "downside_quantile_alpha": snapshot.downside_quantile_alpha,
        "adoption_review_id": snapshot.adoption_review_id,
        "training_completed": training_completed,
        "training_total": 18,
        "blockers": list(snapshot.blocking_reasons),
        "forecasts": [
            {
                "symbol": item.symbol,
                "holding": item.symbol in snapshot.holding_symbols,
                "expected_return_1d": None,
                "expected_return_5d": item.expected_return_5d,
                "expected_return_20d": item.expected_return_20d,
                "downside_quantile": item.downside_quantile,
                "large_loss_probability": item.large_loss_probability,
                "uncertainty": item.uncertainty.combined,
            }
            for item in snapshot.predictions
            if item.symbol in symbols
        ],
        "research": [
            item.model_dump(
                mode="json",
                include={"research_id", "symbol", "reviewed_at", "conclusion", "findings"},
            )
            for item in research
        ],
    }


def sync_private_results(
    payload: dict[str, Any],
    *,
    bearer_token: str,
    origin: str = PRIVATE_SITE_ORIGIN,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, str]:
    """Send only to the pinned private origin, refuse redirects, and read bytes back.

    Caller supplies the Sites service credential from environment/OS storage. It is
    neither persisted nor included in exceptions. No data provider credentials or
    credentials for the existing public Site are used here.
    """
    parsed = urlsplit(origin)
    if origin != PRIVATE_SITE_ORIGIN or parsed.username or parsed.password or not bearer_token:
        raise ValueError("verified private Site origin and service token are required")
    payload_json = canonical_json(payload)
    if len(payload_json.encode("utf-8")) > 1_000_000:
        raise ValueError("private sync exceeds the bounded result payload")
    identity = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    headers = {
        "OAI-Sites-Authorization": "Bearer " + bearer_token,
        "X-Stock-AI-Sync": "private-v1",
    }
    try:
        with httpx.Client(
            headers=headers,
            follow_redirects=False,
            timeout=30,
            transport=transport,
        ) as client:
            response = client.post(
                origin + "/api/sync",
                json={
                    "snapshot_id": identity,
                    "payload_json": payload_json,
                },
            )
            response.raise_for_status()
            confirmation = response.json()
            if (
                confirmation.get("snapshot_id") != identity
                or confirmation.get("verified") is not True
            ):
                raise ValueError("private sync confirmation identity mismatch")
            readback = client.get(origin + "/api/sync", params={"id": identity})
            readback.raise_for_status()
            observed = readback.json()
            if (
                observed.get("snapshot_id") != identity
                or observed.get("payload_json") != payload_json
            ):
                raise ValueError("private sync readback differs from original projection")
            return {"snapshot_id": identity, "received_at": str(observed["received_at"])}
    except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError):
        raise RuntimeError(
            "private result sync failed; original local records were retained"
        ) from None
