# lua.py -- the egg. `spark lua` is a side-scrolling ASCII action-adventure
# in the rain forest of O Urubu-Rei e a Lua: eight zones, one Star of
# Memory in each (a line of the tale, home/.config/spark/tale), fallen
# logs, rivers, briars, prowling oncas and diving bats, and a bow. Eight
# stars open the Great Palm at the far end; the king vulture carries the
# hero up, the stars come out, a palette of your own lands in
# ~/.config/spark/themes/ and a card explains the word you have been typing.
#
# This is the ONE feature deliberately outside the landing rule: no help
# line, no cheatsheet row, no check row, no page, no AGENTS.md mention,
# and the one use of curses in spark (CLAUDE.md names it as the exception).
# The completion files name it in a comment (the drift guard in
# tests/smoke.py accepts that on purpose) and tests/smoke.py exercises it
# headless (--sim) and on a pty. Do not document it further; it is meant
# to be found, not read about.
#
# Text-first still holds where it matters: without a tty it prints one
# line and the tale's opening, never a frame; every glyph has an ASCII face
# for the console (spark.ASCII); the passages fold to ASCII there. The moon
# is real: tonight's phase comes from the date (no network) and sets how
# far around the hero the forest is lit. The forest is seeded by the day.
# stdlib only; curses is imported inside play(), never at import time.

import json
import math
import os
import random
import sys
import unicodedata
from datetime import date

from . import ASCII, CONFIG_DIR, MARK, REPO, STATE_DIR, say

STATE_FILE = os.path.join(STATE_DIR, "lua")
TALE_FILES = (os.path.join(CONFIG_DIR, "tale"), os.path.join(REPO, "home", ".config", "spark", "tale"))
PALETTE_NAME = "canarinho"
PALETTE = (
    "# Canarinho -- spark's own, written by the one who crossed the forest (MIT, like spark)",
    "THEME_BG=#0a1a33", "THEME_FG=#f4f4ec", "THEME_ACCENT=#ffdf00", "THEME_MUTED=#4c6e5a", "THEME_BTOP=Default",
    "THEME_ANSI_0=#11233f", "THEME_ANSI_1=#d94f4f", "THEME_ANSI_2=#009c3b", "THEME_ANSI_3=#ffdf00",
    "THEME_ANSI_4=#2e6fd6", "THEME_ANSI_5=#a86fcf", "THEME_ANSI_6=#3aa6a6", "THEME_ANSI_7=#d8dccf",
    "THEME_ANSI_8=#3d5a80", "THEME_ANSI_9=#f07070", "THEME_ANSI_10=#33cc66", "THEME_ANSI_11=#ffe94d",
    "THEME_ANSI_12=#5b93ff", "THEME_ANSI_13=#c79bff", "THEME_ANSI_14=#5fd0d0", "THEME_ANSI_15=#ffffff",
)
CARD = (
    "Lua -- PUC-Rio, Tecgraf, 1993. In Portuguese: moon.",
    "The plugin that puts spark in your editor is written in it.",
    "Cobra Computadores drew its engineers from the same city; those",
    "machines were rented by the hour. This one is yours.",
    "You have been typing the word all along.",
)

# glyphs: (terminal, console) -- every one drawable on the Linux console
_G = {"canopy": ("♣", "Y"), "log": ("■", "="), "hp_on": ("█", "#"), "hp_off": ("░", "."),
      "soil": ("#", "#"), "water": ("~", "~"), "ground": ("_", "_")}


def G(name):
    return _G[name][1 if ASCII else 0]


# colours for the frame: (colour 0-7, bold); curses maps them to pairs
DIM, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
PLAIN = (0, False)

# ------------------------------------------------------------- the moon --
SYNODIC = 29.530588853
NEW_MOON = date(2000, 1, 6)        # 18:14 UTC: a known new moon
PHASES = (("nova", "new"), ("crescente", "waxing crescent"), ("quarto crescente", "first quarter"),
          ("crescente gibosa", "waxing gibbous"), ("cheia", "full"), ("minguante gibosa", "waning gibbous"),
          ("quarto minguante", "last quarter"), ("minguante", "waning crescent"))


def phase(day=None):
    """0..1 through the lunation from the local date: 0 new, 0.5 full."""
    day = day or date.today()
    return (((day - NEW_MOON).days - 0.76 + 0.5) % SYNODIC) / SYNODIC


def phase_index(p):
    return int(p * 8 + 0.5) % 8


def illumination(p):
    return (1 - math.cos(2 * math.pi * p)) / 2


