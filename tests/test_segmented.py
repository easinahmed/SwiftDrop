"""Segmented (multi-connection) downloader: correctness, fallbacks, stop and disk errors."""

import errno
import hashlib
import os
import random
import threading
import time

import pytest
from requests.cookies import RequestsCookieJar

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.connpool import ConnectionPool
from swiftdrop.engine.segmented import SegmentedDownloader, SegmentedUnavailable
from swiftdrop.errors import DownloadFailure
from tests.conftest import wait_for

MiB = 1024 * 1024


def unique_bytes(size: int, seed: int = 1) -> bytes:
    # Not make_bytes(): its 64 KiB period would hide a segment written at the wrong offset.
    return random.Random(seed).randbytes(size)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seg_of(part):
    return part.with_suffix(part.suffix + ".seg")


def data_requests(server):
    """Ranged requests other than the 1-byte probe."""
    return [headers for _, headers in server.requests if headers.get("Range", "bytes=0-0") != "bytes=0-0"]


def fd_count() -> int:
    return len(os.listdir("/dev/fd"))


def segment_threads():
    return [t for t in threading.enumerate() if t.name.startswith("segment-")]


def test_segmented_byte_identical(http_server, tmp_path):
    data = unique_bytes(20 * MiB)
    url = http_server.add_file("big.mp4", data)
    part = tmp_path / "download.part"
    updates = []
    state = {}
    result = SegmentedDownloader(connections=4).download(url, part, CancelToken(), updates.append, state)
    assert part.read_bytes() == data
    assert result.sha256 == sha(data)
    assert result.size == len(data)
    assert result.content_type == "video/mp4"
    assert not seg_of(part).exists()
    assert http_server.peak_active >= 2
    assert len(data_requests(http_server)) >= 4
    assert any(u.connections for u in updates)
    final = updates[-1]
    assert final.downloaded == len(data) and final.total == len(data) and final.progress == 1.0
    assert state["final_url"] == url


def test_dynamic_split_takes_over_slow_tail(http_server, tmp_path):
    data = unique_bytes(20 * MiB, seed=2)
    url = http_server.add_file("tail.mp4", data) + "?slowconn=1&slowrate=400000"
    part = tmp_path / "download.part"
    started = time.monotonic()
    result = SegmentedDownloader(connections=4).download(url, part, CancelToken(), lambda u: None, {})
    elapsed = time.monotonic() - started
    assert result.sha256 == sha(data)
    # The throttled connection's 5 MiB segment alone would take ~13 s at 400 kB/s. Finished workers
    # must keep halving its unwritten tail (down to the 1 MiB minimum) and fetch the rest themselves;
    # the 1.25 MiB the slow connection keeps then takes ~3.3 s.
    assert elapsed < 8.0, f"took {elapsed:.2f}s"
    assert len(data_requests(http_server)) > 4, "no dynamic split happened"


def test_ineligible_small_or_no_range(http_server, tmp_path):
    dl = SegmentedDownloader()
    small = http_server.add_file("small.mp4", unique_bytes(1 * MiB))
    big = http_server.add_file("big.mp4", unique_bytes(8 * MiB))
    assert dl.eligible(dl.probe(big, CancelToken())) is True
    assert dl.eligible(dl.probe(small, CancelToken())) is False
    assert dl.eligible(dl.probe(big + "?norange=1", CancelToken())) is False

    part = tmp_path / "download.part"
    seg_of(part).write_bytes(b"stale")
    state = {"segments": ((0, 10, 5),)}
    with pytest.raises(SegmentedUnavailable):
        dl.download(small, part, CancelToken(), lambda u: None, state)
    assert not seg_of(part).exists()
    assert state.get("segments") is None


def test_server_stops_honoring_ranges_falls_back_clean(http_server, tmp_path):
    url = http_server.add_file("r.mp4", unique_bytes(20 * MiB)) + "?range_after=2"
    part = tmp_path / "download.part"
    state = {"segments": ((0, 10, 5),)}
    with pytest.raises(SegmentedUnavailable):
        SegmentedDownloader(connections=4).download(url, part, CancelToken(), lambda u: None, state)
    assert not seg_of(part).exists()
    assert not part.exists()
    assert state.get("segments") is None


def test_validator_change_falls_back(http_server, tmp_path):
    url = http_server.add_file("v.mp4", unique_bytes(20 * MiB)) + "?etag_after=3"
    part = tmp_path / "download.part"
    state = {"segments": ((0, 10, 5),)}
    with pytest.raises(SegmentedUnavailable):
        SegmentedDownloader(connections=4).download(url, part, CancelToken(), lambda u: None, state)
    assert not seg_of(part).exists()
    assert not part.exists()
    assert state.get("segments") is None


