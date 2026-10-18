"""The pre-download preview: detected links, their status and metadata.

``analyze`` is synchronous and cheap (parsing + offline classification), so
pasting 1,000 links stays instant. Metadata (title, size, playlist entries) is
then fetched by a small fixed pool of inspector threads — never one thread per
link — and streamed to the UI as it arrives. Inspection is optional: a link can
be downloaded before (or without) being inspected.
"""

from __future__ import annotations

import queue as queue_mod
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.errors import DownloadFailure, classify_exception
from swiftdrop.events import ChangeTracker
from swiftdrop.history import HistoryStore
from swiftdrop.logging_setup import get_logger
from swiftdrop.models import ErrorInfo, InspectResult, MediaKind, new_id
from swiftdrop.providers.registry import LinkInfo, ProviderRegistry
from swiftdrop.settings import SettingsStore
from swiftdrop.urls import display_domain, parse_url_list

log = get_logger("preview")

MAX_PREVIEW_ITEMS = 5000
INSPECT_WORKERS = 4


@dataclass
class PreviewItem:
    url: str
    key: str
    link: LinkInfo
    id: str = field(default_factory=new_id)
    status: str = "pending"  # pending | inspecting | ready | error | blocked
    info: InspectResult | None = None
    error: ErrorInfo | None = None
    in_queue: str | None = None  # state of an unfinished job for the same link
    downloaded_before: dict[str, Any] | None = None
    order: int = 0

    def to_public(self) -> dict[str, Any]:
        info = self.info.to_public() if self.info else None
        kind = (self.info.kind if self.info and self.info.kind != MediaKind.UNKNOWN else self.link.kind).value
        return {
            "id": self.id,
            "url": self.url,
            "source": display_domain(self.url),
            "status": self.status,
            "link": self.link.to_public(),
            "info": info,
            "kind": kind,
            "title": (self.info.title if self.info and self.info.title else None),
            "error": self.error.to_dict() if self.error else None,
            "in_queue": self.in_queue,
            "downloaded_before": self.downloaded_before,
            "order": self.order,
        }


