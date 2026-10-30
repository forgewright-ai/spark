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
#                     own knowledge wearing the source's clothes. A line
#                     that is the source's own words, copied whole,
#                     quotes it (text.Ground.verbatim).
#   when it fails     when the source does not answer, the whole reply is
#                     one line showing the source's own opening words --
#                     composed here, never asked of the model: no "the
#                     text does not say, but generally ...". On stderr,
#                     exit 1, stdout untouched: a client tells "no
#                     answer" from "an answer" by the exit code.
#   the reading       one request a part read. The answer's first line is
#                     the model's reading of the source, `[Language, kind]`,
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
#                     before) and `--part N` reads one. Without it spark
#                     picks: the parts ranked here by the question's
#                     words (ranked: BM25 over their passages, no
#                     model), the best read
#                     first and the next only when it does not answer,
#                     TRIES at most -- a bare question reads part 1.
#                     The answer's first line names the part it read,
#                     always: an answer from part 2 that does not say so
#                     cannot be told from an answer about the whole.
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

import math
import os
import re
import sys
import time

from . import MARK, config, die, ledger, log_exc, say, session, wire
from . import text as textmod

READ_MAX = 16000        # the source one part reads
PART_OVERLAP = 400      # a part carries this much of the one before it
# Parts one question reads when spark picks them: each is a whole
# request, about 10 s of a 16000-character prefill on a CPU box, so the
# second is read only when the first does not answer, and no third.
TRIES = 2
K1, B = 1.2, 0.75       # BM25's saturation and length weight, the textbook pair
# The ranking scores passages, not whole parts: a paragraph, one longer
# than PASSAGE cut into pieces, and a part scores the sum of its BEST.
PASSAGE = 600
BEST = 3
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


_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
# One thing said in everyday words, a named line each: a reader asks about
# "my other computer" where the guide says "another machine". The ranking
# counts a part's word of the same line as the reader's own, at SAME_WEIGHT:
# the reader's own word still counts the most. One word a line, never two
# (no "get back"), and only words that mean the same in a manual, a mail and
# a contract alike: no "list" (a man page's file list), "image" (a disk's),
# "end" or "make", and no "stop" ("stop root from logging in" is prevent,
# where sshd's "terminate" is a connection's end).
SAME = (
    ("machine", "computer host pc laptop"),
    ("directory", "folder dir"),
    ("delete", "remove erase rm unlink"),
    ("start", "launch begin"),
    ("show", "display"),
    ("change", "modify alter"),
    ("error", "failure fail fault"),
    ("restore", "recover recovery"),
    ("picture", "photo pic"),
    ("price", "cost fee"),
    ("disk", "drive"),
    ("copy", "duplicate cp"),
)
SAME_WEIGHT = 0.5


def _terms(s):
    """The words a passage is ranked by: intake's one tokenizer, a camelCase
    word split first (sshd_config's PasswordAuthentication holds
    "password")."""
    from . import intake        # here: a source of one part never pays the import
    return intake.words(_CAMEL.sub(r"\1 \2", s))


def _key(term):
    """A term with a doubled last consonant and then a closing e off, so a
    word's forms meet: intake's stem takes "deleting" and "deleted" to
    "delet" and leaves "delete", and takes "logging" to "logg"."""
    if len(term) > 3 and term[-1] == term[-2] and term[-1] not in "aeiou":
        term = term[:-1]
    return term[:-1] if len(term) > 3 and term.endswith("e") else term


def _same_of():
    """{key: the keys of its SAME line}, the words keyed as a passage's are."""
    out = {}
    for head, rest in SAME:
        keys = frozenset(_key(t) for w in [head] + rest.split() for t in _terms(w))
        for k in keys:
            out[k] = keys
    return out


def passages(part):
    """The pieces of a part the ranking scores: its paragraphs (a blank
    line between two), one longer than PASSAGE characters cut into
    pieces of at most that, at a space where there is one."""
    out = []
    for para in re.split(r"\n\s*\n", part):
        while len(para) > PASSAGE:
            cut = max(para.rfind(" ", 1, PASSAGE + 1), para.rfind("\n", 1, PASSAGE + 1))
            cut = cut if cut > 0 else PASSAGE
            out.append(para[:cut])
            para = para[cut:]
        if para.strip():
            out.append(para)
    return out


