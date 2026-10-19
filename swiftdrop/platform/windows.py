"""Windows integration with the standard library only (ctypes, winreg, os.startfile).

* Explorer reveal (``explorer /select``) / open with the default app (``os.startfile``)
* Clipboard: Win32 ``CF_UNICODETEXT``; content marked by password managers with
  ``ExcludeClipboardContentFromMonitorProcessing`` is ignored, never logged or stored
* Notifications are written to the log; "Open at login" is not available yet
* Short on-screen messages: a small topmost ``STATIC`` window that never takes focus

Every Win32 call sits behind ``sys.platform == "win32"`` so the module imports (and
type-checks) on macOS too.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from swiftdrop.logging_setup import get_logger

log = get_logger("windows")

MAX_CLIPBOARD_CHARS = 200_000
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
_EXCLUDE_FORMAT = "ExcludeClipboardContentFromMonitorProcessing"


def _win32() -> tuple[Any, Any] | None:
    """(user32, kernel32) with pointer-sized argument/return types, or None off Windows."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _open_clipboard(user32: Any, owner: Any = None) -> bool:
    # Another app may hold the clipboard for a moment; retry briefly.
    for _ in range(10):
        if user32.OpenClipboard(owner):
            return True
        time.sleep(0.02)
    return False


class WindowsPlatform:
    def __init__(self) -> None:
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()
        self._api = _win32()

    # -- Explorer ---------------------------------------------------------
    def reveal(self, path: Path) -> bool:
        if sys.platform != "win32":
            return False
        try:
            if path.exists():
                # Separate "/select," and path arguments: list2cmdline quotes the path when needed.
                subprocess.Popen(["explorer", "/select,", str(path)])
                return True
            if path.parent.exists():
                return self.open_path(path.parent)
        except OSError:
            log.warning("Could not show the file in Explorer", exc_info=True)
        return False

    def open_path(self, path: Path) -> bool:
        if sys.platform != "win32":
            return False
        if not path.exists():
            return False
        try:
            os.startfile(str(path))  # noqa: S606 - opens a downloaded file with its default app
            return True
        except OSError:
            log.warning("Could not open %s", path.name, exc_info=True)
            return False

    # -- Clipboard --------------------------------------------------------
    def read_clipboard(self) -> str | None:
        if self._api is None:
            return None
        user32, kernel32 = self._api
        try:
            if not _open_clipboard(user32):
                return None
            try:
                excluded = user32.RegisterClipboardFormatW(_EXCLUDE_FORMAT)
                if excluded and user32.IsClipboardFormatAvailable(excluded):
                    return None  # a password manager asked clipboard watchers to skip this
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return None
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    return None
                try:
                    text = ctypes.wstring_at(pointer)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        except Exception:
            log.debug("Clipboard read failed", exc_info=True)
            return None
        return text[:MAX_CLIPBOARD_CHARS] if text else None

    def write_clipboard(self, text: str) -> bool:
        if self._api is None:
            return False
        user32, kernel32 = self._api
        data = (text + "\0").encode("utf-16-le")
        # SetClipboardData fails after EmptyClipboard when the clipboard was opened without an
        # owner window, so a hidden helper window owns it for the duration of the write.
        owner = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
        try:
            if not owner or not _open_clipboard(user32, owner):
                return False
            try:
                user32.EmptyClipboard()
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not handle:
                    return False
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    kernel32.GlobalFree(handle)
                    return False
                ctypes.memmove(pointer, data, len(data))
                kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    kernel32.GlobalFree(handle)  # still ours: the clipboard only owns it on success
                    return False
                return True
            finally:
                user32.CloseClipboard()
        except Exception:
            log.debug("Clipboard write failed", exc_info=True)
            return False
        finally:
            if owner:
                user32.DestroyWindow(owner)

    def _sequence_number(self) -> int:
        return int(self._api[0].GetClipboardSequenceNumber()) if self._api is not None else 0

    def _app_in_front(self) -> bool:
        """True while one of SwiftDrop's own windows is in front (copies made in the app)."""
        if self._api is None:
            return False
        from ctypes import wintypes

        user32 = self._api[0]
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        return int(pid.value) == os.getpid()

    def start_clipboard_monitor(self, callback: Callable[[str], None]) -> None:
        if self._api is None or (self._monitor_thread and self._monitor_thread.is_alive()):
            return
        self._monitor_stop.clear()

        def loop() -> None:
            last = self._sequence_number()
            while not self._monitor_stop.wait(1.0):
                try:
                    number = self._sequence_number()
                    if number == last:
                        continue
                    last = number
                    if self._app_in_front():
                        continue  # copied inside SwiftDrop (Copy link, Ctrl+C): never offer it back
                    text = self.read_clipboard()
                except Exception:
                    log.debug("Clipboard poll failed", exc_info=True)
                    continue
                if text:
                    try:
                        callback(text)
                    except Exception:
                        log.exception("Clipboard callback failed")

        self._monitor_thread = threading.Thread(target=loop, name="clipboard-monitor", daemon=True)
        self._monitor_thread.start()
        log.info("Clipboard monitoring started")

    def stop_clipboard_monitor(self) -> None:
        if self._monitor_thread is None:
            return
        self._monitor_stop.set()
        self._monitor_thread = None
        log.info("Clipboard monitoring stopped")

    # -- Notifications ----------------------------------------------------
    def notify(self, title: str, body: str) -> None:
        log.info("Notification: %s — %s", title, body)

    def can_notify(self) -> bool:
        return False

    def flash_message(self, text: str) -> None:
        if sys.platform == "win32":
            threading.Thread(target=_flash, args=(text,), name="flash-message", daemon=True).start()

    # -- Login item -------------------------------------------------------
    def login_item_supported(self) -> bool:
        return False

    def set_login_item(self, enabled: bool) -> None:
        raise RuntimeError("Open at login isn't available on Windows yet.")

    # -- Appearance -------------------------------------------------------
    def set_appearance(self, theme: str) -> None:
        pass  # the web UI follows the theme setting itself