def moon_art(p):
    """Four ASCII lines: a ring, its inside lit from the right while waxing
    and from the left while waning, as the sky does it."""
    lit = int(round(illumination(p) * 4))
    if lit >= 4:
        inner = "####"
    elif p < 0.5:
        inner = " " * (4 - lit) + "#" * lit
    else:
        inner = "#" * lit + " " * (4 - lit)
    return [" .--. ", "|%s|" % inner, "|%s|" % inner, " '--' "]


def moon_line(day=None):
    p = phase(day)
    pt, en = PHASES[phase_index(p)]
    return "Rando: %s / %s (%d%%)" % (pt, en, int(round(illumination(p) * 100)))


# ------------------------------------------------------------- the tale --
def fold(s):
    """The console has no accents: NFKD, then ASCII only. Curly quotes too."""
    if not ASCII:
        return s
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'").replace("…", "...")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def tale():
    """{tag: (pt, en)} from the first tale file that exists."""
    for path in TALE_FILES:
        try:
            with open(path, encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f]
        except OSError:
            continue
        out, tag, body = {}, None, []
        for ln in lines + ["[end]"]:
            if not ln.strip() or ln.startswith("#"):
                continue
            if ln.startswith("[") and ln.endswith("]"):
                if tag and len(body) >= 2:
                    out[tag] = (body[0], body[1])
                tag, body = ln[1:-1], []
            else:
                body.append(ln)
        return out
    return {}


# ------------------------------------------------------------ the state --
def load_state():
    st = {"best": {"zone": 0, "stars": 0}, "won": False}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got.get("best"), dict):
            st["best"].update(got["best"])
        st["won"] = bool(got.get("won"))
    except (OSError, ValueError, AttributeError):
        pass
    return st


def save_state(st):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_FILE)


def write_palette():
    d = os.path.join(CONFIG_DIR, "themes")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, PALETTE_NAME + ".env")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(PALETTE) + "\n")
    return path


# ------------------------------------------------------------ the world --
ZONES = 8
ZONE_W = 320
START_W = 40
END_W = 60
WORLD_W = START_W + ZONES * ZONE_W + END_W
FLOOR = 13                 # the row of the ground line; the hero stands on FLOOR - 1
SOIL = 14                  # the row under it; the deep water
PLAY_H = 15                # world rows 0..14
STAND = FLOOR - 1          # 12
LAND, WATER, STONE = "land", "water", "stone"
JUMP_REACH = 7             # cells of water a plain jump clears
JUMP_ROWS = 4              # rows a plain jump rises


