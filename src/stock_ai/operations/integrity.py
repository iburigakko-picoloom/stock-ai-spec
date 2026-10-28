"""Reuse a full integrity proof only while SQLite and its files are unchanged."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock

from stock_ai.operations.store import (
    OperationalIntegrityError,
    OperationalStorageBusyError,
    OperationalStore,
)


class IntegrityGuard:
    """One read-only observer per API instance; no TTL or trusted mutation counter.

    data_version is compared on the SAME connection, including external commits.
    File identity/timestamps additionally invalidate replacement and file edits.
    All writes and record-level hash/relationship checks remain authoritative.
    """

    def __init__(self, store: OperationalStore) -> None:
        self.store = store
        self._lock = RLock()
        self._observer: sqlite3.Connection | None = None
        self._proof: tuple[object, ...] | None = None
        self._counts: dict[str, int] = {}

    def _files(self) -> tuple[object, ...]:
        stamps: list[object] = []
        for path in (self.store.path, Path(f"{self.store.path}-wal")):
            try:
                stat = path.stat()
                # SQLite fchmod()s WAL on ordinary connection opens, changing
                # ctime without changing data. data_version plus WAL mtime and
                # size observe commits; the base file also retains ctime.
                stamps.append((stat.st_dev, stat.st_ino, stat.st_size,
                               stat.st_mtime_ns,
                               stat.st_ctime_ns if path == self.store.path else None))
            except FileNotFoundError:
                stamps.append(None)
        return tuple(stamps)

    def _token(self) -> tuple[object, ...]:
        assert self._observer is not None
        return (self._observer.execute("PRAGMA data_version").fetchone()[0], *self._files())

    def close(self) -> None:
        with self._lock:
            if self._observer is not None:
                self._observer.close()
                self._observer = None
            self._proof = None
            self._counts = {}

    def proof_is_current(self) -> bool:
        """Check an existing proof without verifying or accepting a newer state."""
        with self._lock:
            return (self._observer is not None and self._proof is not None
                    and self._proof == self._token())

    def verify(self) -> dict[str, int]:
        with self._lock:
            try:
                if self._observer is not None and self._proof == self._token():
                    return dict(self._counts)
                # Reopen on invalidation, so a replaced file or page changed
                # outside SQLite cannot be hidden by the observer's page cache.
                self.close()
                self._observer = sqlite3.connect(
                    self.store.path.as_uri() + "?mode=ro", uri=True, check_same_thread=False,
                )
                self._observer.execute("PRAGMA query_only=ON")
                before = self._token()
                counts = self.store.verify_integrity()
                after = self._token()
                if before == after:
                    self._counts = dict(counts)
                    self._proof = after
                # A concurrent commit never obtains a cached proof. The next
                # request verifies again, and route-level checks still run.
                return counts
            except sqlite3.OperationalError as exc:
                self.close()
                if getattr(exc, "sqlite_errorcode", 0) & 0xFF in (
                    sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
                ):
                    raise OperationalStorageBusyError("STORAGE_BUSY") from exc
                raise OperationalIntegrityError("integrity observer failed") from exc
            except (OSError, sqlite3.DatabaseError) as exc:
                self.close()
                raise OperationalIntegrityError("integrity observer failed") from exc
            except BaseException:
                self.close()
                raise
