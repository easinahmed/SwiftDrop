"""Instant, offline recognition of popular media sites.

Matching a URL against yt-dlp's ~1,750 extractors costs ~2 ms per link (plus a
multi-second import), so pasting 1,000 links can't wait for it. This table
labels well-known sites immediately; everything else is resolved by the
background inspector.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class KnownSite:
    label: str
    domains: tuple[str, ...]
    playlist_pattern: re.Pattern[str] | None = None


KNOWN_SITES: tuple[KnownSite, ...] = (
    KnownSite(
        "YouTube",
        ("youtube.com", "youtu.be", "youtube-nocookie.com"),
        re.compile(r"[?&]list=|/playlist\b|/@[^/]+/?(?:videos|shorts|streams|playlists)?/?$|/channel/|/c/|/user/"),
    ),
    KnownSite("Vimeo", ("vimeo.com",), re.compile(r"/(?:showcase|album|channels)/")),
    KnownSite("SoundCloud", ("soundcloud.com",), re.compile(r"/sets/")),
    KnownSite("Bandcamp", ("bandcamp.com",), re.compile(r"/album/")),
    KnownSite("Internet Archive", ("archive.org",)),
    KnownSite("X (Twitter)", ("twitter.com", "x.com")),
    KnownSite("TikTok", ("tiktok.com",)),
    KnownSite("Instagram", ("instagram.com",)),
    KnownSite("Facebook", ("facebook.com", "fb.watch")),
    KnownSite("Reddit", ("reddit.com", "redd.it")),
    KnownSite("Twitch", ("twitch.tv",), re.compile(r"/videos/?$|/collections/")),
    KnownSite("Dailymotion", ("dailymotion.com", "dai.ly"), re.compile(r"/playlist/")),
    KnownSite("Mixcloud", ("mixcloud.com",)),
    KnownSite("Streamable", ("streamable.com",)),
    KnownSite("TED", ("ted.com",)),
    KnownSite("Loom", ("loom.com",)),
    KnownSite("Rumble", ("rumble.com",)),
    KnownSite("Odysee", ("odysee.com",)),
    KnownSite("Bilibili", ("bilibili.com", "b23.tv")),
    KnownSite("Imgur", ("imgur.com",)),
    KnownSite("Apple Podcasts", ("podcasts.apple.com",)),
    KnownSite("Kick", ("kick.com",)),
    KnownSite("Pinterest", ("pinterest.com",)),
    KnownSite("Tumblr", ("tumblr.com",)),
    KnownSite("Flickr", ("flickr.com",)),
    KnownSite("Vevo", ("vevo.com",)),
    KnownSite("Audiomack", ("audiomack.com",)),
    KnownSite("NPR", ("npr.org",)),
    KnownSite("BBC", ("bbc.co.uk", "bbc.com")),
)


def match_known_site(url: str) -> tuple[str, bool] | None:
    """Return (label, looks_like_playlist) for well-known media sites."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    for site in KNOWN_SITES:
        if any(host == d or host.endswith("." + d) for d in site.domains):
            rest = parts.path + (f"?{parts.query}" if parts.query else "")
            playlist = bool(site.playlist_pattern and site.playlist_pattern.search(rest))
            return site.label, playlist
    return None


_PRETTY = {
    "youtube": "YouTube",
    "soundcloud": "SoundCloud",
    "vimeo": "Vimeo",
    "bandcamp": "Bandcamp",
    "archive.org": "Internet Archive",
    "twitter": "X (Twitter)",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "reddit": "Reddit",
    "twitch": "Twitch",
    "dailymotion": "Dailymotion",
    "generic": "Web page",
    "mixcloud": "Mixcloud",
    "applepodcasts": "Apple Podcasts",
}
_PLAYLIST_WORDS = (
    "playlist",
    "tab",
    "album",
    "channel",
    "user",
    "set",
    "collection",
    "show",
    "series",
    "season",
    "showcase",
    "list",
    "feed",
    "favorites",
    "likes",
)


def pretty_extractor(name: str | None) -> str:
    if not name:
        return "Web page"
    base = name.split(":", 1)[0]
    lowered = base.lower()
    return _PRETTY.get(lowered, base[:1].upper() + base[1:])


def extractor_is_playlist(name: str | None) -> bool:
    if not name or ":" not in name:
        return False
    suffix = name.split(":", 1)[1].lower()
    return any(word in suffix for word in _PLAYLIST_WORDS)
