# spark.read -- contract 11: what a source says, and only what it says.
#
# The source on stdin -- a page, a message, a document -- a question in
# the words, the answer raw text out; never a path. Contract 12 proved
# the law's machinery on questions; this is the same gate turned to
# claims: what a model says about a source is checked against the
# source, line by line, before the reader sees it.
#
#   what grounds it   every claim quotes the source. A line whose quotes
#                     are not in the source is dropped (text.Gate), and
#                     so is a line that quotes nothing (text.UNQUOTED):
#                     an unquoted sentence about a source is the model's
#                     own knowledge wearing the source's clothes.
#   when it fails     when the source does not answer, the whole reply is
#                     one line showing the source's own opening words --
#                     composed here, never asked of the model: no "the
#                     text does not say, but generally ...". On stderr,
#                     exit 1, stdout untouched: a client tells "no
#                     answer" from "an answer" by the exit code.
#   the reading       one request a read. The answer's first line is the
#                     model's reading of the source, `[Language, kind]`,
#                     taken out here before the fence and the gate
#                     (Reading): at a terminal stderr shows it
#                     (`reading ... English, essay`), stdout never sees
#                     it, and it is neither kept nor dropped. A first
#                     line that quotes is an answer line.
#   the wait          the source stands first in the request and the
#                     words last, so the engine's prompt cache holds the
#                     source across questions: a second question about
#                     the same source costs its own tokens. --warm sends
#                     that request without the words, for one token, and
#                     prints nothing: a client calls it the moment the
#                     text is known, before the reader types, and the
#                     question's request then processes only its own.
#   caps              READ_MAX chars a part; past that the source is
#                     parts (each carrying PART_OVERLAP chars of the one
#                     before) and `--part N` reads one -- refused with
#                     the count otherwise -- and the answer's first line
#                     names the part it read, always: an answer from
#                     part 2 that does not say so cannot be told from an
#                     answer about the whole.
#   ledger            kind `read`: the questions asked of this source
#                     (--name records them, --ledger lists), so a second
#                     reader sees what has been asked. Nothing
#                     invalidates them -- a source does not change, and
#                     that is what makes it a source; age and `--ledger
#                     clear` are the only ways out. No suppression: a
#                     question asked twice of a source is a fair
#                     question twice, unlike a note declined in a draft.
#                     A warm writes none.
#   what leaves       the source's text and the question, to the model
#                     this machine answers from. No name, no path, no
#                     cwd: --name stays in the ledger on this machine.
#                     A span that looks like a secret (text.SOURCE_SHAPES)
#                     is held back first: the model sees [held].

import os
import sys
import time

from . import MARK, config, die, ledger, log_exc, say, session, wire
from . import text as textmod

READ_MAX = 16000        # the source one part reads
PART_OVERLAP = 400      # a part carries this much of the one before it
MODE = "read-source"    # persona.MODES key
READ_TOKENS = 500
READ_TIMEOUT = 180
OPEN_MAX = 60           # chars of the source the refusal line shows
ASKS = "The reader asks:"      # the words' label, last in the request

READ_USAGE = """spark read -- answers from a text, quoted from it

  spark read <words>          the answer, every line quoting the text
  spark read                  what the text covers
  --part N                    read part N of a long text (16000 characters
                              a part)
  --name NAME                 a name to keep the questions under
  --ledger [clear] [--name NAME]  the questions asked; clear forgets them
  --warm                      send the text ahead and print nothing: the
                              next question about it is answered sooner

  A line that does not quote the text is dropped. When the text does not
  answer, spark shows how it opens and exits 1. Secrets are held back.
  From a pipe: w3m -dump URL | spark read "what is this page for"
"""