def ranked(data, question):
    """The parts of `data` to read for `question`, best first: BM25 over
    the parts' passages by the question's words, a part scoring the sum
    of its BEST passages, ties to the earlier part, a part holding none
    of them left out. A word's rarity is counted over the passages, not
    the parts: a man page says its topic in every part, and counted over
    three parts that word weighed next to nothing, so one stray word in
    another part outranked the part that answers (#160). A word of the
    question's SAME line counts too, at SAME_WEIGHT, and the line is one
    term to BM25 (its rarity is the line's, not the word's). One part, a
    bare question, or words no part holds (another language) is [1]."""
    total = parts_of(len(data))
    asked = list(dict.fromkeys(_key(t) for t in _terms(question)))
    if total == 1 or not asked:
        return [1]
    same = _same_of()
    owner, counts, lens = [], [], []
    for n in range(1, total + 1):
        for p in passages(part_slice(data, n)):
            words = _terms(p)
            if not words:
                continue
            tf = {}
            for w in words:
                k = _key(w)
                tf[k] = tf.get(k, 0) + 1
            owner.append(n)
            counts.append(tf)
            lens.append(len(words))
    if not counts:
        return [1]
    avg = sum(lens) / float(len(lens))

    def weight(tf, k):
        """The question's term `k` in a passage: its own count, plus its
        SAME line's other words at SAME_WEIGHT."""
        return tf.get(k, 0) + SAME_WEIGHT * sum(tf.get(o, 0) for o in same.get(k, ()) if o != k)
    idf = {}
    for k in asked:
        df = sum(1 for c in counts if weight(c, k))
        idf[k] = math.log(1 + (len(counts) - df + 0.5) / (df + 0.5))
    best = {}
    for n, tf, ln in zip(owner, counts, lens):
        score = 0.0
        for k in asked:
            f = weight(tf, k)
            if f:
                score += idf[k] * f * (K1 + 1) / (f + K1 * (1 - B + B * ln / avg))
        if score > 0:
            best.setdefault(n, []).append(score)
    scores = [(sum(sorted(s, reverse=True)[:BEST]), n) for n, s in best.items()]
    return [n for _score, n in sorted(scores, key=lambda s: (-s[0], s[1]))] or [1]


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


def turned(busy):
    """What a turn to the next part does at a terminal: the pulse
    cleared, then `reading ... part 5 of 6, part 4 does not answer`
    (a tty only); the next request starts the pulse again."""
    def tell(part, nxt, total):
        busy.stop()
        session._tell("%s part %d of %d, part %d does not answer\n" % (session.READING_LINE, nxt, total, part))
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
        # misuse of spark read, and explain blamed spark read). On
        # stderr: stdout is the answer's, and a reader's wrapper that
        # piped an empty page must not show this line as its answer
        print("%s read -- the pipe brought no text (an error? put 2>&1 before the |)" % MARK,
              file=sys.stderr, flush=True)
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
               on_ask=busy.start, on_read=told(busy), on_next=turned(busy))
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


def _cut(data, want, question=""):
    """(data, plan, total, held, names): the source held back -- every
    span that looks like a secret becomes [held] before the parts, the
    gate and the model see it -- and the parts to read, in order: the
    part `want` alone when one is named, else the best TRIES for
    `question` (ranked). Refused for a part that is not there (exit 2),
    before anything is sent."""
    spans, names = textmod.held_spans(data)
    held = len(spans)
    if held:
        data = textmod.hold_spans(data, spans)
    total = parts_of(len(data))
    if want is not None and want > total:
        raise Refused("the source is %d part%s; there is no part %d"
                      % (total, "" if total == 1 else "s", want), 2)
    plan = [want] if want is not None else ranked(data, question)[:TRIES]
    return data, plan, total, held, names


def context_of(part, question=""):
    """The request's text: the source first under its own label, the
    words last under theirs. So the engine's prompt cache holds the
    source across questions, and a warm's request is this one without
    the words."""
    return "Source:\n" + part + "\n\n" + ASKS + ((" " + question) if question else "")


