"""Spotify songs, albums and playlists, saved from matching YouTube Music tracks.

Spotify's own audio is DRM-protected and is never touched. SwiftDrop reads the
public song list from Spotify's embed page (no sign-in, no cookies), looks each
song up on YouTube Music (then YouTube) and downloads the match through the
yt-dlp provider as audio. A match must have the same title and artist and a
length within a few seconds; anything less is reported as "No matching song
found" rather than downloaded on a guess.

Without signing in, Spotify's embed page lists at most the first 100 songs of a
playlist.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import requests

from swiftdrop import binaries
from swiftdrop.cancel import CancelToken
from swiftdrop.engine.http import DEFAULT_USER_AGENT
from swiftdrop.engine.progress import ProgressUpdate
from swiftdrop.errors import DownloadFailure, classify_exception, classify_http_status, classify_message, failure
from swiftdrop.filenames import sanitize_filename, split_ext
from swiftdrop.logging_setup import get_logger
from swiftdrop.models import DownloadOptions, InspectResult, MediaKind, PlaylistEntry
from swiftdrop.providers.base import DownloadOutcome, JobContext, Provider
from swiftdrop.redact import redact
from swiftdrop.settings import Settings

log = get_logger("spotify")

SPOTIFY_HOSTS = frozenset({"open.spotify.com", "play.spotify.com"})
SHORT_LINK_HOSTS = frozenset({"spotify.link", "spotify.app.link"})
EMBED_TRACK_LIMIT = 100  # the most songs Spotify's embed page lists for a playlist
SEARCH_RESULTS = 8
MUSIC_LOOKUPS = 3  # YouTube Music results looked up in detail per song (each takes a second or two)
_MAX_PAGE_BYTES = 8 * 1024 * 1024

_PATH_RE = re.compile(
    r"^/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(?:embed/)?(track|album|playlist)/([A-Za-z0-9]{22})/?$", re.I
)
_LINK_IN_PAGE_RE = re.compile(r"https://open\.spotify\.com/(track|album|playlist)/([A-Za-z0-9]{22})")
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_ARTIST_SEPARATOR = ",\xa0"  # Spotify joins artists with comma + no-break space ("Tyler, The Creator" is one)
_FEATURING_RE = re.compile(r"\s*[(\[](?:feat|ft|featuring|with)\.?\s[^)\]]*[)\]]", re.I)
# Words that mark another version of a song; a candidate with one is only accepted when the
# Spotify title has it too.
_VERSION_WORDS = (
    "live", "remix", "cover", "karaoke", "instrumental", "acoustic", "sped up", "slowed", "nightcore", "8d",
    "reverb", "reaction", "reacts", "react", "tutorial", "lesson", "mashup", "extended", "demo", "1 hour",
    "bass boosted",
)  # fmt: skip


# -- links ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpotifyLink:
    kind: str  # "track" | "album" | "playlist"
    id: str

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/{self.kind}/{self.id}"

    @property
    def embed_url(self) -> str:
        return f"https://open.spotify.com/embed/{self.kind}/{self.id}"


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def parse_spotify_link(url: str) -> SpotifyLink | None:
    """A Spotify song, album or playlist link; None for anything else (podcasts, artists, …)."""
    if _host(url) not in SPOTIFY_HOSTS:
        return None
    match = _PATH_RE.match(urlsplit(url).path)
    return SpotifyLink(match.group(1).lower(), match.group(2)) if match else None


def is_short_link(url: str) -> bool:
    """spotify.link share links, which redirect to a song, album or playlist."""
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in SHORT_LINK_HOSTS)


# -- song lists --------------------------------------------------------------------------------


@dataclass(frozen=True)
class SpotifyTrack:
    id: str
    title: str
    artists: tuple[str, ...]
    duration: float | None  # seconds
    image: str | None = None

    @property
    def display(self) -> str:
        """ "Artist, Artist - Title": the job title and file name."""
        return f"{', '.join(self.artists)} - {self.title}" if self.artists else self.title


@dataclass(frozen=True)
class SpotifyCollection:
    kind: str  # "album" | "playlist"
    id: str
    name: str
    image: str | None
    tracks: tuple[SpotifyTrack, ...]


def _page_changed(detail: str) -> DownloadFailure:
    return failure(
        "extractor_broken",
        detail,
        title="Couldn't read this Spotify link",
        message="Spotify's page didn't have the song list SwiftDrop expects. Spotify may have changed its website.",
        hint="Try again later, or check for a SwiftDrop update.",
    )


def _largest_image(entity: dict[str, Any]) -> str | None:
    images = (entity.get("visualIdentity") or {}).get("image") or []
    sized = [i for i in images if isinstance(i, dict) and i.get("url")]
    if sized:
        return str(max(sized, key=lambda i: i.get("maxWidth") or 0)["url"])
    sources = (entity.get("coverArt") or {}).get("sources") or []
    return next((str(s["url"]) for s in sources if isinstance(s, dict) and s.get("url")), None)


def _seconds(ms: Any) -> float | None:
    return ms / 1000 if isinstance(ms, int | float) and ms > 0 else None


def parse_embed(html: str, link: SpotifyLink) -> SpotifyTrack | SpotifyCollection:
    """The song (or album/playlist and its songs) described by a Spotify embed page."""
    found = _NEXT_DATA_RE.search(html)
    if not found:
        raise _page_changed("embed page without __NEXT_DATA__")
    try:
        props = json.loads(found.group(1))["props"]["pageProps"]
    except (ValueError, KeyError, TypeError) as exc:
        raise _page_changed(f"unreadable __NEXT_DATA__: {exc}") from exc
    if not isinstance(props, dict):
        raise _page_changed("pageProps is not an object")
    if props.get("status") == 404:
        raise failure(
            "not_found",
            link.url,
            title=f"Spotify {link.kind} not found",
            message=f"This Spotify {link.kind} is private or doesn't exist.",
            hint="Make sure it's public in Spotify, then copy its link again.",
        )
    entity = ((props.get("state") or {}).get("data") or {}).get("entity")
    if not isinstance(entity, dict):
        raise _page_changed("no entity on the embed page")
    image = _largest_image(entity)
    if link.kind == "track":
        artists = tuple(str(a["name"]) for a in entity.get("artists") or [] if isinstance(a, dict) and a.get("name"))
        title = entity.get("title") or entity.get("name")
        if not title:
            raise _page_changed("track without a title")
        return SpotifyTrack(link.id, str(title), artists, _seconds(entity.get("duration")), image)
    items = entity.get("trackList")
    if not isinstance(items, list):
        raise _page_changed("no trackList on the embed page")
    tracks: list[SpotifyTrack] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind, _, track_id = str(item.get("uri") or "").rpartition(":")
        if kind != "spotify:track" or not track_id or not item.get("title"):
            continue  # podcast episodes in a playlist, local files
        artists = tuple(a.strip() for a in str(item.get("subtitle") or "").split(_ARTIST_SEPARATOR) if a.strip())
        tracks.append(SpotifyTrack(track_id, str(item["title"]), artists, _seconds(item.get("duration"))))
    name = str(entity.get("name") or entity.get("title") or f"Spotify {link.kind}")
    return SpotifyCollection(link.kind, link.id, name, image, tuple(tracks))


@dataclass(frozen=True)
class FetchedPage:
    url: str  # after redirects
    text: str


def fetch_page(url: str, token: CancelToken) -> FetchedPage:
    token.raise_if_stopped()
    try:
        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "en"}
        with requests.get(url, headers=headers, timeout=20, stream=True) as response:
            if response.status_code >= 400:
                raise DownloadFailure(classify_http_status(response.status_code, url))
            body = response.raw.read(_MAX_PAGE_BYTES, decode_content=True)
            final_url, encoding = response.url, response.encoding
    except requests.RequestException as exc:
        raise DownloadFailure(classify_exception(exc)) from exc
    token.raise_if_stopped()
    return FetchedPage(final_url, body.decode(encoding or "utf-8", errors="replace"))


# -- matching ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    video_id: str
    title: str
    duration: float | None
    artists: tuple[str, ...] = ()
    channel: str = ""
    music: bool = False  # from YouTube Music (official audio)
    album: str | None = None


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def core_title(title: str) -> str:
    """The song name without "(feat. …)" or " - Remastered 2011"-style suffixes."""
    title = _FEATURING_RE.sub("", title)
    return title.split(" - ", 1)[0].strip() or title


def _title_matches(track: SpotifyTrack, title: str) -> float:
    """Share of the song name's words found in a candidate title (0 when under 80 %)."""
    wanted = _words(core_title(track.title))
    if not wanted:
        return 0.0
    have = set(_words(title))
    share = sum(w in have for w in wanted) / len(wanted)
    return share if share >= 0.8 else 0.0


