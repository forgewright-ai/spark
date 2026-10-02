# spark.words -- the lines an awakened machine says, and its faces.
#
# ~/.config/spark/words is `ID<TAB>line`, one a line, written by `spark
# awaken` (the model's lines, each checked) and yours to change with
# `spark words edit`. ~/.config/spark/faces is `MOOD=frame`, plus the
# blink rate and the temperament. The shipped lines are
# home/.config/spark/words.d/<temperament> and the parts of a face
# home/.config/spark/faces.kit, both in this tree.
#
# Every line passes look.clean() when it is read, so a line a person or a
# model wrote with an escape, a character outside ASCII, more than 72
# columns or a secret's shape is never printed: it is refused, and the
# shipped line stands in.
#
#   spark words           the lines by id, and the faces
#   spark words edit      change them in $VISUAL / $EDITOR, then the check
#   spark words greet     (the widgets, the first prompt after an absence)

import hashlib
import os
import sys
import time

from . import MARK, REPO, look, say

SHIPPED_DIR = os.path.join(REPO, "home", ".config", "spark", "words.d")
KIT_FILE = os.path.join(REPO, "home", ".config", "spark", "faces.kit")
TEMPERS = ("plain", "warm", "playful", "terse")
DEFAULT_TEMPER = "plain"
# the ids every temperament ships; `hello` carries {name}, the machine's
IDS = ("greet.1", "greet.2", "greet.3", "awake", "asleep", "runs", "done", "hello")
# frames between blinks by temperament (0: never); look reads RATE=
BLINK_RATE = {"playful": 14, "warm": 28, "plain": 50, "terse": 0}
# the order the faces are shown in
FACE_ORDER = look.MOODS + ("blink", "glance")

USAGE = """%s words -- the lines it says, and its faces

  spark words                   the lines by id, and the faces
  spark words edit              change the lines in $VISUAL / $EDITOR; each
                                line is checked again after

  The file is ~/.config/spark/words, one ID<TAB>line a line: ASCII, at
  most 72 characters. spark awaken writes it and the faces. A line that
  fails the check is never said: the shipped line stands in for it.
""" % MARK


def why_refused(line):
    """Why look.clean() refuses `line`, in a few words ('' when it does not)."""
    s = (line or "").strip()
    if not s:
        return "empty"
    if len(s) > look.LINE_MAX:
        return "over %d characters" % look.LINE_MAX
    if any(not (" " <= c <= "~") for c in s):
        return "an escape or a character outside ASCII"
    if look.clean(s) is None:
        return "it looks like a secret"
    return ""


def parse(path):
    """({id: line}, [(n, id, why)]) from an `ID<TAB>line` file: every line
    through look.clean(); comments and blanks skipped; a refused line
    named with its number and the reason. A missing file is ({}, [])."""
    lines, refused = {}, []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read().splitlines()
    except OSError:
        return lines, refused
    for n, text in enumerate(raw, 1):
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        key, sep, body = text.partition("\t")
        key = key.strip()
        if not sep or not look.valid_id(key):
            refused.append((n, key[:20] or "?", "not ID<TAB>line"))
            continue
        c = look.clean(body)
        if c is None:
            refused.append((n, key, why_refused(body)))
            continue
        lines[key] = c
    return lines, refused


def shipped(temper):
    """The shipped lines of a temperament (plain for an unknown one)."""
    t = temper if temper in TEMPERS else DEFAULT_TEMPER
    return parse(os.path.join(SHIPPED_DIR, t))[0]


def temper():
    """This machine's temperament: TEMPER= in the faces file, else plain."""
    t = look._read_kv(look.FACES_FILE).get("TEMPER", "").strip()
    return t if t in TEMPERS else DEFAULT_TEMPER


def load():
    """The machine's lines: the words file over its temperament's shipped
    lines, so a refused or missing line always has one to stand in."""
    out = shipped(temper())
    out.update(parse(look.WORDS_FILE)[0])
    return out


def kit():
    """{EYES: [...], MOUTH: [...], BODY: [...]} from faces.kit."""
    out = {}
    try:
        with open(KIT_FILE, encoding="utf-8") as f:
            for text in f.read().splitlines():
                key, sep, val = text.partition("=")
                if sep and key.isupper() and not text.startswith("#"):
                    out[key] = [v for v in val.split() if look.clean(v)]
    except OSError:
        pass
    for key, dflt in (("EYES", ["o"]), ("MOUTH", ["."]), ("BODY", ["()"])):
        if not out.get(key):
            out[key] = dflt
    return out


def pick(choices, seed, salt):
    """A choice made the same way on the same machine every time."""
    h = hashlib.sha256(("%s:%s" % (seed, salt)).encode("utf-8", "replace")).digest()
    return choices[h[0] % len(choices)]


