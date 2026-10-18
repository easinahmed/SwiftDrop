"""Application entry point."""

from __future__ import annotations

import argparse
import os
import sys

from swiftdrop.appinfo import APP_NAME, APP_VERSION
from swiftdrop.logging_setup import configure_logging, get_logger
from swiftdrop.paths import default_paths


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_NAME.lower(), description=f"{APP_NAME} media downloader")
    parser.add_argument("--self-test", action="store_true", help="run the built-in end-to-end check and exit")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector and verbose logs")
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


def _activate_running_instance() -> None:
    try:
        from AppKit import NSApplicationActivateAllWindows, NSRunningApplication
    except ImportError:
        return
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.swiftdrop.SwiftDrop")
    if apps:
        apps[0].activateWithOptions_(NSApplicationActivateAllWindows)


def main(argv: list[str] | None = None) -> int:
    _ensure_std_streams()
    args = _parse(sys.argv[1:] if argv is None else argv)
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
        _activate_running_instance()
        return 0

    from swiftdrop.platform.macos import MacPlatform
    from swiftdrop.service import AppService
    from swiftdrop.ui.window import run

    service = AppService(paths, MacPlatform())
    service.start()
    try:
        run(service, debug=args.debug)
    except Exception:
        log.exception("UI crashed")
        raise
    finally:
        service.shutdown()
        instance_lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
