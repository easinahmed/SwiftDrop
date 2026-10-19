"""The keyboard shortcut: parsing and validation, the service wiring (with a fake), and one real
macOS registration."""

from __future__ import annotations

import ctypes
import sys

import pytest

from swiftdrop.hotkey import DEFAULT_HOTKEY, KEYS, ShortcutError, format_shortcut, parse_shortcut
from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.platform.hotkey_macos import KEY_CODES
from swiftdrop.platform.hotkey_windows import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, WindowsHotkey, hotkey_args
from swiftdrop.service import HOTKEY_IN_USE, AppService, ServiceError
from swiftdrop.settings import SettingsError, SettingsStore
from swiftdrop.storage import Database
from tests.conftest import make_bytes, wait_for
from tests.test_capture import FakeUI

# -- parsing ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "mac", "canonical"),
    [
        ("ctrl+alt+d", True, "ctrl+alt+d"),
        ("Alt + Ctrl + D", True, "ctrl+alt+d"),
        ("shift+ctrl+7", False, "ctrl+shift+7"),
        ("cmd+shift+x", True, "shift+cmd+x"),
        ("ctrl+alt+shift+cmd+0", True, "ctrl+alt+shift+cmd+0"),
        ("alt+z", False, "alt+z"),
    ],
)
def test_parse_shortcut_normalises(text, mac, canonical):
    assert str(parse_shortcut(text, mac=mac)) == canonical


@pytest.mark.parametrize(
    ("text", "mac"),
    [
        ("d", True),  # no modifier
        ("shift+d", True),  # shift alone would block typing capitals
        ("ctrl+alt+f12", True),  # letters and digits only
        ("ctrl+alt+dd", True),
        ("ctrl+ctrl+d", True),
        ("ctrl+meta+d", True),
        ("cmd+d", False),  # Command is Mac only
        ("ctrl+alt+", True),
        ("", True),
        ("ctrl+" * 20 + "d", True),
        (None, True),
        (42, False),
    ],
)
def test_parse_shortcut_rejects(text, mac):
    with pytest.raises(ShortcutError):
        parse_shortcut(text, mac=mac)


def test_format_shortcut():
    assert format_shortcut(DEFAULT_HOTKEY, mac=True) == "⌃⌥D"
    assert format_shortcut(DEFAULT_HOTKEY, mac=False) == "Ctrl+Alt+D"
    assert format_shortcut("cmd+shift+ctrl+alt+9", mac=True) == "⌃⌥⇧⌘9"
    assert format_shortcut("ctrl+shift+5", mac=False) == "Ctrl+Shift+5"


def test_platform_key_tables_cover_every_key():
    assert set(KEY_CODES) == set(KEYS)
    assert len(set(KEY_CODES.values())) == len(KEYS)
    assert KEY_CODES["d"] == 0x02 and KEY_CODES["0"] == 0x1D
    assert hotkey_args(parse_shortcut("ctrl+alt+d", mac=False)) == (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x44)
    assert hotkey_args(parse_shortcut("shift+alt+0", mac=False)) == (MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, 0x30)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows fallback")
def test_windows_hotkey_is_inert_elsewhere():
    hotkey = WindowsHotkey()
    assert hotkey.start("ctrl+alt+d", lambda: None) is False
    hotkey.stop()


# -- settings ----------------------------------------------------------------------------


def test_hotkey_settings_are_validated(tmp_path):
    store = SettingsStore(Database(tmp_path / "db.sqlite3"))
    assert store.update({"hotkey": " Alt+Ctrl+K "}).hotkey == "ctrl+alt+k"
    for bad in ("k", "shift+k", "ctrl+alt+f1", True):
        with pytest.raises(SettingsError):
            store.update({"hotkey": bad})
    with pytest.raises(SettingsError):
        store.update({"hotkey_enabled": "yes"})


def test_command_is_refused_on_windows(tmp_path, monkeypatch):
    store = SettingsStore(Database(tmp_path / "db.sqlite3"))
    assert store.update({"hotkey": "cmd+alt+d"}).hotkey == "alt+cmd+d"
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(SettingsError):
        store.update({"hotkey": "cmd+alt+d"})
    reopened = SettingsStore(Database(tmp_path / "db.sqlite3"))
    assert reopened.get().hotkey == DEFAULT_HOTKEY  # a saved Mac-only shortcut falls back


