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
#                     heartbeat would pollute a piped match stream. Silence
#                     never hides a line the model did not see: every line
#                     goes to the model once, a look the model was too busy
#                     for (session.once) keeps its lines and is tried again,
#                     and lines that go unseen are said on stderr. stdin
#                     closing ends it (exit 0), Ctrl-C ends it (130).
#   caps              a window is WINDOW_LINES lines or WINDOW_SECS old,
#                     whichever first, at most WATCH_MAX chars to the model,
#                     the oldest lines first; a backlog is several windows.
#                     A live stream gets no more than one model call per
#                     MIN_INTERVAL -- what makes it cheap enough to leave
#                     running -- and a backlog of BACKLOG_LOOKS windows at
#                     most. A file, or a pipe that ended before the first
#                     look, is not live: its windows go back to back, and
#                     one that needs more than FILE_LOOKS_MAX is refused.
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
import stat
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
WATCH_MAX = 8000        # chars of the window the model sees
WATCH_TOKENS = 120      # a match is one short line
WATCH_TIMEOUT = 60
MODE = "watch-stream"   # persona.MODES key
# A finished input (a file, or a pipe that ended before the first look) is
# read whole, its windows back to back. A look costs 5 to 10 seconds on
# the reference box (2 k tokens of prefill at 100 to 270 a second, and a
# short reply), so 60 looks are five to ten minutes: the longest a person
# waits on one answer. Past that, finding a word in a file is grep's job,
# and the refusal says so before the first look.
FILE_LOOKS_MAX = 60
FILE_BYTES = WATCH_MAX * FILE_LOOKS_MAX     # past this a file is refused unread
# A live stream that outruns the model keeps at most this many windows of
# lines waiting, about two minutes of looks at MIN_INTERVAL. A watch
# further behind than that reports history, not the stream; the oldest
# lines past it go unseen, and one stderr line says how many.
BACKLOG_LOOKS = 12
RETRIES = 3             # a look the model was too busy for, tried again at the end
DRAIN_WAIT = 0.05       # seconds a read waits for the rest of a burst
DRAIN_MAX = 2 * FILE_BYTES  # a first read this big and still going is a live stream

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


def _take(lines):
    """The next window from the oldest of `lines`: (the window, how many
    lines it took). At most WINDOW_LINES whole lines whose numbered text
    fits WATCH_MAX; a line longer than that is a window of its own, its
    tail kept."""
    width = len("[%d] " % WINDOW_LINES) + 1
    kept, size = [], 0
    for line in lines[:WINDOW_LINES]:
        if kept and size + len(line) + width > WATCH_MAX:
            break
        if not kept and len(line) + width > WATCH_MAX:
            return [line[-(WATCH_MAX - width):]], 1
        kept.append(line)
        size += len(line) + width
    return kept, len(kept)


def windows(lines):
    """`lines` cut into windows, oldest first: every line in one of them."""
    out, i = [], 0
    while i < len(lines):
        kept, n = _take(lines[i:])
        out.append(kept)
        i += n
    return out


def _full(pending):
    """Does `pending` hold more than one window: one is ready to look at."""
    return bool(pending) and len(windows(pending[:WINDOW_LINES + 1])) > 1


def _bound(pending, looks):
    """Drop the oldest of `pending`, in place, past `looks` windows of
    lines or characters. Returns how many went."""
    width = len("[%d] " % WINDOW_LINES) + 1
    size = sum(len(l) + width for l in pending)
    n = 0
    while pending and (len(pending) - n > looks * WINDOW_LINES or size > looks * WATCH_MAX):
        size -= len(pending[n]) + width
        n += 1
    del pending[:n]
    return n


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


