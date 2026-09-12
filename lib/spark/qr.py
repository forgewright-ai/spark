# spark qr -- a QR encoder written from ISO/IEC 18004, the way chacha.py
# was written from RFC 8439: pure stdlib, small on purpose, pinned to the
# spec's own vectors in tests/qr_test.py (format-info table, the canonical
# Reed-Solomon example, and a full-matrix pin that is decoded back --
# format bits, unmask, zigzag, zero syndromes, the exact payload).
#
#   scope     byte mode only, error correction level L, versions 1-5
#             ONLY. At L those are each a single Reed-Solomon block (no
#             codeword interleaving) and v<=6 carries no version-info
#             field: that cap is what keeps this module small. It holds
#             106 bytes -- a login URL is ~80 -- and encode() answers
#             None past it, so a caller skips the QR and loses no line.
#   masking   all 8 masks with the spec's 4 penalty rules; the lowest
#             score wins, as the spec asks of an encoder.
#   render    half-block glyphs (two module rows per text line), LIGHT
#             modules drawn as glyphs: a terminal's dark background
#             plays the dark modules. Quiet zone 4, the spec's own. The
#             ASCII fallback
#             (SPARK_ASCII=1 / the Linux console, the one switch in
#             lib/spark/__init__.py) draws "##" per light module with
#             quiet zone 1 -- sub-spec, so version 5 stays inside the
#             console's 80 columns.
#   custody   a QR of a login URL IS the token drawn as squares: it is
#             printed only where the token itself would print.
#
# API: encode(data) -> matrix (list of rows of 0 light / 1 dark) or
# None; render(text, ascii_=None) -> str, "" when encode() refuses.
# A library, not a verb: forgeserve and users print it at a tty.

from . import ASCII

# version -> (data codewords, ec codewords) at level L, single block
_CW = {1: (19, 7), 2: (34, 10), 3: (55, 15), 4: (80, 20), 5: (108, 26)}
_EC_L = 1                     # the level's two format bits: L = 0b01
CAPACITY = _CW[5][0] - 2      # 106 bytes: mode + count cost 2 at v1-9

# ---------------------------------------------------------- GF(256)
# arithmetic over the field of the spec, primitive polynomial 0x11d

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11d
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _gen_poly(n):
    """The generator polynomial for n ec codewords: (x-a^0)..(x-a^n-1)."""
    g = [1]
    for i in range(n):
        nxt = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            nxt[j] ^= _gf_mul(c, _EXP[i])
            nxt[j + 1] ^= c
        g = nxt
    return g[::-1][1:]          # monic: drop the leading 1, high first


def rs_ec(data, n):
    """The n Reed-Solomon ec codewords for the data codewords."""
    g = _gen_poly(n)
    rem = [0] * n
    for d in data:
        f = d ^ rem[0]
        rem = rem[1:] + [0]
        if f:
            for i in range(n):
                rem[i] ^= _gf_mul(g[i], f)
    return rem


# ---------------------------------------------------------- format info

def format_bits(ec, mask):
    """The 15 format bits (int) for an ec level and mask: BCH(15,5),
    generator 0x537, then the spec's fixed XOR mask 0x5412."""
    data = (ec << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


# ---------------------------------------------------------- the matrix

def _size(version):
    return 17 + 4 * version


def _new(version):
    n = _size(version)
    grid = [[0] * n for _ in range(n)]
    func = [[False] * n for _ in range(n)]

    def put(r, c, v):
        grid[r][c] = v
        func[r][c] = True

    def finder(r0, c0):
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if not (0 <= rr < n and 0 <= cc < n):
                    continue
                inside = 0 <= r <= 6 and 0 <= c <= 6
                ring = inside and (r in (0, 6) or c in (0, 6))
                core = 2 <= r <= 4 and 2 <= c <= 4
                put(rr, cc, 1 if (ring or core) else 0)

    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)
    for i in range(8, n - 8):               # timing
        put(6, i, 1 if i % 2 == 0 else 0)
        put(i, 6, 1 if i % 2 == 0 else 0)
    if version >= 2:                        # one alignment pattern, centered
        a = 4 * version + 10
        for r in range(-2, 3):
            for c in range(-2, 3):
                put(a + r, a + c, 1 if (max(abs(r), abs(c)) != 1) else 0)
    put(4 * version + 9, 8, 1)              # the dark module
    for r, c in _fmt_cells(n):              # reserve the format areas
        func[r][c] = True
    return grid, func


