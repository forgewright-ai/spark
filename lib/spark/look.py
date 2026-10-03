# spark.look -- the living layer's state: the one switch, how its parts
# resolve at this terminal, and the one file the widgets read.
#
# Nothing here changes a byte until `spark awaken` has run: an unawakened
# machine answers "off" for every part, so every caller keeps today's
# output. The switch (contract 3, spark.env) is SPARK_LOOK, auto|on|off,
# and three parts follow it, each with its own auto rule:
#   motion   the scanner, the waking bar, a face that blinks
#   colour   the built-in palette when no SGR is exported
#   words    the face in the wait (no line is printed for it: v1.72)
# auto = only where the terminal carries it: a tty, not TERM=dumb, and
# for colour NO_COLOR unset. on = at any tty, NO_COLOR overridden. The
# pace (SPARK_REVEAL, `spark reveal`) is its own.
#
# The look file ($STATE_DIR/look) is state, not config: KEY=value lines
# written atomically by render() alone and parsed line by line by the
# hooks -- never sourced, never eval'd (a face holds parentheses).
#
# The height (SPARK_HEIGHT, 1..5, `spark height N`) is not a part: it is
# the row spark writes in, counted up from the prompt's input line, and
# it reaches every machine, awakened or not (1 = today).

import os
import sys
from contextlib import contextmanager

from . import CONFIG_DIR, SPARK_ENV, STATE_DIR

LOOK_FILE = os.path.join(STATE_DIR, "look")
LOADS_FILE = os.path.join(STATE_DIR, "loads.json")
WORDS_FILE = os.path.join(CONFIG_DIR, "words")
FACES_FILE = os.path.join(CONFIG_DIR, "faces")

PARTS = ("motion", "colour", "words")
KEY = "SPARK_LOOK"
VALUES = ("auto", "on", "off")

HEIGHT_MIN, HEIGHT_MAX = 1, 5
LINE_MAX = 72           # a spark line plus its mark and face still fits 80 columns
FACE_MAX = 8            # a face rides beside the mark: `* (o.o) awake`
BLINK_DEFAULT = 14      # scanner frames between two blinks; 0 = never

# The six roles and their built-in values when nothing is exported. No hue
# reads on every background, so the accent is bold in the terminal's own
# foreground; dim is decoration only (dots, brackets, arrows), never text
# a person has to read.
ROLES = ("accent", "muted", "warn", "trouble", "ok", "you")
DEFAULT_SGR = {"accent": "1", "muted": "2", "warn": "31", "trouble": "1;31", "ok": "32", "you": ""}

MOODS = ("asleep", "waking", "idle", "thinking", "pleased", "puzzled", "alarmed", "listening")
# The shipped kit's one face per mood, used until awaken writes the
# machine's own into FACES_FILE. ASCII only: the console draws them.
# listening (Esc v) is the idle face with an ear mark, `~`.
DEFAULT_FACES = {"asleep": "(-.-)z", "waking": "(-o-)", "idle": "(o.o)", "thinking": "(o.O)",
                 "pleased": "(^.^)", "puzzled": "(o.?)", "alarmed": "(O.O)", "listening": "(o.o)~",
                 "blink": "(-.-)", "glance": "(.o.)"}
# the faces file's two settings beside the frames (awaken writes them):
# RATE= the frames between blinks, TEMPER= the temperament's name
FACE_SETTINGS = ("RATE", "TEMPER")

_state = None
_assume = False         # inside `spark awaken` (assume_awake)


def _read_kv(path):
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f.read().splitlines():
                k, sep, v = line.partition("=")
                if sep and k and k.replace("_", "").isalnum():
                    out[k] = v
    except OSError:
        pass
    return out


def state():
    """The look file as a dict ({} when absent), read once per process."""
    global _state
    if _state is None:
        _state = _read_kv(LOOK_FILE)
    return _state


def forget():
    """Drop the cached state (after render, and in tests)."""
    global _state
    _state = None


