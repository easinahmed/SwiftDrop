"""Pure format selection that keeps MP4 output QuickTime-compatible."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

HwProbe = Callable[[str], bool]

_QT_NATIVE = ("avc1", "hvc1", "hev1")
_AAC_ARGS = {"merger+ffmpeg_o": ["-c:a", "aac", "-b:a", "192k"]}


_ALIASES = {"h264": "avc1", "avc": "avc1", "avc3": "avc1", "h265": "hvc1", "hevc": "hvc1", "av1": "av01", "vp9": "vp09"}


def _codec(value: Any) -> str:
    name = str(value or "none").split(".")[0].lower()
    return _ALIASES.get(name, name)


def _present(value: Any) -> bool:
    """yt-dlp semantics: the string "none" means absent; a missing codec (None) is unknown, so maybe present."""
    return value is None or _codec(value) != "none"


def _has_video(fmt: dict) -> bool:
    return _present(fmt.get("vcodec")) and fmt.get("ext") != "mhtml"


def _has_audio(fmt: dict) -> bool:
    return _present(fmt.get("acodec")) and fmt.get("ext") != "mhtml"


def _height(fmt: dict) -> int:
    return int(_num(fmt.get("height")))


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _rank(fmt: dict) -> tuple[bool, float]:
    """Sort key: https before m3u8/dash, then higher bitrate."""
    return (fmt.get("protocol") != "https", -_num(fmt.get("tbr")))


def _best(candidates: list[dict]) -> dict:
    return min(candidates, key=_rank)


def _pick_video(pool: list[dict], max_height: int | None, hw: HwProbe, want_hdr: bool) -> dict:
    sdr = [f for f in pool if (f.get("dynamic_range") or "SDR") == "SDR"]
    hdr = [f for f in pool if f not in sdr]
    pool = (hdr or sdr) if want_hdr else (sdr or hdr)
    sized = [f for f in pool if f.get("height")] or pool
    heights = {_height(f) for f in sized}
    # The tallest height that fits the request; when every format is taller, the smallest one.
    fitting = [h for h in heights if max_height is None or h <= max_height]
    target = max(fitting) if fitting else min(heights)
    at_target = [f for f in sized if _height(f) == target]

    def of(*codecs: str) -> list[dict]:
        return [f for f in at_target if _codec(f.get("vcodec")) in codecs]

    for codecs in (("avc1",), ("av01",), ("hvc1", "hev1")):
        if codecs == ("av01",) and not hw("av01"):
            continue
        found = of(*codecs)
        if found:
            return _best(found)
    return _best(at_target)


def pick_streams(
    formats: list[dict],
    max_height: int | None,
    hw_decodes: HwProbe,
    *,
    want_hdr: bool = False,
) -> tuple[dict, dict | None]:
    """Return (video, audio), or (combined, None) when only combined streams exist."""
    video_only = [f for f in formats if _has_video(f) and not _has_audio(f)]
    audio_only = [f for f in formats if _has_audio(f) and not _has_video(f)]
    if video_only and audio_only:
        video = _pick_video(video_only, max_height, hw_decodes, want_hdr)
        mp4a = [f for f in audio_only if _codec(f.get("acodec")) == "mp4a"]

        def abr(f: dict) -> float:
            return _num(f.get("abr")) or _num(f.get("tbr"))

        return video, max(mp4a or audio_only, key=abr)
    combined = [f for f in formats if _has_video(f) and _has_audio(f)]
    if combined:
        return _pick_video(combined, max_height, hw_decodes, want_hdr), None
    if video_only:
        return _pick_video(video_only, max_height, hw_decodes, want_hdr), None
    raise ValueError("no downloadable video format")


def merged_format(video: dict, audio: dict) -> dict:
    """A yt-dlp `_merge`-shaped dict; requested_formats keeps the full originals."""
    parts = [video, audio]
    sizes = [_num(f.get("filesize") or f.get("filesize_approx")) for f in parts]
    return {
        "requested_formats": parts,
        "format": "+".join(str(f["format"]) for f in parts if f.get("format")),
        "format_id": "+".join(str(f["format_id"]) for f in parts),
        "ext": "mp4",
        "protocol": "+".join(str(f.get("protocol") or "https") for f in parts),
        "filesize_approx": int(sum(sizes)) or None,
        "tbr": sum(_num(f.get("tbr") or f.get("vbr") or f.get("abr")) for f in parts),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("fps"),
        "dynamic_range": video.get("dynamic_range"),
        "vcodec": video.get("vcodec"),
        "vbr": video.get("vbr"),
        "acodec": audio.get("acodec"),
        "abr": audio.get("abr"),
        "asr": audio.get("asr"),
        "audio_channels": audio.get("audio_channels"),
    }


def quicktime_selector(max_height: int | None, hw_decodes: HwProbe) -> Callable[[dict], Iterator[dict]]:
    """The yt-dlp `format` callable."""

    def select(ctx: dict) -> Iterator[dict]:
        formats = ctx["formats"]
        try:
            video, audio = pick_streams(formats, max_height, hw_decodes)
        except ValueError:
            # No video at all (an audio-only site): like yt-dlp's trailing "/b", take the best
            # audio-bearing format. yt-dlp sorts ``formats`` worst to best.
            audible = [f for f in formats if _has_audio(f)]
            if audible:
                yield audible[-1]
            return
        yield video if audio is None else merged_format(video, audio)

    return select


def needs_quicktime_conversion(vcodec: str, hw_decodes: HwProbe) -> bool:
    """True unless QuickTime plays the codec: avc1/hvc1/hev1, or av01 with hardware decode."""
    codec = _codec(vcodec)
    if codec in _QT_NATIVE:
        return False
    return not (codec == "av01" and hw_decodes("av01"))


def merger_audio_args(audio: dict | None) -> dict | None:
    """AAC transcode args for the merger when the audio is not already mp4a."""
    if audio is None or _codec(audio.get("acodec")) == "mp4a":
        return None
    return {"merger+ffmpeg_o": list(_AAC_ARGS["merger+ffmpeg_o"])}