def evaluate(cfg, shell, instruction, kept):
    """One look at the window `kept`: the matched line(s) to stdout, or
    nothing. Returns (looked, hint): looked is False after a transient
    brain gap with nothing named, so the caller keeps the lines for
    another try, and hint says why."""
    reply = io.StringIO()
    fence = textmod.Fence(reply, newline=None)

    def run(s):
        return s.ask_stream(instruction, "Lines:\n" + _numbered(kept), fence.feed,
                            max_tokens=WATCH_TOKENS, timeout=WATCH_TIMEOUT)

    looked, hint = session.once(lambda: session.Session(cfg, MODE, shell, "", role="ember"), run)
    fence.close()
    # a reply cut mid-line (the cap, a dropped stream) is still read: what
    # it names or quotes before the cut is real, and a window it named a
    # line in is not looked at twice
    said = set()
    for row in reply.getvalue().splitlines():
        hit = match(row, kept)
        if hit is None or hit[0] in said:
            continue
        said.add(hit[0])
        sys.stdout.write(say_match(hit[1], kept[hit[0]]) + "\n")
    if said:
        sys.stdout.flush()
    return looked or bool(said), hint


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
    try:
        st = os.fstat(fd)
        if stat.S_ISREG(st.st_mode):
            # a file is not live: read whole, its windows back to back
            if st.st_size > FILE_BYTES:
                return _too_big(-(-st.st_size // WATCH_MAX), st.st_size)
            data = _read_all(fd)
            if len(data) > FILE_BYTES:              # it grew while we read
                return _too_big(-(-len(data) // WATCH_MAX), len(data))
            return _finished(cfg, shell, instruction, _lines(data, True)[0], min_gap)
        return _live(cfg, shell, instruction, fd, win_secs, min_gap)
    except wire.BrainError as e:
        # a transient gap was already ridden out (session.once); this is a
        # rotated token or a broken server -- one line, not a traceback
        print("%s watch -- %s" % (MARK, e.hint), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _read_all(fd):
    """A regular file to its end, or FILE_BYTES and one more read."""
    out = b""
    while len(out) <= FILE_BYTES:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        out += chunk
    return out


def _lines(data, eof):
    """(lines, tail): the whole lines of `data`, the brain's own dropped,
    and the partial line after the last newline -- a line of its own at
    the end of the input."""
    parts = data.split(b"\n")
    tail = parts.pop()
    if eof and tail:
        parts.append(tail)
        tail = b""
    lines = [l for l in (p.decode("utf-8", "replace") for p in parts) if not own_line(l)]
    return lines, tail


def _too_big(looks, size):
    """The refusal before the first look: a finished input past the looks a
    file may take, and what fits instead."""
    print("%s watch -- %s on stdin would take about %d looks of the model, past the %d a file may take: "
          "grep finds a line in it at once, spark read --part N reads 16 kB of it, and "
          "tail -f FILE | spark watch WORDS watches what comes next"
          % (MARK, "%.1f MB" % (size / 1e6) if size >= 1e6 else "%d kB" % max(1, size // 1000), looks,
             FILE_LOOKS_MAX), file=sys.stderr)
    return 2


def _finished(cfg, shell, instruction, lines, min_gap, bound=False):
    """A finished input, every window back to back. A look the model was
    too busy for is tried again RETRIES times, min_gap apart; past that,
    one line names the lines never looked at, exit 1. `bound` (the end of
    a live stream) keeps the newest FILE_LOOKS_MAX windows and says how
    many went unseen; else an input past them is refused unread."""
    wins = windows(lines)
    if len(wins) > FILE_LOOKS_MAX:
        if not bound:
            return _too_big(len(wins), sum(len(l) + 1 for l in lines))
        _unseen(sum(len(w) for w in wins[:-FILE_LOOKS_MAX]))
        wins = wins[-FILE_LOOKS_MAX:]
    for i, kept in enumerate(wins):
        tries = 0
        while True:
            looked, hint = evaluate(cfg, shell, instruction, kept)
            if looked:
                break
            tries += 1
            if tries > RETRIES:
                left = sum(len(w) for w in wins[i:])
                print("! %d line%s never looked at -- %s" % (left, " was" if left == 1 else "s were", hint),
                      file=sys.stderr)
                return 1
            time.sleep(min_gap)
    return 0


def _unseen(n):
    """The one line that says lines went by and the model never saw them."""
    if n:
        print("! %d line%s went by unseen: the stream outran the model -- a file reads whole as "
              "spark watch WORDS < FILE" % (n, "" if n == 1 else "s"), file=sys.stderr, flush=True)
    return 0


def _live(cfg, shell, instruction, fd, win_secs, min_gap):
    """A live stream: a window when it is full or old enough, one look per
    min_gap at most, the oldest lines first. A look the model was too
    busy for keeps its lines for the next. A backlog past BACKLOG_LOOKS
    windows loses its oldest lines, said on stderr. A pipe that ended
    before the first look was a finished input all along."""
    # monotonic() starts near 0 on some platforms (Apple's 3.9): the first
    # window must never wait the interval out
    pending, opened, last_call, looked_once, dropped = [], None, -min_gap, False, 0
    tail = b""
    while True:
        now = time.monotonic()
        wait = win_secs
        if pending:
            # a look needs both, the window due (full, or old enough) and
            # the interval since the last call run out: wait for the later
            # one, never spin in select while the other runs out
            due_in = 0.0 if (_due(len(pending), opened, now, win_secs) or _full(pending)) else opened + win_secs - now
            wait = min(win_secs, max(0.0, last_call + min_gap - now, due_in))
        ready, _, _ = select.select([fd], [], [], wait)
        eof = False
        if ready:
            # drain what arrived: readline() buffers up to 8 kB, so the
            # rest of a burst would wait for the NEXT arrival to be seen
            # -- select watches the fd, not the TextIOWrapper's buffer;
            # and the rest of a burst still on its way is waited for a
            # moment, so a backlog is cut with all of it in sight
            data = b""
            while len(data) < DRAIN_MAX:
                chunk = os.read(fd, 65536)
                if not chunk:
                    eof = True
                    break
                data += chunk
                if not select.select([fd], [], [], DRAIN_WAIT)[0]:
                    break
            lines, tail = _lines(tail + data, eof)
            if lines and opened is None:
                opened = time.monotonic()
            pending.extend(lines)
            if not eof:
                dropped += _bound(pending, BACKLOG_LOOKS)    # memory stays bounded between looks
        if eof:
            if not looked_once and not dropped:
                return _finished(cfg, shell, instruction, pending, min_gap)
            dropped = _unseen(dropped)
            return _finished(cfg, shell, instruction, pending, min_gap, bound=True)
        now = time.monotonic()
        if not (_due(len(pending), opened, now, win_secs) or _full(pending)) or now - last_call < min_gap:
            continue
        dropped = _unseen(dropped + _bound(pending, BACKLOG_LOOKS))
        kept, n = _take(pending)
        looked, _hint = evaluate(cfg, shell, instruction, kept)
        last_call, looked_once = now, True
        if looked:
            del pending[:n]
            opened = (opened if pending else None)
