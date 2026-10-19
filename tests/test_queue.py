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


def _fail_save_once(monkeypatch, db, state: JobState):
    """Make the next save of a job in ``state`` raise like a full disk / locked database."""
    original = db.save_jobs
    calls = {"failed": 0}

    def flaky(jobs):
        jobs = list(jobs)
        if calls["failed"] == 0 and any(j.state == state for j in jobs):
            calls["failed"] += 1
            raise sqlite3.OperationalError("database or disk is full")
        return original(jobs)

    monkeypatch.setattr(db, "save_jobs", flaky)
    return calls


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_dispatcher_survives_db_error(tmp_path, monkeypatch):
    provider = FakeProvider()
    queue, db, _, downloads = build_queue(tmp_path, provider, max_concurrent=2)
    calls = _fail_save_once(monkeypatch, db, JobState.DOWNLOADING)
    queue.start()
    queue.add(make_jobs([f"https://e.com/slow{i}" for i in range(4)], downloads))
    assert wait_for(lambda: all(s in ("completed", "failed") for s in states(queue)), timeout=10)
    assert calls["failed"] == 1
    assert queue._dispatcher.is_alive()
    assert len(queue._running) == 0
    assert sorted(states(queue)) == ["completed", "completed", "completed", "failed"]
    failed = next(j for j in queue.jobs_public() if j["state"] == "failed")
    assert failed["error"]["code"] == "disk_full"
    queue.shutdown()


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_worker_survives_finish_persist_error(tmp_path, monkeypatch):
    provider = FakeProvider()
    queue, db, _, downloads = build_queue(tmp_path, provider, max_concurrent=2)
    calls = _fail_save_once(monkeypatch, db, JobState.COMPLETED)
    queue.start()
    ids = queue.add(make_jobs([f"https://e.com/f{i}" for i in range(4)], downloads))
    assert wait_for(lambda: all(s in ("completed", "failed") for s in states(queue)), timeout=10)
    # A finished job deletes its staging folder and releases its hold after the state flips.
    assert wait_for(
        lambda: not queue._running and not queue._reserved and all(not queue.staging_dir(i).exists() for i in ids)
    )
    assert calls["failed"] == 1
    assert queue._dispatcher.is_alive()
    assert len(queue._running) == 0
    assert states(queue) == ["completed"] * 4  # the file was saved; only the bookkeeping write failed
    assert all(not queue.staging_dir(i).exists() for i in ids)
    queue.shutdown()


def _reopen(tmp_path: Path, provider, db_file: Path) -> DownloadQueue:
    db = Database(db_file)
    return DownloadQueue(
        registry=ProviderRegistry(direct=provider),
        db=db,
        history=HistoryStore(db),
        settings=SettingsStore(db),
        tracker=ChangeTracker(),
        partial_root=tmp_path / "partial",
    )


def test_resume_on_launch_resumes_interrupted(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider, resume_on_launch=True)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/block"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING)
    queue.shutdown(timeout=3)  # a normal quit leaves the job INTERRUPTED
    assert queue.get(job_id).state == JobState.INTERRUPTED
    provider.release.set()
    queue2 = _reopen(tmp_path, provider, tmp_path / "db.sqlite3")
    queue2.load()
    queue2.start()
    assert wait_for(lambda: queue2.get(job_id).state in (JobState.DOWNLOADING, JobState.COMPLETED))
    assert wait_for(lambda: queue2.get(job_id).state == JobState.COMPLETED)
    queue2.shutdown()


def test_resume_all_after_pause_all_resumes_stopping_jobs(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider, max_concurrent=2)
    queue.start()
    queue.add(make_jobs([f"https://e.com/block{i}" for i in range(3)], downloads))
    assert wait_for(lambda: sorted(states(queue)) == ["downloading", "downloading", "queued"])
    queue.pause_all()
    queue.resume_all()  # immediately, while the two running jobs are still stopping
    time.sleep(1.0)
    assert "paused" not in states(queue)
    assert sorted(states(queue)) == ["downloading", "downloading", "queued"]
    provider.release.set()
    assert wait_for(lambda: all(s == "completed" for s in states(queue)))
    queue.shutdown()


class _PartialProvider:
    """Writes 1.25 MiB of partial data, reports it, then waits to be stopped."""

    name = "direct"

    def __init__(self) -> None:
        self.reported = threading.Event()

    def inspect(self, url, token, settings):
        return InspectResult(provider="direct", title="x")

    def download(self, ctx):
        (ctx.staging_dir / "download.part").write_bytes(b"\x00" * 1_310_720)
        ctx.report(ProgressUpdate(downloaded=1_310_720, total=10_000_000))
        self.reported.set()
        while not ctx.token.wait(0.05):
            pass
        ctx.token.raise_if_stopped()


