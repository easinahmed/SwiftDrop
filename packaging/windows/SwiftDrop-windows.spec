# PyInstaller spec for the Windows build (onedir, windowed).  Built by .github/workflows/windows.yml:
#   pyinstaller --noconfirm packaging/windows/SwiftDrop-windows.spec
# Needs the web UI (cd frontend && npm run build) and ffmpeg.exe + ffprobe.exe in vendor/bin/windows-x64.
# SwiftDrop.ico was made from packaging/generated/icon-1024.png (packaging/make_icon.py) with Pillow.
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent.parent  # noqa: F821 - provided by PyInstaller
sys.path.insert(0, str(ROOT))
from swiftdrop.appinfo import APP_CREDIT, APP_NAME, APP_VERSION  # noqa: E402

VENDOR = ROOT / "vendor" / "bin" / "windows-x64"
ICON = ROOT / "packaging" / "windows" / "SwiftDrop.ico"
WEB = ROOT / "swiftdrop" / "ui" / "web"

if not (WEB / "index.html").exists():
    raise SystemExit("Web UI not built. Run: cd frontend && npm run build")
for tool in ("ffmpeg.exe", "ffprobe.exe"):
    if not (VENDOR / tool).exists():
        raise SystemExit(f"{tool} not provisioned in {VENDOR}")

# swiftdrop.binaries looks for the tools in <bundle>/bin when frozen.
binaries = [(str(VENDOR / "ffmpeg.exe"), "bin"), (str(VENDOR / "ffprobe.exe"), "bin")]

datas = [
    (str(WEB), "swiftdrop/ui/web"),
    (str(ROOT / "vendor" / "licenses"), "licenses"),
    *collect_data_files("yt_dlp_ejs"),
    *collect_data_files("certifi"),
]

hiddenimports = [
    *collect_submodules("yt_dlp"),
    *collect_submodules("yt_dlp_ejs"),
    "clr",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "swiftdrop.platform.windows",
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

numbers = (*(int(part) for part in APP_VERSION.split(".")[:3]), 0)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Easin Codes"),
                        StringStruct("FileDescription", APP_NAME),
                        StringStruct("FileVersion", APP_VERSION),
                        StringStruct("InternalName", APP_NAME),
                        StringStruct("LegalCopyright", APP_CREDIT),
                        StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", APP_VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

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
    icon=str(ICON),
    version=version_info,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
