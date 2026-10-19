"""End-to-end self test: ``SwiftDrop --self-test`` (also works from the packaged .app).

Verifies, without touching user data or third-party websites, that the bundle
contains a working UI, download engines and helper binaries:

1. bundled resources (web UI, CA certificates, yt-dlp + EJS components)
2. FFmpeg / ffprobe run
3. real direct downloads from a local HTTP server, including a failing link
4. an HLS stream downloaded by yt-dlp and merged by FFmpeg
5. an RSS feed expanded into a playlist
6. on Windows: pythonnet and the WebView2 interop assemblies the window needs

Exit status 0 means every check passed. The windowed Windows build has no console,
so the summary is also written to the file named by ``SWIFTDROP_SELFTEST_REPORT``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from swiftdrop.appinfo import APP_NAME, APP_VERSION


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:  # skip the slow reverse-DNS lookup
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = str(self.server_address[0]), int(self.server_address[1])

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # header probes close connections early on purpose


def _serve(root: Path) -> tuple[_Server, str]:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, *args: Any) -> None:
            pass

        def guess_type(self, path: Any) -> str:
            if str(path).endswith(".m3u8"):
                return "application/vnd.apple.mpegurl"
            if str(path).endswith(".xml"):
                return "application/rss+xml"
            return super().guess_type(path)

    server = _Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class CheckFailed(Exception):
    pass


def require(condition: object, message: object) -> None:
    """Explicit check that survives ``python -O`` (asserts would be stripped)."""
    if not condition:
        raise CheckFailed(str(message))


def _wait(predicate: Callable[[], bool], timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _write_report(text: str) -> None:
    report = os.environ.get("SWIFTDROP_SELFTEST_REPORT")
    if not report:
        return
    try:
        Path(report).write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"Could not write the report to {report}: {exc}", flush=True)


def run_self_test() -> int:
    """Run every check; an unexpected crash still ends in a report and exit status 1.

    (A windowed Windows build would otherwise show a blocking traceback dialog.)
    """
    try:
        return _run_checks()
    except Exception:
        text = f"{APP_NAME} self-test crashed:\n{traceback.format_exc()}"
        print(text, flush=True)
        _write_report(text)
        return 1


def _run_checks() -> int:
    home = Path(tempfile.mkdtemp(prefix="swiftdrop-selftest-"))
    os.environ["SWIFTDROP_HOME"] = str(home)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn: Callable[[], str]) -> None:
        started = time.monotonic()
        try:
            detail = fn()
            results.append((name, True, f"{detail} ({time.monotonic() - started:.1f}s)"))
        except Exception as exc:
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    lines: list[str] = []

    def say(line: str) -> None:
        lines.append(line)
        print(line, flush=True)

    say(f"{APP_NAME} {APP_VERSION} self-test (frozen={getattr(sys, 'frozen', False)}, platform={sys.platform})")
    from swiftdrop import binaries
    from swiftdrop.logging_setup import configure_logging
    from swiftdrop.paths import default_paths, web_root

    paths = default_paths().ensure()
    configure_logging(paths.logs_dir, verbose=True)
    media = home / "www"
    media.mkdir()
    downloads = home / "Downloads"
    downloads.mkdir()

    def resources() -> str:
        index = web_root() / "index.html"
        require(index.exists(), f"missing {index}")
        assets = list((web_root() / "assets").glob("*.js"))
        require(assets, "web UI assets missing")
        import certifi
        import webview  # noqa: F401
        import yt_dlp
        import yt_dlp_ejs  # noqa: F401

        require(Path(certifi.where()).exists(), "CA bundle missing")
        return f"UI ok, yt-dlp {yt_dlp.version.__version__}, CA bundle ok"

    def ffmpeg() -> str:
        path = binaries.find_ffmpeg()
        require(path, "ffmpeg not found")
        version = binaries.ffmpeg_version(path)
        require(version, "ffmpeg did not run")
        probe = binaries.find_ffprobe()
        bundled = binaries.is_bundled(path)
        if getattr(sys, "frozen", False):
            require(bundled, f"ffmpeg is not the bundled copy: {path}")
        return f"ffmpeg {version} ({'bundled' if bundled else path}), ffprobe {'ok' if probe else 'missing'}"

    def windows_ui() -> str:
        import clr  # pythonnet: pywebview drives WinForms + WebView2 through it
        from webview.util import interop_dll_path

        clr.AddReference("System.Windows.Forms")
        for dll in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll"):
            path = interop_dll_path(dll)
            require(Path(path).is_file(), f"missing {dll}")
            clr.AddReference(path)
        return "pythonnet, WinForms and WebView2 interop assemblies load"

    check("bundled resources", resources)
    check("ffmpeg", ffmpeg)
    if sys.platform == "win32":
        check("Windows UI runtime", windows_ui)

    from swiftdrop.models import JobState
    from swiftdrop.platform import NullPlatform
    from swiftdrop.service import AppService

    payload = os.urandom(3_000_000)
    (media / "video.mp4").write_bytes(payload)
    (media / "photo.jpg").write_bytes(os.urandom(200_000))
    server, base = _serve(media)
    service = AppService(paths, NullPlatform())
    service.settings.update({"download_dir": str(downloads), "max_concurrent": 3})
    service.start()
    try:

        def state_of(job_id: str) -> str:
            job = service.queue.get(job_id)
            return job.state.value if job else "missing"

        def direct() -> str:
            text = f"{base}/video.mp4\n{base}/photo.jpg\n{base}/video.mp4\n{base}/missing.mp4"
            analysis = service.analyze_text(text)
            require(analysis["duplicates"] == 1, analysis)
            items = [{"id": i["id"], "entries": None} for i in analysis["added"]]
            service.settings.update({"auto_inspect": False})
            ids = service.start_downloads(items, None, None)["job_ids"]
            require(
                _wait(lambda: all(state_of(i) in ("completed", "failed") for i in ids), 60),
                "downloads did not finish in time",
            )
            states = sorted(state_of(i) for i in ids)
            require(states == ["completed", "completed", "failed"], states)
            got = hashlib.sha256((downloads / "video.mp4").read_bytes()).hexdigest()
            require(got == hashlib.sha256(payload).hexdigest(), "checksum mismatch")
            return "2 files downloaded and verified, 404 reported as failed"

        def hls() -> str:
            ffmpeg_path = binaries.find_ffmpeg()
            require(ffmpeg_path, "ffmpeg required")
            out = media / "hls"
            out.mkdir()
            subprocess.run(
                [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=15",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                 "-f", "hls", "-hls_time", "1", "-hls_list_size", "0", str(out / "index.m3u8")],
                check=True, capture_output=True, timeout=120,
                stdin=subprocess.DEVNULL, creationflags=binaries.NO_WINDOW,
            )  # fmt: skip
            analysis = service.analyze_text(f"{base}/hls/index.m3u8")
            item = analysis["added"][0]
            job_id = service.start_downloads([{"id": item["id"], "entries": None}], None, None)["job_ids"][0]
            require(
                _wait(lambda: state_of(job_id) in ("completed", "failed"), 120), "HLS download did not finish in time"
            )
            job = service.queue.get(job_id)
            if job is None:
                raise CheckFailed("job disappeared")
            require(job.state == JobState.COMPLETED, job.error)
            require(job.filepath and Path(job.filepath).is_file(), "downloaded file missing")
            require((job.file_size or 0) > 10_000, "downloaded file is too small")
            return f"{Path(job.filepath or '').name} ({job.file_size} bytes) via yt-dlp + FFmpeg"

        def playlist() -> str:
            items = "".join(
                f'<item><title>Episode {n}</title><enclosure url="{base}/photo.jpg?e={n}" type="image/jpeg"/></item>'
                for n in (1, 2)
            )
            (media / "feed.xml").write_text(
                f'<?xml version="1.0"?><rss version="2.0"><channel><title>Self-test feed</title>'
                f"<link>{base}</link><description>t</description>{items}</channel></rss>"
            )
            from swiftdrop.cancel import CancelToken

            link = service.registry.classify(f"{base}/feed.xml")
            info = service.registry.inspect(f"{base}/feed.xml", link, CancelToken(), service.settings.get())
            require(info.is_playlist and len(info.entries) == 2, info)
            return f"feed expanded into {len(info.entries)} entries"

        check("direct downloads", direct)
        check("HLS stream (yt-dlp + FFmpeg)", hls)
        check("playlist expansion", playlist)
    finally:
        service.shutdown()
        server.shutdown()

    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        say(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    passed = all(ok for _, ok, _ in results)
    say("All checks passed." if passed else "Some checks FAILED.")
    if not passed:
        say(f"Logs kept in {home}")
    _write_report("\n".join(lines) + "\n")
    if passed:
        shutil.rmtree(home, ignore_errors=True)
    return 0 if passed else 1
