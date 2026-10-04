# spark.words -- an awakened machine's temperament and its faces.
#
# ~/.config/spark/faces is `MOOD=frame`, one a line, plus the blink rate
# and the temperament, written by `spark awaken`. Every mood is made and
# kept, one still each (asleep, waking, idle, thinking, pleased,
# puzzled, alarmed, listening, blink, glance). The frames a mood moves
# through are derived from the idle one when drawn (look.Anim), never
# stored. The parts of a face are
# home/.config/spark/faces.kit, and the personality a temperament keeps
# when the model's is refused is home/.config/spark/words.d/<temperament>,
# both in this tree.
#
# Since v1.73 awaken writes no lines to say and there is no `spark words`.
# The face says nothing: it shows in a wait, leads a reply, follows the
# mark in spark's row, rests above an idle prompt, and is in `spark
# look`. A shell started before
# the update may still run `spark words greet`; bin/spark answers it,
# silent.

import hashlib
import os

from . import REPO, look

SHIPPED_DIR = os.path.join(REPO, "home", ".config", "spark", "words.d")
KIT_FILE = os.path.join(REPO, "home", ".config", "spark", "faces.kit")
TEMPERS = ("plain", "warm", "playful", "terse")
DEFAULT_TEMPER = "plain"
# frames between blinks by temperament (0: never); look reads RATE=
BLINK_RATE = {"playful": 14, "warm": 28, "plain": 50, "terse": 0}
# the order the faces are written in
FACE_ORDER = look.MOODS + ("blink", "glance")


def parse(path):
    """({id: line}, [(n, id)]) from an `ID<TAB>line` file: every line
    through look.clean(); comments and blanks skipped; a refused line
    named with its number. A missing file is ({}, [])."""
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
        c = look.clean(body) if sep and look.valid_id(key) else None
        if c is None:
            refused.append((n, key[:20] or "?"))
            continue
        lines[key] = c
    return lines, refused


def personality(temper):
    """The shipped personality paragraph of a temperament (plain for an
    unknown one): its personality.N lines in order, joined."""
    t = temper if temper in TEMPERS else DEFAULT_TEMPER
    got = parse(os.path.join(SHIPPED_DIR, t))[0]
    return " ".join(got[k] for k in sorted(got) if k.startswith("personality."))


def temper():
    """This machine's temperament: TEMPER= in the faces file, else plain."""
    t = look._read_kv(look.FACES_FILE).get("TEMPER", "").strip()
    return t if t in TEMPERS else DEFAULT_TEMPER


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


def write_faces(faces, temper_name):
    """The faces file: MOOD=frame each, then RATE= and TEMPER=, 0600."""
    body = "".join("%s=%s\n" % (m.upper(), faces[m]) for m in FACE_ORDER if m in faces and look.clean(faces[m]))
    body += "RATE=%d\nTEMPER=%s\n" % (BLINK_RATE.get(temper_name, 50), temper_name)
    _atomic(look.FACES_FILE, body)


def _atomic(path, body):
    from . import vault
    os.makedirs(os.path.dirname(path), exist_ok=True)
    vault.write_private(path, body.encode("utf-8"))
