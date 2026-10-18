"""The download queue: scheduling, bounded concurrency and job lifecycle.

* One dispatcher thread starts at most ``max_concurrent`` worker threads; all
  other jobs wait in FIFO order. Nothing scales with the number of queued
  links, so 1,000 pasted URLs cost memory, not processes.
* Every job runs inside its own ``try`` — a failure is recorded on that job
  and the dispatcher moves on.
* Pause/cancel are cooperative (:class:`~swiftdrop.cancel.CancelToken`); a
  paused job keeps its partial data in ``partial/<job id>/`` and resumes from
  there.
* State transitions are persisted immediately, progress at most every few
  seconds, so a crash or quit never marks unfinished work as complete.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from swiftdrop.cancel import CancelToken, JobStopped, StopReason
from swiftdrop.engine.progress import ProgressUpdate, SpeedMeter
from swiftdrop.errors import DownloadFailure, classify_exception, failure, make_error
from swiftdrop.events import ChangeTracker
from swiftdrop.filenames import sanitize_filename, subfolder_for_kind
from swiftdrop.fileops import dir_size, move_into_place, remove_tree, reserve_unique_path
from swiftdrop.history import HistoryStore
from swiftdrop.logging_setup import get_logger
from swiftdrop.models import (
    ACTIVE_STATES,
    FINISHED_STATES,
    RESUMABLE_STATES,
    Collection,
    ErrorInfo,
    Job,
    JobState,
    MediaKind,
)
from swiftdrop.providers.base import DownloadOutcome
from swiftdrop.providers.registry import ProviderRegistry
from swiftdrop.settings import Settings, SettingsStore
from swiftdrop.storage import Database

log = get_logger("queue")

CHECKPOINT_INTERVAL = 5.0
_SETTABLE_INFO = frozenset(
    {
        "title",
        "filename",
        "kind",
        "thumbnail",
        "extractor",
        "duration",
        "quality_label",
        "resumable",
        "provider",
        "note",
    }
)


@dataclass
class _Running:
    thread: threading.Thread
    token: CancelToken
    remove_when_done: bool = False


@dataclass
class BatchSummary:
    completed: int = 0
    failed: int = 0
    cancelled: int = 0

    def any(self) -> bool:
        return bool(self.completed or self.failed)


class _Context:
    """The :class:`~swiftdrop.providers.base.JobContext` handed to providers."""

    def __init__(
        self, queue: DownloadQueue, job: Job, token: CancelToken, settings: Settings, collection_folder: str | None
    ) -> None:
        self._queue = queue
        self.job_id = job.id
        self.url = job.url
        self.options = job.options
        self.settings = settings
        self.token = token
        self.staging_dir = queue.staging_dir(job.id)
        self.meta = job.meta  # shared dict; persisted with the job
        self.collection_folder = collection_folder
        self.destination = job.destination
        self._last_checkpoint = time.monotonic()

    def report(self, update: ProgressUpdate) -> None:
        self._queue._apply_progress(self.job_id, update)
        now = time.monotonic()
        if now - self._last_checkpoint >= CHECKPOINT_INTERVAL:
            self._last_checkpoint = now
            self.checkpoint()

    def set_info(self, **fields: Any) -> None:
        self._queue._apply_info(self.job_id, fields)

    def checkpoint(self) -> None:
        self._queue._persist_ids([self.job_id])

    def finalize(self, source: Path, filename: str, kind: MediaKind) -> Path:
        directory = Path(self.destination)
        if self.settings.organize_by_type:
            directory = directory / subfolder_for_kind(kind)
        if self.collection_folder and self.settings.playlist_subfolders:
            directory = directory / self.collection_folder
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if not os.access(directory, os.W_OK | os.X_OK):
                raise failure("permission", f"not writable: {directory}")
            target = reserve_unique_path(directory, filename)
            return move_into_place(source, target)
        except DownloadFailure:
            raise
        except OSError as exc:
            raise DownloadFailure(classify_exception(exc)) from exc


class DownloadQueue:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        db: Database,
        history: HistoryStore,
        settings: SettingsStore,
        tracker: ChangeTracker,
        partial_root: Path,
        on_batch_finished: Callable[[BatchSummary], None] | None = None,
    ) -> None:
        self._registry = registry
        self._db = db
        self._history = history
        self._settings = settings
        self._tracker = tracker
        self._partial_root = partial_root
        self._on_batch_finished = on_batch_finished
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._jobs: dict[str, Job] = {}
        self._collections: dict[str, Collection] = {}
        self._running: dict[str, _Running] = {}
        self._order = 0
        self._stopping = False
        self._dispatcher: threading.Thread | None = None
        self._batch = BatchSummary()
        self.peak_concurrency = 0  # observability / tests
        # Aggregate throughput across all jobs. Measured from real byte counts, so it stays
        # accurate even when each file finishes before its own meter has enough samples.
        self._bytes_transferred = 0
        self._throughput = SpeedMeter(window=3.0, min_elapsed=0.5)

    # -- lifecycle --------------------------------------------------------
    def load(self) -> None:
        """Restore jobs from the database, never promoting unfinished work."""
        resume = self._settings.get().resume_on_launch
        changed: list[Job] = []
        with self._lock:
            for collection in self._db.load_collections():
                self._collections[collection.id] = collection
            for job in self._db.load_jobs():
                job.speed = None
                job.eta = None
                if job.state in ACTIVE_STATES:
                    job.state = JobState.QUEUED if resume else JobState.INTERRUPTED
                    job.phase = ""
                    job.note = "Interrupted when the app quit — resume to continue."
                    changed.append(job)
                elif job.state == JobState.QUEUED and not resume:
                    job.state = JobState.PAUSED
                    job.note = "Restored from your last session."
                    changed.append(job)
                elif job.state == JobState.COMPLETED:
                    job.file_missing = not (job.filepath and os.path.exists(job.filepath))
                self._jobs[job.id] = job
                self._order = max(self._order, job.order + 1)
            self._drop_orphan_collections()
        if changed:
            self._db.save_jobs(changed)

    def start(self) -> None:
        with self._lock:
            if self._dispatcher is not None:
                return
            self._stopping = False
            self._dispatcher = threading.Thread(target=self._dispatch_loop, name="queue-dispatcher", daemon=True)
            self._dispatcher.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop scheduling, interrupt running jobs (resumable) and persist everything."""
        with self._cond:
            self._stopping = True
            running = list(self._running.values())
            for item in running:
                item.token.stop(StopReason.SHUTDOWN)
            self._cond.notify_all()
        deadline = time.monotonic() + timeout
        for item in running:
            item.thread.join(max(0.0, deadline - time.monotonic()))
        if self._dispatcher is not None:
            self._dispatcher.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            for job in self._jobs.values():
                if job.state in ACTIVE_STATES:
                    job.state = JobState.INTERRUPTED
                    job.speed = job.eta = None
            self._db.save_jobs(list(self._jobs.values()))

    def notify_settings_changed(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def staging_dir(self, job_id: str) -> Path:
        return self._partial_root / job_id

    # -- adding -----------------------------------------------------------
    def add(self, jobs: Iterable[Job], collection: Collection | None = None) -> list[str]:
        added: list[Job] = []
        with self._cond:
            if collection is not None:
                self._collections[collection.id] = collection
                self._db.save_collection(collection)
            for job in jobs:
                job.order = self._order
                self._order += 1
                job.state = JobState.QUEUED
                if collection is not None:
                    job.collection_id = collection.id
                self._jobs[job.id] = job
                added.append(job)
            self._db.save_jobs(added)
            for job in added:
                self._tracker.job(job.id)
            if collection is not None:
                self._tracker.collections()
            self._cond.notify_all()
        return [job.id for job in added]

    # -- dispatching ------------------------------------------------------
    def _next_queued(self) -> Job | None:
        best: Job | None = None
        for job in self._jobs.values():
            if (
                job.state == JobState.QUEUED
                and job.id not in self._running
                and (best is None or job.order < best.order)
            ):
                best = job
        return best

    def _dispatch_loop(self) -> None:
        with self._cond:
            while not self._stopping:
                limit = self._settings.get().max_concurrent
                while len(self._running) < limit and not self._stopping:
                    job = self._next_queued()
                    if job is None:
                        break
                    self._start_job(job)
                self._cond.wait(timeout=1.0)

    def _start_job(self, job: Job) -> None:
        token = CancelToken()
        settings = self._settings.get()
        collection = self._collections.get(job.collection_id) if job.collection_id else None
        folder = sanitize_filename(collection.title, default="Playlist") if collection else None
        job.state = JobState.DOWNLOADING
        job.attempts += 1
        job.started_at = time.time()
        job.error = None
        job.note = None
        job.speed = job.eta = None
        job.phase = "Starting"
        ctx = _Context(self, job, token, settings, folder)
        thread = threading.Thread(target=self._run_job, args=(job.id, ctx), name=f"job-{job.id}", daemon=True)
        self._running[job.id] = _Running(thread=thread, token=token)
        self.peak_concurrency = max(self.peak_concurrency, len(self._running))
        self._db.save_jobs([job])
        self._tracker.job(job.id)
        thread.start()

    def _run_job(self, job_id: str, ctx: _Context) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            provider_name = job.provider if job else "auto"
        outcome = None
        error = None
        stop_reason: StopReason | None = None
        try:
            ctx.staging_dir.mkdir(parents=True, exist_ok=True)
            provider = self._registry.provider(provider_name)
            outcome = provider.download(ctx)
        except JobStopped as exc:
            stop_reason = exc.reason
        except DownloadFailure as exc:
            error = exc.info
        except Exception as exc:
            log.exception("Job %s crashed", job_id)
            error = classify_exception(exc)
        if outcome is None and error is None and stop_reason is None:
            error = make_error("unknown", "provider returned no result")
        if error is not None and ctx.token.stopped:
            # Errors raised while unwinding a pause/cancel are noise.
            stop_reason, error = ctx.token.reason, None
        self._finish_job(job_id, ctx, outcome, error, stop_reason)

    def _finish_job(
        self,
        job_id: str,
        ctx: _Context,
        outcome: DownloadOutcome | None,
        error: ErrorInfo | None,
        stop_reason: StopReason | None,
    ) -> None:
        cleanup_staging = False
        record_history = False
        with self._cond:
            running = self._running.pop(job_id, None)
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.speed = None
            job.eta = None
            if outcome is not None:
                job.state = JobState.COMPLETED
                job.filepath = str(outcome.filepath)
                job.filename = outcome.filepath.name
                job.file_size = outcome.size
                job.kind = outcome.kind if outcome.kind != MediaKind.UNKNOWN else job.kind
                job.sha256 = outcome.sha256
                job.progress = 1.0
                job.downloaded_bytes = outcome.size
                job.total_bytes = outcome.size
                job.total_is_estimate = False
                job.phase = ""
                job.finished_at = time.time()
                job.file_missing = False
                cleanup_staging = True
                record_history = True
                self._batch.completed += 1
            elif stop_reason == StopReason.PAUSE:
                job.state = JobState.PAUSED
                job.phase = ""
            elif stop_reason == StopReason.SHUTDOWN:
                job.state = JobState.INTERRUPTED
                job.phase = ""
                job.note = "Interrupted when the app quit — resume to continue."
            elif stop_reason == StopReason.CANCEL:
                job.state = JobState.CANCELLED
                job.phase = ""
                job.finished_at = time.time()
                cleanup_staging = True
                record_history = True
                self._batch.cancelled += 1
            else:
                job.state = JobState.FAILED
                job.error = error
                job.phase = ""
                job.finished_at = time.time()
                record_history = True
                self._batch.failed += 1
            remove = bool(running and running.remove_when_done)
            self._db.save_jobs([job])
            collection = self._collections.get(job.collection_id) if job.collection_id else None
            snapshot = replace(job)
            self._cond.notify_all()
        if cleanup_staging:
            remove_tree(ctx.staging_dir)
        if record_history:
            self._record_history(snapshot, collection)
        if remove:
            self.remove([job_id])
        else:
            self._tracker.job(job_id)
            if collection is not None:
                self._tracker.collections()
        self._maybe_batch_finished()

    def _record_history(self, job: Job, collection: Collection | None) -> None:
        if not self._settings.get().save_history:
            return
        try:
            self._history.record(job, collection.title if collection else None)
            self._tracker.history()
        except Exception:
            log.exception("Could not record history for %s", job.id)

    def _maybe_batch_finished(self) -> None:
        with self._lock:
            busy = self._running or any(j.state == JobState.QUEUED for j in self._jobs.values())
            if busy or not self._batch.any():
                return
            summary, self._batch = self._batch, BatchSummary()
        if self._on_batch_finished:
            try:
                self._on_batch_finished(summary)
            except Exception:
                log.exception("Batch-finished callback failed")

    # -- progress from providers -----------------------------------------
    def _apply_progress(self, job_id: str, update: ProgressUpdate) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in ACTIVE_STATES:
                return
            if update.processing:
                job.state = JobState.PROCESSING
            if update.downloaded is not None:
                self._bytes_transferred += max(0, update.downloaded - (job.downloaded_bytes or 0))
                job.downloaded_bytes = update.downloaded
            if update.total is not None:
                job.total_bytes = update.total
                job.total_is_estimate = update.total_is_estimate
            if update.downloaded is not None or update.total is not None:
                job.speed = update.speed
                job.eta = update.eta
            if update.progress is not None:
                job.progress = max(0.0, min(1.0, update.progress))
            elif update.downloaded is not None and job.total_bytes:
                job.progress = max(0.0, min(1.0, job.downloaded_bytes / job.total_bytes))
            if update.phase is not None:
                job.phase = update.phase
        self._tracker.job(job_id)

    def _apply_info(self, job_id: str, fields: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                if key not in _SETTABLE_INFO:
                    raise ValueError(f"providers may not set {key}")
                if key == "kind" and not isinstance(value, MediaKind):
                    value = MediaKind(value)
                if key == "title" and not value:
                    continue
                setattr(job, key, value)
        self._tracker.job(job_id)

    def _persist_ids(self, ids: Iterable[str]) -> None:
        with self._lock:
            jobs = [replace(self._jobs[i], meta=dict(self._jobs[i].meta)) for i in ids if i in self._jobs]
        self._db.save_jobs(jobs)

    # -- user actions -----------------------------------------------------
    def _select(self, ids: Iterable[str]) -> list[Job]:
        return [self._jobs[i] for i in ids if isinstance(i, str) and i in self._jobs]

    def pause(self, ids: Iterable[str]) -> int:
        count = 0
        with self._cond:
            for job in self._select(ids):
                if job.state == JobState.QUEUED:
                    job.state = JobState.PAUSED
                    self._db.save_jobs([job])
                    self._tracker.job(job.id)
                    count += 1
                elif job.state in ACTIVE_STATES and job.id in self._running:
                    self._running[job.id].token.stop(StopReason.PAUSE)
                    job.phase = "Pausing…"
                    self._tracker.job(job.id)
                    count += 1
        return count

    def resume(self, ids: Iterable[str]) -> int:
        count = 0
        with self._cond:
            for job in self._select(ids):
                if job.state in RESUMABLE_STATES or job.state == JobState.FAILED:
                    job.state = JobState.QUEUED
                    job.note = None
                    job.error = None
                    job.finished_at = None
                    self._db.save_jobs([job])
                    self._tracker.job(job.id)
                    count += 1
            self._cond.notify_all()
        return count

    def retry(self, ids: Iterable[str]) -> int:
        count = 0
        with self._cond:
            for job in self._select(ids):
                if job.state in (JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED, JobState.PAUSED):
                    if job.state == JobState.CANCELLED:
                        job.reset_progress()
                        job.meta.clear()
                    job.state = JobState.QUEUED
                    job.error = None
                    job.note = None
                    job.finished_at = None
                    self._db.save_jobs([job])
                    self._tracker.job(job.id)
                    count += 1
                elif job.state == JobState.COMPLETED and job.file_missing:
                    job.reset_progress()
                    job.meta.clear()
                    job.state = JobState.QUEUED
                    job.filepath = None
                    job.file_missing = False
                    self._db.save_jobs([job])
                    self._tracker.job(job.id)
                    count += 1
            self._cond.notify_all()
        return count

    def cancel(self, ids: Iterable[str]) -> int:
        to_clean: list[str] = []
        finished: list[tuple[Job, Collection | None]] = []
        count = 0
        with self._cond:
            for job in self._select(ids):
                if job.id in self._running:
                    self._running[job.id].token.stop(StopReason.CANCEL)
                    job.phase = "Cancelling…"
                    self._tracker.job(job.id)
                    count += 1
                elif job.state in (JobState.QUEUED, JobState.PAUSED, JobState.INTERRUPTED, JobState.FAILED):
                    job.state = JobState.CANCELLED
                    job.finished_at = time.time()
                    job.speed = job.eta = None
                    self._db.save_jobs([job])
                    self._tracker.job(job.id)
                    to_clean.append(job.id)
                    collection = self._collections.get(job.collection_id) if job.collection_id else None
                    finished.append((replace(job), collection))
                    count += 1
        for job_id in to_clean:
            remove_tree(self.staging_dir(job_id))
        for snapshot, collection in finished:
            self._record_history(snapshot, collection)
        self._maybe_batch_finished()
        return count

    def remove(self, ids: Iterable[str]) -> int:
        """Remove jobs from the list. Completed files are never deleted."""
        removed: list[str] = []
        with self._cond:
            for job in self._select(ids):
                running = self._running.get(job.id)
                if running is not None:
                    running.remove_when_done = True
                    running.token.stop(StopReason.CANCEL)
                    continue
                del self._jobs[job.id]
                removed.append(job.id)
            self._db.delete_jobs(removed)
            self._drop_orphan_collections()
        for job_id in removed:
            remove_tree(self.staging_dir(job_id))
            self._tracker.job_removed(job_id)
        return len(removed)

    def pause_all(self) -> int:
        with self._lock:
            ids = [j.id for j in self._jobs.values() if j.state in ACTIVE_STATES or j.state == JobState.QUEUED]
        return self.pause(ids)

    def resume_all(self) -> int:
        with self._lock:
            ids = [j.id for j in self._jobs.values() if j.state in RESUMABLE_STATES]
        return self.resume(ids)

    def retry_failed(self) -> int:
        with self._lock:
            ids = [j.id for j in self._jobs.values() if j.state == JobState.FAILED]
        return self.retry(ids)

    def clear(self, which: str = "completed") -> int:
        states = {
            "completed": {JobState.COMPLETED},
            "finished": set(FINISHED_STATES),
            "failed": {JobState.FAILED},
            "cancelled": {JobState.CANCELLED},
        }.get(which)
        if states is None:
            raise ValueError("unknown filter")
        with self._lock:
            ids = [j.id for j in self._jobs.values() if j.state in states]
        return self.remove(ids)

    def _drop_orphan_collections(self) -> None:
        used = {j.collection_id for j in self._jobs.values() if j.collection_id}
        for collection_id in list(self._collections):
            if collection_id not in used:
                del self._collections[collection_id]
                self._db.delete_collection(collection_id)
                self._tracker.collections()

    # -- queries ------------------------------------------------------------
    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return replace(job) if job else None

    def jobs_public(self, ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if ids is None:
                jobs = sorted(self._jobs.values(), key=lambda j: j.order)
            else:
                jobs = [self._jobs[i] for i in ids if i in self._jobs]
            return [job.to_public() for job in jobs]

    def active_keys(self) -> dict[str, str]:
        """dedupe key → state for every job that is not finished."""
        with self._lock:
            return {j.key: j.state.value for j in self._jobs.values() if j.state not in FINISHED_STATES}

    def collections_public(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for collection in sorted(self._collections.values(), key=lambda c: c.created_at, reverse=True):
                members = [j for j in self._jobs.values() if j.collection_id == collection.id]
                counts = {state.value: 0 for state in JobState}
                for member in members:
                    counts[member.state.value] += 1
                fractions = [
                    1.0 if m.state == JobState.COMPLETED else (m.progress or 0.0)
                    for m in members
                    if m.state != JobState.CANCELLED
                ]
                data = collection.to_record()
                data.update(
                    {
                        "item_ids": [m.id for m in sorted(members, key=lambda m: (m.playlist_index or 0, m.order))],
                        "counts": counts,
                        "count": len(members),
                        "completed": counts[JobState.COMPLETED.value],
                        "progress": (sum(fractions) / len(fractions)) if fractions else 0.0,
                        "downloaded_bytes": sum(m.downloaded_bytes or 0 for m in members),
                    }
                )
                result.append(data)
            return result

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts = {state.value: 0 for state in JobState}
            for job in self._jobs.values():
                counts[job.state.value] += 1
            if self._running:
                speed = self._throughput.update(self._bytes_transferred) or 0.0
            else:
                self._throughput.reset()
                speed = 0.0
            return {
                "counts": counts,
                "active": counts["downloading"] + counts["processing"],
                "queued": counts["queued"],
                "total": len(self._jobs),
                "speed": speed,
                "running": len(self._running),
            }

    def partial_usage(self) -> int:
        return dir_size(self._partial_root) if self._partial_root.exists() else 0

    def clean_orphan_partials(self) -> int:
        """Delete staging folders that no paused/interrupted/failed job can resume from."""
        with self._lock:
            keep = {j.id for j in self._jobs.values() if j.state not in FINISHED_STATES or j.state == JobState.FAILED}
            keep |= set(self._running)
        freed = 0
        if not self._partial_root.exists():
            return 0
        for child in self._partial_root.iterdir():
            if child.name not in keep:
                freed += remove_tree(child) if child.is_dir() else _unlink_size(child)
        return freed

    def clean_all_partials(self) -> int:
        """Delete partial data for every job that isn't running (they will restart from zero)."""
        with self._lock:
            running = set(self._running)
        freed = 0
        if not self._partial_root.exists():
            return 0
        for child in self._partial_root.iterdir():
            if child.name in running:
                continue
            freed += remove_tree(child) if child.is_dir() else _unlink_size(child)
        return freed


def _unlink_size(path: Path) -> int:
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0
