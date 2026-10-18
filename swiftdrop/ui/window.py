"""Creates the native window (WKWebView via pywebview) and runs the UI loop."""

from __future__ import annotations

from typing import Any

from swiftdrop.appinfo import APP_NAME
from swiftdrop.logging_setup import get_logger
from swiftdrop.paths import web_root
from swiftdrop.service import AppService
from swiftdrop.ui import devtools
from swiftdrop.ui.bridge import Bridge
from swiftdrop.ui.navlock import install_navigation_lock

log = get_logger("window")


def _confirm_quit(active: int) -> bool:
    """Native confirmation shown while downloads are running (main thread)."""
    try:
        import AppKit

        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(f"Quit {APP_NAME}?")
        noun = "download is" if active == 1 else "downloads are"
        alert.setInformativeText_(
            f"{active} {noun} in progress. They'll be paused and you can resume them the next time you open {APP_NAME}."
        )
        alert.addButtonWithTitle_("Quit")
        alert.addButtonWithTitle_("Cancel")
        return alert.runModal() == AppKit.NSAlertFirstButtonReturn
    except Exception:
        log.exception("Could not show quit confirmation")
        return True


def run(service: AppService, *, debug: bool = False) -> None:
    import webview

    from swiftdrop.platform.macos import system_prefers_dark

    index = web_root() / "index.html"
    if not index.exists():
        raise SystemExit(f"UI files are missing ({index}). Build them with: make ui")

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = debug

    theme = service.settings.get().theme
    dark = theme == "dark" or (theme == "system" and system_prefers_dark())
    background = "#161618" if dark else "#f4f4f6"

    install_navigation_lock(index.as_uri())
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
        background_color=background,
        text_select=True,
        zoomable=False,
    )
    if window is None:
        raise RuntimeError("The window could not be created.")
    bridge.attach(window)
    devtools.install(window)

    def on_closing() -> Any:
        active = service.queue.stats()["active"]
        if active and not _confirm_quit(active):
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

    try:
        webview.start(on_started, private_mode=True, debug=debug)
    finally:
        bridge.stop()
