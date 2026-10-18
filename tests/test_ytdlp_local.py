"""yt-dlp integration against local fixtures only (HLS, RSS feed, HTML5 page).

These exercise the real yt-dlp engine and the bundled/located FFmpeg without
touching any third-party website.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.progress import ProgressUpdate
from swiftdrop.models import DownloadOptions, JobState, MediaKind
from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.providers.ytdlp import YtDlpProvider, _ProgressTracker, format_options
from swiftdrop.service import AppService
from swiftdrop.settings import Settings
from tests.conftest import make_bytes, wait_for

pytestmark = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    from swiftdrop.binaries import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    root = tmp_path_factory.mktemp("media")
    hls = root / "hls"
    hls.mkdir()
    common = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=6:size=320x240:rate=15",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=6",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
    ]
    subprocess.run(
        [
            *common,
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            "-hls_segment_filename",
            str(hls / "seg%03d.ts"),
            str(hls / "index.m3u8"),
        ],
        check=True,
    )
    subprocess.run([*common, str(root / "clip.mp4")], check=True)
    return root


def make_service(tmp_path: Path, downloads: Path) -> AppService:
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    service = AppService(paths, NullPlatform())
    service.settings.update({"download_dir": str(downloads), "max_concurrent": 3, "default_video_format": "mp4"})
    service.start()
    return service


def preview_ready(service, count):
    items = service.preview.items_public()
    return len(items) == count and all(i["status"] in ("ready", "error", "blocked") for i in items)


def test_format_options_mapping():
    assert format_options(DownloadOptions("1080", "mp4", "m4a"), True)["format_sort"][:2] == ["res:1080", "vcodec:h264"]
    assert format_options(DownloadOptions("best", "mkv", "m4a"), True)["merge_output_format"] == "mkv"
    audio = format_options(DownloadOptions("audio", "mp4", "mp3"), True)
    assert audio["postprocessors"][0]["preferredcodec"] == "mp3"
    no_ffmpeg = format_options(DownloadOptions("720", "mp4", "m4a"), False)
    assert no_ffmpeg["format"] == "b[height<=720]/b" and "merge_output_format" not in no_ffmpeg
    from swiftdrop.errors import DownloadFailure

    with pytest.raises(DownloadFailure) as info:
        format_options(DownloadOptions("audio", "mp4", "mp3"), False)
    assert info.value.info.code == "ffmpeg_missing"


class _FakeCtx:
    def __init__(self):
        self.updates: list[ProgressUpdate] = []
        self.token = CancelToken()

    def report(self, update):
        self.updates.append(update)


def test_merged_progress_is_monotonic(monkeypatch):
    ctx = _FakeCtx()
    tracker = _ProgressTracker(ctx)  # type: ignore[arg-type]
    tracker._throttle.ready = lambda force=False: True  # type: ignore[method-assign]
    tracker.plan(
        {
            "requested_formats": [
                {"format_id": "137", "vcodec": "avc1", "filesize": 1000},
                {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "filesize": 200},
            ]
        }
    )
    video, audio = {"format_id": "137"}, {"format_id": "140"}
    for done in (100, 500, 1000):
        tracker.on_progress(
            {"status": "downloading", "downloaded_bytes": done, "total_bytes": 1000, "speed": 100.0, "info_dict": video}
        )
    tracker.on_progress({"status": "finished", "total_bytes": 1000, "info_dict": video})
    for done in (50, 200):
        tracker.on_progress(
            {"status": "downloading", "downloaded_bytes": done, "total_bytes": 200, "speed": 100.0, "info_dict": audio}
        )
    values = [u.progress for u in ctx.updates]
    assert values == sorted(values)
    assert values[-1] == pytest.approx(1.0)
    assert ctx.updates[0].total == 1200
    assert ctx.updates[-1].phase == "Downloading audio (2/2)"


def test_hls_stream_downloads_and_merges(tmp_path, http_server, media_dir, downloads_dir):
    http_server.static_dirs["media"] = media_dir
    url = http_server.url("/static/media/hls/index.m3u8")
    service = make_service(tmp_path, downloads_dir)
    try:
        info = service.analyze_text(url)
        assert info["added"][0]["link"]["provider"] == "ytdlp"
        assert wait_for(lambda: preview_ready(service, 1), timeout=60)
        (item,) = service.preview.items_public()
        assert item["status"] == "ready", item["error"]
        result = service.start_downloads([{"id": item["id"], "entries": None}], None, None)
        assert result["created"] == 1
        job_id = result["job_ids"][0]
        assert wait_for(lambda: service.queue.get(job_id).state in (JobState.COMPLETED, JobState.FAILED), timeout=90)
        job = service.queue.get(job_id)
        assert job.state == JobState.COMPLETED, job.error
        path = Path(job.filepath)
        assert path.exists() and path.parent == downloads_dir and path.suffix == ".mp4"
        probe = subprocess.run(
            [str(Path(service.diagnostics()["ffmpeg"]["path"])), "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
        )
        assert "Video: h264" in probe.stderr and "Audio: aac" in probe.stderr
        assert not service.queue.staging_dir(job_id).exists()
    finally:
        service.shutdown()


def test_hls_audio_only_extraction(tmp_path, http_server, media_dir, downloads_dir):
    http_server.static_dirs["media"] = media_dir
    url = http_server.url("/static/media/hls/index.m3u8")
    service = make_service(tmp_path, downloads_dir)
    try:
        service.settings.update({"auto_inspect": False})
        service.analyze_text(url)
        (item,) = service.preview.items_public()
        result = service.start_downloads(
            [{"id": item["id"], "entries": None}], {"quality": "audio", "audio_format": "mp3"}, None
        )
        job_id = result["job_ids"][0]
        assert wait_for(lambda: service.queue.get(job_id).state in (JobState.COMPLETED, JobState.FAILED), timeout=90)
        job = service.queue.get(job_id)
        assert job.state == JobState.COMPLETED, job.error
        assert job.filepath.endswith(".mp3") and job.kind == MediaKind.AUDIO
    finally:
        service.shutdown()


def test_rss_feed_expands_to_playlist_of_direct_jobs(tmp_path, http_server, downloads_dir):
    episodes = {f"episode-{i}.mp3": make_bytes(150_000 + i, seed=i) for i in range(1, 4)}
    items = []
    for name in episodes:
        http_server.add_file(name, episodes[name])
        items.append(
            f"<item><title>Episode {name[-5]}</title><guid>{name}</guid>"
            f'<enclosure url="{http_server.url("/file/" + name)}" length="1" type="audio/mpeg"/></item>'
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<title>Local Test Podcast</title><link>http://example.com</link><description>d</description>"
        + "".join(items)
        + "</channel></rss>"
    ).encode()
    http_server.add_file("feed.xml", feed)
    feed_url = http_server.url("/file/feed.xml?type=application/rss%2Bxml")
    service = make_service(tmp_path, downloads_dir)
    try:
        analyzed = service.analyze_text(feed_url)
        assert len(analyzed["added"]) == 1
        assert wait_for(lambda: preview_ready(service, 1), timeout=60)
        (item,) = service.preview.items_public()
        assert item["status"] == "ready", item["error"]
        assert item["info"]["is_playlist"] and item["info"]["entry_count"] == 3
        entries = service.preview.entries(item["id"])
        chosen = [e["id"] for e in entries[:2]]
        result = service.start_downloads([{"id": item["id"], "entries": chosen}], None, None)
        assert result["created"] == 2
        assert wait_for(lambda: all(j["state"] == "completed" for j in service.queue.jobs_public()), timeout=60)
        jobs = service.queue.jobs_public()
        assert {j["provider"] for j in jobs} == {"direct"}
        (collection,) = service.queue.collections_public()
        assert collection["title"] == "Local Test Podcast" and collection["completed"] == 2
        folder = downloads_dir / "Local Test Podcast"
        assert sorted(p.name for p in folder.iterdir()) == ["episode-1.mp3", "episode-2.mp3"]
        assert (folder / "episode-1.mp3").read_bytes() == episodes["episode-1.mp3"]
        # Adding the feed again skips episodes that were already downloaded.
        service.analyze_text(feed_url)
        assert wait_for(lambda: preview_ready(service, 1), timeout=60)
        (again,) = service.preview.items_public()
        second = service.start_downloads([{"id": again["id"], "entries": None}], None, None)
        assert second["created"] == 1
        assert sum(1 for s in second["skipped"] if s["reason"] == "Already downloaded") == 2
    finally:
        service.shutdown()


def test_html5_page_with_embedded_video(tmp_path, http_server, media_dir, downloads_dir):
    clip = (media_dir / "clip.mp4").read_bytes()
    http_server.add_file("clip.mp4", clip)
    page = (
        f"<html><head><title>Demo page</title></head><body><video controls>"
        f'<source src="{http_server.url("/file/clip.mp4")}" type="video/mp4"></video></body></html>'
    ).encode()
    http_server.add_file("watch", page)
    url = http_server.url("/file/watch?type=text/html")
    service = make_service(tmp_path, downloads_dir)
    try:
        service.analyze_text(url)
        assert wait_for(lambda: preview_ready(service, 1), timeout=60)
        (item,) = service.preview.items_public()
        assert item["status"] == "ready", item["error"]
        assert item["info"]["provider"] == "ytdlp"
        result = service.start_downloads([{"id": item["id"], "entries": None}], None, None)
        job_id = result["job_ids"][0]
        assert wait_for(lambda: service.queue.get(job_id).state in (JobState.COMPLETED, JobState.FAILED), timeout=60)
        job = service.queue.get(job_id)
        assert job.state == JobState.COMPLETED, job.error
        assert Path(job.filepath).stat().st_size > 10_000
    finally:
        service.shutdown()


def test_page_without_media_is_reported_clearly(tmp_path, http_server, downloads_dir):
    service = make_service(tmp_path, downloads_dir)
    try:
        service.analyze_text(http_server.url("/page.html"))
        assert wait_for(lambda: preview_ready(service, 1), timeout=60)
        (item,) = service.preview.items_public()
        assert item["status"] == "error"
        assert item["error"]["code"] == "not_media"
    finally:
        service.shutdown()


def test_pause_and_resume_hls_download(tmp_path, http_server, media_dir, downloads_dir):
    http_server.static_dirs["media"] = media_dir
    http_server.static_rate = 40_000  # slow enough to pause mid-stream
    url = http_server.url("/static/media/hls/index.m3u8")
    service = make_service(tmp_path, downloads_dir)
    try:
        service.settings.update({"auto_inspect": False})
        service.analyze_text(url)
        (item,) = service.preview.items_public()
        job_id = service.start_downloads([{"id": item["id"], "entries": None}], None, None)["job_ids"][0]
        assert wait_for(lambda: (service.queue.get(job_id).downloaded_bytes or 0) > 0, timeout=60)
        service.queue.pause([job_id])
        assert wait_for(lambda: service.queue.get(job_id).state == JobState.PAUSED, timeout=30)
        staging = service.queue.staging_dir(job_id)
        assert staging.exists() and any(staging.iterdir()), "partial data must be kept while paused"
        http_server.static_rate = 0
        service.queue.resume([job_id])
        assert wait_for(lambda: service.queue.get(job_id).state in (JobState.COMPLETED, JobState.FAILED), timeout=90)
        job = service.queue.get(job_id)
        assert job.state == JobState.COMPLETED, job.error
    finally:
        service.shutdown()


def test_cancel_during_extraction_is_respected(tmp_path):
    provider = YtDlpProvider()
    token = CancelToken()
    token.stop(StopReason.CANCEL)

    with pytest.raises(JobStopped):
        provider.inspect("http://127.0.0.1:9/never", token, Settings())


@pytest.mark.network
def test_live_permitted_sources_inspect():
    """Live check (opt-in): CC-licensed Blender content on YouTube, metadata only, no download."""
    provider = YtDlpProvider()
    playlist = provider.inspect(
        "https://www.youtube.com/playlist?list=PLa1F2ddGya_-UvuAqHAksYnB0qL9yWDO6", CancelToken(), Settings()
    )
    assert playlist.is_playlist and len(playlist.entries) > 10
    assert playlist.extractor == "YouTube"
    video = provider.inspect("https://www.youtube.com/watch?v=aqz-KE-bpKQ", CancelToken(), Settings())
    assert not video.is_playlist and "Big Buck Bunny" in video.title
    assert 1080 in video.heights