def test_interrupt_persists_downloaded_bytes(tmp_path):
    provider = _PartialProvider()
    queue, db, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/partial"], downloads))
    assert provider.reported.wait(5)
    # Crash before the periodic checkpoint: snapshot the database without a clean shutdown.
    snapshot = sqlite3.connect(tmp_path / "crashed.sqlite3")
    db._conn.backup(snapshot)
    snapshot.close()
    queue2 = _reopen(tmp_path, provider, tmp_path / "crashed.sqlite3")
    queue2.load()
    restored = queue2.get(job_id)
    assert restored.state == JobState.INTERRUPTED
    assert restored.downloaded_bytes == 1_310_720
    queue.shutdown(timeout=3)


def test_clean_all_partials_holds_lock(tmp_path, monkeypatch):
    import swiftdrop.queue as queue_module

    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/block"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING)
    queue.pause([job_id])
    assert wait_for(lambda: queue.get(job_id).state == JobState.PAUSED)
    (queue.staging_dir(job_id) / "old.part").write_bytes(b"old partial data")

    real_remove_tree = queue_module.remove_tree
    started_during_cleanup = []

    def racing_remove_tree(path):
        if path.name == job_id and not started_during_cleanup:
            # The user resumes the job while its partial folder is being cleaned up.
            queue.resume([job_id])
            started_during_cleanup.append(
                wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING, timeout=0.6)
            )
        return real_remove_tree(path)

    monkeypatch.setattr(queue_module, "remove_tree", racing_remove_tree)
    queue.clean_all_partials()
    assert started_during_cleanup == [False], "the job must not start while its folder is being deleted"
    assert wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING)
    assert wait_for(lambda: queue.staging_dir(job_id).exists())  # the worker creates it after the state flips
    provider.release.set()
    assert wait_for(lambda: queue.get(job_id).state in (JobState.COMPLETED, JobState.FAILED))
    assert queue.get(job_id).state == JobState.COMPLETED
    queue.shutdown()


def test_add_paused_jobs_start_paused(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/later"], downloads), paused=True)
    assert queue.get(job_id).state == JobState.PAUSED
    time.sleep(1.0)
    assert queue.get(job_id).state == JobState.PAUSED
    assert provider.calls == []
    queue.shutdown()


class _SlowUnwind:
    """Blocks until stopped, then takes 0.6 s to unwind (like a slow socket close)."""

    name = "direct"

    def __init__(self) -> None:
        self.starts = 0

    def inspect(self, url, token, settings):
        return InspectResult(provider="direct", title="x")

    def download(self, ctx):
        self.starts += 1
        (ctx.staging_dir / "x.part").write_bytes(b"\0" * 1000)
        ctx.report(ProgressUpdate(downloaded=1000, total=10000))
        while not ctx.token.wait(0.02):
            pass
        reason = ctx.token.reason  # engines read the reason when they raise
        time.sleep(0.6)
        from swiftdrop.cancel import JobStopped

        raise JobStopped(reason)


def _started(queue, provider, job_id):
    return wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING and provider.starts == 1)


def test_pause_resume_pause_ends_paused(tmp_path):
    provider = _SlowUnwind()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/a"], downloads))
    assert _started(queue, provider, job_id)
    queue.pause([job_id])
    queue.resume([job_id])
    queue.pause([job_id])  # the user's last action
    time.sleep(1.5)
    assert queue.get(job_id).state == JobState.PAUSED
    assert provider.starts == 1
    queue.shutdown(timeout=2)


def test_pause_resume_cancel_ends_cancelled(tmp_path):
    provider = _SlowUnwind()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/a"], downloads))
    assert _started(queue, provider, job_id)
    queue.pause([job_id])
    time.sleep(0.1)  # the engine has already raised with reason PAUSE
    queue.resume([job_id])
    queue.cancel([job_id])  # the user's last action
    time.sleep(1.5)
    assert queue.get(job_id).state == JobState.CANCELLED
    assert provider.starts == 1
    queue.shutdown(timeout=2)


def test_paused_then_quit_stays_paused_on_resume_launch(tmp_path):
    provider = _SlowUnwind()
    queue, _, _, downloads = build_queue(tmp_path, provider, resume_on_launch=True)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/a"], downloads))
    assert _started(queue, provider, job_id)
    queue.pause([job_id])  # the user pauses...
    queue.shutdown(timeout=0.2)  # ...and quits before the pause has finished unwinding
    queue2 = _reopen(tmp_path, provider, tmp_path / "db.sqlite3")
    queue2.load()
    assert queue2.get(job_id).state == JobState.PAUSED


