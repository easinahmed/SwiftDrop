#!/usr/bin/env python3
"""Render the app icon (macOS Big Sur style squircle) and build an .icns with iconutil."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "generated"
SIZE = 1024
BODY = 824  # Apple's icon grid: 824x824 body centred on a 1024 canvas
TOP = (52, 120, 255)
BOTTOM = (118, 82, 245)


def squircle_mask(size: int, exponent: float = 5.0) -> Image.Image:
    scale = 4
    big = size * scale
    mask = Image.new("L", (big, big), 0)
    pixels = mask.load()
    half = big / 2
    for y in range(big):
        ny = abs((y + 0.5 - half) / half)
        # Solve |x|^n + |y|^n = 1 for the row's half-width.
        span = (1 - ny**exponent) ** (1 / exponent) if ny < 1 else 0
        width = int(span * half)
        for x in range(int(half - width), int(half + width)):
            pixels[x, y] = 255
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def gradient(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return image


def glyph(size: int) -> Image.Image:
    """White "arrow down to tray" glyph with rounded strokes."""
    scale = 4
    big = size * scale
    layer = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(layer)
    stroke = int(big * 0.085)
    cx = big // 2
    top, tip = int(big * 0.2), int(big * 0.62)
    wing = int(big * 0.2)

    def line(p1: tuple[int, int], p2: tuple[int, int]) -> None:
        draw.line([p1, p2], fill=255, width=stroke)
        r = stroke // 2
        for x, y in (p1, p2):
            draw.ellipse([x - r, y - r, x + r, y + r], fill=255)

    line((cx, top), (cx, tip))
    line((cx - wing, tip - wing), (cx, tip))
    line((cx + wing, tip - wing), (cx, tip))
    tray_y = int(big * 0.8)
    line((int(big * 0.22), tray_y), (int(big * 0.78), tray_y))
    return layer.resize((size, size), Image.Resampling.LANCZOS)


def render() -> Image.Image:
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    mask = squircle_mask(BODY)
    offset = (SIZE - BODY) // 2

    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow_mask = Image.new("L", (SIZE, SIZE), 0)
    shadow_mask.paste(mask, (offset, offset + 14))
    shadow.putalpha(shadow_mask.point(lambda v: int(v * 0.32)))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(18)))

    body = gradient(BODY).convert("RGBA")
    highlight = Image.new("L", (BODY, BODY), 0)
    ImageDraw.Draw(highlight).ellipse([-BODY * 0.2, -BODY * 0.85, BODY * 1.2, BODY * 0.4], fill=34)
    highlight = highlight.filter(ImageFilter.GaussianBlur(BODY // 7))
    body = Image.composite(Image.new("RGBA", body.size, (255, 255, 255, 255)), body, highlight)

    mark = glyph(int(BODY * 0.62))
    mark_offset = ((BODY - mark.width) // 2, (BODY - mark.height) // 2 + 6)
    mark_shadow = Image.new("L", (BODY, BODY), 0)
    mark_shadow.paste(mark, (mark_offset[0], mark_offset[1] + 8))
    mark_shadow = mark_shadow.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.25))
    body = Image.composite(Image.new("RGBA", body.size, (20, 20, 60, 255)), body, mark_shadow)
    full_mark = Image.new("L", (BODY, BODY), 0)
    full_mark.paste(mark, mark_offset)
    body = Image.composite(Image.new("RGBA", body.size, (255, 255, 255, 255)), body, full_mark)

    rim = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(5)))
    body = Image.composite(Image.new("RGBA", body.size, (255, 255, 255, 255)), body, rim.point(lambda v: v // 6))
    body.putalpha(mask)
    canvas.alpha_composite(body, (offset, offset))
    return canvas


def main() -> int:
    OUT.mkdir(exist_ok=True)
    icon = render()
    icon.save(OUT / "icon-1024.png")
    iconset = OUT / "SwiftDrop.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        icon.resize((size, size), Image.Resampling.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
        icon.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "SwiftDrop.icns")], check=True)
    shutil.rmtree(iconset)
    print(f"Wrote {OUT / 'SwiftDrop.icns'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
