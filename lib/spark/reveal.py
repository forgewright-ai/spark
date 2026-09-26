# spark.reveal -- stdin to stdout, at a reader's pace.
#
# A grounded answer arrives in bursts: nothing while the model composes
# and the gate checks a line, then the whole line at once. At a
# terminal, this filter turns the bursts into a steady hand -- each
# character written CPS a second, so an earlier line is still appearing
# while the next is being composed, and the wait hides behind the
# reading. It is presentation only, chosen by the reader: piped
# anywhere but a terminal it copies stdin to stdout byte for byte, so
# no pipeline ever slows down by accident. Purely local -- nothing is
# sent, nothing is read but stdin, no model is involved.

import codecs
import os
import sys
import time

CPS_DEFAULT = 30        # ~350 words a minute at six characters a word
CPS_MIN, CPS_MAX = 5, 200
READ_CPS = 40           # the ceiling of `auto`: a reader's pace, ~450 words a minute
MODEL_SHARE = 0.85      # `auto` stays under the model's own pace, so the hand never waits
CHARS_PER_TOKEN = 4.2   # the fallback when a turn recorded no length


def measured(turns):
    """(tokens a second, characters a token, turns counted) over the
    given turn records; (0, CHARS_PER_TOKEN, 0) when none carry a speed."""
    tps, cpt, n = 0.0, 0.0, 0
    for t in turns:
        try:
            r = float(t.get("tg_tps") or 0)
            k = int(t.get("tg_n") or 0)
            c = int(t.get("chars") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if r <= 0:
            continue
        tps += r
        cpt += (c / k) if (k > 0 and c > 0) else CHARS_PER_TOKEN
        n += 1
    if n == 0:
        return 0.0, CHARS_PER_TOKEN, 0
    return tps / n, cpt / n, n


def pace_report(cfg, current=None):
    """The benchmark, as lines: what the model writes (characters a
    second, from its newest turns), the threshold a smooth reveal stays
    under, and what is chosen now. The choice is the reader's."""
    from . import session
    tps, cpt, n = measured(session.recent_turns(8))
    thr = auto_cps(cfg)
    if n == 0:
        lines = ["no turn measured yet -- ask something first; a reveal without a measure is %d a second" % CPS_DEFAULT]
    else:
        model_cps = tps * cpt
        lines = ["the model writes %.0f characters a second (%.1f tokens a second, %.1f characters a token, %d turns)" % (model_cps, tps, cpt, n),
                 "under %d a second a reveal never waits on it (auto = %d); above, the model's own pauses show" % (int(model_cps * MODEL_SHARE), thr)]
    if current is not None:
        if current == "auto":
            now = "auto (%d a second)" % thr
        elif current:
            now = "%d a second" % current
        else:
            now = "off -- the replies as they come"
        lines.append("now: %s (spark reveal N | auto | off keeps it; /reveal in a chat is for that chat)" % now)
    return lines


def auto_cps(cfg, turns=None):
    """The pace of `auto`, from the model's own measured speed: the
    newest turns of the answering model (today's and yesterday's JSONL,
    tokens a second and characters a token as they were recorded), scaled
    to MODEL_SHARE so the writer always has text in hand, capped at
    READ_CPS so a fast model still reads like a hand; CPS_DEFAULT when
    nothing was measured yet. A threshold offered, never imposed: the
    reader picks off, auto or a number (the prompt line never streams,
    so it is never asked there)."""
    from . import session
    tps, cpt, n = measured(turns if turns is not None else session.recent_turns(8))
    if n == 0:
        return CPS_DEFAULT
    cps = int(min(READ_CPS, tps * cpt * MODEL_SHARE))
    return max(CPS_MIN, min(CPS_MAX, cps))

USAGE = """spark reveal -- the pace replies appear at, and a filter at that pace

  spark reveal                what the model writes, and the pace now
  spark reveal N|auto|off     keep the pace for chat, explain and bare
                              words in spark.env (N: %d..%d a second)
  ... | spark reveal [N]      piped in: stdin to stdout letter by letter,
                              N a second (default %d, or SPARK_REVEAL_CPS)

  Piped in and out to anything but a terminal, the filter is an exact
  copy, byte for byte. Nothing is sent anywhere.

      spark read <words> < page.txt | spark reveal
""" % (CPS_MIN, CPS_MAX, CPS_DEFAULT)


def _standing(args):
    """`spark reveal [N|auto|off]` typed at a terminal, with nothing
    piped in: show or keep the standing pace (SPARK_REVEAL). The filter
    read the keyboard here and waited for Ctrl-C, keeping nothing."""
    from spark import SPARK_ENV, config, say
    cfg = config.load()
    if not args:
        for line in pace_report(cfg, cfg.reveal):
            say(line)
        return 0
    word = args[0].strip().lower()
    if word not in ("auto", "off"):
        try:
            n = int(word)
        except ValueError:
            n = -1
        if not CPS_MIN <= n <= CPS_MAX:
            say("spark reveal -- the pace is a number, %d..%d, auto, or off" % (CPS_MIN, CPS_MAX))
            return 2
        word = str(n)
    from . import site
    site.set_keys(_file=SPARK_ENV, SPARK_REVEAL=word)
    if word == "off":
        say("replies in chat, explain and bare words now appear as they come")
    elif word == "auto":
        say("replies in chat, explain and bare words now appear at the measured pace, %d a second now" % auto_cps(cfg))
    else:
        say("replies in chat, explain and bare words now appear at %s characters a second" % word)
    return 0


def cmd_reveal(args):
    from spark import page, say
    if args and args[0] in ("-h", "--help", "help"):
        page(USAGE.rstrip())
        return 0
    if len(args) > 1:
        say("spark reveal -- one optional pace: a number, auto, or off")
        return 2
    if sys.stdin.isatty():
        return _standing(args)
    cps = os.environ.get("SPARK_REVEAL_CPS", "")
    if args:
        cps = args[0]
    if cps:
        try:
            cps = int(cps)
        except ValueError:
            cps = -1
        if not CPS_MIN <= cps <= CPS_MAX:
            say("spark reveal -- CPS is a number, %d..%d" % (CPS_MIN, CPS_MAX))
            return 2
    else:
        cps = CPS_DEFAULT
    if len(args) > 1:
        say("spark reveal -- one optional number; the text comes on stdin")
        return 2
    src = getattr(sys.stdin, "buffer", sys.stdin)
    out = getattr(sys.stdout, "buffer", sys.stdout)
    if not sys.stdout.isatty():
        while True:
            chunk = src.read(65536)
            if not chunk:
                break
            out.write(chunk)
            out.flush()
        return 0
    # a character at a time, never mid-codepoint: bytes are decoded
    # incrementally. The pace never owes time: after a gap in the input
    # (the model composing the next line) the clock restarts from now,
    # so a stall is never repaid as a burst -- the burst is what this
    # filter exists to remove.
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    enc = codecs.getincrementalencoder("utf-8")()
    step = 1.0 / cps
    due = time.monotonic()
    while True:
        chunk = os.read(src.fileno(), 4096)
        text = dec.decode(chunk, final=not chunk)
        for ch in text:
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            out.write(enc.encode(ch))
            out.flush()
            due = max(time.monotonic(), due) + step
        if not chunk:
            break
    return 0