def _has_phrase(words: list[str], phrase: str) -> bool:
    return f" {phrase} " in f" {' '.join(words)} "


def match_score(track: SpotifyTrack, candidate: Candidate) -> float | None:
    """How well a YouTube result matches a Spotify song; None when it isn't the same recording."""
    if candidate.duration is None:
        return None
    gap = 0.0
    if track.duration is not None:
        gap = abs(candidate.duration - track.duration)
        if gap > max(4.0, track.duration * 0.03):
            return None
    title_share = _title_matches(track, candidate.title)
    if not title_share:
        return None
    candidate_words = _words(candidate.title)
    track_words = _words(track.title)
    if any(_has_phrase(candidate_words, w) and not _has_phrase(track_words, w) for w in _VERSION_WORDS):
        return None
    listed = {a.casefold() for a in candidate.artists}
    haystack = set(_words(" ".join((candidate.title, candidate.channel, *candidate.artists))))
    named = [a for a in track.artists if set(_words(a)) <= haystack]
    if track.artists and not named:
        return None
    score = title_share - gap / 10
    if candidate.music:
        score += 0.5
    if any(a.casefold() in listed for a in track.artists):
        score += 0.3
    return score


class Searcher(Protocol):
    def music(self, query: str, token: CancelToken) -> list[Candidate]: ...

    def details(self, video_id: str, token: CancelToken) -> Candidate: ...

    def videos(self, query: str, token: CancelToken) -> list[Candidate]: ...


