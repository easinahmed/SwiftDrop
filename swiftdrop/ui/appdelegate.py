"""Keeps SwiftDrop running in the Dock for the copy pop-up, and receives swiftdrop:// links (macOS only).

pywebview's Cocoa backend has no hook for these, so its delegate classes are extended
with ``objc.Category`` (the same technique as :mod:`swiftdrop.ui.navlock`):

* ``AppDelegate.applicationShouldHandleReopen:hasVisibleWindows:`` — a click on the Dock
  icon shows the main window again (pywebview doesn't implement it).
* ``WindowDelegate.windowShouldClose:`` — while ``should_hide()`` is true, the red close
  button (and ⌘W) on the *main* window hides it instead of closing it, which would quit.
  ⌘Q and the Quit menu go through ``applicationShouldTerminate:`` instead, so they still
  quit, after the usual confirmation when downloads are running.

``swiftdrop://add?url=…`` links arrive as a ``kAEGetURL`` Apple Event (the bundle declares
the scheme in ``CFBundleURLTypes``), also right after launch when the link started the app.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from swiftdrop.logging_setup import get_logger

log = get_logger("appdelegate")

_CLOSE_SEL = "windowShouldClose_"
_INTERNET_EVENT_CLASS = 0x4755524C  # 'GURL' (kInternetEventClass)
_GET_URL_EVENT = 0x4755524C  # 'GURL' (kAEGetURL)
_DIRECT_OBJECT = 0x2D2D2D2D  # '----' (keyDirectObject)


# The pywebview Window shown again from the Dock, and whether closing it should only hide it.
_state: dict[str, Any] = {"main_window": None, "should_hide": None, "on_url": None, "url_handler": None}


def hide_instead_of_close(ns_window: Any) -> bool:
    """True if this native window is the main window and closing it should only hide it."""
    main = _state["main_window"]
    should_hide: Callable[[], bool] | None = _state["should_hide"]
    native = getattr(main, "native", None)
    return native is not None and should_hide is not None and ns_window == native and bool(should_hide())


def show_main_window() -> None:
    window = _state["main_window"]
    if window is not None:
        window.show()


def install_app_hooks(main_window: Any, should_hide: Callable[[], bool]) -> None:
    """Install the categories once (idempotent) and point them at ``main_window``."""
    import objc
    from webview.platforms.cocoa import BrowserView

    _state["main_window"] = main_window
    _state["should_hide"] = should_hide

    app_delegate = BrowserView.AppDelegate
    if not getattr(app_delegate, "_swiftdrop_reopen", False):

        class AppDelegate(objc.Category(app_delegate)):  # type: ignore[misc]  # name must match the extended class
            @objc.typedSelector(b"Z@:@Z")
            def applicationShouldHandleReopen_hasVisibleWindows_(self, app: Any, has_visible: bool) -> bool:
                try:
                    show_main_window()
                except Exception:
                    log.exception("Could not show the main window")
                return True

        app_delegate._swiftdrop_reopen = True

    window_delegate = BrowserView.WindowDelegate
    if not getattr(window_delegate, "_swiftdrop_hide", False):
        original = getattr(window_delegate.pyobjc_instanceMethods, _CLOSE_SEL).callable

        class WindowDelegate(objc.Category(window_delegate)):  # type: ignore[misc]  # name must match the extended class
            def windowShouldClose_(self, ns_window: Any) -> bool:
                try:
                    if hide_instead_of_close(ns_window):
                        ns_window.orderOut_(None)
                        return False
                except Exception:
                    log.exception("Hide-on-close check failed; closing normally")
                return bool(original(self, ns_window))

        window_delegate._swiftdrop_hide = True


def install_url_handler(on_url: Callable[[str], None]) -> None:
    """Route ``kAEGetURL`` Apple Events (swiftdrop:// links) to ``on_url``. Call before the run loop starts."""
    import Foundation
    import objc

    _state["on_url"] = on_url
    if _state["url_handler"] is not None:
        return

    class SwiftDropURLHandler(Foundation.NSObject):
        @objc.typedSelector(b"v@:@@")
        def handleGetURLEvent_withReplyEvent_(self, event: Any, reply: Any) -> None:
            try:
                descriptor = event.paramDescriptorForKeyword_(_DIRECT_OBJECT)
                link = str(descriptor.stringValue()) if descriptor is not None else ""
                callback = _state["on_url"]
                if link and callback is not None:
                    callback(link)
            except Exception:
                log.exception("Could not handle a swiftdrop:// link")

    handler = SwiftDropURLHandler.alloc().init()
    _state["url_handler"] = handler  # the event manager doesn't retain it
    Foundation.NSAppleEventManager.sharedAppleEventManager().setEventHandler_andSelector_forEventClass_andEventID_(
        handler, b"handleGetURLEvent:withReplyEvent:", _INTERNET_EVENT_CLASS, _GET_URL_EVENT
    )
