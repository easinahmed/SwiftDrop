"""Confirm windows for links that arrive from outside the main window.

Links come from the clipboard pop-up (a download or video link was just copied) and from
``swiftdrop://add?url=…`` links (the "Send to SwiftDrop" bookmark). Nothing here ever
starts a download on its own: every link is shown in a confirm window first.

* A direct file link (known file extension) gets a 1-byte ranged probe for its name and
  size. If the probe fails, a copied link is ignored (it isn't a download after all); a
  link the user sent on purpose is still shown, named from its URL.
* A video page (a site yt-dlp knows) is shown as is: Start / Start later queue it with
  the default quality.
* Several links in one copy, or a playlist, open one window offering "Add all", which
  puts them in the New Download list and shows the main window.

At most :data:`MAX_PENDING` windows wait at once. The window itself is behind
:class:`ConfirmUI` so tests can fake it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from swiftdrop.cancel import CancelToken
from swiftdrop.errors import DownloadFailure
from swiftdrop.filenames import choose_filename, kind_for_extension, sanitize_filename, split_ext
from swiftdrop.logging_setup import get_logger
from swiftdrop.models import InspectResult, Job, MediaKind, new_id
from swiftdrop.settings import SettingsError, validate_directory
from swiftdrop.urls import dedupe_key, display_domain

if TYPE_CHECKING:
    from swiftdrop.service import AppService

log = get_logger("capture")

MAX_PENDING = 20
MAX_LINKS_SHOWN = 100
DECISIONS = ("start", "later", "cancel", "add_all")


class CaptureError(ValueError):
    """A user-facing problem with a confirm-window action."""


class ConfirmUI(Protocol):
    """Opens and closes the confirm window for a waiting capture (called from worker threads)."""

    def open(self, capture_id: str) -> None: ...

    def close(self, capture_id: str) -> None: ...


@dataclass
class PendingCapture:
    id: str
    kind: str  # "file" | "page" | "links"
    origin: str  # "clipboard" | "link"
    urls: list[str]
    provider: str = "direct"
    filename: str = ""
    size: int | None = None
    media: MediaKind = MediaKind.OTHER
    label: str = ""
    opened: bool = False
    deciding: bool = False

    def public(self) -> dict[str, Any]:
        sites: list[str] = []
        for url in self.urls:
            site = display_domain(url)
            if site and site not in sites:
                sites.append(site)
        return {
            "id": self.id,
            "kind": self.kind,
            "origin": self.origin,
            "url": self.urls[0],
            "urls": self.urls[:MAX_LINKS_SHOWN],
            "count": len(self.urls),
            "sites": sites[:5],
            "source": sites[0] if sites else "",
            "label": self.label,
            "filename": self.filename,
            "size": self.size,
            "media": self.media.value,
        }


class CaptureManager:
    def __init__(self, service: AppService) -> None:
        self._service = service
        self._lock = threading.Lock()
        self._pending: dict[str, PendingCapture] = {}
        self._ui: ConfirmUI | None = None
        self._show_main: Callable[[], None] | None = None
        self._closed = False

    # -- lifecycle --------------------------------------------------------------
    def attach_ui(self, ui: ConfirmUI, show_main: Callable[[], None] | None = None) -> None:
        """Called once the window system runs; opens windows for links that arrived earlier."""
        with self._lock:
            self._ui = ui
            self._show_main = show_main
            waiting = [c.id for c in self._pending.values() if not c.opened]
        for capture_id in waiting:
            self._open(capture_id)

    @property
    def has_ui(self) -> bool:
        return self._ui is not None

    def show_main(self) -> None:
        show = self._show_main
        if show is not None:
            show()

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._pending.clear()

    def pending_ids(self) -> list[str]:
        with self._lock:
            return list(self._pending)

    # -- offering links (any thread) ------------------------------------------------
    def offer_url(self, url: str, *, origin: str) -> None:
        """Show one link in a confirm window (probing a file link first, off the caller's thread)."""
        threading.Thread(target=self._prepare_url, args=(url, origin), name="capture-prepare", daemon=True).start()

    def offer_links(self, urls: list[str], *, origin: str) -> None:
        if urls:
            self._add(PendingCapture(id=new_id(), kind="links", origin=origin, urls=list(urls)))

    def _prepare_url(self, url: str, origin: str) -> None:
        try:
            capture = self._describe(url, origin)
        except Exception:
            log.exception("Could not prepare a link for the confirm window")
            return
        if capture is not None:
            self._add(capture)

    def _describe(self, url: str, origin: str) -> PendingCapture | None:
        registry = self._service.registry
        link = registry.classify(url)
        if link.blocked:
            if origin == "link":
                self._service.tracker.notice("warning", f"{link.blocked.title}: {link.blocked.message}")
            return None
        if link.provider != "direct":
            if link.playlist_hint:  # playlists are picked from in the New Download list
                return PendingCapture(id=new_id(), kind="links", origin=origin, urls=[url], label=link.label)
            page_media: MediaKind = (
                link.kind if link.kind not in (MediaKind.UNKNOWN, MediaKind.OTHER) else MediaKind.VIDEO
            )
            provider = link.provider if link.provider in ("ytdlp", "auto") else "auto"
            return PendingCapture(
                id=new_id(),
                kind="page",
                origin=origin,
                urls=[url],
                provider=provider,
                media=page_media,
                label=link.label,
            )
        info = self._probe(url)
        if info is None:
            if origin == "clipboard":
                return None  # copied, but not something we can download: stay quiet
            name = choose_filename(url=url, content_disposition=None, content_type=None)
            return PendingCapture(id=new_id(), kind="file", origin=origin, urls=[url], filename=name, media=link.kind)
        name = info.filename or choose_filename(url=url, content_disposition=None, content_type=info.content_type)
        media = info.kind if info.kind not in (MediaKind.UNKNOWN,) else link.kind
        return PendingCapture(
            id=new_id(),
            kind="file",
            origin=origin,
            urls=[url],
            filename=sanitize_filename(name),
            size=info.size if info.size is not None and info.size >= 0 else None,
            media=media if media != MediaKind.UNKNOWN else MediaKind.OTHER,
        )

    def _probe(self, url: str) -> InspectResult | None:
        """1-byte ranged GET (redirects followed); None if the answer isn't a file."""
        try:
            return self._service.registry.direct.inspect(url, CancelToken(), self._service.settings.get())
        except DownloadFailure as exc:
            log.info("Link check failed: %s", exc.info.code)
        except Exception as exc:
            log.warning("Link check failed: %s", type(exc).__name__)
        return None

    def _add(self, capture: PendingCapture) -> None:
        with self._lock:
            if self._closed or len(self._pending) >= MAX_PENDING:
                log.info("Too many confirm windows open; a link was not shown")
                return
            self._pending[capture.id] = capture
        self._open(capture.id)

    def _open(self, capture_id: str) -> None:
        with self._lock:
            ui = self._ui
            capture = self._pending.get(capture_id)
            if ui is None or capture is None or capture.opened:
                return  # opened by attach_ui() once the window system runs
            capture.opened = True
        log.info("Showing a confirm window (%s, from %s)", capture.kind, capture.origin)
        try:
            ui.open(capture_id)
        except Exception:
            log.exception("Could not open the confirm window")
            with self._lock:
                self._pending.pop(capture_id, None)

    # -- the confirm window ------------------------------------------------------
    def capture_public(self, capture_id: str) -> dict[str, Any]:
        with self._lock:
            capture = self._pending.get(capture_id)
            data = capture.public() if capture is not None else None
        if data is None:
            raise CaptureError("This link is no longer waiting.")
        settings = self._service.settings.get()
        data.update(
            {
                "folder": settings.download_dir,
                "theme": settings.theme,
                "quality_label": settings.default_options().label(),
            }
        )
        return data

    def decide(self, capture_id: str, decision: str, filename: str, folder: str) -> dict[str, Any]:
        if decision not in DECISIONS:
            raise CaptureError("Unknown choice.")
        with self._lock:
            capture = self._pending.get(capture_id)
            if capture is None or capture.deciding:
                raise CaptureError("This link is no longer waiting.")
            capture.deciding = True
        result: dict[str, Any] = {"decision": decision, "job_id": None}
        try:
            if decision in ("start", "later"):
                if capture.kind == "links":
                    raise CaptureError("Use Add all for several links.")
                result["job_id"] = self._create_job(capture, filename, folder, paused=decision == "later")
            elif decision == "add_all":
                self._add_to_list(capture)
        except Exception:
            with self._lock:
                capture.deciding = False  # let the user fix the folder or name and try again
            raise
        self._finish(capture_id)
        return result

    def _create_job(self, capture: PendingCapture, filename: str, folder: str, *, paused: bool) -> str:
        service = self._service
        try:
            destination = validate_directory(folder)
        except SettingsError as exc:
            raise CaptureError(str(exc)) from exc
        url = capture.urls[0]
        key = dedupe_key(url)
        if key in service.queue.active_keys():
            raise CaptureError("This link is already in your downloads.")
        options = service.settings.get().default_options()
        if capture.kind == "file":
            name = sanitize_filename(filename.strip()) if filename.strip() else capture.filename
            kind = kind_for_extension(split_ext(name)[1])
            job = Job(
                url=url,
                key=key,
                destination=destination,
                options=options,
                provider="direct",
                title=name,
                source=display_domain(url),
                kind=kind if kind != MediaKind.UNKNOWN else capture.media,
                total_bytes=capture.size or None,
                meta={"filename_override": name},
            )
        else:
            job = Job(
                url=url,
                key=key,
                destination=destination,
                options=options,
                provider=capture.provider,
                title="",
                source=display_domain(url),
                kind=capture.media,
                extractor=capture.label or None,
                quality_label=options.label(),
            )
        (job_id,) = service.queue.add([job], paused=paused)
        label = job.title or display_domain(url)
        service.tracker.notice("info", f"{'Added' if paused else 'Downloading'} {label}")
        return job_id

    def _add_to_list(self, capture: PendingCapture) -> None:
        service = self._service
        service.analyze_text("\n".join(capture.urls), append=True)
        service.tracker.navigate("home")
        self.show_main()

    def window_closed(self, capture_id: str) -> None:
        """Closing the confirm window counts as Cancel (unless a choice is being carried out)."""
        with self._lock:
            capture = self._pending.get(capture_id)
            if capture is None or capture.deciding:
                return
        self._finish(capture_id)

    def _finish(self, capture_id: str) -> None:
        with self._lock:
            capture = self._pending.pop(capture_id, None)
            ui = self._ui
        if capture is not None and ui is not None and capture.opened:
            try:
                ui.close(capture_id)
            except Exception:
                log.warning("Could not close the confirm window", exc_info=True)
