"""Lossless shared columns for immutable market batches, with legacy decoding.

Normalized JSON is compacted only when its exact original bytes can be rebuilt.
Record hashes are derived from retained raw records using the frozen v1 hash.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zlib
from itertools import pairwise
from json.encoder import encode_basestring_ascii
from operator import add
from typing import NamedTuple

import pandas as pd
from pandas._libs.json import ujson_loads
from pandas.io.json._table_schema import convert_json_field_to_pandas_type

from stock_ai.data.normalize import record_hash_v1

PREFIX = b"stockai-columns-v1\n"
MAX_BLOCK = 128 * 1024 * 1024


class Number(str):
    """Retain the original Pandas JSON numeric spelling, including exponents."""


class _VerifiedColumn(NamedTuple):
    compressed: bytes
    tokens: tuple[str, ...]
    utf8_bytes: int


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS market_columns("
               "digest TEXT PRIMARY KEY,payload BLOB NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS market_compaction("
               "id INTEGER PRIMARY KEY CHECK(id=1),sequence INTEGER NOT NULL,"
               "valuation_sequence INTEGER NOT NULL)")


def _inflate(payload, limit=MAX_BLOCK):
    decoder = zlib.decompressobj()
    value = decoder.decompress(payload, limit + 1)
    if len(value) > limit or not decoder.eof or decoder.unused_data:
        raise ValueError("Invalid/oversized market block")
    return value


def _token(value):
    if isinstance(value, Number):
        return str(value)
    if type(value) is str:
        return encode_basestring_ascii(value).replace("/", "\\/")
    if value is None or type(value) in (bool, int, float):
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    raise TypeError("Nested provider values retain legacy storage")


def _column(db, values):
    if values and all(item == values[0] for item in values):
        return {"constant": values[0]}
    data = json.dumps(values, separators=(",", ":")).encode()
    if len(data) > MAX_BLOCK:
        raise ValueError("Market column exceeds storage limit")
    digest = hashlib.sha256(data).hexdigest()
    compressed = zlib.compress(data)
    inserted = db.execute("INSERT OR IGNORE INTO market_columns VALUES(?,?)", (digest, compressed))
    if inserted.rowcount == 0:
        stored = db.execute("SELECT payload FROM market_columns WHERE digest=?",
                            (digest,)).fetchone()
        if stored is None or (stored[0] != compressed and _inflate(stored[0]) != data):
            raise ValueError("Market column changed")
    return {"ref": digest}


def _document(kind, rows, columns, **other):
    encoded = json.dumps(
        {"kind": kind, "rows": rows, "columns": columns, **other},
        separators=(",", ":"), allow_nan=False,
    ).encode()
    if len(encoded) > MAX_BLOCK:
        raise ValueError("Market descriptor exceeds storage limit")
    return PREFIX + zlib.compress(encoded)


def pack_records(db, records):
    records = list(records)
    if len(records) > 50000:
        raise ValueError("Market batch row limit")
    fields = list(dict.fromkeys(key for row in records for key in row))
    prepared = []
    try:
        for field in fields:
            present = [index for index, row in enumerate(records) if field in row]
            values = [_token(records[index][field]) for index in present]
            prepared.append((field, present, values))
    except TypeError:
        return zlib.compress(json.dumps(records, allow_nan=False).encode())
    columns = []
    for field, present, values in prepared:
        column = {"name": field, **_column(db, values)}
        if len(present) != len(records):
            column["present"] = present
        columns.append(column)
    return _document("records", len(records), columns)


def _table(schema, names, values, count):
    keys = [encode_basestring_ascii(name) + ":" for name in names]
    if (keys and type(count) is int and type(values) in (list, tuple)
            and len(keys) == len(values)
            and all(type(column) in (list, tuple) and len(column) == count for column in values)):
        rows = ("{" + ",".join(map(add, keys, row)) + "}"
                for row in zip(*values, strict=True))
    else:
        # Preserve the existing empty-column, requested-count and error semantics.
        rows = (
            "{" + ",".join(key + column[index]
                           for key, column in zip(keys, values, strict=True)) + "}"
            for index in range(count)
        )
    return ('{"schema":' + schema + ',"data":[' + ",".join(rows) + "]}").encode()


def pack_table(db, original, raw):
    text = original.decode()
    if not text.startswith('{"schema":'):
        return zlib.compress(original)
    _, end = json.JSONDecoder().raw_decode(text, len('{"schema":'))
    schema = text[len('{"schema":'):end]
    document = json.loads(text, parse_int=Number, parse_float=Number)
    rows = document["data"]
    fields = list(rows[0]) if rows else [field["name"] for field in document["schema"]["fields"]]
    if any(list(row) != fields for row in rows):
        return zlib.compress(original)
    values = [[_token(row[field]) for row in rows] for field in fields]
    if _table(schema, fields, values, len(rows)) != original:
        return zlib.compress(original)
    raw_hashes = [_token(record_hash_v1(row)) for row in raw]
    columns = []
    for field, items in zip(fields, values, strict=True):
        if field == "source_record_hash" and items == raw_hashes:
            columns.append({"name": field, "raw_hashes": True})
        else:
            columns.append({"name": field, **_column(db, items)})
    return _document("table", len(rows), columns, schema=schema)


def _read(db, payload, kind, raw=None, *, profile_only=False, cache=None, raw_hashes=None):
    document = json.loads(_inflate(payload[len(PREFIX):]))
    expected = {"kind", "rows", "columns"}
    if kind == "table":
        expected.add("schema")
    if (not isinstance(document, dict)
            or set(document) != expected
            or (kind == "table" and not isinstance(document["schema"], str))):
        raise ValueError("Invalid market column document")
    count = document["rows"]
    columns = document["columns"]
    if document["kind"] != kind or type(count) is not int or not 0 <= count <= 50000:
        raise ValueError("Invalid market column document")
    if not isinstance(columns, list):
        raise ValueError("Invalid market columns")
    names, values, presence, references, seen = [], [], [], {}, set()
    expanded = len(document.get("schema", "")) + 2 * count
    limit = MAX_BLOCK if kind == "table" else 64 * 1024 * 1024
    for column in columns:
        known_strings = False
        name = column["name"]
        if not isinstance(name, str) or name in seen:
            raise ValueError("Invalid market column name")
        indexes = column.get("present")
        if indexes is not None and (
            kind != "records" or not isinstance(indexes, list)
            or any(type(item) is not int or not 0 <= item < count for item in indexes)
            or any(left >= right for left, right in pairwise(indexes))
        ):
            raise ValueError("Invalid market column presence")
        length = count if indexes is None else len(indexes)
        tags = set(column) - {"name", "present"}
        if tags == {"constant"}:
            if type(column["constant"]) is not str:
                raise ValueError("Invalid market constant")
            expanded += len(column["constant"].encode()) * length
            if expanded > limit:
                raise ValueError("Expanded market records exceed storage limit")
            items = [column["constant"]] * length
            known_strings = True
        elif (tags == {"raw_hashes"} and kind == "table" and name == "source_record_hash"
              and column["raw_hashes"] is True):
            if profile_only:
                # Only dtype/all-null evidence; full hash verification follows
                # in frame() in the caller's same SQLite snapshot.
                items = [_token("0" * 64)] * count
            elif raw_hashes is not None:
                if len(raw_hashes) != count:
                    raise ValueError("Raw market records missing")
                items = [_token(value) for value in raw_hashes]
            else:
                if raw is None or len(raw) != count:
                    raise ValueError("Raw market records missing")
                items = [_token(record_hash_v1(row)) for row in raw]
            expanded += sum(len(item) for item in items)
        elif tags == {"ref"}:
            digest = column["ref"]
            if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
                raise ValueError("Invalid market column reference")
            if digest not in references:
                stored = db.execute("SELECT payload FROM market_columns WHERE digest=?",
                                    (digest,)).fetchone()
                if stored is None:
                    raise ValueError("Market column missing")
                key = ("tokens", digest)
                verified = cache.get(key) if cache is not None else None
                # Read the DB bytes every time, including cache hits. A changed
                # or removed column cannot hide behind a previous valid read.
                if isinstance(verified, _VerifiedColumn) and verified.compressed == stored[0]:
                    cache.move_to_end(key)
                else:
                    encoded = _inflate(stored[0])
                    if hashlib.sha256(encoded).hexdigest() != digest:
                        raise ValueError("Market column changed")
                    verified = json.loads(encoded)
                    if isinstance(verified, list) and all(type(item) is str for item in verified):
                        verified = _VerifiedColumn(
                            stored[0], tuple(verified), sum(len(item.encode()) for item in verified)
                        )
                        if cache is not None:
                            cache[key] = verified
                            cache.move_to_end(key)
                            if len(cache) > 128:
                                cache.popitem(last=False)
                references[digest] = verified
            verified = references[digest]
            if isinstance(verified, _VerifiedColumn):
                items = verified.tokens
                expanded += verified.utf8_bytes
                known_strings = True
            else:
                items = verified
        else:
            raise ValueError("Invalid market column encoding")
        if ((not known_strings and not isinstance(items, list)) or len(items) != length
                or (not known_strings and any(type(item) is not str for item in items))):
            raise ValueError("Invalid market column length/value")
        expanded += (len(encode_basestring_ascii(name)) + 2) * length
        if expanded > limit:
            raise ValueError("Expanded market records exceed storage limit")
        seen.add(name)
        names.append(name)
        values.append(items)
        presence.append(indexes)
    return document, names, values, presence


def records(db, payload, *, cache=None):
    if not payload.startswith(PREFIX):
        result = json.loads(_inflate(payload, 64 * 1024 * 1024))
        if not isinstance(result, list):
            raise ValueError("Invalid legacy market records")
        return result
    document, names, values, presence = _read(db, payload, "records", cache=cache)
    if all(indexes is None for indexes in presence):
        # One JSON parse avoids a separate parser call for every scalar cell.
        wrapped = _table("{}", names, values, document["rows"])
        return json.loads(wrapped)["data"]
    result = [{} for _ in range(document["rows"])]
    for name, items, indexes in zip(names, values, presence, strict=True):
        targets = range(len(result)) if indexes is None else indexes
        for index, item in zip(targets, items, strict=True):
            result[index][name] = json.loads(item)
    return result


def table(db, payload, raw, expected):
    if not payload.startswith(PREFIX):
        decoded = _inflate(payload, 128 * 1024 * 1024)
    else:
        source = records(db, raw)
        document, names, values, _ = _read(db, payload, "table", source)
        decoded = _table(document["schema"], names, values, document["rows"])
    if hashlib.sha256(decoded).hexdigest() != expected:
        raise ValueError("Stored normalized data changed")
    return decoded


def _raw_record_hashes(db, payload, cache):
    """The frozen v1 raw identity without a dict/JSON roundtrip for every row."""
    if not payload.startswith(PREFIX):
        return [record_hash_v1(row) for row in records(db, payload, cache=cache)]
    document, names, values, presence = _read(db, payload, "records", cache=cache)
    if any(indexes is not None for indexes in presence) or len(set(names)) != len(names):
        return [record_hash_v1(row) for row in records(db, payload, cache=cache)]
    if not names:
        return [hashlib.sha256(b"{}").hexdigest()] * document["rows"]

    keys, columns = [], []
    for index in sorted(range(len(names)), key=names.__getitem__):
        keys.append(json.dumps(names[index], ensure_ascii=False) + ":")
        canonical = {}
        for token in values[index]:
            if token not in canonical:
                # A valid quoted string with no escape is already canonical v1.
                canonical[token] = (token if re.fullmatch(r'"[^"\\\x00-\x1f]*"', token) else
                    json.dumps(json.loads(token), ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False))
        columns.append([canonical[token] for token in values[index]])
    return [hashlib.sha256(("{" + ",".join(map(add, keys, row)) + "}").encode()).hexdigest()
            for row in zip(*columns, strict=True)]


def frame(db, payload, raw, expected, cache):
    """Use Pandas' own scalar parser/schema conversion with shared columns.

    Verify the exact frozen row JSON before materializing its columns. Constant
    strings are parsed once, and immutable reference columns share decoded
    values within this one PIT read. Values, types and indexes match read_json.
    """
    if not payload.startswith(PREFIX):
        return pd.read_json(io.BytesIO(table(db, payload, raw, expected)), orient="table")
    hashes = _raw_record_hashes(db, raw, cache)
    document, names, values, _ = _read(db, payload, "table", cache=cache, raw_hashes=hashes)
    decoded = _table(document["schema"], names, values, document["rows"])
    if hashlib.sha256(decoded).hexdigest() != expected:
        raise ValueError("Stored normalized data changed")
    if document["rows"] == 0:
        # Pandas infers an empty row table differently from a dict of empty
        # columns. Keep its exact empty-schema semantics across pinned runtimes.
        return pd.read_json(io.BytesIO(decoded), orient="table")
    schema = ujson_loads(document["schema"], precise_float=False)
    columns = {}
    for spec, name, items in zip(document["columns"], names, values, strict=True):
        key = spec.get("ref")
        if key is not None and key in cache:
            cache.move_to_end(key)
            columns[name] = cache[key]
        elif "constant" in spec:
            columns[name] = [ujson_loads(spec["constant"], precise_float=False)] * document["rows"]
        else:
            columns[name] = ujson_loads("[" + ",".join(items) + "]", precise_float=False)
            if key is not None:
                cache[key] = columns[name]
                if len(cache) > 128:
                    cache.popitem(last=False)
    order = [field["name"] for field in schema["fields"]]
    dtypes = {field["name"]: convert_json_field_to_pandas_type(field) for field in schema["fields"]}
    # These are the same casts/index operations as Pandas' table-schema reader.
    result = pd.DataFrame(columns, columns=order).astype(dtypes)
    if "primaryKey" in schema:
        result = result.set_index(schema["primaryKey"])
        result.index.names = [
            None if (name == "index" and len(result.index.names) == 1)
            or (isinstance(name, str) and name.startswith("level_") and len(result.index.names) > 1)
            else name for name in result.index.names
        ]
    return result


def frame_profile(frame):
    """Preserve dtype/all-null concat evidence without retaining a source batch."""
    if frame.empty:
        return frame
    profile = frame.iloc[:1].copy()
    missing = profile.isna().iloc[0]
    for name in missing[missing].index:
        column = frame[name]
        present = column.notna().to_numpy()
        if present.any():
            profile[name] = column.iloc[[int(present.argmax())]].array
    return profile.reset_index(drop=True)


def dtype_profile(db, payload, raw, expected, cache):
    """Provisional dtype evidence; callers must fully verify every batch after it.

    Compact profiles avoid reconstructing raw row hashes twice. They never
    supply source values or identities. FeatureSource always calls frame() for
    every selected batch in a second pass of the same SQLite transaction.
    Legacy and empty tables use the full verified reader here as well.
    """
    if not payload.startswith(PREFIX):
        return frame_profile(frame(db, payload, raw, expected, cache))
    document, names, values, _ = _read(db, payload, "table", profile_only=True, cache=cache)
    if document["rows"] == 0:
        return frame_profile(frame(db, payload, raw, expected, cache))
    schema = ujson_loads(document["schema"], precise_float=False)
    order = [field["name"] for field in schema["fields"]]
    dtypes = {field["name"]: convert_json_field_to_pandas_type(field) for field in schema["fields"]}
    tokens = {name: next((item for item in items if item != "null"), "null")
              for name, items in zip(names, values, strict=True)}
    columns = {name: [ujson_loads(token, precise_float=False)] for name, token in tokens.items()}
    result = pd.DataFrame(columns, columns=order).astype(dtypes)
    # A legacy numeric/date spelling such as a quoted NaN/NaT can become null
    # only after the schema cast. Find non-null evidence with that same cast.
    for name, items in zip(names, values, strict=True):
        if tokens[name] == "null" or not result[name].isna().all():
            continue
        seen = {"null", tokens[name]}
        for token in items:
            if token in seen:
                continue
            seen.add(token)
            candidate = pd.Series([ujson_loads(token, precise_float=False)]).astype(dtypes[name])
            if not candidate.isna().all():
                result[name] = candidate.array
                break
    if "primaryKey" in schema:
        result = result.set_index(schema["primaryKey"])
    return result.reset_index(drop=True)
