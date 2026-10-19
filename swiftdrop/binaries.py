"""Locating helper executables (FFmpeg, ffprobe, an optional JavaScript runtime).

Search order: explicit environment override → binaries bundled inside the app
(``Contents/Frameworks/bin``) or provisioned into ``vendor/bin/<arch>`` for
development → well-known install locations. Apps launched from Finder don't
inherit the shell ``PATH``, so Homebrew locations are probed explicitly.

On Windows the tools are ``.exe`` files: the installed app uses only its bundled
``bin`` folder (plus Node.js from Program Files); from source, ``vendor/bin/windows-x64``
and ``PATH`` are searched.
"""

from __future__ import annotations

import functools
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from swiftdrop.paths import is_frozen, resource_root

_SYSTEM_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin")


# Frozen builds trust only these locations for the JavaScript runtime.
_FROZEN_JS_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")

WINDOWS_ARCH_DIR = "windows-x64"
# Console tools started from the windowed Windows app must not flash a console window (0 elsewhere).
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _windows() -> bool:
    return sys.platform == "win32"


def machine_arch() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x86_64"


def bundled_bin_dirs() -> list[Path]:
    root = resource_root()
    if is_frozen():
        return [root / "bin"]
    arch = WINDOWS_ARCH_DIR if _windows() else machine_arch()
    return [root / "vendor" / "bin" / arch, root / "vendor" / "bin"]


def _is_exe(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _find(
    name: str,
    env_var: str,
    extra_dirs: tuple[str, ...] = (),
    system_dirs: tuple[str, ...] = _SYSTEM_DIRS,
    use_path: bool = True,
) -> Path | None:
    frozen = is_frozen()
    if _windows():
        name = f"{name}.exe"
    override = None if frozen else os.environ.get(env_var)
    if override:
        candidate = Path(override).expanduser()
        return candidate if _is_exe(candidate) else None
    for directory in bundled_bin_dirs():
        candidate = directory / name
        if _is_exe(candidate):
            return candidate
    for extra in (*(() if frozen else extra_dirs), *system_dirs):
        candidate = Path(extra).expanduser() / name
        if _is_exe(candidate):
            return candidate
    if not use_path:
        return None
    found = shutil.which(name)
    return Path(found) if found else None


def find_ffmpeg() -> Path | None:
    if _windows():
        return _find("ffmpeg", "SWIFTDROP_FFMPEG", system_dirs=(), use_path=not is_frozen())
    return _find("ffmpeg", "SWIFTDROP_FFMPEG")


def find_ffprobe() -> Path | None:
    if _windows():
        return _find("ffprobe", "SWIFTDROP_FFPROBE", system_dirs=(), use_path=not is_frozen())
    return _find("ffprobe", "SWIFTDROP_FFPROBE")


def is_bundled(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        resolved = path.resolve()
        return any(resolved.is_relative_to(d.resolve()) for d in bundled_bin_dirs() if d.exists())
    except OSError:
        return False


@functools.lru_cache(maxsize=8)
def tool_version(path: str, args: tuple[str, ...] = ("-version",)) -> str | None:
    try:
        out = subprocess.run(  # fixed executable path + constant arguments
            [path, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first = (out.stdout or out.stderr or "").strip().splitlines()
    return first[0][:200] if first else None


def ffmpeg_version(path: Path | None) -> str | None:
    if path is None:
        return None
    line = tool_version(str(path))
    if not line:
        return None
    match = re.search(r"version\s+(\S+)", line)
    return match.group(1) if match else line


@dataclass(frozen=True)
class JsRuntime:
    name: str
    path: Path
    version: str


_JS_MIN = {"deno": (2, 3, 0), "node": (22, 0, 0), "bun": (1, 2, 11)}


def _parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in match.groups()) if match else ()


@functools.lru_cache(maxsize=1)
def find_js_runtime() -> JsRuntime | None:
    """Best supported JavaScript runtime for yt-dlp's YouTube challenge solver."""
    home = Path.home()
    frozen = is_frozen()
    nodejs = str(Path(os.environ.get("PROGRAMFILES") or r"C:\Program Files") / "nodejs")
    for name, extra in (
        ("deno", (str(home / ".deno" / "bin"),)),
        ("node", (str(home / ".volta" / "bin"),)),
        ("bun", (str(home / ".bun" / "bin"),)),
    ):
        env_var = f"SWIFTDROP_{name.upper()}"
        if _windows():
            # Node.js from Program Files (the installed app too); home folders and PATH only from source.
            system_dirs = (nodejs,) if name == "node" else ()
            path = _find(name, env_var, extra, system_dirs=system_dirs, use_path=not frozen)
        elif frozen:
            path = _find(name, env_var, system_dirs=_FROZEN_JS_DIRS, use_path=False)
        else:
            path = _find(name, env_var, extra)
        if path is None:
            continue
        line = tool_version(str(path), ("--version",)) or ""
        version = _parse_version(line)
        if version and version >= _JS_MIN[name]:
            return JsRuntime(name=name, path=path, version=".".join(map(str, version)))
    return None