def test_cancelled_then_quit_stays_cancelled_on_resume_launch(tmp_path):
    provider = _SlowUnwind()
    queue, _, _, downloads = build_queue(tmp_path, provider, resume_on_launch=True)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/a"], downloads))
    assert _started(queue, provider, job_id)
    queue.cancel([job_id])
    queue.shutdown(timeout=0.2)
    queue2 = _reopen(tmp_path, provider, tmp_path / "db.sqlite3")
    queue2.load()
    assert queue2.get(job_id).state == JobState.CANCELLED


def test_clean_all_resets_failed_job(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/fail"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.FAILED)
    with queue._lock:  # a failed job that had made progress and can still be retried
        job = queue._jobs[job_id]
        job.downloaded_bytes, job.total_bytes, job.progress = 5000, 10000, 0.5
        job.meta["http"] = {"etag": '"v1"', "accept_ranges": True}
    (queue.staging_dir(job_id) / "download.part").write_bytes(b"\0" * 5000)
    queue.clean_all_partials()
    job = queue.get(job_id)
    assert not queue.staging_dir(job_id).exists()
    assert job.downloaded_bytes == 0
    assert "http" not in job.meta
    queue.shutdown(timeout=2)


def test_cancel_then_retry_during_cleanup(tmp_path, monkeypatch):
    import swiftdrop.queue as queue_module

    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    (job_id,) = queue.add(make_jobs(["https://e.com/slow"], downloads), paused=True)
    queue.staging_dir(job_id).mkdir(parents=True)
    (queue.staging_dir(job_id) / "old.part").write_bytes(b"x" * 10)
    queue.start()
    real_remove_tree = queue_module.remove_tree

    def slow_remove(path):
        if path.name == job_id:
            queue.retry([job_id])  # the user clicks Retry right after Cancel
            wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING, timeout=1)
            time.sleep(0.2)  # a large folder takes a while to delete
        return real_remove_tree(path)

    monkeypatch.setattr(queue_module, "remove_tree", slow_remove)
    queue.cancel([job_id])
    monkeypatch.setattr(queue_module, "remove_tree", real_remove_tree)
    assert wait_for(lambda: queue.get(job_id).state in (JobState.COMPLETED, JobState.FAILED), timeout=10)
    assert queue.get(job_id).state == JobState.COMPLETED, queue.get(job_id).error
    queue.shutdown(timeout=2)


class _MarkerProvider:
    """Marks its job's meta and writes a fresh partial file, then waits to be released."""

    name = "direct"

    def __init__(self) -> None:
        self.starts: list[float] = []
        self.release = threading.Event()
        self.marker_at_end: list[str | None] = []

    def inspect(self, url, token, settings):
        return InspectResult(provider="direct", title="x")

    def download(self, ctx):
        self.starts.append(time.monotonic())
        ctx.meta["marker"] = "set-by-running-job"
        (ctx.staging_dir / "new.part").write_bytes(b"new data")
        while not self.release.is_set():
            ctx.token.raise_if_stopped()
            time.sleep(0.01)
        self.marker_at_end.append(ctx.meta.get("marker"))
        path = ctx.finalize(ctx.staging_dir / "new.part", f"{ctx.job_id}.bin", MediaKind.OTHER)
        return DownloadOutcome(filepath=path, size=8, kind=MediaKind.OTHER)


def test_cancel_retry_during_cleanup_waits_for_the_owner(tmp_path, monkeypatch):
    import swiftdrop.queue as queue_module

    provider = _MarkerProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    (job_id,) = queue.add(make_jobs(["https://e.com/x"], downloads), paused=True)
    staging = queue.staging_dir(job_id)
    staging.mkdir(parents=True)
    (staging / "old.part").write_bytes(b"old partial data")
    queue.start()
    real_remove_tree = queue_module.remove_tree
    injected = {"done": False}
    started_during_cleanup = []

    def slow_remove(path):
        if path.name == job_id and not injected["done"]:
            injected["done"] = True  # clean_all_partials is deleting this folder right now
            queue.cancel([job_id])
            queue.retry([job_id])
            queue.cancel([job_id])
            queue.retry([job_id])
            started_during_cleanup.append(wait_for(lambda: bool(provider.starts), timeout=0.6))
        return real_remove_tree(path)

    monkeypatch.setattr(queue_module, "remove_tree", slow_remove)
    queue.clean_all_partials()
    monkeypatch.setattr(queue_module, "remove_tree", real_remove_tree)
    assert started_during_cleanup == [False], "the job started while its folder was still being deleted"
    assert wait_for(lambda: bool(provider.starts))
    provider.release.set()
    assert wait_for(lambda: queue.get(job_id).state in (JobState.COMPLETED, JobState.FAILED))
    assert queue.get(job_id).state == JobState.COMPLETED, queue.get(job_id).error
    assert provider.marker_at_end == ["set-by-running-job"], "cleanup reset a running job's meta"
    queue.shutdown(timeout=2)


