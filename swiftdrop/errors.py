"""Turning low-level failures into clear, user-facing explanations.

Every failure that reaches the UI is an :class:`~swiftdrop.models.ErrorInfo`
with a short title, a plain-language message, a hint about what to do next and
(redacted) technical detail for debugging.
"""

from __future__ import annotations

import errno
import re
import ssl
from typing import Any

import requests

from swiftdrop.models import ErrorInfo
from swiftdrop.redact import redact

# code -> (title, message, hint, retryable)
_CATALOG: dict[str, tuple[str, str, str, bool]] = {
    "invalid_url": ("Invalid link", "This doesn't look like a valid web address.", "Check the link for typos.", False),
    "unsupported": (
        "Unsupported link",
        "No downloadable media was found at this link.",
        "Make sure the link opens a public video, audio file, image or file in your browser.",
        False,
    ),
    "not_media": (
        "Not a media file",
        "This link points to a web page, and no downloadable media was found on it.",
        "Open the page in a browser and copy the direct link to the media instead.",
        False,
    ),
    "drm": (
        "Protected content",
        "This media is protected by DRM (copy protection) and can't be downloaded.",
        "Use the service's own offline or download feature.",
        False,
    ),
    "private": (
        "Private content",
        "This media is private or restricted by its owner.",
        "Only public media, or media your account can access, can be downloaded.",
        False,
    ),
    "login_required": (
        "Sign-in required",
        "The site requires you to be signed in to access this media.",
        "If you have access, turn on “Use browser sign-in” in Settings → Privacy, sign in with that browser and retry.",
        False,
    ),
    "bot_check": (
        "Verification required",
        "The site asked to confirm the request comes from a person.",
        "Wait a while and retry, or turn on “Use browser sign-in” in Settings → Privacy.",
        True,
    ),
    "geo_blocked": (
        "Not available in your region",
        "The owner has restricted this media to other regions.",
        "This restriction can't be bypassed.",
        False,
    ),
    "not_found": (
        "Not found",
        "The file or page doesn't exist (HTTP 404).",
        "The link may have been removed or mistyped.",
        False,
    ),
    "expired": (
        "Link expired",
        "This link has expired or is no longer valid.",
        "Copy a fresh link from the source and try again.",
        False,
    ),
    "forbidden": (
        "Access denied",
        "The server refused to provide this file (HTTP 403).",
        "The link may be private, expired, or only work while signed in.",
        True,
    ),
    "unavailable": (
        "Media unavailable",
        "This media has been removed or is currently unavailable.",
        "There's nothing to download at this link right now.",
        False,
    ),
    "live": ("Live stream", "This is a live or upcoming stream.", "Try again after the broadcast has ended.", False),
    "rate_limited": (
        "Rate limited",
        "The site is limiting requests right now (HTTP 429).",
        "Wait a few minutes before retrying, or lower simultaneous downloads in Settings.",
        True,
    ),
    "network": (
        "Network problem",
        "The connection was lost or the server couldn't be reached.",
        "Check your internet connection and retry. Downloads continue from where they stopped "
        "when the server allows it.",
        True,
    ),
    "timeout": (
        "Timed out",
        "The server stopped responding.",
        "Retry in a moment — the download will continue where it stopped when possible.",
        True,
    ),
    "tls": (
        "Secure connection failed",
        "A secure (HTTPS) connection to the server couldn't be established.",
        "The site's certificate may be invalid, or a network filter is interfering.",
        True,
    ),
    "server_error": (
        "Server error",
        "The server returned an error.",
        "This is usually temporary. Retry in a moment.",
        True,
    ),
    "disk_full": (
        "Not enough disk space",
        "There isn't enough free space to save this file.",
        "Free up space or choose another destination folder.",
        True,
    ),
    "permission": (
        "Can't save to folder",
        "SwiftDrop isn't allowed to write to the destination folder.",
        "Choose another folder, or allow access in System Settings → Privacy & Security → Files and Folders.",
        True,
    ),
    "filesystem": (
        "File error",
        "The file couldn't be written.",
        "Check that the destination drive is connected and writable.",
        True,
    ),
    "ffmpeg_missing": (
        "FFmpeg unavailable",
        "This download needs FFmpeg to merge or convert media, but the bundled copy couldn't be found.",
        "Reinstall SwiftDrop, or pick “Auto” format so no conversion is needed.",
        False,
    ),
    "ffmpeg_failed": (
        "Processing failed",
        "FFmpeg couldn't merge or convert this media.",
        "Retry with format “MKV” or “Auto”, which accept more codecs.",
        True,
    ),
    "format_unavailable": (
        "Format unavailable",
        "The requested quality or format isn't offered for this media.",
        "Choose “Best” quality or “Auto” format and retry.",
        False,
    ),
    "js_runtime": (
        "JavaScript runtime needed",
        "This site needs a JavaScript runtime (Deno or Node.js) to unlock its media formats.",
        "Install Deno (brew install deno) or Node.js, then retry.",
        True,
    ),
    "extractor_broken": (
        "Site changed",
        "The site's page layout changed, so the media couldn't be located.",
        "Update SwiftDrop to get the latest download engine.",
        True,
    ),
    "no_match": (
        "No matching song found",
        "SwiftDrop couldn't find this song on YouTube with the same title, artist and length.",
        "It may not be on YouTube, or only as a live, remixed or cover version.",
        False,
    ),
    "integrity": (
        "Download incomplete",
        "The downloaded file is smaller than the server reported.",
        "Retry the download.",
        True,
    ),
    "interrupted": ("Interrupted", "The download was interrupted before it finished.", "Resume to continue.", True),
    "unknown": (
        "Download failed",
        "Something unexpected went wrong.",
        "Open the technical details for more information, then retry.",
        True,
    ),
}


