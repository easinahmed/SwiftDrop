"""The only surface the web UI can reach.

Security model (mirrors Electron's contextIsolation + preload allow-list):

* Functions are registered with ``window.expose()`` — an exact-name allow-list.
  No Python object is passed as ``js_api``, so pywebview's recursive attribute
  exposure and dotted-name lookups can't reach internal objects.
* Every argument is type- and size-checked here before it reaches the service.
* The UI never supplies filesystem paths for reveal/open: it passes a job or
  history id and the path comes from SwiftDrop's own records. A destination
  folder is only accepted if it is the saved default, the Downloads folder, or a
  folder the user picked in a native dialog during this session.
* Nothing is ever executed through a shell.

Engine → UI updates flow through a single publisher thread that coalesces
changes (see :mod:`swiftdrop.events`).
"""

from __future__ import annotations

import functools
import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from swiftdrop.logging_setup import get_logger
from swiftdrop.paths import default_download_dir, web_root
from swiftdrop.service import AppService, ServiceError
from swiftdrop.settings import SettingsError
from swiftdrop.ui.navlock import normalize_url

log = get_logger("bridge")

MAX_TEXT_CHARS = 2_000_000
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IDS = 20_000
PUSH_INTERVAL = 0.2
_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class BridgeError(ValueError):
    pass


