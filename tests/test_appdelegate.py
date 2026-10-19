"""Dock reopen / hide-on-close hooks on pywebview's Cocoa delegates (macOS only)."""

from __future__ import annotations

import sys

import pytest

from swiftdrop.ui import appdelegate

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Cocoa only")


class FakeWindow:
    def __init__(self, native) -> None:
        self.native = native
        self.shown = 0

    def show(self) -> None:
        self.shown += 1


def test_hooks_install_once_and_route_to_the_main_window():
    from webview.platforms.cocoa import BrowserView

    hide = {"on": True}
    main = FakeWindow(native=object())
    appdelegate.install_app_hooks(main, lambda: hide["on"])
    appdelegate.install_app_hooks(main, lambda: hide["on"])  # idempotent
    app_delegate = BrowserView.AppDelegate
    assert app_delegate.instancesRespondToSelector_(b"applicationShouldHandleReopen:hasVisibleWindows:")
    method = app_delegate.pyobjc_instanceMethods.applicationShouldHandleReopen_hasVisibleWindows_
    assert method.signature == b"Z@:@Z"
    assert BrowserView.WindowDelegate.instancesRespondToSelector_(b"windowShouldClose:")

    assert appdelegate.hide_instead_of_close(main.native) is True
    assert appdelegate.hide_instead_of_close(object()) is False  # a confirm window closes normally
    hide["on"] = False
    assert appdelegate.hide_instead_of_close(main.native) is False

    delegate = app_delegate.alloc().init()
    assert delegate.applicationShouldHandleReopen_hasVisibleWindows_(None, False) is True
    assert main.shown == 1


def test_url_handler_receives_get_url_events():
    import Foundation

    links = []
    appdelegate.install_url_handler(links.append)
    appdelegate.install_url_handler(links.append)  # idempotent
    handler = appdelegate._state["url_handler"]
    event = Foundation.NSAppleEventDescriptor.appleEventWithEventClass_eventID_targetDescriptor_returnID_transactionID_(
        0x4755524C, 0x4755524C, None, -1, 0
    )
    event.setParamDescriptor_forKeyword_(
        Foundation.NSAppleEventDescriptor.descriptorWithString_("swiftdrop://add?url=https%3A%2F%2Fe.com%2Fa.zip"),
        0x2D2D2D2D,
    )
    handler.handleGetURLEvent_withReplyEvent_(event, None)
    assert links == ["swiftdrop://add?url=https%3A%2F%2Fe.com%2Fa.zip"]
    manager = Foundation.NSAppleEventManager.sharedAppleEventManager()
    assert manager is not None
