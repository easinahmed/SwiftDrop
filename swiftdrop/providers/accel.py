"""Accelerated downloads for yt-dlp formats that are plain HTTP(S) files.

Instead of yt-dlp's single-connection downloader the streams of the chosen format go through
:class:`~swiftdrop.engine.segmented.SegmentedDownloader` side by side, with one combined,
size-weighted progress. Signed links (YouTube) expire: a 403/410 triggers up to two link
refreshes, after which the segment map resumes where it stopped.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from requests.cookies import RequestsCookieJar

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.progress import ProgressUpdate
from swiftdrop.engine.segmented import SegmentedDownloader
from swiftdrop.errors import DownloadFailure, failure
from swiftdrop.logging_setup import get_logger
from swiftdrop.providers.base import JobContext

log = get_logger("accel")

MAX_REFRESHES = 2
EXPIRED_MESSAGE = "YouTube stopped serving this video, try again later"
_PLAIN_PROTOCOLS = frozenset({"http", "https"})
_EXPIRED_CODES = ("forbidden", "expired")  # HTTP 403 / 410


def accelerated_plan(info: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The requested formats when every one is a plain HTTP(S) file with a URL, else None."""
    plan = info.get("requested_formats") or [info]
    if all(f.get("protocol") in _PLAIN_PROTOCOLS and f.get("url") for f in plan):
        return list(plan)
    return None


def _size(fmt: dict[str, Any]) -> int | None:
    value = fmt.get("filesize") or fmt.get("filesize_approx")
    return int(value) if isinstance(value, int | float) and value > 0 else None


def _is_video(fmt: dict[str, Any]) -> bool:
    return (fmt.get("vcodec") or "none") != "none"


class _Combined:
    """One monotonic progress over all streams, weighted by size."""

    def __init__(self, ctx: JobContext, plan: list[dict[str, Any]]) -> None:
        self._ctx = ctx
        self._lock = threading.Lock()
        self._kinds = ["video" if _is_video(f) else "audio" for f in plan]
        self._totals: list[int | None] = [_size(f) for f in plan]
        self._done = [0] * len(plan)
        self._speed: list[float] = [0.0] * len(plan)
        self._last = 0.0

    def update(self, index: int, update: ProgressUpdate) -> None:
        with self._lock:
            if update.downloaded is not None:
                self._done[index] = max(self._done[index], update.downloaded)
                self._speed[index] = update.speed or 0.0
            if update.total:
                self._totals[index] = update.total
            known = all(t is not None for t in self._totals)
            total = sum(t or 0 for t in self._totals) if known else None
            done = sum(self._done)
            speed = sum(self._speed)
            pending = next((i for i, t in enumerate(self._totals) if t is None or self._done[i] < t), 0)
            phase = f"Downloading {self._kinds[pending]}"
            progress = None
            if total:
                progress = self._last = max(self._last, min(1.0, done / total))
            self._ctx.report(
                ProgressUpdate(
                    downloaded=done,
                    total=total,
                    progress=progress,
                    speed=speed or None,
                    eta=(total - done) / speed if total and speed else None,
                    phase=phase,
                )
            )


def download_streams(
    plan: list[dict[str, Any]],
    ctx: JobContext,
    refresh: Callable[[str], dict[str, Any]],
    downloader_factory: Callable[[], SegmentedDownloader],
    *,
    cookies: RequestsCookieJar | None = None,
) -> list[Path]:
    """Download every stream of ``plan`` concurrently; returns their files in plan order."""
    streams: dict[str, dict[str, Any]] = ctx.meta.setdefault("streams", {})
    for fmt in plan:  # create every state dict first: later changes never resize ``meta`` while it is saved
        streams.setdefault(str(fmt["format_id"]), {})
    combined = _Combined(ctx, plan)
    group = CancelToken()  # stops the siblings when one stream fails
    results: list[Path | None] = [None] * len(plan)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def run(index: int) -> None:
        try:
            results[index] = _download_one(
                index, plan[index], ctx, group, combined, refresh, downloader_factory, cookies
            )
        except BaseException as exc:
            with lock:
                errors.append(exc)
            group.stop(StopReason.CANCEL)

    threads = [threading.Thread(target=run, args=(i,), name=f"stream-{i}", daemon=True) for i in range(len(plan))]
    for thread in threads:
        thread.start()
    try:
        while any(t.is_alive() for t in threads):
            if ctx.token.stopped:
                group.stop(ctx.token.reason or StopReason.CANCEL)
            threads[0].join(0.1)
    finally:
        group.stop(StopReason.CANCEL)
        for thread in threads:
            thread.join()
    if ctx.token.stopped:
        raise JobStopped(ctx.token.reason or StopReason.CANCEL)
    real = [e for e in errors if not isinstance(e, JobStopped)]
    if real:
        raise real[0]
    if errors:
        raise errors[0]
    return [path for path in results if path is not None]


def _new_downloader(factory: Callable[[], SegmentedDownloader], *, shed_403: bool) -> SegmentedDownloader:
    downloader = factory()
    downloader.shed_403 = shed_403
    downloader.min_size = 1  # a short audio stream still goes through (as one connection) next to a big video
    return downloader


def _download_one(
    index: int,
    fmt: dict[str, Any],
    ctx: JobContext,
    token: CancelToken,
    combined: _Combined,
    refresh: Callable[[str], dict[str, Any]],
    downloader_factory: Callable[[], SegmentedDownloader],
    cookies: RequestsCookieJar | None,
) -> Path:
    format_id = str(fmt["format_id"])
    state = ctx.meta["streams"][format_id]
    part = ctx.staging_dir / f"stream-{index}.part"
    downloader = _new_downloader(downloader_factory, shed_403=False)  # a 403 on a signed link means "expired"
    refreshes = 0
    unvalidated = False
    while True:
        try:
            downloader.download(
                fmt["url"],
                part,
                token,
                lambda update: combined.update(index, update),
                state,
                headers=fmt.get("http_headers"),
                cookies=cookies,
                allow_unvalidated_resume=unvalidated,
            )
            return part
        except DownloadFailure as exc:
            if exc.info.code not in _EXPIRED_CODES:
                raise
            if refreshes >= MAX_REFRESHES:
                raise failure(
                    "expired",
                    f"link kept failing after {MAX_REFRESHES} refreshes: {exc.info.detail}",
                    message=EXPIRED_MESSAGE,
                ) from exc
            refreshes += 1
            log.info("Stream %s link expired; refreshing (%d/%d)", format_id, refreshes, MAX_REFRESHES)
            fresh = refresh(format_id)
            old, new = _size(fmt), _size(fresh)
            if old is not None and new is not None and old != new:
                state.pop("segments", None)  # a different file: nothing of the partial one is reusable
                part.with_suffix(part.suffix + ".seg").unlink(missing_ok=True)
            unvalidated = True  # same stream behind a new signature; the segmented size check still applies
            fmt = fresh
            # A fresh downloader: shedding on 403/429/503 applies only if the new link fails too.
            downloader = _new_downloader(downloader_factory, shed_403=True)