# -- validation helpers -------------------------------------------------------
def _str(value: Any, name: str, max_len: int, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise BridgeError(f"{name} must be text.")
    if len(value) > max_len:
        raise BridgeError(f"{name} is too long.")
    if not allow_empty and not value.strip():
        raise BridgeError(f"{name} is empty.")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise BridgeError(f"{name} must be true or false.")
    return value


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise BridgeError(f"{name} must be a number between {lo} and {hi}.")
    return value


def _ids(value: Any, name: str = "ids") -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_IDS:
        raise BridgeError(f"{name} must be a list.")
    for item in value:
        if not isinstance(item, str) or not _ID_RE.match(item):
            raise BridgeError(f"{name} contains an invalid id.")
    return value


def _id(value: Any, name: str = "id") -> str:
    return _ids([value], name)[0]


def _choice(value: Any, name: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise BridgeError(f"Unknown {name}.")
    return value


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BridgeError(f"{name} must be an object.")
    return value


def _resolve(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        return path


def bundled_index_url() -> str:
    return (web_root() / "index.html").as_uri()


def endpoint(allowed: Callable[[], bool]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a bridge function: refuse foreign pages, uniform envelope, no tracebacks leak."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any) -> dict[str, Any]:
            if not allowed():
                log.warning("Refused bridge call to %s from a non-bundled page", fn.__name__)
                return {"ok": False, "error": "Not allowed."}
            try:
                return {"ok": True, "data": fn(*args)}
            except (BridgeError, ServiceError, SettingsError) as exc:
                return {"ok": False, "error": str(exc), **getattr(exc, "extra", {})}
            except TypeError as exc:
                log.warning("Bad bridge call to %s: %s", fn.__name__, exc)
                return {"ok": False, "error": "Invalid request."}
            except Exception:
                log.exception("Bridge call %s failed", fn.__name__)
                return {"ok": False, "error": "Something went wrong. Details were written to the log."}

        return wrapper

    return decorate


class Bridge:
    def __init__(self, service: AppService) -> None:
        self._service = service
        self._window: Any = None
        self._publisher: threading.Thread | None = None
        self._stop = threading.Event()
        self._approved_dirs: set[str] = {
            _resolve(service.settings.get().download_dir),
            _resolve(str(default_download_dir())),
        }

    def approve_dir(self, path: str) -> None:
        self._approved_dirs.add(_resolve(path))

    def check_dir(self, path: str) -> str:
        """Only folders the user chose natively (or the defaults) may be written to."""
        if _resolve(path) not in self._approved_dirs:
            raise BridgeError("Choose the destination folder with the folder picker.")
        return path

    # -- window plumbing --------------------------------------------------
    def attach(self, window: Any) -> None:
        self._window = window
        window.expose(*self.functions(window))

    @staticmethod
    def window_allowed(window: Any) -> bool:
        """True only while ``window`` is showing the bundled index.html."""
        try:
            current = window.get_current_url()
        except Exception:
            return False
        if not current:
            return False
        return normalize_url(current) == normalize_url(bundled_index_url())

    def start_publisher(self) -> None:
        self._publisher = threading.Thread(target=self._publish_loop, name="ui-publisher", daemon=True)
        self._publisher.start()

    def stop(self) -> None:
        self._stop.set()

    def _publish_loop(self) -> None:
        window = self._window
        if not window.events.loaded.wait(30):
            log.warning("UI did not finish loading within 30s; pushing updates anyway")
        last = 0.0
        while not self._stop.is_set():
            if not self._service.tracker.wait(1.0):
                continue
            delay = PUSH_INTERVAL - (time.monotonic() - last)
            if delay > 0 and self._stop.wait(delay):
                return
            payload = self.build_push()
            if payload is None:
                continue
            if not self.window_allowed(window):
                continue  # never push app state into a foreign page
            last = time.monotonic()
            script = f"window.__SD_PUSH__ && window.__SD_PUSH__({json.dumps(payload, ensure_ascii=True)})"
            try:
                window.run_js(script)
            except Exception:
                if self._stop.is_set():
                    return
                log.debug("Push failed", exc_info=True)

    def build_push(self) -> dict[str, Any] | None:
        changes = self._service.tracker.drain()
        if changes.empty():
            return None
        service = self._service
        payload: dict[str, Any] = {"stats": service.queue.stats()}
        if changes.jobs:
            payload["jobs"] = service.queue.jobs_public(changes.jobs)
        if changes.removed_jobs:
            payload["removed_jobs"] = sorted(changes.removed_jobs)
        if changes.collections or changes.jobs or changes.removed_jobs:
            payload["collections"] = service.queue.collections_public()
        if changes.preview:
            payload["preview"] = service.preview.items_public(changes.preview)
        if changes.removed_preview:
            payload["removed_preview"] = sorted(changes.removed_preview)
        if changes.settings:
            payload["settings"] = service.settings.get().to_dict()
        if changes.history:
            payload["history_changed"] = True
        if changes.clipboard is not None:
            payload["clipboard"] = changes.clipboard
        if changes.notices:
            payload["notices"] = changes.notices
        return payload

    def _dialog(self, kind: str, **kwargs: Any) -> Any:
        if self._window is None:
            raise ServiceError("No window available.")
        import webview

        dialog_type = {
            "folder": webview.FileDialog.FOLDER,
            "open": webview.FileDialog.OPEN,
            "save": webview.FileDialog.SAVE,
        }[kind]
        return self._window.create_file_dialog(dialog_type, **kwargs)

    # -- exposed functions --------------------------------------------------
    def functions(self, window: Any) -> list[Callable[..., Any]]:
        service = self._service
        bridge = self
        endpoint_ = endpoint(lambda: bridge.window_allowed(window))

        @endpoint_
        def get_bootstrap() -> dict[str, Any]:
            return service.bootstrap()

        @endpoint_
        def get_state() -> dict[str, Any]:
            state = service.bootstrap()
            state.pop("app", None)
            return state

        @endpoint_
        def analyze_text(text: Any, append: Any) -> dict[str, Any]:
            return service.analyze_text(_str(text, "Text", MAX_TEXT_CHARS), _bool(append, "append"))

        @endpoint_
        def inspect_preview(ids: Any) -> int:
            return service.preview.inspect(_ids(ids))

        @endpoint_
        def remove_preview(ids: Any) -> int:
            return service.preview.remove(_ids(ids))

        @endpoint_
        def clear_preview() -> int:
            return service.preview.clear()

        @endpoint_
        def get_playlist_entries(item_id: Any) -> list[dict[str, Any]]:
            return service.preview.entries(_id(item_id))

        @endpoint_
        def start_downloads(request: Any) -> dict[str, Any]:
            request = _dict(request, "Request")
            raw_items = request.get("items")
            if not isinstance(raw_items, list) or not raw_items or len(raw_items) > MAX_IDS:
                raise BridgeError("Select at least one link.")
            items = []
            for raw in raw_items:
                raw = _dict(raw, "Item")
                entries = raw.get("entries")
                if entries is not None:
                    if not isinstance(entries, list) or len(entries) > 50_000:
                        raise BridgeError("Invalid playlist selection.")
                    entries = [_str(e, "Entry", 512) for e in entries]
                items.append({"id": _id(raw.get("id")), "entries": entries})
            options = request.get("options")
            if options is not None:
                options = _dict(options, "Options")
            destination = request.get("destination")
            if destination is not None:
                destination = bridge.check_dir(_str(destination, "Destination", 4096))
            return service.start_downloads(items, options, destination)

        @endpoint_
        def job_action(action: Any, ids: Any) -> int:
            return service.job_action(
                _choice(action, "action", ("pause", "resume", "cancel", "retry", "remove")), _ids(ids)
            )

        @endpoint_
        def queue_action(action: Any) -> int:
            return service.queue_action(
                _choice(
                    action,
                    "action",
                    (
                        "pause_all",
                        "resume_all",
                        "retry_failed",
                        "clear_completed",
                        "clear_finished",
                        "clear_failed",
                        "clear_cancelled",
                    ),
                )
            )

        @endpoint_
        def reveal_job(job_id: Any) -> bool:
            return service.reveal(service.job_file(_id(job_id)))

        def _open_confirmed(path: Path, confirmed: bool) -> bool:
            try:
                return service.open_file(path, confirmed=confirmed)
            except ServiceError as exc:
                if str(exc) != "confirm_open":
                    raise
                error = ServiceError("confirm_open")
                error.extra = {"name": path.name}  # type: ignore[attr-defined]
                raise error from None

        @endpoint_
        def open_job(job_id: Any, confirmed: Any = False) -> bool:
            path = service.job_file(_id(job_id))
            return _open_confirmed(path, _bool(confirmed, "confirmed"))

        @endpoint_
        def reveal_history(entry_id: Any) -> bool:
            return service.reveal(service.history_file(_int(entry_id, "id", 1, 2**62)))

        @endpoint_
        def open_history(entry_id: Any, confirmed: Any = False) -> bool:
            path = service.history_file(_int(entry_id, "id", 1, 2**62))
            return _open_confirmed(path, _bool(confirmed, "confirmed"))

        @endpoint_
        def search_history(params: Any) -> dict[str, Any]:
            params = _dict(params, "Search")
            return service.search_history(
                _str(params.get("query", ""), "Search", 500),
                _str(params.get("kind", "all"), "Kind", 20),
                _str(params.get("status", "all"), "Status", 20),
                _int(params.get("limit", 200), "limit", 1, 1000),
                _int(params.get("offset", 0), "offset", 0, 10_000_000),
            )

        @endpoint_
        def clear_history() -> int:
            return service.clear_history()

        @endpoint_
        def delete_history(ids: Any) -> int:
            if not isinstance(ids, list) or len(ids) > MAX_IDS:
                raise BridgeError("ids must be a list.")
            return service.delete_history([_int(i, "id", 1, 2**62) for i in ids])

        @endpoint_
        def get_settings() -> dict[str, Any]:
            return service.settings.get().to_dict()

        @endpoint_
        def update_settings(patch: Any) -> dict[str, Any]:
            patch = _dict(patch, "Settings")
            if "download_dir" in patch:
                bridge.check_dir(_str(patch["download_dir"], "Destination", 4096))
            return service.update_settings(patch)

        @endpoint_
        def choose_folder(initial: Any) -> str | None:
            start = _str(initial or "", "Folder", 4096)
            result = bridge._dialog("folder", directory=start if start and Path(start).is_dir() else "")
            if not result:
                return None
            chosen = str(result[0] if isinstance(result, list | tuple) else result)
            bridge.approve_dir(chosen)
            return chosen

        @endpoint_
        def import_url_file() -> dict[str, Any] | None:
            result = bridge._dialog(
                "open", allow_multiple=False, file_types=("Text files (*.txt;*.csv;*.md;*.list)", "All files (*.*)")
            )
            if not result:
                return None
            path = Path(result[0] if isinstance(result, list | tuple) else result)
            if path.stat().st_size > MAX_IMPORT_BYTES:
                raise BridgeError("That file is larger than 5 MB. Split it into smaller lists.")
            text = path.read_text(encoding="utf-8", errors="replace")
            return {"name": path.name, "text": text}

        @endpoint_
        def read_clipboard() -> str:
            return service.platform.read_clipboard() or ""

        @endpoint_
        def copy_text(text: Any) -> bool:
            return service.platform.write_clipboard(_str(text, "Text", 100_000))

        @endpoint_
        def export_data(kind: Any) -> str | None:
            filename, content = service.export_text(_choice(kind, "export", ("results", "failed")))
            settings = service.settings.get()
            result = bridge._dialog("save", directory=settings.download_dir, save_filename=filename)
            if not result:
                return None
            target = Path(result[0] if isinstance(result, list | tuple) else result)
            target.write_text(content, encoding="utf-8")
            return str(target)

        @endpoint_
        def storage_info() -> dict[str, Any]:
            return service.storage_info()

        @endpoint_
        def clean_temp(include_paused: Any) -> int:
            return service.clean_temp(_bool(include_paused, "include_paused"))

        @endpoint_
        def get_diagnostics() -> dict[str, Any]:
            return service.diagnostics()

        @endpoint_
        def open_logs_folder() -> bool:
            return service.platform.open_path(service.paths.logs_dir)

        @endpoint_
        def open_partial_folder() -> bool:
            service.paths.partial_dir.mkdir(parents=True, exist_ok=True)
            return service.platform.open_path(service.paths.partial_dir)

        @endpoint_
        def open_download_folder() -> bool:
            return service.platform.open_path(Path(service.settings.get().download_dir))

        return [
            get_bootstrap,
            get_state,
            analyze_text,
            inspect_preview,
            remove_preview,
            clear_preview,
            get_playlist_entries,
            start_downloads,
            job_action,
            queue_action,
            reveal_job,
            open_job,
            reveal_history,
            open_history,
            search_history,
            clear_history,
            delete_history,
            get_settings,
            update_settings,
            choose_folder,
            import_url_file,
            read_clipboard,
            copy_text,
            export_data,
            storage_info,
            clean_temp,
            get_diagnostics,
            open_logs_folder,
            open_partial_folder,
            open_download_folder,
        ]