class PreviewManager:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        tracker: ChangeTracker,
        settings: SettingsStore,
        history: HistoryStore,
        active_keys: Callable[[], dict[str, str]],
        workers: int = INSPECT_WORKERS,
    ) -> None:
        self._registry = registry
        self._tracker = tracker
        self._settings = settings
        self._history = history
        self._active_keys = active_keys  # callable -> dict[key, state]
        self._lock = threading.RLock()
        self._items: dict[str, PreviewItem] = {}
        self._tokens: dict[str, CancelToken] = {}
        self._work: queue_mod.Queue[str | None] = queue_mod.Queue()
        self._order = 0
        self._threads = [
            threading.Thread(target=self._worker, name=f"inspector-{i}", daemon=True) for i in range(workers)
        ]
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        with self._lock:
            for item_id in list(self._tokens):
                self._tokens.pop(item_id).stop(StopReason.CANCEL)
        for _ in self._threads:
            self._work.put(None)

    # -- analysis ---------------------------------------------------------
    def analyze(self, text: str, append: bool = True) -> dict[str, Any]:
        if not append:
            self.clear()
        with self._lock:
            known = {item.key for item in self._items.values()}
        result = parse_url_list(text, known_keys=known)
        active = self._active_keys()
        skip_history = self._settings.get().skip_already_downloaded
        auto_inspect = self._settings.get().auto_inspect
        added: list[PreviewItem] = []
        capacity_hit = False
        with self._lock:
            for parsed in result.urls:
                if len(self._items) >= MAX_PREVIEW_ITEMS:
                    capacity_hit = True
                    break
                link = self._registry.classify(parsed.url)
                item = PreviewItem(url=parsed.url, key=parsed.key, link=link, order=self._order)
                self._order += 1
                if link.blocked:
                    item.status = "blocked"
                    item.error = link.blocked
                item.in_queue = active.get(parsed.key)
                if skip_history:
                    try:
                        previous = self._history.find_completed(parsed.key)
                    except Exception:
                        previous = None
                    if previous:
                        item.downloaded_before = {
                            "filepath": previous["filepath"],
                            "finished_at": previous["finished_at"],
                            "title": previous["title"],
                        }
                self._items[item.id] = item
                added.append(item)
        for item in added:
            self._tracker.preview(item.id)
            if auto_inspect and item.status == "pending":
                self._enqueue(item.id)
        return {
            "added": [item.to_public() for item in added],
            "duplicates": len(result.duplicates),
            "invalid": [{"url": url[:300], "reason": reason} for url, reason in result.invalid[:200]],
            "invalid_count": len(result.invalid),
            "truncated": result.truncated or capacity_hit,
        }

    def _enqueue(self, item_id: str) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item_id in self._tokens:
                return
            self._tokens[item_id] = CancelToken()
        self._work.put(item_id)

    def inspect(self, ids: list[str]) -> int:
        count = 0
        for item_id in ids:
            with self._lock:
                item = self._items.get(item_id)
                if item is None or item.status in ("blocked", "inspecting"):
                    continue
                item.status = "pending"
                item.error = None
            self._tracker.preview(item_id)
            self._enqueue(item_id)
            count += 1
        return count

    def _worker(self) -> None:
        while True:
            item_id = self._work.get()
            if item_id is None:
                return
            with self._lock:
                item = self._items.get(item_id)
                token = self._tokens.get(item_id)
                if item is None or token is None or token.stopped:
                    self._tokens.pop(item_id, None)
                    continue
                item.status = "inspecting"
                url, link = item.url, item.link
            self._tracker.preview(item_id)
            info: InspectResult | None = None
            error: ErrorInfo | None = None
            try:
                info = self._registry.inspect(url, link, token, self._settings.get())
            except JobStopped:
                pass
            except DownloadFailure as exc:
                error = exc.info
            except Exception as exc:
                log.exception("Inspection failed")
                error = classify_exception(exc)
            with self._lock:
                self._tokens.pop(item_id, None)
                item = self._items.get(item_id)
                if item is None or token.stopped:
                    continue
                if info is not None:
                    item.info = info
                    item.status = "ready"
                    item.error = None
                else:
                    item.status = "error"
                    item.error = error
            self._tracker.preview(item_id)

    # -- mutations --------------------------------------------------------
    def remove(self, ids: list[str]) -> int:
        removed = []
        with self._lock:
            for item_id in ids:
                if self._items.pop(item_id, None) is not None:
                    removed.append(item_id)
                    token = self._tokens.pop(item_id, None)
                    if token:
                        token.stop(StopReason.CANCEL)
        for item_id in removed:
            self._tracker.preview_removed(item_id)
        return len(removed)

    def clear(self) -> int:
        with self._lock:
            ids = list(self._items)
        return self.remove(ids)

    def take(self, ids: list[str]) -> list[PreviewItem]:
        """Remove and return items (used when downloads start)."""
        with self._lock:
            items = [self._items[i] for i in ids if i in self._items]
        self.remove([item.id for item in items])
        return items

    # -- queries ----------------------------------------------------------
    def items_public(self, ids: list[str] | set[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if ids is None:
                items = sorted(self._items.values(), key=lambda i: i.order)
            else:
                items = [self._items[i] for i in ids if i in self._items]
            return [item.to_public() for item in items]

    def entries(self, item_id: str) -> list[dict[str, Any]]:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item.info is None:
                return []
            return [entry.to_dict() for entry in item.info.entries]

    def keys(self) -> set[str]:
        with self._lock:
            return {item.key for item in self._items.values()}

    def get(self, item_id: str) -> PreviewItem | None:
        with self._lock:
            return self._items.get(item_id)
