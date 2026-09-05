#!/usr/bin/env python3
# icon-svg.py -- spark's app icons and social card from the banner grid
# (home/.config/spark/banner, the file banner-svg.py takes as its argument):
# the letters as block rectangles, no font, so they draw the same
# everywhere. www/favicon.svg and www/og.png came out of it. Emits two SVGs
# and three PNGs; the PNGs are written directly with a stdlib zlib/struct
# encoder (a block grid is a trivial raster, no external rasterizer).
# Usage: icon-svg.py [BANNER_FILE] [OUT_DIR]
# Writes into OUT_DIR (default tools/out/):
#   icon-macos.svg  icon-macos-1024.png   rounded #100e0c tile, the S at 60%
#   icon-square.svg icon-square-1024.png  full-bleed #100e0c, the S at 66%
#   social-1280x640.png                   the full banner centered, 60px margin
import math
import os
import re
import struct
import sys
import zlib

GROUND = "#100e0c"
COLOURS = ["#ffe066", "#ffe066", "#e0b400", "#e0b400", "#d24a2a", "#d24a2a"]
CELL_W, CELL_H = 10, 18       # one character cell, as in banner-svg.py
LINE = 3                      # the thin stroke of a box-drawing piece
FULL = [(0, 0, 1, 1)]
def hbar(y): return (0, y, 1, LINE / CELL_H)
def vbar(x): return (x, 0, LINE / CELL_W, 1)
MID_X, MID_Y = 0.5 - LINE / CELL_W / 2, 0.5 - LINE / CELL_H / 2
PIECES = {
    "\u2588": FULL,
    "\u2550": [hbar(MID_Y)],
    "\u2551": [vbar(MID_X)],
    "\u2554": [(MID_X, MID_Y, 1 - MID_X, LINE / CELL_H), (MID_X, MID_Y, LINE / CELL_W, 1 - MID_Y)],
    "\u2557": [(0, MID_Y, MID_X + LINE / CELL_W, LINE / CELL_H), (MID_X, MID_Y, LINE / CELL_W, 1 - MID_Y)],
    "\u255a": [(MID_X, 0, LINE / CELL_W, MID_Y + LINE / CELL_H), (MID_X, MID_Y, 1 - MID_X, LINE / CELL_H)],
    "\u255d": [(MID_X, 0, LINE / CELL_W, MID_Y + LINE / CELL_H), (0, MID_Y, MID_X + LINE / CELL_W, LINE / CELL_H)],
    " ": [],
}
S_COLS = 8                    # the S is the banner's first eight columns


def read_banner(path):
    lines = [re.sub(r"\\033\[[0-9;]*m", "", l.rstrip("\n")) for l in open(path, encoding="utf-8")]
    return [l for l in lines if l.strip()][:6]


def grid_rects(lines, cols=None):
    """[(x, y, w, h, colour)] in banner units (CELL_W x CELL_H per cell)."""
    out = []
    for row, line in enumerate(lines):
        colour = COLOURS[row % len(COLOURS)]
        cells = line if cols is None else line[:cols]
        for col, ch in enumerate(cells):
            for (fx, fy, fw, fh) in PIECES.get(ch, FULL):
                out.append((col * CELL_W + fx * CELL_W, row * CELL_H + fy * CELL_H,
                            fw * CELL_W, fh * CELL_H, colour))
    return out


def rgba(hex6, a=255):
    return (int(hex6[1:3], 16), int(hex6[3:5], 16), int(hex6[5:7], 16), a)


