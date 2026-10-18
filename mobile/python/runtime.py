"""Offline mobile adapter around the unchanged PC ledger/API and calculation code."""

from __future__ import annotations

import base64
import inspect
import io
import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi.routing import APIRoute, request_response

from stock_ai.operations.api import create_app
from stock_ai.operations.manual_portfolio import ManualPortfolio, strict_json
from stock_ai.operations.manual_settings import ManualPersonalSettings
from stock_ai.operations.store import OperationalConflictError

from . import (
    decisions,
    forecasts,
    manual_chatgpt,
    market,
    membership,
    models,
    personal,
    research,
    universe,
)
from .features import bundled_selection, calculate
from .model_bundle import parity as bundle_parity
from .portable_model import predict
from .storage import connect

STATE = Path("/stockai-state")
MAX_DATABASE_BYTES = 256 * 1024 * 1024
_app = None


def _async_call(fn):
    async def invoke(**kwargs):
        return fn(**kwargs)

    return invoke


def _restore_archive(archive: zipfile.ZipFile) -> None:
    names = archive.namelist()
    if set(names) - {"operations.sqlite3", "mobile.sqlite3"} or len(names) != len(set(names)):
        raise ValueError("Unexpected backup file")
    # Validate both snapshots on disk before replacing either current database.
    with tempfile.TemporaryDirectory(prefix="state-import-", dir=STATE) as folder:
        staged = Path(folder)
        for name in names:
            info = archive.getinfo(name)
            if info.file_size > MAX_DATABASE_BYTES:
                raise ValueError("Backup exceeds mobile storage limit")
            target = staged / name
            length = 0
            with archive.open(name) as source, target.open("wb") as output:
                while chunk := source.read(64 * 1024):
                    length += len(chunk)
                    if length > MAX_DATABASE_BYTES:
                        raise ValueError("Backup exceeds mobile storage limit")
                    output.write(chunk)
            with target.open("rb") as content:
                if content.read(16) != b"SQLite format 3\x00":
                    raise ValueError("Invalid SQLite backup")
            uri = target.resolve().as_uri() + "?mode=ro&immutable=1"
            with closing(sqlite3.connect(uri, uri=True)) as probe:
                if probe.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Invalid SQLite integrity")
        for name in names:
            (staged / name).replace(STATE / name)


class StateImport:
    """Decode native fragments into one temporary ZIP without a full Python string."""

    def __init__(self, length: int):
        if type(length) is not int or not 0 <= length <= 128 * 1024 * 1024 or length % 4:
            raise ValueError("Invalid native state length")
        self.length = length
        self._received = 0
        self._index = 0
        self._closed = False
        self._archive = tempfile.TemporaryFile()

    def append(self, index: int, fragment: str) -> None:
        try:
            remaining = self.length - self._received
            if (self._closed or type(index) is not int or index != self._index
                    or not isinstance(fragment, str) or not remaining
                    or len(fragment) != min(256 * 1024, remaining)
                    or ("=" in fragment and len(fragment) != remaining)):
                raise ValueError("Invalid native state fragment")
            self._archive.write(base64.b64decode(fragment, validate=True))
            self._received += len(fragment)
            self._index += 1
        except BaseException:
            self.close()
            raise

    def finish(self) -> dict:
        try:
            if self._closed or self._received != self.length:
                raise ValueError("Incomplete native state")
            STATE.mkdir(exist_ok=True)
            if self.length:
                self._archive.seek(0)
                with zipfile.ZipFile(self._archive) as archive:
                    _restore_archive(archive)
            return initialize()
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._archive.close()


def initialize(encoded: str = "") -> dict:
    global _app
    STATE.mkdir(exist_ok=True)
    if encoded:
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded, validate=True))) as archive:
            _restore_archive(archive)
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
    membership.initialize(STATE / "mobile.sqlite3")
    models.initialize(STATE / "mobile.sqlite3")
    forecasts.initialize(STATE / "mobile.sqlite3")
    forecasts.reconcile_publications(STATE / "mobile.sqlite3", _app.state.store)
    personal.initialize(_app.state.store, STATE / "mobile.sqlite3", datetime.now(UTC))
    decisions.initialize(STATE / "mobile.sqlite3")
    decisions.reconcile(STATE / "mobile.sqlite3", _app.state.store)
    _app.state.store.verify_integrity()
    return {"research_only": True, "order_submission": False}