def test_html_rejected(http_server, tmp_path):
    url = http_server.add_file("page.mp4", unique_bytes(20 * MiB)) + "?type=text/html"
    part = tmp_path / "download.part"
    with pytest.raises(DownloadFailure) as info:
        SegmentedDownloader().download(url, part, CancelToken(), lambda u: None, {})
    assert info.value.info.code == "not_media"
    assert not seg_of(part).exists() and not part.exists()


def test_stop_keeps_seg_and_closes_fds(http_server, tmp_path):
    size = 20 * MiB
    url = http_server.add_file("stop.mp4", unique_bytes(size)) + "?rate=2000000"
    part = tmp_path / "download.part"
    token = CancelToken()
    baseline = fd_count()

    def on_progress(update):
        if update.downloaded and update.downloaded > size // 4:
            token.stop(StopReason.CANCEL)

    with pytest.raises(JobStopped):
        SegmentedDownloader(connections=4).download(url, part, token, on_progress, {})
    assert not segment_threads(), "workers are joined before download() returns"
    assert seg_of(part).exists(), "the partial .seg is kept for resume"
    assert seg_of(part).stat().st_size == size
    assert not part.exists()
    # The test server lives in this process, so its sockets close asynchronously after ours.
    assert wait_for(lambda: http_server.active == 0 and fd_count() <= baseline, timeout=5), (fd_count(), baseline)


def test_stop_after_last_write_still_completes(http_server, tmp_path, monkeypatch):
    # A pause that lands after the final byte is written must not throw away a complete file
    # (the next attempt would truncate the .seg and download everything again).
    data = unique_bytes(8 * MiB, seed=6)
    url = http_server.add_file("late.mp4", data)
    part = tmp_path / "download.part"
    token = CancelToken()
    real_pwrite = os.pwrite
    lock = threading.Lock()
    written = [0]

    def pwrite_then_stop(fd, buf, offset):
        count = real_pwrite(fd, buf, offset)
        with lock:
            written[0] += count
            if written[0] >= len(data):
                token.stop(StopReason.PAUSE)
        return count

    monkeypatch.setattr(os, "pwrite", pwrite_then_stop)
    result = SegmentedDownloader(connections=4).download(url, part, token, lambda u: None, {})
    assert token.stopped
    assert result.sha256 == sha(data)
    assert part.read_bytes() == data
    assert not seg_of(part).exists()


def test_worker_start_failure_joins_started_workers(http_server, tmp_path, monkeypatch):
    url = http_server.add_file("threads.mp4", unique_bytes(20 * MiB, seed=7)) + "?rate=2000000"
    real_start = threading.Thread.start
    started = [0]

    def start_fails_on_second_worker(self):
        if self.name.startswith("segment-"):
            started[0] += 1
            if started[0] == 2:
                raise RuntimeError("can't start new thread")
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", start_fails_on_second_worker)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        SegmentedDownloader(connections=4).download(url, tmp_path / "download.part", CancelToken(), lambda u: None, {})
    assert not segment_threads(), "the worker that did start must be halted and joined"


def test_preallocation_enospc_reports_disk_full(http_server, tmp_path, monkeypatch):
    url = http_server.add_file("full.mp4", unique_bytes(20 * MiB))
    part = tmp_path / "download.part"

    def no_space(fd, length):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "ftruncate", no_space)
    with pytest.raises(DownloadFailure) as info:
        SegmentedDownloader().download(url, part, CancelToken(), lambda u: None, {})
    assert info.value.info.code == "disk_full"
    assert not seg_of(part).exists()


def test_transient_errors_retry_the_range(http_server, tmp_path):
    data = unique_bytes(8 * MiB, seed=5)
    # The probe gets one 503; then two workers' connections drop after 1.5 MB (the probe uses up drop #1).
    url = http_server.add_file("drop.mp4", data) + "?fail_once=503&drop_after=1500000&drop_times=3"
    part = tmp_path / "download.part"
    result = SegmentedDownloader(connections=2).download(url, part, CancelToken(), lambda u: None, {})
    assert result.sha256 == sha(data)
    resumed = [h["Range"] for h in data_requests(http_server)][2:]
    assert len(resumed) >= 2, "each dropped range is re-requested from where it stopped"
    assert all(not r.startswith(("bytes=0-", f"bytes={4 * MiB}-")) for r in resumed)


