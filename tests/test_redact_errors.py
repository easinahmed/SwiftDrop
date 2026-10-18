import errno
import logging

import pytest
import requests

from swiftdrop.errors import classify_exception, classify_http_status, classify_message
from swiftdrop.logging_setup import configure_logging, get_logger
from swiftdrop.redact import redact


def test_redacts_query_secrets():
    url = "https://cdn.example.com/v.mp4?id=1&sig=abc123&token=zzz&X-Amz-Signature=deadbeef&keep=yes"
    out = redact(url)
    assert "abc123" not in out and "zzz" not in out and "deadbeef" not in out
    assert "id=1" in out and "keep=yes" in out


def test_redacts_headers_bearer_and_userinfo():
    text = "Cookie: SID=secret; HSID=x\nAuthorization: Bearer abcdefghijkl\nhttps://bob:pw@example.com/x"
    out = redact(text)
    assert "secret" not in out
    assert "abcdefghijkl" not in out
    assert "bob" not in out and "pw@" not in out


def test_log_file_never_contains_secrets(tmp_path):
    log_file = configure_logging(tmp_path)
    log = get_logger("test")
    log.info("fetching %s", "https://x.example.com/a?token=SUPERSECRET")
    try:
        raise ValueError("Cookie: session=TOPSECRET")
    except ValueError:
        log.exception("boom")
    for handler in logging.getLogger("swiftdrop").handlers:
        handler.flush()
    content = log_file.read_text()
    assert "SUPERSECRET" not in content
    assert "TOPSECRET" not in content
    assert "REDACTED" in content


def test_http_status_classification():
    assert classify_http_status(404).code == "not_found"
    assert classify_http_status(403).code == "forbidden"
    assert classify_http_status(429).code == "rate_limited"
    assert classify_http_status(503).code == "server_error"
    assert classify_http_status(401).code == "login_required"


def test_message_classification():
    assert (
        classify_message("ERROR: [youtube] abc: Private video. Sign in if you've been granted access").code == "private"
    )
    assert classify_message("This video is DRM protected").code == "drm"
    assert classify_message("Requested format is not available").code == "format_unavailable"
    assert classify_message("ERROR: Unsupported URL: https://x").code == "unsupported"
    assert classify_message("Unable to download webpage: HTTP Error 404: Not Found").code == "not_found"
    assert classify_message("The uploader has not made this video available in your country").code == "geo_blocked"
    assert classify_message("ffprobe and ffmpeg not found").code == "ffmpeg_missing"
    assert classify_message("Sign in to confirm you're not a bot").code == "bot_check"
    assert classify_message("totally new error").code == "unknown"


def test_exception_classification():
    assert classify_exception(OSError(errno.ENOSPC, "No space left on device")).code == "disk_full"
    assert classify_exception(PermissionError(errno.EACCES, "denied")).code == "permission"
    assert classify_exception(requests.ConnectionError("reset")).code == "network"
    assert classify_exception(requests.ReadTimeout("slow")).code == "timeout"
    detail = classify_exception(requests.ConnectionError("https://e.com/?token=SECRET")).detail
    assert "SECRET" not in detail


@pytest.mark.parametrize(
    "text",
    [
        "https://cdn.example.com/v.mp4?x-signature=SECRETV",
        "https://scontent.fbcdn.net/v.mp4?a=1&oh=SECRETV",
        "https://scontent.fbcdn.net/v.mp4?a=1&_nc_ohc=SECRETV",
        "https://api.example.com/x?jwt=SECRETV",
        "https://cdn.example.com/x?hash=SECRETV",
        "https://cdn.example.com/x?auth_key=SECRETV",
        "https://example.com/callback?code=SECRETV",
        "https://example.com/callback#access_token=SECRETV",
        "https://example.com/redirect?next=https%3A%2F%2Fcdn.example.com%2Fv%3Fsig%3DSECRETV",
        "{'Cookie': 'SID=SECRETV'}",
        '{"Authorization": "token SECRETV"}',
        '{"X-Api-Key": "SECRETV"}',
        str({"cookie": "a=SECRETV; b=SECRETV"}),
    ],
)
def test_redacts_additional_secrets(text):
    out = redact(text)
    assert "REDACTED" in out
    assert "SECRETV" not in out


def test_redacts_json_cookie_with_escaped_quotes():
    import json

    text = json.dumps({"Cookie": 'session="SECRETV"; b=SECRETV2', "Accept": "text/html"})
    out = redact(text)
    assert "SECRETV" not in out
    assert "text/html" in out  # other keys untouched


def test_redact_header_dict_no_catastrophic_backtracking():
    """An unclosed quoted header value full of backslashes must not freeze logging."""
    import subprocess
    import sys
    from pathlib import Path

    probe = (
        "import time\n"
        "from swiftdrop.redact import redact\n"
        "t = time.perf_counter()\n"
        "redact('\"Cookie\": \"' + '\\\\' * 5000)\n"
        "print(time.perf_counter() - t)\n"
    )
    root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, timeout=10, check=True, cwd=root
        )
    except subprocess.TimeoutExpired:
        raise AssertionError("redact() took more than 10 s on 5000 backslashes (catastrophic backtracking)")
    assert float(out.stdout.strip()) < 0.5
    # escaped quotes inside a value still end up fully redacted
    import json

    assert "SECRETV" not in redact(json.dumps({"Cookie": 'session="SECRETV"; b=SECRETV2'}))
    assert "SECRETV" not in redact("{'Cookie': 'a\\'SECRETV'}")
