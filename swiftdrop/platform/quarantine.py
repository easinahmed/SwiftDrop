"""Quarantine and where-from attributes, plus the "can this run code?" check.

On Windows the equivalent is the Mark of the Web: a ``Zone.Identifier`` alternate
data stream (Internet zone) that SmartScreen and Office check before running a file.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import plistlib
import sys
import time
import uuid
from pathlib import Path

from swiftdrop.appinfo import APP_NAME
from swiftdrop.logging_setup import get_logger

log = get_logger("quarantine")

QUARANTINE_ATTR = "com.apple.quarantine"
WHERE_FROMS_ATTR = "com.apple.metadata:kMDItemWhereFroms"

EXECUTABLE_EXTS = frozenset(
    [
        "app",
        "pkg",
        "mpkg",
        "dmg",
        "command",
        "terminal",
        "tool",
        "sh",
        "zsh",
        "bash",
        "scpt",
        "applescript",
        "workflow",
        "jar",
        "fileloc",
        "webloc",
        "inetloc",
        "action",
        "prefpane",
    ]
)

# Windows file types that run code or change the system when opened (in addition to the list above).
WINDOWS_EXECUTABLE_EXTS = frozenset(
    [
        "exe",
        "msi",
        "msp",
        "bat",
        "cmd",
        "com",
        "scr",
        "pif",
        "cpl",
        "ps1",
        "psm1",
        "vbs",
        "vbe",
        "js",
        "jse",
        "wsf",
        "wsh",
        "hta",
        "lnk",
        "url",
        "reg",
        "jar",
        "msix",
        "msixbundle",
        "appx",
        "appxbundle",
        "appref-ms",
    ]
)

_libc: ctypes.CDLL | None = None


def _load_libc() -> ctypes.CDLL:
    global _libc
    if _libc is None:
        lib = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
        lib.setxattr.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        lib.setxattr.restype = ctypes.c_int
        _libc = lib
    return _libc


def _setxattr(path: Path, name: str, value: bytes) -> None:
    libc = _load_libc()
    if libc.setxattr(os.fsencode(path), name.encode(), value, len(value), 0, 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def zone_identifier(origin_url: str | None, referrer: str | None = None) -> str:
    """Contents of the ``Zone.Identifier`` stream: Internet zone (3) plus where the file came from."""
    lines = ["[ZoneTransfer]", "ZoneId=3"]
    for key, url in (("ReferrerUrl", referrer), ("HostUrl", origin_url)):
        # Control characters (CR/LF above all) could inject extra keys such as ZoneId=0.
        clean = "".join(ch for ch in url or "" if ch.isprintable())
        if clean:
            lines.append(f"{key}={clean}")
    return "\r\n".join(lines) + "\r\n"


def _apply_mark_of_the_web(path: Path, origin_url: str | None, referrer: str | None) -> bool:
    try:
        if not path.is_file():
            raise FileNotFoundError(path)
        with open(f"{path}:Zone.Identifier", "wb") as stream:
            stream.write(zone_identifier(origin_url, referrer).encode("utf-8"))
        return True
    except OSError as exc:  # e.g. FAT32/exFAT volumes have no alternate data streams
        log.warning("Could not mark %s as downloaded from the internet: %s", path.name, exc)
        return False


def apply_quarantine(path: Path, origin_url: str | None, referrer: str | None = None, agent: str = APP_NAME) -> bool:
    """Mark a downloaded file so Gatekeeper checks it and Finder shows where it came from.

    On Windows this writes the Mark of the Web instead (``agent`` is not recorded there).
    """
    if sys.platform == "win32":
        return _apply_mark_of_the_web(path, origin_url, referrer)
    try:
        value = f"0081;{int(time.time()):08x};{agent};{uuid.uuid4()}"
        _setxattr(path, QUARANTINE_ATTR, value.encode())
        froms = [u for u in (origin_url, referrer) if u]
        if froms:
            _setxattr(path, WHERE_FROMS_ATTR, plistlib.dumps(froms, fmt=plistlib.FMT_BINARY))
        return True
    except (OSError, AttributeError, ValueError) as exc:
        log.warning("Could not set quarantine attributes on %s: %s", path.name, exc)
        return False


def needs_open_confirmation(path: Path) -> bool:
    """True when opening the file could run code (app bundles, scripts, installers, +x files)."""
    ext = path.suffix.lower().lstrip(".")
    if ext in EXECUTABLE_EXTS or (sys.platform == "win32" and ext in WINDOWS_EXECUTABLE_EXTS):
        return True
    try:
        if path.is_dir():
            return False
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False
