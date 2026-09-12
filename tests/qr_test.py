#!/usr/bin/env python3
"""The QR encoder against the spec's own numbers, then a decode-back.

Every piece of lib/spark/qr.py is pinned the way vault_test.py pins the
cipher: the format-info words against the spec's Table C.1 (all 8 masks
at L and M), the Reed-Solomon coder against the canonical v1-M example,
and a full matrix that is decoded back by this test -- the format bits
read and unXORed, the mask undone, the zigzag walked, the Reed-Solomon
syndromes all zero, and the byte-mode payload equal to the input. Then
structure (size, finders, timing, quiet zones, the render forms) and
refusals (too long answers None, an empty render answers ""). The
deploy step adds the one check no code can: a phone scans the printed
QR on the box.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from spark import qr  # noqa: E402

FAILED = 0


def check(name, got, want):
    global FAILED
    if got != want:
        FAILED += 1
        print("FAIL %s\n  got  %r\n  want %r" % (name, got, want))
    else:
        print("ok   %s" % name)


# --- 1. format info: the spec's Table C.1, levels L and M, masks 0-7
TABLE_C1 = {
    (1, 0): "111011111000100", (1, 1): "111001011110011",
    (1, 2): "111110110101010", (1, 3): "111100010011101",
    (1, 4): "110011000101111", (1, 5): "110001100011000",
    (1, 6): "110110001000001", (1, 7): "110100101110110",
    (0, 0): "101010000010010", (0, 1): "101000100100101",
    (0, 2): "101111001111100", (0, 3): "101101101001011",
    (0, 4): "100010111111001", (0, 5): "100000011001110",
    (0, 6): "100111110010111", (0, 7): "100101010100000",
}
for (ec, mask), want in sorted(TABLE_C1.items()):
    check("format ec=%d mask=%d" % (ec, mask),
          format(qr.format_bits(ec, mask), "015b"), want)

# --- 2. Reed-Solomon: the canonical v1-M example
check("rs canonical vector",
      qr.rs_ec([32, 91, 11, 120, 209, 114, 220, 77, 67, 64,
                236, 17, 236, 17, 236, 17], 10),
      [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

# --- 3. capacity and version choice
check("capacity is v5 at L", qr.CAPACITY, 106)
check("107 bytes refuse", qr.encode("x" * 107), None)
check("106 bytes fit (v5, 37)", len(qr.encode("x" * 106)), 37)
check("17 bytes fit v1 (21)", len(qr.encode("x" * 17)), 21)
check("18 bytes need v2 (25)", len(qr.encode("x" * 18)), 25)

URL = "http://192.0.2.1:8081/login#t=" + "Ab0-_" * 8 + "Ab0"  # TEST-NET, 73
M = qr.encode(URL)
N = len(M)
check("the pinned URL is v4", N, 33)

# --- 4a. the format cells, literally: a transposed layout decodes fine
# in this file's own decoder and fails every camera -- pin the spec's
# figure 25 as coordinates (v1, n=21), bit order 0..14 per copy
check("format cells (v1)", qr._fmt_cells(21),
      [(0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
       (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0),
       (8, 20), (8, 19), (8, 18), (8, 17), (8, 16), (8, 15), (8, 14),
       (8, 13),
       (14, 8), (15, 8), (16, 8), (17, 8), (18, 8), (19, 8), (20, 8)])

# --- 4. structure: finders, timing, only 0/1 cells
check("cells are 0/1", sorted(set(v for row in M for v in row)), [0, 1])
for name, r0, c0 in (("top-left", 0, 0), ("top-right", 0, N - 7),
                     ("bottom-left", N - 7, 0)):
    core = all(M[r0 + r][c0 + c] == 1 for r in (2, 3, 4) for c in (2, 3, 4))
    ring = all(M[r0][c0 + i] == 1 and M[r0 + 6][c0 + i] == 1 and
               M[r0 + i][c0] == 1 and M[r0 + i][c0 + 6] == 1 for i in range(7))
    check("finder %s" % name, core and ring, True)
check("timing row alternates",
      [M[6][c] for c in range(8, N - 8)],
      [1 if c % 2 == 0 else 0 for c in range(8, N - 8)])
check("dark module", M[4 * 4 + 9][8], 1)

# --- 5. decode-back: the strongest self-check without a camera


def decode(m):
    n = len(m)
    cells = qr._fmt_cells(n)
    bits = 0
    for i in range(15):
        r, c = cells[i]
        bits |= (m[r][c] & 1) << i
    data5 = (bits ^ 0x5412) >> 10
    ec, mask = data5 >> 3, data5 & 7
    if format(qr.format_bits(ec, mask), "015b") != format(bits, "015b"):
        return ec, mask, None, "format word does not re-encode"
    version = (n - 17) // 4
    _, func = qr._new(version)
    stream = []
    for (r, c) in qr._path(func, n):
        v = m[r][c]
        if qr._MASKS[mask](r, c):
            v ^= 1
        stream.append(v)
    ncw, necw = qr._CW[version]
    cw = [sum(stream[i * 8 + j] << (7 - j) for j in range(8))
          for i in range(ncw + necw)]

    def poly_eval(p, x):
        y = 0
        for c in p:
            y = qr._gf_mul(y, x) ^ c
        return y
    syn = [poly_eval(cw, qr._EXP[i]) for i in range(necw)]
    if any(syn):
        return ec, mask, None, "syndromes not zero"
    bs = []
    for b in cw[:ncw]:
        for i in range(7, -1, -1):
            bs.append((b >> i) & 1)
    mode = sum(bs[i] << (3 - i) for i in range(4))
    if mode != 4:
        return ec, mask, None, "not byte mode"
    cnt = sum(bs[4 + i] << (7 - i) for i in range(8))
    payload = bytes(sum(bs[12 + k * 8 + i] << (7 - i) for i in range(8))
                    for k in range(cnt))
    return ec, mask, payload, ""


ec, mask, payload, why = decode(M)
check("decode-back: level L", ec, 1)
check("decode-back: a legal mask", 0 <= mask <= 7, True)
check("decode-back: clean (%s)" % (why or "ok"), why, "")
check("decode-back: the exact payload", payload, URL.encode())

for text in ("x" * 17, "spark", "http://spark.local:8081/login#t=" + "Q" * 43,
             "x" * 106):
    m2 = qr.encode(text)
    _, _, p2, why2 = decode(m2)
    check("decode-back %d bytes (%s)" % (len(text), why2 or "ok"),
          p2, text.encode())

# --- 6. render: dimensions, quiet zones, the two forms
half = qr.render(URL, ascii_=False).split("\n")
check("half-block lines for v4 (33+8)/2", len(half), (33 + 8 + 1) // 2)
check("half-block width fits 80", max(len(l) for l in half) <= 33 + 8, True)
check("half-block glyph set",
      set("".join(half)) <= set(" \u2580\u2584\u2588"), True)
check("quiet zone: the top line is all light",
      set(half[0]) <= set("\u2588"), True)

plain = qr.render(URL, ascii_=True).split("\n")
check("ascii lines for v4 (33+2)", len(plain), 33 + 2)
check("ascii width fits 80 at v5",
      max(len(l) for l in qr.render("x" * 106, ascii_=True).split("\n")), 78)
check("ascii glyph set", set("".join(plain)) <= set("# "), True)
check("too long renders empty", qr.render("x" * 200), "")

if FAILED:
    print("%d failed" % FAILED)
    sys.exit(1)
print("qr_test: all ok")
