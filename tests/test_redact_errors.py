import errno
import logging

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
