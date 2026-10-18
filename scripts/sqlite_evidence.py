"""Dependency-free typed SQLite evidence shared by native acceptance controllers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from contextlib import closing
from pathlib import Path


def table_snapshot(path: Path) -> dict:
    """Hash every ordered typed cell and user schema without loading whole tables."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        schema = db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        tables = {}
        for kind, name, _, _sql in schema:
            if kind != "table":
                continue
            identifier = '"' + name.replace('"', '""') + '"'
            info = db.execute(f"PRAGMA table_info({identifier})").fetchall()
            primary = sorted((column[5], column[1]) for column in info if column[5])
            keys = [column for _, column in primary] or [column[1] for column in info]
            ordering = ",".join('"' + column.replace('"', '""') + '"' for column in keys)
            value = hashlib.sha256()
            count = 0
            for row in db.execute(f"SELECT * FROM {identifier} ORDER BY {ordering}"):
                value.update(b"R")
                for cell in row:
                    if cell is None:
                        tag, content = b"N", b""
                    elif isinstance(cell, bytes):
                        tag, content = b"B", cell
                    elif isinstance(cell, str):
                        tag, content = b"S", cell.encode("utf-8")
                    elif isinstance(cell, int):
                        tag, content = b"I", str(cell).encode("ascii")
                    elif isinstance(cell, float):
                        tag, content = b"F", cell.hex().encode("ascii")
                    else:
                        raise ValueError("Unexpected SQLite cell type")
                    value.update(tag + struct.pack(">Q", len(content)))
                    value.update(content)
                count += 1
            tables[name] = {"rows": count, "typed_cells_sha256": value.hexdigest()}
    schema_digest = hashlib.sha256(json.dumps(schema, ensure_ascii=False).encode()).hexdigest()
    return {
        "schema_sha256": schema_digest,
        "tables": tables,
    }
