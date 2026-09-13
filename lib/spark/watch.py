# spark.watch -- contract 14: a live stream, watched for the one thing that matters.
#
# The stream on stdin -- log lines, build output, a running process -- a
# instruction in the words, and one line out when a line matches it; never
# a path. Bare (no words) is refused: a watcher with nothing to watch for
# would narrate the whole stream.
#
#   what grounds it   the one line out quotes the stream. Enforced after
#                     the model, line by line (text.Gate, keep=grounded):
#                     a line whose quote is not among the ones it was shown
#                     is dropped, so "a 500 appeared" cannot fire when none
#                     did. A line that quotes nothing is dropped too.
#   when it stays     silence is the answer when nothing matches -- the
#     silent           normal, healthy state. Nothing on stdout means
#                     watching, not stuck; there is no heartbeat, because a
#                     heartbeat would pollute a piped match stream. A
#                     transient brain gap (down, loading, timeout, cut)
#                     skips the window and the watch goes on (session.once);
#                     stdin closing ends it (exit 0), Ctrl-C ends it (130).
#   caps              a window is WINDOW_LINES lines or WINDOW_SECS old,
#                     whichever first, at most WATCH_MAX chars to the model,
#                     and no more than one model call per MIN_INTERVAL. This
#                     is what makes it cheap enough to leave running.
#   ledger            none. A live stream keeps no record: there is nothing
#                     stable to name, and the next line is the only state
#                     that matters.
#   what leaves       the window's lines and the instruction, to the model
#                     this machine answers from. A production log is never
#                     streamed to a vendor -- this is local in the strongest
#                     sense, the same brain the prompt uses.

import os
import select
import sys
import time

from . import MARK, config, say, session
from . import text as textmod

WINDOW_LINES = 40       # a window closes at this many lines...
WINDOW_SECS = 3.0       # ...or this many seconds old, whichever comes first
MIN_INTERVAL = 1.0      # at most one model call this often -- leave it running
WATCH_MAX = 8000        # chars of the window the model sees (newest kept)
WATCH_TOKENS = 120      # a match is one short line
WATCH_TIMEOUT = 60
MODE = "watch-stream"   # persona.MODES key

WATCH_USAGE = """spark watch -- a live stream, watched for the one thing that matters (contract 14)

  <stream> | spark watch <words>   watch stdin; say nothing until a line
                                   matches <words>, then one line quoting it

  silence is the normal, healthy state; a match is one line, the matching
  text quoted and checked, so it cannot report what is not there. Local
  only: the stream never leaves this machine.
  From a pipe: tail -f app.log | spark watch "a 500 appears"
               journalctl -f  | spark watch "anything about the disk"
"""


def _window(lines):
    """The window's text for the model, newest kept within WATCH_MAX."""
    text = "\n".join(lines)
    return text[-WATCH_MAX:] if len(text) > WATCH_MAX else text


def _due(n_lines, opened, now, secs=WINDOW_SECS):
    """Is the open window ready to look at? Full, or old enough."""
    return n_lines > 0 and (n_lines >= WINDOW_LINES or (opened is not None and now - opened >= secs))


def evaluate(cfg, shell, instruction, window):
    """One look at a window: the grounded match line(s) to stdout, or
    nothing. Returns True when a line was kept (a match), False otherwise
    -- including a transient brain gap, which skips the window silently."""
    def keep(_line, verdict, _misses):
        return verdict == textmod.GROUNDED   # it quotes, and the quote is in the window

    # whole=True: a quote of the stream matches at word boundaries, so
    # "500" cannot ground against a window holding only "1500ms"
    gate = textmod.Gate(sys.stdout, window, keep, whole=True)
    fence = textmod.Fence(gate, newline=None)

    def run(s):
        return s.ask_stream(instruction, "Lines:\n" + window, fence.feed,
                            max_tokens=WATCH_TOKENS, timeout=WATCH_TIMEOUT)

    session.once(lambda: session.Session(cfg, MODE, shell, "", role="ember"), run)
    fence.close()
    gate.close()
    if gate.kept:
        sys.stdout.flush()
    return gate.kept > 0


def cmd_watch(args):
    """Contract 14: the stream on stdin, the instruction in the words, one
    grounded line out when a line matches -- and nothing until then."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(WATCH_USAGE.rstrip())
        return 0
    instruction = " ".join(args).strip()
    if sys.stdin.isatty() or not instruction:
        say(WATCH_USAGE.rstrip())
        say("\n  a question for spark itself is: spark %s" % (instruction or "<words>"))
        return 2
    cfg = config.load()
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    fd = sys.stdin.fileno()
    win_secs = float(os.environ.get("SPARK_WATCH_SECS") or WINDOW_SECS)   # a test seam
    lines, opened, last_call = [], None, 0.0
    tail = b""
    try:
        while True:
            ready, _, _ = select.select([fd], [], [], win_secs)
            now = time.monotonic()
            if ready:
                # drain what arrived: readline() buffers up to 8 kB, so the
                # rest of a burst would wait for the NEXT arrival to be seen
                # -- select watches the fd, not the TextIOWrapper's buffer
                chunk = os.read(fd, 65536)
                if not chunk:                    # EOF: look at the tail, then done
                    if tail:
                        lines.append(tail.decode("utf-8", "replace"))
                    if lines:
                        evaluate(cfg, shell, instruction, _window(lines))
                    return 0
                tail += chunk
                parts = tail.split(b"\n")
                tail = parts.pop()               # a partial line waits for its end
                lines.extend(p.decode("utf-8", "replace") for p in parts)
                if lines and opened is None:
                    opened = now
            if _due(len(lines), opened, now, win_secs) and now - last_call >= MIN_INTERVAL:
                evaluate(cfg, shell, instruction, _window(lines))
                lines, opened, last_call = [], None, now
    except KeyboardInterrupt:
        return 130