class Canvas:
    def __init__(self, w, h, colour=(0, 0, 0, 0)):
        self.w, self.h = w, h
        self.rows = [bytearray(bytes(colour) * w) for _ in range(h)]

    def fill_rect(self, x0, y0, x1, y1, colour):
        xa, ya = max(0, int(round(x0))), max(0, int(round(y0)))
        xb, yb = min(self.w, int(round(x1))), min(self.h, int(round(y1)))
        if xb <= xa or yb <= ya:
            return
        px = bytes(colour) * (xb - xa)
        for y in range(ya, yb):
            self.rows[y][xa * 4:xb * 4] = px

    def fill_round_rect(self, x0, y0, x1, y1, r, colour):
        """Axis-aligned rounded rectangle, corners approximated row by row."""
        for y in range(max(0, int(round(y0))), min(self.h, int(round(y1)))):
            cy = y + 0.5
            dy = 0.0
            if cy < y0 + r:
                dy = (y0 + r) - cy
            elif cy > y1 - r:
                dy = cy - (y1 - r)
            if dy >= r:
                continue
            dx = r - math.sqrt(r * r - dy * dy) if dy > 0 else 0.0
            self.fill_rect(x0 + dx, y, x1 - dx, y + 1, colour)

    def draw_grid(self, rects, scale, ox, oy):
        for (x, y, w, h, colour) in rects:
            self.fill_rect(ox + x * scale, oy + y * scale,
                           ox + (x + w) * scale, oy + (y + h) * scale, rgba(colour))

    def write_png(self, path):
        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
        raw = b"".join(b"\x00" + bytes(r) for r in self.rows)
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)))
            f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
            f.write(chunk(b"IEND", b""))


def svg(path, size, rects, scale, ox, oy, tile=None):
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="spark">'
           % (size, size, size, size)]
    if tile is None:
        out.append('<rect width="%d" height="%d" fill="%s"/>' % (size, size, GROUND))
    else:
        tx, tw, tr = tile
        out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="%d" fill="%s"/>' % (tx, tx, tw, tw, tr, GROUND))
    out.append('<g transform="translate(%.1f,%.1f) scale(%.4f)">' % (ox, oy, scale))
    for (x, y, w, h, colour) in rects:
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (x, y, w + 0.4, h + 0.4, colour))
    out += ["</g>", "</svg>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    banner = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "lists", "banner")
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)
    lines = read_banner(banner)
    s_rects = grid_rects(lines, cols=S_COLS)
    all_rects = grid_rects(lines)
    s_w, s_h = S_COLS * CELL_W, len(lines) * CELL_H
    b_w, b_h = max(len(l) for l in lines) * CELL_W, len(lines) * CELL_H

    # macOS: 1024 canvas, transparent ground, a rounded GROUND tile 824x824
    # centered (r ~185 -- the one radius exception; the artwork stays square),
    # the S at 60% of the tile's width.
    size, tile_w, tile_r = 1024, 824, 185
    tile_x = (size - tile_w) / 2
    scale = tile_w * 0.60 / s_w
    ox, oy = (size - s_w * scale) / 2, (size - s_h * scale) / 2
    svg(os.path.join(outdir, "icon-macos.svg"), size, s_rects, scale, ox, oy,
        tile=(int(tile_x), tile_w, tile_r))
    c = Canvas(size, size)
    c.fill_round_rect(tile_x, tile_x, tile_x + tile_w, tile_x + tile_w, tile_r, rgba(GROUND))
    c.draw_grid(s_rects, scale, ox, oy)
    c.write_png(os.path.join(outdir, "icon-macos-1024.png"))

    # square: full-bleed GROUND, the S at 66% of the canvas width.
    scale = size * 0.66 / s_w
    ox, oy = (size - s_w * scale) / 2, (size - s_h * scale) / 2
    svg(os.path.join(outdir, "icon-square.svg"), size, s_rects, scale, ox, oy)
    c = Canvas(size, size, rgba(GROUND))
    c.draw_grid(s_rects, scale, ox, oy)
    c.write_png(os.path.join(outdir, "icon-square-1024.png"))

    # social card: the full banner centered on GROUND, 60px margin all round.
    # No tagline: rectangles only, no fonts.
    sw, sh, margin = 1280, 640, 60
    scale = min((sw - 2 * margin) / b_w, (sh - 2 * margin) / b_h)
    ox, oy = (sw - b_w * scale) / 2, (sh - b_h * scale) / 2
    c = Canvas(sw, sh, rgba(GROUND))
    c.draw_grid(all_rects, scale, ox, oy)
    c.write_png(os.path.join(outdir, "social-1280x640.png"))

    for f in ("icon-macos.svg", "icon-square.svg", "icon-macos-1024.png",
              "icon-square-1024.png", "social-1280x640.png"):
        print("%s  %d bytes" % (os.path.join(outdir, f), os.path.getsize(os.path.join(outdir, f))))


if __name__ == "__main__":
    main()
