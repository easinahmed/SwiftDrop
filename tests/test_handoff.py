"""The inbox between app instances and the swiftdrop:// link format."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from swiftdrop.handoff import (
    InboxWatcher,
    inbox_dir,
    is_web_url,
    parse_scheme_link,
    read_pending,
    send,
    validate_message,
)
from tests.conftest import wait_for


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("swiftdrop://add?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc", "https://www.youtube.com/watch?v=abc"),
        ("SwiftDrop://add?url=http%3A%2F%2Fe.com%2Fa.zip", "http://e.com/a.zip"),
        ("swiftdrop:///add?url=https%3A%2F%2Fe.com%2F", "https://e.com/"),
        ("swiftdrop:add?url=https%3A%2F%2Fe.com%2Fx", "https://e.com/x"),
        ("swiftdrop://add?url=javascript%3Aalert(1)", None),
        ("swiftdrop://add?url=file%3A%2F%2F%2Fetc%2Fpasswd", None),
        ("swiftdrop://add?url=https%3A%2F%2Fe.com%2Fa%20b", None),  # whitespace
        ("swiftdrop://add", None),
        ("swiftdrop://add?url=https%3A%2F%2Fa.com&url=https%3A%2F%2Fb.com", None),
        ("swiftdrop://open?url=https%3A%2F%2Fe.com", None),
        ("https://e.com/?url=https%3A%2F%2Fe.com", None),
        ("swiftdrop://add?url=https%3A%2F%2Fe.com%2F" + "a" * 8200, None),
    ],
)
def test_parse_scheme_link(link, expected):
    assert parse_scheme_link(link) == expected


def test_web_url_rules():
    assert is_web_url("https://e.com/a")
    for bad in ("ftp://e.com", "https://", "https://e.com/\x00", None, 5, "https://e.com/" + "x" * 8200):
        assert not is_web_url(bad)


def test_messages_are_validated():
    assert validate_message({"type": "show", "x": 1}) == {"type": "show"}
    assert validate_message({"type": "add", "url": "https://e.com/v"}) == {"type": "add", "url": "https://e.com/v"}
    for bad in ({"type": "add", "url": "file:///x"}, {"type": "start"}, [], "show", {"type": "add"}):
        assert validate_message(bad) is None


def test_send_and_read_in_order_once(tmp_path):
    assert send(tmp_path, {"type": "add", "url": "https://e.com/1"})
    assert send(tmp_path, {"type": "show"})
    folder = inbox_dir(tmp_path)
    if os.name == "posix":
        assert oct(folder.stat().st_mode & 0o777) == oct(0o700)
    assert [f.name.startswith(".") for f in folder.iterdir()] == [False, False]  # no temp files left
    assert read_pending(tmp_path) == [{"type": "add", "url": "https://e.com/1"}, {"type": "show"}]
    assert read_pending(tmp_path) == []


def test_junk_old_and_oversized_messages_are_dropped(tmp_path):
    folder = inbox_dir(tmp_path)
    folder.mkdir()
    (folder / "1-a.json").write_bytes(b"\xff\xfe not json")
    (folder / "2-b.json").write_text(json.dumps({"type": "add", "url": "https://e.com/" + "x" * 20_000}))
    old = folder / "3-c.json"
    old.write_text(json.dumps({"type": "show"}))
    os.utime(old, (time.time() - 120, time.time() - 120))
    (folder / "4-d.json").write_text(json.dumps({"type": "add", "url": "javascript:alert(1)"}))
    assert read_pending(tmp_path) == []
    assert list(folder.iterdir()) == []


def test_watcher_delivers_messages(tmp_path):
    received = []
    lock = threading.Lock()

    def handler(message):
        with lock:
            received.append(message)

    watcher = InboxWatcher(tmp_path, handler, interval=0.02)
    watcher.start()
    try:
        send(tmp_path, {"type": "show"})
        assert wait_for(lambda: received == [{"type": "show"}], timeout=3)
    finally:
        watcher.stop()
