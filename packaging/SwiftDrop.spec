# PyInstaller spec for the macOS .app bundle.  Build with:  make app   (or packaging/build_macos.sh)
# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
sys.path.insert(0, str(ROOT))
from swiftdrop.appinfo import APP_NAME, APP_VERSION, BUNDLE_ID  # noqa: E402

ARCH = os.environ.get("SWIFTDROP_ARCH", "arm64")
IDENTITY = os.environ.get("SWIFTDROP_CODESIGN_IDENTITY") or None
VENDOR = ROOT / "vendor" / "bin" / ARCH
ICON = ROOT / "packaging" / "generated" / "SwiftDrop.icns"
WEB = ROOT / "swiftdrop" / "ui" / "web"

if not (WEB / "index.html").exists():
    raise SystemExit("Web UI not built. Run: make ui")
if not (VENDOR / "ffmpeg").exists():
    raise SystemExit(f"FFmpeg not provisioned in {VENDOR}. Run: make binaries")

binaries = [(str(VENDOR / "ffmpeg"), "bin")]
if (VENDOR / "ffprobe").exists():
    binaries.append((str(VENDOR / "ffprobe"), "bin"))

datas = [
    (str(WEB), "swiftdrop/ui/web"),
    (str(ROOT / "vendor" / "licenses"), "licenses"),
    *collect_data_files("yt_dlp_ejs"),
]

hiddenimports = [
    *collect_submodules("yt_dlp"),
    *collect_submodules("yt_dlp_ejs"),
    "UserNotifications",
    "ServiceManagement",
    "WebKit",
    "webview.platforms.cocoa",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "pytest", "mypy", "PIL", "IPython"],
    noarchive=False,
    optimize=0,  # keep asserts/docstrings: the self-test and yt-dlp rely on them
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=ARCH,
    codesign_identity=IDENTITY,
    entitlements_file=str(ROOT / "packaging" / "entitlements.plist") if IDENTITY else None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(  # noqa: F821
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ICON) if ICON.exists() else None,
    bundle_identifier=BUNDLE_ID,
    version=APP_VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSHumanReadableCopyright": f"{APP_NAME} {APP_VERSION}",
        # Thumbnails from plain-http sites are shown inside the web view.
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoadsInWebContent": True},
    },
)
