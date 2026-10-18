# dmgbuild settings: python -m dmgbuild -s packaging/dmg_settings.py -D app=dist/SwiftDrop.app "SwiftDrop" out.dmg
import os.path

app = defines.get("app", "dist/SwiftDrop.app")  # noqa: F821 - provided by dmgbuild
app_name = os.path.basename(app)
here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "packaging"

format = defines.get("format", "UDZO")  # noqa: F821
compression_level = 9
filesystem = "HFS+"
files = [app]
symlinks = {"Applications": "/Applications"}
# No hide_extensions: it writes com.apple.FinderInfo onto the bundle, which breaks strict
# signature verification. Finder hides the .app extension by default anyway.
icon_locations = {app_name: (170, 230), "Applications": (490, 230)}
icon = defines.get("icon", "packaging/generated/SwiftDrop.icns")  # noqa: F821 - volume icon
background = defines.get("background", "packaging/generated/dmg-background.tiff")  # noqa: F821
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
window_rect = ((200, 160), (660, 420))
default_view = "icon-view"
show_icon_preview = False
icon_size = 112
text_size = 13
arrange_by = None
grid_spacing = 100
label_pos = "bottom"
