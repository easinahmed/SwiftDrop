"""Sites supported by yt-dlp (video/audio platforms, HLS/DASH streams, podcasts …).

yt-dlp runs in-process: one ``YoutubeDL`` instance per job, inside the job's
worker thread, so the queue's concurrency limit bounds it like everything else.

* Cancellation: the progress / post-processing hooks raise a
  ``DownloadCancelled`` subclass as soon as the job's token stops; yt-dlp
  re-raises it unchanged. Partial ``.part`` / fragment files stay in the job's
  staging folder, so "pause" + "resume" continues where it stopped.
* Progress: merged downloads (video + audio) arrive as two sequential streams;
  they are combined into one monotonic overall progress value.
* Output: files are written to the staging folder and moved into the
  destination by :meth:`JobContext.finalize` (conflict-safe).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from swiftdrop import binaries
from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.progress import ProgressUpdate, Throttle
from swiftdrop.errors import DownloadFailure, classify_exception, classify_message, failure
from swiftdrop.filenames import kind_for_extension
from swiftdrop.logging_setup import get_logger
from swiftdrop.models import DownloadOptions, InspectResult, MediaKind, PlaylistEntry
from swiftdrop.providers.base import DownloadOutcome, JobContext
from swiftdrop.providers.registry import SiteMatch
from swiftdrop.providers.sites import extractor_is_playlist, pretty_extractor
from swiftdrop.ratelimit import TokenBucket
from swiftdrop.redact import redact
from swiftdrop.settings import Settings

log = get_logger("ytdlp")

MAX_PLAYLIST_ENTRIES = 5000
_UNAVAILABLE_TITLES = ("[private video]", "[deleted video]", "[unavailable video]")
_PP_PHASES = {
    "Merger": "Merging video and audio",
    "ExtractAudio": "Converting audio",
    "FFmpegExtractAudio": "Converting audio",
    "VideoRemuxer": "Remuxing",
    "VideoConvertor": "Converting video",
    "FixupM3u8": "Finalizing stream",
    "FixupM4a": "Finalizing audio",
    "FixupDuplicateMoov": "Finalizing video",
    "FixupStretched": "Finalizing video",
    "FixupTimestamp": "Finalizing video",
    "FixupDuration": "Finalizing video",
    "MoveFiles": "Finishing",
}

try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, DownloadError, ExtractorError
except ImportError as exc:  # pragma: no cover - declared dependency
    raise ImportError("yt-dlp is required for site downloads") from exc


class _Stopped(DownloadCancelled):
    """Raised from hooks to unwind yt-dlp when the job is paused/cancelled."""

    msg = "Stopped by SwiftDrop"


class _Logger:
    """Routes yt-dlp output to our (redacting) log; never to stdout."""

    def __init__(self, job: str) -> None:
        self._job = job
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        log.debug("[%s] %s", self._job, msg)

    def info(self, msg: str) -> None:
        log.debug("[%s] %s", self._job, msg)

    def warning(self, msg: str) -> None:
        self.warnings.append(redact(msg)[:500])
        log.info("[%s] warning: %s", self._job, msg)

    def error(self, msg: str) -> None:
        log.warning("[%s] error: %s", self._job, msg)


def format_options(options: DownloadOptions, has_ffmpeg: bool) -> dict[str, Any]:
    """Translate the user's quality/format choice into yt-dlp parameters."""
    if options.audio_only:
        if not has_ffmpeg:
            if options.audio_format != "auto":
                raise failure("ffmpeg_missing", "audio conversion requested without FFmpeg")
            return {"format": "ba/b"}
        codec = "best" if options.audio_format == "auto" else options.audio_format
        opts: dict[str, Any] = {
            "format": "ba/b",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "0"}],
        }
        if options.audio_format == "m4a":
            opts["format_sort"] = ["ext:m4a"]
        return opts

    height = options.max_height
    sort: list[str] = [f"res:{height}"] if height else []
    if not has_ffmpeg:
        # Without FFmpeg nothing can be merged: take the best single file that has both streams.
        if options.video_format in ("mp4", "webm"):
            sort.append(f"ext:{options.video_format}")
        return {"format": f"b[height<={height}]/b" if height else "b", "format_sort": sort}

    opts = {"format": "bv*+ba/b"}
    if options.video_format == "mp4":
        sort += ["vcodec:h264", "acodec:aac", "ext:mp4:m4a"]
        opts["merge_output_format"] = "mp4"
    elif options.video_format == "webm":
        sort += ["ext:webm:webm"]
        opts["merge_output_format"] = "webm"
    elif options.video_format == "mkv":
        opts["merge_output_format"] = "mkv"
    opts["format_sort"] = sort
    return opts


