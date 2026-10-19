"""The keyboard shortcut on macOS: a Carbon hot key (``RegisterEventHotKey``) through ctypes.

Unlike an ``NSEvent`` global monitor, a Carbon hot key needs no Accessibility permission,
and the key press isn't passed on to the app in front. pywebview runs the
``NSApplication`` run loop, which delivers the ``kEventHotKeyPressed`` Carbon event to the
handler installed here, on the main thread. The handler only checks that the press is
ours and hands it to the callback on a worker thread.

Carbon calls are made on the main thread (:func:`swiftdrop.platform.macos.run_on_main`).
The hot key is registered exclusively: registration fails with ``eventHotKeyExistsErr``
while another app holds the same shortcut exclusively. Apps that register it without
that option can't be detected.

Key codes are physical key positions (``kVK_ANSI_*``), as on a US keyboard.
"""

from __future__ import annotations

import ctypes
import itertools
import sys
import threading
from collections.abc import Callable
from typing import Any

from swiftdrop.hotkey import Shortcut, ShortcutError, parse_shortcut
from swiftdrop.logging_setup import get_logger

log = get_logger("hotkey")

CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
_KEYBOARD_CLASS = 0x6B657962  # 'keyb' (kEventClassKeyboard)
_HOT_KEY_PRESSED = 5  # kEventHotKeyPressed
_DIRECT_OBJECT = 0x2D2D2D2D  # '----' (kEventParamDirectObject)
_TYPE_HOT_KEY_ID = 0x686B6964  # 'hkid' (typeEventHotKeyID)
_SIGNATURE = 0x53447270  # 'SDrp': marks SwiftDrop's hot keys
_EXCLUSIVE = 1  # kEventHotKeyExclusive
_NO_ERR = 0
_NOT_HANDLED = -9874  # eventNotHandledErr: let other handlers see the event

MODIFIER_MASKS = {"cmd": 1 << 8, "shift": 1 << 9, "alt": 1 << 11, "ctrl": 1 << 12}  # cmdKey, shiftKey, …
KEY_CODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07,
    "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10,
    "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "9": 0x19,
    "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F, "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25,
    "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E,
}  # fmt: skip


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_KEEP_ALIVE: list[Any] = []  # Carbon keeps calling installed handlers: never free them
_IDS = itertools.count(1)


def _load_carbon() -> Any | None:
    if sys.platform != "darwin":
        return None
    try:
        carbon = ctypes.CDLL(CARBON)
    except OSError:
        log.warning("Carbon is unavailable; the keyboard shortcut is off")
        return None
    void_p, uint32, int32 = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    carbon.GetApplicationEventTarget.argtypes = []
    carbon.GetApplicationEventTarget.restype = void_p
    carbon.InstallEventHandler.argtypes = [
        void_p,
        _HANDLER,
        ctypes.c_ulong,
        ctypes.POINTER(_EventTypeSpec),
        void_p,
        ctypes.POINTER(void_p),
    ]
    carbon.InstallEventHandler.restype = int32
    carbon.RegisterEventHotKey.argtypes = [uint32, uint32, _EventHotKeyID, void_p, uint32, ctypes.POINTER(void_p)]
    carbon.RegisterEventHotKey.restype = int32
    carbon.UnregisterEventHotKey.argtypes = [void_p]
    carbon.UnregisterEventHotKey.restype = int32
    carbon.GetEventParameter.argtypes = [
        void_p,
        uint32,
        uint32,
        ctypes.POINTER(uint32),
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        void_p,
    ]
    carbon.GetEventParameter.restype = int32
    return carbon


def _on_main(fn: Callable[[], Any], timeout: float = 3.0) -> Any:
    from swiftdrop.platform.macos import run_on_main

    return run_on_main(fn, timeout)


def _run(callback: Callable[[], None]) -> None:
    try:
        callback()
    except Exception:
        log.exception("Keyboard shortcut action failed")