class _QuietLogger:
    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.debug("search: %s", redact(msg))

    def error(self, msg: str) -> None:
        log.info("search: %s", redact(msg))


class YouTubeSearch:
    """YouTube Music and YouTube search through yt-dlp: no sign-in and no browser cookies."""

    def _extract(self, url: str, token: CancelToken, *, flat: bool) -> dict[str, Any]:
        import yt_dlp
        from yt_dlp.utils import DownloadError, ExtractorError

        options: dict[str, Any] = {
            "logger": _QuietLogger(),
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 20,
            "extractor_retries": 2,
        }
        if flat:
            options.update({"extract_flat": "in_playlist", "playlistend": SEARCH_RESULTS})
        runtime = binaries.find_js_runtime()
        if runtime:
            options["js_runtimes"] = {runtime.name: {"path": str(runtime.path)}}
        token.raise_if_stopped()
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False, process=flat)
        except (DownloadError, ExtractorError) as exc:
            raise DownloadFailure(classify_message(str(exc))) from exc
        except Exception as exc:
            raise DownloadFailure(classify_exception(exc)) from exc
        token.raise_if_stopped()
        return info if isinstance(info, dict) else {}

    @staticmethod
    def _entries(info: dict[str, Any]) -> list[dict[str, Any]]:
        return [e for e in info.get("entries") or [] if isinstance(e, dict) and e.get("id")]

    def music(self, query: str, token: CancelToken) -> list[Candidate]:
        info = self._extract(f"https://music.youtube.com/search?q={quote(query)}#songs", token, flat=True)
        return [
            Candidate(str(e["id"]), str(e.get("title") or ""), e.get("duration"), music=True)
            for e in self._entries(info)
        ]

    def details(self, video_id: str, token: CancelToken) -> Candidate:
        info = self._extract(f"https://music.youtube.com/watch?v={quote(video_id)}", token, flat=False)
        artists = info.get("artists") or info.get("creators") or []
        return Candidate(
            video_id,
            str(info.get("track") or info.get("title") or ""),
            info.get("duration"),
            tuple(str(a) for a in artists),
            str(info.get("channel") or ""),
            music=True,
            album=info.get("album"),
        )

    def videos(self, query: str, token: CancelToken) -> list[Candidate]:
        info = self._extract(f"ytsearch{SEARCH_RESULTS}:{query}", token, flat=True)
        return [
            Candidate(
                str(e["id"]),
                str(e.get("title") or ""),
                e.get("duration"),
                channel=str(e.get("channel") or e.get("uploader") or ""),
            )
            for e in self._entries(info)
        ]


