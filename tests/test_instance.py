from __future__ import annotations

import sys

from swiftdrop.binaries import find_ffmpeg, find_js_runtime
from swiftdrop.instance import acquire_instance_lock


def test_second_instance_lock_fails(tmp_path):
    first = acquire_instance_lock(tmp_path)
    assert first is not None
    assert acquire_instance_lock(tmp_path) is None
    first.release()
    again = acquire_instance_lock(tmp_path)
    assert again is not None
    again.release()


def _fake_exe(path, body="#!/bin/sh\necho hi\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def test_frozen_ignores_env_overrides(tmp_path, monkeypatch):
    fake = _fake_exe(tmp_path / "ffmpeg")
    monkeypatch.setenv("SWIFTDROP_FFMPEG", str(fake))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert find_ffmpeg() != fake


def test_frozen_ignores_home_js_runtimes(tmp_path, monkeypatch):
    fake = _fake_exe(tmp_path / ".deno" / "bin" / "deno", "#!/bin/sh\necho deno 9.9.9\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SWIFTDROP_DENO", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("swiftdrop.binaries._SYSTEM_DIRS", ())
    monkeypatch.setattr("swiftdrop.binaries._FROZEN_JS_DIRS", ())
    monkeypatch.setattr("swiftdrop.binaries.shutil.which", lambda name: None)
    find_js_runtime.cache_clear()
    try:
        runtime = find_js_runtime()
        assert runtime is None or runtime.path != fake
    finally:
        find_js_runtime.cache_clear()
