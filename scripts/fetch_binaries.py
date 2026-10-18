#!/usr/bin/env python3
"""Provision FFmpeg/ffprobe into ``vendor/bin/<arch>/`` for bundling.

The app never assumes a system-wide FFmpeg; the build copies a *portable*
(statically linked) build into the bundle. This script refuses binaries that:

* are not built for the requested architecture,
* link against anything outside /System and /usr/lib (i.e. Homebrew dylibs,
  which would not exist on another Mac),
* were configured with ``--enable-nonfree`` (not redistributable).

It also writes ``vendor/licenses/FFMPEG-NOTICE.md`` describing the licence and
where the corresponding source is available.

Usage::

    python scripts/fetch_binaries.py                       # copy from /usr/local/bin or /opt/homebrew/bin
    python scripts/fetch_binaries.py --from /path/to/dir   # copy from a directory with ffmpeg + ffprobe
    python scripts/fetch_binaries.py --zip-url URL --sha256 HEX [--probe-zip-url URL --probe-sha256 HEX]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ("ffmpeg", "ffprobe")
DEFAULT_SOURCES = ("/usr/local/bin", "/opt/homebrew/bin")


def run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(binary: Path, arch: str) -> dict[str, str]:
    archs = run("lipo", "-archs", str(binary)).split()
    if arch not in archs:
        raise SystemExit(f"{binary} is built for {archs}, not {arch}")
    deps = [line.strip().split(" (")[0] for line in run("otool", "-L", str(binary)).splitlines()[1:]]
    foreign = [d for d in deps if d and not d.startswith(("/System/", "/usr/lib/"))]
    if foreign:
        raise SystemExit(
            f"{binary} links against non-system libraries and would not run on other Macs:\n  "
            + "\n  ".join(foreign)
            + "\nUse a statically linked build (for example from https://ffmpeg.martin-riedl.de)."
        )
    banner = run(str(binary), "-hide_banner", "-buildconf") if binary.name == "ffmpeg" else ""
    version = run(str(binary), "-version").splitlines()[0]
    if "--enable-nonfree" in banner:
        raise SystemExit(f"{binary} was built with --enable-nonfree and may not be redistributed")
    return {"version": version, "buildconf": banner, "sha256": sha256(binary)}


def download_zip(url: str, expected: str, name: str, dest: Path) -> Path:
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected.lower():
        raise SystemExit(f"SHA-256 mismatch for {url}: expected {expected}, got {actual}")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = next((m for m in archive.namelist() if Path(m).name == name), None)
        if member is None:
            raise SystemExit(f"{name} not found in {url}")
        target = dest / name
        target.write_bytes(archive.read(member))
    target.chmod(0o755)
    return target


def write_notice(info: dict[str, dict[str, str]], source: str) -> None:
    licenses = ROOT / "vendor" / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    buildconf = info["ffmpeg"]["buildconf"]
    gpl = "--enable-gpl" in buildconf
    v3 = "--enable-version3" in buildconf
    licence = ("GPL v3" if v3 else "GPL v2 or later") if gpl else ("LGPL v3" if v3 else "LGPL v2.1 or later")
    lines = [
        "# FFmpeg in SwiftDrop",
        "",
        "SwiftDrop bundles unmodified FFmpeg command-line programs (`ffmpeg`, `ffprobe`) and runs them as",
        "separate processes to merge and convert media. They are not linked into SwiftDrop.",
        "",
        f"* Licence of the bundled build: **{licence}** (determined from its build configuration).",
        f"* Obtained from: {source}",
        "* FFmpeg source code: https://ffmpeg.org/download.html (the release matching the version below).",
        "* Licence texts: https://www.gnu.org/licenses/ — see also https://ffmpeg.org/legal.html",
        "",
        "To ship an LGPL-only build instead, provision one with `scripts/fetch_binaries.py --from <dir>`",
        "(any statically linked build without `--enable-gpl` / `--enable-nonfree`).",
        "",
    ]
    for tool, details in info.items():
        lines += [f"## {tool}", "", f"* Version: `{details['version']}`", f"* SHA-256: `{details['sha256']}`", ""]
    lines += ["## Build configuration", "", "```", buildconf.strip(), "```", ""]
    (licenses / "FFMPEG-NOTICE.md").write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arch", default="arm64" if platform.machine() == "arm64" else "x86_64")
    parser.add_argument("--from", dest="source_dir")
    parser.add_argument("--zip-url")
    parser.add_argument("--sha256")
    parser.add_argument("--probe-zip-url")
    parser.add_argument("--probe-sha256")
    args = parser.parse_args()

    dest = ROOT / "vendor" / "bin" / args.arch
    dest.mkdir(parents=True, exist_ok=True)
    if args.zip_url:
        if not args.sha256:
            raise SystemExit("--sha256 is required with --zip-url")
        download_zip(args.zip_url, args.sha256, "ffmpeg", dest)
        if args.probe_zip_url:
            download_zip(args.probe_zip_url, args.probe_sha256 or "", "ffprobe", dest)
        source = args.zip_url
    else:
        candidates = [args.source_dir] if args.source_dir else list(DEFAULT_SOURCES)
        directory = next((Path(c) for c in candidates if c and (Path(c) / "ffmpeg").exists()), None)
        if directory is None:
            raise SystemExit("No ffmpeg found. Pass --from DIR or --zip-url URL --sha256 HEX.")
        for tool in TOOLS:
            src = directory / tool
            if src.exists():
                shutil.copy2(src.resolve(), dest / tool)
                (dest / tool).chmod(0o755)
        source = f"local copy of {directory}"

    info = {}
    for tool in TOOLS:
        binary = dest / tool
        if not binary.exists():
            if tool == "ffmpeg":
                raise SystemExit("ffmpeg is required")
            print("ffprobe not provisioned (optional)")
            continue
        info[tool] = verify(binary, args.arch)
        print(f"OK  {binary.relative_to(ROOT)}  {info[tool]['version'][:70]}")
    write_notice(info, source)
    print(f"Wrote {Path('vendor/licenses/FFMPEG-NOTICE.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
