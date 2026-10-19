import time

import pytest

from swiftdrop.history import HistoryStore
from swiftdrop.models import ErrorInfo, Job, JobState, MediaKind
from swiftdrop.settings import SettingsError, SettingsStore
from swiftdrop.storage import Database


def test_settings_defaults_and_persistence(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    store = SettingsStore(db)
    assert store.get().max_concurrent == 3
    assert store.get().clipboard_monitoring is False, "the in-app clipboard banner must be off by default"
    assert store.get().clipboard_popup is False, "copying alone must not pop up unless the user turns it on"
    assert store.get().watch_clipboard is False, "no clipboard watcher by default"
    assert store.get().hotkey_enabled is True and store.get().hotkey == "ctrl+alt+d"
    assert store.get().shortcut_notice_seen is False
    assert store.get().download_dir  # defaults to ~/Downloads
    store.update({"max_concurrent": 6, "theme": "dark", "download_dir": str(tmp_path), "bandwidth_limit_kbps": 512})
    db.close()

    reopened = SettingsStore(Database(tmp_path / "db.sqlite3"))
    settings = reopened.get()
    assert settings.max_concurrent == 6
    assert settings.theme == "dark"
    assert settings.download_dir == str(tmp_path.resolve())
    assert settings.bandwidth_bytes_per_sec == 512 * 1024


@pytest.mark.parametrize(
    "patch",
    [
        {"max_concurrent": 0},
        {"max_concurrent": 11},
        {"max_concurrent": "3"},
        {"max_concurrent": True},
        {"theme": "neon"},
        {"default_quality": "8k"},
        {"notifications": "yes"},
        {"download_dir": "relative/path"},
        {"download_dir": "/definitely/not/here"},
        {"cookies_from_browser": "netscape"},
        {"unknown_key": 1},
        ["not", "a", "dict"],
    ],
)
def test_settings_validation_rejects_bad_values(tmp_path, patch):
    store = SettingsStore(Database(tmp_path / "db.sqlite3"))
    before = store.get()
    with pytest.raises(SettingsError):
        store.update(patch)
    assert store.get() == before


def test_settings_survive_deleted_destination(tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    db = Database(tmp_path / "db.sqlite3")
    SettingsStore(db).update({"download_dir": str(folder)})
    db.close()
    folder.rmdir()
    store = SettingsStore(Database(tmp_path / "db.sqlite3"))
    assert store.get().download_dir != str(folder)  # falls back to the default


def test_corrupt_database_is_moved_aside(tmp_path):
    path = tmp_path / "db.sqlite3"
    path.write_bytes(b"this is not a sqlite database" * 100)
    db = Database(path)
    assert SettingsStore(db).get().max_concurrent == 3
    assert any(p.name.startswith("db.sqlite3.corrupt-") for p in tmp_path.iterdir())


def _job(tmp_path, name, state, kind=MediaKind.VIDEO, error=None):
    path = tmp_path / name
    if state == JobState.COMPLETED:
        path.write_bytes(b"x")
    return Job(
        url=f"https://example.com/{name}",
        key=f"example.com/{name}",
        destination=str(tmp_path),
        title=name,
        source="example.com",
        kind=kind,
        state=state,
        filepath=str(path) if state == JobState.COMPLETED else None,
        file_size=1,
        finished_at=time.time(),
        error=error,
    )


def test_history_record_search_and_clear_keeps_files(tmp_path):
    history = HistoryStore(Database(tmp_path / "db.sqlite3"))
    history.record(_job(tmp_path, "holiday.mp4", JobState.COMPLETED))
    history.record(_job(tmp_path, "podcast.mp3", JobState.COMPLETED, MediaKind.AUDIO))
    history.record(
        _job(tmp_path, "broken.mp4", JobState.FAILED, error=ErrorInfo("not_found", "Not found", "missing")),
    )
    history.record(_job(tmp_path, "running.mp4", JobState.DOWNLOADING))  # ignored
    assert history.search()["total"] == 3
    assert [i["title"] for i in history.search(query="holi")["items"]] == ["holiday.mp4"]
    assert [i["title"] for i in history.search(kind="audio")["items"]] == ["podcast.mp3"]
    failed = history.search(status="failed")["items"]
    assert failed[0]["error_message"] == "missing"
    assert history.search(query="100%_")["total"] == 0  # LIKE wildcards are escaped
    assert history.find_completed("example.com/holiday.mp4")["file_exists"] is True
    assert history.clear() == 3
    assert (tmp_path / "holiday.mp4").exists(), "clearing history must never delete files"


def test_history_find_completed_ignores_missing_files(tmp_path):
    history = HistoryStore(Database(tmp_path / "db.sqlite3"))
    job = _job(tmp_path, "temp.mp4", JobState.COMPLETED)
    history.record(job)
    (tmp_path / "temp.mp4").unlink()
    assert history.find_completed(job.key) is None


def test_invalid_patch_leaves_login_item_untouched(tmp_path):
    from swiftdrop.paths import AppPaths
    from swiftdrop.platform import NullPlatform
    from swiftdrop.service import AppService, ServiceError

    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    platform = NullPlatform()
    svc = AppService(paths, platform, enable_sites=False)
    try:
        with pytest.raises(ServiceError):
            svc.update_settings({"open_at_login": True, "theme": "bogus"})
        assert platform.login_item_calls == []
    finally:
        svc.shutdown()
