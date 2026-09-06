# lua.py -- the egg. `spark lua` runs a small ASCII runner: the hero of
# O Urubu-Rei e a Lua runs the night, jumping trunks and stones while the
# king vulture glides overhead, and every `*` he takes is one line of the
# tale (home/.config/spark/tale). Eight of them end it: the bird carries
# him up, the stars come out, a palette of your own lands in
# ~/.config/spark/themes/ and a card explains the word you have been typing.
#
# This is the ONE feature deliberately outside the landing rule: no help
# line, no cheatsheet row, no check row, no page, no AGENTS.md mention.
# The completion files name it in a comment (the drift guard in
# tests/smoke.py accepts that on purpose) and tests/smoke.py exercises it
# through --sim and a pty. Do not document it further; it is meant to be
# found, not read about. The moon is real: tonight's phase comes from the
# date (no network) and sets how far ahead the track is lit.
#
# Text-first still holds: without a tty it prints one line and the tale's
# opening, never a frame; every glyph is ASCII; the passages fold to ASCII
# on the console. stdlib only, no curses.

import json
import math
import os
import random
import select
import sys
import time
import unicodedata
from datetime import date

from . import ASCII, CONFIG_DIR, MARK, REPO, STATE_DIR, say

STATE_FILE = os.path.join(STATE_DIR, "lua")
TALE_FILES = (os.path.join(CONFIG_DIR, "tale"), os.path.join(REPO, "home", ".config", "spark", "tale"))
PALETTE_NAME = "canarinho"
PALETTE = (
    "# Canarinho -- spark's own, written by the one who ran the night (MIT, like spark)",
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
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'").replace("\u2026", "...")
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
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
        st.setdefault("got", [])
        st.setdefault("best", 0)
        st.setdefault("won", False)
        return st
    except (OSError, ValueError):
        return {"got": [], "best": 0, "won": False}


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


# ------------------------------------------------------------- the game --
HERO_X = 6
GROUND = 8                       # the row of `_`; the hero stands on GROUND - 1
JUMP = (1, 2, 3, 3, 2, 1)        # height per tick after the key
ROCK, TRUNK, SPARK = "^", "|", "*"
FPS = 15.0
SHOW_TICKS = 45                  # a taken passage stays in the footer this long


class Game:
    def __init__(self, width, seed=None, day=None, got=None):
        self.w = max(60, min(width, 100))
        self.rng = random.Random(seed)
        self.p = phase(day)
        self.lit = 20 + int((self.w - HERO_X - 20) * illumination(self.p))
        self.got = list(got or [])
        self.items = []          # [x (float), kind]
        self.next_x = float(self.w + 10)
        self.since_spark = 0
        self.h = 0               # the hero's height
        self.air = -1            # index into JUMP, -1 on the ground
        self.speed = 0.6
        self.dist = 0.0
        self.tick = 0
        self.taken = []          # passages taken this run, in order
        self.show = None         # (ticks left, tag)
        self.over = None         # "hit" | "won" | "quit"
        self.bird_x = float(self.w - 12)
        self.bird_dx = -0.2
        self.dive = None         # the ending's frame counter

    # -- the world ---------------------------------------------------------
    def spawn(self):
        while self.next_x < self.w + 2:
            self.since_spark += 1
            if self.since_spark >= 3 and len(self.got) < 8:
                kind, self.since_spark = SPARK, 0
            else:
                kind = ROCK if self.rng.random() < 0.6 else TRUNK
            self.items.append([self.next_x, kind])
            self.next_x += 14 + self.rng.randint(0, 16)

    def jump(self):
        if self.air < 0:
            self.air = 0

    def step(self, key=None):
        """One tick. key: 'j' jump, None nothing."""
        self.tick += 1
        if key == "j":
            self.jump()
        if self.air >= 0:
            self.h = JUMP[self.air]
            self.air = self.air + 1 if self.air + 1 < len(JUMP) else -1
        else:
            self.h = 0
        for it in self.items:
            it[0] -= self.speed
        self.next_x -= self.speed
        self.dist += self.speed
        self.speed = min(1.4, 0.6 + int(self.dist) // 100 * 0.05)
        self.bird_x += self.bird_dx
        if self.bird_x < HERO_X + 8 or self.bird_x > self.w - 13:
            self.bird_dx = -self.bird_dx
        if self.show:
            self.show = (self.show[0] - 1, self.show[1]) if self.show[0] > 1 else None
        # what reaches the hero's column this tick
        keep = []
        for x, kind in self.items:
            if x < -2:
                continue
            if x <= HERO_X < x + self.speed or int(round(x)) == HERO_X:
                if kind == SPARK:
                    if self.h >= 2:
                        self.take()
                        continue
                elif kind == ROCK and self.h == 0 or kind == TRUNK and self.h <= 1:
                    self.over = "hit"
            keep.append([x, kind])
        self.items = keep
        self.spawn()
        if self.over is None and self.taken and len(self.got) >= 8 and self.dive is None:
            self.dive = 0          # the eighth, taken tonight: the bird comes
        if self.dive is not None:
            self.dive += 1
            if self.dive > 20:
                self.over = "won"

    def take(self):
        n = len(self.got) + 1
        if n <= 8:
            self.got.append(n)
            self.taken.append(str(n))
            self.show = (SHOW_TICKS, str(n))
        else:
            self.dist += 50

    def autopilot(self):
        """The sim's pilot: jump when the next item lands in the jump's high
        ticks. Not perfect -- a run still ends -- but it collects."""
        if self.air >= 0:
            return None
        ahead = [x for x, _ in self.items if x > HERO_X]
        if not ahead:
            return None
        ticks = (min(ahead) - HERO_X) / self.speed
        return "j" if 1.5 <= ticks <= 3.5 else None

    # -- the picture -------------------------------------------------------
    def frame(self, tl, best):
        w = self.w
        rows = [[" "] * w for _ in range(14)]

        def put(r, c, s):
            for i, ch in enumerate(s):
                if 0 <= c + i < w:
                    rows[r][c + i] = ch
        put(0, 2, "%s lua" % MARK)
        put(0, w - 16, "* %d/8" % len(self.got))
        put(1, 2, moon_line())
        for i, ln in enumerate(moon_art(self.p)):
            put(1 + i, w - 8, ln)
        # the ending's stars, under everything else
        if self.dive is not None:
            r = self.rng
            for _ in range(self.dive * 2):
                put(r.randint(2, GROUND - 2), r.randint(0, w - 10), "*")
        # the bird
        bx = int(round(self.bird_x))
        wings = "~v~" if (self.tick // 4) % 2 == 0 else "-v-"
        if self.dive is not None:
            bx = HERO_X - 1
            wings = "\\v/"
            put(max(2, GROUND - 1 - self.h - 1 - min(self.dive, 4)), bx, wings)
        else:
            put(2, bx, wings)
        # the ground and what stands on it, lit only so far ahead
        for c in range(w):
            rows[GROUND][c] = "_" if c <= HERO_X + self.lit else " "
        for x, kind in self.items:
            c = int(round(x))
            if c > HERO_X + self.lit or c < 0:
                continue
            if kind == ROCK:
                put(GROUND - 1, c, ROCK)
            elif kind == TRUNK:
                put(GROUND - 1, c, TRUNK)
                put(GROUND - 2, c, TRUNK)
            else:
                put(GROUND - 3, c, SPARK)
        # the hero
        hero_r = GROUND - 1 - self.h
        if self.dive is not None:
            hero_r = max(1, hero_r - self.dive // 2)
        put(hero_r, HERO_X, "@")
        put(GROUND + 1, 2, "distancia %d" % int(self.dist))
        put(GROUND + 1, w - 14, "best %d" % max(best, int(self.dist)))
        if self.show:
            import textwrap
            pt, en = tl.get(self.show[1], ("", ""))
            for i, ln in enumerate((textwrap.wrap(fold(pt), w - 4)[:2] + [""] * 2)[:2]):
                put(GROUND + 2 + i, 2, ln)
            for i, ln in enumerate((textwrap.wrap(fold(en), w - 4)[:2] + [""] * 2)[:2]):
                put(GROUND + 4 + i, 4, ln)
        return ["".join(r).rstrip() for r in rows]


# ------------------------------------------------------------- the runs --
def sim(seed, tape, day=None, st=None):
    """Headless: a fixed seed and a key tape ('j' jump, '.' nothing, per
    tick, repeating; 'auto' = the autopilot). Prints the numbers."""
    st = st if st is not None else load_state()
    g = Game(80, seed=seed, day=day, got=st["got"])
    for i in range(4000):
        key = g.autopilot() if tape == "auto" else ("j" if tape[i % len(tape)] == "j" else None)
        g.step(key)
        if g.over:
            break
    g.over = g.over or "end"
    return g


def finish(g, st, tl):
    """After a run, at the shell: what was taken, the numbers, the ending."""
    st["got"] = g.got
    st["best"] = max(st["best"], int(g.dist))
    path = None
    if g.over == "won":
        st["won"] = True
        path = write_palette()      # before a word is printed: a closed pipe must not lose the prize
    save_state(st)
    say()
    say("%s lua -- %s" % (MARK, moon_line()))
    for tag in g.taken:
        pt, en = tl.get(tag, ("", ""))
        say("  * %s" % fold(pt))
        say("    %s" % fold(en))
    if g.over == "hit":
        pt, en = tl.get("queda", ("", ""))
        say("  %s" % fold(pt))
        say("  %s" % fold(en))
    say("  distancia %d, best %d, * %d/8" % (int(g.dist), st["best"], len(g.got)))
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


def play(st, tl):
    import termios
    import tty
    cols, lines = shutil_size()
    if cols < 60 or lines < 16:
        say("%s lua: a terminal of 60x16 at least (this one is %dx%d)" % (MARK, cols, lines))
        return 2
    g = Game(cols, got=st["got"])
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out = sys.stdout
    paused = False
    try:
        tty.setcbreak(fd)
        out.write("\033[?1049h\033[?25l\033[H\033[2J")
        out.flush()
        frame_t = 1.0 / FPS
        while not g.over:
            t0 = time.monotonic()
            key = None
            if select.select([fd], [], [], frame_t)[0]:
                data = os.read(fd, 16)
                if data in (b"q", b"\x1b", b"\x03"):
                    g.over = "quit"
                    break
                if data == b"p":
                    paused = not paused
                elif data in (b" ", b"\n", b"\r", b"\x1b[A", b"k", b"w"):
                    key = "j"
            if paused:
                continue
            g.step(key)
            rows = g.frame(tl, st["best"])
            out.write("\033[H" + "\r\n".join(r + "\033[K" for r in rows))
            if paused:
                out.write("\r\n  paused -- p goes on, q leaves")
            out.flush()
            rest = frame_t - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)
        if g.over in ("hit", "won"):
            time.sleep(0.6)
    finally:
        out.write("\033[?25h\033[?1049l")
        out.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if g.over == "quit":
        st["best"] = max(st["best"], int(g.dist))
        st["got"] = g.got
        save_state(st)
        say("%s lua -- distancia %d, * %d/8" % (MARK, int(g.dist), len(g.got)))
        return 0
    finish(g, st, tl)
    return 0


def shutil_size():
    import shutil
    s = shutil.get_terminal_size((80, 24))
    return s.columns, s.lines


USAGE = """%s lua -- the dark, a runner, a moon

  spark lua                 run: Space (or Enter, Up) jumps, p pauses, q leaves
  spark lua --moon [DATE]   tonight's moon, or a date's (YYYY-MM-DD)
  spark lua --reset         forget what was collected
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
        g = sim(seed, tape, day, st)
        say("distance %d sparks %d over %s got %s" % (int(g.dist), len(g.taken), g.over, ",".join(str(n) for n in g.got)))
        finish(g, st, tl)
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        pt, en = tl.get("abertura", ("", ""))
        say("%s lua: a terminal, please -- this one runs in the dark" % MARK)
        say("  %s" % fold(pt))
        say("  %s" % fold(en))
        return 2
    return play(st, tl)
