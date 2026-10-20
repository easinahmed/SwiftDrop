"""Spotify links: song lists read from the public embed page, audio from matching YouTube tracks.

Every test here runs offline against synthetic embed pages and fake search results,
except the ``network`` ones at the bottom.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from swiftdrop.cancel import CancelToken
from swiftdrop.engine.progress import ProgressUpdate
from swiftdrop.errors import DownloadFailure, failure
from swiftdrop.models import DownloadOptions, MediaKind
from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.providers.base import DownloadOutcome
from swiftdrop.providers.registry import ProviderRegistry
from swiftdrop.providers.spotify import (
    Candidate,
    FetchedPage,
    SongMatcher,
    SpotifyLink,
    SpotifyProvider,
    SpotifyTrack,
    match_score,
    parse_embed,
    parse_spotify_link,
    tag_audio,
)
from swiftdrop.service import AppService
from swiftdrop.settings import Settings
from swiftdrop.urls import parse_url_list
from tests.conftest import wait_for

PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"
TRACK_ID = "4cOdK2wGLETKBW3PvgPWqT"


def embed_page(page_props: dict[str, Any]) -> str:
    data = {"props": {"pageProps": page_props}, "page": "/embed/[type]/[id]"}
    return (
        "<!DOCTYPE html><html><head></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
        "</body></html>"
    )


def entity_page(entity: dict[str, Any]) -> str:
    return embed_page({"state": {"data": {"entity": entity}}})


def playlist_entity(tracks: list[dict[str, Any]], kind: str = "playlist") -> dict[str, Any]:
    return {
        "type": kind,
        "name": "Road Trip",
        "title": "Road Trip",
        "subtitle": "Easin",
        "coverArt": {"sources": [{"url": "https://i.scdn.co/image/cover", "width": None, "height": None}]},
        "trackList": tracks,
    }


def track_item(track_id: str, title: str, artists: str, ms: int) -> dict[str, Any]:
    return {"uri": f"spotify:track:{track_id}", "title": title, "subtitle": artists, "duration": ms}


SONGS = [
    track_item("6OmhkSOpvYBokMKQxpIGx2", "Global Warming (feat. Sensato)", "Pitbull,\xa0Sensato", 85400),
    track_item("0000000000000000000002", "EARFQUAKE", "Tyler, The Creator", 190067),
    {"uri": "spotify:episode:0000000000000000000003", "title": "A podcast", "subtitle": "Show", "duration": 1},
    track_item("0000000000000000000004", "আমার সোনার বাংলা", "Rabindranath Tagore", 180000),
]

TRACK_ENTITY = {
    "type": "track",
    "name": "Never Gonna Give You Up",
    "title": "Never Gonna Give You Up",
    "artists": [{"name": "Rick Astley", "uri": "spotify:artist:0gxyHStUsqpMadRV0Di1Qt"}],
    "duration": 213573,
    "visualIdentity": {
        "image": [
            {"url": "https://image-cdn/small", "maxWidth": 64, "maxHeight": 64},
            {"url": "https://image-cdn/large", "maxWidth": 640, "maxHeight": 640},
        ]
    },
}


# -- links -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://open.spotify.com/playlist/{PLAYLIST_ID}?si=abc123", ("playlist", PLAYLIST_ID)),
        (f"https://open.spotify.com/intl-de/track/{TRACK_ID}", ("track", TRACK_ID)),
        (f"https://open.spotify.com/intl-pt-BR/track/{TRACK_ID}", ("track", TRACK_ID)),
        ("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy", ("album", "4aawyAB9vmqN3uQ7FjRGTy")),
        (f"https://open.spotify.com/embed/track/{TRACK_ID}", ("track", TRACK_ID)),
        (f"https://play.spotify.com/track/{TRACK_ID}", ("track", TRACK_ID)),
        ("https://open.spotify.com/episode/0Q86acNRm6V9GYx55SXKwf", None),
        ("https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0", None),
        ("https://open.spotify.com/artist/0gxyHStUsqpMadRV0Di1Qt", None),
        (f"https://example.com/track/{TRACK_ID}", None),
        ("https://open.spotify.com/track/tooShort", None),
        (f"https://open.spotify.com/track/{TRACK_ID}/../../x", None),
    ],
)
def test_parse_spotify_link(url, expected):
    link = parse_spotify_link(url)
    assert (link.kind, link.id) == expected if expected else link is None


def test_link_url_is_canonical():
    assert SpotifyLink("track", TRACK_ID).url == f"https://open.spotify.com/track/{TRACK_ID}"
    assert SpotifyLink("track", TRACK_ID).embed_url == f"https://open.spotify.com/embed/track/{TRACK_ID}"


# -- embed pages ----------------------------------------------------------------------


def test_parse_playlist_embed():
    collection = parse_embed(entity_page(playlist_entity(SONGS)), SpotifyLink("playlist", PLAYLIST_ID))
    assert collection.name == "Road Trip"
    assert collection.image == "https://i.scdn.co/image/cover"
    assert [t.id for t in collection.tracks] == [
        "6OmhkSOpvYBokMKQxpIGx2",
        "0000000000000000000002",
        "0000000000000000000004",
    ]  # the podcast episode is left out
    first, tyler, bangla = collection.tracks
    assert first.artists == ("Pitbull", "Sensato")
    assert first.duration == pytest.approx(85.4)
    assert tyler.artists == ("Tyler, The Creator",)  # only ",<nbsp>" separates artists
    assert bangla.display == "Rabindranath Tagore - আমার সোনার বাংলা"
    assert first.display == "Pitbull, Sensato - Global Warming (feat. Sensato)"


def test_parse_track_embed():
    track = parse_embed(entity_page(TRACK_ENTITY), SpotifyLink("track", TRACK_ID))
    assert isinstance(track, SpotifyTrack)
    assert track.id == TRACK_ID
    assert track.title == "Never Gonna Give You Up"
    assert track.artists == ("Rick Astley",)
    assert track.duration == pytest.approx(213.573)
    assert track.image == "https://image-cdn/large"


def test_missing_playlist_is_reported_as_not_found():
    page = embed_page({"status": 404, "title": "Page not found"})
    with pytest.raises(DownloadFailure) as caught:
        parse_embed(page, SpotifyLink("playlist", PLAYLIST_ID))
    assert caught.value.info.code == "not_found"
    assert "private" in caught.value.info.message


@pytest.mark.parametrize(
    "page",
    [
        "<html>no data here</html>",
        '<script id="__NEXT_DATA__" type="application/json">{not json</script>',
        embed_page({"state": {"data": {}}}),
        entity_page({"type": "playlist", "name": "x", "trackList": "nope"}),
    ],
)
def test_changed_embed_page_fails_clearly(page):
    with pytest.raises(DownloadFailure) as caught:
        parse_embed(page, SpotifyLink("playlist", PLAYLIST_ID))
    assert caught.value.info.code == "extractor_broken"
    assert "Spotify" in caught.value.info.title


# -- matching ----------------------------------------------------------------------------

EXPECTATIONS = SpotifyTrack("x", "expectations (feat. Chappell Roan)", ("Olivia Rodrigo", "Chappell Roan"), 223.935)


def video(title: str, duration: float | None, channel: str = "", artists: tuple[str, ...] = ()) -> Candidate:
    return Candidate(video_id="v", title=title, duration=duration, channel=channel, artists=artists)


def test_official_audio_matches():
    assert match_score(EXPECTATIONS, video("expectations", 224, "Olivia Rodrigo", ("Olivia Rodrigo",))) is not None


def test_lyric_video_with_the_same_length_matches():
    lyric = video("Olivia Rodrigo, Chappell Roan - expectations (Lyric Video)", 225)
    assert match_score(EXPECTATIONS, lyric) is not None


def test_length_mismatch_is_rejected():
    music_video = video("Olivia Rodrigo - expectations (feat. Chappell Roan) (Official Music Video)", 293)
    assert match_score(EXPECTATIONS, music_video) is None


@pytest.mark.parametrize(
    "title",
    [
        "Olivia Rodrigo - expectations (Live at Glastonbury)",
        "Olivia Rodrigo - expectations (Remix)",
        "expectations - Olivia Rodrigo (Karaoke Version)",
        "Olivia Rodrigo - expectations (sped up)",
        "Producer Reacts to Olivia Rodrigo || Expectations",
    ],
)
def test_other_versions_are_rejected(title):
    assert match_score(EXPECTATIONS, video(title, 224)) is None


def test_a_live_song_may_match_a_live_version():
    live = SpotifyTrack("x", "Yellow - Live in Buenos Aires", ("Coldplay",), 300.0)
    assert match_score(live, video("Coldplay - Yellow (Live In Buenos Aires)", 301)) is not None


def test_wrong_artist_is_rejected():
    assert match_score(EXPECTATIONS, video("Someone Else - expectations", 224, "Someone Else")) is None


def test_wrong_title_is_rejected():
    assert match_score(EXPECTATIONS, video("Olivia Rodrigo - happier", 224, "Olivia Rodrigo")) is None


def test_non_latin_titles_match():
    song = SpotifyTrack("x", "আমার সোনার বাংলা", ("Rabindranath Tagore",), 180.0)
    assert match_score(song, video("আমার সোনার বাংলা | Rabindranath Tagore", 182)) is not None


def test_closer_official_audio_scores_higher():
    official = Candidate("a", "expectations", 224, ("Olivia Rodrigo", "Chappell Roan"), "Olivia Rodrigo", music=True)
    lyric = video("Olivia Rodrigo, Chappell Roan - Expectations (Lyrics)", 228, "Vibe Music")
    assert match_score(EXPECTATIONS, official) > match_score(EXPECTATIONS, lyric)


class FakeSearch:
    def __init__(self, music=(), details=None, videos=()):
        self.music_results = list(music)
        self.details_by_id = dict(details or {})
        self.video_results = list(videos)
        self.calls: list[tuple[str, str]] = []

    def music(self, query, token):
        self.calls.append(("music", query))
        return self.music_results

    def details(self, video_id, token):
        self.calls.append(("details", video_id))
        return self.details_by_id[video_id]

    def videos(self, query, token):
        self.calls.append(("videos", query))
        return self.video_results


def test_matcher_prefers_youtube_music_and_checks_details():
    search = FakeSearch(
        music=[Candidate("wrong", "happier", None, music=True), Candidate("song", "expectations", None, music=True)],
        details={"song": Candidate("song", "expectations", 224, ("Olivia Rodrigo",), "Olivia Rodrigo", music=True)},
    )
    match = SongMatcher(search).find(EXPECTATIONS, CancelToken())
    assert match is not None and match.video_id == "song"
    assert ("details", "wrong") not in search.calls  # titles that can't match aren't looked up
    assert not any(kind == "videos" for kind, _ in search.calls)


def test_matcher_falls_back_to_youtube_search():
    search = FakeSearch(
        music=[Candidate("song", "expectations", None, music=True)],
        details={"song": Candidate("song", "expectations", 300, ("Olivia Rodrigo",), music=True)},  # wrong length
        videos=[video("Olivia Rodrigo, Chappell Roan - expectations (Lyric Video)", 225)],
    )
    match = SongMatcher(search).find(EXPECTATIONS, CancelToken())
    assert match is not None and match.title.endswith("(Lyric Video)")


def test_matcher_returns_none_without_a_good_match():
    search = FakeSearch(videos=[video("Olivia Rodrigo - expectations (Live)", 224)])
    assert SongMatcher(search).find(EXPECTATIONS, CancelToken()) is None


def test_matcher_survives_a_failed_detail_lookup():
    class Flaky(FakeSearch):
        def details(self, video_id, token):
            raise failure("network", "connection reset")

    search = Flaky(
        music=[Candidate("song", "expectations", None, music=True)],
        videos=[video("Olivia Rodrigo - expectations (Official Audio)", 224, "Olivia Rodrigo")],
    )
    assert SongMatcher(search).find(EXPECTATIONS, CancelToken()) is not None


# -- provider ------------------------------------------------------------------------------


class FakeYtDlp:
    """Stands in for the yt-dlp provider: writes a file and reports a YouTube title."""

    name = "ytdlp"

    def __init__(self) -> None:
        self.seen: list[tuple[str, DownloadOptions]] = []

    def inspect(self, url, token, settings):  # pragma: no cover - not used
        raise AssertionError

    def download(self, ctx):
        self.seen.append((ctx.url, ctx.options))
        ctx.report(ProgressUpdate(phase="Downloading"))
        ctx.set_info(title="Rick Astley - Never Gonna Give You Up (Official Video) [4K]", quality_label="Audio · M4A")
        path = ctx.staging_dir / "youtube title.m4a"
        path.write_bytes(b"audio")
        final = ctx.finalize(path, path.name, MediaKind.AUDIO)
        return DownloadOutcome(filepath=final, size=5, kind=MediaKind.AUDIO)


def fake_pages(pages: dict[str, str]):
    def fetch(url: str, token: CancelToken) -> str:
        return pages[url]

    return fetch


class FakeContext:
    def __init__(self, tmp_path: Path, url: str) -> None:
        self.job_id = "0123456789abcdef"
        self.url = url
        self.options = DownloadOptions(quality="1080", video_format="mp4", audio_format="m4a")
        self.settings = Settings()
        self.token = CancelToken()
        self.staging_dir = tmp_path / "staging"
        self.staging_dir.mkdir()
        self.meta: dict[str, Any] = {}
        self.collection_folder = None
        self.info: dict[str, Any] = {}
        self.finalized: list[tuple[str, MediaKind]] = []
        self.out = tmp_path / "out"
        self.out.mkdir()

    def report(self, update):
        pass

    def set_info(self, **fields):
        self.info.update(fields)

    def checkpoint(self):
        pass

    def finalize(self, source, filename, kind):
        self.finalized.append((filename, kind))
        target = self.out / filename
        source.rename(target)
        return target


TRACK_URL = f"https://open.spotify.com/track/{TRACK_ID}"
RICK = Candidate("dQw4w9WgXcQ", "Never Gonna Give You Up", 213, ("Rick Astley",), "Rick Astley", music=True)


def make_provider(search: FakeSearch, ytdlp: FakeYtDlp | None = None, pages: dict[str, str] | None = None):
    pages = pages or {SpotifyLink("track", TRACK_ID).embed_url: entity_page(TRACK_ENTITY)}
    return SpotifyProvider(ytdlp or FakeYtDlp(), fetch=fake_pages(pages), search=search)


def test_download_uses_the_youtube_match_and_spotify_names(tmp_path, monkeypatch):
    tagged: list[tuple[Path, SpotifyTrack]] = []
    monkeypatch.setattr(
        "swiftdrop.providers.spotify.tag_audio", lambda path, track, album: tagged.append((path, track))
    )
    ytdlp = FakeYtDlp()
    search = FakeSearch(music=[Candidate("dQw4w9WgXcQ", "Never Gonna Give You Up", None, music=True)],
                        details={"dQw4w9WgXcQ": RICK})  # fmt: skip
    ctx = FakeContext(tmp_path, TRACK_URL)
    outcome = make_provider(search, ytdlp).download(ctx)
    url, options = ytdlp.seen[0]
    assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert options.audio_only and options.audio_format == "m4a"  # always audio, in the chosen format
    assert outcome.filepath.name == "Rick Astley - Never Gonna Give You Up.m4a"
    assert ctx.finalized == [("Rick Astley - Never Gonna Give You Up.m4a", MediaKind.AUDIO)]
    assert ctx.info["title"] == "Rick Astley - Never Gonna Give You Up"  # not the YouTube video title
    assert ctx.info["extractor"] == "Spotify · YouTube Music"  # where the audio really comes from
    assert ctx.info["quality_label"] == "Audio · M4A"
    assert tagged and tagged[0][1].title == "Never Gonna Give You Up"


def test_download_reuses_the_match_after_a_pause(tmp_path, monkeypatch):
    monkeypatch.setattr("swiftdrop.providers.spotify.tag_audio", lambda *a: None)
    search = FakeSearch(music=[Candidate("dQw4w9WgXcQ", "Never Gonna Give You Up", None, music=True)],
                        details={"dQw4w9WgXcQ": RICK})  # fmt: skip
    ctx = FakeContext(tmp_path, TRACK_URL)
    provider = make_provider(search)
    provider.download(ctx)
    search.calls.clear()
    ctx.out = tmp_path / "again"
    ctx.out.mkdir()
    provider.download(ctx)
    assert search.calls == []  # same song, no new search


def test_download_without_a_match_fails_clearly(tmp_path):
    ytdlp = FakeYtDlp()
    with pytest.raises(DownloadFailure) as caught:
        make_provider(FakeSearch(), ytdlp).download(FakeContext(tmp_path, TRACK_URL))
    assert caught.value.info.code == "no_match"
    assert caught.value.info.retryable is False
    assert ytdlp.seen == []  # nothing is downloaded on a guess


def test_inspect_playlist(tmp_path):
    link = SpotifyLink("playlist", PLAYLIST_ID)
    provider = make_provider(FakeSearch(), pages={link.embed_url: entity_page(playlist_entity(SONGS))})
    result = provider.inspect(link.url, CancelToken(), Settings())
    assert result.provider == "spotify" and result.is_playlist
    assert result.kind == MediaKind.AUDIO
    assert result.extractor == "Spotify"
    assert result.title == "Road Trip"
    assert [e.url for e in result.entries][:1] == ["https://open.spotify.com/track/6OmhkSOpvYBokMKQxpIGx2"]
    assert result.entries[0].title == "Pitbull, Sensato - Global Warming (feat. Sensato)"
    assert result.entries[0].duration == pytest.approx(85.4)
    assert not result.entries_truncated


def test_inspect_marks_a_100_song_playlist_as_partial():
    tracks = [track_item(f"{n:022d}", f"Song {n}", "Artist", 200000) for n in range(100)]
    link = SpotifyLink("playlist", PLAYLIST_ID)
    provider = make_provider(FakeSearch(), pages={link.embed_url: entity_page(playlist_entity(tracks))})
    result = provider.inspect(link.url, CancelToken(), Settings())
    assert len(result.entries) == 100 and result.entries_truncated


def test_inspect_track():
    result = make_provider(FakeSearch()).inspect(TRACK_URL, CancelToken(), Settings())
    assert not result.is_playlist
    assert result.title == "Rick Astley - Never Gonna Give You Up"
    assert result.kind == MediaKind.AUDIO and result.thumbnail == "https://image-cdn/large"


def test_playlist_link_in_a_single_job_is_refused(tmp_path):
    ctx = FakeContext(tmp_path, f"https://open.spotify.com/playlist/{PLAYLIST_ID}")
    with pytest.raises(DownloadFailure) as caught:
        make_provider(FakeSearch()).download(ctx)
    assert "playlist" in caught.value.info.title.lower()


# -- registry ---------------------------------------------------------------------------------


def test_registry_routes_spotify_music_links():
    registry = ProviderRegistry(direct=object(), sites=object(), spotify=make_provider(FakeSearch()))  # type: ignore[arg-type]
    playlist = registry.classify(f"https://open.spotify.com/playlist/{PLAYLIST_ID}")
    assert (playlist.provider, playlist.kind, playlist.playlist_hint) == ("spotify", MediaKind.AUDIO, True)
    track = registry.classify(TRACK_URL)
    assert (track.provider, track.playlist_hint, track.label) == ("spotify", False, "Spotify")
    assert registry.classify("https://spotify.link/AbCdEf123").provider == "spotify"
    podcast = registry.classify("https://open.spotify.com/episode/0Q86acNRm6V9GYx55SXKwf")
    assert podcast.provider == "blocked" and podcast.blocked is not None
    assert "podcast" in podcast.blocked.message.lower()


def test_registry_without_spotify_support_keeps_it_blocked():
    registry = ProviderRegistry(direct=object(), sites=None)  # type: ignore[arg-type]
    assert registry.classify(TRACK_URL).provider == "blocked"


# -- service: preview → queue → file ------------------------------------------------------------


def test_spotify_playlist_downloads_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr("swiftdrop.providers.spotify.tag_audio", lambda *a: None)
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    svc = AppService(paths, NullPlatform(), enable_sites=False)
    link = SpotifyLink("playlist", PLAYLIST_ID)
    songs = [SONGS[0], SONGS[1]]
    pages = {link.embed_url: entity_page(playlist_entity(songs))}
    for item in songs:
        track_id = item["uri"].rsplit(":", 1)[1]
        artists = [{"name": a} for a in item["subtitle"].split(",\xa0")]
        entity = {"type": "track", "title": item["title"], "artists": artists, "duration": item["duration"]}
        pages[SpotifyLink("track", track_id).embed_url] = entity_page(entity)
    search = FakeSearch(
        videos=[
            video("Pitbull - Global Warming ft. Sensato", 86, "Pitbull"),
            video("Tyler, The Creator - EARFQUAKE (Audio)", 190, "Tyler, The Creator"),
        ]
    )
    svc.registry.spotify = SpotifyProvider(FakeYtDlp(), fetch=fake_pages(pages), search=search)
    svc.settings.update({"download_dir": str(downloads), "auto_inspect": True})
    svc.start()
    try:
        (item,) = svc.analyze_text(link.url)["added"]
        assert item["link"]["provider"] == "spotify"
        assert wait_for(lambda: svc.preview.get(item["id"]).info is not None)
        result = svc.start_downloads([{"id": item["id"], "entries": None}], {"quality": "1080"}, None)
        assert result["created"] == 2
        assert wait_for(lambda: svc.queue.stats()["counts"]["completed"] == 2, timeout=20)
        jobs = svc.queue.jobs_public(result["job_ids"])
        assert {j["provider"] for j in jobs} == {"spotify"}
        assert all(svc.queue.get(i).options.audio_only for i in result["job_ids"])
        assert {j["quality_label"] for j in jobs} == {"Audio · M4A"}
        names = sorted(p.name for p in downloads.rglob("*.m4a"))
        assert names == ["Pitbull, Sensato - Global Warming (feat. Sensato).m4a", "Tyler, The Creator - EARFQUAKE.m4a"]
    finally:
        svc.shutdown()


# -- tags ------------------------------------------------------------------------------------------


@pytest.mark.ffmpeg
def test_tag_audio_writes_title_and_artist(tmp_path):
    from swiftdrop.binaries import NO_WINDOW, find_ffmpeg, find_ffprobe

    ffmpeg, ffprobe = find_ffmpeg(), find_ffprobe()
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg not available")
    path = tmp_path / "song.m4a"
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac",
         str(path)],
        check=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
    )  # fmt: skip
    track = SpotifyTrack(TRACK_ID, "Never Gonna Give You Up", ("Rick Astley",), 1.0)
    tag_audio(path, track, "Whenever You Need Somebody")
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
    )  # fmt: skip
    tags = {k.lower(): v for k, v in json.loads(out.stdout)["format"]["tags"].items()}
    assert tags["title"] == "Never Gonna Give You Up"
    assert tags["artist"] == "Rick Astley"
    assert tags["album"] == "Whenever You Need Somebody"
    assert list(tmp_path.iterdir()) == [path]  # no temporary file left behind


def test_tag_audio_never_breaks_the_download(tmp_path):
    path = tmp_path / "not-audio.m4a"
    path.write_bytes(b"this is not audio")
    tag_audio(path, SpotifyTrack(TRACK_ID, "T", ("A",), 1.0), None)
    assert path.read_bytes() == b"this is not audio"
    assert list(tmp_path.iterdir()) == [path]


# -- live (SWIFTDROP_NETWORK_TESTS=1) ------------------------------------------------------------------


@pytest.mark.network
def test_live_spotify_playlist_and_match():
    provider = SpotifyProvider(FakeYtDlp())
    result = provider.inspect(f"https://open.spotify.com/playlist/{PLAYLIST_ID}", CancelToken(), Settings())
    assert result.is_playlist and len(result.entries) >= 10
    track = SpotifyTrack(TRACK_ID, "Never Gonna Give You Up", ("Rick Astley",), 213.573)
    match = SongMatcher().find(track, CancelToken())
    assert match is not None and abs((match.duration or 0) - 213.573) < 5


def test_single_spotify_song_is_queued_as_audio(tmp_path):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    (tmp_path / "Downloads").mkdir()
    svc = AppService(paths, NullPlatform(), enable_sites=False)
    svc.registry.spotify = make_provider(FakeSearch())
    svc.settings.update({"download_dir": str(tmp_path / "Downloads"), "auto_inspect": False})
    try:
        (item,) = svc.analyze_text(TRACK_URL)["added"]
        (job_id,) = svc.start_downloads([{"id": item["id"], "entries": None}], {"quality": "1080"}, None)["job_ids"]
        job = svc.queue.get(job_id)
        assert job.provider == "spotify" and job.options.audio_only and job.kind == MediaKind.AUDIO
        assert job.quality_label == "Audio · M4A"
    finally:
        svc.shutdown()


def test_copied_spotify_links_count_as_downloadable(tmp_path):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    svc = AppService(paths, NullPlatform(), enable_sites=False)
    svc.registry.spotify = make_provider(FakeSearch())
    try:
        links = parse_url_list(f"{TRACK_URL} https://open.spotify.com/episode/0Q86acNRm6V9GYx55SXKwf").urls
        assert [p.url for p in svc._downloadable(links)] == [TRACK_URL]
    finally:
        svc.shutdown()


def test_a_refused_youtube_stream_is_tried_once_more(tmp_path, monkeypatch):
    monkeypatch.setattr("swiftdrop.providers.spotify.tag_audio", lambda *a: None)

    class RefusedOnce(FakeYtDlp):
        def download(self, ctx):
            if not self.seen:
                self.seen.append((ctx.url, ctx.options))
                raise failure("forbidden", "HTTP Error 403: Forbidden")
            return super().download(ctx)

    search = FakeSearch(music=[Candidate("dQw4w9WgXcQ", "Never Gonna Give You Up", None, music=True)],
                        details={"dQw4w9WgXcQ": RICK})  # fmt: skip
    ytdlp = RefusedOnce()
    outcome = make_provider(search, ytdlp).download(FakeContext(tmp_path, TRACK_URL))
    assert outcome.filepath.name == "Rick Astley - Never Gonna Give You Up.m4a"
    assert len(ytdlp.seen) == 2


def test_a_youtube_fallback_match_is_labelled(tmp_path, monkeypatch):
    monkeypatch.setattr("swiftdrop.providers.spotify.tag_audio", lambda *a: None)
    search = FakeSearch(videos=[video("Rick Astley - Never Gonna Give You Up (Official Audio)", 213, "Rick Astley")])
    ctx = FakeContext(tmp_path, TRACK_URL)
    make_provider(search).download(ctx)
    assert ctx.info["extractor"] == "Spotify · YouTube"


def test_a_stream_refused_twice_fails(tmp_path):
    class Refused(FakeYtDlp):
        def download(self, ctx):
            self.seen.append((ctx.url, ctx.options))
            raise failure("forbidden", "HTTP Error 403: Forbidden")

    search = FakeSearch(music=[Candidate("dQw4w9WgXcQ", "Never Gonna Give You Up", None, music=True)],
                        details={"dQw4w9WgXcQ": RICK})  # fmt: skip
    ytdlp = Refused()
    with pytest.raises(DownloadFailure) as caught:
        make_provider(search, ytdlp).download(FakeContext(tmp_path, TRACK_URL))
    assert caught.value.info.code == "forbidden" and len(ytdlp.seen) == 2


SHORT = "https://spotify.link/zLIDHxA0bKb"


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (FetchedPage(TRACK_URL + "?si=x&_branch_match_id=1", "<html></html>"), TRACK_URL),  # plain redirect
        (  # Branch's in-between page, which links to the target
            FetchedPage("https://spotify.app.link/zLIDHxA0bKb?_p=c1", f'<a href="{TRACK_URL}">Open</a>'),
            TRACK_URL,
        ),
    ],
)
def test_short_links_resolve(page, expected):
    provider = SpotifyProvider(
        FakeYtDlp(), fetch=lambda url, token: page if url == SHORT else entity_page(TRACK_ENTITY), search=FakeSearch()
    )
    result = provider.inspect(SHORT, CancelToken(), Settings())
    assert result.resolved_url == expected


def test_expired_short_link_never_picks_a_song_from_the_home_page():
    home = FetchedPage("https://open.spotify.com/", f'<a href="https://open.spotify.com/playlist/{PLAYLIST_ID}">x</a>')
    provider = SpotifyProvider(FakeYtDlp(), fetch=lambda url, token: home, search=FakeSearch())
    with pytest.raises(DownloadFailure) as caught:
        provider.inspect(SHORT, CancelToken(), Settings())
    assert caught.value.info.title == "Unsupported Spotify link"
