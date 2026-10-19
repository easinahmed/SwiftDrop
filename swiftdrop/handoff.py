"""Hand-off between SwiftDrop processes, and the ``swiftdrop://`` link format.

A second launch of the app (double-click, a ``swiftdrop://`` link on Windows, the
"Send to SwiftDrop" bookmark in development) doesn't start another engine: it drops a
small JSON message into ``<data_dir>/inbox/`` and exits. The running app polls that
folder every 0.5 s. Messages:

* ``{"type": "show"}`` — show the main window (it may be hidden in the background);
* ``{"type": "add", "url": "https://…"}`` — offer that link in a confirm window.

Everything read from the inbox, or from a ``swiftdrop://add?url=…`` link, is untrusted:
only ``http``/``https`` URLs of at most 8192 characters pass, and an added link is
always shown in the confirm window, never started on its own.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from swiftdrop.logging_setup import get_logger

log = get_logger("handoff")

INBOX_DIR = "inbox"
POLL_INTERVAL = 0.5
MAX_MESSAGE_BYTES = 16 * 1024
MAX_AGE = 60.0  # older messages were meant for an app that has since quit
MAX_URL_CHARS = 8192
SCHEME = "swiftdrop"

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def is_web_url(value: Any) -> bool:
    """An absolute http(s) URL with a host, ≤ 8192 characters, without whitespace or control characters."""
    if not isinstance(value, str) or not value or len(value) > MAX_URL_CHARS:
        return False
    if _CONTROL_RE.search(value) or any(c.isspace() for c in value):
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(host)


def is_scheme_link(value: str) -> bool:
    return value[: len(SCHEME) + 1].lower() == f"{SCHEME}:"


def parse_scheme_link(link: str) -> str | None:
    """The web URL carried by ``swiftdrop://add?url=<encoded>`` (also ``swiftdrop:add?…``), or None."""
    if not isinstance(link, str) or len(link) > 4 * MAX_URL_CHARS or not is_scheme_link(link):
        return None
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        return None
    action = (parts.netloc or parts.path).strip("/").lower()
    if action != "add":
        return None
    values = parse_qs(parts.query, keep_blank_values=False, max_num_fields=8).get("url", [])
    if len(values) != 1:
        return None
    url = values[0].strip()
    return url if is_web_url(url) else None


def validate_message(data: Any) -> dict[str, Any] | None:
    """The normalised message, or None if it isn't one we act on."""
    if not isinstance(data, dict):
        return None
    kind = data.get("type")
    if kind == "show":
        return {"type": "show"}
    if kind == "add" and is_web_url(data.get("url")):
        return {"type": "add", "url": data["url"]}
    return None


def inbox_dir(data_dir: Path) -> Path:
    return data_dir / INBOX_DIR


def send(data_dir: Path, message: dict[str, Any]) -> bool:
    """Leave a message for the running app (written atomically: it never sees half a file)."""
    folder = inbox_dir(data_dir)
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        tmp = folder / f".{name}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(message, handle)
        os.replace(tmp, folder / f"{name}.json")
        return True
    except OSError:
        log.warning("Could not hand the request to the running app", exc_info=True)
        return False


def read_pending(data_dir: Path, now: float | None = None) -> list[dict[str, Any]]:
    """Take every waiting message (oldest first); each file is deleted once read."""
    folder = inbox_dir(data_dir)
    try:
        entries = sorted(folder.glob("*.json"))
    except OSError:
        return []
    now = time.time() if now is None else now
    messages: list[dict[str, Any]] = []
    for entry in entries:
        try:
            info = entry.stat()
            raw = entry.read_bytes() if info.st_size <= MAX_MESSAGE_BYTES else b""
        except OSError:
            continue
        finally:
            with contextlib.suppress(OSError):
                entry.unlink()
        if now - info.st_mtime > MAX_AGE:
            continue
        try:
            message = validate_message(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError, RecursionError):
            message = None
        if message is not None:
            messages.append(message)
    return messages


class InboxWatcher:
    """Polls the inbox and hands each valid message to ``handler`` (on the watcher thread)."""

    def __init__(
        self, data_dir: Path, handler: Callable[[dict[str, Any]], None], interval: float = POLL_INTERVAL
    ) -> None:
        self._data_dir = data_dir
        self._handler = handler
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        with contextlib.suppress(OSError):
            inbox_dir(self._data_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="inbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(2.0)

    def poll(self) -> int:
        messages = read_pending(self._data_dir)
        for message in messages:
            try:
                self._handler(message)
            except Exception:
                log.exception("Handling a %s request failed", message.get("type"))
        return len(messages)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.poll()
