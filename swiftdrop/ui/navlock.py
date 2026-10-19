"""Keeps the app window on the bundled UI.

pywebview re-injects the whole JS -> Python bridge into whatever page the window is
showing, and its ``request_sent`` event cannot veto a navigation. So the native
navigation delegate is wrapped here: main-frame navigations are only allowed to the
bundled ``index.html`` (any fragment) and ``about:blank``; sub-frame navigations are
refused; anything else is cancelled. ``target=_blank`` links are already routed to the
external browser by pywebview and never reach this check.

The lock is macOS-only. pywebview's WebView2 backend (Windows) has no hook that can veto
a navigation, so there the per-call check in ``bridge.py`` (which compares the window's
current URL with :func:`normalize_url`) is what keeps foreign pages away from the bridge.
"""

from __future__ import annotations

import sys
from typing import Any
from urllib.parse import unquote, urlsplit

from swiftdrop.logging_setup import get_logger

log = get_logger("navlock")

_SEL = "webView_decidePolicyForNavigationAction_decisionHandler_"
_POLICY_CANCEL = 0
_installed_for: str | None = None


def normalize_url(url: str) -> str:
    """Comparable form: no fragment, percent-decoded path, lowercase scheme and host.

    On Windows, file paths are case-insensitive and may use backslashes (``C:\\`` vs ``c:\\``),
    so ``file:`` paths are compared with forward slashes and casefolded.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.netloc or "").lower()
    path = unquote(parts.path)
    if sys.platform == "win32" and scheme == "file":
        path = path.replace("\\", "/").casefold()
    return f"{scheme}://{host}{path}" + (f"?{parts.query}" if parts.query else "")


def navigation_allowed(url: str, main_frame: bool, index_url: str) -> bool:
    if not main_frame:
        return False
    if url.strip().lower() == "about:blank":
        return True
    return normalize_url(url) == normalize_url(index_url)


def install_navigation_lock(index_url: str) -> None:
    """Wrap pywebview's Cocoa navigation delegate (idempotent; macOS only)."""
    global _installed_for
    import objc
    from webview.platforms.cocoa import BrowserView

    delegate = BrowserView.BrowserDelegate
    _installed_for = index_url
    if getattr(delegate, "_swiftdrop_navlock", False):
        return
    original = getattr(delegate.pyobjc_instanceMethods, _SEL).callable

    class BrowserDelegate(objc.Category(delegate)):  # type: ignore[misc]  # name must match the extended class
        def webView_decidePolicyForNavigationAction_decisionHandler_(
            self, webview: Any, action: Any, handler: Any
        ) -> None:
            try:
                target = action.request().URL()
                url = str(target.absoluteString()) if target is not None else ""
                frame = action.targetFrame()
                main_frame = frame is None or bool(frame.isMainFrame())
                allowed = navigation_allowed(url, main_frame, _installed_for or "")
            except Exception:
                log.exception("Navigation check failed; blocking")
                handler(_POLICY_CANCEL)
                return
            if not allowed:
                log.warning("Blocked navigation to %s", url.split("?", 1)[0][:200])
                handler(_POLICY_CANCEL)
                return
            original(self, webview, action, handler)

    delegate._swiftdrop_navlock = True

