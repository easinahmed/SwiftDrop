"""Confirm windows for copied and sent links: what pops up, and what each choice does."""

from __future__ import annotations

import pytest

from swiftdrop.capture import MAX_PENDING, CaptureError
from swiftdrop.errors import failure
from swiftdrop.models import InspectResult, JobState, MediaKind
from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.providers.registry import SiteMatch
from swiftdrop.service import AppService
from tests.conftest import make_bytes, wait_for


class FakeUI:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.closed: list[str] = []

    def open(self, capture_id: str) -> None:
        self.opened.append(capture_id)

    def close(self, capture_id: str) -> None:
        self.closed.append(capture_id)


class FakeSites:
    """A video engine that knows exactly one site, offline."""

    name = "ytdlp"

    def match(self, url):
        return SiteMatch("Fake", "Fake", False) if "videos.example" in url else None

    def inspect(self, url, token, settings):
        raise failure("unsupported", "fake")

    def download(self, ctx):
        raise failure("unsupported", "fake")


@pytest.fixture
def service(tmp_path):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    svc = AppService(paths, NullPlatform(), enable_sites=False)
    svc.settings.update({"download_dir": str(downloads), "clipboard_popup": True})  # the opt-in auto pop-up
    svc.start()
    svc.queue.shutdown(timeout=1)  # jobs stay where they are added; the engine isn't under test here
    yield svc
    svc.shutdown()


@pytest.fixture
def ui(service):
    fake = FakeUI()
    shown = []
    service.capture.attach_ui(fake, show_main=lambda: shown.append(True))
    fake.shown = shown
    return fake


def opened(ui, count=1):
    assert wait_for(lambda: len(ui.opened) >= count, timeout=5)
    return ui.opened[count - 1]


def test_copied_file_link_pops_up_with_probed_name_and_size(service, ui, http_server, tmp_path):
    url = http_server.add_file("report.pdf", make_bytes(4000))
    service.clipboard_detected(f"look: {url}")
    info = service.capture.capture_public(opened(ui))
    assert info["kind"] == "file" and info["filename"] == "report.pdf" and info["size"] == 4000
    assert info["source"] == "127.0.0.1"
    assert info["folder"] == str(tmp_path / "Downloads")
    result = service.capture.decide(info["id"], "start", "My: report.pdf", str(tmp_path / "Downloads"))
    job = service.queue.get(result["job_id"])
    assert job.state == JobState.QUEUED and job.provider == "direct" and job.url == url
    assert job.meta == {"filename_override": "My- report.pdf"}  # sanitised
    assert ui.closed == [info["id"]]
    with pytest.raises(CaptureError):
        service.capture.decide(info["id"], "start", "x", str(tmp_path / "Downloads"))  # only once


def test_same_link_pops_up_once_per_session(service, ui, http_server):
    url = http_server.add_file("a.zip", make_bytes(100))
    service.clipboard_detected(url)
    opened(ui)
    service.clipboard_detected(url)
    service.clipboard_detected(f"again {url}")
    assert not wait_for(lambda: len(ui.opened) > 1, timeout=0.3)


def test_ordinary_and_failing_links_never_pop_up(service, ui, http_server):
    service.clipboard_detected("https://example.com/about and https://news.example.org/story")
    service.clipboard_detected(http_server.url("/status/403") + "?x=.zip")  # not a file extension: ignored
    service.clipboard_detected(http_server.url("/file/missing.zip"))  # a .zip that 404s: probe fails, stays quiet
    assert not wait_for(lambda: ui.opened, timeout=0.5)


def test_nothing_pops_up_without_a_window_or_when_switched_off(service, http_server):
    url = http_server.add_file("b.zip", make_bytes(100))
    service.clipboard_detected(url)  # no UI yet: no probe, no pop-up
    ui = FakeUI()
    service.capture.attach_ui(ui)
    assert service.capture.pending_ids() == []
    service.settings.update({"clipboard_popup": False})
    service.clipboard_detected(http_server.add_file("c.zip", make_bytes(100)))
    assert not wait_for(lambda: ui.opened, timeout=0.3)


def test_start_later_and_cancel(service, ui, http_server, tmp_path):
    service.clipboard_detected(http_server.add_file("d.mp4", make_bytes(100)))
    first = opened(ui)
    result = service.capture.decide(first, "later", "", str(tmp_path / "Downloads"))
    job = service.queue.get(result["job_id"])
    assert job.state == JobState.PAUSED and job.meta == {"filename_override": "d.mp4"} and job.kind == MediaKind.VIDEO
    service.clipboard_detected(http_server.add_file("e.mp4", make_bytes(100)))
    second = opened(ui, 2)
    assert service.capture.decide(second, "cancel", "", "")["job_id"] is None
    assert len(service.queue.jobs_public()) == 1


