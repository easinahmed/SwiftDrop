"""Moving finished downloads into place across volumes (copy path forced via _same_volume)."""

from pathlib import Path

import pytest

from swiftdrop import fileops
from swiftdrop.filenames import sanitize_filename
from swiftdrop.fileops import move_into_place, reserve_unique_path


@pytest.fixture
def cross_volume(monkeypatch):
    monkeypatch.setattr(fileops, "_same_volume", lambda a, b: False)


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.startswith("."))


def test_cross_volume_long_name(tmp_path, cross_volume):
    src = tmp_path / "staging.part"
    src.write_bytes(b"video bytes")
    dest = tmp_path / "dest"
    name = "a" * 236 + ".mp4"
    assert len(name.encode()) == 240
    target = reserve_unique_path(dest, name)
    final = move_into_place(src, target)
    assert final.read_bytes() == b"video bytes"
    assert not src.exists()
    assert _leftovers(dest) == []
    assert not any(p.name.endswith(".swiftdrop-copy") for p in dest.iterdir())


def test_cross_volume_failed_copy_removes_temp(tmp_path, cross_volume, monkeypatch):
    src = tmp_path / "staging.part"
    src.write_bytes(b"video bytes")
    dest = tmp_path / "dest"
    target = reserve_unique_path(dest, "clip.mp4")

    def disk_full_copy(source, destination, *args, **kwargs):
        Path(destination).write_bytes(b"half a file")  # the copy got partway
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fileops.shutil, "copy2", disk_full_copy)
    with pytest.raises(OSError) as info:
        move_into_place(src, target)
    assert info.value.errno == 28
    assert list(dest.iterdir()) == [], "no temp file and no zero-byte placeholder may remain"
    assert src.exists(), "the partial download must survive a failed move"


def test_cross_volume_unicode_long_name(tmp_path, cross_volume):
    src = tmp_path / "staging.part"
    src.write_bytes(b"video bytes")
    dest = tmp_path / "dest"
    # One leading ASCII char puts the sanitized name exactly on the 240-byte limit.
    name = sanitize_filename("x" + ("🎬ধ" * 120) + ".mp4")
    assert len(name.encode("utf-8")) == 240
    target = reserve_unique_path(dest, name)
    final = move_into_place(src, target)
    assert final.read_bytes() == b"video bytes"
    assert len(final.name.encode("utf-8")) <= 255
    assert final.name.endswith(".mp4")
    assert _leftovers(dest) == []
