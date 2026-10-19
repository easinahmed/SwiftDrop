"""Application service: the single façade the UI bridge (and tests) talk to.

It wires together persistence, settings, the preview, the queue, providers and
platform integration, and owns the cross-cutting rules (destination handling,
duplicate skipping, side effects of settings changes).
"""

from __future__ import annotations

import csv
import io
import os
import platform as py_platform
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from swiftdrop import binaries
from swiftdrop.appinfo import APP_NAME, APP_VERSION, BUNDLE_ID
from swiftdrop.capture import CaptureManager
from swiftdrop.engine.connpool import GLOBAL_POOL
from swiftdrop.engine.http import HttpDownloader
from swiftdrop.engine.segmented import SegmentedDownloader
from swiftdrop.events import ChangeTracker
from swiftdrop.handoff import InboxWatcher
from swiftdrop.history import HISTORY_KINDS, HISTORY_STATUSES, HistoryStore
from swiftdrop.logging_setup import get_logger, set_verbose
from swiftdrop.models import Collection, DownloadOptions, Job, JobState, MediaKind
from swiftdrop.paths import AppPaths, is_frozen
from swiftdrop.platform import NullPlatform, Platform, free_space
from swiftdrop.platform.quarantine import needs_open_confirmation
from swiftdrop.preview import PreviewItem, PreviewManager
from swiftdrop.providers.direct import DirectProvider
from swiftdrop.providers.registry import ProviderRegistry, SiteMatcher
from swiftdrop.queue import BatchSummary, DownloadQueue
from swiftdrop.ratelimit import TokenBucket
from swiftdrop.settings import SettingsError, SettingsStore, validate_directory, validate_patch
from swiftdrop.storage import Database
from swiftdrop.urls import InvalidUrlError, ParsedUrl, dedupe_key, display_domain, normalize_url, parse_url_list

log = get_logger("service")

MAX_SITE_CHECKS = 10  # full yt-dlp site matching is slow; only for copies with a few unknown links


class ServiceError(ValueError):
    """A user-facing problem with a request (shown as a message in the UI)."""


def _build_site_matcher(bucket: TokenBucket) -> SiteMatcher | None:
    try:
        from swiftdrop.providers.ytdlp import YtDlpProvider
    except ImportError:  # pragma: no cover - yt-dlp is a declared dependency
        log.warning("yt-dlp is not installed; only direct file downloads are available")
        return None
    return YtDlpProvider(
        bucket=bucket,
        segmented_factory=lambda n: SegmentedDownloader(connections=n, pool=GLOBAL_POOL, bucket=bucket),
    )


