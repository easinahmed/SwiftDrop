"""Scrub secrets from text before it is logged or shown as technical detail.

Signed media URLs routinely carry credentials in their query strings
(``sig=``, ``token=``, ``X-Amz-Signature=`` …) and yt-dlp may echo request
headers. Everything that goes to a log file or the "technical details" panel
passes through :func:`redact`.
"""

from __future__ import annotations

import re

_SECRET_PARAM_NAMES = (
    "sig",
    "signature",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "auth",
    "authorization",
    "key",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "pwd",
    "session",
    "sessionid",
    "session_id",
    "sid",
    "cookie",
    "policy",
    "key-pair-id",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "x-goog-signature",
    "x-goog-credential",
    "hdnts",
    "hdnea",
    "hmac",
    "oauth_token",
    "oauth_signature",
    "lsig",
    "nonce",
    # CDN / platform signatures seen in media URLs (TikTok, Meta, generic CDNs, OAuth)
    "x-signature",
    "oh",
    "_nc_ohc",
    "jwt",
    "hash",
    "auth_key",
    "code",
)
_HEADER_NAMES = ("cookie", "set-cookie", "authorization", "proxy-authorization", "x-api-key", "x-auth-token")

# Separators may appear literally (?a=1&sig=…#access_token=…) or percent-encoded inside
# another URL's parameter (…%3Fsig%3D…%26x%3D…); both forms are matched without
# re-encoding the rest of the text.
_SEP = r"(?:[?&;#]|%3F|%26|%23)"
_EQ = r"(?:=|%3D)"
_PARAM_RE = re.compile(
    r"(?P<prefix>" + _SEP + r"(?:" + "|".join(re.escape(n) for n in _SECRET_PARAM_NAMES) + r"))"
    r"(?P<eq>" + _EQ + r")(?P<value>(?:(?!%26|%23)[^&#\s\"'<>])*)",
    re.IGNORECASE,
)
_HEADER_RE = re.compile(
    r"(?P<name>\b(?:" + "|".join(_HEADER_NAMES) + r")\b\s*[:=]\s*)(?P<value>[^\r\n]*)",
    re.IGNORECASE,
)
# Headers rendered as a Python dict or JSON object: {'Cookie': '…'} / {"Authorization": "…"}
_HEADER_DICT_RE = re.compile(
    r"(?P<key>(?P<kq>[\"'])(?:" + "|".join(_HEADER_NAMES) + r")(?P=kq)\s*:\s*)"
    # the value may contain escaped quotes (JSON: \"), which must not end it early
    r"(?P<vq>[\"'])(?P<value>(?:\\.|(?!(?P=vq)|\\).)*?)(?P=vq)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_USERINFO_RE = re.compile(r"(?P<scheme>\bhttps?://)(?P<userinfo>[^/\s:@]+(?::[^/\s@]*)?)@", re.IGNORECASE)

REDACTED = "REDACTED"


def redact(text: object) -> str:
    """Return ``text`` with credentials, tokens and cookies replaced."""
    if text is None:
        return ""
    value = str(text)
    if not value:
        return value
    value = _USERINFO_RE.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", value)
    value = _HEADER_DICT_RE.sub(lambda m: f"{m.group('key')}{m.group('vq')}{REDACTED}{m.group('vq')}", value)
    value = _HEADER_RE.sub(lambda m: f"{m.group('name')}{REDACTED}", value)
    value = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
    value = _PARAM_RE.sub(lambda m: f"{m.group('prefix')}{m.group('eq')}{REDACTED}", value)
    return value
