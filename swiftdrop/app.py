"""Application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from swiftdrop import handoff
from swiftdrop.appinfo import APP_NAME, APP_VERSION
from swiftdrop.handoff import is_scheme_link, parse_scheme_link
from swiftdrop.hotkey import native_hotkey
from swiftdrop.logging_setup import configure_logging, get_logger
from swiftdrop.paths import default_paths
from swiftdrop.platform import Platform


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME.lower(), description=f"{APP_NAME} media downloader")
    parser.add_argument("--self-test", action="store_true", help="run the built-in end-to-end check and exit")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector and verbose logs")
    parser.add_argument("--background", action="store_true", help="start with the main window hidden")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    # Finder may pass -psn_* arguments to bundled apps; ignore anything unknown.
    args, _unknown = parser.parse_known_args(argv)
    return args


def _ensure_std_streams() -> None:
    """A Finder-launched bundle may have no stdout/stderr; libraries that print must not crash."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - lives for the whole process
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115


def _hand_off(data_dir: Path, links: list[str], background: bool) -> None:
    """Another SwiftDrop is running: pass it the links (or ask it to show its window) and exit."""
    if sys.platform == "win32":
        # We were just started by the user, so we may give the running app the right to
        # bring its window to the front (otherwise Windows only flashes its taskbar button).
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    for url in (parse_scheme_link(link) for link in links):
        if url:
            handoff.send(data_dir, {"type": "add", "url": url})
    if links or background:
        return
    handoff.send(data_dir, {"type": "show"})  # its window may be hidden in the background
    _activate_running_instance()


def _activate_running_instance() -> None:
    if sys.platform == "win32":
        from swiftdrop.platform.windows import activate_window

        activate_window(APP_NAME)
        return
    try:
        from AppKit import NSApplicationActivateAllWindows, NSRunningApplication
    except ImportError:
        return
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.swiftdrop.SwiftDrop")
    if apps:
        apps[0].activateWithOptions_(NSApplicationActivateAllWindows)


def _native_platform() -> Platform:
    if sys.platform == "win32":
        from swiftdrop.platform.windows import WindowsPlatform

        return WindowsPlatform()
    from swiftdrop.platform.macos import MacPlatform

    return MacPlatform()


def main(argv: list[str] | None = None) -> int:
    _ensure_std_streams()
    raw_args = sys.argv[1:] if argv is None else argv
    # swiftdrop://add?url=… links (Windows passes them as an argument; so can a terminal).
    links = [arg for arg in raw_args if is_scheme_link(arg)]
    args = _parse([arg for arg in raw_args if not is_scheme_link(arg)])
    if args.self_test:
        from swiftdrop.selftest import run_self_test

        return run_self_test()

    paths = default_paths().ensure()
    configure_logging(paths.logs_dir, verbose=args.debug)
    log = get_logger("app")

    from swiftdrop.instance import acquire_instance_lock

    instance_lock = acquire_instance_lock(paths.data_dir)
    if instance_lock is None:
        log.info("SwiftDrop is already running")
        _hand_off(paths.data_dir, links, args.background)
        return 0

    from swiftdrop.service import AppService
    from swiftdrop.ui.window import run

    service = AppService(paths, _native_platform(), inbox=True, hotkey=native_hotkey())
    service.start()
    for link in links:  # shown once the window system runs
        url = parse_scheme_link(link)
        if url:
            service.capture.offer_url(url, origin="link")
    try:
        # Started just to handle a link: only its confirm window needs to appear.
        run(service, debug=args.debug, background=args.background or bool(links))
    except Exception:
        log.exception("UI crashed")
        raise
    finally:
        service.shutdown()
        instance_lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
