#!/usr/bin/env python3
# banner-svg.py -- spark's banner (home/.config/spark/banner, six lines of
# block and box-drawing characters with one colour per line) as an SVG of
# rectangles: no font, so it draws the same on GitHub, in a browser tab and
# as a link preview. Usage: banner-svg.py BANNER_FILE > banner.svg
import re
import sys

COLOURS = ["#ffe066", "#ffe066", "#e0b400", "#e0b400", "#d24a2a", "#d24a2a"]   # bright yellow -> yellow -> red
CELL_W, CELL_H = 10, 18       # one character cell
LINE = 3                      # the thin stroke of a box-drawing piece
# each character -> rectangles as (x, y, w, h) fractions of a cell
FULL = [(0, 0, 1, 1)]
def hbar(y): return (0, y, 1, LINE / CELL_H)
def vbar(x): return (x, 0, LINE / CELL_W, 1)
MID_X, MID_Y = 0.5 - LINE / CELL_W / 2, 0.5 - LINE / CELL_H / 2
PIECES = {
    "\u2588": FULL,
    "\u2550": [hbar(MID_Y)],                                   # =
    "\u2551": [vbar(MID_X)],                                   # ||
    "\u2554": [(MID_X, MID_Y, 1 - MID_X, LINE / CELL_H), (MID_X, MID_Y, LINE / CELL_W, 1 - MID_Y)],   # top-left
    "\u2557": [(0, MID_Y, MID_X + LINE / CELL_W, LINE / CELL_H), (MID_X, MID_Y, LINE / CELL_W, 1 - MID_Y)],  # top-right
    "\u255a": [(MID_X, 0, LINE / CELL_W, MID_Y + LINE / CELL_H), (MID_X, MID_Y, 1 - MID_X, LINE / CELL_H)],  # bottom-left
    "\u255d": [(MID_X, 0, LINE / CELL_W, MID_Y + LINE / CELL_H), (0, MID_Y, MID_X + LINE / CELL_W, LINE / CELL_H)],  # bottom-right
    " ": [],
}

lines = [re.sub(r"\\033\[[0-9;]*m", "", l.rstrip("\n")) for l in open(sys.argv[1], encoding="utf-8")]
lines = [l for l in lines if l.strip()][:6]
width = max(len(l) for l in lines) * CELL_W
height = len(lines) * CELL_H
out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="spark">'
       % (width, height, width, height)]
for row, line in enumerate(lines):
    colour = COLOURS[row % len(COLOURS)]
    for col, ch in enumerate(line):
        for (fx, fy, fw, fh) in PIECES.get(ch, FULL):
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                       % (col * CELL_W + fx * CELL_W, row * CELL_H + fy * CELL_H, fw * CELL_W + 0.4, fh * CELL_H + 0.4, colour))
out.append("</svg>")
sys.stdout.write("\n".join(out) + "\n")
