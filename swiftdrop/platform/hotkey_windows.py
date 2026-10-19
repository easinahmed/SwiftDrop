"""The keyboard shortcut on Windows: ``RegisterHotKey`` on a dedicated message-loop thread.

The hot key is registered without a window, so Windows posts ``WM_HOTKEY`` to the queue of
the thread that registered it. That thread runs a ``GetMessageW`` loop and hands each press
to the callback on a worker thread. To stop, ``WM_QUIT`` is posted to it
(``PostThreadMessageW``) and it calls ``UnregisterHotKey`` itself, as Windows requires.

``RegisterHotKey`` fails (``ERROR_HOTKEY_ALREADY_REGISTERED``) while another app uses the
same shortcut. Every Win32 call sits behind ``sys.platform == "win32"``.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from typing import Any

from swiftdrop.hotkey import Shortcut, ShortcutError, parse_shortcut
from swiftdrop.logging_setup import get_logger

log = get_logger("hotkey")

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000  # holding the keys down doesn't repeat the press
WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
WM_USER = 0x0400
PM_NOREMOVE = 0x0000
HOTKEY_ID = 0x5344  # this thread's only hot key (application ids are 0x0000–0xBFFF)
MODIFIER_FLAGS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT}
START_TIMEOUT = 5.0


def hotkey_args(shortcut: Shortcut) -> tuple[int, int]:
    """(modifiers, virtual-key code) for ``RegisterHotKey``; VK_A…VK_Z and VK_0…VK_9 equal 'A'…'Z', '0'…'9'."""
    modifiers = MOD_NOREPEAT
    for name in shortcut.modifiers:
        modifiers |= MODIFIER_FLAGS[name]
    return modifiers, ord(shortcut.key.upper())


def _win32() -> tuple[Any, Any] | None:
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    msg_p = ctypes.POINTER(wintypes.MSG)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [msg_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int  # -1 on error
    user32.PeekMessageW.argtypes = [msg_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    return user32, kernel32


def _last_error() -> int:
    if sys.platform != "win32":
        return 0
    return ctypes.get_last_error()


def _run(callback: Callable[[], None]) -> None:
    try:
        callback()
    except Exception:
        log.exception("Keyboard shortcut action failed")


class WindowsHotkey:
    """Implements :class:`swiftdrop.hotkey.GlobalHotkey` with one ``RegisterHotKey`` hot key."""

    def __init__(self) -> None:
        self._api = _win32()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def start(self, shortcut: str, callback: Callable[[], None]) -> bool:
        try:
            parsed = parse_shortcut(shortcut, mac=False)
        except ShortcutError:
            return False
        if self._api is None:
            return False
        modifiers, key = hotkey_args(parsed)
        with self._lock:
            self._stop_locked()
            ready = threading.Event()
            result: dict[str, int] = {"ok": 0, "thread_id": 0}
            thread = threading.Thread(
                target=self._loop, args=(modifiers, key, callback, ready, result), name="hotkey", daemon=True
            )
            thread.start()
            if not ready.wait(START_TIMEOUT):
                log.warning("The keyboard shortcut thread didn't start")
                return False
            if not result["ok"]:
                thread.join(1.0)
                return False
            self._thread, self._thread_id = thread, result["thread_id"]
        log.info("Keyboard shortcut %s registered", parsed)
        return True

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        thread, thread_id = self._thread, self._thread_id
        self._thread, self._thread_id = None, 0
        if thread is None or self._api is None:
            return
        if not self._api[0].PostThreadMessageW(thread_id, WM_QUIT, 0, 0):
            log.warning("Could not stop the keyboard shortcut thread (error %d)", _last_error())
        thread.join(2.0)

    def _loop(
        self,
        modifiers: int,
        key: int,
        callback: Callable[[], None],
        ready: threading.Event,
        result: dict[str, int],
    ) -> None:
        from ctypes import wintypes

        assert self._api is not None
        user32, kernel32 = self._api
        msg = wintypes.MSG()
        try:
            result["thread_id"] = int(kernel32.GetCurrentThreadId())
            # Create this thread's message queue first, so a WM_QUIT posted by stop() can't be lost.
            user32.PeekMessageW(ctypes.byref(msg), None, WM_USER, WM_USER, PM_NOREMOVE)
            if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers, key):
                log.info("The keyboard shortcut is taken (error %d)", _last_error())
                return
            result["ok"] = 1
        finally:
            ready.set()
        try:
            while True:
                got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got == 0 or got == -1:  # WM_QUIT, or an error
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    threading.Thread(target=_run, args=(callback,), name="hotkey-press", daemon=True).start()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            log.info("Keyboard shortcut unregistered")
