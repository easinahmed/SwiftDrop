"""Services whose media is DRM-protected or that offer no permitted download path.

Links to these services are rejected up front with an explanation and a
compliant alternative instead of failing obscurely later.
"""

from __future__ import annotations

from dataclasses import dataclass

from swiftdrop.errors import make_error
from swiftdrop.models import ErrorInfo


@dataclass(frozen=True)
class RestrictedService:
    name: str
    domains: tuple[str, ...]
    message: str
    alternative: str


_STREAMING_VIDEO = "Use the service's official app to download for offline viewing where your plan allows it."

SERVICES: tuple[RestrictedService, ...] = (
    RestrictedService(
        "Spotify",
        ("open.spotify.com", "play.spotify.com", "spotify.link", "spotify.app.link"),
        "Spotify music and audiobooks are DRM-protected streams, so they can't be saved as files.",
        "Use “Download” in the Spotify app (Premium) for offline listening, or buy DRM-free files from "
        "stores such as Bandcamp. For podcasts, paste the show's public RSS feed URL instead — "
        "SwiftDrop can download podcast episodes from RSS feeds.",
    ),
    RestrictedService(
        "Apple Music",
        ("music.apple.com", "itunes.apple.com"),
        "Apple Music tracks are DRM-protected and can't be downloaded as files.",
        "Use “Download” in the Music app for offline listening, or purchase the track in the iTunes Store.",
    ),
    RestrictedService("Apple TV", ("tv.apple.com",), "Apple TV video is DRM-protected.", _STREAMING_VIDEO),
    RestrictedService("Netflix", ("netflix.com",), "Netflix video is DRM-protected.", _STREAMING_VIDEO),
    RestrictedService("Disney+", ("disneyplus.com",), "Disney+ video is DRM-protected.", _STREAMING_VIDEO),
    RestrictedService("Prime Video", ("primevideo.com",), "Prime Video is DRM-protected.", _STREAMING_VIDEO),
    RestrictedService(
        "Max", ("max.com", "hbomax.com", "play.max.com"), "Max video is DRM-protected.", _STREAMING_VIDEO
    ),
    RestrictedService("Hulu", ("hulu.com",), "Hulu video is DRM-protected.", _STREAMING_VIDEO),
    RestrictedService("Paramount+", ("paramountplus.com",), "Paramount+ video is DRM-protected.", _STREAMING_VIDEO),
    RestrictedService("Peacock", ("peacocktv.com",), "Peacock video is DRM-protected.", _STREAMING_VIDEO),
    RestrictedService(
        "TIDAL",
        ("tidal.com", "listen.tidal.com"),
        "TIDAL streams are DRM-protected.",
        "Use offline mode in the TIDAL app, or buy DRM-free files from a music store.",
    ),
    RestrictedService(
        "Deezer",
        ("deezer.com", "deezer.page.link"),
        "Deezer streams are DRM-protected.",
        "Use offline mode in the Deezer app, or buy DRM-free files from a music store.",
    ),
    RestrictedService(
        "Amazon Music",
        ("music.amazon.com", "music.amazon.co.uk", "music.amazon.de"),
        "Amazon Music streams are DRM-protected.",
        "Use offline mode in the Amazon Music app, or purchase DRM-free MP3s from Amazon's digital store.",
    ),
    RestrictedService(
        "Audible",
        ("audible.com", "audible.co.uk"),
        "Audible audiobooks are DRM-protected.",
        "Use the Audible app's download feature.",
    ),
)


def match_restricted(host: str) -> RestrictedService | None:
    host = host.lower().rstrip(".")
    for service in SERVICES:
        for domain in service.domains:
            if host == domain or host.endswith("." + domain):
                return service
    return None


def restricted_error(service: RestrictedService) -> ErrorInfo:
    return make_error(
        "drm",
        f"{service.name} link",
        title=f"{service.name} isn't supported",
        message=service.message,
        hint=service.alternative,
        retryable=False,
    )
