"""Quarantine/where-from helpers and the confirmation before opening executables."""

from __future__ import annotations

import ctypes
import ctypes.util
import plistlib
import re

import pytest

from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.platform.quarantine import apply_quarantine, needs_open_confirmation
from swiftdrop.service import AppService, ServiceError

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.getxattr.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_int,
]
_libc.getxattr.restype = ctypes.c_ssize_t


def _getxattr(path, name: str) -> bytes:
    raw = str(path).encode()
    key = name.encode()
    size = _libc.getxattr(raw, key, None, 0, 0, 0)
    assert size >= 0, f"missing xattr {name}"
    buf = ctypes.create_string_buffer(size)
    assert _libc.getxattr(raw, key, buf, size, 0, 0) == size
    return buf.raw


def test_quarantine_xattrs_written(tmp_path):
    f = tmp_path / "x.zip"
    f.write_bytes(b"data")
    assert apply_quarantine(f, "https://a/x.zip", "https://a/") is True
    value = _getxattr(f, "com.apple.quarantine").decode()
    assert re.match(r"^0081;[0-9a-f]{8};SwiftDrop;", value)
    froms = plistlib.loads(_getxattr(f, "com.apple.metadata:kMDItemWhereFroms"))
    assert froms == ["https://a/x.zip", "https://a/"]


def test_quarantine_failure_returns_false(tmp_path):
    assert apply_quarantine(tmp_path / "missing.bin", "https://a/x") is False


def test_needs_open_confirmation(tmp_path):
    (tmp_path / "Foo.app").mkdir()
    assert needs_open_confirmation(tmp_path / "x.command")
    assert needs_open_confirmation(tmp_path / "x.dmg")
    assert needs_open_confirmation(tmp_path / "Foo.app")
    assert not needs_open_confirmation(tmp_path / "x.mp4")
    assert not needs_open_confirmation(tmp_path / "x.pdf")
    tool = tmp_path / "runme"
    tool.write_bytes(b"#!/bin/sh\n")
    assert not needs_open_confirmation(tool)
    tool.chmod(0o755)
    assert needs_open_confirmation(tool)


def test_open_executable_requires_confirmation(tmp_path):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    platform = NullPlatform()
    svc = AppService(paths, platform, enable_sites=False)
    try:
        script = tmp_path / "x.command"
        script.write_text("echo hi")
        with pytest.raises(ServiceError, match="confirm_open"):
            svc.open_file(script)
        assert platform.opened == []
        assert svc.open_file(script, confirmed=True)
        assert platform.opened == [script]
        movie = tmp_path / "x.mp4"
        movie.write_bytes(b"x")
        assert svc.open_file(movie)
    finally:
        svc.shutdown()


def test_finished_download_is_quarantined(tmp_path, http_server):
    from tests.conftest import make_bytes, wait_for

    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    svc = AppService(paths, NullPlatform(), enable_sites=False)
    svc.settings.update({"download_dir": str(downloads), "organize_by_type": False})
    svc.start()
    try:
        url = http_server.add_file("q.bin", make_bytes(10_000))
        item = svc.analyze_text(url)["added"][0]
        svc.start_downloads([{"id": item["id"], "entries": None}], None, None)
        assert wait_for(lambda: any(p.is_file() for p in downloads.rglob("*")))
        final = next(p for p in downloads.rglob("*") if p.is_file())
        assert wait_for(lambda: svc.platform.notifications)
        assert _getxattr(final, "com.apple.quarantine")
        froms = plistlib.loads(_getxattr(final, "com.apple.metadata:kMDItemWhereFroms"))
        assert url in froms
    finally:
        svc.shutdown()
