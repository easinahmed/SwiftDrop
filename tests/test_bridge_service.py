"""Bridge security/validation and service-level rules (no GUI required)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.service import AppService
from swiftdrop.ui.bridge import Bridge
from tests.conftest import make_bytes, wait_for

EXPECTED_FUNCTIONS = {
    "get_bootstrap",
    "get_state",
    "analyze_text",
    "inspect_preview",
    "remove_preview",
    "clear_preview",
    "get_playlist_entries",
    "start_downloads",
    "job_action",
    "queue_action",
    "reveal_job",
    "open_job",
    "reveal_history",
    "open_history",
    "search_history",
    "clear_history",
    "delete_history",
    "get_settings",
    "update_settings",
    "choose_folder",
    "import_url_file",
    "read_clipboard",
    "copy_text",
    "export_data",
    "storage_info",
    "clean_temp",
    "get_diagnostics",
    "open_logs_folder",
    "open_partial_folder",
    "open_download_folder",
}


@pytest.fixture
def service(tmp_path):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    svc = AppService(paths, NullPlatform(), enable_sites=False)
    svc.settings.update({"download_dir": str(downloads)})
    svc.start()
    yield svc
    svc.shutdown()


@pytest.fixture
def api(service):
    bridge = Bridge(service)
    return {fn.__name__: fn for fn in bridge.functions()}, bridge


def test_exposed_surface_is_an_exact_allow_list(api):
    functions, _ = api
    assert set(functions) == EXPECTED_FUNCTIONS
    for fn in functions.values():
        # Plain functions (no bound objects) so pywebview can't walk into internals.
        assert inspect.isfunction(fn)


def test_bridge_never_leaks_tracebacks(api, service, monkeypatch):
    functions, _ = api

    def boom():
        raise RuntimeError("secret internal detail /Users/x token=abc")

    monkeypatch.setattr(service, "bootstrap", boom)
    result = functions["get_bootstrap"]()
    assert result["ok"] is False
    assert "secret" not in result["error"] and "Traceback" not in result["error"]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("analyze_text", (123, True)),
        ("analyze_text", ("x" * 2_000_001, True)),
        ("analyze_text", ("https://a.com", "yes")),
        ("job_action", ("rm -rf", ["0123456789abcdef"])),
        ("job_action", ("pause", ["../../etc"])),
        ("job_action", ("pause", "0123456789abcdef")),
        ("reveal_job", ("/etc/passwd",)),
        ("open_history", ("1; DROP TABLE history",)),
        ("queue_action", ("format_disk",)),
        ("start_downloads", ({"items": []},)),
        ("start_downloads", ({"items": [{"id": "bad"}]},)),
        ("update_settings", ({"max_concurrent": 999},)),
        ("update_settings", ("not-a-dict",)),
        ("copy_text", (None,)),
        ("export_data", ("/tmp/out.csv",)),
        ("clean_temp", ("yes",)),
        ("search_history", ({"limit": 10**9},)),
    ],
)
def test_bridge_rejects_invalid_input(api, name, args):
    functions, _ = api
    result = functions[name](*args)
    assert result["ok"] is False
    assert isinstance(result["error"], str) and result["error"]


def test_bridge_rejects_wrong_arity(api):
    functions, _ = api
    assert functions["analyze_text"]()["ok"] is False


def test_destination_must_come_from_folder_picker(api, service, tmp_path):
    functions, bridge = api
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    rejected = functions["update_settings"]({"download_dir": str(outside)})
    assert rejected["ok"] is False and "folder picker" in rejected["error"]
    bridge.approve_dir(str(outside))  # what choose_folder() does after the native dialog
    accepted = functions["update_settings"]({"download_dir": str(outside)})
    assert accepted["ok"] is True and accepted["data"]["download_dir"] == str(outside.resolve())


def test_reveal_only_uses_recorded_paths(api, service, http_server):
    functions, _ = api
    url = http_server.add_file("clip.mp4", make_bytes(20_000))
    added = functions["analyze_text"](url, True)["data"]["added"]
    started = functions["start_downloads"]({"items": [{"id": added[0]["id"], "entries": None}]})
    assert started["ok"], started
    job_id = started["data"]["job_ids"][0]
    assert wait_for(lambda: service.queue.get(job_id).state.value == "completed")
    assert functions["reveal_job"](job_id)["ok"] is True
    assert service.platform.revealed == [Path(service.queue.get(job_id).filepath)]


def test_push_payload_is_json_and_coalesced(api, service):
    _, bridge = api
    service.analyze_text("https://example.com/a.mp4 https://example.com/b.mp4")
    payload = bridge.build_push()
    assert payload is not None
    json.dumps(payload)  # must serialise for run_js
    assert len(payload["preview"]) == 2
    assert bridge.build_push() is None  # drained


def test_analyze_flags_blocked_duplicates_and_queue(service):
    result = service.analyze_text(
        "https://open.spotify.com/track/123\nhttps://example.com/a.mp4\nhttps://example.com/a.mp4\nftp://x.com/y"
    )
    assert result["duplicates"] == 1
    assert result["invalid_count"] == 1
    spotify = next(i for i in result["added"] if "spotify" in i["url"])
    assert spotify["status"] == "blocked"
    assert spotify["error"]["code"] == "drm"
    assert "Spotify" in spotify["error"]["title"]


def test_start_skips_items_already_in_queue(service, http_server):
    url = http_server.add_file("slow.bin", make_bytes(2_000_000)) + "?rate=200000"
    first = service.analyze_text(url)["added"][0]
    service.start_downloads([{"id": first["id"], "entries": None}], None, None)
    second = service.analyze_text(url)["added"][0]
    assert second["in_queue"] in ("queued", "downloading")
    result = service.start_downloads([{"id": second["id"], "entries": None}], None, None)
    assert result["created"] == 0
    assert result["skipped"][0]["reason"] == "Already in the queue"


def test_export_failed_links(service, http_server):
    url = http_server.url("/status/404")
    item = service.analyze_text(url)["added"][0]
    service.start_downloads([{"id": item["id"], "entries": None}], None, None)
    assert wait_for(lambda: service.queue.stats()["counts"]["failed"] == 1)
    name, content = service.export_text("failed")
    assert name.endswith(".txt") and url in content
    name, csv_text = service.export_text("results")
    assert name.endswith(".csv") and "status,title,url" in csv_text


def test_batch_notification(service, http_server):
    url = http_server.add_file("n.mp3", make_bytes(10_000))
    item = service.analyze_text(url)["added"][0]
    service.start_downloads([{"id": item["id"], "entries": None}], None, None)
    assert wait_for(lambda: service.platform.notifications)
    assert service.platform.notifications[0][0] == "Downloads complete"


def test_clipboard_detection_only_offers_new_links(service):
    service.analyze_text("https://example.com/known.mp4")
    service.tracker.drain()
    service.clipboard_detected("password123 and https://example.com/known.mp4 and https://example.com/new.mp4")
    changes = service.tracker.drain()
    assert changes.clipboard["urls"] == ["https://example.com/new.mp4"]
    service.clipboard_detected("just text, no links")
    assert service.tracker.drain().clipboard is None
