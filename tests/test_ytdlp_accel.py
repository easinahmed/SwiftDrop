"""Accelerated segmented HTTPS streams for yt-dlp formats: plan, merge, expired-link refresh, fallback."""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
from pathlib import Path

import pytest

from swiftdrop.cancel import CancelToken
from swiftdrop.engine.segmented import SegmentedDownloader
from swiftdrop.errors import DownloadFailure
from swiftdrop.media.convert import merge_streams
from swiftdrop.models import DownloadOptions
from swiftdrop.providers.accel import EXPIRED_MESSAGE, accelerated_plan, download_streams
from swiftdrop.providers.ytdlp import YtDlpProvider
from swiftdrop.settings import Settings


class _Ctx:
    job_id = "0123456789abcdef"
    url = "https://example.com/watch?v=1"
    collection_folder = None

    def __init__(self, tmp_path: Path) -> None:
        self.options = DownloadOptions("best", "mkv", "m4a")
        self.settings = Settings()
        self.token = CancelToken()
        self.staging_dir = tmp_path / "staging"
        self.staging_dir.mkdir()
        self.meta: dict = {}
        self.updates: list = []

    def report(self, update):
        self.updates.append(update)

    def set_info(self, **fields):
        pass

    def checkpoint(self):
        pass

    def finalize(self, source, filename, kind):
        return source


def _factory():
    return SegmentedDownloader(connections=1, min_segment=32 * 1024)


def _fmt(url, data, format_id, **extra):
    return {"format_id": format_id, "url": url, "protocol": "https", "filesize": len(data), **extra}


def test_accelerated_plan_only_for_http_formats():
    https = {"format_id": "1", "url": "https://x/v", "protocol": "https"}
    audio = {"format_id": "2", "url": "https://x/a", "protocol": "http"}
    assert accelerated_plan({"requested_formats": [https, audio]}) == [https, audio]
    assert accelerated_plan({"requested_formats": [https, {**audio, "protocol": "m3u8_native"}]}) is None
    assert accelerated_plan({"requested_formats": [{"format_id": "3", "protocol": "https"}]}) is None  # no url
    assert accelerated_plan({**https}) == [https]


@pytest.mark.ffmpeg
def test_download_streams_and_merge_mp4(tmp_path, http_server, ffmpeg_path):
    src = tmp_path / "src"
    src.mkdir()
    video, audio = src / "v.mp4", src / "a.m4a"
    run = [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(
        [*run, "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30", "-t", "2", "-an", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )  # fmt: skip
    subprocess.run([*run, "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(audio)], check=True)
    plan = [
        _fmt(http_server.add_file("v.mp4", video.read_bytes()), video.read_bytes(), "v", vcodec="avc1", acodec="none"),
        _fmt(http_server.add_file("a.m4a", audio.read_bytes()), audio.read_bytes(), "a", vcodec="none", acodec="mp4a"),
    ]
    ctx = _Ctx(tmp_path)
    paths = download_streams(plan, ctx, lambda fid: pytest.fail("no refresh expected"), _factory)
    merged = tmp_path / "out.mp4"
    merge_streams(paths[0], paths[1], merged, ffmpeg=ffmpeg_path, token=CancelToken(), audio_to_aac=False)
    probe = subprocess.run(
        [str(ffmpeg_path.with_name("ffprobe")), "-v", "error", "-show_entries", "stream=codec_type", "-of", "json",
         str(merged)], capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert sorted(s["codec_type"] for s in json.loads(probe.stdout)["streams"]) == ["audio", "video"]
    done = [u.downloaded for u in ctx.updates if u.downloaded is not None]
    assert done and done == sorted(done)
    assert {u.phase for u in ctx.updates} <= {"Downloading video", "Downloading audio"}


def test_expired_link_refreshes_and_continues(tmp_path, http_server):
    data = random.Random(3).randbytes(2 * 1024 * 1024)
    cut = int(len(data) * 0.4)
    url = http_server.add_file("s.bin", data) + f"?fail_after_bytes={cut}&fail_code=403"
    fresh_url = http_server.add_file("s.bin", data) + "?renewed=1"
    refreshed: list[str] = []

    def refresh(format_id):
        refreshed.append(format_id)
        return _fmt(fresh_url, data, format_id, vcodec="avc1", acodec="mp4a")

    ctx = _Ctx(tmp_path)
    (path,) = download_streams([_fmt(url, data, "18", vcodec="avc1", acodec="mp4a")], ctx, refresh, _factory)
    assert refreshed == ["18"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()
    renewed = [
        int(h["Range"].split("=")[1].split("-")[0])
        for p, h in http_server.requests
        if "renewed=1" in p and h.get("Range") != "bytes=0-0"
    ]
    assert renewed and min(renewed) >= cut * 0.9, "the bytes before the failure must not be fetched again"


def test_two_failed_refreshes_fail_job(tmp_path, http_server):
    dead = http_server.url("/status/403")
    calls: list[str] = []

    def refresh(format_id):
        calls.append(format_id)
        return {"format_id": format_id, "url": dead, "protocol": "https"}

    plan = [{"format_id": "18", "url": dead, "protocol": "https", "vcodec": "avc1", "acodec": "mp4a"}]
    with pytest.raises(DownloadFailure) as failed:
        download_streams(plan, _Ctx(tmp_path), refresh, _factory)
    assert failed.value.info.message == EXPIRED_MESSAGE
    assert len(calls) == 2


def test_hls_falls_back_to_ytdlp_with_8_fragments(tmp_path, monkeypatch):
    import yt_dlp

    seen: dict = {}
    ctx = _Ctx(tmp_path)
    produced = ctx.staging_dir / "Clip.mkv"
    produced.write_bytes(b"x")
    fmt = {"format_id": "hls", "url": "https://x/index.m3u8", "protocol": "m3u8_native", "ext": "mp4"}

    def fake_extract_info(self, url, download=True, **kwargs):
        return {"id": "v", "title": "Clip", "extractor": "generic", "formats": [fmt], **fmt}

    def fake_process(self, info, download=True):
        seen["fragments"] = self.params["concurrent_fragment_downloads"]
        return {**info, "requested_downloads": [{"filepath": str(produced)}]}

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract_info)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "process_ie_result", fake_process)
    provider = YtDlpProvider(segmented_factory=lambda n: pytest.fail("HLS must not use the segmented engine"))
    provider.download(ctx)
    assert seen["fragments"] == 8
