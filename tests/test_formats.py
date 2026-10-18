"""Pure format selection for QuickTime-compatible MP4 output."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from swiftdrop.platform.codecs import hardware_decodes
from swiftdrop.providers.formats import (
    merged_format,
    merger_audio_args,
    needs_quicktime_conversion,
    pick_streams,
    quicktime_selector,
)

FIXTURE = Path(__file__).parent / "fixtures" / "yt_formats_ri1Ar5nEq4s.json"


def _formats() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def _av1_hw(fourcc: str) -> bool:
    return fourcc in {"av01", "avc1", "hvc1"}


def _no_hw(fourcc: str) -> bool:
    return False


def test_2160_with_av1_hw_picks_401_140() -> None:
    video, audio = pick_streams(_formats(), 2160, _av1_hw)
    assert video["format_id"] == "401"
    assert audio is not None and audio["format_id"] == "140"


def test_2160_without_av1_hw_picks_vp9_https_and_flags_conversion() -> None:
    video, audio = pick_streams(_formats(), 2160, _no_hw)
    assert video["format_id"] == "315"
    assert audio is not None and audio["format_id"] == "140"
    assert needs_quicktime_conversion("vp9", _no_hw) is True


def test_best_with_av1_hw_picks_4320_av1() -> None:
    video, _ = pick_streams(_formats(), None, _av1_hw)
    assert video["format_id"] == "571"


def test_1080_picks_avc1_https_299() -> None:
    video, _ = pick_streams(_formats(), 1080, _av1_hw)
    assert video["format_id"] == "299"


def test_skips_storyboard_and_prefers_sdr() -> None:
    for limit in (None, 2160, 1080):
        video, _ = pick_streams(_formats(), limit, _av1_hw, want_hdr=False)
        assert video["format_id"] not in {"701", "sb0"}
    hdr, _ = pick_streams(_formats(), 2160, _av1_hw, want_hdr=True)
    assert hdr["format_id"] == "701"


def test_opus_only_audio_gets_aac_merge_args() -> None:
    formats = [f for f in _formats() if not str(f.get("acodec")).startswith("mp4a")]
    _, audio = pick_streams(formats, 1080, _av1_hw)
    assert audio is not None and audio["acodec"] == "opus"
    assert merger_audio_args(audio) == {"merger+ffmpeg_o": ["-c:a", "aac", "-b:a", "192k"]}
    mp4a = next(f for f in _formats() if f["format_id"] == "140")
    assert merger_audio_args(mp4a) is None


def test_needs_conversion_rules() -> None:
    assert not needs_quicktime_conversion("avc1.64002A", _no_hw)
    assert not needs_quicktime_conversion("hev1.1.6.L93", _no_hw)
    assert needs_quicktime_conversion("av01.0.13M.08", _no_hw)
    assert not needs_quicktime_conversion("av01.0.13M.08", _av1_hw)


def test_selector_yields_merged_dict_with_required_keys() -> None:
    select = quicktime_selector(2160, _av1_hw)
    out = list(select({"formats": _formats(), "incomplete_formats": False}))
    assert len(out) == 1
    merged = out[0]
    for key in (
        "requested_formats",
        "format_id",
        "ext",
        "protocol",
        "vcodec",
        "acodec",
        "height",
        "width",
        "fps",
        "dynamic_range",
        "filesize_approx",
    ):
        assert key in merged
    assert merged["format_id"] == "401+140"
    assert merged["ext"] == "mp4"
    assert merged["protocol"] == "https+https"
    assert [f["format_id"] for f in merged["requested_formats"]] == ["401", "140"]
    assert merged["height"] == 2160


def test_merged_format_sums_sizes() -> None:
    video = {"format_id": "v", "protocol": "https", "vcodec": "avc1", "filesize": 10}
    audio = {"format_id": "a", "protocol": "https", "acodec": "mp4a", "filesize_approx": 5}
    assert merged_format(video, audio)["filesize_approx"] == 15


@pytest.mark.skipif(sys.platform != "darwin", reason="VideoToolbox is macOS only")
def test_hardware_decodes_returns_bool() -> None:
    assert isinstance(hardware_decodes("vp09"), bool)


def test_height_below_all_formats_picks_lowest() -> None:
    formats = [f for f in _formats() if not f.get("height") or f["height"] >= 480 or f.get("ext") == "mhtml"]
    video, audio = pick_streams(formats, 360, _av1_hw)
    assert video["height"] == 480
    assert video["format_id"] == "135"  # avc1 over https, not the 4K stream
    assert audio is not None and audio["format_id"] == "140"


def test_missing_requested_height_prefers_codec_at_next_lower() -> None:
    formats = [
        f
        for f in _formats()
        if f.get("height") != 1080 and not (f.get("height") == 720 and str(f.get("vcodec")).startswith("avc1"))
    ]
    video, _ = pick_streams(formats, 1080, _av1_hw)
    assert video["format_id"] == "398"  # AV1 at 720 beats the higher-bitrate VP9 at 720


def test_unknown_codecs_are_a_combined_stream() -> None:
    generic = [{"format_id": "0", "ext": "mp4", "protocol": "m3u8_native", "vcodec": None, "acodec": None}]
    video, audio = pick_streams(generic, 1080, _av1_hw)
    assert video["format_id"] == "0" and audio is None
    assert list(quicktime_selector(None, _av1_hw)({"formats": generic})) == generic


def test_selector_falls_back_to_audio_when_no_video() -> None:
    audio_only = [f for f in _formats() if f.get("vcodec") == "none" and f.get("ext") != "mhtml"]
    out = list(quicktime_selector(1080, _av1_hw)({"formats": audio_only}))
    assert len(out) == 1 and out[0]["vcodec"] == "none"
    assert list(quicktime_selector(1080, _av1_hw)({"formats": []})) == []


def test_raw_codec_names_are_normalised() -> None:
    # TikTok / archive.org style names: no needless re-encode, avc1 still preferred.
    assert needs_quicktime_conversion("h264", lambda c: False) is False
    assert needs_quicktime_conversion("h265", lambda c: False) is False
    formats = [
        {"format_id": "a", "vcodec": "h265", "acodec": "aac", "height": 720, "ext": "mp4", "protocol": "https"},
        {"format_id": "b", "vcodec": "h264", "acodec": "aac", "height": 720, "ext": "mp4", "protocol": "https"},
    ]
    video, audio = pick_streams(formats, 720, lambda c: False)
    assert video["format_id"] == "b" and audio is None
