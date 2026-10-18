"""Convert a downloaded video into HEVC (hvc1) MP4 so QuickTime Player can open it.

The encode runs on the Mac's media engine (``hevc_videotoolbox``). Audio is copied
only when it is already AAC (QuickTime plays nothing else reliably in MP4); Opus, Vorbis
and the like are re-encoded to AAC at 192k. FFmpeg always runs as an argument list, never through a shell,
and a stopped job terminates it (then kills it after a grace period).
"""

from __future__ import annotations

import collections
import json
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.errors import failure
from swiftdrop.logging_setup import get_logger

log = get_logger("convert")

DEFAULT_BITRATE = 40_000_000  # bit/s when the source bitrate is unknown
MAX_BITRATE = 60_000_000
BITRATE_FACTOR = 1.5
KILL_GRACE = 3.0  # seconds between terminate and kill

# ffprobe codec names to the yt-dlp style fourcc that format selection reasons about.
_FOURCC = {"h264": "avc1", "hevc": "hvc1", "av1": "av01", "vp9": "vp09", "vp8": "vp8"}


def _is_aac(codec: str | None) -> bool:
    return (codec or "").lower().split(".")[0] in ("aac", "mp4a")


def hevc_bitrate(source_bitrate: int | None) -> int:
    """Target video bitrate: the source rate x 1.5, capped at 60 Mbit/s; 40 Mbit/s when unknown."""
    if not source_bitrate or source_bitrate <= 0:
        return DEFAULT_BITRATE
    return min(int(source_bitrate * BITRATE_FACTOR), MAX_BITRATE)


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(KILL_GRACE)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def convert_for_quicktime(
    src: Path,
    dst: Path,
    *,
    ffmpeg: Path,
    token: CancelToken,
    on_progress: Callable[[float], None],
    duration: float | None,
    source_bitrate: int | None,
    audio_codec: str | None = None,
    ffprobe: Path | None = None,
) -> None:
    """Re-encode ``src`` to HEVC (tagged hvc1) at ``dst``; raises JobStopped when the token stops.

    ``audio_codec`` is the source audio codec when the caller knows it; otherwise it is probed.
    Audio is copied only when AAC, else transcoded to AAC 192k.
    """
    token.raise_if_stopped()
    if audio_codec is None:
        probe = ffprobe or ffmpeg.with_name("ffprobe")
        if probe.exists():
            audio_codec = probe_audio_codec(src, probe)
    audio_args = ["-c:a", "copy"] if _is_aac(audio_codec) else ["-c:a", "aac", "-b:a", "192k"]
    cmd = [
        str(ffmpeg), "-y", "-i", str(src),
        "-c:v", "hevc_videotoolbox", "-tag:v", "hvc1", "-b:v", str(hevc_bitrate(source_bitrate)),
        *audio_args,
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]  # fmt: skip
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace"
    )
    stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
    finished = threading.Event()

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())

    def watch_token() -> None:
        while not finished.is_set():
            if token.wait(0.1):
                _stop(proc)
                return

    threads = [
        threading.Thread(target=drain_stderr, name="ffmpeg-stderr", daemon=True),
        threading.Thread(target=watch_token, name="ffmpeg-cancel", daemon=True),
    ]
    for thread in threads:
        thread.start()
    last = 0.0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            fraction: float | None = None
            if key == "out_time_us" and duration and duration > 0 and value.lstrip("-").isdigit():
                fraction = min(1.0, max(0.0, int(value) / 1_000_000 / duration))
            elif key == "progress" and value == "end":
                fraction = 1.0
            if fraction is not None and fraction >= last and not token.stopped:
                last = fraction
                on_progress(fraction)
        returncode = proc.wait()
    except BaseException:
        _stop(proc)
        dst.unlink(missing_ok=True)
        raise
    finally:
        finished.set()
        for thread in threads:
            thread.join(timeout=KILL_GRACE + 1)
    if token.stopped:
        dst.unlink(missing_ok=True)
        raise JobStopped(token.reason or StopReason.CANCEL)
    if returncode != 0 or not dst.is_file():
        dst.unlink(missing_ok=True)
        detail = " | ".join(stderr_tail) or f"ffmpeg exited with status {returncode}"
        log.warning("QuickTime conversion failed: %s", detail)
        raise failure(
            "ffmpeg_failed",
            detail,
            title="Couldn't convert for QuickTime",
            message="FFmpeg couldn't convert this video into a format QuickTime Player can open.",
            hint="Retry, or choose “Original quality (MKV, may need VLC)” to keep the original codec.",
        )


def merge_streams(
    video: Path,
    audio: Path | None,
    dst: Path,
    *,
    ffmpeg: Path,
    token: CancelToken,
    audio_to_aac: bool,
) -> None:
    """Mux separately downloaded streams into ``dst`` without re-encoding the video.

    Audio is copied, or transcoded to AAC 192k when ``audio_to_aac``. MP4 output gets
    ``+faststart``. Raises JobStopped when the token stops (``dst`` is removed).
    """
    token.raise_if_stopped()
    cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video)]
    if audio is not None:
        cmd += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", "192k"] if audio_to_aac else ["-c:a", "copy"]
    if dst.suffix.lower() == ".mp4":
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(dst))
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, errors="replace"
    )
    stderr = ""
    try:
        while True:
            try:
                _, stderr = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if token.stopped:
                    _stop(proc)
                    dst.unlink(missing_ok=True)
                    raise JobStopped(token.reason or StopReason.CANCEL) from None
    except BaseException:
        _stop(proc)
        raise
    if proc.returncode != 0 or not dst.is_file():
        dst.unlink(missing_ok=True)
        detail = " | ".join((stderr or "").strip().splitlines()[-20:]) or f"ffmpeg exited with status {proc.returncode}"
        log.warning("Merging streams failed: %s", detail)
        raise failure(
            "ffmpeg_failed",
            detail,
            title="Couldn't merge video and audio",
            message="FFmpeg couldn't combine the downloaded video and audio.",
            hint="Retry the download.",
        )


def probe_audio_codec(path: Path, ffprobe: Path) -> str | None:
    """The first audio stream's ffprobe codec name (``aac``, ``opus`` …), or None."""
    cmd = [
        str(ffprobe), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name", "-of", "json", str(path),
    ]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout
        streams = json.loads(out).get("streams") or []
    except (OSError, subprocess.SubprocessError, ValueError):
        log.warning("ffprobe failed on %s", path.name, exc_info=True)
        return None
    return str(streams[0].get("codec_name") or "").lower() or None if streams else None


def probe_video_codec(path: Path, ffprobe: Path) -> tuple[str | None, int | None]:
    """The first video stream's codec as a fourcc (``avc1``, ``vp09`` …) and its bitrate in bit/s.

    Returns ``(None, None)`` when the file has no video stream or ffprobe fails.
    """
    cmd = [
        str(ffprobe), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,codec_tag_string,bit_rate", "-of", "json", str(path),
    ]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout
        streams = json.loads(out).get("streams") or []
    except (OSError, subprocess.SubprocessError, ValueError):
        log.warning("ffprobe failed on %s", path.name, exc_info=True)
        return None, None
    if not streams:
        return None, None
    stream = streams[0]
    name = str(stream.get("codec_name") or "").lower()
    tag = str(stream.get("codec_tag_string") or "").lower()
    codec = tag if name == "hevc" and tag in ("hvc1", "hev1") else _FOURCC.get(name, name or None)
    rate = stream.get("bit_rate")
    return codec, int(rate) if str(rate).isdigit() else None
