import hashlib
import threading
import time

import pytest

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.http import HttpDownloader
from swiftdrop.errors import DownloadFailure
from swiftdrop.ratelimit import TokenBucket
from tests.conftest import make_bytes


def fast_downloader(**kwargs):
    kwargs.setdefault("backoff_base", 0.01)
    kwargs.setdefault("backoff_max", 0.05)
    kwargs.setdefault("read_timeout", 5)
    kwargs.setdefault("chunk_size", 32 * 1024)
    return HttpDownloader(**kwargs)


def collect():
    updates = []
    return updates, updates.append


def test_downloads_file_and_verifies(http_server, tmp_path):
    data = make_bytes(1_500_000)
    url = http_server.add_file("video.mp4", data)
    part = tmp_path / "x.part"
    updates, on_progress = collect()
    state = {}
    result = fast_downloader().download(url, part, CancelToken(), on_progress, state)
    assert part.read_bytes() == data
    assert result.size == len(data)
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.content_type == "video/mp4"
    assert state["accept_ranges"] is True
    final = updates[-1]
    assert final.downloaded == len(data) and final.total == len(data) and final.progress == 1.0


def test_progress_is_monotonic_and_bounded(http_server, tmp_path):
    data = make_bytes(400_000)
    url = http_server.add_file("a.bin", data) + "?rate=300000"
    updates, on_progress = collect()
    fast_downloader().download(url, tmp_path / "a.part", CancelToken(), on_progress, {})
    values = [u.downloaded for u in updates if u.downloaded is not None]
    assert values == sorted(values)
    assert all(0 <= v <= len(data) for v in values)
    assert any(u.speed for u in updates), "a real speed should be measured on a slow transfer"


def test_follows_redirects(http_server, tmp_path):
    data = make_bytes(10_000)
    target = http_server.add_file("img.png", data)
    url = http_server.url("/redirect?to=" + target)
    result = fast_downloader().download(url, tmp_path / "r.part", CancelToken(), lambda u: None, {})
    assert result.final_url == target
    assert (tmp_path / "r.part").read_bytes() == data


def test_resumes_after_connection_drop(http_server, tmp_path):
    data = make_bytes(1_000_000)
    url = http_server.add_file("drop.mp4", data) + "?drop_after=300000"
    result = fast_downloader().download(url, tmp_path / "d.part", CancelToken(), lambda u: None, {})
    assert (tmp_path / "d.part").read_bytes() == data
    assert result.resumed is True
    ranged = [h for p, h in http_server.requests if p.startswith("/file/drop.mp4") and "Range" in h]
    assert ranged and ranged[-1]["Range"].startswith("bytes=")
    assert ranged[-1]["Range"] != "bytes=0-"


def test_restarts_when_server_has_no_range_support(http_server, tmp_path):
    data = make_bytes(600_000)
    url = http_server.add_file("norange.bin", data) + "?norange=1&drop_after=200000"
    result = fast_downloader().download(url, tmp_path / "n.part", CancelToken(), lambda u: None, {})
    assert (tmp_path / "n.part").read_bytes() == data
    assert result.size == len(data)


def test_retries_transient_503_with_backoff(http_server, tmp_path):
    data = make_bytes(20_000)
    url = http_server.add_file("flaky.bin", data) + "?flaky=2"
    updates, on_progress = collect()
    fast_downloader().download(url, tmp_path / "f.part", CancelToken(), on_progress, {})
    assert (tmp_path / "f.part").read_bytes() == data
    assert any(u.phase and "retrying" in u.phase for u in updates)


def test_gives_up_after_max_retries(http_server, tmp_path):
    url = http_server.add_file("dead.bin", b"x") + "?flaky=99"
    with pytest.raises(DownloadFailure) as info:
        fast_downloader(max_retries=2).download(url, tmp_path / "g.part", CancelToken(), lambda u: None, {})
    assert info.value.info.code == "server_error"