def make_faces(eyes, mouth, body):
    """Every mood of one face from its parts: the same eyes, mouth and body
    in each, the blink closed eyes without the asleep face's z, listening
    the idle face with an ear mark (`~`)."""
    left, right = body[0], body[-1]
    wide = "o" if eyes == "O" else "O"

    def f(a, m, b, tail=""):
        return left + a + m + b + right + tail
    return {"idle": f(eyes, mouth, eyes), "blink": f("-", mouth, "-"), "asleep": f("-", mouth, "-", "z"),
            "waking": f("-", "o", "-"), "thinking": f(eyes, mouth, wide), "pleased": f("^", mouth, "^"),
            "puzzled": f(eyes, mouth, "?"), "alarmed": f("O", mouth, "O"), "glance": f(".", eyes, "."),
            "listening": f(eyes, mouth, eyes, "~")}


def face(mood="idle"):
    """One of this machine's faces (look.faces: the file over the kit)."""
    return look.faces().get(mood, look.DEFAULT_FACES["idle"])


def _show():
    have = os.path.isfile(look.WORDS_FILE)
    lines = load()
    say("words  %s  %s" % (temper(), look.WORDS_FILE if have else "shipped (spark awaken makes them this machine's own)"))
    for key in IDS + tuple(sorted(k for k in lines if k not in IDS and not k.startswith("personality."))):
        if key in lines:
            say("  %-10s %s" % (key, lines[key]))
    _, refused = parse(look.WORDS_FILE)
    for n, key, why in refused:
        say("  refused    line %d (%s): %s -- the shipped line stands in" % (n, key, why))
    fs = look.faces()
    say("faces  %s" % (look.FACES_FILE if os.path.isfile(look.FACES_FILE) else "shipped"))
    row = ["%s %s" % (m, fs[m]) for m in FACE_ORDER if m in fs]
    for i in range(0, len(row), 4):
        say("  " + "   ".join(row[i:i + 4]))
    return 0


def _edit():
    from . import soul
    ed = soul._editor()
    if not ed:
        say("spark words: no editor found -- set $EDITOR, or write %s by hand" % look.WORDS_FILE)
        return 1
    if not os.path.isfile(look.WORDS_FILE):
        write_words(shipped(temper()))
        say("ok     seeded       from the %s lines" % temper())
    else:
        os.chmod(look.WORDS_FILE, 0o600)
    import subprocess
    try:
        rc = subprocess.call(ed + [look.WORDS_FILE])
    except OSError as e:
        say("spark words: cannot run %s: %s" % (ed[0], e))
        return 1
    if rc != 0:
        say("spark words: %s exited %d -- the file is as it left it" % (ed[0], rc))
    lines, refused = parse(look.WORDS_FILE)
    for n, key, why in refused:
        say("refused  line %d (%s): %s -- the shipped line stands in" % (n, key, why))
    say("ok     words        %d line%s, %d refused" % (len(lines), "" if len(lines) == 1 else "s", len(refused)))
    return 0


def write_words(lines):
    """The words file, `ID<TAB>line`, 0600, atomically; every line checked."""
    body = "".join("%s\t%s\n" % (k, look.clean(v)) for k, v in lines.items()
                   if not k.startswith("personality.") and look.clean(v))
    _atomic(look.WORDS_FILE, body)


def write_faces(faces, temper_name):
    """The faces file: MOOD=frame each, then RATE= and TEMPER=, 0600."""
    body = "".join("%s=%s\n" % (m.upper(), faces[m]) for m in FACE_ORDER if m in faces and look.clean(faces[m]))
    body += "RATE=%d\nTEMPER=%s\n" % (BLINK_RATE.get(temper_name, 50), temper_name)
    _atomic(look.FACES_FILE, body)


def _atomic(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def greeting(day=None):
    """One of the machine's greet lines, in turn by the day ('' when it
    has none): the widgets' greeting and the chat's opening say it."""
    lines = load()
    greets = [lines[k] for k in sorted(lines) if k.startswith("greet.")]
    if not greets:
        return ""
    if day is None:
        day = int(time.time() // 86400)
    return greets[int(day) % len(greets)]


def greet(day=None):
    """The greeting the widgets ask for: nothing unless this machine is
    awake and its look is not off; else one
    line with its face (the greetings in turn by the day) and, when memory
    holds one, a remembered fact, shown here and written nowhere."""
    from . import config, memory
    if not look.awake():
        return []
    cfg = config.load()
    if look.part("words", cfg) == "off":
        return []
    line = greeting(day)
    if not line:
        return []
    if day is None:
        day = int(time.time() // 86400)
    out = ["* %s %s" % (face("idle"), line)]
    fact = memory.one_fact(cfg, day)
    if fact:
        head = "You asked me to remember: "
        room = look.LINE_MAX - 2 - len(head)
        fact = " ".join(fact.split())
        if len(fact) > room:
            fact = fact[:room - 3].rsplit(" ", 1)[0].rstrip() + "..."
        c = look.clean(head + fact)
        if c:
            out.append("  " + c)
    return out


def main(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if not args or args[0] in ("show", "status"):
        return _show()
    if args[0] == "edit":
        return _edit()
    if args[0] == "greet":
        try:
            for line in greet():
                say(line)
        except Exception:  # noqa: BLE001 -- a greeting never stands between you and the prompt
            pass
        return 0
    if len(args) > 1 or args[0].endswith("?"):
        # `spark words that rhyme with moon?` is a question, not a sub-word
        from . import cli
        return cli.main(["words"] + list(args))
    say(USAGE.rstrip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
