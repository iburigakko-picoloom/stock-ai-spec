"""Bound local SQLite transactions to deterministic connection lifetimes."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager


@contextmanager
def connect(path):
    connection = sqlite3.connect(path)
    try:
        # sqlite3.Connection.__exit__ commits/rolls back but does not close.
        # A retained connection can keep WAL handles alive across state restore.
        with connection:
            yield connection
    finally:
        connection.close()
