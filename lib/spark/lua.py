# lua.py -- the egg. `spark lua` is a micro side-scroller drawn right at the
# prompt: nine lines, one sprite high each, redrawn in place. The hero of
# O Urubu-Rei e a Lua runs the forest of the tale through eight short
# zones -- the river, the forest, the hunt, the wind, the rain, the
# thunder, the lightning, the strength -- and the star at the end of each
# is one of the eight memories of the line he remembers himself by:
# "Ele lembrou do rio, da mata, da cacada, do vento, da chuva, do trovao e
# do raio, e seu corpo foi se enchendo de uma forca que ele havia
# esquecido." The line assembles under the band, in English, as he collects
# it; each zone's gate opens with its star. Eight stars open the Great Palm; the king vulture
# carries him up, SUCCESS in the flag's colours, a palette of your own in
# ~/.config/spark/themes/, and a card that explains the word you typed.
#
# This is the ONE feature deliberately outside the landing rule: no help
# line, no cheatsheet row, no check row, no page, no AGENTS.md mention.
# The completion files name it in a comment (the drift guard in
# tests/smoke.py accepts that on purpose) and tests/smoke.py exercises it
# headless (--sim) and on a pty. Do not document it further; it is meant
# to be found, not read about.
#
# Text-first holds: no curses, no alternate screen -- the band stays in the
# scrollback when you leave; without a tty it prints one line and the
# tale's opening, never a frame; every glyph has an ASCII face for the
# console (spark.ASCII); the text folds to ASCII there; eight colours plus
# bold, nothing else. The moon is real: tonight's phase comes from the date
# (no network) and sits in the status line. The forest is seeded by the
# day. stdlib only.

import io
import json
import math
import os
import random
import select
import shutil
import subprocess
import sys
import textwrap
import time
import unicodedata
import wave
from datetime import date

from . import ASCII, CONFIG_DIR, IS_MAC, MARK, REPO, STATE_DIR, say

STATE_FILE = os.path.join(STATE_DIR, "lua")
SOUND_DIR = os.path.join(STATE_DIR, "cache", "lua")
TALE_FILES = (os.path.join(CONFIG_DIR, "tale"), os.path.join(REPO, "home", ".config", "spark", "tale"))
PALETTE_NAME = "canarinho"
PALETTE = (
    "# Canarinho -- spark's own, written by the one who crossed the forest (MIT, like spark)",
    "THEME_BG=#0a1a33", "THEME_FG=#f4f4ec", "THEME_ACCENT=#ffdf00", "THEME_MUTED=#4c6e5a", "THEME_BTOP=Default",
    "THEME_ANSI_0=#11233f", "THEME_ANSI_1=#d94f4f", "THEME_ANSI_2=#009c3b", "THEME_ANSI_3=#ffdf00",
    "THEME_ANSI_4=#2e6fd6", "THEME_ANSI_5=#a86fcf", "THEME_ANSI_6=#3aa6a6", "THEME_ANSI_7=#d8dccf",
    "THEME_ANSI_8=#3d5a80", "THEME_ANSI_9=#f07070", "THEME_ANSI_10=#33cc66", "THEME_ANSI_11=#ffe94d",
    "THEME_ANSI_12=#5b93ff", "THEME_ANSI_13=#c79bff", "THEME_ANSI_14=#5fd0d0", "THEME_ANSI_15=#ffffff",
    "THEME_LOGO=bright-green bright-green bright-yellow bright-yellow bright-blue bright-blue",
)
# the one line that keeps the joke: the rest is in CREDITS.md
CARD = "lua: the moon, in Portuguese. It was in the word all along."

# glyphs: (terminal, console) -- every one drawable on the Linux console
_G = {"canopy": ("♣", "Y"), "log": ("■", "="), "hp_on": ("█", "#"), "hp_off": ("░", "."),
      "soil": ("#", "#"), "water": ("~", "~"), "ground": ("_", "_"), "block": ("█", "#")}


def G(name):
    return _G[name][1 if ASCII else 0]


# an attribute is (colour 0-7, style) -- style "" plain, "b" bold, "d" dim;
# colour 0 means the terminal's own foreground
DEFAULT, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
PLAIN = (0, "")

# ------------------------------------------------------------- the moon --
SYNODIC = 29.530588853
NEW_MOON = date(2000, 1, 6)        # 18:14 UTC: a known new moon
PHASES = (("new", "nova"), ("waxing crescent", "crescente"), ("first quarter", "quarto crescente"),
          ("waxing gibbous", "crescente gibosa"), ("full", "cheia"), ("waning gibbous", "minguante gibosa"),
          ("last quarter", "quarto minguante"), ("waning crescent", "minguante"))


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
    en, _ = PHASES[phase_index(p)]
    return "Moon: %s" % en


# ------------------------------------------------------------- the tale --
def fold(s):
    """The console has no accents: NFKD, then ASCII only. Curly quotes too."""
    if not ASCII:
        return s
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'").replace("…", "...")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def tale():
    """{tag: (en, pt)} from the first tale file that exists."""
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


GAP = "....."


def memory(tl, taken, lang):
    """The remembered line assembled from the pieces taken (a set of "1".."8"),
    a gap for each one missing; lang 0 = English, 1 = Portuguese."""
    return fold(" ".join(tl.get(str(n), ("", ""))[lang] if str(n) in taken else GAP for n in range(1, 9)))


# the eight zones: (English, Portuguese) names, the memory each holds
ZONE_NAMES = (("the river", "o rio"), ("the forest", "a mata"), ("the hunt", "a caçada"), ("the wind", "o vento"),
              ("the rain", "a chuva"), ("the thunder", "o trovão"), ("the lightning", "o raio"), ("the strength", "a força"))

# ------------------------------------------------------------ the state --
NIGHTS = 6                 # the forest runs faster and pays more each night, up to this


def load_state():
    st = {"best": {"zone": 0, "stars": 0}, "won": False, "nights": 0, "scores": []}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got.get("best"), dict):
            st["best"].update(got["best"])
        st["won"] = bool(got.get("won"))
        st["nights"] = int(got.get("nights", 0))
        st["scores"] = [r for r in got.get("scores", []) if isinstance(r, dict)][:5]
    except (OSError, ValueError, AttributeError, TypeError):
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
    try:
        with open(path, encoding="utf-8") as f:
            have = f.read()
    except OSError:
        have = ""
    if "THEME_LOGO=" not in have:           # absent, or written before the logo line existed
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(PALETTE) + "\n")
    return path


