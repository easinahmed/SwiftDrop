import threading

import pytest

from swiftdrop.filenames import (
    MAX_NAME_BYTES,
    choose_filename,
    filename_from_content_disposition,
    kind_for_extension,
    sanitize_filename,
    unique_path,
)
from swiftdrop.fileops import move_into_place, reserve_unique_path
from swiftdrop.models import MediaKind


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("normal.mp4", "normal.mp4"),
        ('a/b\\c:d*e?f"g<h>i|j.mp4', "a-b-c-d-e-f-g-h-i-j.mp4"),
        ("../../etc/passwd", "-..-etc-passwd"),
        ("   spaced    out   name .mp3 ", "spaced out name .mp3"),
        (".hidden", "hidden"),
        ("...", "download"),
        ("", "download"),
        ("tab\tand\nnewline\x00.txt", "tab and newline.txt"),
        ("trailing dots...", "trailing dots"),
    ],
)
def test_sanitize(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_nfc_normalizes():
    decomposed = "Café.mp4"
    assert sanitize_filename(decomposed) == "Café.mp4"


def test_sanitize_truncates_utf8_bytes_and_keeps_extension():
    name = ("视频" * 200) + ".mp4"
    result = sanitize_filename(name)
    assert result.endswith(".mp4")
    assert len(result.encode("utf-8")) <= MAX_NAME_BYTES
    result.encode("utf-8").decode("utf-8")  # still valid UTF-8


def test_content_disposition_variants():
    assert filename_from_content_disposition('attachment; filename="report.pdf"') == "report.pdf"
    assert filename_from_content_disposition("attachment; filename*=UTF-8''na%C3%AFve%20file.mp4") == "naïve file.mp4"
    assert filename_from_content_disposition('attachment; filename="../../evil.sh"') == "evil.sh"
    assert filename_from_content_disposition(None) == ""


def test_choose_filename_adds_extension_from_mime():
    assert choose_filename(url="https://example.com/download?id=3", content_type="video/mp4") == "download.mp4"
    assert choose_filename(url="https://example.com/photo", content_type="image/jpeg") == "photo.jpg"
    assert choose_filename(url="https://example.com/clip.mov", content_type="video/quicktime") == "clip.mov"


@pytest.mark.parametrize(
    ("name", "ctype", "expected"),
    [
        ("watch.php", "video/mp4", "watch.mp4"),
        ("get.cgi", "audio/mpeg", "get.mp3"),
        ("stream.aspx", "image/jpeg", "stream.jpg"),
        ("report.pdf", "application/octet-stream", "report.pdf"),
        ("archive.tar.gz", "application/gzip", "archive.tar.gz"),
        ("clip.mp4", "video/quicktime", "clip.mp4"),
    ],
)
def test_choose_filename_media_mime_replaces_unknown_extension(name, ctype, expected):
    assert choose_filename(url=f"https://example.com/{name}", content_type=ctype) == expected


def test_choose_filename_keeps_stream_manifest_extension():
    url = "https://example.com/play.m3u8"
    assert choose_filename(url=url, content_type="application/vnd.apple.mpegurl") == "play.m3u8"


def test_kind_for_extension():
    assert kind_for_extension("MP4") == MediaKind.VIDEO
    assert kind_for_extension("flac") == MediaKind.AUDIO
    assert kind_for_extension("heic") == MediaKind.IMAGE
    assert kind_for_extension("zip") == MediaKind.OTHER
    assert kind_for_extension("") == MediaKind.UNKNOWN


def test_unique_path_appends_counter(tmp_path):
    (tmp_path / "a.mp4").write_text("x")
    (tmp_path / "a (1).mp4").write_text("x")
    assert unique_path(tmp_path, "a.mp4").name == "a (2).mp4"


def test_reserve_unique_path_is_race_free(tmp_path):
    results = []
    lock = threading.Lock()

    def worker():
        path = reserve_unique_path(tmp_path, "same.mp4")
        with lock:
            results.append(path.name)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 20


def test_move_into_place_replaces_placeholder(tmp_path):
    src = tmp_path / "src.part"
    src.write_bytes(b"data")
    dest_dir = tmp_path / "out"
    target = reserve_unique_path(dest_dir, "file.bin")
    final = move_into_place(src, target)
    assert final.read_bytes() == b"data"
    assert not src.exists()
