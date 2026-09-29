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
#
# The height (SPARK_HEIGHT, 1..5, `spark height N`) is not a part: it is
# the row spark writes in, counted up from the prompt's input line, and
# it reaches every machine, awakened or not (1 = today).

import os
import sys

from . import CONFIG_DIR, SPARK_ENV, STATE_DIR

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
FACE_MAX = 8            # a face rides beside the mark: `* (o.o) awake`
BLINK_DEFAULT = 14      # scanner frames between two blinks; 0 = never

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
# the faces file's two settings beside the frames (awaken writes them):
# RATE= the frames between blinks, TEMPER= the temperament's name
FACE_SETTINGS = ("RATE", "TEMPER")

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


def _cfg(cfg):
    if cfg is None:
        from . import config
        cfg = config.load()
    return cfg


def stored(name, cfg=None):
    """What spark.env holds for a part (auto, on or off), awake or not."""
    if name == "reveal":
        return (_cfg(cfg).get("SPARK_REVEAL", "off").strip() or "off")
    v = (_cfg(cfg).get(KEY_OF[name], "off") or "off").strip()
    return v if v in VALUES else "off"


def part(name, cfg=None):
    """auto, on or off for one part. Unawakened, every part is off, and
    reveal answers from SPARK_REVEAL as it always did."""
    if name == "reveal":
        return stored(name, cfg)
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


def slow_terminal():
    """ssh, the Linux console, or a tmux shown on it: auto keeps today's
    0.35 s dots there, where eight frames a second would smear."""
    from . import ASCII
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY") or ASCII)


def scanner(stream):
    """The scanner draws on `stream`: motion active, and on a fast
    terminal unless motion is on (on forces it over ssh and the console)."""
    return active("motion", stream) and (part("motion") == "on" or not slow_terminal())


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


def faces(path=None):
    """The machine's faces: the faces file over the shipped kit, each
    cleaned. RATE= and TEMPER= are settings, not faces."""
    out = dict(DEFAULT_FACES)
    for mood, frame in _read_kv(path or FACES_FILE).items():
        if mood.upper() in FACE_SETTINGS:
            continue
        m = mood.lower()
        if m in out and clean(frame) and len(frame.strip()) <= FACE_MAX:
            out[m] = frame.strip()
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
                good = bool(tab) and _id.strip() and clean(text) is not None and clean(_id) is not None
            else:
                key, eq, frame = line.partition("=")
                if eq and key.strip().upper() in FACE_SETTINGS:
                    good = clean(frame) is not None
                else:
                    good = bool(eq) and clean(key) is not None and clean(frame) is not None
            if not good:
                out.append((os.path.basename(path), n))
    return out


def height(cfg=None):
    try:
        n = int(_cfg(cfg).get("SPARK_HEIGHT", "1"))
    except ValueError:
        return 1
    return n if HEIGHT_MIN <= n <= HEIGHT_MAX else 1


def content(cfg, on, faces_path=None):
    """The look file's text for `cfg`, awake (`on`) or not: what render()
    writes, and what the check's look row compares the file with."""
    lines = ["AWAKE=%s" % ("yes" if on else "no")]
    for p in ("motion", "colour", "words"):
        v = stored(p, cfg)
        lines.append("%s=%s" % (p.upper(), v if on else "off"))
    lines.append("HEIGHT=%d" % height(cfg))
    # the built-in palette only: a shell's own SPARK_*_SGR exports win
    # there, and auto (tty, NO_COLOR) is decided per shell by the hook
    colour = on and stored("colour", cfg) != "off"
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
    on = awake() if awake_now is None else awake_now
    _atomic(LOOK_FILE, content(cfg, on))
    forget()


def news(nid, line):
    """One state change worth one showing: `ID<TAB>line` in the news file,
    atomic, the line through clean(). The hook shows each id once. A line
    clean() refuses, or an id that is not one plain word, writes nothing."""
    line = clean(line)
    nid = (nid or "").strip()
    if line is None or not nid or not all(c.isalnum() or c in "-_." for c in nid):
        return False
    try:
        _atomic(NEWS_FILE, "%s\t%s\n" % (nid, line))
    except OSError:
        return False
    return True