def test_closing_the_window_cancels(service, ui, http_server):
    service.clipboard_detected(http_server.add_file("f.zip", make_bytes(10)))
    capture_id = opened(ui)
    service.capture.window_closed(capture_id)
    assert service.capture.pending_ids() == []
    with pytest.raises(CaptureError):
        service.capture.capture_public(capture_id)


def test_folder_must_exist_and_the_user_can_retry(service, ui, http_server, tmp_path):
    service.clipboard_detected(http_server.add_file("g.zip", make_bytes(10)))
    capture_id = opened(ui)
    with pytest.raises(CaptureError):
        service.capture.decide(capture_id, "start", "g.zip", str(tmp_path / "missing"))
    assert service.capture.decide(capture_id, "start", "g.zip", str(tmp_path / "Downloads"))["job_id"]


def test_video_site_link_pops_up_and_queues_with_default_quality(service, ui, tmp_path):
    service.registry.sites = FakeSites()
    service.settings.update({"default_quality": "1080"})
    service.clipboard_detected("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    info = service.capture.capture_public(opened(ui))
    assert info["kind"] == "page" and info["media"] == "video" and info["quality_label"] == "1080p · MP4"
    job = service.queue.get(service.capture.decide(info["id"], "start", "", str(tmp_path / "Downloads"))["job_id"])
    assert job.provider == "ytdlp" and job.options.quality == "1080" and job.kind == MediaKind.VIDEO
    # Unknown hosts are checked against the engine's full site list (a few links only).
    service.clipboard_detected("https://videos.example.net/v/1")
    assert service.capture.capture_public(opened(ui, 2))["kind"] == "page"


def test_several_links_in_one_copy_open_one_window_and_add_all(service, ui, http_server):
    first = http_server.add_file("h1.zip", make_bytes(10))
    second = http_server.add_file("h2.zip", make_bytes(10))
    service.clipboard_detected(f"{first}\n{second}\nhttps://example.com/plain")
    info = service.capture.capture_public(opened(ui))
    assert info["kind"] == "links" and info["count"] == 2 and info["urls"] == [first, second]
    with pytest.raises(CaptureError):
        service.capture.decide(info["id"], "start", "", "")
    service.tracker.drain()
    service.capture.decide(info["id"], "add_all", "", "")
    assert sorted(item["url"] for item in service.preview.items_public()) == [first, second]
    assert service.tracker.drain().navigate == "home"
    assert ui.shown == [True]


def test_sent_link_is_shown_even_if_the_check_fails(service, ui, http_server):
    service.handle_message({"type": "add", "url": http_server.url("/file/nothing-here.zip")})
    info = service.capture.capture_public(opened(ui))
    assert info["kind"] == "file" and info["filename"] == "nothing-here.zip" and info["size"] is None
    assert info["origin"] == "link"


def test_sent_links_wait_for_the_window_system(service, http_server):
    service.handle_message({"type": "add", "url": http_server.add_file("i.zip", make_bytes(10))})
    assert wait_for(lambda: len(service.capture.pending_ids()) == 1, timeout=5)
    ui = FakeUI()
    service.capture.attach_ui(ui)
    assert ui.opened == service.capture.pending_ids()


def test_show_message_and_pending_limit(service, ui, monkeypatch):
    service.handle_message({"type": "show"})
    assert ui.shown == [True]
    monkeypatch.setattr(
        type(service.registry.direct),
        "inspect",
        lambda self, url, token, settings: InspectResult(provider="direct", filename="x.bin", size=1),
    )
    for i in range(MAX_PENDING + 3):
        service.capture.offer_url(f"https://e.com/{i}.bin", origin="link")
    assert wait_for(lambda: len(ui.opened) == MAX_PENDING, timeout=5)
    assert not wait_for(lambda: len(ui.opened) > MAX_PENDING, timeout=0.3)


def test_banner_still_offers_other_links_when_enabled(service, ui):
    service.settings.update({"clipboard_monitoring": True})
    service.tracker.drain()
    service.clipboard_detected("https://example.com/plain-page")
    assert service.tracker.drain().clipboard["urls"] == ["https://example.com/plain-page"]
    assert not ui.opened
