"""Typed domain objects shared by the queue, providers, storage and UI bridge."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from typing import Any


class MediaKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    OTHER = "other"
    UNKNOWN = "unknown"


class JobState(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"  # post-processing (FFmpeg merge / conversion, moving into place)
    PAUSED = "paused"
    INTERRUPTED = "interrupted"  # app quit or crashed mid-download; resumable
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATES = frozenset({JobState.DOWNLOADING, JobState.PROCESSING})
WAITING_STATES = frozenset({JobState.QUEUED})
RESUMABLE_STATES = frozenset({JobState.PAUSED, JobState.INTERRUPTED})
FINISHED_STATES = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED})

QUALITY_CHOICES = ("best", "2160", "1440", "1080", "720", "480", "360", "audio")
VIDEO_FORMAT_CHOICES = ("auto", "mp4", "mkv", "webm")
AUDIO_FORMAT_CHOICES = ("auto", "m4a", "mp3", "opus", "flac", "wav")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class DownloadOptions:
    quality: str = "best"
    video_format: str = "mp4"
    audio_format: str = "m4a"

    @property
    def audio_only(self) -> bool:
        return self.quality == "audio"

    @property
    def max_height(self) -> int | None:
        return int(self.quality) if self.quality.isdigit() else None

    def label(self) -> str:
        if self.audio_only:
            fmt = self.audio_format.upper() if self.audio_format != "auto" else "Best"
            return f"Audio · {fmt}"
        quality = "Best" if self.quality == "best" else f"{self.quality}p"
        fmt = self.video_format.upper() if self.video_format != "auto" else "Auto"
        return f"{quality} · {fmt}"

    @classmethod
    def from_dict(cls, data: Any, defaults: DownloadOptions | None = None) -> DownloadOptions:
        base = defaults or cls()
        if not isinstance(data, dict):
            return base
        quality = data.get("quality", base.quality)
        video_format = data.get("video_format", base.video_format)
        audio_format = data.get("audio_format", base.audio_format)
        return cls(
            quality=quality if quality in QUALITY_CHOICES else base.quality,
            video_format=video_format if video_format in VIDEO_FORMAT_CHOICES else base.video_format,
            audio_format=audio_format if audio_format in AUDIO_FORMAT_CHOICES else base.audio_format,
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ErrorInfo:
    code: str
    title: str
    message: str
    hint: str = ""
    detail: str = ""
    retryable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> ErrorInfo | None:
        if not isinstance(data, dict) or "code" not in data:
            return None
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Job:
    url: str
    key: str
    destination: str
    options: DownloadOptions = field(default_factory=DownloadOptions)
    provider: str = "auto"
    id: str = field(default_factory=new_id)
    title: str = ""
    source: str = ""
    kind: MediaKind = MediaKind.UNKNOWN
    state: JobState = JobState.QUEUED
    created_at: float = field(default_factory=time.time)
    order: int = 0
    collection_id: str | None = None
    playlist_index: int | None = None
    thumbnail: str | None = None
    extractor: str | None = None
    duration: float | None = None
    phase: str = ""
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    total_is_estimate: bool = False
    speed: float | None = None
    eta: float | None = None
    progress: float | None = None
    filename: str | None = None
    filepath: str | None = None
    file_size: int | None = None
    quality_label: str | None = None
    error: ErrorInfo | None = None
    attempts: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    resumable: bool | None = None
    note: str | None = None
    file_missing: bool = False
    sha256: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    # -- serialisation -------------------------------------------------
    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["state"] = self.state.value
        data["options"] = self.options.to_dict()
        data["error"] = self.error.to_dict() if self.error else None
        return data

    @classmethod
    def from_record(cls, data: dict[str, Any]) -> Job:
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["kind"] = MediaKind(values.get("kind", MediaKind.UNKNOWN))
        values["state"] = JobState(values.get("state", JobState.QUEUED))
        values["options"] = DownloadOptions.from_dict(values.get("options"))
        values["error"] = ErrorInfo.from_dict(values.get("error"))
        values["meta"] = dict(values.get("meta") or {})
        return cls(**values)

    def to_public(self) -> dict[str, Any]:
        """Shape sent to the UI. Engine internals (``meta``) stay in Python."""
        data = self.to_record()
        data.pop("meta", None)
        data.pop("key", None)
        if self.error:
            data["error"] = self.error.to_dict()
        return data

    def reset_progress(self) -> None:
        self.downloaded_bytes = 0
        self.total_bytes = None
        self.total_is_estimate = False
        self.speed = None
        self.eta = None
        self.progress = None
        self.phase = ""


@dataclass
class Collection:
    """A playlist / album / channel expanded into individual jobs."""

    title: str
    url: str
    source: str
    destination: str
    id: str = field(default_factory=new_id)
    extractor: str | None = None
    thumbnail: str | None = None
    created_at: float = field(default_factory=time.time)
    total_entries: int | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, data: dict[str, Any]) -> Collection:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class PlaylistEntry:
    id: str
    url: str
    title: str
    index: int
    duration: float | None = None
    thumbnail: str | None = None
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InspectResult:
    """Metadata gathered for a link before downloading (never required to start)."""

    provider: str
    title: str = ""
    kind: MediaKind = MediaKind.UNKNOWN
    extractor: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    size: int | None = None
    size_is_estimate: bool = False
    filename: str | None = None
    heights: list[int] = field(default_factory=list)
    has_audio_only: bool = False
    is_playlist: bool = False
    entries: list[PlaylistEntry] = field(default_factory=list)
    entries_truncated: bool = False
    resolved_url: str | None = None
    content_type: str | None = None  # internal: response type seen while probing

    def to_public(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "title": self.title,
            "kind": self.kind.value,
            "extractor": self.extractor,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
            "size": self.size,
            "size_is_estimate": self.size_is_estimate,
            "filename": self.filename,
            "heights": self.heights,
            "has_audio_only": self.has_audio_only,
            "is_playlist": self.is_playlist,
            "entry_count": len(self.entries),
            "entries_truncated": self.entries_truncated,
        }