# ------------------------------------------------------------------- verbs
USAGE = """spark look -- motion, colour, words: the living prompt

  spark look                    the four parts, the height, and awake or not
  spark look PART auto|on|off   PART: motion, colour, words
  spark look reveal N|auto|off  the same as spark reveal
  spark look off                motion, colour and words off at once

  motion   the scanner while a reply comes, the waking bar, a face that
           blinks; auto keeps the dots over ssh and on the console
  colour   the built-in palette, where you export no SPARK_*_SGR
  words    the greeting, the news and the faces
  auto     where the terminal carries it: a terminal, not TERM=dumb, and
           for colour NO_COLOR unset; on overrides NO_COLOR

  The parts start at spark awaken. A pipe never sees a frame or a colour.
"""

HEIGHT_USAGE = """spark height -- the row spark writes in, above your prompt

  spark height                  the row now
  spark height N                N rows up from the line you type on, 1..5

  1 is the row just above the prompt. A prompt of two lines (a status
  line above the one you type on) wants 2.
"""

_WHAT = {"motion": "the scanner, the waking bar, a face that blinks",
         "colour": "the built-in palette, where you export none",
         "reveal": "the pace replies appear at (spark reveal)",
         "words": "the greeting, the news and the faces"}


def _here(name, cfg):
    """How an auto or on part resolves at this terminal, in words."""
    if not awake():
        return ""
    if not active(name, sys.stdout, cfg):
        return "off at this terminal"
    if name == "motion" and not scanner(sys.stdout):
        return "dots at this terminal"
    return "on at this terminal"


def fresh(cfg=None):
    """Bring the look file up to date with spark.env and the faces file on
    an awakened machine (a hand edit of either); True when it was. The
    file is derived state, like check.json: the bare verb shows the
    settings, and the file the hooks read follows them."""
    if not awake():
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
    for p in PARTS:
        v = stored(p, cfg)
        here = _here(p, cfg) if p != "reveal" and v != "off" else ""
        say("%-7s %-5s %s%s" % (p, v, _WHAT[p], " -- " + here if here else ""))
    say("%-7s %-5d %s" % ("height", height(cfg), "the row spark writes in, above your prompt"))
    if awake():
        say("awake -- spark look PART auto|on|off changes a part")
    else:
        say("not awakened -- spark awaken gives this machine a personality and a look")
    return 0


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
    word = args[0].lower()
    if word == "reveal":
        from . import reveal
        return reveal.cmd_reveal(args[1:])
    if word == "off" and len(args) == 1:
        _set(SPARK_LOOK_MOTION="off", SPARK_LOOK_COLOUR="off", SPARK_LOOK_WORDS="off")
        say("motion, colour and words are off -- the reveal is untouched (spark reveal off stops it)")
        return 0
    if word == "color":
        word = "colour"
    if word not in KEY_OF:
        say("spark look -- no part named %s: motion, colour, reveal or words" % args[0])
        return 2
    if len(args) == 1:
        from . import config
        cfg = config.load()
        v = stored(word, cfg)
        here = _here(word, cfg) if v != "off" else ""
        say("%s %s -- %s%s" % (word, v, _WHAT[word], "; " + here if here else ""))
        return 0
    val = args[1].lower()
    if len(args) > 2 or val not in VALUES:
        say("spark look -- %s takes auto, on or off" % word)
        return 2
    _set(**{KEY_OF[word]: val})
    if awake() or val == "off":
        say("%s is %s now" % (word, val))
    else:
        say("%s is %s -- it takes effect after spark awaken" % (word, val))
    return 0


def cmd_height(args):
    from . import say
    if args and args[0] in ("-h", "--help", "help"):
        say(HEIGHT_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        say("height %d -- the row spark writes in, above your prompt" % height())
        return 0
    try:
        n = int(args[0])
    except ValueError:
        n = 0
    if len(args) > 1 or not HEIGHT_MIN <= n <= HEIGHT_MAX:
        say("spark height -- the height is a number, %d..%d" % (HEIGHT_MIN, HEIGHT_MAX))
        return 2
    _set(SPARK_HEIGHT=str(n))
    say("height %d now -- spark writes %s above the line you type on" % (n, "the row just" if n == 1 else "%d rows" % n))
    return 0
