"""Windows code paths that can be exercised on any OS (sys.platform / environment patched)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from swiftdrop import binaries
from swiftdrop.cancel import CancelToken
from swiftdrop.engine import segmented
from swiftdrop.errors import DownloadFailure
from swiftdrop.media.convert import convert_for_quicktime
from swiftdrop.paths import default_paths
from swiftdrop.platform.codecs import hardware_decodes
from swiftdrop.platform.quarantine import apply_quarantine, needs_open_confirmation, zone_identifier
from swiftdrop.platform.windows import WindowsPlatform, system_prefers_dark
from swiftdrop.providers.ytdlp import YtDlpProvider
from swiftdrop.ui.navlock import navigation_allowed, normalize_url


@pytest.fixture
def win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def test_paths_on_windows(win32, monkeypatch, tmp_path):
    monkeypatch.delenv("SWIFTDROP_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    paths = default_paths()
    assert paths.data_dir == tmp_path / "Roaming" / "SwiftDrop"
    assert paths.partial_dir == tmp_path / "Roaming" / "SwiftDrop" / "partial"
    assert paths.logs_dir == tmp_path / "Local" / "SwiftDrop" / "Logs"


def test_paths_on_windows_without_env(win32, monkeypatch):
    monkeypatch.delenv("SWIFTDROP_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    paths = default_paths()
    assert paths.data_dir == Path.home() / "AppData" / "Roaming" / "SwiftDrop"
    assert paths.logs_dir == Path.home() / "AppData" / "Local" / "SwiftDrop" / "Logs"


def test_zone_identifier_content():
    text = zone_identifier("https://a.example/x.exe", "https://a.example/")
    assert text == (
        "[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=https://a.example/\r\nHostUrl=https://a.example/x.exe\r\n"
    )
    assert zone_identifier(None) == "[ZoneTransfer]\r\nZoneId=3\r\n"


def test_zone_identifier_strips_injected_lines():
    lines = zone_identifier("https://a.example/x\r\nZoneId=0").split("\r\n")
    assert lines == ["[ZoneTransfer]", "ZoneId=3", "HostUrl=https://a.example/xZoneId=0", ""]


def test_apply_quarantine_writes_zone_identifier_on_windows(win32, tmp_path):
    target = tmp_path / "setup.exe"
    target.write_bytes(b"MZ")
    assert apply_quarantine(target, "https://a.example/setup.exe") is True
    # On NTFS this is the alternate data stream; elsewhere ":" is just part of a file name.
    stream = Path(f"{target}:Zone.Identifier")
    assert stream.read_bytes() == b"[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://a.example/setup.exe\r\n"
    assert apply_quarantine(tmp_path / "missing.exe", "https://a.example/") is False
    assert not Path(f"{tmp_path / 'missing.exe'}:Zone.Identifier").exists()


def test_needs_open_confirmation_on_windows(win32, tmp_path):
    for name in ("setup.exe", "x.MSI", "run.bat", "s.ps1", "link.lnk", "app.msix", "t.reg", "x.dmg"):
        assert needs_open_confirmation(tmp_path / name), name
    for name in ("movie.mp4", "song.mp3", "doc.pdf", "archive.zip"):
        assert not needs_open_confirmation(tmp_path / name), name


def test_windows_extensions_unchanged_on_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert not needs_open_confirmation(tmp_path / "setup.exe")


def test_hardware_decodes_on_windows(win32):
    hardware_decodes.cache_clear()
    try:
        for fourcc in ("av01", "vp09", "hvc1", "hev1"):
            assert hardware_decodes(fourcc) is True
        assert hardware_decodes("vp8") is False
    finally:
        hardware_decodes.cache_clear()


def test_quicktime_conversion_never_runs_on_windows(win32, tmp_path):
    src = tmp_path / "in.webm"
    src.write_bytes(b"x")
    with pytest.raises(DownloadFailure):
        convert_for_quicktime(
            src,
            tmp_path / "out.mp4",
            ffmpeg=tmp_path / "ffmpeg.exe",
            token=CancelToken(),
            on_progress=lambda _f: None,
            duration=None,
            source_bitrate=None,
        )
    info = {"vcodec": "vp9", "acodec": "opus"}
    assert YtDlpProvider._make_quicktime_playable(None, info, src) == src  # type: ignore[arg-type]


# What Path(r"C:\Users\Jo Doe\...\index.html").as_uri() returns on Windows.
INDEX = "file:///C:/Users/Jo%20Doe/AppData/Local/Programs/SwiftDrop/_internal/swiftdrop/ui/web/index.html"


@pytest.mark.parametrize(
    "url",
    [
        INDEX,
        INDEX + "#/history",
        INDEX.replace("file:///C:", "file:///c:"),
        INDEX.replace("%20", " "),
        "file:///" + INDEX.removeprefix("file:///").replace("/", "\\"),  # backslashes
        INDEX.replace("SwiftDrop", "SWIFTDROP"),
    ],
)
def test_windows_index_url_matches(win32, url):
    assert navigation_allowed(url, True, INDEX)
    assert normalize_url(url) == normalize_url(INDEX)


def test_windows_foreign_urls_refused(win32):
    index = INDEX
    assert not navigation_allowed(index.replace("index.html", "other.html"), True, index)
    assert not navigation_allowed("https://example.com/index.html", True, index)
    assert not navigation_allowed("file:///C:/Windows/index.html", True, index)


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    path.chmod(0o755)
    return path


def test_windows_ffmpeg_from_vendor_dir(win32, monkeypatch, tmp_path):
    monkeypatch.setattr(binaries, "resource_root", lambda: tmp_path)
    monkeypatch.delenv("SWIFTDROP_FFMPEG", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    ffmpeg = _exe(tmp_path / "vendor" / "bin" / "windows-x64" / "ffmpeg.exe")
    assert binaries.find_ffmpeg() == ffmpeg


def test_windows_frozen_ffmpeg_only_bundled(win32, monkeypatch, tmp_path):
    monkeypatch.setattr(binaries, "resource_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    elsewhere = _exe(tmp_path / "elsewhere" / "ffmpeg.exe")
    monkeypatch.setattr(binaries.shutil, "which", lambda _name: str(elsewhere))
    assert binaries.find_ffmpeg() is None  # PATH is not trusted in the installed app
    bundled = _exe(tmp_path / "bin" / "ffmpeg.exe")
    assert binaries.find_ffmpeg() == bundled


def test_pwrite_fallback_on_windows(win32, tmp_path):
    target = tmp_path / "seg.bin"
    target.write_bytes(b"\0" * 8)
    fd = os.open(target, os.O_WRONLY)
    try:
        assert segmented._pwrite(fd, memoryview(b"\n\n"), 3) == 2
    finally:
        os.close(fd)
    assert target.read_bytes() == b"\0\0\0\n\n\0\0\0"


def test_windows_platform_is_inert_elsewhere(tmp_path):
    if sys.platform == "win32":
        pytest.skip("talks to the real Windows clipboard")
    platform = WindowsPlatform()
    assert platform.read_clipboard() is None
    assert platform.write_clipboard("x") is False
    assert platform.reveal(tmp_path) is False
    assert platform.open_path(tmp_path) is False
    assert platform.login_item_supported() is False
    with pytest.raises(RuntimeError):
        platform.set_login_item(True)
    platform.start_clipboard_monitor(lambda _text: None)
    platform.stop_clipboard_monitor()
    assert system_prefers_dark() is False