class SongMatcher:
    def __init__(self, search: Searcher | None = None) -> None:
        self._search = search or YouTubeSearch()

    def find(self, track: SpotifyTrack, token: CancelToken) -> Candidate | None:
        """The best YouTube recording of a Spotify song, or None when nothing matches well enough."""
        artists = " ".join(track.artists[:2])
        title = core_title(track.title)
        # YouTube Music lists official album audio first, but its search results carry no lengths:
        # look up the few whose titles fit.
        looked = 0
        for result in self._safely(self._search.music, f"{artists} {title}", token):
            if looked >= MUSIC_LOOKUPS:
                break
            if not _title_matches(track, result.title):
                continue
            looked += 1
            try:
                candidate = self._search.details(result.video_id, token)
            except DownloadFailure as exc:
                log.info("Couldn't look up %s: %s", result.video_id, exc.info.title)
                continue
            if match_score(track, candidate) is not None:
                return candidate
        scored = [
            (score, candidate)
            for candidate in self._safely(self._search.videos, f"{artists} - {title}", token)
            if (score := match_score(track, candidate)) is not None
        ]
        return max(scored, key=lambda pair: pair[0])[1] if scored else None

    @staticmethod
    def _safely(
        search: Callable[[str, CancelToken], list[Candidate]], query: str, token: CancelToken
    ) -> list[Candidate]:
        try:
            return search(query, token)
        except DownloadFailure as exc:
            log.info("Search failed: %s", exc.info.title)
            return []


# -- tags ------------------------------------------------------------------------------------------


def tag_audio(path: Path, track: SpotifyTrack, album: str | None) -> None:
    """Write title, artist and album tags (best effort: an untagged file is still a good download)."""
    ffmpeg = binaries.find_ffmpeg()
    if ffmpeg is None:
        return
    tagged = path.with_name(f".swiftdrop-tags{path.suffix}")
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-map", "0", "-c", "copy",
        "-metadata", f"title={track.title}", "-metadata", f"artist={', '.join(track.artists)}",
    ]  # fmt: skip
    if album:
        command += ["-metadata", f"album={album}"]
    if path.suffix.lower() == ".mp3":
        command += ["-id3v2_version", "3"]
    command.append(str(tagged))
    try:
        result = subprocess.run(  # fixed executable, argument list (no shell)
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            creationflags=binaries.NO_WINDOW,
        )
        if result.returncode == 0 and tagged.is_file() and tagged.stat().st_size > 0:
            os.replace(tagged, path)
        else:
            log.info("Couldn't tag %s: %s", path.suffix, redact(result.stderr.strip()[-300:]))
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("Couldn't tag %s: %s", path.suffix, exc)
    finally:
        tagged.unlink(missing_ok=True)


# -- provider ----------------------------------------------------------------------------------------


class _MatchedJob:
    """The job as the yt-dlp provider sees it: the YouTube match, as audio, under Spotify's names."""

    def __init__(self, ctx: JobContext, match: Candidate, track: SpotifyTrack) -> None:
        self._ctx = ctx
        self._track = track
        self._album = match.album
        self.url = f"https://www.youtube.com/watch?v={match.video_id}"
        self.options: DownloadOptions = ctx.options.as_audio()
        self.job_id = ctx.job_id
        self.settings: Settings = ctx.settings
        self.token: CancelToken = ctx.token
        self.staging_dir: Path = ctx.staging_dir
        self.meta: dict[str, Any] = ctx.meta  # the job's own dict, so resume state is saved with it
        self.collection_folder = ctx.collection_folder

    def report(self, update: ProgressUpdate) -> None:
        self._ctx.report(update)

    def checkpoint(self) -> None:
        self._ctx.checkpoint()

    def set_info(self, **fields: Any) -> None:
        for name in ("title", "thumbnail", "duration", "extractor"):
            fields.pop(name, None)  # keep the Spotify song's details, not the YouTube video's
        if fields:
            self._ctx.set_info(**fields)

    def finalize(self, source: Path, filename: str, kind: MediaKind) -> Path:
        ext = split_ext(filename)[1] or source.suffix.lstrip(".")
        tag_audio(source, self._track, self._album)
        name = sanitize_filename(f"{self._track.display}.{ext}" if ext else self._track.display)
        return self._ctx.finalize(source, name, MediaKind.AUDIO)


