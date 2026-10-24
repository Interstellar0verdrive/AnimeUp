"""Draws the AnimeUp app icon as a 1024x1024 PNG.

    python tools/make_icon.py <output.png>

The logo is the one in the header of `ui/app.py`: three rounded squares
climbing diagonally in #2AC9DE at opacities 0.3 / 0.55 / 1, on a 22x22
viewBox. Here it sits on a dark macOS-style rounded square (#17191C at the
top fading to #101113 at the bottom, the UI's two background colours).

No binary assets in git: tools/build_app.sh runs this at build time, then
makes the iconset with `sips` and the .icns with `iconutil`. Needs Pillow.
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
SS = 4                     # supersampling factor, for smooth edges
CYAN = (0x2A, 0xC9, 0xDE)
TOP = (0x17, 0x19, 0x1C)
BOTTOM = (0x10, 0x11, 0x13)

# macOS icon grid (Big Sur and later): the shape is 824 px on a 1024 canvas,
# with ~100 px of transparent margin that leaves room for the shadow.
TILE = 824
TILE_RADIUS = 185

# The logo in its own 22x22 coordinates: (x, y, size, opacity).
SQUARES = [(1, 13, 8, 0.30), (7, 7, 9, 0.55), (13, 1, 8, 1.00)]
CORNER = 1.5
LOGO = 540                 # rendered width of the 22-unit viewBox, in px


def _gradient(w: int, h: int) -> Image.Image:
    """Vertical gradient from TOP to BOTTOM."""
    column = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    return column.resize((w, h))


def draw(path: str) -> None:
    s = SIZE * SS
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    off = (SIZE - TILE) // 2 * SS
    box = (off, off, off + TILE * SS, off + TILE * SS)

    # Soft drop shadow under the tile.
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + 12 * SS, box[2], box[3] + 12 * SS),
        radius=TILE_RADIUS * SS, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14 * SS))
    canvas = Image.alpha_composite(canvas, shadow)

    # The dark tile, with a hairline highlight around the edge.
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=TILE_RADIUS * SS, fill=255)
    tile = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    tile.paste(_gradient(TILE * SS, TILE * SS), (off, off))
    tile.putalpha(mask)
    canvas = Image.alpha_composite(canvas, tile)
    rim = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(box, radius=TILE_RADIUS * SS,
                                          outline=(255, 255, 255, 22), width=3 * SS)
    canvas = Image.alpha_composite(canvas, rim)

    # The logo, centred: each square is its own layer so the overlaps blend
    # the way SVG opacity does.
    unit = LOGO * SS / 22
    origin = (s - LOGO * SS) / 2
    for x, y, size, opacity in SQUARES:
        layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        x0, y0 = origin + x * unit, origin + y * unit
        ImageDraw.Draw(layer).rounded_rectangle(
            (x0, y0, x0 + size * unit, y0 + size * unit),
            radius=CORNER * unit, fill=CYAN + (round(255 * opacity),))
        canvas = Image.alpha_composite(canvas, layer)

    canvas.resize((SIZE, SIZE), Image.LANCZOS).save(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: make_icon.py <output.png>")
    draw(sys.argv[1])
