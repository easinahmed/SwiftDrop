"""Locating helper executables (FFmpeg, ffprobe, an optional JavaScript runtime).

Search order: explicit environment override → binaries bundled inside the app
(``Contents/Frameworks/bin``) or provisioned into ``vendor/bin/<arch>`` for
development → well-known install locations. Apps launched from Finder don't
inherit the shell ``PATH``, so Homebrew locations are probed explicitly.
"""

from __future__ import annotations

import functools
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from swiftdrop.paths import is_frozen, resource_root

_SYSTEM_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin")


def machine_arch() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in ("arm64", "aarch64") else "x86_64"


def bundled_bin_dirs() -> list[Path]:
    root = resource_root()
    if is_frozen():
        return [root / "bin"]
    return [root / "vendor" / "bin" / machine_arch(), root / "vendor" / "bin"]


def _is_exe(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _find(name: str, env_var: str, extra_dirs: tuple[str, ...] = ()) -> Path | None:
    override = os.environ.get(env_var)
    if override:
        candidate = Path(override).expanduser()
        return candidate if _is_exe(candidate) else None
    for directory in bundled_bin_dirs():
        candidate = directory / name
        if _is_exe(candidate):
            return candidate
    for extra in (*extra_dirs, *_SYSTEM_DIRS):
        candidate = Path(extra).expanduser() / name
        if _is_exe(candidate):
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def find_ffmpeg() -> Path | None:
    return _find("ffmpeg", "SWIFTDROP_FFMPEG")


def find_ffprobe() -> Path | None:
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
            [path, *args], capture_output=True, text=True, timeout=10, check=False
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
    for name, extra in (
        ("deno", (str(home / ".deno" / "bin"),)),
        ("node", (str(home / ".volta" / "bin"),)),
        ("bun", (str(home / ".bun" / "bin"),)),
    ):
        path = _find(name, f"SWIFTDROP_{name.upper()}", extra)
        if path is None:
            continue
        line = tool_version(str(path), ("--version",)) or ""
        version = _parse_version(line)
        if version and version >= _JS_MIN[name]:
            return JsRuntime(name=name, path=path, version=".".join(map(str, version)))
    return None
