"""Safe filenames, extension detection and conflict resolution."""

from __future__ import annotations

import mimetypes
import os
import re
import unicodedata
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urlsplit

from swiftdrop.models import MediaKind

MAX_NAME_BYTES = 240  # APFS allows 255 UTF-8 bytes; leave room for " (999)" and ".part"
DEFAULT_STEM = "download"

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED_RE = re.compile(r'[/\\:*?"<>|]')
_WHITESPACE_RE = re.compile(r"\s+")

VIDEO_EXTS = frozenset(
    {"mp4", "m4v", "mov", "webm", "mkv", "avi", "wmv", "flv", "mpg", "mpeg", "3gp", "ts", "ogv", "mts", "m2ts"}
)
AUDIO_EXTS = frozenset(
    {"mp3", "m4a", "aac", "wav", "flac", "ogg", "oga", "opus", "aiff", "aif", "alac", "wma", "mka", "caf"}
)
IMAGE_EXTS = frozenset(
    {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "avif", "bmp", "tif", "tiff", "svg", "ico", "jxl"}
)
STREAM_MANIFEST_EXTS = frozenset({"m3u8", "mpd", "f4m", "ism"})
DOCUMENT_EXTS = frozenset(
    {
        "pdf",
        "zip",
        "dmg",
        "pkg",
        "tar",
        "gz",
        "tgz",
        "bz2",
        "xz",
        "7z",
        "rar",
        "epub",
        "txt",
        "csv",
        "json",
        "srt",
        "vtt",
        "iso",
        "apk",
        "exe",
        "msi",
        "docx",
        "xlsx",
        "pptx",
        "doc",
        "xls",
        "ppt",
        "psd",
        "ai",
        "sketch",
        "fig",
        "torrent",
    }
)

# Extensions that identify a downloadable file when they end a URL path.
DIRECT_FILE_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | DOCUMENT_EXTS

_PREFERRED_MIME_EXT = {
    "image/jpeg": "jpg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "video/quicktime": "mov",
    "video/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/avif": "avif",
    "video/webm": "webm",
    "audio/webm": "webm",
    "video/x-matroska": "mkv",
    "text/plain": "txt",
    "application/octet-stream": "",
}


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def sanitize_filename(name: str, default: str = DEFAULT_STEM, max_bytes: int = MAX_NAME_BYTES) -> str:
    """Return a filename that is safe to create on macOS (APFS/HFS+, also exFAT).

    Removes path separators, control characters and characters Finder or FAT
    volumes reject, collapses whitespace, strips leading dots (hidden files) and
    truncates to ``max_bytes`` UTF-8 bytes while keeping the extension.
    """
    if not isinstance(name, str):
        name = str(name or "")
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"[\t\n\r\v\f]", " ", name)
    name = _CONTROL_RE.sub("", name)
    name = _RESERVED_RE.sub("-", name)
    name = _WHITESPACE_RE.sub(" ", name).strip()
    name = name.lstrip(". ").rstrip(". ")
    if not name or set(name) <= {"-", "_", " "}:
        name = default
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or len(ext) > 12 or " " in ext:
        stem, ext = name, ""
    ext_bytes = len(ext.encode("utf-8")) + (1 if ext else 0)
    stem = _truncate_utf8(stem, max(1, max_bytes - ext_bytes)) or default
    return f"{stem}.{ext}" if ext else stem


def split_ext(name: str) -> tuple[str, str]:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or len(ext) > 12:
        return name, ""
    return stem, ext.lower()


def extension_for_mime(content_type: str | None) -> str:
    if not content_type:
        return ""
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in _PREFERRED_MIME_EXT:
        return _PREFERRED_MIME_EXT[mime]
    guessed = mimetypes.guess_extension(mime, strict=False) or ""
    return guessed.lstrip(".")


def url_extension(url: str) -> str:
    try:
        path = unquote(urlsplit(url).path)
    except ValueError:
        return ""
    last = path.rsplit("/", 1)[-1]
    _, ext = split_ext(last)
    return ext


def filename_from_url(url: str) -> str:
    try:
        path = unquote(urlsplit(url).path)
    except ValueError:
        return ""
    return path.rstrip("/").rsplit("/", 1)[-1]


def filename_from_content_disposition(header: str | None) -> str:
    """Parse ``Content-Disposition`` including RFC 5987 ``filename*``."""
    if not header:
        return ""
    msg = Message()
    msg["content-disposition"] = header
    try:
        name = msg.get_filename()
    except (ValueError, LookupError):
        name = None
    if not name:
        match = re.search(r'filename\s*=\s*"?([^";]+)"?', header, re.IGNORECASE)
        name = match.group(1) if match else ""
    # Strip any directory components a hostile server might send.
    return os.path.basename(name.replace("\\", "/")) if name else ""


def kind_for_extension(ext: str) -> MediaKind:
    ext = (ext or "").lower().lstrip(".")
    if ext in VIDEO_EXTS:
        return MediaKind.VIDEO
    if ext in AUDIO_EXTS:
        return MediaKind.AUDIO
    if ext in IMAGE_EXTS:
        return MediaKind.IMAGE
    if ext in STREAM_MANIFEST_EXTS:
        return MediaKind.VIDEO
    return MediaKind.OTHER if ext else MediaKind.UNKNOWN


def kind_for_mime(content_type: str | None) -> MediaKind:
    if not content_type:
        return MediaKind.UNKNOWN
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime.startswith("video/") or mime in {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "application/dash+xml",
    }:
        return MediaKind.VIDEO
    if mime.startswith("audio/"):
        return MediaKind.AUDIO
    if mime.startswith("image/"):
        return MediaKind.IMAGE
    return MediaKind.OTHER


def choose_filename(
    *,
    url: str,
    content_disposition: str | None = None,
    content_type: str | None = None,
    fallback_title: str | None = None,
) -> str:
    """Pick the best filename for a direct download and make it safe."""
    name = filename_from_content_disposition(content_disposition) or filename_from_url(url)
    if not name and fallback_title:
        name = fallback_title
    name = sanitize_filename(name or DEFAULT_STEM)
    stem, ext = split_ext(name)
    mime_ext = extension_for_mime(content_type)
    if not ext and mime_ext:
        name = sanitize_filename(f"{stem}.{mime_ext}")
    elif ext and mime_ext and kind_for_extension(ext) == MediaKind.UNKNOWN:
        name = sanitize_filename(f"{name}.{mime_ext}")
    return name


def unique_path(directory: Path, filename: str, reserved: set[str] | None = None) -> Path:
    """Return ``directory/filename`` or ``directory/stem (n).ext`` if it exists.

    ``reserved`` holds lower-cased names already promised to other in-flight
    jobs so two concurrent downloads never pick the same target.
    """
    filename = sanitize_filename(filename)
    stem, ext = split_ext(filename)
    suffix = f".{ext}" if ext else ""
    taken = reserved or set()
    candidate = directory / filename
    counter = 1
    while candidate.exists() or candidate.is_symlink() or candidate.name.lower() in taken:
        candidate = directory / f"{stem} ({counter}){suffix}"
        counter += 1
        if counter > 10_000:
            raise FileExistsError(f"Could not find a free filename for {filename}")
    return candidate


def subfolder_for_kind(kind: MediaKind) -> str:
    return {
        MediaKind.VIDEO: "Videos",
        MediaKind.AUDIO: "Audio",
        MediaKind.IMAGE: "Images",
    }.get(kind, "Other")