def parts_of(n):
    """How many parts a source of n chars is: one up to READ_MAX, then
    one more per stride (READ_MAX minus the overlap) of the excess."""
    if n <= READ_MAX:
        return 1
    return 1 + -(-(n - READ_MAX) // (READ_MAX - PART_OVERLAP))


def part_slice(data, n):
    """Part n, 1-based: READ_MAX chars from its stride, so each part
    opens with the last PART_OVERLAP chars of the one before it."""
    start = (n - 1) * (READ_MAX - PART_OVERLAP)
    return data[start:start + READ_MAX]


def opening(part):
    """The part's own opening words, folded to one line and cut at a
    word: what the refusal shows instead of a model's guess."""
    words = " ".join(part.split())
    if len(words) <= OPEN_MAX:
        return words
    return (words[:OPEN_MAX].rsplit(" ", 1)[0] or words[:OPEN_MAX]) + " ..."


class _Part:
    """The stream under the gate: writes `[part N of M]` once, before the
    first kept line, so a refused round leaves stdout untouched."""

    def __init__(self, stream, header):
        self.stream, self.header = stream, header
        self.first = None       # when the first kept line went out

    def write(self, s):
        if self.first is None:
            self.first = time.monotonic()
        if self.header:
            self.stream.write(self.header + "\n")
            self.header = ""
        self.stream.write(s)

    def flush(self):
        self.stream.flush()


QUOTE_MARKS = "\"'`“”‘’"
READING_MAX = 60        # chars: a first line past it is the answer's


def reading_of(line):
    """`Language, kind` when `line` is the model's reading of the source,
    else None: the bracketed line the brief asks for, or a bare line of
    at most four words with a comma. A line that quotes, runs past
    READING_MAX or ends like a sentence is the answer's."""
    s = line.strip()
    if not s or len(s) > READING_MAX or any(q in s for q in QUOTE_MARKS):
        return None
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return inner if inner and "[" not in inner and "]" not in inner else None
    if "," in s and len(s.split()) <= 4 and not s.endswith((":", ".", "!", "?")):
        return s
    return None


class Reading:
    """The answer's first line, taken out of the stream before the fence
    and the gate: the model's reading of the source (reading_of), told
    to `on_read` once and never written on. A first line that is no
    reading is the answer's and goes on whole, and so does a line that
    runs past READING_MAX before its newline, as it comes. A reply with
    no newline is one line: close() judges it the same way."""

    def __init__(self, stream, on_read=None):
        self.stream, self.on_read = stream, on_read
        self.buf, self.done, self.reading = "", False, ""

    def feed(self, delta):
        if self.done:
            self.stream.feed(delta)
            return
        self.buf += delta
        if "\n" in self.buf:
            line, rest = self.buf.split("\n", 1)
            self.buf, self.done = "", True
            if not self._take(line):
                self.stream.feed(line + "\n")
            if rest:
                self.stream.feed(rest)
        elif len(self.buf) > READING_MAX + 2:
            held, self.buf, self.done = self.buf, "", True
            self.stream.feed(held)

    def _take(self, line):
        reading = reading_of(line)
        if reading is None:
            return False
        self.reading = reading
        if self.on_read:
            self.on_read(reading)
        return True

    def close(self):
        if not self.done and self.buf and not self._take(self.buf):
            self.stream.feed(self.buf)
        self.buf, self.done = "", True


def told(busy):
    """What the reading's line does at a terminal: the pulse cleared,
    then `reading ... Portuguese, fiction` on stderr (session._tell: a
    tty only, nothing in a pipe)."""
    def tell(reading):
        busy.stop()
        session._tell(session.READING_LINE + " " + reading + "\n")
    return tell


def _args(args):
    """(options, words) -- ValueError names a flag that lacks its value."""
    opts = {"name": "", "part": None, "ledger": None, "warm": False}
    words, rest = [], list(args)
    while rest:
        a = rest.pop(0)
        if a == "--ledger":
            opts["ledger"] = "clear" if rest[:1] == ["clear"] else "list"
            if opts["ledger"] == "clear":
                rest.pop(0)
        elif a == "--warm":
            opts["warm"] = True
        elif a in ("--name", "--part"):
            if not rest:
                raise ValueError(a)
            opts[a[2:]] = rest.pop(0)
        else:
            words.append(a)
    return opts, words


def cmd_read(args):
    """Contract 11: the source on stdin, the question in the words, the
    answer raw text out -- every line quoting the source, checked, or
    dropped before the reader sees it."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(READ_USAGE.rstrip())
        return 0
    try:
        opts, words = _args(args)
    except ValueError as e:
        say("%s read -- %s needs a value" % (MARK, e))
        return 2
    name = os.path.basename(textmod.utf8(opts["name"]).strip())
    if opts["ledger"]:
        if opts["ledger"] == "clear":
            try:
                n = ledger.clear(name or None, ledger.KIND_READ)
            except ledger.Refused as e:
                say("%s read --ledger -- %s" % (MARK, e.hint))
                return 2
            if n:
                say("* dropped %d question%s%s" % (n, "" if n == 1 else "s", (" for " + name) if name else ""))
        else:
            for line in ledger.listing(name or None, ledger.KIND_READ,
                                       "no question asked (spark read <words> --name NAME keeps them)",
                                       noun="question"):
                say(line)
        return 0
    want = opts["part"]
    if want is not None:
        try:
            want = int(want)
        except ValueError:
            want = 0
        if want < 1:
            say("%s read -- --part N is a part number, 1 up" % MARK)
            return 2
    piped = not sys.stdin.isatty()
    data = textmod.stdin_text(source=True) if piped else ""
    if piped and not data:
        # a pipe that brought nothing: the command before it wrote to
        # stderr (a usage line, an error) or wrote nothing at all -- say
        # that, not the whole usage (ssh -h | spark read ... read as a
        # misuse of spark read, and explain blamed spark read)
        say("%s read -- the pipe brought no text (an error? put 2>&1 before the |)" % MARK)
        return 2
    if not data:
        # at a terminal with nothing piped in, this is almost always a
        # question meant for the prompt: say where it goes, do not guess
        say(READ_USAGE.rstrip())
        say("\n  to ask spark: spark %s" % (" ".join(words) or "<words>"))
        return 2
    if opts["warm"]:
        # the text sent ahead: nothing printed, nothing kept, exit 0
        try:
            warm(config.load(), data, want)
        except Refused as e:
            if e.code == 2:
                say("%s read -- %s" % (MARK, e.hint))
                return 2
            die(e.hint)
        except wire.BrainError as e:
            die(e.hint)
        return 0
    # the wait at a terminal: a pulse from the request to the first kept
    # line, only where a person watches (text.wait); a reader's wrapper
    # pipes stdout and never sees a frame
    busy = textmod.wait("read")
    try:
        answer(config.load(), data, " ".join(words), _Waited(sys.stdout, busy), want, name,
               on_ask=busy.start, on_read=told(busy))
    except Refused as e:
        busy.stop()
        if e.code == 2:
            say("%s read -- %s" % (MARK, e.hint))
            return 2
        die(e.hint)
    except wire.BrainError as e:
        busy.stop()
        die(e.hint)
    finally:
        busy.stop()
    return 0


class _Waited:
    """A stream under a pulse: the pulse is gone before the first byte."""

    def __init__(self, stream, busy):
        self.stream, self.busy = stream, busy

    def write(self, s):
        self.busy.stop()
        self.stream.write(s)

    def flush(self):
        self.stream.flush()


class Refused(Exception):
    """Contract 11 said no in one line: `hint`, and the exit code a verb
    gives it (2: the invocation, a part that is not there; 1: the world,
    a source too long or one that does not answer)."""

    def __init__(self, hint, code=1):
        super().__init__(hint)
        self.hint, self.code = hint, code


def _cut(data, want):
    """(part, want, total, held, names): the source held back -- every
    span that looks like a secret becomes [held] before the parts, the
    gate and the model see it -- and cut to the part `want`. Refused for
    a long source with no part named (exit 1) and for a part that is not
    there (exit 2), before anything is sent."""
    spans, names = textmod.held_spans(data)
    held = len(spans)
    if held:
        data = textmod.hold_spans(data, spans)
    total = parts_of(len(data))
    if total > 1 and want is None:
        raise Refused("the source is %d characters, %d parts of %d -- read one: --part N"
                      % (len(data), total, READ_MAX))
    if want is not None and want > total:
        raise Refused("the source is %d part%s; there is no part %d"
                      % (total, "" if total == 1 else "s", want), 2)
    want = want or 1
    return part_slice(data, want), want, total, held, names


def context_of(part, question=""):
    """The request's text: the source first under its own label, the
    words last under theirs. So the engine's prompt cache holds the
    source across questions, and a warm's request is this one without
    the words."""
    return "Source:\n" + part + "\n\n" + ASKS + ((" " + question) if question else "")


def answer(cfg, data, question, stream, want=None, name="", on_ask=None, thread=None, on_read=None):
    """Contract 11's core, one law for every caller (spark read, the
    chat's /read): the source `data` held back, cut to the part `want`,
    asked `question` (bare: what it covers), and every line of the
    answer through the gate before it reaches `stream` -- a line that
    does not quote the source, or whose quotes are not in it, never gets
    there. The answer's first line is the model's reading of the source,
    taken out before the gate (Reading) and told to `on_read(reading)`.
    `on_ask()` runs once, right before the request. `thread` (the chat's
    /read) rides the turn record, so `/last` there finds the words.
    Returns the gate's kept count, never 0: nothing kept is Refused, with
    the source's own opening words. Refused before anything is sent for
    a part that is not there; wire.BrainError and KeyboardInterrupt pass
    through, the stream closed first."""
    part, want, total, held, names = _cut(data, want)
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    text = question.strip() or "What does this source cover?"
    if held:        # said once nothing can refuse any more: the source is on its way
        print(textmod.held_line(held, names), file=sys.stderr, flush=True)
    if on_ask:
        on_ask()

    def keep(_line, verdict, _misses):
        return verdict == textmod.GROUNDED  # it quotes, and a quote anchors

    header = "[part %d of %d]" % (want, total) if total > 1 else ""
    out = _Part(stream, header)
    gate = textmod.Gate(out, part, keep)
    fence = textmod.Fence(gate, newline=None)
    first = Reading(fence, on_read)

    def done():
        first.close()
        fence.close()
        gate.close()
    t0 = time.monotonic()
    try:
        s = session.Session(cfg, MODE, shell, "", role="ember")
        _out, _ms = s.ask_stream("", context_of(part, text), first.feed, max_tokens=READ_TOKENS, timeout=READ_TIMEOUT)
    except (wire.BrainError, KeyboardInterrupt):
        done()
        raise
    done()
    ms = int((time.monotonic() - t0) * 1000)
    if gate.kept and name:
        # the record a second reader sees: what was asked, of which part
        note = ("part %d of %d: " % (want, total) if total > 1 else "") + text
        try:
            ledger.keep(ledger.KIND_READ, name, note, cfg)
        except (ledger.Refused, OSError):
            log_exc("read ledger")
    # Both times start before the answer's session setup; ledger writes
    # are not output.
    first_ms = {"first_ms": int((out.first - t0) * 1000)} if out.first is not None else {}
    s.record(kind="read", chars=len(part), ms=ms, part=want, parts=total,
             kept=gate.kept, dropped=gate.dropped, quotes=gate.quoted, unanchored=gate.missed,
             **dict(first_ms, **({"held": held} if held else {}), **({"thread": thread} if thread else {})))
    if not gate.kept:
        where = "part %d of %d" % (want, total) if total > 1 else "the source"
        raise Refused('%s does not answer -- it opens: "%s"' % (where, opening(part)))
    return gate.kept


def warm(cfg, data, want=None):
    """The text sent ahead (--warm): the same source, held back and cut
    to the same part, in the answer's request shape without the words,
    for one token. The engine's slot then holds the source, and the
    question's request processes only its own tokens. Nothing is
    printed, the turn is kind `warm`, numbers only, and no ledger record
    is written. Refused as answer() is for a part that is not there.
    Returns the part count."""
    part, want, total, held, _names = _cut(data, want)
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    t0 = time.monotonic()
    s = session.Session(cfg, MODE, shell, "", role="ember")
    s.ask_stream("", context_of(part), lambda _delta: None, max_tokens=1, timeout=READ_TIMEOUT)
    s.record(kind="warm", chars=len(part), ms=int((time.monotonic() - t0) * 1000), part=want, parts=total,
             **({"held": held} if held else {}))
    return total
