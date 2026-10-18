"""QA automation hook (disabled unless ``SWIFTDROP_QA_DIR`` is set).

Lets developers and CI capture real WKWebView screenshots and drive the UI
without macOS screen-recording permission:

* ``<dir>/<name>.js``   → evaluated in the page; result written to ``<name>.out.json``
* ``<dir>/<name>.snap`` → page snapshot written to ``<name>.png``

The variable is only read from the process environment, so it carries no more
privilege than the user launching the app.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from swiftdrop.logging_setup import get_logger

log = get_logger("qa")

_NO_MOTION_JS = (
    "if (!document.getElementById('qa-no-motion')) {"
    " var s = document.createElement('style'); s.id = 'qa-no-motion';"
    " s.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}';"
    " document.head.appendChild(s); } 1"
)


def _find_webview(view: Any) -> Any:
    import WebKit

    if isinstance(view, WebKit.WKWebView):
        return view
    for sub in view.subviews() or []:
        found = _find_webview(sub)
        if found is not None:
            return found
    return None


def _snapshot(window: Any, target: Path) -> None:
    import AppKit
    from PyObjCTools import AppHelper

    done = threading.Event()

    def take() -> None:
        webview = _find_webview(window.native.contentView())
        if webview is None:
            done.set()
            return

        def handler(image: Any, error: Any) -> None:
            try:
                if image is not None:
                    tiff = image.TIFFRepresentation()
                    rep = AppKit.NSBitmapImageRep.imageRepWithData_(tiff)
                    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
                    png.writeToFile_atomically_(str(target), True)
                else:
                    log.warning("Snapshot failed: %s", error)
            finally:
                done.set()

        webview.takeSnapshotWithConfiguration_completionHandler_(None, handler)

    AppHelper.callAfter(take)
    done.wait(10)


def install(window: Any) -> None:
    qa_dir = os.environ.get("SWIFTDROP_QA_DIR")
    if not qa_dir:
        return
    root = Path(qa_dir)
    root.mkdir(parents=True, exist_ok=True)
    log.warning("QA automation hook enabled (%s)", root)

    def loop() -> None:
        window.events.loaded.wait(60)
        while True:
            for request in sorted(root.iterdir()):
                try:
                    if request.suffix == ".js":
                        script = request.read_text()
                        request.unlink()
                        try:
                            result = window.evaluate_js(script)
                            payload = {"ok": True, "result": result}
                        except Exception as exc:
                            payload = {"ok": False, "error": str(exc)}
                        request.with_suffix(".out.json").write_text(json.dumps(payload, default=str))
                    elif request.suffix == ".snap":
                        request.unlink()
                        # WebKit freezes transitions in occluded windows; disable motion so
                        # snapshots show the settled UI rather than a frame mid-transition.
                        window.evaluate_js(_NO_MOTION_JS)
                        time.sleep(0.15)
                        _snapshot(window, request.with_suffix(".png"))
                except FileNotFoundError:
                    continue
                except Exception:
                    log.exception("QA request %s failed", request.name)
            time.sleep(0.2)

    threading.Thread(target=loop, name="qa-hook", daemon=True).start()
