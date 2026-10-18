"""Streaming HTTP(S) downloader with resume, retries and bandwidth limiting.

* Streams to disk in fixed-size chunks — memory use is constant regardless of
  file size.
* Resumes partial files with ``Range`` + ``If-Range`` when the server supports
  it, and restarts cleanly when it doesn't (or the file changed).
* Retries transient failures (connection drops, timeouts, 429/5xx) with
  exponential backoff + jitter, honouring ``Retry-After``.
* Verifies the final size against ``Content-Length`` / ``Content-Range`` and
  computes a SHA-256 of the result.
"""

from __future__ import annotations

import email.utils
import hashlib
import random
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from swiftdrop.appinfo import USER_AGENT_TOKEN
from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.progress import ProgressUpdate, SpeedMeter, Throttle
from swiftdrop.errors import DownloadFailure, classify_exception, classify_http_status, failure
from swiftdrop.logging_setup import get_logger
from swiftdrop.ratelimit import TokenBucket

log = get_logger("http")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    f"Version/18.0 Safari/605.1.15 {USER_AGENT_TOKEN}"
)
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 522, 524})
DISK_HEADROOM = 32 * 1024 * 1024
_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)
_TOTAL_ONLY_RE = re.compile(r"bytes\s+\*/(\d+)", re.IGNORECASE)

ProgressFn = Callable[[ProgressUpdate], None]


class _Incomplete(Exception):
    """Connection ended before the advertised number of bytes arrived."""


@dataclass
class HttpProbe:
    url: str
    status: int
    content_type: str | None
    content_length: int | None
    content_disposition: str | None
    accept_ranges: bool
    etag: str | None
    last_modified: str | None

    @property
    def is_html(self) -> bool:
        ctype = (self.content_type or "").lower()
        return "text/html" in ctype or "application/xhtml" in ctype


@dataclass
class HttpResult:
    final_url: str
    size: int
    content_type: str | None
    content_disposition: str | None
    sha256: str
    resumed: bool


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed.timestamp() - time.time())


