"""Multi-connection (segmented) downloads for direct files served with byte ranges.

The file is pre-allocated as ``<part>.seg`` and split into N ranges. Each worker thread
fetches a range with ``Range`` + ``If-Range`` and writes it with ``os.pwrite`` through its
own file descriptor. A worker that runs out of work takes over the unwritten second half
of the largest remaining range (as long as both halves stay >= ``min_segment``), so one
slow connection can't hold the whole download back.

Every response is validated: status 206, ``Content-Range`` starting at the requested
byte with the expected total, no ``Content-Encoding`` and an unchanged validator. Any
mismatch means ranges can't be trusted for this file: the ``.seg`` file is deleted,
``state["segments"]`` is cleared and :class:`SegmentedUnavailable` tells the caller to
start from zero with :class:`~swiftdrop.engine.http.HttpDownloader`.
"""

from __future__ import annotations

import collections
import contextlib
import os
import random
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict
from urllib3.exceptions import HTTPError as Urllib3Error
from urllib3.exceptions import ReadTimeoutError

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.connpool import ConnectionPool
from swiftdrop.engine.http import (
    _CONTENT_RANGE_RE,
    DEFAULT_USER_AGENT,
    RETRYABLE_STATUS,
    HttpDownloader,
    HttpProbe,
    HttpResult,
    ProgressFn,
    _check_disk_space,
    _hash_file,
    _int_header,
    _parse_retry_after,
    _usable_validator,
)
from swiftdrop.engine.progress import ProgressUpdate, SpeedMeter
from swiftdrop.engine.segmap import _Halted, _Job, _Segment
from swiftdrop.engine.stall import StallDetector
from swiftdrop.errors import DownloadFailure, classify_exception, classify_http_status, failure
from swiftdrop.logging_setup import get_logger
from swiftdrop.ratelimit import TokenBucket

log = get_logger("segmented")

SNAPSHOT_EVERY = 2.0  # seconds between published segment maps
BLOCK = 256 * 1024  # largest write; a worker may write one block past its recorded position
READ = 64 * 1024  # read size; workers check for stop, range changes and stalls between reads
MAX_RETRIES = 6  # consecutive failed attempts on one range before the download fails
_TRANSIENT = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError, Urllib3Error)
# Windows opens os.open() files in text mode (LF -> CRLF on write) unless O_BINARY is set.
_O_BINARY: int = getattr(os, "O_BINARY", 0)
# Windows can only fsync (FlushFileBuffers) a handle opened for writing.
_O_SYNC_FLAGS = os.O_WRONLY | _O_BINARY if sys.platform == "win32" else os.O_RDONLY


def _pwrite(fd: int, data: memoryview, offset: int) -> int:
    """``os.pwrite``; Windows has none, so seek + write there (safe: every worker owns its fd)."""
    if sys.platform == "win32":
        os.lseek(fd, offset, os.SEEK_SET)
        return os.write(fd, data)
    return os.pwrite(fd, data, offset)


class SegmentedUnavailable(Exception):
    """Use ``HttpDownloader`` instead. The ``.seg`` file and ``state["segments"]`` are already cleared."""


class _Mismatch(Exception):
    """A response shows the server can't be trusted with ranges, or the file changed."""