class World:
    """The forest for one seed: a floor kind per column, canopy per column,
    and lists of logs, briars, stars, oncas, bats; the palm at the end.
    Beatable by construction (check() proves the invariants)."""

    def __init__(self, seed):
        self.seed = seed
        r = self.rng = random.Random(seed)
        self.floor = [LAND] * WORLD_W
        self.canopy = [0] * WORLD_W          # 0 = none, else the row
        self.logs = []                       # [x0, x1, height]
        self.briars = set()
        self.stars = []                      # {"x", "y", "n", "taken"}
        self.oncas = []                      # {"x", "x0", "x1", "d", "alive"}
        self.bats = []                       # {"ax", "ay", "x", "y", "t", "dive", "alive"}
        self.palm_x = WORLD_W - 30
        for x in range(WORLD_W):
            if r.random() < 0.28:
                self.canopy[x] = r.randint(1, 3)
        for z in range(1, ZONES + 1):
            self._zone(z, START_W + (z - 1) * ZONE_W)

    # -- generation ------------------------------------------------------
    def _zone(self, z, x0):
        """A zone: the star's spot is reserved first (over flat ground in
        zones 1-3, over a log in 4-6, over a river's stone in 7-8), then a
        walk of flat land and features fills the rest around it."""
        r = self.rng
        x1 = x0 + ZONE_W
        sx = r.randint(x0 + 60, x1 - 80)          # the reserved span starts here
        if z <= 3:
            self.stars.append({"x": sx + 4, "y": STAND - 3, "n": z, "taken": False})
            reserve = (sx, sx + 8)
        elif z <= 6:
            self.logs.append([sx + 4, sx + 8, 2])
            self.stars.append({"x": sx + 6, "y": STAND - 2 - 3, "n": z, "taken": False})
            reserve = (sx, sx + 14)
        else:
            for i in range(sx + 4, sx + 18):
                self.floor[i] = WATER
            for i in range(sx + 10, sx + 12):
                self.floor[i] = STONE
            self.stars.append({"x": sx + 11, "y": STAND - 3, "n": z, "taken": False})
            reserve = (sx, sx + 24)
        x = x0 + 12                                # a flat start
        while x + 40 < x1:
            x += r.randint(10, 22)                 # flat land
            kind = self._pick(z)
            w = self._width(kind, z)
            if x + w + 3 > reserve[0] and x < reserve[1]:
                x = reserve[1] + 3                 # step over the star's span
                continue
            self._feature(kind, x, w, z)
            x += w + 3                             # landing room after a feature

    def _pick(self, z):
        table = [("log", 3), ("river", 2 + z // 2), ("briar", 1 + z // 3), ("onca", 1 + z // 2)]
        total = sum(w for _, w in table)
        pick = self.rng.random() * total
        for kind, w in table:
            pick -= w
            if pick <= 0:
                return kind
        return "log"

    def _width(self, kind, z):
        r = self.rng
        if kind == "log":
            return r.randint(4, 6)
        if kind == "river":
            return r.randint(4, 7) if z <= 2 or r.random() < 0.5 else r.randint(9, 13)
        if kind == "briar":
            return r.randint(2, 4)
        return 20                                  # an onca's stretch

    def _feature(self, kind, x, w, z):
        r = self.rng
        if kind == "log":
            self.logs.append([x, x + w - 1, 1 if z <= 3 or r.random() < 0.5 else 2])
            if z >= 3 and r.random() < 0.3:
                self._bat(x + w // 2)
        elif kind == "river":
            for i in range(x, x + w):
                self.floor[i] = WATER
            if w > JUMP_REACH:                     # a stone splits it into jumpable runs
                mid = x + w // 2
                for i in range(mid - 1, mid + 1):
                    self.floor[i] = STONE
            if z >= 3 and r.random() < 0.4:
                self._bat(x + w // 2)
        elif kind == "briar":
            for i in range(x, x + w):
                self.briars.add(i)
        else:                                      # an onca's stretch: flat, it patrols it
            self.oncas.append({"x": float(x + 10), "x0": x, "x1": x + w - 1, "d": 1, "alive": True})
            if z >= 2 and r.random() < 0.3:
                self._bat(x + 10)

    def _bat(self, ax):
        ay = self.rng.randint(3, 6)
        self.bats.append({"ax": ax, "ay": ay, "x": float(ax), "y": float(ay), "t": self.rng.randint(0, 60),
                          "dive": None, "alive": True})

    # -- geometry --------------------------------------------------------
    def log_at(self, x):
        for x0, x1, h in self.logs:
            if x0 <= x <= x1:
                return h
        return 0

    def stand_row(self, x):
        """The row the hero stands on at column x: STAND on land, less a
        log's height, FLOOR (the surface) on water."""
        x = max(0, min(WORLD_W - 1, x))
        if self.floor[x] == WATER:
            return FLOOR
        return STAND - self.log_at(x)

    def solid(self, x, y, stars):
        """A cell the hero cannot enter: a log's body, the palm's trunk
        while it is shut, the world's ends."""
        if x < 0 or x >= WORLD_W:
            return True
        h = self.log_at(x)
        if h and STAND - h < y <= STAND:
            return True
        if stars < 8 and self.palm_x <= x <= self.palm_x + 1 and 3 <= y <= STAND:
            return True
        return False

    def zone_of(self, x):
        return max(1, min(ZONES, int((x - START_W) // ZONE_W) + 1))

    def check(self):
        """The beatable-by-construction promise: every stretch of water is
        at most JUMP_REACH wide, every log at most JUMP_ROWS - 2 high, every
        star over a floor the hero can stand under it and within a jump.
        Returns a list of complaints, empty when the forest is fair."""
        bad = []
        run = 0
        for x in range(WORLD_W):
            run = run + 1 if self.floor[x] == WATER else 0
            if run > JUMP_REACH:
                bad.append("water run wider than %d at %d" % (JUMP_REACH, x))
                run = 0
        for x0, x1, h in self.logs:
            if h > JUMP_ROWS - 2:
                bad.append("log at %d too high (%d)" % (x0, h))
            if x1 - x0 + 1 > 6:
                bad.append("log at %d too wide" % x0)
        for s in self.stars:
            if self.floor[s["x"]] == WATER:
                bad.append("star %d over water" % s["n"])
            elif self.stand_row(s["x"]) - s["y"] > JUMP_ROWS:
                bad.append("star %d out of reach" % s["n"])
        return bad


# ------------------------------------------------------------- the game --
FPS = 20
RUN = 0.9
WADE = 0.45
GRAVITY = 0.25
JUMP_V = -1.4
HOLD = 4
SHOW_TICKS = 70
HP_MAX = 8


class Hero:
    def __init__(self, x):
        self.x = float(x)
        self.y = float(STAND)
        self.vy = 0.0
        self.facing = 1
        self.ground = True
        self.hp = HP_MAX
        self.immune = 0
        self.knock = 0
        self.knock_d = 0
        self.wet = 0

    @property
    def col(self):
        return int(round(self.x))

    @property
    def row(self):
        return int(round(self.y))


class Game:
    def __init__(self, cols, seed=None, day=None):
        self.cols = max(60, min(int(cols), 120))
        self.day = day
        self.seed = seed if seed is not None else (day or date.today()).toordinal()
        self.world = World(self.seed)
        self.rng = random.Random(self.seed * 7 + 1)
        self.p = phase(day)
        self.lit = 24 + int((self.cols - 24) * illumination(self.p))
        self.hero = Hero(8)
        self.arrows = []                     # [x, y, dir, range]
        self.hold = {"a": 0, "d": 0}
        self.want_jump = False
        self.want_shot = False
        self.cool = 0
        self.tick = 0
        self.cam = 0.0
        self.stars = 0
        self.taken = []                      # passage tags this run, in order
        self.show = None                     # (ticks, pt, en)
        self.over = None                     # dead | won | quit
        self.dying = None
        self.ending = None                   # the vulture's frame counter
        self.zone_max = 1
        self.hurts = []                      # (tick, cause) -- the sim's post-mortem

    # -- input -----------------------------------------------------------
    def key(self, k):
        """a d (move, a short hold refreshed by autorepeat), w (jump), s (shoot)."""
        if k in self.hold:
            self.hold[k] = HOLD
        elif k == "w":
            self.want_jump = True
        elif k == "s":
            self.want_shot = True

    # -- one tick --------------------------------------------------------
    def step(self):
        self.tick += 1
        if self.over or self.ending is not None:
            self._ending()
            return
        if self.dying is not None:
            self.dying -= 1
            if self.dying <= 0:
                self.over = "dead"
            return
        h, w = self.hero, self.world
        for k in self.hold:
            if self.hold[k]:
                self.hold[k] -= 1
        move = (1 if self.hold["d"] else 0) - (1 if self.hold["a"] else 0)
        if move:
            h.facing = move
        in_water = w.floor[h.col] == WATER and h.y >= FLOOR - 0.5
        if self.want_jump and h.ground:
            h.vy = JUMP_V
            h.ground = False
        self.want_jump = False
        if self.want_shot and self.cool == 0 and len(self.arrows) < 3:
            self.arrows.append([h.x + h.facing, h.row, h.facing, 30])
            self.cool = 6
        self.want_shot = False
        if self.cool:
            self.cool -= 1
        # horizontal
        if h.knock:
            vx = h.knock_d * 1.2
            h.knock -= 1
        else:
            vx = move * (WADE if in_water else RUN)
        nx = h.x + vx
        if not w.solid(int(round(nx)), h.row, self.stars):
            h.x = max(1.0, min(WORLD_W - 2.0, nx))
        # vertical
        h.vy = min(2.0, h.vy + GRAVITY)
        ny = h.y + h.vy
        floor = w.stand_row(h.col)
        if h.vy >= 0 and ny >= floor:
            # landing -- or a bank: wading out of a river, the hero is one
            # row under the land's floor and steps up onto it
            h.y = float(floor)
            h.vy = 0.0
            h.ground = True
        else:
            h.y = max(0.0, ny)
            h.ground = False
            if h.y == 0.0:
                h.vy = 0.0
        in_water = w.floor[h.col] == WATER and h.y >= FLOOR - 0.5
        # damage: water, briars
        if in_water:
            h.wet += 1
            if h.wet % 20 == 0:
                self._hurt(1, 0, "water")
        else:
            h.wet = 0
        if h.row == STAND and h.col in w.briars:
            self._hurt(1, -h.facing, "briar")
        if h.immune:
            h.immune -= 1
        # fauna
        for o in w.oncas:
            if not o["alive"]:
                continue
            d = h.x - o["x"]
            if abs(d) < 12:
                o["x"] += (1.0 if d > 0 else -1.0)
                o["d"] = 1 if d > 0 else -1
            else:
                o["x"] += o["d"] * 0.4
            if o["x"] <= o["x0"]:
                o["x"], o["d"] = float(o["x0"]), 1
            elif o["x"] >= o["x1"]:
                o["x"], o["d"] = float(o["x1"]), -1
            if abs(o["x"] - h.x) < 1.0 and h.row == STAND:
                self._hurt(2, 1 if h.x >= o["x"] else -1, "onca")
        for b in w.bats:
            if not b["alive"]:
                continue
            b["t"] += 1
            if b["dive"] is None:
                b["x"] = b["ax"] + 6 * math.sin(b["t"] / 10.0)
                b["y"] = b["ay"] + 1.5 * math.sin(b["t"] / 7.0)
                b["rest"] = max(0, b.get("rest", 0) - 1)
                if abs(b["x"] - h.x) < 10 and abs(h.y - b["y"]) > 1 and not b["rest"]:
                    b["dive"] = 0
                    b["aim"] = (h.x, h.y)                # a swoop at where the hero is: keep moving
            else:
                b["dive"] += 1
                if b["dive"] <= 14:
                    b["x"] += max(-0.9, min(0.9, b["aim"][0] - b["x"]))
                    b["y"] += max(-0.9, min(0.9, b["aim"][1] - b["y"]))
                elif b["dive"] <= 30:
                    b["x"] += max(-0.6, min(0.6, b["ax"] - b["x"]))
                    b["y"] += max(-0.6, min(0.6, b["ay"] - b["y"]))
                else:
                    b["dive"], b["rest"] = None, 80
            if abs(b["x"] - h.x) < 1.0 and abs(b["y"] - h.y) < 1.0:
                self._hurt(1, 1 if h.x >= b["x"] else -1, "bat")
        # arrows
        keep = []
        for a in self.arrows:
            x0 = a[0]
            a[0] += a[2] * 2
            a[3] -= 2
            ax, ay = int(round(a[0])), a[1]
            lo, hi = min(x0, a[0]) - 1.0, max(x0, a[0]) + 1.0
            if a[3] <= 0 or ax < 0 or ax >= WORLD_W or w.solid(ax, ay, self.stars):
                continue
            hit = False
            if ay == STAND:
                for bx in [x for x in w.briars if lo <= x <= hi]:
                    w.briars.discard(bx)
            for o in w.oncas:
                if o["alive"] and ay == STAND and lo <= o["x"] <= hi:
                    o["alive"], hit = False, True
            for b in w.bats:
                if b["alive"] and lo <= b["x"] <= hi and abs(b["y"] - ay) < 1.5:
                    b["alive"], hit = False, True
            if not hit:
                keep.append(a)
        self.arrows = keep
        # the stars
        for s in w.stars:
            if not s["taken"] and abs(s["x"] - h.x) < 1.3 and abs(s["y"] - h.y) < 1.2:
                s["taken"] = True
                self.stars += 1
                self.taken.append(str(s["n"]))
                self.show = (SHOW_TICKS, str(s["n"]))
        # the palm
        if h.col >= w.palm_x - 2:
            if self.stars >= 8:
                self.ending = 0
            elif self.show is None or self.show[1] != "palma":
                self.show = (40, "palma")
        if self.show:
            self.show = (self.show[0] - 1, self.show[1]) if self.show[0] > 1 else None
        self.zone_max = max(self.zone_max, w.zone_of(h.col))
        # the camera
        lead = self.cols // 3 if h.facing > 0 else 2 * self.cols // 3
        target = max(0.0, min(float(WORLD_W - self.cols), h.x - lead))
        self.cam += (target - self.cam) * 0.2
        if h.hp <= 0 and self.dying is None:
            self.dying = 10

    def _hurt(self, n, knock_dir, cause):
        h = self.hero
        if h.immune:
            return
        h.hp -= n
        self.hurts.append((self.tick, cause))
        h.immune = 15
        if knock_dir:
            h.knock, h.knock_d = 4, knock_dir

    def _ending(self):
        self.ending += 1
        if self.ending >= 34:
            self.over = "won"

    @property
    def zone(self):
        return self.world.zone_of(self.hero.col)

    # -- the picture -----------------------------------------------------
    def frame(self, tl, best):
        """20 rows of (char, (colour, bold)): status, 15 of forest, 4 of
        footer. Everything outside the moon's reach is dark."""
        w, h, cols = self.world, self.hero, self.cols
        rows = [[(" ", PLAIN)] * cols for _ in range(20)]
        cam = int(round(self.cam))

        def put(r, c, s, attr=PLAIN):
            if 0 <= r < 20:
                for i, ch in enumerate(s):
                    if 0 <= c + i < cols:
                        rows[r][c + i] = (ch, attr)

        def wput(r, wx, ch, attr=PLAIN):
            if abs(wx - h.x) <= self.lit:
                put(r, wx - cam, ch, attr)

        # status
        hp = max(0, h.hp)
        bar = "[" + G("hp_on") * hp + G("hp_off") * (HP_MAX - hp) + "]"
        put(0, 1, "%s lua" % MARK, (WHITE, True))
        put(0, 12, "HP " + bar, (GREEN if hp > 3 else RED, True))
        put(0, 27, "* %d/8" % self.stars, (YELLOW, True))
        put(0, 35, "zone %d/8" % self.zone, PLAIN)
        put(0, 46, moon_line(self.day)[: cols - 47], (CYAN, False))
        # the forest, column by column
        for sx in range(cols):
            wx = cam + sx
            if wx < 0 or wx >= WORLD_W or abs(wx - h.x) > self.lit:
                continue
            if w.canopy[wx]:
                put(w.canopy[wx], sx, G("canopy"), (GREEN, False))
            kind = w.floor[wx]
            if kind == WATER:
                put(FLOOR + 1, sx, G("water"), (BLUE, True))
                put(SOIL + 1, sx, G("water"), (BLUE, False))
            elif kind == STONE:
                put(FLOOR + 1, sx, G("log"), (YELLOW, False))
                put(SOIL + 1, sx, G("water"), (BLUE, False))
            else:
                put(FLOOR + 1, sx, G("ground"), PLAIN)
                put(SOIL + 1, sx, G("soil"), (DIM, True))
            lh = w.log_at(wx)
            for r in range(STAND - lh + 1, STAND + 1):
                put(r + 1, sx, G("log"), (YELLOW, False))
            if wx in w.briars:
                put(STAND + 1, sx, "x", (RED, False))
        # the palm
        for r in range(3, STAND + 1):
            for c in (w.palm_x, w.palm_x + 1):
                wput(r + 1, c, "|", (GREEN, self.stars >= 8))
        for r, span in ((1, 2), (2, 3), (3, 3)):
            for c in range(w.palm_x - span + 1, w.palm_x + span + 1):
                wput(r + 1, c, G("canopy"), (GREEN, True))
        # stars, fauna, arrows
        blink = (self.tick // 5) % 2 == 0
        for s in w.stars:
            if not s["taken"]:
                wput(s["y"] + 1, s["x"], "*", (YELLOW, blink))
        for o in w.oncas:
            if o["alive"]:
                wput(STAND + 1, int(round(o["x"])), "M", (RED, True))
        for b in w.bats:
            if b["alive"]:
                wput(int(round(b["y"])) + 1, int(round(b["x"])), "v", (MAGENTA, False))
        for a in self.arrows:
            wput(a[1] + 1, int(round(a[0])), ">" if a[2] > 0 else "<", (WHITE, True))
        # the hero, the vulture
        hr, hc = h.row, h.col - cam
        if self.ending is not None:
            e = self.ending
            vr = max(1, 1 + (hr - 1) * min(e, 14) // 14) if e <= 14 else max(1, hr - (e - 14) // 2)
            put(vr, hc - 1, "~V~" if (e // 3) % 2 else "-V-", (WHITE, True))
            if e > 14:
                hr = max(1, hr - (e - 14) // 2)
                r = self.rng
                for _ in range(e):
                    put(r.randint(2, 12), r.randint(0, cols - 1), "*", (YELLOW, r.random() < 0.5))
        if self.dying is not None:
            put(hr + 1, hc, "x", (RED, True))
        elif not (h.immune and self.tick % 2):
            put(hr + 1, hc, "@", (WHITE, True))
        # the footer
        if self.show:
            import textwrap
            if self.show[1] == "palma":
                pt, en = ("A Grande Palmeira espera por oito estrelas.", "The Great Palm waits for eight stars.")
            else:
                pt, en = tl.get(self.show[1], ("", ""))
            for i, ln in enumerate(textwrap.wrap(fold(pt), cols - 4)[:2]):
                put(16 + i, 2, ln, (YELLOW, False))
            for i, ln in enumerate(textwrap.wrap(fold(en), cols - 6)[:2]):
                put(18 + i, 4, ln, PLAIN)
        return rows


# ------------------------------------------------------------ the pilot --
class Pilot:
    """The sim's player: walks toward the lowest star it lacks (then the
    palm), jumps at water, logs, briars and stars, shoots what stands or
    flies ahead, and jumps when it has been stuck."""

    def __init__(self, g):
        self.g = g
        self.last_x = None
        self.stuck = 0

    def keys(self):
        g, h, w = self.g, self.g.hero, self.g.world
        want = [s for s in w.stars if not s["taken"]]
        goal = min(want, key=lambda s: s["n"])["x"] if want else w.palm_x
        d = 1 if goal >= h.x else -1
        out = ["d" if d > 0 else "a"]
        ahead = [int(round(h.x)) + d * i for i in range(1, 4)]
        jump = False
        for i, x in enumerate(ahead):
            if 0 <= x < WORLD_W:
                if w.floor[x] == WATER and w.floor[h.col] != WATER and i == 1:
                    jump = True
                if w.log_at(x) and not w.log_at(h.col) and i <= 1:
                    jump = True
                if x in w.briars and i <= 1:
                    jump = True
        for s in want:
            dx = abs(s["x"] - h.x)
            above = h.y - s["y"]
            if (s["x"] - h.x) * d >= 0 and 3 <= dx <= 6 and 0 < above <= JUMP_ROWS + 1:
                jump = True
            if dx < 1.0 and 0 < above <= JUMP_ROWS + 1:
                jump = True                      # right under it: straight up
                out = []                         # and no sidestep this tick
            elif dx < 3 and 0 < above <= JUMP_ROWS + 1:
                out = ["d" if s["x"] > h.x else "a"]     # walk under it first
        if self.last_x is not None and abs(h.x - self.last_x) < 0.05 and h.ground:
            self.stuck += 1
            if self.stuck >= 3:
                jump = True
                self.stuck = 0
        else:
            self.stuck = 0
        self.last_x = h.x
        if jump and h.ground:
            out.append("w")
        for o in w.oncas:
            if o["alive"] and (o["x"] - h.x) * d > 0 and abs(o["x"] - h.x) < 12:
                out.append("s")
                if abs(o["x"] - h.x) < 3 and h.ground:
                    out.append("w")
        for b in w.bats:
            if b["alive"] and abs(b["x"] - h.x) < 9 and abs(b["y"] - h.y) < 2.5:
                if (b["x"] - h.x) * d < 0:
                    out = ["a" if d > 0 else "d"] + [k for k in out if k not in ("a", "d")]
                out.append("s")
        return out


def sim(seed, tape, day=None):
    """Headless: a fixed seed and a key tape (per tick, repeating: a d w s
    . ) or `auto`, the Pilot. Returns the finished Game."""
    g = Game(80, seed=seed, day=day)
    pilot = Pilot(g) if tape == "auto" else None
    for i in range(6000):
        if pilot:
            for k in pilot.keys():
                g.key(k)
        else:
            k = tape[i % len(tape)]
            if k in "adws":
                g.key(k)
        g.step()
        if g.over:
            break
    g.over = g.over or "end"
    return g


def sim_line(g):
    return "zone %d stars %d over %s hp %d ticks %d" % (g.zone_max, g.stars, g.over, max(0, g.hero.hp), g.tick)


# ----------------------------------------------------------- the screen --
def play(st, tl):
    import curses

    def _play(stdscr):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.nodelay(True)
        stdscr.keypad(True)
        attrs = {}
        try:
            curses.start_color()
            curses.use_default_colors()
            for i in range(1, 8):
                curses.init_pair(i, i, -1)
            colour = True
        except curses.error:
            colour = False
        for c in range(8):
            for b in (False, True):
                a = curses.color_pair(c) if colour and c else 0
                attrs[(c, b)] = a | (curses.A_BOLD if b else 0)
        lines, cols = stdscr.getmaxyx()
        g = Game(cols, day=None)
        keys = {curses.KEY_LEFT: "a", curses.KEY_RIGHT: "d", curses.KEY_UP: "w",
                ord("a"): "a", ord("d"): "d", ord("w"): "w", ord(" "): "s",
                ord("A"): "a", ord("D"): "d", ord("W"): "w"}
        paused = False
        import time
        while not g.over:
            t0 = time.monotonic()
            while True:
                c = stdscr.getch()
                if c == -1:
                    break
                if c == 27:
                    # a terminal that ignores keypad mode sends ESC [ A..D:
                    # read the two bytes that follow and map them ourselves
                    c1, c2 = stdscr.getch(), stdscr.getch()
                    c = {ord("A"): curses.KEY_UP, ord("B"): curses.KEY_DOWN, ord("C"): curses.KEY_RIGHT,
                         ord("D"): curses.KEY_LEFT}.get(c2, -1) if c1 in (ord("["), ord("O")) else -1
                    if c == -1:
                        continue
                if c in (ord("q"), ord("Q")):
                    g.over = "quit"
                elif c in (ord("p"), ord("P")):
                    paused = not paused
                elif c == curses.KEY_RESIZE:
                    lines, cols = stdscr.getmaxyx()
                    g.cols = max(60, min(cols, 120))
                elif c in keys and not paused:
                    g.key(keys[c])
            if g.over:
                break
            stdscr.erase()
            if lines < 20 or cols < 60:
                stdscr.addstr(0, 0, "spark lua: 60x20 at least (this is %dx%d) -- q leaves" % (cols, lines))
            else:
                if not paused:
                    g.step()
                rows = g.frame(tl, st["best"])
                for r, row in enumerate(rows):
                    c0, run, cur = 0, [], None
                    for c, (ch, attr) in enumerate(row):
                        if attr != cur and run:
                            _draw(stdscr, r, c0, "".join(run), attrs[cur], lines, cols)
                            run, c0 = [], c
                        cur = attr
                        run.append(ch)
                    if run:
                        _draw(stdscr, r, c0, "".join(run), attrs[cur], lines, cols)
                if paused:
                    _draw(stdscr, 15, 2, "paused -- p goes on, q leaves", attrs[(WHITE, True)], lines, cols)
            stdscr.noutrefresh()
            curses.doupdate()
            rest = 1.0 / FPS - (time.monotonic() - t0)
            if rest > 0:
                curses.napms(int(rest * 1000))
        if g.over in ("dead", "won"):
            curses.napms(500)
        return g

    g = curses.wrapper(_play)
    if g.over == "quit":
        _remember(g, st)
        say("%s lua -- zone %d, * %d/8" % (MARK, g.zone_max, g.stars))
        return 0
    finish(g, st, tl)
    return 0


def _draw(stdscr, r, c, s, attr, lines, cols):
    """addstr that never raises: clipped, and the bottom-right cell via insstr."""
    if r >= lines or c >= cols or not s:
        return
    s = s[: cols - c]
    try:
        if r == lines - 1 and c + len(s) >= cols:
            stdscr.insstr(r, c, s, attr)
        else:
            stdscr.addstr(r, c, s, attr)
    except Exception:
        pass


# ------------------------------------------------------------ the shell --
def _remember(g, st):
    b = st["best"]
    if (g.zone_max, g.stars) > (b.get("zone", 0), b.get("stars", 0)):
        st["best"] = {"zone": g.zone_max, "stars": g.stars}
    if g.over == "won":
        st["won"] = True
    save_state(st)


def finish(g, st, tl):
    """After a run, at the shell: the outcome, what was taken, the ending."""
    path = None
    if g.over == "won":
        path = write_palette()       # before a word is printed: a closed pipe must not lose the prize
    _remember(g, st)
    say()
    say("%s lua -- %s" % (MARK, moon_line(g.day)))
    if g.over == "dead":
        say("  GAME OVER -- zone %d, * %d/8" % (g.zone_max, g.stars))
        pt, en = tl.get("queda", ("", ""))
        say("  %s" % fold(pt))
        say("  %s" % fold(en))
    for tag in g.taken:
        pt, en = tl.get(tag, ("", ""))
        say("  * %s" % fold(pt))
        say("    %s" % fold(en))
    say("  zone %d, * %d/8, best zone %d with %d" % (g.zone_max, g.stars, st["best"]["zone"], st["best"]["stars"]))
    if g.over == "won":
        pt, en = tl.get("fim", ("", ""))
        say()
        say("  %s" % fold(pt))
        say("  %s" % fold(en))
        say()
        say("  a palette of your own: %s" % path.replace(os.path.expanduser("~"), "~"))
        say("  spark theme %s" % PALETTE_NAME)
        say()
        for ln in CARD:
            say("  " + ln)
    say()


USAGE = """%s lua -- the forest, a bow, eight stars, a moon

  spark lua                 a d / arrows move, w / Up jumps, Space shoots,
                            p pauses, q leaves
  spark lua --moon [DATE]   tonight's moon, or a date's (YYYY-MM-DD)
  spark lua --reset         forget the best run
""" % MARK


def cmd_lua(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    tl = tale()
    if args and args[0] == "--moon":
        day = date.fromisoformat(args[1]) if len(args) > 1 else None
        say(moon_line(day))
        for ln in moon_art(phase(day)):
            say("  " + ln)
        return 0
    if args and args[0] == "--reset":
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass
        say("%s lua: the night starts over" % MARK)
        return 0
    st = load_state()
    if args and args[0] == "--sim":
        seed = int(args[1]) if len(args) > 1 else 1
        tape = args[2] if len(args) > 2 else "auto"
        day = date.fromisoformat(args[3]) if len(args) > 3 else None
        g = sim(seed, tape, day)
        say(sim_line(g))
        finish(g, st, tl)
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        pt, en = tl.get("abertura", ("", ""))
        say("%s lua: a terminal, please -- this one runs in the dark" % MARK)
        say("  %s" % fold(pt))
        say("  %s" % fold(en))
        return 2
    return play(st, tl)