def _flash(text: str, seconds: float = 1.8) -> None:
    """Show ``text`` in a small borderless window at the top of the screen, then remove it.

    The window belongs to this thread, which pumps its messages (so it paints) until it is
    destroyed. ``WS_EX_NOACTIVATE`` keeps the focus in the app the user is working in.
    """
    if sys.platform != "win32":
        return
    from ctypes import wintypes

    ws_popup, ws_border = 0x80000000, 0x00800000
    ss_center, ss_centerimage = 0x0001, 0x0200
    ws_ex_topmost, ws_ex_toolwindow, ws_ex_noactivate = 0x00000008, 0x00000080, 0x08000000
    sw_shownoactivate, wm_setfont, pm_remove, default_gui_font = 4, 0x0030, 0x0001, 17
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = wintypes.LPARAM
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = wintypes.LPARAM
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        gdi32.GetStockObject.argtypes = [ctypes.c_int]
        gdi32.GetStockObject.restype = wintypes.HGDIOBJ
        width, height = 320, 44
        x = (user32.GetSystemMetrics(0) - width) // 2  # SM_CXSCREEN
        hwnd = user32.CreateWindowExW(
            ws_ex_topmost | ws_ex_toolwindow | ws_ex_noactivate,
            "STATIC",
            text,
            ws_popup | ws_border | ss_center | ss_centerimage,
            x,
            72,
            width,
            height,
            None,
            None,
            None,
            None,
        )
        if not hwnd:
            return
        try:
            font = gdi32.GetStockObject(default_gui_font)
            if font:
                user32.SendMessageW(hwnd, wm_setfont, font, 1)
            user32.ShowWindow(hwnd, sw_shownoactivate)
            user32.UpdateWindow(hwnd)
            msg = wintypes.MSG()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, pm_remove):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.03)
        finally:
            user32.DestroyWindow(hwnd)
    except Exception:
        log.debug("Could not show a message", exc_info=True)


def system_prefers_dark() -> bool:
    """True when Windows apps use the dark theme (Settings → Personalization → Colors)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _ = winreg.QueryValueEx(handle, "AppsUseLightTheme")
        return int(value) == 0
    except (OSError, ValueError, TypeError):
        return False


def confirm_quit(title: str, message: str) -> bool:
    """Native Yes/No question; True (quit) when the dialog can't be shown."""
    if sys.platform != "win32":
        return True
    mb_yesno, mb_iconwarning, mb_setforeground, idyes = 0x4, 0x30, 0x10000, 6
    try:
        answer = ctypes.windll.user32.MessageBoxW(None, message, title, mb_yesno | mb_iconwarning | mb_setforeground)
    except Exception:
        log.exception("Could not show quit confirmation")
        return True
    return int(answer) == idyes


def activate_window(title: str) -> bool:
    """Bring the already running app's window (a WinForms window titled ``title``) to the front."""
    if sys.platform != "win32":
        return False
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    def visit(hwnd: Any, _lparam: Any) -> bool:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buffer, 256)
        if buffer.value != title:
            return True
        user32.GetClassNameW(hwnd, buffer, 256)
        if buffer.value.startswith("WindowsForms"):  # not, say, an Explorer window of the install folder
            found.append(hwnd)
            return False
        return True

    try:
        user32.EnumWindows(enum_proc(visit), 0)
        if not found:
            return False
        sw_restore = 9
        if user32.IsIconic(found[0]):
            user32.ShowWindow(found[0], sw_restore)
        return bool(user32.SetForegroundWindow(found[0]))
    except Exception:
        log.debug("Could not activate the running window", exc_info=True)
        return False