def _int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(value.strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def _usable_validator(etag: str | None) -> str | None:
    # Weak ETags must not be used with If-Range (RFC 9110 §13.1.5).
    if etag and not etag.startswith("W/"):
        return etag
    return None


class HttpDownloader:
    def __init__(
        self,
        *,
        bucket: TokenBucket | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        chunk_size: int = 256 * 1024,
        connect_timeout: float = 15.0,
        read_timeout: float = 30.0,
        max_retries: int = 6,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
        retry_after_cap: float = 60.0,
        session_factory: Callable[[], requests.Session] | None = None,
    ) -> None:
        self.bucket = bucket
        self.user_agent = user_agent
        self.chunk_size = chunk_size
        self.timeout = (connect_timeout, read_timeout)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.retry_after_cap = retry_after_cap
        self._session_factory = session_factory or self._default_session

    @staticmethod
    def _default_session() -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.max_redirects = 20
        return session

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        }
        if extra:
            headers.update(extra)
        return headers

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(self.retry_after_cap, retry_after)
        delay = min(self.backoff_max, self.backoff_base * (2 ** max(0, attempt - 1)))
        return delay + random.uniform(0, self.backoff_base * 0.5)  # noqa: S311 - jitter, not crypto

    def _sleep_or_stop(self, token: CancelToken, seconds: float) -> None:
        if token.wait(seconds):
            raise JobStopped(token.reason or StopReason.CANCEL)

    # ------------------------------------------------------------------
    def probe(self, url: str, token: CancelToken) -> HttpProbe:
        """Fetch response headers (via a 1-byte ranged GET) without downloading the body."""
        attempt = 0
        session = self._session_factory()
        try:
            while True:
                token.raise_if_stopped()
                try:
                    with session.get(
                        url,
                        headers=self._headers({"Range": "bytes=0-0"}),
                        stream=True,
                        timeout=self.timeout,
                        allow_redirects=True,
                    ) as resp:
                        if resp.status_code in RETRYABLE_STATUS and attempt < min(2, self.max_retries):
                            attempt += 1
                            self._sleep_or_stop(
                                token, self._backoff(attempt, _parse_retry_after(resp.headers.get("Retry-After")))
                            )
                            continue
                        if resp.status_code >= 400 and resp.status_code != 416:
                            raise DownloadFailure(classify_http_status(resp.status_code, f"HTTP {resp.status_code}"))
                        headers = resp.headers
                        total = None
                        accept_ranges = False
                        if resp.status_code == 206:
                            accept_ranges = True
                            match = _CONTENT_RANGE_RE.search(headers.get("Content-Range", ""))
                            if match and match.group(3) != "*":
                                total = int(match.group(3))
                        else:
                            accept_ranges = headers.get("Accept-Ranges", "").lower() == "bytes"
                            if not headers.get("Content-Encoding"):
                                total = _int_header(headers.get("Content-Length"))
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
                except (JobStopped, DownloadFailure):
                    raise
                except (requests.ConnectionError, requests.Timeout) as exc:
                    attempt += 1
                    if attempt > min(2, self.max_retries):
                        raise DownloadFailure(classify_exception(exc)) from exc
                    self._sleep_or_stop(token, self._backoff(attempt, None))
                except requests.RequestException as exc:
                    raise DownloadFailure(classify_exception(exc)) from exc
        finally:
            session.close()

    # ------------------------------------------------------------------
    def download(
        self,
        url: str,
        part_path: Path,
        token: CancelToken,
        on_progress: ProgressFn,
        state: dict[str, Any],
        *,
        reject_html: bool = True,
    ) -> HttpResult:
        """Download ``url`` into ``part_path``, resuming if possible.

        ``state`` is a persisted scratch dict (``etag``, ``last_modified``,
        ``accept_ranges``…) so resume validators survive app restarts.
        """
        session = self._session_factory()
        meter = SpeedMeter()
        throttle = Throttle(0.25)
        attempt = 0
        resumed_any = False
        try:
            while True:
                token.raise_if_stopped()
                existing = part_path.stat().st_size if part_path.exists() else 0
                extra: dict[str, str] = {}
                if existing > 0 and state.get("accept_ranges") is not False:
                    extra["Range"] = f"bytes={existing}-"
                    validator = _usable_validator(state.get("etag")) or state.get("last_modified")
                    if validator:
                        extra["If-Range"] = validator
                try:
                    result = self._attempt(
                        session,
                        url,
                        part_path,
                        existing,
                        extra,
                        token,
                        on_progress,
                        state,
                        meter,
                        throttle,
                        reject_html,
                    )
                    result.resumed = result.resumed or resumed_any
                    return result
                except (JobStopped, DownloadFailure):
                    raise
                except _RetryableStatus as exc:
                    attempt += 1
                    if attempt > self.max_retries:
                        raise DownloadFailure(classify_http_status(exc.status, f"HTTP {exc.status}")) from exc
                    delay = self._backoff(attempt, exc.retry_after)
                    on_progress(
                        ProgressUpdate(phase=f"Server busy — retrying in {delay:.0f}s ({attempt}/{self.max_retries})")
                    )
                    self._sleep_or_stop(token, delay)
                except (
                    requests.ConnectionError,
                    requests.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                    _Incomplete,
                ) as exc:
                    current = part_path.stat().st_size if part_path.exists() else 0
                    if current > existing + 1024 * 1024:
                        attempt = 0  # made real progress; only count consecutive stalls
                    attempt += 1
                    if attempt > self.max_retries:
                        raise DownloadFailure(classify_exception(exc)) from exc
                    resumed_any = resumed_any or current > 0
                    delay = self._backoff(attempt, None)
                    log.info(
                        "Transient error (%s); retry %d/%d in %.1fs",
                        type(exc).__name__,
                        attempt,
                        self.max_retries,
                        delay,
                    )
                    on_progress(
                        ProgressUpdate(
                            phase=f"Connection lost — retrying in {delay:.0f}s ({attempt}/{self.max_retries})"
                        )
                    )
                    meter.reset()
                    self._sleep_or_stop(token, delay)
                except OSError as exc:
                    raise DownloadFailure(classify_exception(exc)) from exc
                except requests.RequestException as exc:
                    raise DownloadFailure(classify_exception(exc)) from exc
        finally:
            session.close()

    def _attempt(
        self,
        session: requests.Session,
        url: str,
        part_path: Path,
        existing: int,
        extra_headers: dict[str, str],
        token: CancelToken,
        on_progress: ProgressFn,
        state: dict[str, Any],
        meter: SpeedMeter,
        throttle: Throttle,
        reject_html: bool,
    ) -> HttpResult:
        with session.get(
            url, headers=self._headers(extra_headers), stream=True, timeout=self.timeout, allow_redirects=True
        ) as resp:
            status = resp.status_code
            headers = resp.headers
            if status == 416 and existing > 0:
                match = _TOTAL_ONLY_RE.search(headers.get("Content-Range", ""))
                if match and int(match.group(1)) == existing:
                    # We already have every byte.
                    return HttpResult(
                        resp.url,
                        existing,
                        state.get("content_type"),
                        state.get("content_disposition"),
                        _hash_file(part_path),
                        True,
                    )
                log.info("Server rejected resume range; restarting from zero")
                part_path.unlink(missing_ok=True)
                state["accept_ranges"] = False
                raise _Incomplete("range not satisfiable")
            if status in RETRYABLE_STATUS:
                raise _RetryableStatus(status, _parse_retry_after(headers.get("Retry-After")))
            if status >= 400:
                raise DownloadFailure(classify_http_status(status, f"HTTP {status} for {resp.url}"))

            content_type = headers.get("Content-Type")
            if reject_html and existing == 0 and content_type and "text/html" in content_type.lower():
                raise failure("not_media", f"Content-Type: {content_type}")
            encoded = (
                bool(headers.get("Content-Encoding")) and headers.get("Content-Encoding", "").lower() != "identity"
            )

            total: int | None
            if status == 206:
                match = _CONTENT_RANGE_RE.search(headers.get("Content-Range", ""))
                start = int(match.group(1)) if match else -1
                if start != existing:
                    log.info("Server returned an unexpected range (start=%s, have=%s); restarting", start, existing)
                    part_path.unlink(missing_ok=True)
                    raise _Incomplete("unexpected range")
                total = int(match.group(3)) if match and match.group(3) != "*" else None
                mode = "ab"
                resumed = True
                state["accept_ranges"] = True
            else:
                if existing > 0:
                    log.info("Server ignored the resume request or the file changed; restarting from zero")
                    on_progress(ProgressUpdate(phase="Server doesn't support resuming — restarting"))
                existing = 0
                mode = "wb"
                resumed = False
                total = None if encoded else _int_header(headers.get("Content-Length"))
                state["accept_ranges"] = headers.get("Accept-Ranges", "").lower() == "bytes" and not encoded

            state["etag"] = headers.get("ETag")
            state["last_modified"] = headers.get("Last-Modified")
            state["content_type"] = content_type
            state["content_disposition"] = headers.get("Content-Disposition")
            state["final_url"] = resp.url
            state["total"] = total

            if total is not None:
                _check_disk_space(part_path.parent, total - existing)

            hasher = hashlib.sha256()
            if mode == "ab":
                _hash_into(part_path, hasher)
            downloaded = existing
            meter.reset()
            meter.update(downloaded)
            on_progress(ProgressUpdate(downloaded=downloaded, total=total, phase="Downloading"))
            part_path.parent.mkdir(parents=True, exist_ok=True)
            with open(part_path, mode) as fh:
                for chunk in resp.iter_content(chunk_size=self.chunk_size):
                    token.raise_if_stopped()
                    if not chunk:
                        continue
                    if self.bucket is not None:
                        self.bucket.consume(len(chunk), token)
                        token.raise_if_stopped()
                    fh.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    if throttle.ready():
                        speed = meter.update(downloaded)
                        on_progress(
                            ProgressUpdate(
                                downloaded=downloaded,
                                total=total,
                                speed=speed,
                                eta=meter.eta(downloaded, total),
                                progress=(downloaded / total) if total else None,
                            )
                        )
                fh.flush()

            size = part_path.stat().st_size
            if total is not None and size < total:
                raise _Incomplete(f"received {size} of {total} bytes")
            if total is not None and size > total:
                part_path.unlink(missing_ok=True)
                raise failure("integrity", f"received {size} bytes, expected {total}")
            on_progress(ProgressUpdate(downloaded=size, total=size, progress=1.0, speed=meter.speed, eta=0))
            return HttpResult(
                resp.url, size, content_type, headers.get("Content-Disposition"), hasher.hexdigest(), resumed
            )


class _RetryableStatus(Exception):
    def __init__(self, status: int, retry_after: float | None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after


def _hash_into(path: Path, hasher: Any) -> None:
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            hasher.update(block)


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    _hash_into(path, hasher)
    return hasher.hexdigest()


def _check_disk_space(directory: Path, needed: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(directory).free
    if needed > 0 and free < needed + DISK_HEADROOM:
        raise failure(
            "disk_full",
            f"needs {needed} bytes, {free} bytes free in {directory}",
        )
