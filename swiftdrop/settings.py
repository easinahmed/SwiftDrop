"""User settings: defaults, validation and persistence."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from swiftdrop.models import AUDIO_FORMAT_CHOICES, QUALITY_CHOICES, VIDEO_FORMAT_CHOICES, DownloadOptions
from swiftdrop.paths import default_download_dir
from swiftdrop.storage import Database

THEMES = ("system", "light", "dark")
COOKIE_BROWSERS = ("", "safari", "chrome", "firefox", "brave", "edge", "chromium", "vivaldi", "opera")
MAX_CONCURRENCY = 10
MAX_BANDWIDTH_KBPS = 10_000_000


@dataclass(frozen=True)
class Settings:
    download_dir: str = ""
    remember_destination: bool = True
    organize_by_type: bool = False
    playlist_subfolders: bool = True
    max_concurrent: int = 3
    connections_per_download: int = 4
    theme: str = "system"
    default_quality: str = "best"
    default_video_format: str = "mp4"
    default_audio_format: str = "m4a"
    notifications: bool = True
    clipboard_monitoring: bool = False
    resume_on_launch: bool = False
    open_at_login: bool = False
    bandwidth_limit_kbps: int = 0
    cleanup_temp_on_quit: bool = False
    skip_already_downloaded: bool = True
    auto_inspect: bool = True
    show_thumbnails: bool = True
    save_history: bool = True
    cookies_from_browser: str = ""
    verbose_logging: bool = False

    def default_options(self) -> DownloadOptions:
        return DownloadOptions(
            quality=self.default_quality,
            video_format=self.default_video_format,
            audio_format=self.default_audio_format,
        )

    @property
    def bandwidth_bytes_per_sec(self) -> int:
        return self.bandwidth_limit_kbps * 1024

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SettingsError(ValueError):
    pass


def _bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise SettingsError(f"{name} must be true or false.")
    return value


def _choice(name: str, value: Any, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise SettingsError(f"{name} must be one of: {', '.join(c or '(off)' for c in choices)}.")
    return value


def _int(name: str, value: Any, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or int(value) != value:
        raise SettingsError(f"{name} must be a whole number.")
    value = int(value)
    if not lo <= value <= hi:
        raise SettingsError(f"{name} must be between {lo} and {hi}.")
    return value


def validate_directory(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SettingsError("Choose a destination folder.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SettingsError("The destination must be an absolute folder path.")
    path = path.resolve()
    if not path.is_dir():
        raise SettingsError("The destination folder doesn't exist.")
    if not os.access(path, os.W_OK | os.X_OK):
        raise SettingsError("SwiftDrop can't write to that folder. Choose another one.")
    return str(path)


_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "download_dir": validate_directory,
    "remember_destination": lambda v: _bool("Remember destination", v),
    "organize_by_type": lambda v: _bool("Organize by type", v),
    "playlist_subfolders": lambda v: _bool("Playlist folders", v),
    "max_concurrent": lambda v: _int("Simultaneous downloads", v, 1, MAX_CONCURRENCY),
    "connections_per_download": lambda v: _int("Connections per download", v, 1, 16),
    "theme": lambda v: _choice("Theme", v, THEMES),
    "default_quality": lambda v: _choice("Default quality", v, QUALITY_CHOICES),
    "default_video_format": lambda v: _choice("Default video format", v, VIDEO_FORMAT_CHOICES),
    "default_audio_format": lambda v: _choice("Default audio format", v, AUDIO_FORMAT_CHOICES),
    "notifications": lambda v: _bool("Notifications", v),
    "clipboard_monitoring": lambda v: _bool("Clipboard monitoring", v),
    "resume_on_launch": lambda v: _bool("Resume on launch", v),
    "open_at_login": lambda v: _bool("Open at login", v),
    "bandwidth_limit_kbps": lambda v: _int("Bandwidth limit", v, 0, MAX_BANDWIDTH_KBPS),
    "cleanup_temp_on_quit": lambda v: _bool("Clean up on quit", v),
    "skip_already_downloaded": lambda v: _bool("Skip already downloaded", v),
    "auto_inspect": lambda v: _bool("Fetch link details", v),
    "show_thumbnails": lambda v: _bool("Show thumbnails", v),
    "save_history": lambda v: _bool("Save history", v),
    "cookies_from_browser": lambda v: _choice("Browser sign-in", v, COOKIE_BROWSERS),
    "verbose_logging": lambda v: _bool("Detailed logs", v),
}
assert set(_VALIDATORS) == {f.name for f in fields(Settings)}


def validate_patch(patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise SettingsError("Settings update must be an object.")
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        validator = _VALIDATORS.get(key) if isinstance(key, str) else None
        if validator is None:
            raise SettingsError(f"Unknown setting: {key!r}")
        clean[key] = validator(value)
    return clean


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        stored = self._db.load_settings()
        values: dict[str, Any] = {}
        for key, value in stored.items():
            validator = _VALIDATORS.get(key)
            if validator is None:
                continue
            try:
                values[key] = validator(value)
            except SettingsError:
                continue  # e.g. destination folder was deleted – fall back to the default
        settings = replace(Settings(), **values)
        if not settings.download_dir:
            settings = replace(settings, download_dir=str(default_download_dir()))
        return settings

    def get(self) -> Settings:
        with self._lock:
            return self._settings

    def update(self, patch: Any) -> Settings:
        clean = validate_patch(patch)
        with self._lock:
            self._settings = replace(self._settings, **clean)
            self._db.save_settings(clean)
            return self._settings