class SpotifyProvider:
    name = "spotify"

    def __init__(
        self,
        ytdlp: Provider,
        *,
        fetch: Callable[[str, CancelToken], FetchedPage | str] | None = None,
        search: Searcher | None = None,
    ) -> None:
        self._ytdlp = ytdlp
        self._fetch = fetch or fetch_page
        self._matcher = SongMatcher(search)

    def _page(self, url: str, token: CancelToken) -> FetchedPage:
        page = self._fetch(url, token)
        return page if isinstance(page, FetchedPage) else FetchedPage(url, page)

    def _resolve(self, url: str, token: CancelToken) -> SpotifyLink:
        link = parse_spotify_link(url)
        if link:
            return link
        if is_short_link(url):
            page = self._page(url, token)
            link = parse_spotify_link(page.url)
            if link:
                return link
            # Browsers get an in-between page that links to the target. A dead link lands on
            # Spotify's home page instead, whose links are someone else's songs.
            found = _LINK_IN_PAGE_RE.search(page.text) if is_short_link(page.url) else None
            if found:
                return SpotifyLink(found.group(1), found.group(2))
        raise failure(
            "unsupported",
            url,
            title="Unsupported Spotify link",
            message="Only Spotify songs, albums and playlists can be downloaded.",
            hint="Copy the link of a song, album or playlist (Share → Copy link).",
        )

    def _load(self, link: SpotifyLink, token: CancelToken) -> SpotifyTrack | SpotifyCollection:
        return parse_embed(self._page(link.embed_url, token).text, link)

    def inspect(self, url: str, token: CancelToken, settings: Settings) -> InspectResult:
        link = self._resolve(url, token)
        loaded = self._load(link, token)
        if isinstance(loaded, SpotifyTrack):
            return InspectResult(
                provider=self.name,
                title=loaded.display,
                kind=MediaKind.AUDIO,
                extractor="Spotify",
                thumbnail=loaded.image,
                duration=loaded.duration,
                has_audio_only=True,
                resolved_url=link.url,
            )
        entries: list[PlaylistEntry] = []
        seen: set[str] = set()
        for index, track in enumerate(loaded.tracks, start=1):
            entry_id = track.id if track.id not in seen else f"{track.id}-{index}"
            seen.add(entry_id)
            entries.append(
                PlaylistEntry(
                    id=entry_id,
                    url=SpotifyLink("track", track.id).url,
                    title=track.display,
                    index=index,
                    duration=track.duration,
                )
            )
        return InspectResult(
            provider=self.name,
            title=loaded.name,
            kind=MediaKind.AUDIO,
            extractor="Spotify",
            thumbnail=loaded.image,
            is_playlist=True,
            entries=entries,
            entries_truncated=loaded.kind == "playlist" and len(loaded.tracks) >= EMBED_TRACK_LIMIT,
            resolved_url=link.url,
        )

    def download(self, ctx: JobContext) -> DownloadOutcome:
        token = ctx.token
        token.raise_if_stopped()
        ctx.report(ProgressUpdate(phase="Finding the song on YouTube"))
        link = self._resolve(ctx.url, token)
        if link.kind != "track":
            raise failure(
                "unsupported",
                f"spotify {link.kind} in a single job",
                title=f"This link is a Spotify {link.kind}",
                message="Spotify playlists and albums are expanded on the New Download screen.",
                hint="Add the link there again to choose which songs to download.",
                retryable=False,
            )
        track, match = _from_meta(ctx.meta.get("spotify"), link.id)
        if track is None:
            loaded = self._load(link, token)
            if not isinstance(loaded, SpotifyTrack):
                raise _page_changed("track link returned a collection")
            track = loaded
        ctx.set_info(
            title=track.display, thumbnail=track.image, duration=track.duration, extractor="Spotify",
            kind=MediaKind.AUDIO,
        )  # fmt: skip
        if match is None:
            match = self._matcher.find(track, token)
            if match is None:
                raise failure("no_match", track.display)
            # Keep the match so a paused download resumes the same recording.
            ctx.meta["spotify"] = {"track": asdict(track), "match": asdict(match)}
        log.info("[%s] Spotify song matched to YouTube %s", ctx.job_id, match.video_id)
        ctx.set_info(extractor="Spotify · YouTube Music" if match.music else "Spotify · YouTube")
        job = _MatchedJob(ctx, match, track)
        try:
            return self._ytdlp.download(job)
        except DownloadFailure as exc:
            if exc.info.code != "forbidden":
                raise
        # YouTube now and then refuses a stream address it has just handed out; a fresh look works.
        log.info("[%s] YouTube refused the stream; trying once more", ctx.job_id)
        token.raise_if_stopped()
        return self._ytdlp.download(job)


def _from_meta(saved: Any, track_id: str) -> tuple[SpotifyTrack | None, Candidate | None]:
    if not isinstance(saved, dict):
        return None, None
    try:
        track_data, match_data = dict(saved["track"]), dict(saved["match"])
        track = SpotifyTrack(**{**track_data, "artists": tuple(track_data["artists"])})
        match = Candidate(**{**match_data, "artists": tuple(match_data["artists"])})
    except (KeyError, TypeError, ValueError):
        return None, None
    return (track, match) if track.id == track_id else (None, None)
