# spark.watch -- contract 14: a live stream, watched for the one thing that matters.
#
# The stream on stdin -- log lines, build output, a running process -- a
# instruction in the words, and one line out when a line matches it; never
# a path. Bare (no words) is refused: a watcher with nothing to watch for
# would narrate the whole stream.
#
#   what grounds it   the one line out quotes the stream, and spark writes
#                     the quote, never the model. The window goes numbered;
#                     the model names a line by its number and says a few
#                     words, and spark prints that line from the window. A
#                     number the window does not hold prints nothing, so "a
#                     500 appeared" cannot fire when none did. The number
#                     counts only where the brief puts it, at the reply's
#                     start. A quote the window holds wins over any number:
#                     escaped quotes and a quote cut by the reply's cap
#                     included, that line is the one printed. So does a
#                     log line the model copied whole. A reply that names
#                     no line, or says nothing matches, is dropped.
#   when it stays     silence is the answer when nothing matches -- the
#     silent           normal, healthy state. Nothing on stdout means
#                     watching, not stuck; there is no heartbeat, because a
#                     heartbeat would pollute a piped match stream. A
#                     transient brain gap (down, loading, busy, timeout, cut)
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

import io
import os
import re
import select
import sys
import time

from . import MARK, config, say, session, wire
from . import text as textmod

WINDOW_LINES = 40       # a window closes at this many lines...
WINDOW_SECS = 10.0      # ...or this many seconds old, whichever comes first
MIN_INTERVAL = 10.0     # at most one model call this often -- leave it running
# The watcher must never watch itself. spark's own units log into the
# journal (spark-serve carries llama-server's every slot and task line;
# spark-forge its requests), and a `journalctl -f | spark watch` would
# feed the brain's own inference back to it -- each look writing the
# lines that trigger the next look, the GPU pinned, the info lines
# quoted as failures (seen on the box, 2026-09-21). A journal line whose
# identifier is spark's, and a bare llama-server log line, are dropped
# before the window; a window of only those is no call at all.
OWN_LINE = re.compile(r"(?:^|\s)spark\[\d+\]:\s|(?:^|\s)\d+\.\d{2}\.\d{3}\.\d{3} [IWEDV] (?:srv|slot|main|load|init|sched|update|launch|que|log)\b")
WATCH_MAX = 8000        # chars of the window the model sees (newest kept)
WATCH_TOKENS = 120      # a match is one short line
WATCH_TIMEOUT = 60
MODE = "watch-stream"   # persona.MODES key

WATCH_USAGE = """spark watch -- one line when a stream matches what you ask

  <stream> | spark watch <words>   say nothing until a line matches the
                                   words, then one line quoting it

  From a pipe: tail -f app.log | spark watch "a 500 appears"
               journalctl -f  | spark watch "anything about the disk"
"""


def own_line(line):
    """Is this the brain's own log line (spark's units in the journal, or
    llama-server's log shape)? Never shown to the model."""
    return bool(OWN_LINE.search(line))


def _window(lines):
    """The lines the model sees: the newest whole lines whose numbered text
    fits WATCH_MAX. One line longer than that alone keeps its tail."""
    width = len("[%d] " % len(lines)) + 1
    kept, size = [], 0
    for line in reversed(lines):
        if kept and size + len(line) + width > WATCH_MAX:
            break
        if not kept and len(line) + width > WATCH_MAX:
            line = line[-(WATCH_MAX - width):]
        kept.append(line)
        size += len(line) + width
    kept.reverse()
    return kept


def _numbered(kept):
    """The window as the model reads it: [1] the oldest line, one a line."""
    return "\n".join("[%d] %s" % (n, line) for n, line in enumerate(kept, 1))


# A reply names its line where the brief asks, at its very start:
# `[12] the disk is full`. A number anywhere else is the model's prose or
# a log line's own text (`worker [3] crashed`), never a line number.
_REF = re.compile(r"^\s*\[(\d{1,5})\]")
_REFS = re.compile(r"(?<!\S)\[\d{1,5}\]")
# A reply that says no line matches names none, whatever number it
# mentions ("nothing matches; the closest is [14]").
_NONE = re.compile(r"\b(?:nothing|none|no lines?)\s+(?:\w+\s+){0,3}?match(?:es|ed)?\b"
                   r"|\bno match(?:es)?\b|\bnothing (?:yet|found|to report)\b", re.I)
_OPEN, _CLOSE = '"\u201c', '"\u201d'
WATCH_WORDS = 120       # the model's own words before the line, at most


def _quoted(row):
    """(words, candidates, cut): the text before the reply's first quote
    mark, then what it quotes, the widest first -- the run from its first
    quote mark to its last, the line it copied with that line's own quotes
    inside, escaped or not -- then each plain span. `cut` says the reply
    ended inside its quote: the reply's token cap took the rest."""
    row = row.replace('\\"', '"')
    starts = [i for i in (row.find(c) for c in _OPEN) if i >= 0]
    if not starts:
        return row, [q[0] for q in textmod.quotes(row)], False
    first = min(starts)
    last = max(row.rfind(c) for c in _CLOSE)
    cut = last <= first
    wide = row[first + 1:] if cut else row[first + 1:last]
    return row[:first], [wide] + [q[0] for q in textmod.quotes(row)], cut


def _holds(span, kept):
    """The index of the newest window line that holds `span` at word
    boundaries, or None. A span that opens with the window's own number
    (`[3] GET /x 500`, a quote of the numbered window) holds when line 3
    holds the rest."""
    span = span.strip()
    if textmod.substantial(span):
        for i in range(len(kept) - 1, -1, -1):
            if textmod.anchor(span, kept[i]):
                return i
    m = _REF.match(span)
    if m and 1 <= int(m.group(1)) <= len(kept):
        rest = span[m.end():].strip()
        if textmod.substantial(rest) and textmod.anchor(rest, kept[int(m.group(1)) - 1]):
            return int(m.group(1)) - 1
    return None