def awake():
    return _assume or state().get("AWAKE") == "yes"


@contextmanager
def assume_awake():
    """Inside `spark awaken`: this process acts awake, the look on auto
    (what awaken writes at its end), so its own waits and
    its pace look as they will after. Nothing is written early."""
    global _assume
    _assume = True
    try:
        yield
    finally:
        _assume = False


def _cfg(cfg):
    if cfg is None:
        from . import config
        cfg = config.load()
    return cfg


def _get(cfg, key, default, own):
    """A key's value; `own` reads spark.env's own, the environment
    ignored: the look file bakes in the file, and each shell applies its
    own exports (a SPARK_HEIGHT export must not reach every shell). A
    plain dict (the check's fixture) holds file values only."""
    cfg = _cfg(cfg)
    if own and hasattr(cfg, "own"):
        return cfg.own(key, default) or default
    return cfg.get(key, default) or default


def setting(cfg=None, own=False):
    """What spark.env holds for the look (auto, on or off), awake or not."""
    v = _get(cfg, KEY, "off", own).strip().lower()
    return v if v in VALUES else "off"


def stored(name, cfg=None, own=False):
    """A part's stored value: the look's one setting for motion, colour
    and words; SPARK_REVEAL for reveal."""
    if name == "reveal":
        return _get(cfg, "SPARK_REVEAL", "off", own).strip() or "off"
    return setting(cfg, own)


def part(name, cfg=None):
    """auto, on or off for one part. Unawakened, every part is off, and
    reveal answers from SPARK_REVEAL as it always did."""
    if name == "reveal":
        return stored(name, cfg)
    if _assume:
        return "auto"
    if not awake():
        return "off"
    return stored(name, cfg)


def _tty(stream):
    try:
        return bool(stream) and stream.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def active(name, stream=None, cfg=None):
    """Whether a part draws on `stream` (stdout by default) now. A pipe
    never sees the living layer, whatever the part says."""
    stream = sys.stdout if stream is None else stream
    v = part(name, cfg)
    if v == "off" or not _tty(stream) or os.environ.get("TERM") == "dumb":
        return False
    if v == "on":
        return True
    if name == "colour" and os.environ.get("NO_COLOR"):
        return False
    return True


def scanner(stream):
    """The scanner draws on `stream` wherever motion is active: every
    frame is ASCII, and ssh on a LAN and the console keep up with it."""
    return active("motion", stream)


def default_sgr(role, stream=None):
    """The built-in SGR for `role` when the colour part is active, else ''."""
    return DEFAULT_SGR.get(role, "") if active("colour", stream) else ""


def clean(line):
    """A line fit to print: ASCII, printable, at most LINE_MAX columns,
    no secret shape. None when it is not -- every line the model or a
    person writes into the words or faces file passes here before it is
    stored and again before it is printed (an escape in a file is a way
    to drive the terminal)."""
    if not isinstance(line, str):
        return None
    line = line.strip()
    if not line or len(line) > LINE_MAX:
        return None
    if any(not (" " <= c <= "~") for c in line):
        return None
    from . import text
    if text.held_spans(line)[0]:
        return None
    return line


def valid_id(key):
    """One rule for an id (a words line's, a news line's): ASCII letters,
    digits, `.`, `_` and `-`, nothing else."""
    return bool(key) and key.isascii() and all(c.isalnum() or c in "._-" for c in key)


def face_ok(frame):
    """A face fit to draw: clean() and at most FACE_MAX characters."""
    return clean(frame) is not None and len(frame.strip()) <= FACE_MAX


def faces(path=None):
    """The machine's faces: the faces file over the shipped kit, each
    cleaned. RATE= and TEMPER= are settings, not faces."""
    out = dict(DEFAULT_FACES)
    own = set()
    for mood, frame in _read_kv(path or FACES_FILE).items():
        if mood.upper() in FACE_SETTINGS:
            continue
        m = mood.lower()
        if m in out and face_ok(frame):
            out[m] = frame.strip()
            own.add(m)
    if "idle" in own and "listening" not in own and face_ok(out["idle"] + "~"):
        out["listening"] = out["idle"] + "~"     # a faces file older than the mood: its own idle, listening
    return out


