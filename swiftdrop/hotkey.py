"""The keyboard shortcut that opens copied links in SwiftDrop.

The user copies a link as usual and presses the shortcut (⌃⌥D on a Mac, Ctrl+Alt+D on
Windows); SwiftDrop then shows the download links on the clipboard in a confirm window.

A shortcut is stored as text such as ``"ctrl+alt+d"``: one or more modifiers (``ctrl``,
``alt``, ``shift``, and ``cmd`` on a Mac only) and one letter or digit. Shift alone isn't
enough, as it would take over typing a capital letter or symbol everywhere.

Registering it with the OS sits behind :class:`GlobalHotkey`
(:mod:`swiftdrop.platform.hotkey_macos`, :mod:`swiftdrop.platform.hotkey_windows`), so the
service can be tested with a fake.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

MODIFIERS = ("ctrl", "alt", "shift", "cmd")  # canonical order, also the order macOS shows them in
KEYS = tuple("abcdefghijklmnopqrstuvwxyz0123456789")
DEFAULT_HOTKEY = "ctrl+alt+d"
MAX_SHORTCUT_CHARS = 40

_MAC_SYMBOLS = {"ctrl": "⌃", "alt": "⌥", "shift": "⇧", "cmd": "⌘"}
_WINDOWS_NAMES = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}


class ShortcutError(ValueError):
    """A shortcut that can't be used (the message is shown to the user)."""


class GlobalHotkey(Protocol):
    """One system-wide keyboard shortcut.

    ``start`` replaces any shortcut registered earlier and returns False when the OS refuses it
    (usually because another app uses it). ``callback`` runs on a worker thread.
    """

    def start(self, shortcut: str, callback: Callable[[], None]) -> bool: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class Shortcut:
    modifiers: tuple[str, ...]  # in MODIFIERS order
    key: str  # "a"–"z" or "0"–"9"

    def __str__(self) -> str:
        return "+".join((*self.modifiers, self.key))


def is_mac() -> bool:
    return sys.platform != "win32"


def parse_shortcut(text: Any, *, mac: bool | None = None) -> Shortcut:
    """Validate a stored or submitted shortcut; raises :class:`ShortcutError`."""
    mac = is_mac() if mac is None else mac
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_SHORTCUT_CHARS:
        raise ShortcutError("Choose a keyboard shortcut.")
    parts = [part.strip().lower() for part in text.split("+")]
    *modifiers, key = parts
    if key not in KEYS:
        raise ShortcutError("The shortcut's key must be a letter or a digit.")
    allowed = MODIFIERS if mac else MODIFIERS[:3]
    if not modifiers or len(set(modifiers)) != len(modifiers) or any(m not in allowed for m in modifiers):
        names = "Control, Option, Shift or Command" if mac else "Ctrl, Alt or Shift"
        raise ShortcutError(f"The shortcut needs one or more of {names} and a letter or digit.")
    if set(modifiers) == {"shift"}:
        names = "Control, Option or Command" if mac else "Ctrl or Alt"
        raise ShortcutError(f"Add {names}: Shift alone would stop you typing capitals.")
    return Shortcut(tuple(m for m in MODIFIERS if m in modifiers), key)


def format_shortcut(shortcut: str | Shortcut, *, mac: bool | None = None) -> str:
    """``⌃⌥D`` on a Mac, ``Ctrl+Alt+D`` on Windows."""
    mac = is_mac() if mac is None else mac
    parsed = shortcut if isinstance(shortcut, Shortcut) else parse_shortcut(shortcut, mac=mac)
    if mac:
        return "".join(_MAC_SYMBOLS[m] for m in parsed.modifiers) + parsed.key.upper()
    return "+".join([*(_WINDOWS_NAMES[m] for m in parsed.modifiers), parsed.key.upper()])


def native_hotkey() -> GlobalHotkey | None:
    """The OS implementation for this platform (None where there is none)."""
    if sys.platform == "win32":
        from swiftdrop.platform.hotkey_windows import WindowsHotkey

        return WindowsHotkey()
    if sys.platform == "darwin":
        from swiftdrop.platform.hotkey_macos import MacHotkey

        return MacHotkey()
    return None