def _quality_label(info: dict[str, Any], options: DownloadOptions) -> str:
    if options.audio_only:
        fmt = options.audio_format.upper() if options.audio_format != "auto" else (info.get("ext") or "").upper()
        return f"Audio · {fmt}".strip(" ·")
    height = info.get("height")
    ext = (info.get("ext") or "").upper()
    parts = [f"{height}p" if height else None, ext or None]
    return " · ".join(p for p in parts if p) or options.label()


def _is_audio_only(info: dict[str, Any]) -> bool:
    plan = info.get("requested_formats") or [info]
    return all((f.get("vcodec") or "none") == "none" for f in plan) and any(
        (f.get("acodec") or "none") != "none" for f in plan
    )


class YtDlpProvider:
    name = "ytdlp"

    def __init__(self, bucket: TokenBucket | None = None) -> None:
        self._bucket = bucket
        self._lock = threading.Lock()
        self._extractors: list[Any] | None = None

    # -- extractor matching -------------------------------------------------
    def warm_up(self) -> None:
        """Import yt-dlp's extractors ahead of time (takes a couple of seconds)."""
        try:
            self._load_extractors()
        except Exception:
            log.exception("Could not load yt-dlp extractors")

    def _load_extractors(self) -> list[Any]:
        with self._lock:
            if self._extractors is None:
                from yt_dlp.extractor import gen_extractor_classes

                self._extractors = [ie for ie in gen_extractor_classes() if ie.ie_key() != "Generic"]
            return self._extractors

    def match(self, url: str) -> SiteMatch | None:
        for ie in self._load_extractors():
            try:
                if ie.suitable(url):
                    name = getattr(ie, "IE_NAME", ie.ie_key())
                    return SiteMatch(
                        extractor=ie.ie_key(), label=pretty_extractor(name), playlist_hint=extractor_is_playlist(name)
                    )
            except Exception:  # a broken extractor regex must not break matching
                log.debug("Extractor %s failed to match", ie.ie_key(), exc_info=True)
        return None

    # -- options --------------------------------------------------------------
    def _base_options(self, settings: Settings, logger: _Logger) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "logger": logger,
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "color": {"stdout": "no_color", "stderr": "no_color"},
            "socket_timeout": 20,
            "retries": 5,
            "fragment_retries": 10,
            "extractor_retries": 2,
            "file_access_retries": 3,
            "concurrent_fragment_downloads": 4,
            "continuedl": True,
            "updatetime": False,
            "windowsfilenames": False,
            "trim_file_name": 180,
            "check_formats": None,
        }
        ffmpeg = binaries.find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = str(ffmpeg.parent)
        runtime = binaries.find_js_runtime()
        if runtime:
            opts["js_runtimes"] = {runtime.name: {"path": str(runtime.path)}}
        if settings.cookies_from_browser:
            opts["cookiesfrombrowser"] = (settings.cookies_from_browser,)
        return opts

    @staticmethod
    def _wrap_error(exc: BaseException, token: CancelToken | None = None) -> BaseException:
        if token is not None and token.stopped:
            return JobStopped(token.reason or StopReason.CANCEL)
        if isinstance(exc, DownloadFailure | JobStopped):
            return exc
        if isinstance(exc, _Stopped):
            return JobStopped(StopReason.CANCEL)
        if isinstance(exc, DownloadError | ExtractorError):
            message = str(exc)
            if "cookie" in message.lower() and ("database" in message.lower() or "could not" in message.lower()):
                return failure(
                    "login_required",
                    message,
                    title="Couldn't read browser sign-in",
                    message="SwiftDrop couldn't read cookies from the selected browser.",
                    hint="Quit that browser and retry. For Safari, allow SwiftDrop Full Disk Access in "
                    "System Settings → Privacy & Security, or turn off “Use browser sign-in”.",
                )
            return DownloadFailure(classify_message(message))
        return DownloadFailure(classify_exception(exc))

    # -- inspect --------------------------------------------------------------
    def inspect(self, url: str, token: CancelToken, settings: Settings) -> InspectResult:
        token.raise_if_stopped()
        logger = _Logger("inspect")
        opts = self._base_options(settings, logger)
        opts.update(
            {
                "skip_download": True,
                "extract_flat": "in_playlist",
                "noplaylist": False,
                "playlistend": MAX_PLAYLIST_ENTRIES,
                "lazy_playlist": False,
            }
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise self._wrap_error(exc, token) from exc
        token.raise_if_stopped()
        if not isinstance(info, dict):
            raise failure("unsupported", "no information returned")
        extractor = pretty_extractor(info.get("extractor") or info.get("extractor_key"))
        if info.get("_type") in ("playlist", "multi_video") or info.get("entries") is not None:
            if extractor == "Web page":
                extractor = "Feed"
            return self._playlist_result(info, extractor)
        heights = sorted(
            {
                int(f["height"])
                for f in info.get("formats") or []
                if f.get("height") and (f.get("vcodec") or "none") != "none"
            }
        )
        plan = info.get("requested_formats") or [info]
        sizes = [f.get("filesize") or f.get("filesize_approx") for f in plan]
        size = sum(sizes) if sizes and all(sizes) else None
        estimate = any(not f.get("filesize") for f in plan)
        audio_only = _is_audio_only(info)
        kind = MediaKind.AUDIO if audio_only else MediaKind.VIDEO
        if not heights and not audio_only and kind_for_extension(info.get("ext") or "") == MediaKind.IMAGE:
            kind = MediaKind.IMAGE
        return InspectResult(
            provider=self.name,
            title=info.get("title") or info.get("id") or "",
            kind=kind,
            extractor=extractor,
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            size=size,
            size_is_estimate=estimate,
            heights=heights,
            has_audio_only=any((f.get("vcodec") or "none") == "none" for f in info.get("formats") or []),
            resolved_url=info.get("webpage_url") or url,
        )

    def _playlist_result(self, info: dict[str, Any], extractor: str) -> InspectResult:
        entries: list[PlaylistEntry] = []
        for index, entry in enumerate(info.get("entries") or [], start=1):
            if len(entries) >= MAX_PLAYLIST_ENTRIES:
                break
            if not isinstance(entry, dict):
                continue
            entry_url = entry.get("url") or entry.get("webpage_url") or ""
            if entry_url and "://" not in entry_url and entry.get("webpage_url"):
                entry_url = entry["webpage_url"]
            title = entry.get("title") or entry.get("id") or f"Item {index}"
            nested = entry.get("_type") == "playlist"
            available = (
                entry_url.startswith(("http://", "https://"))
                and not nested
                and title.lower() not in _UNAVAILABLE_TITLES
                and entry.get("availability") not in ("private", "premium_only", "subscriber_only")
            )
            thumbs = entry.get("thumbnails") or []
            thumbnail = entry.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
            entries.append(
                PlaylistEntry(
                    id=str(entry.get("id") or index),
                    url=entry_url,
                    title=f"{title} (playlist)" if nested else title,
                    index=entry.get("playlist_index") or index,
                    duration=entry.get("duration"),
                    thumbnail=thumbnail,
                    available=available,
                )
            )
        # Entry ids must be unique for selection to work.
        seen: set[str] = set()
        for entry in entries:
            if entry.id in seen:
                entry.id = f"{entry.id}-{entry.index}"
            seen.add(entry.id)
        thumbs = info.get("thumbnails") or []
        thumbnail = info.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
        if not thumbnail:
            thumbnail = next((e.thumbnail for e in entries if e.thumbnail), None)
        total = info.get("playlist_count")
        return InspectResult(
            provider=self.name,
            title=info.get("title") or info.get("id") or "Playlist",
            kind=MediaKind.VIDEO,
            extractor=extractor,
            thumbnail=thumbnail,
            is_playlist=True,
            entries=entries,
            entries_truncated=bool(total and total > len(entries)) or len(entries) >= MAX_PLAYLIST_ENTRIES,
            resolved_url=info.get("webpage_url"),
        )

    # -- download ---------------------------------------------------------------
    def download(self, ctx: JobContext) -> DownloadOutcome:
        token = ctx.token
        token.raise_if_stopped()
        logger = _Logger(ctx.job_id)
        settings = ctx.settings
        has_ffmpeg = binaries.find_ffmpeg() is not None
        opts = self._base_options(settings, logger)
        opts.update(format_options(ctx.options, has_ffmpeg))
        opts.update(
            {
                "noplaylist": True,
                "paths": {"home": str(ctx.staging_dir), "temp": str(ctx.staging_dir)},
                "outtmpl": {"default": "%(title).200B.%(ext)s"},
                "overwrites": False,
            }
        )
        if self._bucket is not None and self._bucket.rate > 0:
            opts["ratelimit"] = max(16 * 1024, self._bucket.rate // max(1, settings.max_concurrent))
        tracker = _ProgressTracker(ctx)
        opts["progress_hooks"] = [tracker.on_progress]
        opts["postprocessor_hooks"] = [tracker.on_postprocess]

        ctx.report(ProgressUpdate(phase="Fetching media information"))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(ctx.url, download=False)
                token.raise_if_stopped()
                if not isinstance(info, dict):
                    raise failure("unsupported", "no information returned")
                if info.get("_type") in ("playlist", "multi_video"):
                    raise failure(
                        "unsupported",
                        "link resolved to a playlist",
                        title="This link is a playlist",
                        message="Playlists are expanded on the New Download screen.",
                        hint="Add the link there again to choose which items to download.",
                        retryable=False,
                    )
                tracker.plan(info)
                ctx.set_info(
                    title=info.get("title") or None,
                    thumbnail=info.get("thumbnail"),
                    duration=info.get("duration"),
                    extractor=pretty_extractor(info.get("extractor") or info.get("extractor_key")),
                    quality_label=_quality_label(info, ctx.options),
                    kind=MediaKind.AUDIO if ctx.options.audio_only or _is_audio_only(info) else MediaKind.VIDEO,
                )
                ctx.checkpoint()
                result = ydl.process_ie_result(info, download=True)
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise self._wrap_error(exc, token) from exc

        token.raise_if_stopped()
        downloads = (result or {}).get("requested_downloads") or []
        filepath = downloads[0].get("filepath") or downloads[0].get("_filename") if downloads else None
        if not filepath or not Path(filepath).exists():
            detail = "; ".join(logger.warnings[-3:]) or "yt-dlp reported success but no file was produced"
            raise failure("unknown", detail)
        path = Path(filepath)
        size = path.stat().st_size
        if ctx.options.audio_only or _is_audio_only(result):
            kind = MediaKind.AUDIO
        else:
            by_ext = kind_for_extension(path.suffix.lstrip("."))
            kind = by_ext if by_ext not in (MediaKind.UNKNOWN, MediaKind.OTHER) else MediaKind.VIDEO
        ctx.report(ProgressUpdate(phase="Saving", processing=True))
        final = ctx.finalize(path, path.name, kind)
        return DownloadOutcome(filepath=final, size=size, kind=kind)


class _ProgressTracker:
    """Combines yt-dlp's per-stream hook calls into one honest overall progress."""

    def __init__(self, ctx: JobContext) -> None:
        self._ctx = ctx
        self._throttle = Throttle(0.25)
        self._format_ids: list[str] = []
        self._kinds: list[str] = []
        self._planned_sizes: list[int | None] = []
        self._final_sizes: dict[int, int] = {}
        self._current = 0

    def plan(self, info: dict[str, Any]) -> None:
        plan = info.get("requested_formats") or [info]
        self._format_ids = [str(f.get("format_id")) for f in plan]
        self._kinds = ["video" if (f.get("vcodec") or "none") != "none" else "audio" for f in plan]
        self._planned_sizes = [f.get("filesize") or f.get("filesize_approx") for f in plan]

    def _index(self, info: dict[str, Any]) -> int:
        format_id = str(info.get("format_id"))
        if format_id in self._format_ids:
            return self._format_ids.index(format_id)
        return self._current

    def on_progress(self, d: dict[str, Any]) -> None:
        ctx = self._ctx
        if ctx.token.stopped:
            raise _Stopped()
        status = d.get("status")
        index = self._index(d.get("info_dict") or {})
        self._current = index
        parts = max(1, len(self._format_ids))
        if status == "finished":
            self._final_sizes[index] = int(d.get("total_bytes") or d.get("downloaded_bytes") or 0)
            return
        if status != "downloading" or not self._throttle.ready():
            return
        current_total = d.get("total_bytes")
        estimate = current_total is None
        if current_total is None:
            current_total = d.get("total_bytes_estimate")
        downloaded_part = int(d.get("downloaded_bytes") or 0)

        totals: list[float | None] = []
        for i in range(parts):
            if i in self._final_sizes:
                totals.append(self._final_sizes[i])
            elif i == index:
                totals.append(current_total)
            else:
                planned = self._planned_sizes[i] if i < len(self._planned_sizes) else None
                totals.append(planned)
                if planned is not None:
                    estimate = True
        done_before = sum(self._final_sizes.get(i, 0) for i in range(index))
        downloaded = done_before + downloaded_part
        total = int(sum(t for t in totals if t)) if all(totals) else None
        speed = d.get("speed")
        progress: float | None
        eta: float | None
        if total:
            progress = min(1.0, downloaded / total)
            eta = (total - downloaded) / speed if speed else None
        else:
            frag_index, frag_count = d.get("fragment_index"), d.get("fragment_count")
            progress = (frag_index / frag_count) if frag_index and frag_count else None
            eta = d.get("eta")
        label = self._kinds[index] if index < len(self._kinds) else "media"
        phase = f"Downloading {label} ({index + 1}/{parts})" if parts > 1 else "Downloading"
        ctx.report(
            ProgressUpdate(
                downloaded=downloaded,
                total=total,
                total_is_estimate=bool(total) and estimate,
                speed=float(speed) if speed else None,
                eta=float(eta) if eta is not None else None,
                progress=progress,
                phase=phase,
            )
        )

    def on_postprocess(self, d: dict[str, Any]) -> None:
        if self._ctx.token.stopped and d.get("status") == "started":
            raise _Stopped()
        if d.get("status") != "started":
            return
        name = str(d.get("postprocessor") or "")
        phase = _PP_PHASES.get(name) or next((v for k, v in _PP_PHASES.items() if k in name), "Processing")
        self._ctx.report(ProgressUpdate(phase=phase, processing=True))
