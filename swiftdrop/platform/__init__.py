"""Platform integration (macOS) behind a small interface so the core stays testable."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class Platform(Protocol):
    def reveal(self, path: Path) -> bool: ...

    def open_path(self, path: Path) -> bool: ...

    def read_clipboard(self) -> str | None: ...

    def write_clipboard(self, text: str) -> bool: ...

    def notify(self, title: str, body: str) -> None: ...

    def set_login_item(self, enabled: bool) -> None: ...

    def login_item_supported(self) -> bool: ...

    def set_appearance(self, theme: str) -> None: ...

    def start_clipboard_monitor(self, callback: Callable[[str], None]) -> None: ...

    def stop_clipboard_monitor(self) -> None: ...


class NullPlatform:
    """Used in tests and headless runs: records calls, touches nothing."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.revealed: list[Path] = []
        self.opened: list[Path] = []
        self.clipboard: str | None = None
        self.login_item_calls: list[bool] = []
        self.monitor_callback: Callable[[str], None] | None = None

    def reveal(self, path: Path) -> bool:
        self.revealed.append(path)
        return True

    def open_path(self, path: Path) -> bool:
        self.opened.append(path)
        return True

    def read_clipboard(self) -> str | None:
        return self.clipboard

    def write_clipboard(self, text: str) -> bool:
        self.clipboard = text
        return True

    def notify(self, title: str, body: str) -> None:
        self.notifications.append((title, body))

    def set_login_item(self, enabled: bool) -> None:
        self.login_item_calls.append(enabled)
        raise RuntimeError("Open at login is only available in the installed app.")

    def login_item_supported(self) -> bool:
        return False

    def set_appearance(self, theme: str) -> None:
        pass

    def start_clipboard_monitor(self, callback: Callable[[str], None]) -> None:
        self.monitor_callback = callback

    def stop_clipboard_monitor(self) -> None:
        self.monitor_callback = None


def free_space(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None