def _fmt_cells(n):
    """The 30 format cells as (row, col), in bit order 0..14 (LSB
    first) per copy. Copy 1 around the top-left finder: bits 0-5 down
    beside it (rows 0-5, col 8), 6-7 at its corner, then 8-14 leftward
    under it (row 8, cols 7..0). Copy 2: bits 0-7 under the top-right
    finder (row 8, cols n-1..n-8), bits 8-14 beside the bottom-left one
    (rows n-7..n-1, col 8). The layout of the spec's figure 25; getting
    it transposed is invisible to a same-source decoder and fatal to a
    camera, which is why tests/qr_test.py also pins these cells
    literally."""
    one = [(0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
           (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0)]
    two = [(8, n - 1), (8, n - 2), (8, n - 3), (8, n - 4), (8, n - 5),
           (8, n - 6), (8, n - 7), (8, n - 8),
           (n - 7, 8), (n - 6, 8), (n - 5, 8), (n - 4, 8), (n - 3, 8),
           (n - 2, 8), (n - 1, 8)]
    return one + two


def _place_format(grid, n, ec, mask):
    bits = format_bits(ec, mask)
    cells = _fmt_cells(n)
    for i in range(15):                     # bit i (LSB first) on cells[i]
        v = (bits >> i) & 1
        r, c = cells[i]
        grid[r][c] = v
        r, c = cells[15 + i]
        grid[r][c] = v


def _path(func, n):
    """The zigzag: two columns at a time from the right, skipping the
    timing column, up then down, function cells stepped over."""
    cells = []
    col, up = n - 1, True
    while col >= 1:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if up else range(n)
        for r in rows:
            for c in (col, col - 1):
                if not func[r][c]:
                    cells.append((r, c))
        up = not up
        col -= 2
    return cells


_MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _penalty(grid, n):
    """The spec's four rules: runs (N1), 2x2 blocks (N2), finder-like
    1:1:3:1:1 runs with 4 light beside (N3), dark balance (N4)."""
    p = 0
    lines = [row[:] for row in grid]
    lines += [[grid[r][c] for r in range(n)] for c in range(n)]
    for line in lines:                      # N1
        run, last = 0, -1
        for v in line + [-1]:
            if v == last:
                run += 1
            else:
                if run >= 5:
                    p += 3 + run - 5
                run, last = 1, v
    for r in range(n - 1):                  # N2
        for c in range(n - 1):
            if grid[r][c] == grid[r][c + 1] == grid[r + 1][c] == grid[r + 1][c + 1]:
                p += 3
    bad = ([1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1])
    for line in lines:                      # N3
        for i in range(len(line) - 10):
            if line[i:i + 11] in bad:
                p += 40
    dark = sum(sum(row) for row in grid)    # N4
    p += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return p


# ---------------------------------------------------------- encode

def _bits_of(data, version):
    ncw = _CW[version][0]
    bits = []

    def emit(v, w):
        for i in range(w - 1, -1, -1):
            bits.append((v >> i) & 1)

    emit(4, 4)                              # byte mode
    emit(len(data), 8)                      # count, 8 bits at v1-9
    for b in data:
        emit(b, 8)
    emit(0, min(4, ncw * 8 - len(bits)))    # terminator
    while len(bits) % 8:
        bits.append(0)
    pad = (236, 17)
    i = 0
    while len(bits) < ncw * 8:
        emit(pad[i % 2], 8)
        i += 1
    return [sum(bits[i * 8 + j] << (7 - j) for j in range(8)) for i in range(ncw)]


def encode(data):
    """The QR matrix for data (str or bytes): rows of 0 light / 1 dark,
    or None when the data outgrows version 5 at level L (106 bytes)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    version = None
    for v in sorted(_CW):
        if len(data) <= _CW[v][0] - 2:
            version = v
            break
    if version is None:
        return None
    dcw = _bits_of(data, version)
    cw = dcw + rs_ec(dcw, _CW[version][1])
    stream = []
    for b in cw:
        for i in range(7, -1, -1):
            stream.append((b >> i) & 1)
    grid, func = _new(version)
    n = _size(version)
    cells = _path(func, n)
    for i, (r, c) in enumerate(cells):      # leftover cells stay 0
        grid[r][c] = stream[i] if i < len(stream) else 0
    best, best_p = None, None
    for m in range(8):
        g = [row[:] for row in grid]
        for (r, c) in cells:
            if _MASKS[m](r, c):
                g[r][c] ^= 1
        _place_format(g, n, _EC_L, m)
        p = _penalty(g, n)
        if best_p is None or p < best_p:
            best, best_p = g, p
    return best


# ---------------------------------------------------------- render

def render(text, ascii_=None):
    """The QR for text as terminal lines, or "" when it does not fit.
    Half-block glyphs by default (light modules drawn, quiet zone 2);
    the ASCII form ("##" per light module, quiet zone 1) on the console."""
    m = encode(text)
    if m is None:
        return ""
    if ascii_ is None:
        ascii_ = ASCII
    n = len(m)
    if ascii_:
        q = 1
        w = n + 2 * q
        rows = []
        for r in range(w):
            line = []
            for c in range(w):
                v = m[r - q][c - q] if (q <= r < q + n and q <= c < q + n) else 0
                line.append("  " if v else "##")
            rows.append("".join(line).rstrip())
        return "\n".join(rows)
    q = 4
    w = n + 2 * q
    def at(r, c):
        if q <= r < q + n and q <= c < q + n:
            return m[r - q][c - q]
        return 0                            # the quiet zone is light
    rows = []
    for r in range(0, w, 2):
        line = []
        for c in range(w):
            top = at(r, c) == 0
            bot = at(r + 1, c) == 0 if r + 1 < w else True
            line.append("\u2588" if top and bot else "\u2580" if top
                        else "\u2584" if bot else " ")
        rows.append("".join(line).rstrip())
    return "\n".join(rows)
