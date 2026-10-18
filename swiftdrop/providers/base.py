"""Provider interfaces.

A *provider* knows how to inspect and download one category of link (direct
files, sites supported by yt-dlp, …). Providers never touch queue state or the
UI directly; they talk to the queue through :class:`JobContext`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from swiftdrop.cancel import CancelToken
from swiftdrop.engine.progress import ProgressUpdate
from swiftdrop.models import DownloadOptions, InspectResult, MediaKind
from swiftdrop.settings import Settings


@dataclass
class DownloadOutcome:
    filepath: Path
    size: int
    kind: MediaKind
    sha256: str | None = None


class JobContext(Protocol):
    """What a provider may know about, and do to, the job it is running."""

    job_id: str
    url: str
    options: DownloadOptions
    settings: Settings
    token: CancelToken
    staging_dir: Path
    meta: dict[str, Any]
    collection_folder: str | None

    def report(self, update: ProgressUpdate) -> None: ...

    def set_info(self, **fields: Any) -> None: ...

    def checkpoint(self) -> None: ...

    def finalize(self, source: Path, filename: str, kind: MediaKind) -> Path: ...


class Provider(Protocol):
    name: str

    def inspect(self, url: str, token: CancelToken, settings: Settings) -> InspectResult: ...

    def download(self, ctx: JobContext) -> DownloadOutcome: ...