def test_headers_and_cookies_sent_on_every_request(http_server, tmp_path):
    data = unique_bytes(8 * MiB, seed=3)
    url = http_server.add_file("auth.mp4", data)
    jar = RequestsCookieJar()
    jar.set("sid", "abc123", domain="127.0.0.1", path="/")
    headers = {"Referer": "https://example.test/watch", "Accept-Encoding": "gzip"}
    part = tmp_path / "download.part"
    result = SegmentedDownloader(connections=2).download(
        url, part, CancelToken(), lambda u: None, {}, headers=headers, cookies=jar
    )
    assert result.sha256 == sha(data)
    assert len(http_server.requests) >= 3
    for _, sent in http_server.requests:
        assert sent.get("Referer") == "https://example.test/watch"
        assert "sid=abc123" in sent.get("Cookie", "")
        assert sent.get("Accept-Encoding") == "identity"


def test_connection_pool_limits_workers(http_server, tmp_path):
    class RecordingPool(ConnectionPool):
        peak = 0

        def acquire(self, token, timeout=None):
            ok = super().acquire(token, timeout)
            if ok:
                self.peak = max(self.peak, self.in_use)
            return ok

    pool = RecordingPool(limit=2)
    data = unique_bytes(8 * MiB, seed=4)
    url = http_server.add_file("pool.mp4", data)
    result = SegmentedDownloader(connections=4, pool=pool).download(
        url, tmp_path / "download.part", CancelToken(), lambda u: None, {}
    )
    assert result.sha256 == sha(data)
    assert 1 <= pool.peak <= 2
    assert pool.in_use == 0


def test_connection_pool_acquire_timeout_and_stop():
    pool = ConnectionPool(limit=1)
    token = CancelToken()
    assert pool.acquire(token) is True
    assert pool.acquire(token, timeout=0.05) is False
    threading.Timer(0.1, token.stop, args=(StopReason.PAUSE,)).start()
    started = time.monotonic()
    assert pool.acquire(token) is False, "a stopped job must not wait for a connection"
    assert time.monotonic() - started < 1.0
    pool.release()
    assert pool.in_use == 0
    assert pool.acquire(CancelToken(), timeout=0.05) is True


def test_rescue_recovers_throttled_connection(http_server, tmp_path):
    data = unique_bytes(16 * MiB, seed=5)
    url = http_server.add_file("rescue.mp4", data) + "?slowconn=2&slowrate=50000"
    downloader = SegmentedDownloader(connections=4)
    started = time.monotonic()
    result = downloader.download(url, tmp_path / "download.part", CancelToken(), lambda u: None, {})
    assert result.sha256 == sha(data)
    assert time.monotonic() - started < 10.0
    assert downloader.last_stats["rescues"] >= 1


def test_slow_steady_server_not_churned(http_server, tmp_path):
    data = unique_bytes(int(2.6 * MiB), seed=6)
    url = http_server.add_file("steady.mp4", data) + "?rate=300000"
    downloader = SegmentedDownloader(connections=2, min_size=MiB)
    started = time.monotonic()
    downloader.download(url, tmp_path / "download.part", CancelToken(), lambda u: None, {})
    assert time.monotonic() - started > 4.1, "the test must outlast the 4 s rate window"
    assert downloader.last_stats["rescues"] == 0


def test_503_sheds_connection(http_server, tmp_path):
    data = unique_bytes(8 * MiB, seed=7)
    # The probe is request 1 and passes; the next two requests (workers) get 503.
    url = http_server.add_file("shed.mp4", data) + "?flaky=2&flaky_skip=1&flaky_status=503&retry_after=0"
    downloader = SegmentedDownloader(connections=4)
    result = downloader.download(url, tmp_path / "download.part", CancelToken(), lambda u: None, {})
    assert result.sha256 == sha(data)
    assert downloader.last_stats["min_connections"] < 4


