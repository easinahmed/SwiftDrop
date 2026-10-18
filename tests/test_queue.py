"""Queue scheduling, concurrency limits, lifecycle and error isolation (with a fake provider)."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from swiftdrop.engine.http import HttpDownloader
from swiftdrop.engine.progress import ProgressUpdate
from swiftdrop.errors import failure
from swiftdrop.events import ChangeTracker
from swiftdrop.history import HistoryStore
from swiftdrop.models import Collection, InspectResult, Job, JobState, MediaKind
from swiftdrop.providers.base import DownloadOutcome
from swiftdrop.providers.direct import DirectProvider
from swiftdrop.providers.registry import ProviderRegistry
from swiftdrop.queue import DownloadQueue
from swiftdrop.settings import SettingsStore
from swiftdrop.storage import Database
from tests.conftest import make_bytes, wait_for


class FakeProvider:
    """Behaviour is driven by the URL: ?fail, ?block, ?slow."""

    name = "direct"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.release = threading.Event()
        self.calls: list[str] = []

    def inspect(self, url, token, settings):
        return InspectResult(provider="direct", title="x")

    def download(self, ctx):
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
            self.calls.append(ctx.url)
        try:
            if "fail" in ctx.url:
                raise failure("not_found", "fake 404")
            if "crash" in ctx.url:
                raise RuntimeError("unexpected bug")
            steps = 50 if "slow" in ctx.url else 3
            for i in range(steps):
                ctx.token.raise_if_stopped()
                if "block" in ctx.url:
                    while not self.release.is_set():
                        ctx.token.raise_if_stopped()
                        time.sleep(0.01)
                ctx.report(ProgressUpdate(downloaded=(i + 1) * 10, total=steps * 10))
                time.sleep(0.01)
            src = ctx.staging_dir / "out.part"
            src.write_bytes(b"done")
            path = ctx.finalize(src, f"{ctx.job_id}.bin", MediaKind.OTHER)
            return DownloadOutcome(filepath=path, size=4, kind=MediaKind.OTHER)
        finally:
            with self.lock:
                self.current -= 1


def build_queue(tmp_path: Path, provider, max_concurrent=3, **settings_patch):
    db = Database(tmp_path / "db.sqlite3")
    settings = SettingsStore(db)
    downloads = tmp_path / "Downloads"
    downloads.mkdir(exist_ok=True)
    settings.update({"download_dir": str(downloads), "max_concurrent": max_concurrent, **settings_patch})
    registry = ProviderRegistry(direct=provider)
    queue = DownloadQueue(
        registry=registry,
        db=db,
        history=HistoryStore(db),
        settings=settings,
        tracker=ChangeTracker(),
        partial_root=tmp_path / "partial",
    )
    return queue, db, settings, downloads


def make_jobs(urls, downloads: Path):
    return [Job(url=u, key=u, destination=str(downloads), provider="direct") for u in urls]


def states(queue):
    return [j["state"] for j in queue.jobs_public()]


def test_bounded_concurrency_with_150_jobs(tmp_path):
    provider = FakeProvider()
    queue, _db, _, downloads = build_queue(tmp_path, provider, max_concurrent=4)
    queue.start()
    threads_before = threading.active_count()
    queue.add(make_jobs([f"https://e.com/{i}" for i in range(150)], downloads))
    peak_threads = 0
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        peak_threads = max(peak_threads, threading.active_count() - threads_before)
        if all(s == "completed" for s in states(queue)):
            break
        time.sleep(0.01)
    assert all(s == "completed" for s in states(queue))
    assert provider.peak <= 4
    assert queue.peak_concurrency <= 4
    # A finishing worker may overlap briefly with its replacement; the count stays bounded by
    # the concurrency limit, never by the number of queued links.
    assert peak_threads <= 2 * 4
    assert len(list(downloads.iterdir())) == 150
    queue.shutdown()


def test_jobs_start_in_fifo_order(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider, max_concurrent=1)
    queue.start()
    urls = [f"https://e.com/{i}" for i in range(6)]
    queue.add(make_jobs(urls, downloads))
    assert wait_for(lambda: all(s == "completed" for s in states(queue)))
    assert provider.calls == urls
    queue.shutdown()


def test_failure_is_isolated(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    queue.add(
        make_jobs(["https://e.com/ok1", "https://e.com/fail", "https://e.com/crash", "https://e.com/ok2"], downloads)
    )
    assert wait_for(lambda: all(s in ("completed", "failed") for s in states(queue)))
    by_url = {j["url"]: j for j in queue.jobs_public()}
    assert by_url["https://e.com/ok1"]["state"] == "completed"
    assert by_url["https://e.com/ok2"]["state"] == "completed"
    assert by_url["https://e.com/fail"]["error"]["code"] == "not_found"
    assert by_url["https://e.com/crash"]["state"] == "failed"
    assert "unexpected bug" in by_url["https://e.com/crash"]["error"]["detail"]
    queue.shutdown()


def test_pause_resume_cancel_retry(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider, max_concurrent=1)
    queue.start()
    ids = queue.add(make_jobs(["https://e.com/block", "https://e.com/waiting"], downloads))
    assert wait_for(lambda: queue.get(ids[0]).state == JobState.DOWNLOADING)

    # Pause a waiting job and the running one.
    assert queue.pause([ids[1]]) == 1
    assert queue.get(ids[1]).state == JobState.PAUSED
    queue.pause([ids[0]])
    assert wait_for(lambda: queue.get(ids[0]).state == JobState.PAUSED)

    # Resume the first: it should run again (keeping its staging folder).
    provider.release.set()
    queue.resume([ids[0]])
    assert wait_for(lambda: queue.get(ids[0]).state == JobState.COMPLETED)
    assert queue.get(ids[1]).state == JobState.PAUSED  # still paused, not auto-started

    # Cancel the paused one, then retry it.
    queue.cancel([ids[1]])
    assert queue.get(ids[1]).state == JobState.CANCELLED
    queue.retry([ids[1]])
    assert wait_for(lambda: queue.get(ids[1]).state == JobState.COMPLETED)
    queue.shutdown()


def test_cancel_running_job_cleans_staging(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/block"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING)
    staging = queue.staging_dir(job_id)
    (staging / "partial.bin").write_bytes(b"123")
    queue.cancel([job_id])
    assert wait_for(lambda: queue.get(job_id).state == JobState.CANCELLED)
    assert wait_for(lambda: not staging.exists())
    assert list(downloads.iterdir()) == []
    queue.shutdown()


def test_retry_failed_only_reruns_failures(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    queue.add(make_jobs(["https://e.com/a", "https://e.com/fail"], downloads))
    assert wait_for(lambda: sorted(states(queue)) == ["completed", "failed"])
    calls_before = len(provider.calls)
    assert queue.retry_failed() == 1
    assert wait_for(lambda: len(provider.calls) == calls_before + 1)
    assert wait_for(lambda: sorted(states(queue)) == ["completed", "failed"])
    assert provider.calls[-1] == "https://e.com/fail"
    queue.shutdown()


def test_remove_never_deletes_completed_files(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/a"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.COMPLETED)
    path = Path(queue.get(job_id).filepath)
    assert queue.clear("completed") == 1
    assert queue.get(job_id) is None
    assert path.exists()
    queue.shutdown()


def test_restart_recovery_never_marks_unfinished_as_completed(tmp_path):
    provider = FakeProvider()
    queue, db, _settings, downloads = build_queue(tmp_path, provider, max_concurrent=1)
    queue.start()
    ids = queue.add(make_jobs(["https://e.com/block", "https://e.com/later", "https://e.com/done-first"], downloads))
    assert wait_for(lambda: queue.get(ids[0]).state == JobState.DOWNLOADING)
    # Simulate a crash: snapshot the database while a job is mid-download, without a clean shutdown.
    queue._persist_ids(ids)
    snapshot = sqlite3.connect(tmp_path / "crashed.sqlite3")
    db._conn.backup(snapshot)
    snapshot.close()

    db2 = Database(tmp_path / "crashed.sqlite3")
    queue2 = DownloadQueue(
        registry=ProviderRegistry(direct=provider),
        db=db2,
        history=HistoryStore(db2),
        settings=SettingsStore(db2),
        tracker=ChangeTracker(),
        partial_root=tmp_path / "partial",
    )
    queue2.load()
    restored = {j["url"]: j for j in queue2.jobs_public()}
    assert restored["https://e.com/block"]["state"] == "interrupted"
    assert restored["https://e.com/later"]["state"] == "paused"
    assert all(j["state"] != "completed" for j in restored.values())
    provider.release.set()
    queue.shutdown(timeout=2)
    queue2.start()
    queue2.resume_all()
    assert wait_for(lambda: all(j["state"] == "completed" for j in queue2.jobs_public()))
    queue2.shutdown()


def test_resume_on_launch_requeues(tmp_path):
    provider = FakeProvider()
    queue, db, _settings, downloads = build_queue(tmp_path, provider, resume_on_launch=True)
    ids = queue.add(make_jobs(["https://e.com/a"], downloads))
    db.close()
    db2 = Database(tmp_path / "db.sqlite3")
    queue2 = DownloadQueue(
        registry=ProviderRegistry(direct=provider),
        db=db2,
        history=HistoryStore(db2),
        settings=SettingsStore(db2),
        tracker=ChangeTracker(),
        partial_root=tmp_path / "partial",
    )
    queue2.load()
    assert queue2.get(ids[0]).state == JobState.QUEUED
    queue2.start()
    assert wait_for(lambda: queue2.get(ids[0]).state == JobState.COMPLETED)
    queue2.shutdown()


def test_shutdown_interrupts_running_jobs(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/block"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING)
    queue.shutdown(timeout=3)
    assert queue.get(job_id).state == JobState.INTERRUPTED


def test_collections_aggregate_progress(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    collection = Collection(title="My: Playlist", url="https://e.com/pl", source="e.com", destination=str(downloads))
    jobs = make_jobs([f"https://e.com/p{i}" for i in range(3)], downloads)
    for index, job in enumerate(jobs, 1):
        job.playlist_index = index
    queue.add(jobs, collection)
    assert wait_for(lambda: all(s == "completed" for s in states(queue)))
    (summary,) = queue.collections_public()
    assert summary["count"] == 3 and summary["completed"] == 3 and summary["progress"] == 1.0
    folder = downloads / "My- Playlist"
    assert folder.is_dir() and len(list(folder.iterdir())) == 3
    queue.shutdown()


def test_changing_concurrency_takes_effect(tmp_path):
    provider = FakeProvider()
    queue, _, settings, downloads = build_queue(tmp_path, provider, max_concurrent=1)
    queue.start()
    queue.add(make_jobs([f"https://e.com/block{i}" for i in range(4)], downloads))
    assert wait_for(lambda: queue.stats()["running"] == 1)
    settings.update({"max_concurrent": 3})
    queue.notify_settings_changed()
    assert wait_for(lambda: queue.stats()["running"] == 3)
    provider.release.set()
    assert wait_for(lambda: all(s == "completed" for s in states(queue)))
    queue.shutdown()


def test_real_direct_downloads_through_queue(tmp_path, http_server):
    """Integration: real HTTP downloads via the direct engine, with one failing link."""
    files = {f"clip{i}.mp4": make_bytes(200_000 + i, seed=i) for i in range(5)}
    urls = [http_server.add_file(name, data) for name, data in files.items()]
    urls.append(http_server.url("/status/404"))
    provider = DirectProvider(lambda: HttpDownloader(backoff_base=0.01, backoff_max=0.02))
    queue, _, _, downloads = build_queue(tmp_path, provider, max_concurrent=3)
    queue.start()
    queue.add(make_jobs(urls, downloads))
    assert wait_for(lambda: all(s in ("completed", "failed") for s in states(queue)), timeout=20)
    results = {j["url"]: j for j in queue.jobs_public()}
    for name, data in files.items():
        assert (downloads / name).read_bytes() == data
    assert results[http_server.url("/status/404")]["error"]["code"] == "not_found"
    done = [j for j in results.values() if j["state"] == "completed"]
    assert all(j["kind"] == "video" and j["sha256"] for j in done)
    queue.shutdown()


@pytest.mark.parametrize("name", ["same.mp4"])
def test_two_jobs_with_same_filename_get_unique_names(tmp_path, http_server, name):
    url_a = http_server.add_file(name, b"A" * 1000)
    url_b = http_server.url(f"/file/{name}?v=2")
    provider = DirectProvider(lambda: HttpDownloader())
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    queue.add(make_jobs([url_a, url_b], downloads))
    assert wait_for(lambda: all(s == "completed" for s in states(queue)))
    assert sorted(p.name for p in downloads.iterdir()) == ["same (1).mp4", "same.mp4"]
    queue.shutdown()