def face_settings(path=None):
    """(blink rate, temper) from the faces file: RATE= a whole number of
    frames between blinks (0 = never, default BLINK_DEFAULT), TEMPER= one
    plain word or ''."""
    kv = _read_kv(path or FACES_FILE)
    try:
        rate = int(kv.get("RATE", ""))
        rate = rate if 0 <= rate <= 999 else BLINK_DEFAULT
    except ValueError:
        rate = BLINK_DEFAULT
    temper = kv.get("TEMPER", "").strip().lower()
    return rate, (temper if temper.isalpha() and len(temper) <= 16 else "")


def blink():
    """The frames between blinks, from the look file (render wrote it)."""
    try:
        return max(0, int(state().get("BLINK", BLINK_DEFAULT)))
    except ValueError:
        return BLINK_DEFAULT


def refused(words=None, faces_path=None):
    """[(file, line number)] for every line of the words or faces file
    that clean() refuses: a line spark will never print. A comment and a
    blank line are not lines; a faces setting (RATE=, TEMPER=) is not a
    face."""
    out = []
    for path, shape in ((words or WORDS_FILE, "words"), (faces_path or FACES_FILE, "faces")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().split("\n")
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if shape == "words":
                _id, tab, text = line.partition("\t")
                good = bool(tab) and valid_id(_id.strip()) and clean(text) is not None
            else:
                key, eq, frame = line.partition("=")
                if eq and key.strip().upper() in FACE_SETTINGS:
                    good = clean(frame) is not None
                else:
                    good = bool(eq) and clean(key) is not None and face_ok(frame)
            if not good:
                out.append((os.path.basename(path), n))
    return out


def height(cfg=None, own=False):
    try:
        n = int(_get(cfg, "SPARK_HEIGHT", "1", own))
    except ValueError:
        return 1
    return n if HEIGHT_MIN <= n <= HEIGHT_MAX else 1


def content(cfg, on, faces_path=None):
    """The look file's text for `cfg`, awake (`on`) or not: what render()
    writes, and what the check's look row compares the file with."""
    lines = ["AWAKE=%s" % ("yes" if on else "no")]
    v = setting(cfg, own=True)
    for p in PARTS:
        lines.append("%s=%s" % (p.upper(), v if on else "off"))
    lines.append("HEIGHT=%d" % height(cfg, own=True))
    # the built-in palette only: a shell's own SPARK_*_SGR exports win
    # there, and auto (tty, NO_COLOR) is decided per shell by the hook
    colour = on and v != "off"
    for role in ROLES:
        lines.append("SGR_%s=%s" % (role.upper(), DEFAULT_SGR[role] if colour else ""))
    for mood, frame in sorted(faces(faces_path).items()):
        lines.append("FACE_%s=%s" % (mood.upper(), frame))
    rate, temper = face_settings(faces_path)
    lines.append("BLINK=%d" % rate)
    lines.append("TEMPER=%s" % temper)
    return "\n".join(lines) + "\n"


def _atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def render(cfg=None, awake_now=None):
    """Write the look file the widgets read. awake_now=True marks the
    machine awake (awaken), False asleep (a reset); None keeps it."""
    if cfg is None:
        from . import config
        cfg = config.load()
    on = state().get("AWAKE") == "yes" if awake_now is None else awake_now
    _atomic(LOOK_FILE, content(cfg, on))
    forget()


# ------------------------------------------------------------------- verbs
USAGE = """spark look -- spark's own look: motion, colour and the face

  spark look                    show the look, the height and the pace
  spark look on|off|auto        turn the look on or off; auto is on at a
                                terminal, and colour only without NO_COLOR

  The look starts with spark awaken. A pipe never sees it.
"""

HEIGHT_USAGE = """spark height -- the row spark writes in, above your prompt

  spark height                  show the row
  spark height N                N rows above the line you type on, 1 to 5

  A prompt of two lines wants 2.
"""

def _here(cfg):
    """How an auto or on look resolves at this terminal, in words: the
    parts follow one switch, and NO_COLOR still holds colour back under
    auto."""
    if not awake():
        return ""
    on = [p for p in PARTS if active(p, sys.stdout, cfg)]
    if len(on) == len(PARTS):
        return "on at this terminal"
    if not on:
        return "off at this terminal"
    off = [p for p in PARTS if p not in on]
    return "%s on at this terminal, %s off" % (", ".join(on), ", ".join(off))


def fresh(cfg=None):
    """Bring the look file up to date with spark.env and the faces file on
    an awakened machine (a hand edit of either); True when it was. The
    file is derived state, like check.json: the bare verb shows the
    settings, and the file the hooks read follows them."""
    if state().get("AWAKE") != "yes":
        return False
    cfg = _cfg(cfg)
    try:
        with open(LOOK_FILE, encoding="utf-8") as f:
            if f.read() == content(cfg, True):
                return False
    except OSError:
        pass
    try:
        render(cfg)
    except OSError:
        return False
    return True


def show(cfg=None):
    from . import say
    cfg = _cfg(cfg)
    fresh(cfg)
    v = setting(cfg)
    here = _here(cfg) if v != "off" else ""
    say(("%-7s %-5s %s" % ("look", v, here)).rstrip())
    say("%-7s %-5d %s" % ("height", height(cfg), _rows(height(cfg))))
    say("%-7s %s" % ("reveal", stored("reveal", cfg)))
    if not awake():
        say("* not awake yet -- spark awaken turns the look on")
    return 0


def _rows(n):
    """Where height n writes, in words."""
    return "the row above your prompt" if n == 1 else "%d rows above your prompt" % n


def _set(**kv):
    from . import site
    site.set_keys(_file=SPARK_ENV, _quiet=True, **kv)
    from . import config
    render(config.load())


def cmd_look(args):
    from . import say
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        return show()
    val = args[0].lower()
    if val in VALUES and len(args) == 1:
        same = val == setting(own=True)
        _set(**{KEY: val})
        if same:
            return 0                # nothing changed: nothing to say
        if awake() or val == "off":
            say("* the look is %s" % val)
        else:
            say("* the look is %s -- it starts after spark awaken" % val)
        return 0
    if val in VALUES or (len(args) == 2 and args[1].lower() in VALUES):
        # `spark look motion on`: the look has no parts to name
        say("spark look -- one switch: spark look on, off or auto")
        return 2
    if len(args) > 1 or args[0].endswith("?"):
        # `spark look for big files in downloads` is a question
        from . import cli
        return cli.main(["look"] + list(args))
    say("spark look -- no word %s: spark look on, off or auto" % args[0])
    return 2


def cmd_height(args):
    from . import say
    if args and args[0] in ("-h", "--help", "help"):
        say(HEIGHT_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        say("height %d -- %s" % (height(), _rows(height())))
        return 0
    try:
        n = int(args[0])
    except ValueError:
        n = 0
        if len(args) > 1 or args[0].endswith("?"):
            # `spark height of a mountain?` is a question
            from . import cli
            return cli.main(["height"] + list(args))
    if len(args) > 1 or not HEIGHT_MIN <= n <= HEIGHT_MAX:
        say("spark height -- the height is a number, %d to %d" % (HEIGHT_MIN, HEIGHT_MAX))
        return 2
    same = str(n) == _cfg(None).own("SPARK_HEIGHT", "")
    _set(SPARK_HEIGHT=str(n))
    if same:
        return 0                    # nothing changed: nothing to say
    say("* height %d -- %s" % (n, _rows(n)))
    return 0