class AppService:
    def __init__(
        self,
        paths: AppPaths,
        platform: Platform | None = None,
        *,
        enable_sites: bool = True,
        inbox: bool = False,
    ) -> None:
        self.paths = paths.ensure()
        self.platform: Platform = platform or NullPlatform()
        self.db = Database(paths.database)
        self.settings = SettingsStore(self.db)
        self.tracker = ChangeTracker()
        self.history = HistoryStore(self.db)
        current = self.settings.get()
        self.bucket = TokenBucket(current.bandwidth_bytes_per_sec)
        direct = DirectProvider(
            lambda: HttpDownloader(bucket=self.bucket),
            lambda connections: SegmentedDownloader(connections=connections, pool=GLOBAL_POOL, bucket=self.bucket),
        )
        sites = _build_site_matcher(self.bucket) if enable_sites else None
        self.registry = ProviderRegistry(direct=direct, sites=sites)
        self.queue = DownloadQueue(
            registry=self.registry,
            db=self.db,
            history=self.history,
            settings=self.settings,
            tracker=self.tracker,
            partial_root=paths.partial_dir,
            on_batch_finished=self._on_batch_finished,
        )
        self.preview = PreviewManager(
            registry=self.registry,
            tracker=self.tracker,
            settings=self.settings,
            history=self.history,
            active_keys=self.queue.active_keys,
        )
        self._clipboard_seen: set[str] = set()
        self._popup_seen: set[str] = set()  # links already offered in a pop-up this session
        self.capture = CaptureManager(self)
        # Requests from later launches of the app (show the window, a swiftdrop:// link).
        self._inbox = InboxWatcher(paths.data_dir, self.handle_message) if inbox else None
        self._started = False
        self._shutdown_lock = threading.Lock()
        self._shut_down = False

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        set_verbose(self.settings.get().verbose_logging)
        self.queue.load()
        self.queue.start()
        self.preview.start()
        warm_up = getattr(self.registry.sites, "warm_up", None)
        if warm_up is not None:
            threading.Thread(target=warm_up, name="sites-warm-up", daemon=True).start()
        if self.settings.get().watch_clipboard:
            self.platform.start_clipboard_monitor(self.clipboard_detected)
        if self._inbox is not None:
            self._inbox.start()
        log.info("%s %s started (frozen=%s)", APP_NAME, APP_VERSION, is_frozen())

    def shutdown(self) -> None:
        """Pause running work (resumable), persist and close. Safe to call more than once."""
        with self._shutdown_lock:
            if self._shut_down:
                return
            self._shut_down = True
        log.info("Shutting down")
        try:
            if self._inbox is not None:
                self._inbox.stop()
            self.capture.shutdown()
            self.platform.stop_clipboard_monitor()
            self.preview.stop()
            self.queue.shutdown()
            if self.settings.get().cleanup_temp_on_quit:
                freed = self.queue.clean_orphan_partials()
                log.info("Removed %d bytes of unused partial files", freed)
        finally:
            self.db.close()

    # -- bootstrap / state --------------------------------------------------
    def bootstrap(self) -> dict[str, Any]:
        return {
            "app": {"name": APP_NAME, "version": APP_VERSION, "bundle_id": BUNDLE_ID, "frozen": is_frozen()},
            "settings": self.settings.get().to_dict(),
            "jobs": self.queue.jobs_public(),
            "collections": self.queue.collections_public(),
            "preview": self.preview.items_public(),
            "stats": self.queue.stats(),
            "capabilities": self.capabilities(),
        }

    def capabilities(self) -> dict[str, Any]:
        ffmpeg = binaries.find_ffmpeg()
        js = binaries.find_js_runtime()
        return {
            "sites": self.registry.sites is not None,
            "ffmpeg": bool(ffmpeg),
            "login_item": self.platform.login_item_supported(),
            "js_runtime": js.name if js else None,
            "platform": "windows" if sys.platform == "win32" else "mac",
        }

    # -- preview ------------------------------------------------------------
    def analyze_text(self, text: str, append: bool = True) -> dict[str, Any]:
        return self.preview.analyze(text, append=append)

    def start_downloads(
        self, items: list[dict[str, Any]], options: dict[str, Any] | None, destination: str | None
    ) -> dict[str, Any]:
        settings = self.settings.get()
        if destination:
            try:
                dest = validate_directory(destination)
            except SettingsError as exc:
                raise ServiceError(str(exc)) from exc
            if settings.remember_destination and dest != settings.download_dir:
                self.settings.update({"download_dir": dest})
                self.tracker.settings()
        else:
            try:
                dest = validate_directory(settings.download_dir)
            except SettingsError as exc:
                raise ServiceError(f"{exc} Choose a destination folder in Settings.") from exc
        opts = DownloadOptions.from_dict(options or {}, defaults=settings.default_options())
        selected_ids = [item["id"] for item in items]
        entry_selection = {item["id"]: item.get("entries") for item in items}
        preview_items = self.preview.take(selected_ids)
        active = self.queue.active_keys()
        created = 0
        skipped: list[dict[str, str]] = []
        job_ids: list[str] = []
        for item in preview_items:
            if item.link.blocked:
                skipped.append({"url": item.url, "reason": item.link.blocked.title})
                continue
            info = item.info
            if info is not None and info.is_playlist:
                ids, skipped_entries = self._enqueue_playlist(item, entry_selection.get(item.id), opts, dest, active)
                job_ids.extend(ids)
                created += len(ids)
                skipped.extend(skipped_entries)
                continue
            if item.key in active:
                skipped.append({"url": item.url, "reason": "Already in the queue"})
                continue
            provider = info.provider if info else item.link.provider
            job = Job(
                url=item.url,
                key=item.key,
                destination=dest,
                options=opts,
                provider=provider if provider in ("direct", "ytdlp", "auto") else "auto",
                title=(info.title if info else "") or "",
                source=display_domain(item.url),
                kind=(info.kind if info and info.kind != MediaKind.UNKNOWN else item.link.kind),
                thumbnail=info.thumbnail if info else None,
                extractor=(info.extractor if info else None) or item.link.label,
                duration=info.duration if info else None,
                total_bytes=info.size if info and not info.size_is_estimate else None,
                quality_label=opts.label() if provider == "ytdlp" else None,
            )
            job_ids.extend(self.queue.add([job]))
            active[item.key] = JobState.QUEUED.value
            created += 1
        return {"created": created, "skipped": skipped, "job_ids": job_ids}

    def _enqueue_playlist(
        self,
        item: PreviewItem,
        selection: list[str] | None,
        opts: DownloadOptions,
        dest: str,
        active: dict[str, str],
    ) -> tuple[list[str], list[dict[str, str]]]:
        info = item.info
        assert info is not None
        skipped: list[dict[str, str]] = []
        entries = [e for e in info.entries if e.available]
        if selection is not None:
            wanted = {str(s) for s in selection if isinstance(s, str)}
            entries = [e for e in entries if e.id in wanted]
        skip_history = self.settings.get().skip_already_downloaded
        jobs: list[Job] = []
        for entry in entries:
            try:
                url = normalize_url(entry.url)
            except InvalidUrlError:
                skipped.append({"url": entry.url, "reason": "Invalid link"})
                continue
            key = dedupe_key(url)
            if key in active:
                skipped.append({"url": url, "reason": "Already in the queue"})
                continue
            if skip_history and self.history.find_completed(key):
                skipped.append({"url": url, "reason": "Already downloaded"})
                continue
            link = self.registry.classify(url)
            if link.blocked:
                skipped.append({"url": url, "reason": link.blocked.title})
                continue
            default_kind = MediaKind.AUDIO if opts.audio_only else MediaKind.VIDEO
            kind = link.kind if link.provider == "direct" else default_kind
            jobs.append(
                Job(
                    url=url,
                    key=key,
                    destination=dest,
                    options=opts,
                    provider=link.provider,
                    title=entry.title,
                    source=display_domain(url),
                    kind=kind,
                    thumbnail=entry.thumbnail,
                    extractor=info.extractor,
                    duration=entry.duration,
                    playlist_index=entry.index,
                    quality_label=opts.label() if link.provider != "direct" else None,
                )
            )
            active[key] = JobState.QUEUED.value
        if not jobs:
            return [], skipped
        collection = Collection(
            title=info.title or display_domain(item.url),
            url=item.url,
            source=display_domain(item.url),
            destination=dest,
            extractor=info.extractor,
            thumbnail=info.thumbnail,
            total_entries=len(info.entries),
        )
        return self.queue.add(jobs, collection), skipped

    # -- queue actions --------------------------------------------------------
    def job_action(self, action: str, ids: list[str]) -> int:
        handlers = {
            "pause": self.queue.pause,
            "resume": self.queue.resume,
            "cancel": self.queue.cancel,
            "retry": self.queue.retry,
            "remove": self.queue.remove,
        }
        if action not in handlers:
            raise ServiceError("Unknown action.")
        return handlers[action](ids)

    def queue_action(self, action: str) -> int:
        if action == "pause_all":
            return self.queue.pause_all()
        if action == "resume_all":
            return self.queue.resume_all()
        if action == "retry_failed":
            return self.queue.retry_failed()
        if action in ("clear_completed", "clear_finished", "clear_failed", "clear_cancelled"):
            return self.queue.clear(action.removeprefix("clear_"))
        raise ServiceError("Unknown action.")

    def job_file(self, job_id: str) -> Path:
        job = self.queue.get(job_id)
        if job is None or job.state != JobState.COMPLETED or not job.filepath:
            raise ServiceError("This download has no file yet.")
        return Path(job.filepath)

    def history_file(self, entry_id: int) -> Path:
        entry = self.history.get(entry_id)
        if entry is None or not entry.get("filepath"):
            raise ServiceError("This history entry has no file.")
        return Path(entry["filepath"])

    def reveal(self, path: Path) -> bool:
        if not path.exists():
            if path.parent.exists():
                self.platform.reveal(path)
            raise ServiceError("The file was moved or deleted.")
        return self.platform.reveal(path)

    def open_file(self, path: Path, *, confirmed: bool = False) -> bool:
        if not path.exists():
            raise ServiceError("The file was moved or deleted.")
        if not confirmed and needs_open_confirmation(path):
            raise ServiceError("confirm_open")
        return self.platform.open_path(path)

    # -- history --------------------------------------------------------------
    def search_history(self, query: str, kind: str, status: str, limit: int, offset: int) -> dict[str, Any]:
        if kind not in HISTORY_KINDS or status not in HISTORY_STATUSES:
            raise ServiceError("Unknown filter.")
        return self.history.search(query.strip(), kind, status, limit, offset)

    def clear_history(self) -> int:
        count = self.history.clear()
        self.tracker.history()
        return count

    def delete_history(self, ids: list[int]) -> int:
        count = self.history.delete(ids)
        self.tracker.history()
        return count

    # -- export ---------------------------------------------------------------
    def export_text(self, kind: str) -> tuple[str, str]:
        """Return (suggested filename, contents) for an export."""
        stamp = datetime.now().strftime("%Y-%m-%d %H.%M")
        if kind == "failed":
            urls = [j["url"] for j in self.queue.jobs_public() if j["state"] == "failed"]
            rows = self.history.search(status="failed", limit=10_000)["items"]
            seen = set(urls)
            urls += [r["url"] for r in rows if r["url"] not in seen]
            return f"{APP_NAME} failed links {stamp}.txt", "\n".join(urls) + ("\n" if urls else "")
        if kind == "results":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["status", "title", "url", "file", "size_bytes", "type", "quality", "error", "finished"])
            for job in self.queue.jobs_public():
                writer.writerow(
                    [
                        job["state"],
                        job["title"],
                        job["url"],
                        job["filepath"] or "",
                        job["file_size"] or "",
                        job["kind"],
                        job["quality_label"] or "",
                        (job["error"] or {}).get("message", ""),
                        _fmt_time(job["finished_at"]),
                    ]
                )
            for row in self.history.all_rows():
                writer.writerow(
                    [
                        row["status"],
                        row["title"],
                        row["url"],
                        row["filepath"] or "",
                        row["file_size"] or "",
                        row["kind"],
                        row["quality"] or "",
                        row["error_message"] or "",
                        _fmt_time(row["finished_at"]),
                    ]
                )
            return f"{APP_NAME} downloads {stamp}.csv", buffer.getvalue()
        raise ServiceError("Unknown export.")

    # -- settings ---------------------------------------------------------------
    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        before = self.settings.get()
        try:
            clean = validate_patch(patch)
        except SettingsError as exc:
            raise ServiceError(str(exc)) from exc
        if "open_at_login" in clean and clean["open_at_login"] != before.open_at_login:
            try:
                self.platform.set_login_item(bool(clean["open_at_login"]))
            except RuntimeError as exc:
                raise ServiceError(str(exc)) from exc
        try:
            after = self.settings.update(clean)
        except SettingsError as exc:
            raise ServiceError(str(exc)) from exc
        if after.bandwidth_limit_kbps != before.bandwidth_limit_kbps:
            self.bucket.set_rate(after.bandwidth_bytes_per_sec)
        if after.max_concurrent != before.max_concurrent:
            self.queue.notify_settings_changed()
        if after.clipboard_monitoring and not before.clipboard_monitoring:
            self._clipboard_seen = set()
        if after.watch_clipboard != before.watch_clipboard:
            if after.watch_clipboard:
                self.platform.start_clipboard_monitor(self.clipboard_detected)
            else:
                self.platform.stop_clipboard_monitor()
        if after.verbose_logging != before.verbose_logging:
            set_verbose(after.verbose_logging)
        if after.theme != before.theme:
            self.platform.set_appearance(after.theme)
        self.tracker.settings()
        return after.to_dict()

    # -- clipboard ----------------------------------------------------------------
    def clipboard_detected(self, text: str) -> None:
        """Called by the clipboard watcher; only links are considered and nothing is stored.

        Download and video links open the pop-up (once per link per session); other links
        are offered in the in-app banner when "Watch clipboard for links" is on. The
        platform watchers already ignore copies made inside SwiftDrop.
        """
        settings = self.settings.get()
        result = parse_url_list(text)
        if not result.urls:
            return
        remaining = [p for p in result.urls if p.key not in self._popup_seen]
        if settings.clipboard_popup and self.capture.has_ui:
            active = self.queue.active_keys()
            offered = self._downloadable([p for p in remaining if p.key not in active])
            if offered:
                self._popup_seen.update(p.key for p in offered)
                if len(offered) == 1:
                    self.capture.offer_url(offered[0].url, origin="clipboard")
                else:
                    self.capture.offer_links([p.url for p in offered], origin="clipboard")
                remaining = [p for p in remaining if p.key not in self._popup_seen]
        if not settings.clipboard_monitoring:
            return
        known = self.preview.keys() | set(self.queue.active_keys()) | self._clipboard_seen
        banner = [p for p in remaining if p.key not in known]
        if not banner:
            return
        for parsed in banner:
            self._clipboard_seen.add(parsed.key)
        self.tracker.clipboard(
            {
                "count": len(banner),
                "urls": [p.url for p in banner[:500]],
                "at": time.time(),
            }
        )

    def _downloadable(self, links: list[ParsedUrl]) -> list[ParsedUrl]:
        """Links worth a pop-up: a known file type or a site the video engine supports."""
        picked: set[str] = set()
        unknown: list[ParsedUrl] = []
        for parsed in links:
            info = self.registry.classify(parsed.url)
            if info.blocked:
                continue
            if info.provider in ("direct", "ytdlp"):
                picked.add(parsed.key)
            elif info.provider == "auto":
                unknown.append(parsed)
        if self.registry.sites is not None and len(unknown) <= MAX_SITE_CHECKS:
            picked.update(p.key for p in unknown if self.registry.site_match(p.url) is not None)
        return [p for p in links if p.key in picked]

    # -- requests from other launches ------------------------------------------------
    def handle_message(self, message: dict[str, Any]) -> None:
        """A validated inbox message (see :mod:`swiftdrop.handoff`)."""
        if message["type"] == "show":
            self.capture.show_main()
        elif message["type"] == "add":
            self.capture.offer_url(message["url"], origin="link")

    # -- maintenance ------------------------------------------------------------------
    def storage_info(self) -> dict[str, Any]:
        settings = self.settings.get()
        return {
            "partial_bytes": self.queue.partial_usage(),
            "partial_dir": str(self.paths.partial_dir),
            "download_dir_free": free_space(Path(settings.download_dir)),
        }

    def clean_temp(self, include_paused: bool) -> int:
        return self.queue.clean_all_partials() if include_paused else self.queue.clean_orphan_partials()

    def diagnostics(self) -> dict[str, Any]:
        ffmpeg = binaries.find_ffmpeg()
        ffprobe = binaries.find_ffprobe()
        js = binaries.find_js_runtime()
        try:
            import yt_dlp.version

            ytdlp_version = yt_dlp.version.__version__
        except Exception:
            ytdlp_version = None
        return {
            "app": f"{APP_NAME} {APP_VERSION}",
            "python": sys.version.split()[0],
            "macos": py_platform.mac_ver()[0],
            "arch": binaries.machine_arch(),
            "yt_dlp": ytdlp_version,
            "ffmpeg": {
                "path": str(ffmpeg) if ffmpeg else None,
                "version": binaries.ffmpeg_version(ffmpeg),
                "bundled": binaries.is_bundled(ffmpeg),
            },
            "ffprobe": str(ffprobe) if ffprobe else None,
            "js_runtime": {"name": js.name, "version": js.version, "path": str(js.path)} if js else None,
            "paths": {
                "data": str(self.paths.data_dir),
                "logs": str(self.paths.logs_dir),
                "partial": str(self.paths.partial_dir),
            },
            "frozen": is_frozen(),
            "pid": os.getpid(),
        }

    # -- notifications ------------------------------------------------------------------
    def _on_batch_finished(self, summary: BatchSummary) -> None:
        if summary.failed and summary.completed:
            title = "Downloads finished"
            body = f"{summary.completed} completed, {summary.failed} failed."
        elif summary.failed:
            title = "Downloads failed"
            body = f"{summary.failed} download{'s' if summary.failed != 1 else ''} couldn't be completed."
        else:
            title = "Downloads complete"
            body = f"{summary.completed} file{'s' if summary.completed != 1 else ''} saved."
        self.tracker.notice("success" if not summary.failed else "warning", f"{title}: {body}")
        if self.settings.get().notifications:
            self.platform.notify(title, body)


def _fmt_time(value: float | None) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")
