"""The confirm window for a copied or sent link (pywebview, macOS and Windows).

Each waiting link gets its own small window (520×380) that loads the same bundled
``index.html`` at ``#/capture/<id>``. It gets the same bridge functions as the main
window, each guarded by the same per-window check that the window still shows the
bundled page (the fragment is ignored by that check and by the navigation lock).

The window floats above other apps' windows and takes focus; several stack with a
small offset. Closing it counts as Cancel (see ``CaptureManager.window_closed``).
"""

from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING, Any

from swiftdrop.logging_setup import get_logger

if TYPE_CHECKING:
    from swiftdrop.service import AppService
    from swiftdrop.ui.bridge import Bridge

log = get_logger("capture-window")

WIDTH = 520
HEIGHT = 380
STACK_OFFSET = 26
TITLE = "New download"


class CaptureWindows:
    """Implements ``swiftdrop.capture.ConfirmUI`` with pywebview windows."""

    def __init__(self, bridge: Bridge, service: AppService, background: str) -> None:
        self._bridge = bridge
        self._service = service
        self._background = background
        self._windows: dict[str, Any] = {}
        self._lock = threading.Lock()

    def open(self, capture_id: str) -> None:
        if threading.current_thread() is threading.main_thread():
            # pywebview only creates windows immediately when called off the main thread.
            threading.Thread(target=self.open, args=(capture_id,), daemon=True).start()
            return
        import webview

        from swiftdrop.ui.bridge import bundled_index_url

        with self._lock:
            stacked = len(self._windows)
        x, y = self._position(stacked)
        window = webview.create_window(
            TITLE,
            url=f"{bundled_index_url()}#/capture/{capture_id}",
            width=WIDTH,
            height=HEIGHT,
            x=x,
            y=y,
            resizable=False,
            min_size=(WIDTH, HEIGHT),
            background_color=self._background,
            focus=True,
            on_top=sys.platform != "darwin",  # macOS: floating level set in _present()
            text_select=True,
            zoomable=False,
        )
        if window is None:
            raise RuntimeError("The download window could not be created.")
        # The window is created asynchronously on the main thread, so this runs before the page
        # has loaded and pywebview injects these functions with its API. Never expose again
        # after load: re-creating the API drops the callbacks of calls already in flight.
        window.expose(*self._bridge.functions(window))

        def on_shown() -> None:
            self._present(window)

        def on_closed() -> None:
            with self._lock:
                self._windows.pop(capture_id, None)
            self._service.capture.window_closed(capture_id)

        window.events.shown += on_shown
        window.events.closed += on_closed
        with self._lock:
            self._windows[capture_id] = window

    def close(self, capture_id: str) -> None:
        with self._lock:
            window = self._windows.pop(capture_id, None)
        if window is not None:
            try:
                window.destroy()
            except Exception:
                log.warning("Could not close a download window", exc_info=True)

    @staticmethod
    def _position(stacked: int) -> tuple[int | None, int | None]:
        """Centred (pywebview's default); later windows step down and right."""
        if stacked == 0:
            return None, None
        try:
            import webview

            screen = webview.screens[0]
            offset = STACK_OFFSET * (stacked % 8)
            return (screen.width - WIDTH) // 2 + offset, (screen.height - HEIGHT) // 2 + offset
        except Exception:
            return None, None

    @staticmethod
    def _present(window: Any) -> None:
        if sys.platform == "win32":
            from swiftdrop.platform.windows import activate_window

            activate_window(TITLE)  # Windows may only flash the taskbar button; on_top keeps it visible
            return
        if sys.platform != "darwin":
            return
        try:
            import AppKit
            from PyObjCTools import AppHelper
        except ImportError:
            return

        def present() -> None:
            native = getattr(window, "native", None)
            if native is None:
                return
            # Floating (above other apps' windows) but below the folder chooser's modal panel.
            native.setLevel_(AppKit.NSFloatingWindowLevel)
            native.makeKeyAndOrderFront_(None)
            AppKit.NSApp.activateIgnoringOtherApps_(True)

        AppHelper.callAfter(present)