def mobile_db():
    return connect(STATE / "mobile.sqlite3")


class _BoundedArchive(io.BytesIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit

    def write(self, content):
        if self.tell() + len(content) > self.limit:
            raise ValueError("State exceeds native transfer limit")
        return super().write(content)


def _export_archive(limit: int | None = None) -> io.BytesIO:
    market.compact_legacy(STATE / "mobile.sqlite3")
    output = io.BytesIO() if limit is None else _BoundedArchive(limit)
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("operations.sqlite3", "mobile.sqlite3"):
                backup_path = STATE / "export.sqlite3"
                try:
                    with closing(sqlite3.connect(STATE / name)) as connection:
                        with closing(sqlite3.connect(backup_path)) as target:
                            connection.backup(target)
                            target.execute("PRAGMA journal_mode=DELETE")
                    if backup_path.stat().st_size > MAX_DATABASE_BYTES:
                        raise ValueError("Backup exceeds mobile storage limit")
                    # ZIP streams the SQLite snapshot; no full read_bytes copy.
                    archive.write(backup_path, arcname=name)
                finally:
                    backup_path.unlink(missing_ok=True)
        return output
    except BaseException:
        output.close()
        raise


def export_state() -> str:
    # The direct/desktop interface keeps its existing complete-string result.
    with _export_archive() as output:
        return base64.b64encode(output.getvalue()).decode("ascii")


_MAX_NATIVE_STATE_CHARACTERS = 128 * 1024 * 1024
_STATE_CHUNK_CHARACTERS = 256 * 1024


class StateExport:
    """Native-only base64 stream, with one archive and bounded encoded fragments."""

    def __init__(self):
        self._archive = _export_archive(_MAX_NATIVE_STATE_CHARACTERS // 4 * 3)
        self._view = self._archive.getbuffer()
        self.length = (len(self._view) + 2) // 3 * 4
        self._offset = 0
        self._closed = False

    def read_next(self) -> str | None:
        if self._closed:
            return None
        if self._offset == len(self._view):
            self.close()
            return None
        end = min(self._offset + _STATE_CHUNK_CHARACTERS // 4 * 3, len(self._view))
        fragment = base64.b64encode(self._view[self._offset:end]).decode("ascii")
        self._offset = end
        return fragment

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._view.release()
            self._archive.close()


async def request(method: str, path: str, body: str = "null") -> dict:
    if _app is None:
        raise RuntimeError("Runtime not initialized")
    if method not in {"GET", "POST"} or not path.startswith("/api/v1/") or "://" in path:
        return {"status": 400, "body": {"detail": "Unsupported local operation"}}
    if path == "/api/v1/mobile/portfolio":
        if method == "POST":
            try:
                incoming = strict_json(body)
                # Legacy raw writes are accepted only for the first input. New
                # clients always submit an expected revision and cannot overwrite
                # a newer draft from a stale screen.
                if isinstance(incoming, dict) and set(incoming) == {
                    "expected_revision_id", "portfolio"
                }:
                    expected = incoming["expected_revision_id"]
                    value = ManualPortfolio.model_validate(incoming["portfolio"])
                else:
                    expected = None
                    value = ManualPortfolio.model_validate(incoming)
                personal.save_portfolio(_app.state.store, value, expected, datetime.now(UTC))
            except OperationalConflictError as error:
                return {"status": 409, "body": {"detail": str(error)}}
            except ValueError:
                return {"status": 422, "body": {"detail": "口座・保有の入力を確認してください。"}}
        return {"status": 200, "body": personal.portfolio_view(_app.state.store)}
    if path.startswith("/api/v1/mobile/personal/"):
        store = _app.state.store
        now = datetime.now(UTC)
        try:
            if path == "/api/v1/mobile/personal/settings":
                if method == "POST":
                    incoming = strict_json(body)
                    if not isinstance(incoming, dict) or set(incoming) != {
                        "expected_revision_id", "settings"
                    }:
                        raise ValueError("Invalid settings envelope")
                    value = ManualPersonalSettings.model_validate(incoming["settings"])
                    return {"status": 200, "body": personal.save_settings(
                        store, value, incoming["expected_revision_id"], now,
                    )}
                return {"status": 200, "body": personal.settings_view(store)}
            if path == "/api/v1/mobile/personal/readiness" and method == "GET":
                return {"status": 200, "body": personal.readiness(
                    store, STATE / "mobile.sqlite3", now,
                )}
            if path == "/api/v1/mobile/personal/initial/preview" and method == "POST":
                return {"status": 200, "body": personal.preview_initial(
                    store, STATE / "mobile.sqlite3", now, persist=True,
                )}
            if path == "/api/v1/mobile/personal/initial/confirm" and method == "POST":
                incoming = strict_json(body)
                if not isinstance(incoming, dict) or set(incoming) != {"preview_id", "confirmed"}:
                    raise ValueError("Invalid confirmation envelope")
                return {"status": 200, "body": personal.confirm_initial(
                    store, STATE / "mobile.sqlite3", incoming["preview_id"],
                    incoming["confirmed"], now,
                )}
        except OperationalConflictError as error:
            return {"status": 409, "body": {"detail": str(error)}}
        except (ValueError, KeyError, TypeError):
            return {"status": 422, "body": {
                "detail": "補足設定・未入力項目・口座との対応を確認してください。"
            }}
    if path == "/api/v1/mobile/features" and method == "POST":
        try:
            return {"status": 200, "body": calculate(json.loads(body), bundled_selection())}
        except (ValueError, KeyError):
            return {
                "status": 422,
                "body": {"detail": "特徴量に必要な履歴・市場・財務データが不足または不整合です。"},
            }
    if path == "/api/v1/mobile/market/membership":
        try:
            now = datetime.now(UTC)
            result = (membership.ingest(STATE / "mobile.sqlite3", json.loads(body), now)
                      if method == "POST" else membership.status(STATE / "mobile.sqlite3", now))
            return {"status": 200, "body": result}
        except (ValueError, KeyError, TypeError, StopIteration):
            return {"status": 422, "body": {
                "detail": "当日の銘柄一覧・カレンダー・受領時刻を確認できません。"
            }}
    if path == "/api/v1/mobile/market/plan":
        try:
            return {"status": 200, "body": market.plan(
                STATE / "mobile.sqlite3", json.loads(body) if method == "POST" else None
            )}
        except (ValueError, KeyError, TypeError):
            return {"status": 422, "body": {
                "detail": "取得範囲は昨日までの最大2年分で指定してください。"
            }}
    if method == "GET" and path in (
        "/api/v1/mobile/market/universe", "/api/v1/mobile/market/current-universe"
    ):
        ledger = _app.state.store.latest_portfolio()
        profile = personal.portfolio_view(_app.state.store)
        held = ([item.symbol for item in ledger.positions] if ledger is not None else
                [item["symbol"] for item in profile["portfolio"]["holdings"]] if profile else [])
        try:
            # The displayed preview observes the same closed alpha boundary.
            now = datetime.now(UTC)
            cutoff = now.astimezone(ZoneInfo("Asia/Tokyo")).replace(
                hour=11, minute=30, second=0, microsecond=0
            )
            selected = universe.select(
                STATE / "mobile.sqlite3", min(now, cutoff), held,
                current_membership=path.endswith("/current-universe"),
            )
            selected["holdings_recorded"] = ledger is not None or bool(
                profile and profile["portfolio"]["holdings_status"] != "unrecorded"
            )
            return {"status": 200, "body": selected}
        except (ValueError, KeyError, TypeError):
            return {"status": 422, "body": {
                "detail": "対象抽出の受領記録または市場データを確認できません。"
            }}
    if path == "/api/v1/mobile/market" and method == "GET":
        return {"status": 200, "body": market.status(STATE / "mobile.sqlite3")}
    if path.startswith("/api/v1/mobile/chatgpt-manual/"):
        try:
            store, now = _app.state.store, datetime.now(UTC)
            local_path = STATE / "mobile.sqlite3"
            if path == "/api/v1/mobile/chatgpt-manual/status" and method == "GET":
                result = manual_chatgpt.status(local_path, store, now)
            elif path == "/api/v1/mobile/chatgpt-manual/export" and method == "POST":
                result = manual_chatgpt.export(local_path, store, json.loads(body), now)
            elif path == "/api/v1/mobile/chatgpt-manual/answer" and method == "POST":
                result = manual_chatgpt.import_answer(local_path, store, json.loads(body), now)
            else:
                raise ValueError("手動ChatGPTの操作を確認してください")
            return {"status": 200, "body": result}
        except (ValueError, KeyError, TypeError) as error:
            # Errors are our fixed explanations or schema errors, never raw JSON
            # or validation's reflected account / answer input.
            detail = (
                str(error)
                if type(error) is ValueError
                else "回答JSON・利用条件・最新snapshotを確認してください"
            )
            return {"status": 422, "body": {"detail": detail}}
    if path == "/api/v1/mobile/research/plan" and method == "GET":
        try:
            return {"status": 200, "body": research.plan(
                STATE / "mobile.sqlite3", _app.state.store, datetime.now(UTC)
            )}
        except (ValueError, KeyError, TypeError):
            return {"status": 422, "body": {"detail": "当日の数値・株数の保存を確認できません。"}}
    if path == "/api/v1/mobile/models" and method == "GET":
        return {"status": 200, "body": models.status(STATE / "mobile.sqlite3", _app.state.store)}
    if path == "/api/v1/mobile/daily" and method == "GET":
        return {"status": 200, "body": forecasts.latest(STATE / "mobile.sqlite3")}
    if path == "/api/v1/mobile/decision" and method == "GET":
        return {"status": 200, "body": decisions.view(STATE / "mobile.sqlite3", _app.state.store)}
    if path == "/api/v1/mobile/decision/generate" and method == "POST":
        try:
            now = datetime.now(UTC)
            decisions.generate(
                STATE / "mobile.sqlite3", _app.state.store, now,
            )
            return {"status": 200, "body": decisions.view(
                STATE / "mobile.sqlite3", _app.state.store,
            )}
        except OperationalConflictError:
            return {"status": 409, "body": {
                "detail": "本人入力が更新されています。保存済み状態から再計算してください。"
            }}
        except (ValueError, KeyError, TypeError):
            return {"status": 422, "body": {
                "detail": "原予測・市場情報・本人設定の整合を確認できず、株数提案を保存できません。"
            }}
    if path == "/api/v1/mobile/daily/generate" and method == "POST":
        try:
            return {"status": 200, "body": forecasts.generate(
                STATE / "mobile.sqlite3", _app.state.store, datetime.now(UTC)
            )}
        except OperationalConflictError:
            return {"status": 409, "body": {
                "detail": "口座・保有が更新されています。保存済みの状態を読み直してください。"
            }}
        except (ValueError, KeyError, TypeError):
            return {"status": 422, "body": {
                "detail": "履歴・当日一覧・校正情報・保有の整合を確認できず、予測を更新できません。"
            }}
    if path == "/api/v1/mobile/models/import" and method == "POST":
        try:
            return {
                "status": 200,
                "body": models.import_bundle(
                    STATE / "mobile.sqlite3", json.loads(body)["content"], datetime.now(UTC)
                ),
            }
        except (ValueError, KeyError, TypeError):
            return {
                "status": 422,
                "body": {"detail": "モデルの採用・配布条件・PC/実機一致の証拠を確認できません。"},
            }
    if path == "/api/v1/mobile/models/bundle/parity" and method == "POST":
        try:
            value = strict_json(body)
            return {"status": 200, "body": bundle_parity(
                value["content"], value["rows"], bundled_selection(),
            )}
        except (ValueError, KeyError, TypeError, IndexError):
            return {"status": 422, "body": {"detail": "モデル一式の一致確認用データが不正です。"}}
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
        except (ValueError, KeyError, TypeError):
            return {
                "status": 422,
                "body": {
                    "detail": "取得したデータが不完全または不整合です。前回の保存日を維持します。"
                },
            }
    if path == "/api/v1/mobile/features/latest" and method == "POST":
        try:
            inputs = market.feature_inputs(STATE / "mobile.sqlite3", datetime.now(UTC), True)
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
        if path == "/api/v1/home" and response.status_code == 200:
            payload["initialLedger"] = personal.initial_reference(_app.state.store)
        return {"status": response.status_code, "body": payload}
