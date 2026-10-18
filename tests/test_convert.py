"""Convert-for-QuickTime (HEVC via VideoToolbox) and the yt-dlp format options that lead to it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.media import convert
from swiftdrop.media.convert import convert_for_quicktime, hevc_bitrate, probe_audio_codec
from swiftdrop.models import DownloadOptions
from swiftdrop.providers.ytdlp import format_options

FIXTURE = Path(__file__).parent / "fixtures" / "yt_formats_ri1Ar5nEq4s.json"


@pytest.fixture
def vt_ffmpeg(ffmpeg_path):
    encoders = subprocess.run([str(ffmpeg_path), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "hevc_videotoolbox" not in encoders:
        pytest.skip("ffmpeg has no hevc_videotoolbox encoder")
    return ffmpeg_path


def _make_clip(ffmpeg: Path, dst: Path, seconds: int, codec: list[str]) -> Path:
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", str(seconds),
         *codec, "-pix_fmt", "yuv420p", str(dst)],
        check=True,
    )  # fmt: skip
    return dst


def _probe_video(ffmpeg: Path, path: Path) -> dict:
    ffprobe = ffmpeg.with_name("ffprobe")
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,codec_tag_string", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)["streams"][0]


@pytest.mark.ffmpeg
def test_convert_for_quicktime_produces_hvc1(tmp_path, vt_ffmpeg):
    vp9 = ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8"]
    src = _make_clip(vt_ffmpeg, tmp_path / "vp9.mp4", 2, vp9)
    assert _probe_video(vt_ffmpeg, src)["codec_name"] == "vp9"
    dst = tmp_path / "out.mp4"
    seen: list[float] = []
    convert_for_quicktime(
        src, dst, ffmpeg=vt_ffmpeg, token=CancelToken(), on_progress=seen.append, duration=2.0, source_bitrate=None
    )
    stream = _probe_video(vt_ffmpeg, dst)
    assert (stream["codec_name"], stream["codec_tag_string"]) == ("hevc", "hvc1")
    assert seen and max(seen) >= 0.99
    assert seen == sorted(seen)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("acodec", ["libopus", "libvorbis"])
def test_convert_transcodes_non_aac_audio_to_aac(tmp_path, vt_ffmpeg, acodec):
    src = tmp_path / "src.webm"
    subprocess.run(
        [str(vt_ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-t", "2", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-pix_fmt", "yuv420p",
         "-c:a", acodec, str(src)],
        check=True,
    )  # fmt: skip
    dst = tmp_path / "out.mp4"
    convert_for_quicktime(
        src, dst, ffmpeg=vt_ffmpeg, token=CancelToken(), on_progress=lambda f: None, duration=2.0, source_bitrate=None
    )
    assert probe_audio_codec(dst, vt_ffmpeg.with_name("ffprobe")) == "aac"


@pytest.mark.ffmpeg
def test_convert_cancel_kills_ffmpeg(tmp_path, vt_ffmpeg, monkeypatch):
    x264 = ["-c:v", "libx264", "-preset", "ultrafast"]
    src = _make_clip(vt_ffmpeg, tmp_path / "long.mp4", 20, x264)
    dst = tmp_path / "out.mp4"
    created: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(convert.subprocess, "Popen", recording_popen)
    token = CancelToken()

    def on_progress(fraction: float) -> None:
        token.stop(StopReason.CANCEL)

    with pytest.raises(JobStopped) as stopped:
        convert_for_quicktime(
            src, dst, ffmpeg=vt_ffmpeg, token=token, on_progress=on_progress, duration=20.0, source_bitrate=8_000_000,
            audio_codec="aac",
        )
    assert stopped.value.reason == StopReason.CANCEL
    (proc,) = created
    assert proc.poll() is not None, "ffmpeg must not outlive the cancelled job"
    assert not dst.exists()


def test_hevc_bitrate_rules():
    assert hevc_bitrate(None) == 40_000_000
    assert hevc_bitrate(0) == 40_000_000
    assert hevc_bitrate(10_000_000) == 15_000_000
    assert hevc_bitrate(50_000_000) == 60_000_000


def test_format_options_mp4_uses_selector():
    opts = format_options(DownloadOptions(quality="2160", video_format="mp4"), True, lambda c: c == "av01")
    assert callable(opts["format"])
    assert opts["merge_output_format"] == "mp4"
    assert "format_sort" not in opts
    (chosen,) = opts["format"]({"formats": json.loads(FIXTURE.read_text())})
    assert chosen["format_id"] == "401+140"


def test_format_options_mkv_original():
    opts = format_options(DownloadOptions(quality="best", video_format="mkv"), True)
    assert opts["format"] == "bv*+ba/b"
    assert opts["merge_output_format"] == "mkv"
