"""Application identity.

Everything user-visible that names the product (window title, data folders, the
bundle, the DMG) is derived from the constants below, so the app can be renamed
in one place. The Python package itself stays ``swiftdrop``.
"""

from __future__ import annotations

APP_NAME = "SwiftDrop"
APP_VERSION = "1.0.0"
APP_CREDIT = "Developed by Easin Codes"
# Reverse-DNS identifier used for the .app bundle, notifications and login items.
# Replace with an identifier from a domain you control before distributing.
BUNDLE_ID = "com.swiftdrop.SwiftDrop"
APP_TAGLINE = "Paste links. Get files."
USER_AGENT_TOKEN = f"{APP_NAME}/{APP_VERSION}"