def test_404_is_not_retried(http_server, tmp_path):
    with pytest.raises(DownloadFailure) as info:
        fast_downloader().download(
            http_server.url("/status/404"), tmp_path / "h.part", CancelToken(), lambda u: None, {}
        )
    assert info.value.info.code == "not_found"
    assert sum(1 for p, _ in http_server.requests if p == "/status/404") == 1


def test_html_page_is_rejected_as_not_media(http_server, tmp_path):
    with pytest.raises(DownloadFailure) as info:
        fast_downloader().download(
            http_server.url("/page.html"), tmp_path / "p.part", CancelToken(), lambda u: None, {}
        )
    assert info.value.info.code == "not_media"


def test_cancel_stops_promptly(http_server, tmp_path):
    data = make_bytes(4_000_000)
    url = http_server.add_file("slow.bin", data) + "?rate=200000"
    token = CancelToken()
    errors = []

    def run():
        try:
            fast_downloader().download(url, tmp_path / "s.part", token, lambda u: None, {})
        except JobStopped as exc:
            errors.append(exc.reason)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.4)
    started = time.monotonic()
    token.stop(StopReason.PAUSE)
    thread.join(5)
    assert not thread.is_alive()
    assert time.monotonic() - started < 2
    assert errors == [StopReason.PAUSE]
    assert 0 < (tmp_path / "s.part").stat().st_size < len(data)


def test_pause_then_resume_continues_from_partial(http_server, tmp_path):
    data = make_bytes(2_000_000)
    url = http_server.add_file("pr.bin", data) + "?rate=1000000"
    part = tmp_path / "pr.part"
    state: dict = {}
    token = CancelToken()

    def run():
        with pytest.raises(JobStopped):
            fast_downloader().download(url, part, token, lambda u: None, state)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    token.stop(StopReason.PAUSE)
    thread.join(5)
    partial = part.stat().st_size
    assert 0 < partial < len(data)
    result = fast_downloader().download(url, part, CancelToken(), lambda u: None, state)
    assert part.read_bytes() == data
    assert result.resumed
    assert result.sha256 == hashlib.sha256(data).hexdigest()


def test_resume_with_changed_file_restarts(http_server, tmp_path):
    data = make_bytes(300_000, seed=1)
    url = http_server.add_file("changing.bin", data)
    part = tmp_path / "c.part"
    part.write_bytes(make_bytes(100_000, seed=2))  # stale partial from an older version
    state = {"etag": '"stale"', "accept_ranges": True}
    fast_downloader().download(url, part, CancelToken(), lambda u: None, state)
    assert part.read_bytes() == data


def test_already_complete_partial_is_accepted(http_server, tmp_path):
    data = make_bytes(50_000)
    url = http_server.add_file("done.bin", data)
    part = tmp_path / "done.part"
    part.write_bytes(data)
    result = fast_downloader().download(url, part, CancelToken(), lambda u: None, {"accept_ranges": True})
    assert result.size == len(data)


def test_bandwidth_limit_is_enforced(http_server, tmp_path):
    data = make_bytes(300_000)
    url = http_server.add_file("limited.bin", data)
    bucket = TokenBucket(600_000)
    start = time.monotonic()
    fast_downloader(bucket=bucket).download(url, tmp_path / "l.part", CancelToken(), lambda u: None, {})
    # 300 KB at 600 KB/s with a full initial bucket needs roughly no wait; use a smaller rate check instead.
    bucket.set_rate(150_000)
    start = time.monotonic()
    fast_downloader(bucket=bucket).download(url, tmp_path / "l2.part", CancelToken(), lambda u: None, {})
    assert time.monotonic() - start > 0.9


def test_probe_reads_headers_without_body(http_server):
    data = make_bytes(123_456)
    url = http_server.add_file("probe.mp4", data) + '?disposition=attachment; filename="Nice Name.mp4"'
    probe = fast_downloader().probe(url, CancelToken())
    assert probe.content_length == len(data)
    assert probe.accept_ranges is True
    assert "Nice Name.mp4" in (probe.content_disposition or "")
    assert not probe.is_html
