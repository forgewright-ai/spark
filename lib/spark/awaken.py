# spark.awaken -- `spark awaken`: give this machine a personality and a look.
#
# The door to the living layer. Nothing living happens before it runs,
# and it is the one place spark asks the model about itself: never
# unasked, never anywhere else. It makes only what shows: a personality
# and a face. Seven steps, each short:
#
#   1 ask    the temperament (plain, warm, playful, terse); Enter keeps plain
#   2 wake   the model, when it is loading (the waking wait)
#   3 birth  one JSON object, `why` first: a personality paragraph, its
#            eyes and mouth from the kit. A refused or missing paragraph
#            keeps the shipped one (words.d/<temperament>), and a part off
#            the kit is picked by the machine's name. Every mood of the
#            face is made and written, one still each.
#   4 soul   the personality paragraph, after the fixed core -- or, with a
#            soul file of your own, "Your own soul is kept."
#   5 pace   one reply revealed at the measured pace; yes, faster, slower
#            or off (faster and slower replay the same text, no new call)
#   6 voice  where a player is: its own speaker, picked by the temperament
#            and the seed the face's body uses, voice.HELLO spoken by it;
#            keep, again (the next speaker) or none. What the engine lacks is
#            downloaded first, its size said and asked (voice.audition)
#   7 done   the look on auto, the look file rendered; a voice kept is
#            written and SPARK_VOICE set to on (a clear voice stays clear:
#            the recipe is written, and spark voice on takes it up)
#
# Nothing is written until the end, and then each file atomically: Ctrl-C
# at any question leaves the machine as it was (exit 130), but for a
# voice part already downloaded and verified, which the next run keeps.
# Running it again runs the birth again. It needs a terminal;
# SPARK_AWAKEN_TTY names a file of answers instead, one a line (the
# tests' seam).

import os
import re
import socket
import sys
import time

from . import MARK, SPARK_ENV, config, look, say, wire
from . import text as textmod
from . import words as wordsmod

USAGE = """%s awaken -- give this machine a personality and a look

  spark awaken                  you pick a temperament; the model writes a
                                personality and picks a face; then the
                                reply pace and a voice. Run it again to
                                start over.

  A soul file of your own is kept.
""" % MARK

TEMPER_DESC = {
    "plain": "plain and brief: the facts, no small talk",
    "warm": "warm and patient, like a good colleague",
    "playful": "light, with a little humour that never hides the answer",
    "terse": "as few words as possible",
}
NO_PACE = "! the model did not answer -- the pace stays as it is"
PERSONALITY_CAP = 480          # the birth's paragraph; soul.PERSONALITY_MAX is the file's cap
BIRTH_TOKENS = 700
BIRTH_TIMEOUT = 180
WAKE_MAX = 240                 # seconds the wait for a loading model lasts, at most
PACE_ASK = "Say hello to me in 2 short sentences. Your temperament: %s."
PACE_TOKENS = 120


def _schema(k):
    return {
        "type": "object",
        "properties": {
            "why": {"type": "string"},
            "personality": {"type": "string"},
            "eyes": {"type": "string", "enum": list(k["EYES"])},
            "mouth": {"type": "string", "enum": list(k["MOUTH"])},
        },
        "required": ["why", "personality", "eyes", "mouth"],
    }


def _brief(temper, k):
    return (
        "You are shaping a local assistant called spark that answers at a person's shell prompt, "
        "in one temperament: %s (%s). Write plain English, ASCII only. No emoji, no quotation "
        "marks, no commands, and no claim about privacy or where anything is sent. Reply with one "
        "JSON object. `why` comes first: one sentence on how the temperament shapes the voice. "
        "`personality`: 2 or 3 sentences, addressed as you, on how you speak (tone only, no "
        "rules). `eyes`: one of %s. `mouth`: one of %s."
        % (temper, TEMPER_DESC[temper], " ".join(k["EYES"]), " ".join(k["MOUTH"])))


# ---------------------------------------------------------------- the asking
class _Ask:
    """The questions' input: the terminal, or SPARK_AWAKEN_TTY's lines."""

    def __init__(self):
        self.lines = None
        path = os.environ.get("SPARK_AWAKEN_TTY")
        if path:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    self.lines = f.read().splitlines()
            except OSError:
                self.lines = []

    def __call__(self, prompt):
        if self.lines is not None:
            sys.stdout.write(prompt)
            ans = self.lines.pop(0) if self.lines else ""
            sys.stdout.write(ans + "\n")
            sys.stdout.flush()
            return ans.strip().lower()
        try:
            return input(prompt).strip().lower()
        except EOFError:
            say("")
            return ""


