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

USAGE = """spark reveal -- stdin to stdout, letter by letter at a reader's pace

  spark reveal [CPS]          characters a second (%d..%d, default %d,
                              or SPARK_REVEAL_CPS)

  at a terminal the text appears as if written by hand, so a slow
  brain's bursts read as a steady line; piped anywhere else it is an
  exact copy, byte for byte. Nothing is sent anywhere.

      spark read <words> < page.txt | spark reveal
""" % (CPS_MIN, CPS_MAX, CPS_DEFAULT)


def cmd_reveal(args):
    from spark import page, say
    if args and args[0] in ("-h", "--help", "help"):
        page(USAGE.rstrip())
        return 0
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
