"""URL extraction, validation, normalisation and duplicate detection.

Users paste anything: one link, hundreds of links, chat transcripts, Markdown,
CSV exports. :func:`extract_urls` pulls every http(s) link out of free text,
:func:`normalize_url` validates and canonicalises a single link and
:func:`dedupe_key` maps equivalent links (``youtu.be/ID`` vs ``youtube.com/watch?v=ID``)
to the same key so duplicates can be flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import SplitResult, parse_qsl, quote, unquote_plus, urlsplit, urlunsplit

MAX_INPUT_CHARS = 2_000_000
MAX_URL_LENGTH = 8192
MAX_URLS_PER_PARSE = 10_000

ALLOWED_SCHEMES = frozenset({"http", "https"})

_SCHEME_URL_RE = re.compile(r"""\b[a-z][a-z0-9+.-]{1,15}://[^\s<>"'`{}|\\^]+""", re.IGNORECASE)
_WWW_URL_RE = re.compile(r"""(?<![\w./@-])www\.[^\s<>"'`{}|\\^]+""", re.IGNORECASE)
# Bare host + path (``youtube.com/watch?v=…``); requires a path so that words
# like ``e.g.`` or ``notes.txt`` are not mistaken for links.
_BARE_URL_RE = re.compile(
    r"""(?<![\w./@:-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?::\d{2,5})?/[^\s<>"'`{}|\\^]*""",
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?'\"*_»”’>"
_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "gbraid",
        "wbraid",
        "msclkid",
        "igshid",
        "igsh",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "yclid",
        "twclid",
        "ttclid",
    }
)
_SITE_TRACKING_PARAMS = {
    "youtube.com": frozenset({"si", "feature", "pp"}),
    "youtu.be": frozenset({"si", "feature"}),
    "open.spotify.com": frozenset({"si"}),
    "instagram.com": frozenset({"img_index"}),
}
_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class InvalidUrlError(ValueError):
    """Raised when a link cannot be downloaded at all (bad scheme, no host …)."""


@dataclass(frozen=True)
class ParsedUrl:
    url: str
    key: str
    original: str


@dataclass
class ParseResult:
    urls: list[ParsedUrl] = field(default_factory=list)
    duplicates: list[ParsedUrl] = field(default_factory=list)
    invalid: list[tuple[str, str]] = field(default_factory=list)
    truncated: bool = False

    @property
    def total_found(self) -> int:
        return len(self.urls) + len(self.duplicates) + len(self.invalid)


def _strip_trailing(candidate: str) -> str:
    """Remove punctuation that belongs to the surrounding prose, not the URL."""
    url = candidate
    while url:
        last = url[-1]
        if last in _TRAILING_PUNCT:
            url = url[:-1]
            continue
        if last in ")]}":
            opener = {")": "(", "]": "[", "}": "{"}[last]
            if url.count(opener) < url.count(last):
                url = url[:-1]
                continue
        break
    return url


def extract_urls(text: str) -> list[str]:
    """Return candidate URL strings in the order they appear in ``text``.

    Matches from the three patterns are merged with a single sorted sweep, so
    the cost stays linear in the number of matches even for huge pastes.
    """
    if not text:
        return []
    matches: list[tuple[int, int, int, str]] = []
    for priority, (regex, prefix) in enumerate(
        ((_SCHEME_URL_RE, ""), (_WWW_URL_RE, "https://"), (_BARE_URL_RE, "https://"))
    ):
        for match in regex.finditer(text):
            raw = _strip_trailing(match.group(0))
            if raw:
                start = match.start()
                matches.append((start, priority, start + len(raw), prefix + raw))
    matches.sort()
    found: list[str] = []
    last_end = -1
    for start, _priority, end, url in matches:
        if start < last_end:
            continue
        found.append(url)
        last_end = end
    return found