class DownloadFailure(Exception):
    """An expected failure with a ready-made user-facing explanation."""

    def __init__(self, info: ErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


def make_error(
    code: str,
    detail: str = "",
    *,
    message: str | None = None,
    hint: str | None = None,
    title: str | None = None,
    retryable: bool | None = None,
) -> ErrorInfo:
    base_title, base_message, base_hint, base_retryable = _CATALOG.get(code, _CATALOG["unknown"])
    return ErrorInfo(
        code=code if code in _CATALOG else "unknown",
        title=title or base_title,
        message=message or base_message,
        hint=base_hint if hint is None else hint,
        detail=redact(_clean_detail(detail))[:4000],
        retryable=base_retryable if retryable is None else retryable,
    )


def failure(code: str, detail: str = "", **kwargs: Any) -> DownloadFailure:
    return DownloadFailure(make_error(code, detail, **kwargs))


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _clean_detail(detail: str) -> str:
    text = _ANSI_RE.sub("", str(detail or "")).strip()
    return re.sub(r"^(ERROR|WARNING):\s*", "", text)


def classify_http_status(status: int, detail: str = "") -> ErrorInfo:
    if status in (401, 407):
        return make_error("login_required", detail)
    if status == 403:
        return make_error("forbidden", detail)
    if status == 404:
        return make_error("not_found", detail)
    if status == 410:
        return make_error("expired", detail, message="The server says this file is gone (HTTP 410).")
    if status == 429:
        return make_error("rate_limited", detail)
    if status == 451:
        return make_error("unavailable", detail, message="This media is unavailable for legal reasons (HTTP 451).")
    if status in (408,):
        return make_error("timeout", detail)
    if 500 <= status <= 599:
        return make_error("server_error", detail, message=f"The server returned an error (HTTP {status}).")
    return make_error("unknown", detail, message=f"The server answered with HTTP {status}.")


# Ordered (pattern, code) pairs matched against lower-cased engine messages.
_MESSAGE_RULES: tuple[tuple[str, str], ...] = (
    (r"\bdrm\b|drm[- ]protected|widevine|fairplay", "drm"),
    (r"no space left|errno 28\b|disk (is )?full", "disk_full"),
    (r"permission denied|errno 13\b|operation not permitted|read-only file system", "permission"),
    (
        r"ffprobe and ffmpeg not found|ffmpeg not found|ffmpeg is not installed|ffmpeg.*not (found|available)",
        "ffmpeg_missing",
    ),
    (r"postprocessing:|conversion failed|error opening output|ffmpeg exited", "ffmpeg_failed"),
    (
        r"requested format (is )?not available|no video formats found|requested formats are incompatible",
        "format_unavailable",
    ),
    (r"n challenge|js challenge|javascript runtime|jsc? runtime|\bejs\b", "js_runtime"),
    (r"not a bot|confirm you.re not a robot|captcha", "bot_check"),
    (
        r"private video|this video is private|is private|private (account|profile|post)|"
        r"you don.t have permission to (view|access)",
        "private",
    ),
    (r"sign in to confirm your age|age[- ]restricted|inappropriate for some users", "login_required"),
    (
        r"login required|log in to|login to|logged[- ]in|requires? (authentication|login|sign[- ]?in)|"
        r"use --cookies|--cookies-from-browser|registered users|members[- ]only|join this channel|"
        r"subscriber[- ]only|premium members",
        "login_required",
    ),
    (
        r"available in your country|geo[- ]?restrict|not available in your (region|location)|"
        r"blocked it in your country",
        "geo_blocked",
    ),
    (r"unsupported url", "unsupported"),
    (r"http error 401", "login_required"),
    (r"http error 403", "forbidden"),
    (r"http error 404", "not_found"),
    (r"http error 410", "expired"),
    (r"http error 429|too many requests|rate[- ]limit", "rate_limited"),
    (r"http error 5\d\d", "server_error"),
    (r"this live event will begin|premieres in|is live|live stream (is )?(offline|not)|is_live", "live"),
    (
        r"video unavailable|has been removed|no longer available|account (has been )?terminated|"
        r"this video is unavailable|content (is )?not available|does not exist",
        "unavailable",
    ),
    (r"timed out|read timeout|timeout", "timeout"),
    (r"certificate verify failed|ssl:|sslerror|tlsv1", "tls"),
    (
        r"connection (reset|refused|aborted)|name or service not known|nodename nor servname|"
        r"network is unreachable|failed to resolve|temporary failure in name resolution|"
        r"remote end closed|connectionerror|unable to download webpage|no route to host|"
        r"incompleteread|unexpected eof",
        "network",
    ),
    (r"unable to extract|failed to parse|unable to find|extractorerror", "extractor_broken"),
)


def classify_message(text: str) -> ErrorInfo:
    lowered = _clean_detail(text).lower()
    for pattern, code in _MESSAGE_RULES:
        if re.search(pattern, lowered):
            return make_error(code, text)
    return make_error("unknown", text)


def classify_exception(exc: BaseException) -> ErrorInfo:
    """Best-effort mapping of any exception to a user-facing :class:`ErrorInfo`."""
    if isinstance(exc, DownloadFailure):
        return exc.info
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, OSError) and exc.errno is not None:
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            return make_error("disk_full", detail)
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            return make_error("permission", detail)
        if exc.errno in (errno.ENOENT, errno.ENOTDIR, errno.EIO, errno.ENAMETOOLONG):
            return make_error("filesystem", detail)
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return classify_http_status(exc.response.status_code, detail)
    if isinstance(exc, requests.exceptions.SSLError | ssl.SSLError):
        return make_error("tls", detail)
    if isinstance(exc, requests.exceptions.Timeout | TimeoutError):
        return make_error("timeout", detail)
    if isinstance(
        exc, requests.exceptions.ConnectionError | requests.exceptions.ChunkedEncodingError | ConnectionError
    ):
        return make_error("network", detail)
    if isinstance(
        exc, requests.exceptions.InvalidURL | requests.exceptions.MissingSchema | requests.exceptions.InvalidSchema
    ):
        return make_error("invalid_url", detail)
    return classify_message(detail)