class MacHotkey:
    """Implements :class:`swiftdrop.hotkey.GlobalHotkey` with one Carbon hot key."""

    def __init__(self) -> None:
        self._carbon = _load_carbon()
        self._lock = threading.Lock()
        self._proc = _HANDLER(self._on_event)
        _KEEP_ALIVE.append(self._proc)
        self._handler: ctypes.c_void_p | None = None
        self._ref: ctypes.c_void_p | None = None
        self._id = 0
        self._callback: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        return self._carbon is not None

    def start(self, shortcut: str, callback: Callable[[], None]) -> bool:
        try:
            parsed = parse_shortcut(shortcut, mac=True)
        except ShortcutError:
            return False
        if self._carbon is None:
            return False
        try:
            return bool(_on_main(lambda: self._register(parsed, callback)))
        except Exception:
            log.warning("Could not register the keyboard shortcut", exc_info=True)
            return False

    def stop(self) -> None:
        if self._carbon is None:
            return
        try:
            _on_main(self._unregister, timeout=1.0)
        except TimeoutError:  # the main thread is busy (quitting): the call is safe from here too
            self._unregister()
        except Exception:
            log.debug("Could not unregister the keyboard shortcut", exc_info=True)

    # -- main thread -------------------------------------------------------------
    def _register(self, shortcut: Shortcut, callback: Callable[[], None]) -> bool:
        carbon = self._carbon
        assert carbon is not None
        self._unregister()
        if not self._install_handler():
            return False
        modifiers = 0
        for name in shortcut.modifiers:
            modifiers |= MODIFIER_MASKS[name]
        hot_key_id = next(_IDS)
        ref = ctypes.c_void_p()
        status = carbon.RegisterEventHotKey(
            KEY_CODES[shortcut.key],
            modifiers,
            _EventHotKeyID(_SIGNATURE, hot_key_id),
            carbon.GetApplicationEventTarget(),
            _EXCLUSIVE,
            ctypes.byref(ref),
        )
        if status != _NO_ERR or not ref.value:
            log.info("The keyboard shortcut %s is taken (error %d)", shortcut, status)
            return False
        with self._lock:
            self._ref, self._id, self._callback = ref, hot_key_id, callback
        log.info("Keyboard shortcut %s registered", shortcut)
        return True

    def _unregister(self) -> None:
        with self._lock:
            ref, self._ref, self._id, self._callback = self._ref, None, 0, None
        if ref is not None and self._carbon is not None:
            status = self._carbon.UnregisterEventHotKey(ref)
            log.info("Keyboard shortcut unregistered (status %d)", status)

    def _install_handler(self) -> bool:
        if self._handler is not None:
            return True
        carbon = self._carbon
        assert carbon is not None
        spec = _EventTypeSpec(_KEYBOARD_CLASS, _HOT_KEY_PRESSED)
        handler = ctypes.c_void_p()
        status = carbon.InstallEventHandler(
            carbon.GetApplicationEventTarget(), self._proc, 1, ctypes.byref(spec), None, ctypes.byref(handler)
        )
        if status != _NO_ERR:
            log.warning("Could not listen for the keyboard shortcut (error %d)", status)
            return False
        self._handler = handler  # stays installed for the app's lifetime; it ignores other hot keys
        return True

    def _on_event(self, _call: Any, event: Any, _data: Any) -> int:
        """Carbon event handler (main thread, inside the run loop): never block here."""
        try:
            carbon = self._carbon
            if carbon is None:
                return _NOT_HANDLED
            hot_key = _EventHotKeyID()
            status = carbon.GetEventParameter(
                event,
                _DIRECT_OBJECT,
                _TYPE_HOT_KEY_ID,
                None,
                ctypes.sizeof(hot_key),
                None,
                ctypes.byref(hot_key),
            )
            with self._lock:
                ours = status == _NO_ERR and hot_key.signature == _SIGNATURE and hot_key.id == self._id
                callback = self._callback if ours else None
            if callback is None:
                return _NOT_HANDLED
            threading.Thread(target=_run, args=(callback,), name="hotkey-press", daemon=True).start()
            return _NO_ERR
        except Exception:
            log.exception("Keyboard shortcut handler failed")
            return _NOT_HANDLED
