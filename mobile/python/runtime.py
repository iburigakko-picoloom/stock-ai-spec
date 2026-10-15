"""Offline mobile adapter around the unchanged PC ledger/API and calculation code."""

from __future__ import annotations

import base64
import inspect
import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.routing import APIRoute, request_response

from stock_ai.operations.api import create_app
from stock_ai.operations.manual_portfolio import ManualPortfolio

from . import market, models
from .features import bundled_selection, calculate
from .portable_model import predict

STATE = Path("/stockai-state")
_app = None


def _async_call(fn):
    async def invoke(**kwargs):
        return fn(**kwargs)

    return invoke


def initialize(encoded: str = "") -> dict:
    global _app
    STATE.mkdir(exist_ok=True)
    if encoded:
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded, validate=True))) as archive:
            if set(archive.namelist()) - {"operations.sqlite3", "mobile.sqlite3"}:
                raise ValueError("Unexpected backup file")
            for name in archive.namelist():
                info = archive.getinfo(name)
                if info.file_size > 256 * 1024 * 1024:
                    raise ValueError("Backup exceeds mobile storage limit")
                content = archive.read(name)
                if not content.startswith(b"SQLite format 3\x00"):
                    raise ValueError("Invalid SQLite backup")
                # Verify BEFORE replacing any current state.
                probe = sqlite3.connect(":memory:")
                probe.deserialize(content)
                if probe.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Invalid SQLite integrity")
                probe.close()
                (STATE / name).write_bytes(content)
    _app = create_app(STATE / "operations.sqlite3")

    # WASM has no Python threads. Run the already-validated synchronous route
    # functions on this dedicated Web Worker, retaining FastAPI validation,
    # dependency checks, middleware, exception handlers and response schemas.
    def adapt(dependant):
        if dependant.call and not inspect.iscoroutinefunction(dependant.call):
            dependant.call = _async_call(dependant.call)
        for child in dependant.dependencies:
            adapt(child)

    for route in _app.routes:
        if isinstance(route, APIRoute):
            adapt(route.dependant)
            route.app = request_response(route.get_route_handler())
    _app.state.store.verify_integrity()
    with mobile_db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS manual_inputs ("
            "id INTEGER PRIMARY KEY, saved_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
    market.initialize(STATE / "mobile.sqlite3")
    models.initialize(STATE / "mobile.sqlite3")
    return {"research_only": True, "order_submission": False}


def mobile_db():
    return sqlite3.connect(STATE / "mobile.sqlite3")


def export_state() -> str:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("operations.sqlite3", "mobile.sqlite3"):
            connection = sqlite3.connect(STATE / name)
            backup_path = STATE / "export.sqlite3"
            target = sqlite3.connect(backup_path)
            connection.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
            target.close()
            archive.writestr(name, backup_path.read_bytes())
            backup_path.unlink()
            connection.close()
    return base64.b64encode(output.getvalue()).decode("ascii")


async def request(method: str, path: str, body: str = "null") -> dict:
    if _app is None:
        raise RuntimeError("Runtime not initialized")
    if method not in {"GET", "POST"} or not path.startswith("/api/v1/") or "://" in path:
        return {"status": 400, "body": {"detail": "Unsupported local operation"}}
    if path == "/api/v1/mobile/portfolio":
        if method == "POST":
            try:
                value = ManualPortfolio.model_validate_json(body)
            except ValueError:
                return {"status": 422, "body": {"detail": "口座・保有の入力を確認してください。"}}
            with mobile_db() as db:
                db.execute(
                    "INSERT INTO manual_inputs(saved_at,payload) VALUES (?,?)",
                    (datetime.now(UTC).isoformat(), value.model_dump_json()),
                )
        with mobile_db() as db:
            row = db.execute(
                "SELECT saved_at,payload FROM manual_inputs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "status": 200,
            "body": None if row is None else {"saved_at": row[0], "portfolio": json.loads(row[1])},
        }
    if path == "/api/v1/mobile/features" and method == "POST":
        try:
            return {"status": 200, "body": calculate(json.loads(body), bundled_selection())}
        except (ValueError, KeyError):
            return {
                "status": 422,
                "body": {"detail": "特徴量に必要な履歴・市場・財務データが不足または不整合です。"},
            }
    if path == "/api/v1/mobile/market" and method == "GET":
        return {"status": 200, "body": market.status(STATE / "mobile.sqlite3")}
    if path == "/api/v1/mobile/models" and method == "GET":
        return {"status": 200, "body": models.status(STATE / "mobile.sqlite3")}
    if path == "/api/v1/mobile/models/import" and method == "POST":
        try:
            return {
                "status": 200,
                "body": models.import_model(STATE / "mobile.sqlite3", json.loads(body)["content"]),
            }
        except (ValueError, KeyError):
            return {
                "status": 422,
                "body": {"detail": "モデルの採用・配布条件・PC/実機一致の証拠を確認できません。"},
            }
    if path == "/api/v1/mobile/models/parity" and method == "POST":
        try:
            value = json.loads(body)
            if len(value["rows"]) > 1000:
                raise ValueError("Parity input limit")
            return {
                "status": 200,
                "body": {
                    "values": predict(value["model"], value["rows"]),
                    "research_only": True,
                    "model_adopted": False,
                },
            }
        except (ValueError, KeyError, TypeError, IndexError):
            return {"status": 422, "body": {"detail": "推論の一致確認用データが不正です。"}}
    if path == "/api/v1/mobile/models/infer" and method == "POST":
        try:
            return {
                "status": 200,
                "body": models.infer(STATE / "mobile.sqlite3", datetime.now(UTC)),
            }
        except (ValueError, KeyError):
            return {
                "status": 422,
                "body": {
                    "detail": "採用モデル・最新データ・一致確認が不足し、予測を更新できません。"
                },
            }
    if path == "/api/v1/mobile/market/ingest" and method == "POST":
        try:
            return {
                "status": 200,
                "body": market.ingest(STATE / "mobile.sqlite3", json.loads(body)),
            }
        except (ValueError, KeyError):
            return {
                "status": 422,
                "body": {
                    "detail": "取得したデータが不完全または不整合です。前回の保存日を維持します。"
                },
            }
    if path == "/api/v1/mobile/features/latest" and method == "POST":
        try:
            inputs = market.feature_inputs(STATE / "mobile.sqlite3", datetime.now(UTC))
            return {"status": 200, "body": calculate(inputs, bundled_selection())}
        except (ValueError, KeyError):
            return {
                "status": 422,
                "body": {"detail": "特徴量に必要な営業日・価格・市場・財務履歴が不足しています。"},
            }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app), base_url="http://localhost"
    ) as client:
        response = await client.request(
            method,
            path,
            content=body if method == "POST" else None,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://localhost",
                "X-Stock-AI-Intent": "manual-record",
            },
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": "この端末ではJSON形式で書き出してください。"}
        return {"status": response.status_code, "body": payload}