def _clean_query(host: str, query: str) -> str:
    """Drop known tracking parameters while keeping every other byte verbatim.

    Signed URLs (S3, CDNs) are computed over the exact query string, so the
    remaining pairs are never re-encoded.
    """
    if not query:
        return ""
    site_params: frozenset[str] = frozenset()
    for domain, params in _SITE_TRACKING_PARAMS.items():
        if host == domain or host.endswith("." + domain):
            site_params = params
            break
    kept = []
    for piece in query.split("&"):
        if not piece:
            continue
        name = unquote_plus(piece.split("=", 1)[0]).lower()
        if name.startswith("utm_") or name in _TRACKING_PARAMS or name in site_params:
            continue
        kept.append(piece)
    return "&".join(kept)


def _encode_host(host: str) -> str:
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidUrlError("The address contains an invalid domain name.") from exc


def normalize_url(raw: str) -> str:
    """Validate ``raw`` and return a canonical http(s) URL.

    Raises :class:`InvalidUrlError` with a user-facing message when the link
    cannot be used.
    """
    if not isinstance(raw, str):
        raise InvalidUrlError("Not a link.")
    candidate = raw.strip()
    if not candidate:
        raise InvalidUrlError("Empty link.")
    if len(candidate) > MAX_URL_LENGTH:
        raise InvalidUrlError("This link is too long to be valid.")
    if "://" not in candidate:
        candidate = "https://" + candidate.lstrip("/")
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise InvalidUrlError("This doesn't look like a valid web address.") from exc
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise InvalidUrlError(f"“{scheme}://” links aren't supported — only http and https.")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError("Links with an embedded username or password aren't supported.")
    try:
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as exc:
        raise InvalidUrlError("The link has an invalid port number.") from exc
    if not host:
        raise InvalidUrlError("The link is missing a domain name.")
    if any(ch.isspace() for ch in host):
        raise InvalidUrlError("The domain name contains spaces.")
    if not host.isascii():
        host = _encode_host(host)
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    elif "." not in host and host != "localhost":
        raise InvalidUrlError("The domain name looks incomplete.")
    netloc = host
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    # Only escape characters that are not allowed in a path (spaces, non-ASCII);
    # existing %-escapes are preserved so encoded slashes keep their meaning.
    path = quote(path, safe="/:@!$&'()*+,;=~%-._")
    query = _clean_query(host.removeprefix("www."), parts.query)
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def display_domain(url: str) -> str:
    host = host_of(url)
    return host[4:] if host.startswith("www.") else host


def _youtube_id(parts: SplitResult) -> str | None:
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    if host == "youtu.be":
        candidate = path.strip("/").split("/")[0]
        return candidate if _YOUTUBE_ID_RE.match(candidate) else None
    if host in _YOUTUBE_HOSTS:
        if path == "/watch":
            for name, value in parse_qsl(parts.query):
                if name == "v" and _YOUTUBE_ID_RE.match(value):
                    return value
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2 and segments[0] in {"shorts", "embed", "live", "v"} and _YOUTUBE_ID_RE.match(segments[1]):
            return segments[1]
    return None


def dedupe_key(url: str) -> str:
    """Key under which equivalent links collapse to one download."""
    parts = urlsplit(url)
    video_id = _youtube_id(parts)
    if video_id:
        return f"youtube:{video_id}"
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    path = parts.path.rstrip("/") or "/"
    query = "&".join(sorted(parts.query.split("&"))) if parts.query else ""
    port = f":{parts.port}" if parts.port else ""
    return f"{host}{port}{path}" + (f"?{query}" if query else "")


def parse_url_list(text: str, known_keys: set[str] | None = None) -> ParseResult:
    """Extract, validate and de-duplicate links from pasted text or a .txt file.

    ``known_keys`` lets callers treat links already present elsewhere (for
    example in the current preview) as duplicates.
    """
    result = ParseResult()
    if not isinstance(text, str) or not text:
        return result
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS]
        result.truncated = True
    seen: set[str] = set(known_keys or ())
    for candidate in extract_urls(text):
        if len(result.urls) >= MAX_URLS_PER_PARSE:
            result.truncated = True
            break
        try:
            url = normalize_url(candidate)
        except InvalidUrlError as exc:
            result.invalid.append((candidate, str(exc)))
            continue
        parsed = ParsedUrl(url=url, key=dedupe_key(url), original=candidate)
        if parsed.key in seen:
            result.duplicates.append(parsed)
            continue
        seen.add(parsed.key)
        result.urls.append(parsed)
    return result
