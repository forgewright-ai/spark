# spark.awaken -- `spark awaken`: give this machine a personality and a look.
#
# The door to the living layer. Nothing living happens before it runs,
# and it is the one place spark asks the model for its own lines: never
# unasked, never anywhere else. Six steps, each short:
#
#   1 ask    the temperament (plain, warm, playful, terse); Enter keeps plain
#   2 wake   the model, when it is loading (the waking wait)
#   3 birth  one JSON object, `why` first: the lines it says, a personality
#            paragraph, its eyes and mouth from the kit. Every line passes
#            look.clean(); a refused or missing one keeps the shipped line
#            (words.d/<temperament>). No model: the shipped lines, said so.
#   4 soul   the personality paragraph, after the fixed core -- or, with a
#            soul file of your own, "Your own soul is kept."
#   5 pace   one reply revealed at the measured pace; yes, faster, slower
#            or off (faster and slower replay the same text, no new call)
#   6 done   the look's parts on auto, the look file rendered
#
# Nothing is written until the end, and then each file atomically: Ctrl-C
# at any question leaves the machine as it was (exit 130). Running it
# again runs the birth again. It needs a terminal; SPARK_AWAKEN_TTY names
# a file of answers instead, one a line (the tests' seam).

import os
import socket
import sys
import time

from . import MARK, SPARK_ENV, config, look, say, wire
from . import text as textmod
from . import words as wordsmod

USAGE = """%s awaken -- give this machine a personality and a look

  spark awaken                  a temperament, the lines it says, its face,
                                the pace of a reply; then motion, colour and
                                words on auto (run it again to start over)

  The model writes the lines and picks the face, once, here. Every line is
  checked, and a shipped line stands in for one it refuses. A soul file of
  your own is kept. spark words shows the lines, spark look the parts.
""" % MARK

TEMPER_DESC = {
    "plain": "plain and brief: the facts, no small talk",
    "warm": "warm and patient, like a good colleague",
    "playful": "light, with a little humour that never hides the answer",
    "terse": "as few words as possible",
}
BIRTH_IDS = ("greet.1", "greet.2", "greet.3", "awake", "asleep", "runs", "done")
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
            "greet": {"type": "array", "items": {"type": "string"}},
            "awake": {"type": "string"},
            "asleep": {"type": "string"},
            "runs": {"type": "string"},
            "done": {"type": "string"},
            "personality": {"type": "string"},
            "eyes": {"type": "string", "enum": list(k["EYES"])},
            "mouth": {"type": "string", "enum": list(k["MOUTH"])},
        },
        "required": ["why", "greet", "awake", "asleep", "runs", "done", "personality", "eyes", "mouth"],
    }


