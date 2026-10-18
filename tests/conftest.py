"""Shared fixtures: an isolated app home and a local HTTP test server.

No test depends on a live third-party website.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


def make_bytes(size: int, seed: int = 7) -> bytes:
    block = hashlib.sha256(str(seed).encode()).digest() * 2048  # 64 KiB pattern
    reps = size // len(block) + 1
    return (block * reps)[:size]


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind() does a reverse-DNS lookup (getfqdn) that can take
        # tens of seconds on some networks; the test server never needs it.
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port

    def handle_error(self, request, client_address) -> None:
        pass  # dropped connections are deliberate in several tests


class TestServer:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.static_dirs: dict[str, Path] = {}
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.lock = threading.Lock()
        self.active = 0
        self.peak_active = 0
        self.static_rate = 0  # bytes/sec applied to /static/ files (simulates slow streams)
        handler = _make_handler(self)
        self.httpd = _QuietServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, path: str) -> str:
        return self.base + path

    def add_file(self, name: str, data: bytes) -> str:
        self.files[name] = data
        return self.url(f"/file/{name}")

    def hit(self, key: str) -> int:
        with self.lock:
            self.counters[key] += 1
            return self.counters[key]


def _make_handler(server: TestServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # silence
            pass

        def _send_status(self, code: int, extra: dict[str, str] | None = None, body: bytes = b"") -> None:
            self.send_response(code)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self) -> None:
            self.do_GET()

        def _connection_number(self, key: str) -> int:
            # One handler instance serves one TCP connection (keep-alive included), so this numbers
            # the connections per key in the order they first ask for it. `slowconn` calls it only for
            # data requests (not the 1-byte `Range: bytes=0-0` probe), so it throttles real transfers.
            numbers: dict[str, int] = self.__dict__.setdefault("_conn_numbers", {})
            if key not in numbers:
                numbers[key] = server.hit("conn:" + key)
            return numbers[key]

        def do_GET(self) -> None:
            with server.lock:
                server.active += 1
                server.peak_active = max(server.peak_active, server.active)
                server.requests.append((self.path, dict(self.headers)))
            try:
                self._route()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with server.lock:
                    server.active -= 1

        def _route(self) -> None:
            parts = urlsplit(self.path)
            query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
            path = parts.path
            if path.startswith("/status/"):
                code = int(path.rsplit("/", 1)[-1])
                self._send_status(code, {"Content-Type": "text/plain"}, b"status")
                return
            if path == "/redirect":
                self._send_status(302, {"Location": query["to"]})
                return
            if path == "/page.html":
                body = b"<html><head><title>Just a page</title></head><body>No media here.</body></html>"
                self._send_status(200, {"Content-Type": "text/html; charset=utf-8"}, body)
                return
            if path.startswith("/static/"):
                _, _, rest = path.partition("/static/")
                name, _, rel = rest.partition("/")
                root = server.static_dirs.get(name)
                target = (root / rel).resolve() if root else None
                if not root or not target or not str(target).startswith(str(root.resolve())) or not target.is_file():
                    self._send_status(404)
                    return
                data = target.read_bytes()
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if target.suffix == ".m3u8":
                    ctype = "application/vnd.apple.mpegurl"
                elif target.suffix == ".xml":
                    ctype = "application/rss+xml"
                if server.static_rate and "rate" not in query:
                    query["rate"] = str(server.static_rate)
                self._serve_bytes(data, ctype, query, key=path)
                return
            if path.startswith("/file/"):
                name = path[len("/file/") :]
                data = server.files.get(name)
                if data is None:
                    self._send_status(404, {"Content-Type": "text/plain"}, b"missing")
                    return
                ctype = query.get("type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
                self._serve_bytes(data, ctype, query, key=self.path)
                return
            self._send_status(404)

        def _serve_bytes(self, data: bytes, ctype: str, query: dict[str, str], key: str) -> None:
            """Serve ``data`` honouring Range/If-Range; query params simulate misbehaving servers.

            flaky=N[&flaky_skip=K&flaky_status=CODE&retry_after=S], fail_once=CODE, norange=1,
            drop_after=B[&drop_times=N], fail_after_bytes=N[&fail_code=C] (cut once, then answer C once),
            rate=B (bytes/s), slowconn=K&slowrate=B (first K data connections throttled),
            range_after=N (only the first N ranged requests get a 206), etag_after=N (ETag changes after N requests).
            """
            flaky = int(query.get("flaky", "0"))
            if flaky:
                count = server.hit("flaky:" + key)
                skip = int(query.get("flaky_skip", "0"))  # let the first requests (the probe) through
                if skip < count <= skip + flaky:
                    extra = {"Content-Type": "text/plain"}
                    if "retry_after" in query:
                        extra["Retry-After"] = query["retry_after"]
                    self._send_status(int(query.get("flaky_status", "503")), extra, b"busy")
                    return
            if "fail_once" in query and server.hit("fail_once:" + key) == 1:
                self._send_status(int(query["fail_once"]), {"Content-Type": "text/plain"}, b"failed once")
                return
            fail_after = int(query.get("fail_after_bytes", "0"))
            fail_count = 0
            if fail_after and self.headers.get("Range") != "bytes=0-0":
                fail_count = server.hit("fail_after:" + key)  # 1st data request is cut; the 2nd gets fail_code
                if fail_count == 2:
                    self._send_status(int(query.get("fail_code", "403")), {"Content-Type": "text/plain"}, b"expired")
                    return
            norange = query.get("norange") == "1"
            etag = '"' + hashlib.md5(data).hexdigest() + '"'
            etag_after = int(query.get("etag_after", "0"))
            if etag_after and server.hit("etag:" + key) > etag_after:
                etag = etag[:-1] + '-changed"'  # the representation "changed" on the server
            start, end = 0, len(data) - 1
            status = 200
            range_header = self.headers.get("Range")
            if_range = self.headers.get("If-Range")
            range_after = int(query.get("range_after", "0"))
            if range_header and range_after and server.hit("range:" + key) > range_after:
                norange = True  # honoured the first N ranged requests; now answer with the full body
            if range_header and not norange and (not if_range or if_range == etag):
                match = re.match(r"bytes=(\d+)-(\d*)", range_header)
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else len(data) - 1
                    if start >= len(data):
                        self._send_status(416, {"Content-Range": f"bytes */{len(data)}"})
                        return
                    end = min(end, len(data) - 1)
                    status = 206
            body = data[start : end + 1]
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            if not norange:
                self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            if "disposition" in query:
                self.send_header("Content-Disposition", query["disposition"])
            self.end_headers()
            if self.command == "HEAD":
                return
            drop_after = int(query.get("drop_after", "0"))
            drop_times = int(query.get("drop_times", "1"))
            should_drop = drop_after and server.hit("drop:" + key) <= drop_times
            if fail_after and fail_count == 1:  # fail_after_bytes: cut the first data response short
                drop_after, should_drop = fail_after, True
            rate = int(query.get("rate", "0"))
            slowconn = int(query.get("slowconn", "0"))
            if slowconn and range_header != "bytes=0-0" and self._connection_number(key) <= slowconn:
                rate = int(query["slowrate"])
            chunk = 16 * 1024
            sent = 0
            for offset in range(0, len(body), chunk):
                piece = body[offset : offset + chunk]
                if should_drop and sent + len(piece) > drop_after:
                    self.wfile.write(piece[: max(0, drop_after - sent)])
                    self.wfile.flush()
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                self.wfile.write(piece)
                sent += len(piece)
                if rate and offset + chunk < len(body):  # no pause after the last piece: it'd inflate `active`
                    time.sleep(len(piece) / rate)

    return Handler


@pytest.fixture
def http_server():
    server = TestServer()
    server.thread.start()
    try:
        yield server
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("SWIFTDROP_HOME", str(home))
    return home


@pytest.fixture
def downloads_dir(tmp_path):
    path = tmp_path / "Downloads"
    path.mkdir()
    return path


def wait_for(predicate, timeout: float = 10.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def ffmpeg_path():
    from swiftdrop.binaries import find_ffmpeg

    path = find_ffmpeg()
    if not path:
        pytest.skip("ffmpeg not available")
    return path


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SWIFTDROP_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network test (set SWIFTDROP_NETWORK_TESTS=1)")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


def _swiftc_command() -> list[str] | None:
    """Apple's swiftc through xcrun (which supplies the SDK); a swiftc first on PATH (e.g. swiftly) may not
    build against the macOS SDK, so it is only the fallback."""
    import shutil

    if shutil.which("xcrun"):
        return ["xcrun", "swiftc"]
    found = shutil.which("swiftc")
    return [found] if found else None


@pytest.fixture(scope="session")
def check_playable(tmp_path_factory):
    """scripts/check_playable.swift compiled once: asks AVFoundation (QuickTime) if files play."""
    import subprocess
    import sys

    if sys.platform != "darwin":
        pytest.skip("AVFoundation is macOS only")
    swiftc = _swiftc_command()
    if not swiftc:
        pytest.skip("swiftc not available")
    source = Path(__file__).resolve().parent.parent / "scripts" / "check_playable.swift"
    binary = tmp_path_factory.mktemp("swift") / "check_playable"
    built = subprocess.run([*swiftc, "-O", "-o", str(binary), str(source)], capture_output=True, text=True, timeout=600)
    if built.returncode != 0:
        pytest.skip("swiftc could not build check_playable: " + built.stderr.strip()[-300:])

    def run(path: Path) -> str:
        return subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=60).stdout

    return run
