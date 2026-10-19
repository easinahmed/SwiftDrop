"""Change tracking between the engine (many threads) and the UI (one publisher).

Download threads never talk to the UI directly. They mark objects dirty here;
a single publisher thread drains the tracker a few times per second and sends
one coalesced update, so 100 concurrent progress streams cost the UI thread
one call per tick.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Changes:
    jobs: set[str] = field(default_factory=set)
    removed_jobs: set[str] = field(default_factory=set)
    preview: set[str] = field(default_factory=set)
    removed_preview: set[str] = field(default_factory=set)
    collections: bool = False
    settings: bool = False
    history: bool = False
    clipboard: dict[str, Any] | None = None
    notices: list[dict[str, Any]] = field(default_factory=list)
    navigate: str | None = None  # a page the main window should switch to

    def empty(self) -> bool:
        return not (
            self.jobs
            or self.removed_jobs
            or self.preview
            or self.removed_preview
            or self.collections
            or self.settings
            or self.history
            or self.clipboard is not None
            or self.notices
            or self.navigate is not None
        )


class ChangeTracker:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._changes = Changes()

    def _mark(self, fn: Callable[[Changes], Any]) -> None:
        with self._cond:
            fn(self._changes)
            self._cond.notify_all()

    def job(self, job_id: str) -> None:
        def apply(c: Changes) -> None:
            c.jobs.add(job_id)
            c.removed_jobs.discard(job_id)

        self._mark(apply)

    def job_removed(self, job_id: str) -> None:
        def apply(c: Changes) -> None:
            c.jobs.discard(job_id)
            c.removed_jobs.add(job_id)
            c.collections = True

        self._mark(apply)

    def preview(self, item_id: str) -> None:
        def apply(c: Changes) -> None:
            c.preview.add(item_id)
            c.removed_preview.discard(item_id)

        self._mark(apply)

    def preview_removed(self, item_id: str) -> None:
        def apply(c: Changes) -> None:
            c.preview.discard(item_id)
            c.removed_preview.add(item_id)

        self._mark(apply)

    def collections(self) -> None:
        self._mark(lambda c: setattr(c, "collections", True))

    def settings(self) -> None:
        self._mark(lambda c: setattr(c, "settings", True))

    def history(self) -> None:
        self._mark(lambda c: setattr(c, "history", True))

    def clipboard(self, payload: dict[str, Any]) -> None:
        self._mark(lambda c: setattr(c, "clipboard", payload))

    def notice(self, kind: str, message: str, **extra: Any) -> None:
        self._mark(lambda c: c.notices.append({"kind": kind, "message": message, **extra}))

    def navigate(self, page: str) -> None:
        self._mark(lambda c: setattr(c, "navigate", page))

    def wait(self, timeout: float) -> bool:
        with self._cond:
            if self._changes.empty():
                self._cond.wait(timeout)
            return not self._changes.empty()

    def drain(self) -> Changes:
        with self._cond:
            changes, self._changes = self._changes, Changes()
            return changes