def test_multi_cancel_db_error_releases_reservations(tmp_path, monkeypatch):
    import contextlib

    provider = FakeProvider()
    queue, db, _, downloads = build_queue(tmp_path, provider)
    first, second = queue.add(make_jobs(["https://e.com/one", "https://e.com/two"], downloads), paused=True)
    for job_id in (first, second):
        queue.staging_dir(job_id).mkdir(parents=True)
        (queue.staging_dir(job_id) / "old.part").write_bytes(b"old")
    original = db.save_jobs

    def fail_on_second(jobs):
        jobs = list(jobs)
        if any(j.id == second and j.state == JobState.CANCELLED for j in jobs):
            raise sqlite3.OperationalError("database or disk is full")
        return original(jobs)

    monkeypatch.setattr(db, "save_jobs", fail_on_second)
    queue.start()
    with contextlib.suppress(sqlite3.OperationalError):
        queue.cancel([first, second])
    assert not queue._reserved, "a reservation leaked, so that job could never start again"
    monkeypatch.setattr(db, "save_jobs", original)
    queue.retry([first])
    assert wait_for(lambda: queue.get(first).state == JobState.COMPLETED)
    queue.shutdown(timeout=2)


def test_cancel_landing_just_before_finish_wins(tmp_path, monkeypatch):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/block"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.DOWNLOADING)
    original_finish = queue._finish_job

    def finish_after_late_cancel(*args):
        queue.cancel([job_id])  # the user cancels right after the engine stopped for a pause
        return original_finish(*args)

    monkeypatch.setattr(queue, "_finish_job", finish_after_late_cancel)
    queue.pause([job_id])
    assert wait_for(lambda: queue.get(job_id).state in (JobState.PAUSED, JobState.CANCELLED))
    assert queue.get(job_id).state == JobState.CANCELLED
    queue.shutdown(timeout=2)


def test_finish_failure_releases_its_reservation(tmp_path, monkeypatch):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    original_save = queue._save_quietly

    def failing_save(jobs):
        if any(j.state == JobState.COMPLETED for j in jobs):
            raise RuntimeError("unexpected failure while finishing")
        return original_save(jobs)

    monkeypatch.setattr(queue, "_save_quietly", failing_save)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/a"], downloads))
    assert wait_for(lambda: job_id not in queue._running and queue.get(job_id).state == JobState.COMPLETED)
    # The worker releases its hold after the state flips; a leaked hold never clears.
    assert wait_for(lambda: not queue._reserved), "the finishing job's reservation leaked"
    queue.shutdown(timeout=2)


def test_filename_override_is_used_and_survives_resets(tmp_path, http_server):
    """A name chosen in the browser confirm window wins over the server's, and resets keep it."""
    url = http_server.add_file("server-name.bin", make_bytes(50_000))
    provider = DirectProvider(lambda: HttpDownloader(backoff_base=0.01, backoff_max=0.02))
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    job = Job(url=url, key=url, destination=str(downloads), provider="direct", meta={"filename_override": "Mine.bin"})
    (job_id,) = queue.add([job])
    assert wait_for(lambda: queue.get(job_id).state == JobState.COMPLETED, timeout=15)
    assert (downloads / "Mine.bin").read_bytes() == make_bytes(50_000)
    assert queue.get(job_id).filename == "Mine.bin"
    assert not (downloads / "server-name.bin").exists()
    queue.shutdown(timeout=2)


def test_resets_keep_filename_override_but_clear_resume_state(tmp_path):
    provider = FakeProvider()
    queue, _, _, downloads = build_queue(tmp_path, provider)
    queue.start()
    (job_id,) = queue.add(make_jobs(["https://e.com/fail"], downloads))
    assert wait_for(lambda: queue.get(job_id).state == JobState.FAILED)
    with queue._lock:
        queue._jobs[job_id].meta.update(
            {"filename_override": "keep.bin", "http": {"etag": '"v1"'}, "announced": True, "streams": {}}
        )
    (queue.staging_dir(job_id)).mkdir(parents=True, exist_ok=True)
    queue.clean_all_partials()
    assert queue.get(job_id).meta == {"filename_override": "keep.bin"}
    with queue._lock:
        queue._jobs[job_id].meta["http"] = {"etag": '"v2"'}
    queue.cancel([job_id])
    queue.retry([job_id])
    assert queue.get(job_id).meta.get("filename_override") == "keep.bin"
    assert "http" not in queue.get(job_id).meta
    queue.shutdown(timeout=2)
