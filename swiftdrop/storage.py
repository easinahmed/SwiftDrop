"""SQLite persistence for settings, the download queue and history.

One database file in Application Support, WAL mode, a single shared
connection guarded by a lock (writes are small and infrequent). A corrupt
database is moved aside instead of crashing the app.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from swiftdrop.logging_setup import get_logger
from swiftdrop.models import Collection, Job

log = get_logger("storage")

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    ord INTEGER NOT NULL,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE,
    url TEXT NOT NULL,
    dedupe_key TEXT,
    title TEXT,
    source TEXT,
    kind TEXT,
    status TEXT NOT NULL,
    filepath TEXT,
    file_size INTEGER,
    quality TEXT,
    error_code TEXT,
    error_message TEXT,
    thumbnail TEXT,
    collection_title TEXT,
    duration REAL,
    sha256 TEXT,
    finished_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS history_finished ON history(finished_at DESC);
CREATE INDEX IF NOT EXISTS history_key ON history(dedupe_key);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = self._open()

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._connect()
        except sqlite3.DatabaseError:
            backup = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            log.warning("Database at %s is unreadable; moving it to %s", self.path, backup)
            self.path.replace(backup)
            for suffix in ("-wal", "-shm"):
                sidecar = self.path.with_name(self.path.name + suffix)
                if sidecar.exists():
                    sidecar.unlink()
            return self._connect()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.executescript(_SCHEMA)
        if version < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.execute("SELECT count(*) FROM jobs").fetchone()  # surfaces corruption early
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            with contextlib.suppress(sqlite3.Error):
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()

    # -- settings -------------------------------------------------------
    def load_settings(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for row in self.query("SELECT key, value FROM settings"):
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                log.warning("Ignoring unreadable setting %s", row["key"])
        return result

    def save_settings(self, values: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(k, json.dumps(v)) for k, v in values.items()],
            )

    # -- jobs -----------------------------------------------------------
    def save_jobs(self, jobs: Iterable[Job]) -> None:
        now = time.time()
        rows = [(job.id, job.order, json.dumps(job.to_record()), now) for job in jobs]
        if not rows:
            return
        with self.transaction() as conn:
            conn.executemany(
                "INSERT INTO jobs(id, ord, data, updated_at) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ord=excluded.ord, data=excluded.data, "
                "updated_at=excluded.updated_at",
                rows,
            )

    def delete_jobs(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        if not ids:
            return
        with self.transaction() as conn:
            conn.executemany("DELETE FROM jobs WHERE id=?", [(i,) for i in ids])

    def load_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        for row in self.query("SELECT data FROM jobs ORDER BY ord ASC"):
            try:
                jobs.append(Job.from_record(json.loads(row["data"])))
            except (ValueError, TypeError, KeyError) as exc:
                log.warning("Skipping unreadable queued job: %s", exc)
        return jobs

    # -- collections ----------------------------------------------------
    def save_collection(self, collection: Collection) -> None:
        self.execute(
            "INSERT INTO collections(id, data) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (collection.id, json.dumps(collection.to_record())),
        )

    def delete_collection(self, collection_id: str) -> None:
        self.execute("DELETE FROM collections WHERE id=?", (collection_id,))

    def load_collections(self) -> list[Collection]:
        result: list[Collection] = []
        for row in self.query("SELECT data FROM collections"):
            try:
                result.append(Collection.from_record(json.loads(row["data"])))
            except (ValueError, TypeError) as exc:
                log.warning("Skipping unreadable collection: %s", exc)
        return result