class _Retry(Exception):
    def __init__(self, reason: str, *, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.status = status
        self.retry_after = retry_after


class _Rescue(Exception):
    """This connection stalled: close it and reopen the remaining range on a new session."""


class SegmentedDownloader:
    def __init__(
        self,
        *,
        connections: int = 4,
        pool: ConnectionPool | None = None,
        bucket: TokenBucket | None = None,
        session_factory: Callable[[], requests.Session] | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        min_size: int = 4 * 1024 * 1024,
        min_segment: int = 1024 * 1024,
        connect_timeout: float = 15.0,
        read_timeout: float = 30.0,
    ) -> None:
        self.connections = max(1, min(16, int(connections)))
        self.pool = pool
        self.bucket = bucket
        self.user_agent = user_agent
        self.min_size = min_size
        self.min_segment = max(1, min_segment)
        self._session_factory = session_factory or HttpDownloader._default_session
        self.detector = StallDetector()
        self.shed_403 = True
        self.last_stats: dict[str, int] = {"rescues": 0, "min_connections": 0, "max_connections": 0}
        self._conn_ids = 0
        self._ids_lock = threading.Lock()
        # An idle connection is replaced after `idle` seconds: that is the socket read timeout.
        self.timeout = (connect_timeout, min(read_timeout, self.detector.idle))

    def _headers(self, extra: dict[str, str] | None, ranges: dict[str, str]) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        headers.update(extra or {})
        headers["Accept-Encoding"] = "identity"  # byte ranges must address the stored bytes
        headers.update(ranges)
        return headers

    # ------------------------------------------------------------------
    def probe(
        self,
        url: str,
        token: CancelToken,
        *,
        headers: dict[str, str] | None = None,
        cookies: RequestsCookieJar | None = None,
    ) -> HttpProbe:
        """1-byte ranged GET: does the server serve ranges, how big is the file, what validates it."""
        if self.pool is not None:
            while not self.pool.acquire(token, timeout=0.25):
                token.raise_if_stopped()
        try:
            return self._probe(url, token, headers, cookies)
        finally:
            if self.pool is not None:
                self.pool.release()

    def _probe(
        self, url: str, token: CancelToken, headers: dict[str, str] | None, cookies: RequestsCookieJar | None
    ) -> HttpProbe:
        session = self._session_factory()
        attempt = 0
        try:
            while True:
                token.raise_if_stopped()
                try:
                    with session.get(
                        url,
                        headers=self._headers(headers, {"Range": "bytes=0-0"}),
                        cookies=cookies,
                        stream=True,
                        timeout=self.timeout,
                        allow_redirects=True,
                    ) as resp:
                        status = resp.status_code
                        if status in RETRYABLE_STATUS and attempt < 2:
                            attempt += 1
                            _pause(token, _backoff(attempt, _parse_retry_after(resp.headers.get("Retry-After"))))
                            continue
                        if status >= 400 and status != 416:
                            raise DownloadFailure(classify_http_status(status, f"HTTP {status}"))
                        return _to_probe(resp)
                except _TRANSIENT as exc:
                    attempt += 1
                    if attempt > 2:
                        raise DownloadFailure(classify_exception(exc)) from exc
                    _pause(token, _backoff(attempt, None))
                except requests.RequestException as exc:
                    raise DownloadFailure(classify_exception(exc)) from exc
        finally:
            session.close()

    def eligible(self, probe: HttpProbe) -> bool:
        size = probe.content_length
        return probe.status == 206 and probe.accept_ranges and size is not None and size >= self.min_size

    # ------------------------------------------------------------------
    def download(
        self,
        url: str,
        part_path: Path,
        token: CancelToken,
        on_progress: ProgressFn,
        state: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        cookies: RequestsCookieJar | None = None,
        reject_html: bool = True,
        allow_unvalidated_resume: bool = False,
    ) -> HttpResult:
        """Download ``url`` over several connections into ``part_path`` (via ``<part>.seg``).

        Raises :class:`SegmentedUnavailable` when the server can't do it, after cleaning up.
        On stop the ``.seg`` file is kept.
        """
        self.last_stats = {"rescues": 0, "min_connections": 0, "max_connections": 0}
        seg_path = part_path.with_suffix(part_path.suffix + ".seg")
        probe = self.probe(url, token, headers=headers, cookies=cookies)
        if reject_html and probe.is_html:
            raise failure("not_media", f"Content-Type: {probe.content_type}")
        size = probe.content_length if self.eligible(probe) else None
        if size is None:
            _discard(seg_path, state)
            raise SegmentedUnavailable(f"not eligible (HTTP {probe.status}, size {probe.content_length})")
        # Naming fields only: the resume validators (etag/last_modified) stay HttpDownloader's own.
        state.update(
            final_url=probe.url,
            content_type=probe.content_type,
            content_disposition=probe.content_disposition,
            total=size,
            accept_ranges=True,
        )
        etag = _usable_validator(probe.etag)
        validator = etag or probe.last_modified
        resumed = _resume_map(seg_path, size, validator, state, unvalidated=allow_unvalidated_resume)
        if resumed is None:
            self._allocate(seg_path, size, state)
            state["seg_validator"] = validator
            state["seg_size"] = size
            state["segments"] = ()  # the key exists from the start, so later updates never resize the dict
            count = max(1, min(self.connections, size // self.min_segment))
            bounds = [size * i // count for i in range(count + 1)]
            segments = [_Segment(bounds[i], bounds[i + 1] - 1) for i in range(count)]
        else:
            segments = resumed
            log.info("Resuming segmented download: %d of %d bytes present", sum(x.written for x in segments), size)
            count = max(1, min(self.connections, size // self.min_segment))
        check = ("ETag", etag) if etag else ("Last-Modified", probe.last_modified) if probe.last_modified else None
        job = _Job(
            url=url,
            seg_path=seg_path,
            size=size,
            headers=dict(headers or {}),
            cookies=cookies,
            validator=validator,
            check=check,
            reject_html=reject_html,
            token=token,
            split_floor=max(self.min_segment, BLOCK),
            segments=segments,
            shed_403=self.shed_403,
            target=count,
        )
        meter = SpeedMeter()
        already = job.stats()[0]
        on_progress(
            ProgressUpdate(
                downloaded=already, total=size, progress=already / size, phase="Downloading", connections=count
            )
        )
        meter.update(already)
        try:
            self._run(job, count, on_progress, state, meter)
        finally:
            state["segments"] = job.snapshot()  # on stop or failure the map lets the next run resume
            self.last_stats = {
                "rescues": job.rescues,
                "min_connections": job.min_target,
                "max_connections": job.max_connections,
            }

        if isinstance(job.error, _Mismatch):
            _discard(seg_path, state)
            log.info("Segmented download unavailable (%s); falling back", job.error)
            raise SegmentedUnavailable(str(job.error)) from job.error
        complete = job.error is None and job.complete()
        if token.stopped and not complete:  # a stop after the last byte still finishes the file
            raise JobStopped(token.reason or StopReason.CANCEL)
        if isinstance(job.error, OSError | Urllib3Error):
            raise DownloadFailure(classify_exception(job.error)) from job.error
        if job.error is not None:
            raise job.error
        try:
            if not complete or seg_path.stat().st_size != size:
                _discard(seg_path, state)
                raise failure("integrity", "segment map incomplete after all workers finished")
            digest = _hash_file(seg_path)
            os.replace(seg_path, part_path)
        except OSError as exc:
            raise DownloadFailure(classify_exception(exc)) from exc
        for key in ("segments", "seg_validator", "seg_size"):
            state.pop(key, None)
        on_progress(ProgressUpdate(downloaded=size, total=size, progress=1.0, speed=meter.speed, eta=0))
        return HttpResult(probe.url, size, probe.content_type, probe.content_disposition, digest, False)

    def _allocate(self, seg_path: Path, size: int, state: dict[str, Any]) -> None:
        try:
            _check_disk_space(seg_path.parent, size)
            fd = os.open(seg_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_BINARY, 0o666)  # umask applies
            try:
                os.ftruncate(fd, size)
            finally:
                os.close(fd)
        except DownloadFailure:
            _discard(seg_path, state)
            raise
        except OSError as exc:
            _discard(seg_path, state)
            raise DownloadFailure(classify_exception(exc)) from exc

    def _run(
        self, job: _Job, count: int, on_progress: ProgressFn, state: dict[str, Any], meter: SpeedMeter
    ) -> None:
        """Run the workers and report progress from this (the caller's) thread until all exit."""
        threads: list[threading.Thread] = []  # only started threads, so the finally can join them all
        try:
            for i in range(count):
                thread = threading.Thread(target=self._worker, args=(job,), name=f"segment-{i}", daemon=True)
                thread.start()
                threads.append(thread)
            next_snapshot = time.monotonic() + SNAPSHOT_EVERY
            while alive := [t for t in threads if t.is_alive()]:
                if job.token.stopped:
                    job.halt.set()
                alive[0].join(0.25)
                if time.monotonic() >= next_snapshot:
                    next_snapshot = time.monotonic() + SNAPSHOT_EVERY
                    self._publish(job, state)
                if job.halt.is_set():
                    continue
                done, connections = job.stats()
                speed = meter.update(done)
                on_progress(
                    ProgressUpdate(
                        downloaded=done,
                        total=job.size,
                        speed=speed,
                        eta=meter.eta(done, job.size),
                        progress=done / job.size,
                        connections=connections or None,
                    )
                )
        except BaseException:
            job.halt.set()
            raise
        finally:
            for thread in threads:
                thread.join()

    def _publish(self, job: _Job, state: dict[str, Any]) -> None:
        """Flush the file, then publish the map (by assignment only: the queue copies ``state`` unlocked)."""
        snapshot = job.snapshot()
        try:
            fd = os.open(job.seg_path, _O_SYNC_FLAGS)
            try:
                os.fsync(fd)  # what the map says is written must survive a crash
            finally:
                os.close(fd)
        except OSError:
            return
        state["segments"] = snapshot

    def _worker(self, job: _Job) -> None:
        acquired = False
        try:
            if self.pool is not None:
                while not self.pool.acquire(job.token, timeout=0.25):
                    if job.halt.is_set() or job.token.stopped or not job.has_work():
                        return
                acquired = True
            fd = os.open(job.seg_path, os.O_WRONLY | _O_BINARY)
            try:
                conn = _Conn(self._session_factory())
                job.opened(1)
                left = False
                try:
                    while not (left := job.leave_if_excess()) and (seg := job.claim()) is not None:
                        self._fetch(job, conn, fd, seg)
                finally:
                    if not left:
                        job.opened(-1)
                    conn.session.close()
            finally:
                os.close(fd)
        except _Halted:
            pass
        except BaseException as exc:
            job.fail(exc)
        finally:
            if acquired and self.pool is not None:
                self.pool.release()

    def _fetch(self, job: _Job, conn: _Conn, fd: int, seg: _Segment) -> None:
        """Fetch ``seg`` until its (possibly shrinking) range is written, retrying transient errors."""
        attempt = 0
        while True:
            pos, end = job.span(seg)
            if pos > end:
                return
            job.ensure_running()
            ranges = {"Range": f"bytes={pos}-{end}"}
            if job.validator:
                ranges["If-Range"] = job.validator
            try:
                with conn.session.get(
                    job.url,
                    headers=self._headers(job.headers, ranges),
                    cookies=job.cookies,
                    stream=True,
                    timeout=self.timeout,
                    allow_redirects=True,
                ) as resp:
                    _validate(job, resp, pos)
                    self._stream(job, seg, resp, fd)
            except _Rescue:
                # The response is closed by the `with`; replace the whole session (new socket) and
                # carry on with what is left of the range. Not a failure: no attempt is counted.
                conn.session.close()
                job.ensure_running()
                conn.session = self._session_factory()
            except (_Retry, *_TRANSIENT) as exc:
                if job.span(seg)[0] > pos:
                    attempt = 0  # this attempt made progress; only count consecutive failures
                attempt += 1
                retry = exc if isinstance(exc, _Retry) else None
                if retry is not None and retry.status in (403, 429, 503):
                    job.shed()
                if attempt > MAX_RETRIES:
                    if retry is not None and retry.status is not None:
                        raise DownloadFailure(classify_http_status(retry.status, str(exc))) from exc
                    raise DownloadFailure(classify_exception(exc)) from exc
                delay = _backoff(attempt, retry.retry_after if retry is not None else None)
                reason = str(exc) if retry is not None else type(exc).__name__  # no URLs in the log
                log.info("Range %d-%d: %s; retry %d/%d in %.1fs", pos, end, reason, attempt, MAX_RETRIES, delay)
                if job.halt.wait(delay):
                    raise _Halted from exc

    def _stream(self, job: _Job, seg: _Segment, resp: requests.Response, fd: int) -> None:
        with self._ids_lock:
            self._conn_ids += 1
            conn_id = self._conn_ids
        started = time.monotonic()
        samples: collections.deque[tuple[float, int]] = collections.deque([(started, 0)])
        total = 0
        while True:
            pos, end = job.span(seg)
            if pos > end:
                return  # done, or another worker took over the rest of this range
            job.ensure_running()
            try:
                data = resp.raw.read(min(READ, end - pos + 1), decode_content=False)
            except ReadTimeoutError as exc:
                if job.allow_rescue():
                    log.info("Range %d-%d: idle for %.0fs; reopening", pos, end, self.detector.idle)
                    raise _Rescue from exc
                raise
            if not data:
                raise _Retry("connection closed before the range was complete")
            if self.bucket is not None:
                self.bucket.consume(len(data), job.token)
            length = job.writable(seg, pos, len(data))
            view = memoryview(data)[:length]
            offset = pos
            while view:
                written = _pwrite(fd, view, offset)
                view, offset = view[written:], offset + written
            job.record(seg, length)
            total += length
            if self._stalled(job, conn_id, samples, started, total):
                _log_peer(resp)
                raise _Rescue

    def _stalled(
        self, job: _Job, conn_id: int, samples: collections.deque[tuple[float, int]], started: float, total: int
    ) -> bool:
        now = time.monotonic()
        samples.append((now, total))
        while now - samples[0][0] > 30.0 and len(samples) > 2:
            samples.popleft()
        then, then_total = next((s for s in samples if now - s[0] <= self.detector.window), samples[-1])
        rate = (total - then_total) / max(now - then, 0.05)  # a tiny span can't claim an absurd rate
        median = job.publish_rate(conn_id, rate, now)
        if now - started < self.detector.window:
            return False  # a young connection has not had its full window yet
        oldest = samples[0]
        span = now - oldest[0]
        own_avg = (total - oldest[1]) / span if span >= self.detector.window else None
        if not self.detector.should_rescue(idle_for=0.0, rate=rate, peer_median=median, own_avg_30s=own_avg):
            return False
        if not job.allow_rescue():
            return False
        job.forget_rate(conn_id)
        log.info("Connection %d stalled at %.0f kB/s; reopening", conn_id, rate / 1000)
        return True


@dataclass(eq=False)
class _Conn:
    """A worker's current session; a rescue swaps it for a fresh one."""

    session: requests.Session


def _log_peer(resp: requests.Response) -> None:
    with contextlib.suppress(Exception):  # diagnostics only, never worth failing a download
        log.debug("Stalled peer: %s", resp.raw._connection.sock.getpeername())


def _validate(job: _Job, resp: requests.Response, pos: int) -> None:
    status = resp.status_code
    headers = resp.headers
    if status in RETRYABLE_STATUS:
        raise _Retry(f"HTTP {status}", status=status, retry_after=_parse_retry_after(headers.get("Retry-After")))
    content_type = headers.get("Content-Type") or ""
    if job.reject_html and status == 200 and "text/html" in content_type.lower():
        raise failure("not_media", f"Content-Type: {content_type}")
    if status == 403 and job.ranged_ok and job.shed_403:
        raise _Retry("HTTP 403 after earlier ranged success", status=403)
    if status >= 400 and status != 416:
        raise DownloadFailure(classify_http_status(status, f"HTTP {status} for {resp.url}"))
    if status != 206:
        raise _Mismatch(f"HTTP {status} instead of 206")
    raw_range = headers.get("Content-Range", "")
    match = _CONTENT_RANGE_RE.search(raw_range)
    if not match or int(match.group(1)) != pos or match.group(3) != str(job.size):
        raise _Mismatch(f"Content-Range {raw_range!r} for bytes {pos}- of {job.size}")
    if _encoded(headers):
        raise _Mismatch(f"Content-Encoding {headers.get('Content-Encoding')!r} on a range")
    if job.check is not None and headers.get(job.check[0]) != job.check[1]:
        raise _Mismatch(f"{job.check[0]} changed during the download")
    job.ranged_ok = True


def _to_probe(resp: requests.Response) -> HttpProbe:
    headers = resp.headers
    encoded = _encoded(headers)
    total = None
    if resp.status_code == 206:
        match = _CONTENT_RANGE_RE.search(headers.get("Content-Range", ""))
        if match and match.group(3) != "*":
            total = int(match.group(3))
        accept_ranges = not encoded
    else:
        accept_ranges = headers.get("Accept-Ranges", "").lower() == "bytes" and not encoded
        total = None if encoded else _int_header(headers.get("Content-Length"))
    return HttpProbe(
        url=resp.url,
        status=resp.status_code,
        content_type=headers.get("Content-Type"),
        content_length=total,
        content_disposition=headers.get("Content-Disposition"),
        accept_ranges=accept_ranges,
        etag=headers.get("ETag"),
        last_modified=headers.get("Last-Modified"),
    )


def _encoded(headers: CaseInsensitiveDict[str]) -> bool:
    encoding = headers.get("Content-Encoding", "").strip().lower()
    return bool(encoding) and encoding != "identity"


def _discard(seg_path: Path, state: dict[str, Any]) -> None:
    """Forget a segmented attempt so nothing of it can leak into a single-connection fallback."""
    try:
        seg_path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Couldn't delete %s: %s", seg_path.name, exc)
    for key in ("segments", "seg_validator", "seg_size"):
        state.pop(key, None)


def _resume_map(
    seg_path: Path, size: int, validator: str | None, state: dict[str, Any], *, unvalidated: bool = False
) -> list[_Segment] | None:
    """Rebuild the segment map from ``state`` when it still describes this file, else None (start clean).

    ``unvalidated`` lets a caller that knows the content is the same (a refreshed link to the same
    stream) resume when the server offers no ETag / Last-Modified; the size must still match.
    """
    raw = state.get("segments")
    if not raw or state.get("seg_size") != size:
        return None
    if (validator is None or state.get("seg_validator") != validator) and not unvalidated:
        return None
    try:
        if seg_path.stat().st_size != size:
            return None
        segments = [_Segment(int(a), int(b), int(w)) for a, b, w in raw]
    except (OSError, TypeError, ValueError):
        return None
    expected = 0
    for seg in sorted(segments, key=lambda x: x.start):
        if seg.start != expected or seg.end < seg.start or not 0 <= seg.written <= seg.end - seg.start + 1:
            return None
        expected = seg.end + 1
    return segments if expected == size else None


def _backoff(attempt: int, retry_after: float | None) -> float:
    # Same schedule as HttpDownloader's defaults (base 1 s, cap 30 s, Retry-After capped at 60 s).
    if retry_after is not None:
        return min(60.0, retry_after)
    return min(30.0, 2.0 ** max(0, attempt - 1)) + random.uniform(0, 0.5)  # noqa: S311 - jitter, not crypto


def _pause(token: CancelToken, seconds: float) -> None:
    if token.wait(seconds):
        raise JobStopped(token.reason or StopReason.CANCEL)
