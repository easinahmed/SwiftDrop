"""Filesystem locations used by the app.

Data lives in the standard macOS locations:

* ``~/Library/Application Support/<App>/`` – database (settings, queue, history)
  and ``partial/`` (in-progress downloads, one folder per job)
* ``~/Library/Logs/<App>/`` – rotating, redacted log files

On Windows: ``%APPDATA%\\<App>\\`` (database and ``partial\\``) and
``%LOCALAPPDATA%\\<App>\\Logs\\``.

All locations can be redirected with ``SWIFTDROP_HOME`` (used by tests and the
self-test so they never touch real user data).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from swiftdrop.appinfo import APP_NAME


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    logs_dir: Path
    partial_dir: Path

    @property
    def database(self) -> Path:
        return self.data_dir / "swiftdrop.sqlite3"

    def ensure(self) -> AppPaths:
        for path in (self.data_dir, self.logs_dir, self.partial_dir):
            path.mkdir(parents=True, exist_ok=True)
        return self


def default_paths() -> AppPaths:
    override = os.environ.get("SWIFTDROP_HOME")
    if override:
        root = Path(override).expanduser()
        return AppPaths(data_dir=root / "data", logs_dir=root / "logs", partial_dir=root / "partial")
    home = Path.home()
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        data = roaming / APP_NAME
        return AppPaths(data_dir=data, logs_dir=local / APP_NAME / "Logs", partial_dir=data / "partial")
    data = home / "Library" / "Application Support" / APP_NAME
    return AppPaths(
        data_dir=data,
        logs_dir=home / "Library" / "Logs" / APP_NAME,
        partial_dir=data / "partial",
    )


def default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def is_frozen() -> bool:
    """True when running from the packaged .app (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory that holds bundled resources (web UI, helper binaries)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def web_root() -> Path:
    if is_frozen():
        return resource_root() / "swiftdrop" / "ui" / "web"
    return Path(__file__).resolve().parent / "ui" / "web"