# ------------------------------------------------------------ the world --
ZONES = 8
ZONE_W = 140
START_W = 30
END_W = 40
WORLD_W = START_W + ZONES * ZONE_W + END_W
CANOPY, AIR2, AIR1, LANE, GROUND, SOIL = range(6)     # the six world rows, one sprite high each
LAND, WATER, STONE = "land", "water", "stone"
JUMP_REACH = 5             # cells of water a jump clears
# what each zone is made of: (kind, weight) and the chance of a bat over a feature
ZONE_MIX = (
    ((("river", 4), ("log", 1)), 0.0),
    ((("log", 4), ("river", 1)), 0.0),
    ((("onca", 3), ("log", 2), ("river", 1)), 0.0),
    ((("river", 2), ("log", 2), ("briar", 1)), 0.5),
    ((("river", 4), ("briar", 3), ("log", 1)), 0.15),
    ((("onca", 3), ("log", 2), ("briar", 2)), 0.3),
    ((("river", 2), ("log", 2), ("briar", 2), ("onca", 2)), 0.4),
    ((("river", 3), ("log", 3), ("briar", 3), ("onca", 3)), 0.4),
)


class World:
    """The forest for one seed: a floor kind per column, canopy per column,
    logs, briars, stars, oncas, bats; the zone posts; the palm at the end.
    Beatable by construction (check() proves the invariants)."""

    def __init__(self, seed):
        self.seed = seed
        r = self.rng = random.Random(seed)
        self.floor = [LAND] * WORLD_W
        self.canopy = [False] * WORLD_W
        self.under = [False] * WORLD_W       # a sparser line of trees under the canopy
        self.logs = set()                    # columns with a log (one high)
        self.briars = set()
        self.stars = []                      # {"x", "n", "taken"}
        self.oncas = []                      # {"x", "x0", "x1", "d", "alive"}
        self.bats = []                       # {"ax", "x", "y", "t", "dive", "aim", "rest", "alive"}
        self.heals = []                      # {"x", "taken"}: a + on the lane, two HP, zones 5-8
        self.posts = []                      # a zone starts here; from the second on, a gate
                                             # that opens with the zone before's star
        self.palm_x = WORLD_W - 22
        for z in range(1, ZONES + 1):
            self._zone(z, START_W + (z - 1) * ZONE_W)

    def _zone(self, z, x0):
        r = self.rng
        x1 = x0 + ZONE_W
        self.posts.append(x0)
        mix, bat_p = ZONE_MIX[z - 1]
        dense = z in (2, 6, 7, 8)
        for x in range(x0, x1):
            if r.random() < (0.45 if dense else 0.25):
                self.canopy[x] = True
            if r.random() < (0.14 if dense else 0.07):
                self.under[x] = True
        gap = (8, 14) if z <= 2 else (6, 12) if z <= 5 else (5, 9)     # the forest thickens
        x = x0 + 8                           # a flat start
        while True:
            x += r.randint(*gap)
            kind = self._pick(mix)
            w = self._width(kind, z)
            if x + w > x1 - 20:              # the last 20 columns stay flat: the star's clearing
                break
            self._feature(kind, x, w, z)
            if r.random() < bat_p:
                self._bat(x + w // 2)
            x += w + 3                       # landing room after a feature
        self.stars.append({"x": x1 - 12, "n": z, "taken": False})
        if z >= 5:                           # a heal midway, on plain ground
            for hx in range(x0 + ZONE_W // 2, x1 - 30):
                if self.floor[hx] == LAND and hx not in self.logs and hx not in self.briars \
                        and not any(o["x0"] - 2 <= hx <= o["x1"] + 2 for o in self.oncas):
                    self.heals.append({"x": hx, "taken": False})
                    break

    def _pick(self, mix):
        total = sum(w for _, w in mix)
        pick = self.rng.random() * total
        for kind, w in mix:
            pick -= w
            if pick <= 0:
                return kind
        return mix[0][0]

    def _width(self, kind, z):
        r = self.rng
        if kind == "log":
            return r.randint(3, 5)
        if kind == "river":
            return r.randint(3, 5) if z < 5 or r.random() < 0.5 else r.randint(7, 9)
        if kind == "briar":
            return r.randint(2, 3)
        return 14                            # an onca's stretch

    def _feature(self, kind, x, w, z):
        if kind == "log":
            self.logs.update(range(x, x + w))
        elif kind == "river":
            for i in range(x, x + w):
                self.floor[i] = WATER
            if w > JUMP_REACH:               # a stone splits it into jumpable runs
                mid = x + w // 2
                self.floor[mid - 1] = self.floor[mid] = STONE
        elif kind == "briar":
            self.briars.update(range(x, x + w))
        else:                                # an onca's stretch: flat, it patrols it
            self.oncas.append({"x": float(x + 7), "x0": x, "x1": x + w - 1, "d": 1, "alive": True,
                               "charge": 1.25 if z >= 7 else 1.1 if z >= 6 else 0.9, "tell": 0, "seen": False})

    def _bat(self, ax):
        self.bats.append({"ax": ax, "x": float(ax), "y": float(CANOPY), "t": self.rng.randint(0, 60),
                          "dive": None, "aim": None, "rest": 0, "alive": True})

    # -- geometry --------------------------------------------------------
    def stand_row(self, x):
        """Where the hero stands at column x: the lane; a log's top; the
        surface of water."""
        x = max(0, min(WORLD_W - 1, x))
        if self.floor[x] == WATER:
            return GROUND
        return AIR1 if x in self.logs else LANE

    def gate_shut(self, x):
        """A zone's post is a gate until the star of the zone before it is
        taken: the memory opens the way."""
        if x in self.posts:
            n = self.posts.index(x)
            return n > 0 and not self.stars[n - 1]["taken"]
        return False

    def solid(self, x, row, stars):
        """A cell the hero cannot enter: a log's body on the lane, a shut
        gate, the palm's trunk while it is shut, the world's ends."""
        if x < 0 or x >= WORLD_W:
            return True
        if row == LANE and x in self.logs:
            return True
        if AIR2 <= row <= LANE and self.gate_shut(x):
            return True
        if stars < 8 and self.palm_x <= x <= self.palm_x + 1 and AIR2 <= row <= LANE:
            return True
        return False

    def zone_of(self, x):
        return max(1, min(ZONES, int((x - START_W) // ZONE_W) + 1))

    def check(self):
        """The beatable-by-construction promise: every stretch of water is
        at most JUMP_REACH wide, every star stands over plain land with a
        clear run-up, every onca's stretch is flat. Returns complaints;
        empty when the forest is fair."""
        bad = []
        run = 0
        for x in range(WORLD_W):
            run = run + 1 if self.floor[x] == WATER else 0
            if run > JUMP_REACH:
                bad.append("water run wider than %d at %d" % (JUMP_REACH, x))
                run = 0
        for s in self.stars:
            for x in range(s["x"] - 6, s["x"] + 3):
                if self.floor[x] != LAND or x in self.logs or x in self.briars:
                    bad.append("star %d has no clear run-up at %d" % (s["n"], x))
                    break
        for o in self.oncas:
            if any(self.floor[x] != LAND or x in self.logs for x in range(o["x0"], o["x1"] + 1)):
                bad.append("onca at %d on rough ground" % o["x0"])
        return bad


# ------------------------------------------------------------- the game --
FPS = 20
RUN = 0.9
WADE = 0.45
GRAVITY = 0.25
JUMP_V = -1.05             # apex 1.7 rows above the lane: a star at AIR2 is taken at the top
HP_MAX = 8


class Hero:
    def __init__(self, x):
        self.x = float(x)
        self.y = float(LANE)
        self.vy = 0.0
        self.run = 0             # -1 0 1: tap to run, tap to stop
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
    def __init__(self, cols, seed=None, day=None, night=1):
        self.night = max(1, min(NIGHTS, int(night)))
        self.pace = 1.0 + 0.12 * (self.night - 1)     # the forest runs faster each night
        self.points = 0                               # before the night's multiplier
        self.far = 0.0                                # the furthest column reached
        self.cols = max(60, min(int(cols), 200))
        self.day = day
        self.seed = seed if seed is not None else (day or date.today()).toordinal()
        self.world = World(self.seed)
        self.rng = random.Random(self.seed * 7 + 1)
        self.p = phase(day)
        self.hero = Hero(6)
        self.first_key = None                # the tick of the first key: the hint shows before it
        self.callout = None                  # (ticks left, zone) when a zone is entered
        self.sparkle = 0                     # ticks of sparkle after a star
        self.fresh = None                    # (ticks left, tag): the newest piece, bold
        self.zone_seen = 1
        self.arrows = []                     # [x, row, dir, range]
        self.want_jump = False
        self.want_shot = False
        self.cool = 0
        self.tick = 0
        self.cam = 0.0
        self.stars = 0
        self.taken = []                      # "1".."8" in the order taken
        self.over = None                     # dead | won | quit
        self.dying = None
        self.ending = None                   # the vulture's frame counter
        self.zone_max = 1
        self.hurts = []                      # (tick, cause): the sim's post-mortem
        self.vulture = float(self.hero.x + 12)
        self.events = []                     # sound names raised this tick: star hit jump vulture dead won
        self.sweep = None                    # the vulture's sweep: (ticks left, direction, x)
        self.sweep_cool = 0                  # ticks until he answers again
        self.chased = 0                      # bats chased away this run

    # -- input -----------------------------------------------------------
    def key(self, k):
        """d a (run right / left, until s), s (stop), w (jump), f (fire),
        v (call the vulture: he sweeps the canopy and the bats flee)."""
        h = self.hero
        if self.first_key is None:
            self.first_key = self.tick
        if k == "d":
            h.run, h.facing = 1, 1
        elif k == "a":
            h.run, h.facing = -1, -1
        elif k == "s":
            h.run = 0
        elif k == "w":
            self.want_jump = True
        elif k == "f":
            self.want_shot = True
        elif k == "v" and self.sweep is None and self.sweep_cool == 0:
            self.sweep, self.sweep_cool = (22, h.facing, h.x - 3 * h.facing), 70   # from just behind the hero, ahead
            self.events.append("vulture")

    # -- one tick --------------------------------------------------------
    def step(self):
        self.tick += 1
        if self.over:
            return
        if self.ending is not None:
            if self.ending == 0:
                self.events.append("won")
                self.points += self.hero.hp * 50 + max(0, 2400 - self.tick) // 2     # the hero left standing, and the haste
            self.ending += 1
            if self.ending >= 40:
                self.over = "won"
            return
        if self.dying is not None:
            self.dying -= 1
            if self.dying <= 0:
                self.over = "dead"
            return
        h, w = self.hero, self.world
        in_water = w.floor[h.col] == WATER and h.y >= GROUND - 0.5
        if self.want_jump and h.ground:
            h.vy = JUMP_V
            h.ground = False
            self.events.append("jump")
        self.want_jump = False
        if self.want_shot and self.cool == 0 and len(self.arrows) < 3:
            self.arrows.append([h.x + h.facing, h.row, h.facing, 26])
            self.cool = 5
        self.want_shot = False
        if self.cool:
            self.cool -= 1
        # horizontal: the run state, or a knockback
        if h.knock:
            vx = h.knock_d * 1.2
            h.knock -= 1
        else:
            vx = h.run * (WADE if in_water else RUN) * self.pace
        nx = h.x + vx
        if not w.solid(int(round(nx)), h.row, self.stars):
            h.x = max(1.0, min(WORLD_W - 2.0, nx))
        elif h.ground and int(round(nx)) in w.logs and not w.gate_shut(int(round(nx))):
            h.vy, h.ground = JUMP_V, False   # ran into a log: hop it, keep running
        # vertical
        h.vy = min(2.0, h.vy + GRAVITY)
        ny = h.y + h.vy
        floor = w.stand_row(h.col)
        if h.vy >= 0 and ny >= floor:
            h.y, h.vy, h.ground = float(floor), 0.0, True    # landing, or a bank stepped up onto
        else:
            h.y, h.ground = max(0.0, ny), False
        in_water = w.floor[h.col] == WATER and h.y >= GROUND - 0.5
        # damage: water, briars
        if in_water:
            h.wet += 1
            if h.wet % 20 == 0:
                self._hurt(1, 0, "water")
        else:
            h.wet = 0
        if h.row == LANE and h.col in w.briars:
            self._hurt(1, -h.facing, "briar")
        if h.immune:
            h.immune -= 1
        # the oncas
        for o in w.oncas:
            if not o["alive"]:
                continue
            d = h.x - o["x"]
            if abs(d) < 12:
                if not o["seen"]:
                    o["seen"], o["tell"] = True, 8       # it sees the hero: a beat of warning, then the charge
                if o["tell"]:
                    o["tell"] -= 1
                    o["d"] = 1 if d > 0 else -1
                else:
                    o["x"] += (o["charge"] if d > 0 else -o["charge"]) * self.pace
                    o["d"] = 1 if d > 0 else -1
            else:
                o["seen"] = False
                o["x"] += o["d"] * 0.4 * self.pace
            if o["x"] <= o["x0"]:
                o["x"], o["d"] = float(o["x0"]), 1
            elif o["x"] >= o["x1"]:
                o["x"], o["d"] = float(o["x1"]), -1
            if abs(o["x"] - h.x) < 1.0 and h.row == LANE:
                self._hurt(2, 1 if h.x >= o["x"] else -1, "onca")
        # the bats
        if self.sweep_cool:
            self.sweep_cool -= 1
        if self.sweep:
            n, d, x = self.sweep
            x1 = x + d * 2.5
            for b in w.bats:
                if b["alive"] and b["y"] <= 1.5 and min(x, x1) - 1.5 <= b["x"] <= max(x, x1) + 1.5:
                    b["alive"], b["flee"] = False, 10
                    self.chased += 1
                    self.points += 10
            self.sweep = (n - 1, d, x1) if n > 1 else None
            if self.sweep is None:
                self.vulture = x1
        for b in w.bats:
            if b.get("flee"):
                b["flee"] -= 1
                b["x"] += 1.5 * (1 if b["x"] >= h.x else -1)
            if not b["alive"]:
                continue
            b["t"] += 1
            if b["dive"] is None:
                b["x"] = b["ax"] + 4 * math.sin(b["t"] / 10.0)
                b["y"] = float(CANOPY)
                b["rest"] = max(0, b["rest"] - 1)
                if abs(b["x"] - h.x) < 9 and not b["rest"]:
                    b["dive"], b["aim"] = 0, (h.x, h.y)     # a swoop at where the hero is: keep moving
            else:
                b["dive"] += 1
                if b["dive"] <= 8:
                    b["x"] += max(-0.9, min(0.9, b["aim"][0] - b["x"]))
                    b["y"] += max(-0.6, min(0.6, b["aim"][1] - b["y"]))
                elif b["dive"] <= 20:
                    b["x"] += max(-0.6, min(0.6, b["ax"] - b["x"]))
                    b["y"] += max(-0.5, min(0.5, CANOPY - b["y"]))
                else:
                    b["dive"], b["rest"] = None, (50 if self.zone >= 6 else 80)
            if abs(b["x"] - h.x) < 1.0 and abs(b["y"] - h.y) < 0.8:
                self._hurt(1, 1 if h.x >= b["x"] else -1, "bat")
        # the arrows
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
            if ay == LANE:
                for bx in [x for x in w.briars if lo <= x <= hi]:
                    w.briars.discard(bx)
            for o in w.oncas:
                if o["alive"] and ay == LANE and lo <= o["x"] <= hi:
                    o["alive"], hit = False, True
                    self.points += 30
            for b in w.bats:
                if b["alive"] and lo <= b["x"] <= hi and abs(b["y"] - ay) < 0.8:
                    b["alive"], hit = False, True
                    self.points += 20
            if not hit:
                keep.append(a)
        self.arrows = keep
        # the heals
        for hl in w.heals:
            if not hl["taken"] and abs(hl["x"] - h.x) < 1.0 and h.row == LANE and h.hp < HP_MAX:
                hl["taken"] = True
                h.hp = min(HP_MAX, h.hp + 2)
                self.events.append("heal")
        # the stars
        for s in w.stars:
            if not s["taken"] and abs(s["x"] - h.x) < 1.3 and abs(AIR1 - h.y) < 0.9:
                s["taken"] = True
                self.stars += 1
                self.points += 100
                self.taken.append(str(s["n"]))
                self.sparkle, self.fresh = 12, (40, str(s["n"]))
                self.events.append("star")
        # the palm
        if h.col >= w.palm_x - 2 and self.stars >= 8:
            self.ending = 0
        if h.x > self.far:
            self.points += int(h.x // 5) - int(self.far // 5)     # a point every five columns of new ground
            self.far = h.x
        z = w.zone_of(h.col)
        self.zone_max = max(self.zone_max, z)
        if z != self.zone_seen:
            self.zone_seen, self.callout = z, (45, z)
        for name in ("callout", "fresh"):
            v = getattr(self, name)
            if v:
                setattr(self, name, (v[0] - 1, v[1]) if v[0] > 1 else None)
        if self.sparkle:
            self.sparkle -= 1
        # the vulture glides ahead of the hero (unless he is sweeping)
        if self.sweep is None:
            self.vulture += (h.x + 10 * h.facing + 5 * math.sin(self.tick / 17.0) - self.vulture) * 0.08
        # the camera
        lead = self.cols // 3 if h.facing > 0 else 2 * self.cols // 3
        target = max(0.0, min(float(WORLD_W - self.cols), h.x - lead))
        self.cam += (target - self.cam) * 0.25
        if h.hp <= 0 and self.dying is None:
            self.dying = 8
            self.events.append("dead")

    def _hurt(self, n, knock_dir, cause):
        h = self.hero
        if h.immune:
            return
        h.hp -= n
        h.immune = 15
        self.hurts.append((self.tick, cause))
        self.events.append("hit")
        if knock_dir:
            h.knock, h.knock_d = 4, knock_dir

    @property
    def zone(self):
        return self.world.zone_of(self.hero.col)

    @property
    def score(self):
        return self.points * self.night

    @property
    def at_palm(self):
        return self.hero.col >= self.world.palm_x - 2

    # -- the picture -----------------------------------------------------
    def _weather(self, put, rows):
        """The zone's decoration: streaks in the wind, drops in the rain, a
        flicker in the thunder, a bolt and a flash in the lightning, a few
        stars over the strength. Returns True on a flash tick."""
        z, t, cols = self.zone, self.tick, self.cols
        if z == 4:                                   # the wind: streaks blowing left
            for k in range(cols // 9):
                put((AIR2 if k % 2 else AIR1) + 1, (k * 9 - t * 2) % cols, "-" if k % 3 else "~", (CYAN, "d"))
        elif z == 5:                                 # the rain: drops falling
            for k in range(cols // 5):
                c = (k * 5 + (k * 7919) % 5) % cols
                put((AIR2 if (t + k) % 2 else AIR1) + 1, c, "'" if (t + k) % 2 else ".", (BLUE, ""))
        elif z == 6:                                 # the thunder: the canopy flickers
            return t % 90 < 2
        elif z == 7:                                 # the lightning: a bolt every few seconds
            if t % 70 < 3:
                bx = (self.seed * 31 + (t // 70) * 47) % max(1, cols - 4) + 2
                for row, ch in ((AIR2, "\\"), (AIR1, "/"), (LANE, "\\")):
                    put(row + 1, bx + (0 if row != AIR1 else 1), ch, (YELLOW, "b"))
                return t % 70 == 0
        elif z == 8:                                 # the strength: the first stars out
            for k in range(cols // 10):
                if (t // 6 + k) % 3 == 0:
                    put(AIR2 + 1, (k * 10 + 3) % cols, ".", (YELLOW, "d"))
        return False

    def frame(self, tl):
        """Nine rows of (char, attr): the status, the six world rows, the
        memory in English (two rows)."""
        w, h, cols = self.world, self.hero, self.cols
        rows = [[(" ", PLAIN)] * cols for _ in range(9)]
        cam = int(round(self.cam))

        def put(r, c, s, attr=PLAIN):
            for i, ch in enumerate(s):
                if 0 <= c + i < cols:
                    rows[r][c + i] = (ch, attr)

        def wput(row, wx, ch, attr=PLAIN):
            put(row + 1, wx - cam, ch, attr)

        def centre(row, s, attr):
            put(row + 1, max(0, (cols - len(s)) // 2), s, attr)

        # the status
        hp = max(0, h.hp)
        zn = fold(ZONE_NAMES[self.zone - 1][0])
        put(0, 1, "%s lua" % MARK, (WHITE, "b"))
        put(0, 12, "HP " + "[" + G("hp_on") * hp + G("hp_off") * (HP_MAX - hp) + "]",
            (GREEN if hp > 5 else YELLOW if hp > 2 else RED, "b"))
        put(0, 27, "* %d/8" % self.stars, (YELLOW, "b"))
        put(0, 35, "V", (WHITE, "b") if self.sweep_cool == 0 else (DEFAULT, "d"))
        put(0, 38, "zone %d/8 %s" % (self.zone, zn), PLAIN)
        right = "night %d   score %d   %s" % (self.night, self.score, moon_line(self.day))
        if cols >= 38 + len(zn) + 12 + len(right) + 2:
            put(0, cols - len(right) - 1, right, (CYAN, ""))
        elif cols >= 38 + len(zn) + 12 + 24:
            put(0, cols - 23, "night %d  score %5d" % (self.night, self.score), (CYAN, ""))
        # the weather of the zone, under everything else
        flash = self._weather(put, rows)
        # the forest, column by column
        for sx in range(cols):
            wx = cam + sx
            if wx < 0 or wx >= WORLD_W:
                continue
            if w.canopy[wx]:
                put(CANOPY + 1, sx, G("canopy"), (WHITE, "b") if flash else (GREEN, ""))
            if w.under[wx]:
                put(AIR2 + 1, sx, G("canopy"), (WHITE, "b") if flash else (GREEN, "d"))
            kind = w.floor[wx]
            if kind == WATER:
                put(GROUND + 1, sx, G("water"), (BLUE, "b"))
                put(SOIL + 1, sx, G("water"), (BLUE, ""))
            elif kind == STONE:
                put(GROUND + 1, sx, G("log"), (YELLOW, ""))
                put(SOIL + 1, sx, G("water"), (BLUE, ""))
            else:
                put(GROUND + 1, sx, G("ground"), (DEFAULT, "d"))
                put(SOIL + 1, sx, G("soil"), (DEFAULT, "d"))
            if wx in w.posts and wx > START_W:
                shut = w.gate_shut(wx)
                for row in (AIR2, AIR1, LANE, GROUND):
                    put(row + 1, sx, "|", (WHITE, "b") if shut else (DEFAULT, "d"))
            if wx in w.logs:
                put(LANE + 1, sx, G("log"), (YELLOW, ""))
            if wx in w.briars:
                put(LANE + 1, sx, "x", (RED, ""))
        # the palm
        for row in (AIR2, AIR1, LANE):
            for c in (w.palm_x, w.palm_x + 1):
                wput(row, c, "|", (GREEN, "b" if self.stars >= 8 else ""))
        for c in range(w.palm_x - 2, w.palm_x + 4):
            wput(CANOPY, c, G("canopy"), (GREEN, "b"))
        # stars, fauna, arrows
        blink = (self.tick // 4) % 2 == 0
        for s in w.stars:
            if not s["taken"]:
                wput(AIR1, s["x"], "*", (YELLOW, "b" if blink else ""))
        for o in w.oncas:
            if o["alive"]:
                wput(LANE, int(round(o["x"])), "M", (RED, "b"))
                if o["tell"]:
                    wput(AIR1, int(round(o["x"])), "!", (RED, "b" if self.tick % 2 else ""))
        for hl in w.heals:
            if not hl["taken"]:
                wput(LANE, hl["x"], "+", (GREEN, "b"))
        for b in w.bats:
            if b["alive"]:
                wput(int(round(b["y"])), int(round(b["x"])), "v", (MAGENTA, "b"))
            elif b.get("flee"):
                wput(CANOPY, int(round(b["x"])), "^", (MAGENTA, ""))
        for a in self.arrows:
            wput(a[1], int(round(a[0])), ">" if a[2] > 0 else "<", (WHITE, "b"))
        # the vulture, the hero, the ending
        hr, hc = h.row, h.col - cam
        wings = "-V-" if self.tick % 12 == 0 else "~V~"
        if self.ending is None:
            if self.sweep:
                put(CANOPY + 1, int(round(self.sweep[2])) - cam - 1, "-V-" if self.tick % 2 else "~V~", (WHITE, "b"))
            else:
                put(CANOPY + 1, int(round(self.vulture)) - cam - 1, wings, (WHITE, "b"))
            if self.dying is not None:
                put(hr + 1, hc, "x", (RED, "b"))
            elif not (h.immune and self.tick % 2):
                put(hr + 1, hc, "@", (WHITE, "b"))
        else:
            e = self.ending
            if e <= 10:                                   # the dive to the hero
                vr = min(AIR1, e // 4)
                put(vr + 1, hc - 1, wings, (WHITE, "b"))
                put(hr + 1, hc, "@", (WHITE, "b"))
            else:                                         # up and away, stars behind
                vr = max(CANOPY, AIR1 - (e - 10) // 5)
                put(vr + 1, hc - 1 + (e - 10), wings, (WHITE, "b"))
                put(vr + 1, hc + (e - 10), "@", (WHITE, "b"))
                r = self.rng
                for _ in range(min(e, 30)):
                    put(r.randint(CANOPY, LANE) + 1, r.randint(0, cols - 1), "*", (YELLOW, "b" if r.random() < 0.5 else ""))
        # feedback: the sparkle, the zone callout, the hint before the first key
        if self.sparkle:
            r = random.Random(self.tick)
            for _ in range(6):
                put(r.choice((AIR2, AIR1)) + 1, hc + r.randint(-4, 4), r.choice("*.+"), (YELLOW, "b"))
        if self.callout and self.ending is None:
            centre(AIR2, "-- %s --" % fold(ZONE_NAMES[self.callout[1] - 1][0]), (WHITE, "b"))
        if self.first_key is None and self.ending is None:
            centre(AIR2, "the forest of O Urubu-Rei e a Lua", (WHITE, "b"))
            centre(AIR1, "d runs   w jumps   Space fires   v the vulture   m mute   q leaves", (CYAN, ""))
        # the memory, in English; the newest piece bold for a moment
        taken = set(self.taken)
        fresh = tl.get(self.fresh[1], ("", ""))[0] if self.fresh else None
        for i, ln in enumerate(textwrap.wrap(memory(tl, taken, 0), cols - 4)[:2]):
            put(7 + i, 2, ln, (WHITE, ""))
            if fresh and fold(fresh) in ln:
                put(7 + i, 2 + ln.index(fold(fresh)), fold(fresh), (YELLOW, "b"))
        return rows


# ------------------------------------------------------------ the pilot --
class Pilot:
    """The sim's player: runs toward the lowest star it lacks (then the
    palm), jumps at water, logs, briars and under a star, fires at what
    stands or flies ahead, and jumps when it has been stuck."""

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
        jump = False
        for i in (1, 2):
            x = h.col + d * i
            if 0 <= x < WORLD_W:
                if w.floor[x] == WATER and w.floor[h.col] != WATER and i == 1:
                    jump = True
                if x in w.logs and h.col not in w.logs and i == 1:
                    jump = True
                if x in w.briars and i == 1:
                    jump = True
        for s in want:
            dx = abs(s["x"] - h.x)
            if dx < 1.0 and h.y > AIR1:
                jump = True
                out = ["s"]
            elif dx < 4 and (s["x"] - h.x) * d > 0:
                jump = dx <= 3.5
        if self.last_x is not None and abs(h.x - self.last_x) < 0.05 and h.ground:
            self.stuck += 1
            if self.stuck >= 3:
                jump, self.stuck = True, 0
        else:
            self.stuck = 0
        self.last_x = h.x
        if jump and h.ground:
            out.append("w")
        for o in w.oncas:
            if o["alive"] and (o["x"] - h.x) * d > 0 and abs(o["x"] - h.x) < 12:
                out.append("f")
                if abs(o["x"] - h.x) < 3 and h.ground:
                    out.append("w")
        for b in w.bats:
            if b["alive"] and abs(b["x"] - h.x) < 8 and abs(b["y"] - h.y) < 1.5:
                out.append("f")
            if b["alive"] and b["y"] <= 1.5 and (b["x"] - h.x) * d > 0 and abs(b["x"] - h.x) < 14 and g.sweep_cool == 0:
                out.append("v")
        return out


def sim(seed, tape, day=None, night=1):
    """Headless: a fixed seed and a key tape (per tick, repeating: a d s w
    f v .) or `auto`, the Pilot. Returns the finished Game."""
    g = Game(80, seed=seed, day=day, night=night)
    pilot = Pilot(g) if tape == "auto" else None
    for i in range(6000):
        if pilot:
            for k in pilot.keys():
                g.key(k)
        else:
            k = tape[i % len(tape)]
            if k in "adswfv":
                g.key(k)
        g.step()
        g.events.clear()
        if g.over:
            break
    g.over = g.over or "end"
    return g


def sim_line(g):
    return "zone %d stars %d over %s hp %d ticks %d score %d night %d" % (
        g.zone_max, g.stars, g.over, max(0, g.hero.hp), g.tick, g.score, g.night)


# ----------------------------------------------------------- the letters --
# a five-row block font for the two endings; the console gets # for the block
FONT = {
    "A": (" ███ ", "█   █", "█████", "█   █", "█   █"),
    "C": (" ████", "█    ", "█    ", "█    ", " ████"),
    "E": ("█████", "█    ", "████ ", "█    ", "█████"),
    "G": (" ████", "█    ", "█  ██", "█   █", " ████"),
    "M": ("█   █", "██ ██", "█ █ █", "█   █", "█   █"),
    "O": (" ███ ", "█   █", "█   █", "█   █", " ███ "),
    "R": ("████ ", "█   █", "████ ", "█  █ ", "█   █"),
    "S": (" ████", "█    ", " ███ ", "    █", "████ "),
    "U": ("█   █", "█   █", "█   █", "█   █", " ███ "),
    "V": ("█   █", "█   █", "█   █", " █ █ ", "  █  "),
    " ": ("   ", "   ", "   ", "   ", "   "),
}


def letters(word):
    """Five rows of block letters for WORD (the FONT's letters only)."""
    rows = []
    for i in range(5):
        rows.append(" ".join(FONT[ch][i] for ch in word).replace("█", G("block")))
    return rows


ENDINGS = {"dead": ("GAME OVER", ((YELLOW, "b"), (YELLOW, "b"), (YELLOW, ""), (RED, "b"), (RED, "b"))),
           "won": ("SUCCESS", ((GREEN, "b"), (GREEN, "b"), (YELLOW, "b"), (YELLOW, "b"), (BLUE, "b")))}


def ending_rows(g, tl, kind):
    """The band with the six world rows replaced by the ending's letters."""
    rows = g.frame(tl)
    cols = g.cols
    word, colours = ENDINGS[kind]
    art = letters(word)
    left = max(0, (cols - len(art[0])) // 2)
    for i in range(6):
        rows[1 + i] = [(" ", PLAIN)] * cols
    for i, (ln, attr) in enumerate(zip(art, colours)):
        for j, ch in enumerate(ln):
            if ch != " " and left + j < cols:
                rows[1 + i][left + j] = (ch, attr)
    return rows


# ------------------------------------------------------------ the sound --
RATE = 22050
SOUNDS = {                       # (Hz, ms) per note, 0 Hz a rest: square waves, 8-bit
    "star": ((880, 60), (1319, 90)),
    "hit": ((196, 60), (147, 110)),
    "jump": ((523, 35), (784, 45)),
    "vulture": ((659, 45), (880, 45), (1175, 90)),
    "heal": ((659, 50), (880, 90)),
    "dead": ((523, 140), (440, 140), (349, 140), (262, 420)),
    "won": ((523, 110), (659, 110), (784, 110), (1047, 160), (0, 40), (1047, 110), (1319, 380)),
}


def synth(notes):
    """A WAV of square waves, 8-bit mono, each note decaying: the 8-bit
    sound of the thing. stdlib only."""
    frames = bytearray()
    for hz, ms in notes:
        n = int(RATE * ms / 1000)
        period = RATE / hz if hz else 0
        for i in range(n):
            if not hz:
                frames.append(128)
                continue
            on = (i % period) < period / 2
            amp = 36 * (1.0 - 0.6 * i / n)
            frames.append(128 + int(amp if on else -amp))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wv:
        wv.setnchannels(1)
        wv.setsampwidth(1)
        wv.setframerate(RATE)
        wv.writeframes(bytes(frames))
    return buf.getvalue()


class Sound:
    """The sounds, played through the OS's own player -- afplay on macOS,
    aplay or paplay on Linux -- from WAVs synthesized once into the state
    cache; without a player, the two endings ring the terminal bell. m
    mutes; SPARK_LUA_MUTE=1 starts muted."""

    def __init__(self, out):
        self.out = out
        self.mute = os.environ.get("SPARK_LUA_MUTE") == "1"
        self.player = None
        for cmd in (("afplay",) if IS_MAC else ("aplay", "-q"), ("paplay",)):
            if shutil.which(cmd[0]):
                self.player = list(cmd)
                break
        self.paths = {}
        self.procs = []

    def _path(self, name):
        if name not in self.paths:
            os.makedirs(SOUND_DIR, mode=0o700, exist_ok=True)
            path = os.path.join(SOUND_DIR, name + ".wav")
            if not os.path.exists(path):
                with open(path, "wb") as f:
                    f.write(synth(SOUNDS[name]))
            self.paths[name] = path
        return self.paths[name]

    def play(self, name):
        if self.mute or name not in SOUNDS:
            return
        self.procs = [p for p in self.procs if p.poll() is None]
        if self.player is None or len(self.procs) > 3:
            if name in ("dead", "won"):
                self.out.write("\a")
                self.out.flush()
            return
        try:
            self.procs.append(subprocess.Popen(self.player + [self._path(name)], stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        except OSError:
            self.player = None


# ------------------------------------------------------------- the band --
class Band:
    """Eleven lines drawn below the prompt and redrawn in place: no
    alternate screen, so the last picture stays in the scrollback. A row is
    written only when it changed; SGR codes only where the attribute
    changes; eight colours, bold, dim, nothing else."""

    N = 9

    def __init__(self, out):
        self.out = out
        self.prev = [None] * self.N

    def open(self):
        self.out.write("\033[?25l" + "\n" * self.N + "\033[%dA" % self.N)
        self.out.flush()

    @staticmethod
    def render(row):
        parts, cur = [], None
        for ch, attr in row:
            if attr != cur:
                codes = []
                if attr[0]:
                    codes.append(str(30 + attr[0]))
                if attr[1] == "b":
                    codes.append("1")
                elif attr[1] == "d":
                    codes.append("2")
                parts.append("\033[0m" + ("\033[%sm" % ";".join(codes) if codes else ""))
                cur = attr
            parts.append(ch)
        return ("".join(parts) + "\033[0m").rstrip()

    def draw(self, rows):
        out = []
        for i, row in enumerate(rows):
            s = self.render(row)
            if s != self.prev[i]:
                out.append("\r" + s + "\033[K")
                self.prev[i] = s
            out.append("\n")
        out.append("\033[%dA" % self.N)
        self.out.write("".join(out))
        self.out.flush()

    def close(self):
        self.out.write("\n" * self.N + "\033[?25h")
        self.out.flush()


def read_keys(fd):
    """The bytes waiting on fd as the game's letters: a d s w f p q; arrows
    as their letters, whether the terminal sends CSI or SS3 forms."""
    try:
        data = os.read(fd, 64)
    except OSError:
        return []
    keys, i = [], 0
    arrows = {b"A": "w", b"B": "s", b"C": "d", b"D": "a"}
    while i < len(data):
        b = data[i:i + 1]
        if b == b"\x1b" and i + 2 < len(data) and data[i + 1:i + 2] in (b"[", b"O") and data[i + 2:i + 3] in arrows:
            keys.append(arrows[data[i + 2:i + 3]])
            i += 3
            continue
        keys.append({b"a": "a", b"d": "d", b"s": "s", b"w": "w", b" ": "f", b"f": "f", b"v": "v", b"m": "m",
                     b"p": "p", b"q": "q", b"\x03": "q"}.get(b.lower()))
        i += 1
    return [k for k in keys if k]


def play(st, tl):
    import termios
    import tty
    size = shutil.get_terminal_size((80, 24))
    if size.columns < 60 or size.lines < Band.N + 2:
        say("%s lua: a terminal of 60x%d at least (this one is %dx%d)" % (MARK, Band.N + 2, size.columns, size.lines))
        return 2
    g = Game(size.columns, day=None, night=st.get("night_pick") or min(NIGHTS, st["nights"] + 1))
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    band = Band(sys.stdout)
    sound = Sound(sys.stdout)
    paused = False
    try:
        tty.setcbreak(fd)
        band.open()
        frame_t = 1.0 / FPS
        while not g.over:
            t0 = time.monotonic()
            if select.select([fd], [], [], 0)[0]:
                for k in read_keys(fd):
                    if k == "q":
                        g.over = "quit"
                    elif k == "p":
                        paused = not paused
                    elif k == "m":
                        sound.mute = not sound.mute
                    elif not paused:
                        g.key(k)
            if g.over:
                break
            if not paused:
                g.step()
                for name in g.events:
                    sound.play(name)
                g.events.clear()
            cols = shutil.get_terminal_size((80, 24)).columns
            if cols != g.cols:
                g.cols = max(60, min(cols, 200))
                band.prev = [None] * Band.N
            rows = g.frame(tl)
            if paused:
                for j, ch in enumerate("paused -- p goes on, q leaves"):
                    rows[AIR1 + 1][2 + j] = (ch, (WHITE, "b"))
            band.draw(rows)
            rest = frame_t - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)
        if g.over in ("dead", "won"):
            band.draw(ending_rows(g, tl, g.over))
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.1)[0]:
                    os.read(fd, 64)
                    break
    finally:
        band.close()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if g.over == "quit":
        _remember(g, st)
        say("%s lua -- left in zone %d, %s; * %d/8" % (MARK, g.zone_max, fold(ZONE_NAMES[g.zone_max - 1][0]), g.stars))
        return 0
    finish(g, st, tl)
    return 0


# ------------------------------------------------------------ the shell --
def _remember(g, st):
    """The best run, the nights won, the top five scores -- kept."""
    b = st["best"]
    if (g.zone_max, g.stars) > (b.get("zone", 0), b.get("stars", 0)):
        st["best"] = {"zone": g.zone_max, "stars": g.stars}
    if g.over == "won":
        st["won"] = True
        st["nights"] = max(st.get("nights", 0), g.night)
    if g.over in ("won", "dead") and g.score > 0:
        rows = st.get("scores", []) + [{"score": g.score, "night": g.night, "stars": g.stars,
                                        "date": date.today().isoformat(), "won": g.over == "won"}]
        st["scores"] = sorted(rows, key=lambda r: -r.get("score", 0))[:5]
    st.pop("night_pick", None)
    save_state(st)


def boxed(paragraphs, width=66):
    """An ASCII box around paragraphs (a blank line between them, each
    wrapped to width): + - | draw on every terminal and console."""
    inner = []
    for para in paragraphs:
        if inner and not (para.startswith(" ") and inner[-1].startswith(" ")) and not para.startswith("    "):
            inner.append("")
        elif inner and para.startswith("    ") and not inner[-1].startswith(" ") and not inner[-1].endswith(":"):
            inner.append("")
        inner.extend(textwrap.wrap(para, width) if not para.startswith(" ") else [para])
    w = max(len(ln) for ln in inner) + 4
    out = ["+" + "-" * w + "+", "|" + " " * w + "|"]
    out += ["|  %-*s  |" % (w - 4, ln) for ln in inner]
    out += ["|" + " " * w + "|", "+" + "-" * w + "+"]
    return out


def finish(g, st, tl):
    """After a run, at the shell: one box -- the outcome, the memory as it
    stands, the tale's line; a win adds the ending, the palette and the
    one line that keeps the joke."""
    path = None
    if g.over == "won":
        path = write_palette()       # before a word is printed: a closed pipe must not lose the prize
    _remember(g, st)
    taken = set(g.taken)
    zone = fold(ZONE_NAMES[g.zone_max - 1][0])
    board = ["Top runs:"] + ["    %d. %5d   night %d   * %d/8   %s%s" % (
        i + 1, r["score"], r["night"], r["stars"], r["date"], "   crossed" if r.get("won") else "")
        for i, r in enumerate(st.get("scores", []))]
    if g.over == "won":
        again = ("Night %d awaits: faster, and every point counts %d times." % (g.night + 1, g.night + 1)
                 if g.night < NIGHTS else "The last night. The forest has nothing left to hide.")
        paras = ["SUCCESS -- eight stars, the forest crossed.  Score %d (night %d)." % (g.score, g.night),
                 memory(tl, taken, 0),
                 fold(tl.get("fim", ("", ""))[0]),
                 CARD,
                 "A palette of your own, in the colours of the flag:",
                 "    spark theme %s" % PALETTE_NAME,
                 again] + board
    else:
        paras = ["GAME OVER in zone %d, %s.  * %d/8   Score %d (night %d)." % (
                     g.zone_max, zone, g.stars, g.score, g.night),
                 memory(tl, taken, 0),
                 fold(tl.get("queda", ("", ""))[0])] + board
    say()
    for ln in boxed(paras):
        say("  " + ln)
    say()


USAGE = """%s lua -- the forest, a bow, eight stars, a moon

  spark lua                 d / Right runs, a / Left runs back, s / Down stops,
                            w / Up jumps, Space fires an arrow, v calls the
                            king vulture down on the bats, m mutes, p pauses,
                            q leaves (SPARK_LUA_MUTE=1 starts muted)
  spark lua --night N       play night N (1-6): faster, more points; the next
                            night opens with each win
  spark lua --scores        the top five runs
  spark lua --moon [DATE]   tonight's moon, or a date's (YYYY-MM-DD)
  spark lua --reset         forget the best run and the scores
""" % MARK


def cmd_lua(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    tl = tale()
    if os.path.exists(os.path.join(CONFIG_DIR, "themes", PALETTE_NAME + ".env")):
        write_palette()                      # a prize written before the logo line existed gets it
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
    if args and args[0] == "--scores":
        say("%s lua -- top runs (nights won: %d)" % (MARK, st["nights"]))
        for i, r in enumerate(st["scores"]):
            say("  %d. %5d   night %d   * %d/8   %s%s" % (i + 1, r["score"], r["night"], r["stars"], r["date"],
                                                          "   crossed" if r.get("won") else ""))
        if not st["scores"]:
            say("  none yet")
        return 0
    if args and args[0] == "--night":
        st["night_pick"] = max(1, min(NIGHTS, int(args[1]) if len(args) > 1 and args[1].isdigit() else 1))
        args = args[2:]
    if args and args[0] == "--sim":
        seed = int(args[1]) if len(args) > 1 else 1
        tape = args[2] if len(args) > 2 else "auto"
        day = date.fromisoformat(args[3]) if len(args) > 3 else None
        g = sim(seed, tape, day, st.get("night_pick") or 1)
        say(sim_line(g))
        finish(g, st, tl)
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        say("%s lua: a terminal, please -- this one runs in the dark" % MARK)
        say("  %s" % fold(tl.get("abertura", ("", ""))[0]))
        return 2
    return play(st, tl)