def test_global_pool_cap(http_server, tmp_path):
    pool = ConnectionPool(limit=8)
    datas = [unique_bytes(8 * MiB, seed=10 + i) for i in range(3)]
    urls = [http_server.add_file(f"g{i}.mp4", d) + "?rate=2000000" for i, d in enumerate(datas)]
    results = {}

    def run(i):
        downloader = SegmentedDownloader(connections=16, pool=pool, min_segment=512 * 1024)
        results[i] = downloader.download(urls[i], tmp_path / f"d{i}.part", CancelToken(), lambda u: None, {})

    threads = [threading.Thread(target=run, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert [results[i].sha256 for i in range(3)] == [sha(d) for d in datas]
    assert http_server.peak_active <= 8
    assert pool.in_use == 0


def test_pause_during_rescue_resumes_intact(http_server, tmp_path):
    from requests import Session

    data = unique_bytes(16 * MiB, seed=8)
    url = http_server.add_file("pause.mp4", data) + "?slowconn=2&slowrate=50000"
    part = tmp_path / "download.part"
    token = CancelToken()
    calls = []

    def factory():
        calls.append(1)
        if len(calls) > 5:  # probe + 4 workers come first: this is a rescue reopening its session
            token.stop(StopReason.PAUSE)
        return Session()

    with pytest.raises(JobStopped):
        SegmentedDownloader(connections=4, session_factory=factory).download(url, part, token, lambda u: None, {})
    assert not segment_threads()
    assert seg_of(part).exists()
    result = SegmentedDownloader(connections=4).download(
        url.replace("slowconn=2", "slowconn=0"), part, CancelToken(), lambda u: None, {}
    )
    assert result.sha256 == sha(data)


def _requested_bytes(server, since):
    total = 0
    for _, headers in server.requests[since:]:
        first, last = headers.get("Range", "bytes=0-0")[len("bytes=") :].split("-")
        total += int(last) - int(first) + 1
    return total


def _pause_at_half(url, part, state, size):
    token = CancelToken()

    def on_progress(update):
        if update.downloaded and update.downloaded > size // 2:
            token.stop(StopReason.PAUSE)

    with pytest.raises(JobStopped):
        SegmentedDownloader(connections=4).download(url, part, token, on_progress, state)


def test_resume_from_persisted_segments(http_server, tmp_path, monkeypatch):
    monkeypatch.setattr("swiftdrop.engine.segmented.SNAPSHOT_EVERY", 0.1)
    size = 16 * MiB
    data = unique_bytes(size, seed=20)
    url = http_server.add_file("resume.mp4", data) + "?rate=2000000"
    part = tmp_path / "download.part"
    state = {}
    _pause_at_half(url, part, state, size)
    written = sum(w for _, _, w in state["segments"])
    assert 0 < written < size
    seen = len(http_server.requests)
    result = SegmentedDownloader(connections=4).download(url, part, CancelToken(), lambda u: None, state)
    assert result.sha256 == sha(data)
    assert _requested_bytes(http_server, seen) <= size - written + MiB + 1
    assert "segments" not in state and not seg_of(part).exists()


def test_snapshot_consistent_under_concurrent_persist(http_server, tmp_path, monkeypatch):
    import json

    monkeypatch.setattr("swiftdrop.engine.segmented.SNAPSHOT_EVERY", 0.05)
    data = unique_bytes(12 * MiB, seed=21)
    url = http_server.add_file("snap.mp4", data) + "?rate=2000000"
    state = {}
    stop = threading.Event()
    problems, seen = [], []

    def persist():
        while not stop.is_set():
            try:
                copy = json.loads(json.dumps(dict(state)))  # what the queue's persistence does
            except Exception as exc:
                problems.append(exc)
                return
            for start, end, written in copy.get("segments", []):
                seen.append(1)
                if not start <= start + written <= end + 1:
                    problems.append((start, end, written))
            time.sleep(0.005)

    thread = threading.Thread(target=persist)
    thread.start()
    try:
        downloader = SegmentedDownloader(connections=4)
        result = downloader.download(url, tmp_path / "d.part", CancelToken(), lambda u: None, state)
    finally:
        stop.set()
        thread.join()
    assert result.sha256 == sha(data)
    assert seen, "no snapshot was observed"
    assert not problems, problems[:3]


def test_resume_with_changed_validator_restarts_clean(http_server, tmp_path, monkeypatch):
    monkeypatch.setattr("swiftdrop.engine.segmented.SNAPSHOT_EVERY", 0.1)
    size = 12 * MiB
    old, new = unique_bytes(size, seed=22), unique_bytes(size, seed=23)
    url = http_server.add_file("changed.mp4", old) + "?rate=2000000"
    part = tmp_path / "download.part"
    state = {}
    _pause_at_half(url, part, state, size)
    assert state["segments"]
    http_server.files["changed.mp4"] = new  # the ETag (a hash of the content) changes
    result = SegmentedDownloader(connections=4).download(url, part, CancelToken(), lambda u: None, state)
    assert result.sha256 == sha(new)
    assert part.read_bytes() == new
