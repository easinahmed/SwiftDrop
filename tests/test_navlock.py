from __future__ import annotations

import sys
from pathlib import Path

import pytest

from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.service import AppService
from swiftdrop.ui.bridge import Bridge
from swiftdrop.ui.navlock import install_navigation_lock, navigation_allowed

INDEX = Path("/Users/someone/Swift Drop/swiftdrop/ui/web/index.html").as_uri()
INDEX_ENCODED = INDEX  # as_uri percent-encodes the space
INDEX_RAW = INDEX.replace("%20", " ")


@pytest.mark.parametrize(
    ("url", "main_frame", "expected"),
    [
        (INDEX + "#/capture/1", True, True),
        (INDEX, True, True),
        (INDEX_RAW, True, True),
        (INDEX_ENCODED.replace("file:///", "FILE:///"), True, True),
        ("about:blank", True, True),
        ("http://127.0.0.1:8767/evil.html", True, False),
        ("file:///etc/passwd", True, False),
        ("file:///Users/someone/Swift%20Drop/swiftdrop/ui/web/other.html", True, False),
        (INDEX, False, False),
        ("about:blank", False, False),
    ],
)
def test_navigation_allowed(url, main_frame, expected):
    assert navigation_allowed(url, main_frame, INDEX) is expected


class FakeWindow:
    def __init__(self, url):
        self.url = url

    def get_current_url(self):
        return self.url


@pytest.fixture
def service(tmp_path):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    (tmp_path / "Downloads").mkdir()
    svc = AppService(paths, NullPlatform(), enable_sites=False)
    svc.settings.update({"download_dir": str(tmp_path / "Downloads")})
    svc.start()
    yield svc
    svc.shutdown()


@pytest.fixture(autouse=True)
def _index(monkeypatch):
    monkeypatch.setattr("swiftdrop.ui.bridge.bundled_index_url", lambda: INDEX)


def test_endpoint_refuses_foreign_page(service):
    functions = Bridge(service).functions(FakeWindow("http://evil/"))
    assert len(functions) == 33
    for fn in functions:
        nargs = fn.__wrapped__.__code__.co_argcount
        assert fn(*([None] * nargs)) == {"ok": False, "error": "Not allowed."}


def test_endpoint_refuses_when_url_unknown(service):
    (fn,) = [f for f in Bridge(service).functions(FakeWindow(None)) if f.__name__ == "get_settings"]
    assert fn() == {"ok": False, "error": "Not allowed."}


def test_endpoint_accepts_index(service):
    functions = {f.__name__: f for f in Bridge(service).functions(FakeWindow(INDEX_RAW + "#/x"))}
    assert functions["get_settings"]()["ok"] is True


def test_capture_window_route_is_the_bundled_page(service):
    """The confirm window loads index.html#/capture/<id>: the per-window check must accept it."""
    assert Bridge.window_allowed(FakeWindow(INDEX + "#/capture/0123456789abcdef")) is True
    assert Bridge.window_allowed(FakeWindow("file:///tmp/evil.html#/capture/0123456789abcdef")) is False
    functions = {f.__name__: f for f in Bridge(service).functions(FakeWindow("http://evil/#/capture/1"))}
    assert functions["decide_capture"]("0123456789abcdef", "start", "x", "/") == {"ok": False, "error": "Not allowed."}


def test_push_is_skipped_on_foreign_page(service):
    bridge = Bridge(service)
    assert bridge.window_allowed(FakeWindow("http://evil/")) is False
    assert bridge.window_allowed(FakeWindow(INDEX)) is True
    assert bridge.window_allowed(FakeWindow(None)) is False


@pytest.mark.skipif(sys.platform != "darwin", reason="Cocoa only")
def test_navigation_lock_installed():
    from webview.platforms.cocoa import BrowserView

    delegate = BrowserView.BrowserDelegate
    sel = delegate.instanceMethodSignatureForSelector_  # noqa: F841 - proves it is an ObjC class
    name = b"webView:decidePolicyForNavigationAction:decisionHandler:"
    before = delegate.pyobjc_instanceMethods.webView_decidePolicyForNavigationAction_decisionHandler_.callable
    install_navigation_lock(INDEX)
    install_navigation_lock(INDEX)  # idempotent
    assert delegate.instancesRespondToSelector_(name)
    after = delegate.pyobjc_instanceMethods.webView_decidePolicyForNavigationAction_decisionHandler_.callable
    assert after is not before