def ask_temper(ask):
    for _ in range(2):
        a = ask("temperament [plain]  (plain, warm, playful, terse): ")
        if not a:
            return "plain"
        if a in wordsmod.TEMPERS:
            return a
    return "plain"


# ----------------------------------------------------------------- the model
def _wake(cfg):
    """A session with the model answering, or (None, hint). A loading model
    is waited for, the waking bar when its last load was measured."""
    from . import engine, session
    try:
        return session.Session(cfg, "answer", ""), ""
    except wire.BrainError as e:
        if e.kind != "loading":
            return None, e.hint
    expected = engine.last_load(engine.model_file(cfg, "ember") or engine.model_file(cfg))
    bar = textmod.Estimate("waking", expected) if expected else textmod.Busy(sys.stderr, kind="swell")
    bar.start()
    t0 = time.time()
    try:
        while time.time() - t0 < max(WAKE_MAX, 2 * (expected or 0)):
            time.sleep(1.0)
            try:
                return session.Session(cfg, "answer", ""), ""
            except wire.BrainError as e:
                if e.kind != "loading":
                    return None, e.hint
        return None, "the model is still loading"
    finally:
        bar.stop()


def ask_birth(s, temper, k):
    """The model's one JSON object for this temperament, or {} on any
    failure. The request goes bare (identity false): no soul and no
    remembered fact rides it, so none can be echoed into the plain
    personality file. It is a turn record, as every request is."""
    msgs = [{"role": "system", "content": _brief(temper, k)},
            {"role": "user", "content": "Shape spark for the %s temperament." % temper}]
    busy = textmod.Busy(sys.stderr).start()
    t0 = time.time()
    try:
        reply, s.timings = s._retry_fresh(lambda: wire.chat_json(
            s.cfg, s.url, msgs, _schema(k), max_tokens=BIRTH_TOKENS, temperature=0.7,
            forge=s.forge, model="ember", timeout=BIRTH_TIMEOUT, identity=False))
    except wire.BrainError:
        return {}
    finally:
        busy.stop()
    s.record(kind="awaken", ms=int((time.time() - t0) * 1000))
    return reply if isinstance(reply, dict) else {}


def _paragraph(t):
    """A personality paragraph fit to keep: whitespace folded, printable
    ASCII, no secret's shape, at most PERSONALITY_CAP. None when not."""
    if not isinstance(t, str):
        return None
    t = " ".join(t.split())
    if not t or len(t) > PERSONALITY_CAP or any(not (" " <= c <= "~") for c in t):
        return None
    if textmod.held_spans(t)[0]:
        return None
    return t


FIRST_PERSON = re.compile(r"\b(?:I|I'm|me|my|myself)\b")