def _brief(temper, k):
    return (
        "You are writing the few lines a local assistant called spark says at a person's shell "
        "prompt, in one temperament: %s (%s). Write plain English, ASCII only, short whole "
        "sentences, each line under 60 characters. No emoji, no quotation marks, no commands, and "
        "no claim about privacy or where anything is sent. Reply with one JSON object. `why` comes "
        "first: one sentence on how the temperament shapes the lines. Then `greet`: 3 different "
        "greetings for a person coming back to the terminal. `awake`: the model answers again. "
        "`asleep`: the model is not answering right now. `runs`: some tasks wait for the person's "
        "review. `done`: a closing line. `personality`: 2 or 3 sentences, addressed as you, on how "
        "you speak (tone only, no rules). `eyes`: one of %s. `mouth`: one of %s."
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
    est = getattr(textmod, "Estimate", None)
    bar = est("waking", expected) if (est and expected) else textmod.Busy(sys.stderr)
    starter = getattr(bar, "start", None)
    if starter:
        starter()
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
        stop = getattr(bar, "stop", None)
        if stop:
            stop()


def ask_birth(s, temper, k):
    """The model's one JSON object for this temperament, or {} on any failure."""
    msgs = [{"role": "system", "content": _brief(temper, k)},
            {"role": "user", "content": "Write the lines for the %s temperament." % temper}]
    busy = textmod.Busy(sys.stderr).start()
    try:
        reply, _ = s._retry_fresh(lambda: wire.chat_json(
            s.cfg, s.url, msgs, _schema(k), max_tokens=BIRTH_TOKENS, temperature=0.7,
            forge=s.forge, model="ember", timeout=BIRTH_TIMEOUT))
    except wire.BrainError:
        return {}
    finally:
        busy.stop()
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


def birth_lines(reply, temper, k, seed):
    """(lines, personality, faces, refused) from the model's reply: every
    line through look.clean(), a refused or missing one the shipped line;
    the eyes and mouth from the kit, else picked by `seed`; the body by
    `seed` always. `refused` counts the lines the check turned away."""
    reply = reply if isinstance(reply, dict) else {}
    ship = wordsmod.shipped(temper)
    lines, refused = dict(ship), 0
    greet = reply.get("greet")
    got = {}
    if isinstance(greet, list):
        for i, g in enumerate(greet[:3], 1):
            got["greet.%d" % i] = g
    for key in ("awake", "asleep", "runs", "done"):
        if key in reply:
            got[key] = reply.get(key)
    for key, val in got.items():
        c = look.clean(val) if isinstance(val, str) else None
        if c:
            lines[key] = c
        else:
            refused += 1
    p = _paragraph(reply.get("personality"))
    if p is None:
        if "personality" in reply:
            refused += 1
        p = " ".join(ship[key] for key in sorted(ship) if key.startswith("personality."))
    eyes = reply.get("eyes") if reply.get("eyes") in k["EYES"] else wordsmod.pick(k["EYES"], seed, "eyes")
    mouth = reply.get("mouth") if reply.get("mouth") in k["MOUTH"] else wordsmod.pick(k["MOUTH"], seed, "mouth")
    body = wordsmod.pick(k["BODY"], seed, "body")
    return lines, p, wordsmod.make_faces(eyes, mouth, body), refused


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
        s.ask_stream(PACE_ASK % TEMPER_DESC[temper], "", chunks.append, max_tokens=PACE_TOKENS, timeout=60)
    except wire.BrainError:
        busy.stop()
        say("The model did not answer, so the pace stays as it is.")
        return None
    finally:
        busy.stop()
    text = _printable("".join(chunks)).strip()
    if not text:
        say("The model did not answer, so the pace stays as it is.")
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


# ------------------------------------------------------------------ the flow
def _seed(cfg):
    try:
        host = socket.gethostname()
    except OSError:
        host = ""
    return host or cfg.name


def _faces_rows(fs):
    row = ["%s %s" % (m, fs[m]) for m in look.MOODS if m in fs]
    return ["  " + "   ".join(row[i:i + 4]) for i in range(0, len(row), 4)]


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


def _hello(lines, name, fs):
    c = look.clean((lines.get("hello") or "").replace("{name}", name or "this machine"))
    return "* %s %s" % (fs["idle"], c or "I am awake.")


def run(cfg, ask):
    from . import soul
    temper = ask_temper(ask)
    k = wordsmod.kit()
    s, hint = _wake(cfg)
    reply = {}
    if s is None:
        say("The model is not answering, so the shipped lines are used.")
        if hint:
            say("  " + hint)
    else:
        reply = ask_birth(s, temper, k)
        if not reply:
            say("The model gave no usable lines, so the shipped lines are used.")
    lines, personality, fs, refused = birth_lines(reply, temper, k, _seed(cfg))
    if reply and refused:
        say("%d of its lines did not pass the check. The shipped line stands in for each."
            % refused if refused > 1 else "1 of its lines did not pass the check. The shipped line stands in.")
    say(_hello(lines, cfg.name, fs))
    for row in _faces_rows(fs):
        say(row)
    say("")
    own = soul.read(cfg)[1] in ("file", "env")
    if own:
        say("Your own soul is kept.")
    else:
        say("Its personality, after spark's own rules:")
        for row in _wrapped(personality):
            say(row)
    say("")
    pace_word = None
    if s is None:
        say("No model can show the pace now, so spark reveal sets it later.")
    else:
        pace_word = pace(s, cfg, temper, ask)
    # the end: every file at once, each atomically
    wordsmod.write_words(lines)
    wordsmod.write_faces(fs, temper)
    if not own:
        soul.write_personality(personality)
    from . import site
    keys = {"SPARK_LOOK_MOTION": "auto", "SPARK_LOOK_COLOUR": "auto", "SPARK_LOOK_WORDS": "auto"}
    if pace_word:
        keys["SPARK_REVEAL"] = pace_word
    site.set_keys(_file=SPARK_ENV, _quiet=True, **keys)
    look.render(config.load(), awake_now=True)
    say("* %s Awake. Motion, colour and words are on auto. spark look shows them." % fs["pleased"])
    say("Your next prompt is awake. If spark's line sits on your prompt, press Esc k.")
    return 0


def main(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if args:
        say("%s awaken -- it takes no words -- spark awaken -h says what it does" % MARK)
        return 2
    if not os.environ.get("SPARK_AWAKEN_TTY") and not (sys.stdin.isatty() and sys.stdout.isatty()):
        say("%s awaken -- it asks you questions, so it needs a terminal" % MARK)
        return 2
    try:
        return run(config.load(), _Ask())
    except KeyboardInterrupt:
        say("")
        return 130
