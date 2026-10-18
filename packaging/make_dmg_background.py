#!/usr/bin/env python3
"""Render the DMG window background (1x + 2x, combined into a HiDPI TIFF)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "generated"
WIDTH, HEIGHT = 660, 420
APP_NAME = "SwiftDrop"


def font(size: int, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def render(scale: int) -> Image.Image:
    w, h = WIDTH * scale, HEIGHT * scale
    image = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(image)
    top, bottom = (248, 248, 251), (234, 234, 242)
    for y in range(h):
        t = y / (h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    title = f"Drag {APP_NAME} to Applications"
    f = font(20 * scale, bold=True)
    tw = draw.textlength(title, font=f)
    draw.text(((w - tw) / 2, 52 * scale), title, font=f, fill=(40, 40, 48))
    sub = "Then open it from your Applications folder."
    f2 = font(13 * scale)
    sw = draw.textlength(sub, font=f2)
    draw.text(((w - sw) / 2, 84 * scale), sub, font=f2, fill=(120, 120, 130))
    # Arrow between the two icon slots (app at x=170, Applications at x=490, y=230).
    y = 230 * scale
    x1, x2 = 262 * scale, 398 * scale
    color = (120, 110, 245)
    draw.line([(x1, y), (x2, y)], fill=color, width=4 * scale)
    draw.polygon([(x2 + 14 * scale, y), (x2 - 4 * scale, y - 11 * scale), (x2 - 4 * scale, y + 11 * scale)], fill=color)
    return image


def main() -> int:
    OUT.mkdir(exist_ok=True)
    one, two = OUT / "dmg-background.png", OUT / "dmg-background@2x.png"
    render(1).save(one)
    render(2).save(two)
    subprocess.run(
        ["tiffutil", "-cathidpicheck", str(one), str(two), "-out", str(OUT / "dmg-background.tiff")],
        check=True,
        capture_output=True,
    )
    print(f"Wrote {OUT / 'dmg-background.tiff'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