def test_saved_pop_up_choice_is_kept(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.save_settings({"clipboard_popup": True})  # turned on (or left on) explicitly before
    assert SettingsStore(db).get().clipboard_popup is True
    fresh = SettingsStore(Database(tmp_path / "fresh.sqlite3"))
    assert fresh.get().clipboard_popup is False and fresh.get().watch_clipboard is False


# -- service wiring --------------------------------------------------------------------------


class FakeHotkey:
    def __init__(self, refuse: set[str] | None = None) -> None:
        self.refuse = refuse or set()
        self.active: str | None = None
        self.callback = None
        self.calls: list[str] = []

    def start(self, shortcut, callback):
        self.calls.append(f"start {shortcut}")
        if shortcut in self.refuse:
            return False
        self.active, self.callback = shortcut, callback
        return True

    def stop(self):
        self.calls.append("stop")
        self.active = self.callback = None


def _service(tmp_path, hotkey, **settings):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial")
    downloads = tmp_path / "Downloads"
    downloads.mkdir(exist_ok=True)
    svc = AppService(paths, NullPlatform(), enable_sites=False, hotkey=hotkey)
    svc.settings.update({"download_dir": str(downloads), **settings})
    return svc


@pytest.fixture
def hotkey():
    return FakeHotkey()


@pytest.fixture
def service(tmp_path, hotkey):
    svc = _service(tmp_path, hotkey)
    svc.start()
    svc.queue.shutdown(timeout=1)  # jobs stay where they are added
    yield svc
    svc.shutdown()


@pytest.fixture
def ui(service):
    fake = FakeUI()
    service.capture.attach_ui(fake)
    return fake


def test_no_clipboard_watcher_by_default_only_the_shortcut(service, hotkey):
    assert service.platform.monitor_callback is None
    assert hotkey.active == DEFAULT_HOTKEY and hotkey.calls == [f"start {DEFAULT_HOTKEY}"]
    service.update_settings({"clipboard_popup": True})
    assert service.platform.monitor_callback is not None
    service.update_settings({"clipboard_popup": False})
    assert service.platform.monitor_callback is None
    service.update_settings({"clipboard_monitoring": True})
    assert service.platform.monitor_callback is not None


def test_changing_and_disabling_the_shortcut(service, hotkey):
    data = service.update_settings({"hotkey": "ctrl+shift+9"})
    assert hotkey.active == "ctrl+shift+9" and hotkey.calls[-2:] == ["stop", "start ctrl+shift+9"]
    assert data["hotkey"] == "ctrl+shift+9" and data["hotkey_error"] is None
    service.update_settings({"theme": "dark"})
    assert hotkey.calls[-1] == "start ctrl+shift+9"  # unrelated changes leave it alone
    service.update_settings({"hotkey_enabled": False})
    assert hotkey.active is None and hotkey.calls[-1] == "stop"
    service.update_settings({"hotkey_enabled": True})
    assert hotkey.active == "ctrl+shift+9"
    service.shutdown()
    assert hotkey.active is None and hotkey.calls[-1] == "stop"


def test_a_taken_shortcut_turns_the_setting_off(tmp_path):
    hotkey = FakeHotkey(refuse={"ctrl+alt+x"})
    svc = _service(tmp_path, hotkey)
    svc.start()
    try:
        svc.tracker.drain()
        data = svc.update_settings({"hotkey": "ctrl+alt+x"})
        assert data["hotkey_enabled"] is False and data["hotkey_error"] == HOTKEY_IN_USE
        assert hotkey.active is None and svc.bootstrap()["settings"]["hotkey_error"] == HOTKEY_IN_USE
        assert svc.tracker.drain().settings
        data = svc.update_settings({"hotkey": "ctrl+alt+y", "hotkey_enabled": True})
        assert data["hotkey_enabled"] is True and data["hotkey_error"] is None and hotkey.active == "ctrl+alt+y"
        with pytest.raises(ServiceError):
            svc.update_settings({"hotkey": "shift+y"})
    finally:
        svc.shutdown()


def test_taken_at_launch_is_reported(tmp_path):
    hotkey = FakeHotkey(refuse={DEFAULT_HOTKEY})
    svc = _service(tmp_path, hotkey)
    svc.start()
    try:
        assert svc.settings.get().hotkey_enabled is False
        assert svc.settings_public()["hotkey_error"] == HOTKEY_IN_USE
        svc.update_settings({"hotkey_enabled": False})
        assert svc.settings_public()["hotkey_error"] is None
    finally:
        svc.shutdown()


def test_no_shortcut_when_switched_off(tmp_path):
    hotkey = FakeHotkey()
    svc = _service(tmp_path, hotkey, hotkey_enabled=False)
    svc.start()
    try:
        assert hotkey.calls == []
    finally:
        svc.shutdown()


def test_press_opens_the_copied_link(service, hotkey, ui, http_server):
    url = http_server.add_file("setup.dmg", make_bytes(500))
    service.platform.clipboard = f"get it here: {url}"
    hotkey.callback()  # what the OS hot key calls (on a worker thread)
    assert wait_for(lambda: ui.opened, timeout=5)
    info = service.capture.capture_public(ui.opened[0])
    assert info["kind"] == "file" and info["origin"] == "hotkey" and info["filename"] == "setup.dmg"
    assert info["size"] == 500
    hotkey.callback()  # its window is already open: no second one
    assert not wait_for(lambda: len(ui.opened) > 1, timeout=0.3)
    service.capture.window_closed(ui.opened[0])
    hotkey.callback()  # pressed again later: shown again
    assert wait_for(lambda: len(ui.opened) == 2, timeout=5)
    assert service.platform.flashes == [] and service.platform.notifications == []


def test_press_with_several_links_offers_add_all(service, hotkey, ui):
    service.platform.clipboard = "https://example.com/a.zip\nhttps://example.org/b.mp4\nhttps://example.com/about"
    hotkey.callback()
    assert wait_for(lambda: ui.opened, timeout=5)
    info = service.capture.capture_public(ui.opened[0])
    assert info["kind"] == "links" and info["count"] == 2


def test_press_shows_a_link_the_check_could_not_reach(service, hotkey, ui, http_server):
    url = http_server.url("/file/missing.zip")  # 404: the auto pop-up stays quiet, a press doesn't
    service.platform.clipboard = url
    hotkey.callback()
    assert wait_for(lambda: ui.opened, timeout=5)
    assert service.capture.capture_public(ui.opened[0])["filename"] == "missing.zip"


@pytest.mark.parametrize("clipboard", [None, "", "some notes", "https://example.com/article"])
def test_press_without_a_download_link_says_so(service, hotkey, ui, clipboard):
    service.platform.clipboard = clipboard
    service.platform.notifications_shown = False  # e.g. running from source
    hotkey.callback()
    assert service.platform.flashes == ["No link copied"]
    service.platform.notifications_shown = True
    hotkey.callback()
    assert service.platform.notifications[-1][0] == "No link copied"
    assert "⌃⌥D" in service.platform.notifications[-1][1] or "Ctrl+Alt+D" in service.platform.notifications[-1][1]
    service.update_settings({"notifications": False})
    hotkey.callback()
    assert service.platform.flashes == ["No link copied", "No link copied"]
    assert not wait_for(lambda: ui.opened, timeout=0.2)


def test_press_for_a_link_already_downloading(service, hotkey, ui, http_server):
    url = http_server.add_file("busy.zip", make_bytes(100))
    item = service.analyze_text(url)["added"][0]
    service.start_downloads([{"id": item["id"], "entries": None}], None, None)
    service.platform.clipboard = url
    service.platform.notifications_shown = False
    hotkey.callback()
    assert service.platform.flashes == ["Already in your downloads"]
    assert not wait_for(lambda: ui.opened, timeout=0.2)


def test_auto_pop_up_does_not_repeat_a_pressed_link(service, hotkey, ui, http_server):
    service.update_settings({"clipboard_popup": True})
    url = http_server.add_file("once.zip", make_bytes(100))
    service.platform.clipboard = url
    hotkey.callback()
    assert wait_for(lambda: ui.opened, timeout=5)
    service.clipboard_detected(url)  # the watcher sees the same copy a moment later
    assert not wait_for(lambda: len(ui.opened) > 1, timeout=0.3)


# -- the real thing (macOS) -------------------------------------------------------------------


def _carbon():
    if sys.platform != "darwin":
        return None
    try:
        return ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    except OSError:
        return None


@pytest.mark.skipif(_carbon() is None, reason="needs macOS Carbon")
def test_macos_registers_dispatches_and_unregisters():
    from swiftdrop.platform import hotkey_macos

    carbon = _carbon()
    c_void_p = ctypes.c_void_p
    carbon.GetApplicationEventTarget.restype = c_void_p
    carbon.CreateEvent.argtypes = [c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_double, ctypes.c_uint32]
    carbon.CreateEvent.argtypes += [ctypes.POINTER(c_void_p)]
    carbon.CreateEvent.restype = ctypes.c_int32
    carbon.SetEventParameter.argtypes = [c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_ulong, c_void_p]
    carbon.SetEventParameter.restype = ctypes.c_int32
    carbon.SendEventToEventTarget.argtypes = [c_void_p, c_void_p]
    carbon.SendEventToEventTarget.restype = ctypes.c_int32
    carbon.ReleaseEvent.argtypes = [c_void_p]

    def press(hot_key_id: int) -> int:
        """Deliver a kEventHotKeyPressed event, as the run loop does for a real key press."""
        event = c_void_p()
        assert carbon.CreateEvent(None, hotkey_macos._KEYBOARD_CLASS, 5, 0.0, 0, ctypes.byref(event)) == 0
        try:
            key = hotkey_macos._EventHotKeyID(hotkey_macos._SIGNATURE, hot_key_id)
            size = ctypes.sizeof(key)
            assert carbon.SetEventParameter(event, 0x2D2D2D2D, 0x686B6964, size, ctypes.byref(key)) == 0
            return carbon.SendEventToEventTarget(event, carbon.GetApplicationEventTarget())
        finally:
            carbon.ReleaseEvent(event)

    hotkey = hotkey_macos.MacHotkey()
    pressed = []
    assert hotkey.start("ctrl+alt+shift+cmd+9", lambda: pressed.append(True)) is True  # ⌃⌥⇧⌘9
    try:
        registered = hotkey._id
        assert press(registered) == 0
        assert wait_for(lambda: pressed == [True], timeout=2)
        assert press(registered + 1000) == hotkey_macos._NOT_HANDLED  # not ours: passed on
    finally:
        hotkey.stop()
    assert hotkey._id == 0 and hotkey._ref is None
    assert press(registered) == hotkey_macos._NOT_HANDLED
    assert hotkey.start("ctrl+alt+shift+cmd+8", lambda: None) is True  # can register again after stopping
    hotkey.stop()
