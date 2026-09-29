# spark.look -- the living layer's state: which parts are on, how they
# resolve at this terminal, and the one file the widgets read.
#
# Nothing here changes a byte until `spark awaken` has run: an unawakened
# machine answers "off" for every part, so every caller keeps today's
# output. The parts (contract 3, spark.env):
#   SPARK_LOOK_MOTION   the scanner, the waking bar, a face that blinks
#   SPARK_LOOK_COLOUR   the built-in palette when no SGR is exported
#   SPARK_LOOK_WORDS    the greeting, the news, the faces, the voice
#   SPARK_REVEAL        the pace (off|auto|N) -- `spark look reveal` is
#                       a second spelling of `spark reveal`
# Each is auto|on|off. auto = only where the terminal carries it: a tty,
# not TERM=dumb, and for colour NO_COLOR unset. on = at any tty.
#
# The look file ($STATE_DIR/look) is state, not config: KEY=value lines
# written atomically by render() alone and parsed line by line by the
# hooks -- never sourced, never eval'd (a face holds parentheses).

import os
import sys

from . import CONFIG_DIR, STATE_DIR

LOOK_FILE = os.path.join(STATE_DIR, "look")
NEWS_FILE = os.path.join(STATE_DIR, "news")
NEWS_SEEN = os.path.join(STATE_DIR, "news-seen")
LOADS_FILE = os.path.join(STATE_DIR, "loads.json")
WORDS_FILE = os.path.join(CONFIG_DIR, "words")
FACES_FILE = os.path.join(CONFIG_DIR, "faces")

PARTS = ("motion", "colour", "reveal", "words")
KEY_OF = {"motion": "SPARK_LOOK_MOTION", "colour": "SPARK_LOOK_COLOUR", "words": "SPARK_LOOK_WORDS"}
VALUES = ("auto", "on", "off")

HEIGHT_MIN, HEIGHT_MAX = 1, 5
LINE_MAX = 72           # a spark line plus its mark and face still fits 80 columns

# The six roles and their built-in values when nothing is exported. No hue
# reads on every background, so the accent is bold in the terminal's own
# foreground; dim is decoration only (dots, brackets, arrows), never text
# a person has to read.
ROLES = ("accent", "muted", "warn", "trouble", "ok", "you")
DEFAULT_SGR = {"accent": "1", "muted": "2", "warn": "31", "trouble": "1;31", "ok": "32", "you": ""}

MOODS = ("asleep", "waking", "idle", "thinking", "pleased", "puzzled", "alarmed")
# The shipped kit's one face per mood, used until awaken writes the
# machine's own into FACES_FILE. ASCII only: the console draws them.
DEFAULT_FACES = {"asleep": "(-.-)z", "waking": "(-o-)", "idle": "(o.o)", "thinking": "(o.O)",
                 "pleased": "(^.^)", "puzzled": "(o.?)", "alarmed": "(O.O)",
                 "blink": "(-.-)", "glance": "(.o.)"}

_state = None


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
    return state().get("AWAKE") == "yes"


def part(name, cfg=None):
    """auto, on or off for one part. Unawakened, every part is off, and
    reveal answers from SPARK_REVEAL as it always did."""
    if name == "reveal":
        if cfg is None:
            from . import config
            cfg = config.load()
        return cfg.get("SPARK_REVEAL", "off").strip() or "off"
    if not awake():
        return "off"
    if cfg is None:
        from . import config
        cfg = config.load()
    v = (cfg.get(KEY_OF[name], "off") or "off").strip()
    return v if v in VALUES else "off"


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


def slow_terminal():
    """ssh, the Linux console, or a tmux shown on it: auto keeps today's
    0.35 s dots there, where eight frames a second would smear."""
    from . import ASCII
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY") or ASCII)


def default_sgr(role):
    """The built-in SGR for `role` when the colour part is active, else ''."""
    return DEFAULT_SGR.get(role, "") if active("colour") else ""


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


def faces():
    """The machine's faces: FACES_FILE over the shipped kit, each cleaned."""
    out = dict(DEFAULT_FACES)
    for mood, frame in _read_kv(FACES_FILE).items():
        m = mood.lower()
        if m in out and clean(frame) and len(frame) <= 8:
            out[m] = frame.strip()
    return out


def height(cfg=None):
    if cfg is None:
        from . import config
        cfg = config.load()
    try:
        n = int(cfg.get("SPARK_HEIGHT", "1"))
    except ValueError:
        return 1
    return n if HEIGHT_MIN <= n <= HEIGHT_MAX else 1


def render(cfg=None, awake_now=None):
    """Write the look file the widgets read. awake_now=True marks the
    machine awake (awaken), False asleep (a reset); None keeps it."""
    from . import config
    if cfg is None:
        cfg = config.load()
    was = awake()
    on = was if awake_now is None else awake_now
    lines = ["AWAKE=%s" % ("yes" if on else "no")]
    for p in ("motion", "colour", "words"):
        v = (cfg.get(KEY_OF[p], "off") or "off").strip()
        lines.append("%s=%s" % (p.upper(), v if (on and v in VALUES) else "off"))
    lines.append("HEIGHT=%d" % height(cfg))
    # the built-in palette only: a shell's own SPARK_*_SGR exports win
    # there, and auto (tty, NO_COLOR) is decided per shell by the hook
    colour = on and (cfg.get(KEY_OF["colour"], "off") or "off").strip() != "off"
    for role in ROLES:
        lines.append("SGR_%s=%s" % (role.upper(), DEFAULT_SGR[role] if colour else ""))
    for mood, frame in sorted(faces().items()):
        lines.append("FACE_%s=%s" % (mood.upper(), frame))
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = LOOK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, LOOK_FILE)
    forget()
