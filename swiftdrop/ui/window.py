"""Creates the native window (WKWebView on macOS, WebView2 on Windows, via pywebview) and runs the UI loop."""

from __future__ import annotations

import sys
import threading
from typing import Any

from swiftdrop.appinfo import APP_NAME
from swiftdrop.handoff import parse_scheme_link
from swiftdrop.logging_setup import get_logger
from swiftdrop.paths import web_root
from swiftdrop.service import AppService
from swiftdrop.ui import devtools
from swiftdrop.ui.appdelegate import install_app_hooks, install_url_handler
from swiftdrop.ui.bridge import Bridge
from swiftdrop.ui.capture_window import CaptureWindows
from swiftdrop.ui.navlock import install_navigation_lock

log = get_logger("window")


def _confirm_quit(active: int) -> bool:
    """Native confirmation shown while downloads are running (main thread)."""
    noun = "download is" if active == 1 else "downloads are"
    detail = (
        f"{active} {noun} in progress. They'll be paused and you can resume them the next time you open {APP_NAME}."
    )
    if sys.platform == "win32":
        from swiftdrop.platform.windows import confirm_quit

        return confirm_quit(f"Quit {APP_NAME}?", detail)
    try:
        import AppKit

        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(f"Quit {APP_NAME}?")
        alert.setInformativeText_(detail)
        alert.addButtonWithTitle_("Quit")
        alert.addButtonWithTitle_("Cancel")
        return alert.runModal() == AppKit.NSAlertFirstButtonReturn
    except Exception:
        log.exception("Could not show quit confirmation")
        return True


def run(service: AppService, *, debug: bool = False, background: bool = False) -> None:
    import webview

    if sys.platform == "win32":
        from swiftdrop.platform.windows import system_prefers_dark
    else:
        from swiftdrop.platform.macos import system_prefers_dark

    index = web_root() / "index.html"
    if not index.exists():
        raise SystemExit(f"UI files are missing ({index}). Build them with: make ui")

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = debug

    theme = service.settings.get().theme
    dark = theme == "dark" or (theme == "system" and system_prefers_dark())
    background_color = "#161618" if dark else "#f4f4f6"

    if sys.platform == "darwin":
        install_navigation_lock(index.as_uri())  # Windows relies on the bridge's per-call URL check
    bridge = Bridge(service)
    # Load from file:// rather than a path: pywebview would otherwise start a local HTTP
    # server for the UI (an extra listening socket, and HTTPServer's reverse-DNS lookup
    # can stall startup for 30 s+ on some networks).
    window = webview.create_window(
        APP_NAME,
        url=index.as_uri(),
        width=1220,
        height=800,
        min_size=(940, 620),
        background_color=background_color,
        text_select=True,
        zoomable=False,
        hidden=background,  # started in the background: only confirm windows appear
    )
    if window is None:
        raise RuntimeError("The window could not be created.")
    bridge.attach(window)
    devtools.install(window)
    quitting = threading.Event()

    def keep_running() -> bool:
        """While the copy pop-up is on, closing the window only hides it."""
        return bool(service.settings.get().clipboard_popup)

    def open_link(link: str) -> None:
        url = parse_scheme_link(link)
        if url is None:
            log.warning("Ignored a swiftdrop:// link that doesn't carry a web address")
            return
        service.capture.offer_url(url, origin="link")

    if sys.platform == "darwin":
        # The red close button hides the window and a Dock click shows it again; ⌘Q still quits.
        install_app_hooks(window, keep_running)
        install_url_handler(open_link)

    def quit_app() -> None:
        if sys.platform == "darwin":
            import AppKit
            from PyObjCTools import AppHelper

            AppHelper.callAfter(AppKit.NSApp.terminate_, None)  # same path as ⌘Q
            return
        quitting.set()
        window.destroy()

    bridge.set_quit_handler(quit_app)
    hidden_notice = threading.Event()

    def on_closing() -> Any:
        if sys.platform == "win32" and not quitting.is_set() and keep_running():
            # No Dock on Windows: hide, and opening SwiftDrop again shows the window.
            threading.Thread(target=window.hide, daemon=True).start()
            if not hidden_notice.is_set():
                hidden_notice.set()
                service.platform.notify(
                    f"{APP_NAME} is still running",
                    "It pops up when you copy a download link. Open it again to show the window.",
                )
            return False
        active = service.queue.stats()["active"]
        if active and not _confirm_quit(active):
            quitting.clear()
            return False
        # ⌘Q terminates the process from inside the Cocoa run loop, so webview.start()
        # may never return: shut down here, while we still control the main thread.
        bridge.stop()
        service.shutdown()
        return None

    window.events.closing += on_closing

    def on_started() -> None:
        service.platform.set_appearance(theme)
        bridge.start_publisher()
        window.events.shown.wait(15)  # the window system is up: confirm windows can be created
        service.capture.attach_ui(CaptureWindows(bridge, service, background_color), show_main=window.show)

    try:
        webview.start(on_started, private_mode=True, debug=debug)
    finally:
        bridge.stop()
