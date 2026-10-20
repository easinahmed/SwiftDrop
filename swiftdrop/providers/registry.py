"""Decides which provider handles a link.

Classification is offline and fast (used while the user is still pasting).
Links that can't be classified offline are resolved on first contact: a
response that is a file goes to the direct engine, a web page goes to yt-dlp's
generic extractor, which finds embedded media where possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from swiftdrop.cancel import CancelToken
from swiftdrop.errors import DownloadFailure, failure
from swiftdrop.filenames import DIRECT_FILE_EXTS, STREAM_MANIFEST_EXTS, kind_for_extension, url_extension
from swiftdrop.logging_setup import get_logger
from swiftdrop.models import ErrorInfo, InspectResult, MediaKind
from swiftdrop.providers.base import DownloadOutcome, JobContext, Provider
from swiftdrop.providers.restricted import match_restricted, restricted_error
from swiftdrop.providers.sites import match_known_site
from swiftdrop.providers.spotify import is_short_link, parse_spotify_link
from swiftdrop.settings import Settings
from swiftdrop.urls import host_of

log = get_logger("registry")


@dataclass(frozen=True)
class SiteMatch:
    extractor: str
    label: str
    playlist_hint: bool


class SiteMatcher(Protocol):
    name: str

    def match(self, url: str) -> SiteMatch | None: ...

    def inspect(self, url: str, token: CancelToken, settings: Settings) -> InspectResult: ...

    def download(self, ctx: JobContext) -> DownloadOutcome: ...


@dataclass
class LinkInfo:
    provider: str  # "direct" | "ytdlp" | "spotify" | "auto" | "blocked"
    kind: MediaKind
    label: str
    extractor: str | None = None
    playlist_hint: bool = False
    blocked: ErrorInfo | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "kind": self.kind.value,
            "label": self.label,
            "extractor": self.extractor,
            "playlist_hint": self.playlist_hint,
            "blocked": self.blocked.to_dict() if self.blocked else None,
        }


class ProviderRegistry:
    def __init__(self, direct: Provider, sites: SiteMatcher | None = None, spotify: Provider | None = None) -> None:
        self.direct = direct
        self.sites = sites
        self.spotify = spotify  # Spotify songs saved from YouTube matches (needs the site engine)

    def classify(self, url: str) -> LinkInfo:
        if self.spotify is not None:
            spotify = parse_spotify_link(url)
            if spotify is not None or is_short_link(url):
                # Short links might be a playlist: they go through inspect, which resolves them.
                playlist = spotify is None or spotify.kind != "track"
                return LinkInfo("spotify", MediaKind.AUDIO, "Spotify", extractor="Spotify", playlist_hint=playlist)
        host = host_of(url)
        service = match_restricted(host)
        if service:
            return LinkInfo("blocked", MediaKind.UNKNOWN, service.name, blocked=restricted_error(service))
        ext = url_extension(url)
        if ext in STREAM_MANIFEST_EXTS:
            label = {"m3u8": "HLS stream", "mpd": "DASH stream"}.get(ext, "Media stream")
            if self.sites is None:
                return LinkInfo("blocked", MediaKind.VIDEO, label, blocked=failure("unsupported").info)
            return LinkInfo("ytdlp", MediaKind.VIDEO, label, extractor="generic")
        if ext in DIRECT_FILE_EXTS:
            return LinkInfo("direct", kind_for_extension(ext), f"{ext.upper()} file")
        if self.sites is not None:
            known = match_known_site(url)
            if known:
                label, playlist = known
                return LinkInfo("ytdlp", MediaKind.VIDEO, label, extractor=label, playlist_hint=playlist)
        return LinkInfo("auto", MediaKind.UNKNOWN, "Web link")

    def site_match(self, url: str) -> SiteMatch | None:
        """Full (slower) check against every site the engine supports."""
        if self.sites is None:
            return None
        try:
            return self.sites.match(url)
        except Exception:  # never let a matcher bug break a download
            log.exception("Site matcher failed")
            return None

    def provider(self, name: str) -> Provider:
        if name == "direct":
            return self.direct
        if name == "ytdlp" and self.sites is not None:
            return self.sites
        if name == "spotify" and self.spotify is not None:
            return self.spotify
        if name == "auto":
            return _AutoProvider(self)
        raise failure("unsupported", f"no provider named {name}")

    def inspect(self, url: str, info: LinkInfo, token: CancelToken, settings: Settings) -> InspectResult:
        if info.blocked:
            raise DownloadFailure(info.blocked)
        if info.provider == "ytdlp" and self.sites is not None:
            return self.sites.inspect(url, token, settings)
        if info.provider == "spotify" and self.spotify is not None:
            return self.spotify.inspect(url, token, settings)
        if info.provider == "auto" and self.site_match(url) is not None:
            return self.sites.inspect(url, token, settings)  # type: ignore[union-attr]
        try:
            result = self.direct.inspect(url, token, settings)
        except DownloadFailure as exc:
            if exc.info.code != "not_media" or self.sites is None:
                raise
        else:
            if self.sites is not None and _is_feed(result.content_type):
                # RSS/Atom feeds are playlists of episodes; fall back to the raw file if not.
                try:
                    return self.sites.inspect(url, token, settings)
                except DownloadFailure:
                    return result
            return result
        # A web page: let the site engine look for embedded media.
        try:
            return self.sites.inspect(url, token, settings)
        except DownloadFailure as exc:
            if exc.info.code in ("unsupported", "extractor_broken", "unknown"):
                raise failure("not_media", exc.info.detail) from exc
            raise


def _is_feed(content_type: str | None) -> bool:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return mime in {
        "application/rss+xml",
        "application/atom+xml",
        "application/xml",
        "text/xml",
        "application/feed+json",
    }


class _AutoProvider:
    """Resolves an unclassified link at download time, then delegates."""

    name = "auto"

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def inspect(self, url: str, token: CancelToken, settings: Settings) -> InspectResult:
        info = LinkInfo("auto", MediaKind.UNKNOWN, "Web link")
        return self._registry.inspect(url, info, token, settings)

    def download(self, ctx: JobContext) -> DownloadOutcome:
        registry = self._registry
        if registry.sites is not None and registry.site_match(ctx.url) is not None:
            ctx.set_info(provider="ytdlp")
            return registry.sites.download(ctx)
        try:
            return registry.direct.download(ctx)
        except DownloadFailure as exc:
            if exc.info.code != "not_media" or registry.sites is None:
                raise
        log.info("Link %s is a web page; trying the site engine", ctx.job_id)
        ctx.set_info(provider="ytdlp")
        try:
            return registry.sites.download(ctx)
        except DownloadFailure as exc:
            if exc.info.code in ("unsupported", "extractor_broken"):
                raise failure("not_media", exc.info.detail) from exc
            raise