def _line_of(span, kept, cut=False):
    """_holds for a quote; a span the reply's cap cut mid-word holds up to
    its last whole word."""
    i = _holds(span, kept)
    if i is None and cut and " " in span.strip():
        i = _holds(span.rstrip().rsplit(" ", 1)[0], kept)
    return i


def _copied(row, kept, led):
    """The index of the window line the reply is a copy of, unquoted, or
    None. A reply that opens with a number is a copy when the whole of it
    is in a line ("[12] cache warmed", the line's own number); one without
    is a copy when it is that line's own words, verbatim (text.Ground)."""
    row = row.strip()
    for i in range(len(kept) - 1, -1, -1):
        if (textmod.substantial(row) and textmod.anchor(row, kept[i]) if led
                else textmod.Ground(kept[i]).verbatim(row)):
            return i
    return None


def match(row, kept):
    """(index, words) for one reply line, or None: the window line it
    quotes, copies or names by the number it opens with, and the model's
    own words. A reply that says nothing matches names no line."""
    if _NONE.search(row):
        return None
    words, spans, cut = _quoted(row)
    for k, span in enumerate(spans):        # a quote the window holds wins over any number
        i = _line_of(span, kept, cut and k == 0)
        if i is not None:
            return i, words
    m = _REF.match(row)
    i = _copied(row, kept, bool(m))
    if i is not None:
        return i, ""
    if m and 1 <= int(m.group(1)) <= len(kept):
        n = int(m.group(1)) - 1
        rest = row[m.end():]
        for c in _OPEN + "`":
            rest = rest.split(c, 1)[0]
        if textmod.substantial(rest) and textmod.anchor(rest.strip(), kept[n]):
            return n, ""                     # the numbered window's own row, copied
        return n, _REFS.sub(" ", rest)
    return None


def say_match(words, line):
    """The line out: the model's few words, then the stream's own line."""
    words = textmod.scrub(" ".join(words.split()), keep="").strip(" :;,.-\u2013\u2014")
    if len(words) > WATCH_WORDS:
        words = words[:WATCH_WORDS].rsplit(" ", 1)[0]
    line = textmod.scrub(line, keep="\t")
    return '%s: "%s"' % (words, line) if words else '"%s"' % line


def _due(n_lines, opened, now, secs=WINDOW_SECS):
    """Is the open window ready to look at? Full, or old enough."""
    return n_lines > 0 and (n_lines >= WINDOW_LINES or (opened is not None and now - opened >= secs))


def evaluate(cfg, shell, instruction, lines):
    """One look at a window: the matched line(s) to stdout, or nothing.
    Returns True when a line was printed (a match), False otherwise --
    including a transient brain gap, which skips the window silently."""
    kept = _window(lines)
    reply = io.StringIO()
    fence = textmod.Fence(reply, newline=None)

    def run(s):
        return s.ask_stream(instruction, "Lines:\n" + _numbered(kept), fence.feed,
                            max_tokens=WATCH_TOKENS, timeout=WATCH_TIMEOUT)

    # a reply cut mid-line (the cap, a dropped stream) is still read: what
    # it names or quotes before the cut is real
    session.once(lambda: session.Session(cfg, MODE, shell, "", role="ember"), run)
    fence.close()
    said = set()
    for row in reply.getvalue().splitlines():
        hit = match(row, kept)
        if hit is None or hit[0] in said:
            continue
        said.add(hit[0])
        sys.stdout.write(say_match(hit[1], kept[hit[0]]) + "\n")
    if said:
        sys.stdout.flush()
    return bool(said)


def cmd_watch(args):
    """Contract 14: the stream on stdin, the instruction in the words, one
    grounded line out when a line matches -- and nothing until then."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(WATCH_USAGE.rstrip())
        return 0
    instruction = " ".join(args).strip()
    if sys.stdin.isatty() or not instruction:
        say(WATCH_USAGE.rstrip())
        say("\n  to ask spark: spark %s" % (instruction or "<words>"))
        return 2
    cfg = config.load()
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    fd = sys.stdin.fileno()
    win_secs = float(os.environ.get("SPARK_WATCH_SECS") or WINDOW_SECS)   # a test seam
    min_gap = float(os.environ.get("SPARK_WATCH_INTERVAL") or MIN_INTERVAL)
    # monotonic() starts near 0 on some platforms (Apple's 3.9): the first
    # window must never wait the interval out
    lines, opened, last_call = [], None, -min_gap
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
                    if tail and not own_line(tail.decode("utf-8", "replace")):
                        lines.append(tail.decode("utf-8", "replace"))
                    if lines:
                        evaluate(cfg, shell, instruction, lines)
                    return 0
                tail += chunk
                parts = tail.split(b"\n")
                tail = parts.pop()               # a partial line waits for its end
                lines.extend(p for p in (q.decode("utf-8", "replace") for q in parts) if not own_line(p))
                if lines and opened is None:
                    opened = now
            if _due(len(lines), opened, now, win_secs) and now - last_call >= min_gap:
                evaluate(cfg, shell, instruction, lines)
                lines, opened, last_call = [], None, now
    except wire.BrainError as e:
        # a transient gap was already ridden out (session.once); this is a
        # rotated token or a broken server -- one line, not a traceback
        print("%s watch -- %s" % (MARK, e.hint), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