def _sentences(t):
    """A model's paragraph as whole sentences: each one's first letter a
    capital, a lone `i` a capital I, a full stop at the end when it has
    no end mark. A small model writes lowercase under a terse brief."""
    t = re.sub(r"(^|[.!?] +)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    t = re.sub(r"\bi\b(?=[ '])", "I", t)
    return t if t.endswith((".", "?", "!")) else t + "."


def birth_parts(reply, temper, k, seed):
    """(personality, faces, refused) from the model's reply: the
    paragraph checked, a refused or missing one the shipped paragraph;
    the eyes and mouth from the kit, else picked by `seed`; the body by
    `seed` always. Every mood of the face is made. `refused` is 1 when
    the check turned the paragraph away."""
    reply = reply if isinstance(reply, dict) else {}
    refused = 0
    p = _paragraph(reply.get("personality"))
    if p is not None:
        p = _sentences(p)
        # the core speaks to the model as "you": a paragraph in the first
        # person reads as a second speaker, so the shipped one stands in
        if FIRST_PERSON.search(p):
            p = None
    if p is None:
        if "personality" in reply:
            refused += 1
        p = wordsmod.personality(temper)
    eyes = reply.get("eyes") if reply.get("eyes") in k["EYES"] else wordsmod.pick(k["EYES"], seed, "eyes")
    mouth = reply.get("mouth") if reply.get("mouth") in k["MOUTH"] else wordsmod.pick(k["MOUTH"], seed, "mouth")
    body = wordsmod.pick(k["BODY"], seed, "body")
    return p, wordsmod.make_faces(eyes, mouth, body), refused


# ------------------------------------------------------------------ the pace
def _printable(t):
    """A reply fit for the screen: newlines kept, every other control out."""
    return "".join(c for c in t if c == "\n" or (c >= " " and not ("\x7f" <= c <= "\x9f")))


def _play(text, cps):
    w = textmod.Wrap(sys.stdout, mark=True, cps=cps)
    w.feed(text)
    w.close()


def pace(s, cfg, temper, ask):
    """One reply, revealed; the answer: 'auto', a number, 'off' or None
    (Enter: SPARK_REVEAL stays as it is)."""
    from . import reveal
    chunks = []
    busy = textmod.Busy(sys.stderr).start()
    try:
        _, ms = s.ask_stream(PACE_ASK % TEMPER_DESC[temper], "", chunks.append, max_tokens=PACE_TOKENS, timeout=60)
        s.record(kind="awaken", ms=ms)
    except wire.BrainError:
        busy.stop()
        say(NO_PACE)
        return None
    finally:
        busy.stop()
    text = _printable("".join(chunks)).strip()
    if not text:
        say(NO_PACE)
        return None
    auto = cps = reveal.auto_cps(cfg)
    for _ in range(12):
        _play(text, cps)
        a = ask("like this pace? (yes, faster, slower, off): ")
        if a in ("yes", "y"):
            return "auto" if cps == auto else str(cps)
        if a == "off":
            return "off"
        if a in ("faster", "slower"):
            step = 1.25 if a == "faster" else 0.75
            cps = max(reveal.CPS_MIN, min(reveal.CPS_MAX, int(round(cps * step))))
            continue
        if not a:
            return None
    return None


# ----------------------------------------------------------------- the voice
def offer_voice(cfg, temper, ask=None):
    """Step 6: the voice, offered where a player is and a person answers
    (never under SPARK_NO_APPLY). The recipe kept, or None: Enter, none,
    no player or a failure leave SPARK_VOICE as it is."""
    from . import voice
    if os.environ.get("SPARK_NO_APPLY") or not voice.player(cfg):
        return None
    kept = voice.audition(cfg, temper, _seed(cfg), ask or _Ask())
    if kept:
        say("* its voice: %s" % voice.describe(kept))
        if voice.mode(cfg) == "clear":
            say("* the clear voice stays on -- spark voice on uses this one")
    say("")
    return kept


# ------------------------------------------------------------------ the flow
def _seed(cfg):
    try:
        host = socket.gethostname()
    except OSError:
        host = ""
    return host or cfg.name


def _wrapped(t, width=70):
    out, cur = [], ""
    for w in t.split():
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return ["  " + x for x in out]


def run(cfg, ask):
    from . import soul
    temper = ask_temper(ask)
    k = wordsmod.kit()
    s, hint = _wake(cfg)
    reply = {}
    if s is None:
        say("! the model is not answering")
        if hint:
            say("  " + hint)
    else:
        reply = ask_birth(s, temper, k)
    personality, fs, _refused = birth_parts(reply, temper, k, _seed(cfg))
    own = soul.read(cfg)[1] in ("file", "env")
    if own:
        say("* your soul is kept")
    else:
        say("* its personality:")
        for row in _wrapped(personality):
            say(row)
    say("")
    pace_word = None
    if s is None:
        say("! no model to show the pace -- spark reveal sets it later")
    else:
        pace_word = pace(s, cfg, temper, ask)
    kept = offer_voice(cfg, temper, ask)
    # the end: every file at once, each atomically
    wordsmod.write_faces(fs, temper)
    if not own:
        soul.write_personality(personality)
    from . import site
    keys = {"SPARK_LOOK": "auto"}
    if pace_word:
        keys["SPARK_REVEAL"] = pace_word
    if kept:
        from . import voice
        voice.write_recipe(kept)
        if voice.mode(cfg) != "clear":      # a clear voice is a person's need: it stays
            keys["SPARK_VOICE"] = "on"
    site.set_keys(_file=SPARK_ENV, _quiet=True, **keys)
    look.render(config.load(), awake_now=True)
    say("* awake -- the look is on auto")
    say("* if spark's line covers your prompt, press Esc k")
    return 0


def main(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if args:
        say("%s awaken -- it takes no words: spark awaken -h says what it does" % MARK)
        return 2
    if not os.environ.get("SPARK_AWAKEN_TTY") and not (sys.stdin.isatty() and sys.stdout.isatty()):
        say("%s awaken -- it asks questions, so it needs a terminal" % MARK)
        return 2
    try:
        with look.assume_awake():
            return run(config.load(), _Ask())
    except KeyboardInterrupt:
        say("")
        return 130
