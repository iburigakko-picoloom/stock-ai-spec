"""Optional native, encrypted calculation cache. Never a published forecast."""

from __future__ import annotations

import base64
import json
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_context = None
_send = None
_read = None
_done = 0
_total = 0
_credits = set()
_started = 0.0
_phase = "preparing"


def configure(context=None, send=None, read=None):
    global _context, _send, _read, _done, _total, _credits, _started, _phase
    _context, _send, _read, _done, _total, _credits = context, send, read, 0, 0, set()
    _started, _phase = time.monotonic(), "preparing"


def enabled():
    return _context is not None and _send is not None


def execution_time(now):
    if not enabled():
        return now
    stamp = datetime.fromisoformat(_context["startedAt"])
    if stamp.tzinfo is None or stamp > now:
        raise ValueError("Invalid checkpoint execution time")
    return stamp


def _pack(value):
    if isinstance(value, pd.DataFrame):
        columns = []
        for name in value.columns:
            series = value[name]
            column = {"dtype": str(series.dtype)}
            if isinstance(series.dtype, pd.DatetimeTZDtype):
                zone = series.dtype.tz
                column["zone"] = (
                    {"kind": "zoneinfo", "name": str(zone)}
                    if isinstance(zone, ZoneInfo)
                    else {"kind": "fixed", "seconds": zone.utcoffset(None).total_seconds()}
                    if isinstance(zone, timezone)
                    else {"kind": "pytz", "name": str(zone)}
                )
                array = series.array.asi8
            else:
                array = series.to_numpy()
            if array.dtype.kind in "biufmM":
                column.update(
                    binary=base64.b64encode(array.tobytes()).decode("ascii"),
                    numpy_dtype=array.dtype.str,
                )
            else:
                column["values"] = [_pack(x) for x in series]
            columns.append(column)
        index = (
            {"range": [value.index.start, value.index.stop, value.index.step]}
            if isinstance(value.index, pd.RangeIndex)
            else {"values": [_pack(x) for x in value.index]}
        )
        return {
            "$frame": {
                "columns": list(value.columns),
                "data": columns,
                "index": index,
                "index_name": value.index.name,
                "duplicates": value.flags.allows_duplicate_labels,
            }
        }
    if value is pd.NaT:
        return {"$nat": True}
    if value is pd.NA:
        return {"$na": True}
    if isinstance(value, (pd.Timestamp, datetime)):
        return {"$time": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, np.generic):
        return _pack(value.item())
    if isinstance(value, float):
        return {"$float": value.hex()}
    if isinstance(value, dict):
        return {key: _pack(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_pack(item) for item in value]
    return value


def _unpack(value):
    if isinstance(value, list):
        return [_unpack(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"$float"}:
        return float.fromhex(value["$float"])
    if set(value) == {"$time"}:
        return pd.Timestamp(value["$time"])
    if set(value) == {"$date"}:
        return date.fromisoformat(value["$date"])
    if set(value) == {"$nat"}:
        return pd.NaT
    if set(value) == {"$na"}:
        return pd.NA
    if set(value) == {"$frame"}:
        frame = value["$frame"]
        columns = {}
        for name, column in zip(frame["columns"], frame["data"], strict=True):
            dtype = column["dtype"]
            values = (
                np.frombuffer(
                    base64.b64decode(column["binary"], validate=True), dtype=column["numpy_dtype"]
                ).copy()
                if "binary" in column
                else [_unpack(x) for x in column["values"]]
            )
            if "zone" in column:
                zone = column["zone"]
                tz = (
                    ZoneInfo(zone["name"])
                    if zone["kind"] == "zoneinfo"
                    else timezone(timedelta(seconds=zone["seconds"]))
                    if zone["kind"] == "fixed"
                    else zone["name"]
                )
                dtype = pd.DatetimeTZDtype(unit=pd.api.types.pandas_dtype(dtype).unit, tz=tz)
                values = pd.to_datetime(values, unit=dtype.unit, utc=True).tz_convert(tz)
            columns[name] = pd.Series(values, dtype=dtype)
        result = pd.DataFrame(columns)
        index = frame["index"]
        result.index = (
            pd.RangeIndex(*index["range"], name=frame["index_name"])
            if "range" in index
            else pd.Index([_unpack(x) for x in index["values"]], name=frame["index_name"])
        )
        return result.set_flags(allows_duplicate_labels=frame["duplicates"])
    return {key: _unpack(item) for key, item in value.items()}


def encode(value):
    raw = json.dumps(
        _pack(value), ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    if len(raw) > 256 * 1024 * 1024:
        raise ValueError("Checkpoint size limit")
    return base64.b64encode(zlib.compress(raw, 1)).decode("ascii")


def decode(value):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(base64.b64decode(value, validate=True), 256 * 1024 * 1024 + 1)
    if len(raw) > 256 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError("Invalid checkpoint")
    return _unpack(json.loads(raw))


def plan(total, phase="features"):
    global _total, _phase
    _total, _phase = total, phase
    if enabled():
        _send(
            json.dumps(
                {"key": "", "data": None, "done": _done, "total": total, "phase": phase}
            )
        )


def cached(key, compute, *, units=0, phase="preparing", credit=None):
    global _done
    if not enabled():
        return compute()
    if phase != _phase:
        plan(_total, phase)
    records = _context["records"]
    data = None
    if key in records:
        result = decode(records[key] if records[key] is not None else _read(key))
    else:
        result = compute()
        data = encode(result)
    identity = credit or key
    if identity not in _credits:
        _done += units
        _credits.add(identity)
    _send(json.dumps({"key": key, "data": data, "done": _done, "total": _total, "phase": phase}))
    # Only yield after newly completed work was sent to the durable owner.
    # Cache hits cannot repeatedly consume the budget without making progress.
    budget = _context.get("budgetSeconds")
    if data is not None and budget is not None and time.monotonic() - _started >= budget:
        raise CheckpointPause("Continue from saved units")
    return result


class CheckpointPause(RuntimeError):
    """Internal continuation signal, never an invalid market/model error."""


def stage(phase):
    if enabled():
        plan(_total, phase)


def feature_batch(symbols, compute):
    from stock_ai.operations.daily import content_id

    return cached("features-" + content_id(symbols), compute, units=len(symbols), phase="features")


def preparation_complete(units):
    """A complete prepared input also covers work skipped by its validated cache."""
    global _done
    _done = units
    if enabled():
        for key in list(_context["records"]):
            if key.startswith("source-"):
                del _context["records"][key]
        plan(_total, "features")


def source_part(identity, credit, compute):
    if not enabled():
        return compute()
    from stock_ai.operations.daily import content_id

    return cached("source-" + content_id(identity), compute, units=1, credit=credit)
