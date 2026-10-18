"""Download history (finished jobs). Clearing history never deletes files."""

from __future__ import annotations

import os
import time
from typing import Any

from swiftdrop.models import Job, JobState
from swiftdrop.storage import Database

HISTORY_KINDS = ("all", "video", "audio", "image", "other")
HISTORY_STATUSES = ("all", "completed", "failed", "cancelled")


class HistoryStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, job: Job, collection_title: str | None = None) -> None:
        if job.state not in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED):
            return
        self._db.execute(
            """
            INSERT INTO history(job_id, url, dedupe_key, title, source, kind, status, filepath, file_size,
                                quality, error_code, error_message, thumbnail, collection_title, duration,
                                sha256, finished_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                title=excluded.title, kind=excluded.kind, status=excluded.status, filepath=excluded.filepath,
                file_size=excluded.file_size, quality=excluded.quality, error_code=excluded.error_code,
                error_message=excluded.error_message, thumbnail=excluded.thumbnail,
                collection_title=excluded.collection_title, duration=excluded.duration,
                sha256=excluded.sha256, finished_at=excluded.finished_at
            """,
            (
                job.id,
                job.url,
                job.key,
                job.title or job.filename or job.url,
                job.source,
                job.kind.value,
                job.state.value,
                job.filepath,
                job.file_size,
                job.quality_label,
                job.error.code if job.error else None,
                job.error.message if job.error else None,
                job.thumbnail,
                collection_title,
                job.duration,
                job.sha256,
                job.finished_at or time.time(),
            ),
        )

    @staticmethod
    def _row_to_public(row: Any) -> dict[str, Any]:
        item = dict(row)
        filepath = item.get("filepath")
        item["file_exists"] = bool(filepath and os.path.exists(filepath))
        item.pop("dedupe_key", None)
        return item

    def search(
        self, query: str = "", kind: str = "all", status: str = "all", limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        clauses, params = [], []
        if query:
            like = f"%{query.replace('%', r'\%').replace('_', r'\_')}%"
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\' "
                "OR filepath LIKE ? ESCAPE '\\')"
            )
            params.extend([like] * 4)
        if kind != "all":
            if kind == "other":
                clauses.append("kind IN ('other', 'unknown')")
            else:
                clauses.append("kind = ?")
                params.append(kind)
        if status != "all":
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = self._db.query(f"SELECT count(*) AS n FROM history {where}", params)[0]["n"]  # noqa: S608
        rows = self._db.query(
            f"SELECT * FROM history {where} ORDER BY finished_at DESC, id DESC LIMIT ? OFFSET ?",  # noqa: S608
            [*params, limit, offset],
        )
        return {"items": [self._row_to_public(r) for r in rows], "total": total}

    def get(self, entry_id: int) -> dict[str, Any] | None:
        rows = self._db.query("SELECT * FROM history WHERE id = ?", (entry_id,))
        return self._row_to_public(rows[0]) if rows else None

    def find_completed(self, dedupe_key: str) -> dict[str, Any] | None:
        """Most recent completed download of the same link whose file still exists."""
        rows = self._db.query(
            "SELECT * FROM history WHERE dedupe_key = ? AND status = 'completed' ORDER BY finished_at DESC LIMIT 5",
            (dedupe_key,),
        )
        for row in rows:
            item = self._row_to_public(row)
            if item["file_exists"]:
                return item
        return None

    def delete(self, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        return self._db.execute(f"DELETE FROM history WHERE id IN ({placeholders})", ids)  # noqa: S608

    def clear(self) -> int:
        return self._db.execute("DELETE FROM history")

    def all_rows(self) -> list[dict[str, Any]]:
        return [self._row_to_public(r) for r in self._db.query("SELECT * FROM history ORDER BY finished_at DESC")]
