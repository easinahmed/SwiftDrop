#!/bin/zsh
# Build the macOS app bundle and DMG.
#
#   packaging/build_macos.sh
#
# Optional environment:
#   SWIFTDROP_ARCH                arm64 (default) or x86_64 (run on an Intel Mac / x86_64 Python)
#   SWIFTDROP_CODESIGN_IDENTITY   "Developer ID Application: Your Name (TEAMID)" — otherwise ad-hoc signed
#   SWIFTDROP_NOTARY_PROFILE      keychain profile created with `xcrun notarytool store-credentials`
set -euo pipefail

ROOT="${0:A:h:h}"
cd "$ROOT"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
ARCH="${SWIFTDROP_ARCH:-arm64}"
APP_NAME="$($PY -c 'from swiftdrop.appinfo import APP_NAME; print(APP_NAME)')"
VERSION="$($PY -c 'from swiftdrop.appinfo import APP_VERSION; print(APP_VERSION)')"
APP="dist/$APP_NAME.app"
DMG="dist/$APP_NAME-$VERSION-$ARCH.dmg"

step() { print -P "\n%F{blue}==>%f %B$1%b"; }

step "Building web UI"
(cd frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build)

step "Provisioning FFmpeg ($ARCH)"
[ -x "vendor/bin/$ARCH/ffmpeg" ] || "$PY" scripts/fetch_binaries.py --arch "$ARCH"

step "Rendering icon and DMG artwork"
"$PY" packaging/make_icon.py
"$PY" packaging/make_dmg_background.py

step "Bundling with PyInstaller"
rm -rf "build/$APP_NAME" "$APP" "dist/$APP_NAME"
SWIFTDROP_ARCH="$ARCH" "$PY" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath dist --workpath build packaging/SwiftDrop.spec

step "Signing"
if [[ -n "${SWIFTDROP_CODESIGN_IDENTITY:-}" ]]; then
  # PyInstaller already signed every binary with the identity + hardened runtime; seal the bundle.
  codesign --force --options runtime --timestamp \
    --entitlements packaging/entitlements.plist -s "$SWIFTDROP_CODESIGN_IDENTITY" "$APP"
else
  echo "No SWIFTDROP_CODESIGN_IDENTITY set: ad-hoc signing (local use / testing only)."
  codesign --force --deep -s - "$APP"
fi
codesign --verify --deep --strict --verbose=1 "$APP"

step "Self-test of the bundled app"
"$APP/Contents/MacOS/$APP_NAME" --self-test

step "Creating DMG"
rm -f "$DMG"
"$PY" -m dmgbuild -s packaging/dmg_settings.py -D app="$APP" "$APP_NAME" "$DMG"
if [[ -n "${SWIFTDROP_CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --timestamp -s "$SWIFTDROP_CODESIGN_IDENTITY" "$DMG"
fi

if [[ -n "${SWIFTDROP_NOTARY_PROFILE:-}" ]]; then
  [[ -n "${SWIFTDROP_CODESIGN_IDENTITY:-}" ]] || { echo "Notarization requires a Developer ID signature." >&2; exit 1; }
  step "Notarizing"
  xcrun notarytool submit "$DMG" --keychain-profile "$SWIFTDROP_NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi

step "Done"
ls -lh "$DMG"
echo "$ROOT/$DMG"