def answer(cfg, data, question, stream, want=None, name="", on_ask=None, thread=None, on_read=None,
           on_next=None):
    """Contract 11's core, one law for every caller (spark read, the
    chat's /read): the source `data` held back, cut to the part `want`
    (none named: the parts ranked for the question, the next read only
    when one does not answer), asked `question` (bare: what it covers),
    and every line of the answer through the gate before it reaches
    `stream` -- a line that does not quote the source, or whose quotes
    are not in it, never gets there. The answer's first line is the
    model's reading of the source, taken out before the gate (Reading)
    and told to `on_read(reading)`, once. `on_ask()` runs right before
    each request, `on_next(part, nxt, total)` between two. `thread` (the
    chat's /read) rides the turn record, so `/last` there finds the
    words. Returns (n, part): the number and the text, held back, of the
    part that answered -- what the chat's thread keeps for the turn
    after. Nothing kept is Refused, with the source's own opening words,
    or with the parts read and the remedy. Refused before anything is sent for a part that is
    not there; wire.BrainError and KeyboardInterrupt pass through, the
    stream closed first."""
    data, plan, total, held, names = _cut(data, want, question)
    text = question.strip() or "What does this source cover?"
    if held:        # said once nothing can refuse any more: the source is on its way
        print(textmod.held_line(held, names), file=sys.stderr, flush=True)
    for i, n in enumerate(plan):
        if i and on_next:
            on_next(plan[i - 1], n, total)
        part = part_slice(data, n)
        if _ask(cfg, part, n, total, text, stream, name=name, on_ask=on_ask,
                thread=thread, on_read=on_read if i == 0 else None, held=held):
            return n, part
    if total == 1 or len(plan) == total:
        raise Refused('the source does not answer -- it opens: "%s"' % opening(part_slice(data, 1)))
    if want is not None:
        raise Refused('part %d of %d does not answer -- it opens: "%s"'
                      % (want, total, opening(part_slice(data, want))))
    which = " and ".join(str(n) for n in plan)
    raise Refused("part%s %s of %d %s not answer -- read another: --part N"
                  % ("s" if len(plan) > 1 else "", which, total, "do" if len(plan) > 1 else "does"))


# A figure of two digits or more that a line states outside its quotes
# must be the source's own (`unsourced`): a sum, a count or a date the
# model worked out is its own claim wearing the source's quote, and a
# one-word quote grounds a line since v1.101. One digit stays free, as a
# source writes "two years" where a line says 2.
FIGURE = re.compile(r"(?<!\w)\d[\d.,]*\d")


def figures(text):
    """The figures in `text`, two digits or more, their separators out:
    "5,200" and "5200" are one figure, and a decimal part's whole counts
    too ("4.800,00" holds 4800)."""
    got = set()
    for m in FIGURE.finditer(text):
        n = m.group(0).strip(".,")
        got.add(re.sub(r"[.,]", "", n))
        cents = re.match(r"^(.*?)[.,](\d{2})$", n)
        if cents:
            got.add(re.sub(r"[.,]", "", cents.group(1)))
    return {g for g in got if len(g) >= 2}


def unsourced(line, have):
    """The figures `line` states outside its quotes that the source does
    not hold (`have`, the source's figures)."""
    bare = line
    for q in textmod.quotes(line):
        bare = bare.replace(q[0], " ")
    return figures(bare) - have


def _ask(cfg, part, want, total, text, stream, name="", on_ask=None, thread=None, on_read=None, held=0):
    """One request: `part` (part `want` of `total`) asked `text`, the
    answer through the gate to `stream`, the turn recorded (`held` the
    source's held spans), the ledger written when a line was kept.
    Returns the kept count."""
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    if on_ask:
        on_ask()

    have = figures(part)

    def keep(line, verdict, _misses):
        # it quotes, a quote anchors, and every figure it states is the source's
        return verdict == textmod.GROUNDED and not unsourced(line, have)

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
    return gate.kept


def warm(cfg, data, want=None):
    """The text sent ahead (--warm): the same source, held back and cut
    to the same part, in the answer's request shape without the words,
    for one token. The engine's slot then holds the source, and the
    question's request processes only its own tokens. Nothing is
    printed, the turn is kind `warm`, numbers only, and no ledger record
    is written. Refused as answer() is for a part that is not there, and
    for a long source with no part named (exit 1, nothing sent): the
    part a question reads is the one its words pick, and a warm has no
    words, so a 16 kB prefill of part 1 would go mostly unused. Returns
    the part count."""
    data, plan, total, held, _names = _cut(data, want)
    if total > 1 and want is None:
        raise Refused("the source is %d characters, %d parts of %d -- read one: --part N"
                      % (len(data), total, READ_MAX))
    want = plan[0]
    part = part_slice(data, want)
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    t0 = time.monotonic()
    s = session.Session(cfg, MODE, shell, "", role="ember")
    s.ask_stream("", context_of(part), lambda _delta: None, max_tokens=1, timeout=READ_TIMEOUT)
    s.record(kind="warm", chars=len(part), ms=int((time.monotonic() - t0) * 1000), part=want, parts=total,
             **({"held": held} if held else {}))
    return total
