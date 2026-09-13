# spark.text -- wrap a streamed answer at the terminal's width, a word at a
# time, keeping the model's own line breaks. A line beginning with four
# spaces or a ``` fence is left verbatim, unwrapped, to its own end (code,
# already-formatted output). The mark (glyph("hammer") + " ") prints once,
# before the first character; close() writes it alone when nothing arrived.

import re
import shutil
import sys

from . import glyph


class Wrap:
    """feed(delta) a chunk at a time; close() when the stream ends. Width is
    the terminal's columns at a tty, 80 when piped (an explicit isatty
    check, not the COLUMNS environment, which leaks into test subprocesses).
    `col` (the cursor's column) and `need_space` (a space is owed before the
    next word) are kept apart so the mark's own trailing space is never
    doubled."""

    def __init__(self, stream=sys.stdout, mark=True):
        self.stream = stream
        self.mark = mark
        self.width = shutil.get_terminal_size((80, 24)).columns if stream.isatty() else 80
        self.col = 0
        self.need_space = False
        self.started = False
        self.word = ""            # the word being built
        self.line_head = ""       # a line's first chars, while undecided
        self.deciding = True      # still buffering line_head
        self.verbatim = False     # this line passes through unwrapped

    def _start(self):
        if not self.started:
            self.started = True
            if self.mark:
                m = glyph("hammer") + " "
                self.stream.write(m)
                self.col += len(m)

    def _word_out(self, w):
        if not w:
            return
        self._start()
        if self.need_space:
            if self.col + 1 + len(w) > self.width - 1:
                self.stream.write("\n")
                self.col = 0
            else:
                self.stream.write(" ")
                self.col += 1
        self.stream.write(w)
        self.col += len(w)
        self.need_space = True
        self.stream.flush()

    def _char(self, ch):
        if self.verbatim:
            self._start()
            self.stream.write(ch)
            self.col += 1
            self.stream.flush()
            return
        if ch == " ":
            if self.word:
                self._word_out(self.word)
                self.word = ""
            self.need_space = True
        else:
            self.word += ch

    def _new_line(self):
        if self.deciding and self.line_head:
            self.deciding = False
            pending, self.line_head = self.line_head, ""
            for ch in pending:
                self._char(ch)
        if self.word:
            self._word_out(self.word)
            self.word = ""
        self._start()
        self.stream.write("\n")
        self.stream.flush()
        self.col = 0
        self.need_space = False
        self.verbatim = False
        self.line_head = ""
        self.deciding = True

    def feed(self, delta):
        for ch in delta:
            if ch == "\n":
                self._new_line()
                continue
            if self.deciding:
                self.line_head += ch
                spaces = self.line_head == " " * len(self.line_head)
                fence = self.line_head == "`" * len(self.line_head)
                if spaces and len(self.line_head) < 4:
                    continue
                if fence and len(self.line_head) < 3:
                    continue
                self.deciding = False
                self.verbatim = spaces or fence
                pending, self.line_head = self.line_head, ""
                if self.verbatim:
                    self._start()
                    self.stream.write(pending)
                    self.col += len(pending)
                    self.stream.flush()
                else:
                    for c2 in pending:
                        self._char(c2)
                continue
            self._char(ch)

    def close(self):
        if self.deciding and self.line_head:
            self.deciding = False
            pending, self.line_head = self.line_head, ""
            for ch in pending:
                self._char(ch)
        if self.word:
            self._word_out(self.word)
            self.word = ""
        self._start()
        self.stream.write("\n")
        self.stream.flush()


class Fence:
    """The editor's stream: raw text, no mark, no width -- only a code
    fence the model wrapped the answer in is removed. feed(delta) holds the
    first line back until its newline (a first line that is only a fence,
    with or without a language word, is dropped) and always keeps a short
    tail unwritten in case it is the start of a closing fence; close()
    drops a closing fence at the very end and writes the rest."""

    HOLD = 4          # "\n```" -- the longest prefix of a closing fence

    def __init__(self, stream=sys.stdout, newline=None):
        """newline=True ends the output with exactly one newline, False with
        none, None leaves it as the model sent it -- a rewrite keeps the
        selection's own final-newline shape, whatever the model did."""
        self.stream = stream
        self.newline = newline
        self.buf = ""
        self.first = True     # still deciding about the first line
        self.last = ""        # the last character written

    def _write(self, s):
        if s:
            self.stream.write(s)
            self.stream.flush()
            self.last = s[-1]

    FENCE = re.compile(r"^\s*```[A-Za-z0-9_+.-]*\s*$")

    @classmethod
    def _is_fence(cls, line):
        return bool(cls.FENCE.match(line))

    def feed(self, delta):
        self.buf += delta
        if self.first:
            nl = self.buf.find("\n")
            if nl < 0:
                return
            self.first = False
            if self._is_fence(self.buf[:nl]):
                self.buf = self.buf[nl + 1:]
        if len(self.buf) > self.HOLD:
            self._write(self.buf[:-self.HOLD])
            self.buf = self.buf[-self.HOLD:]

    def close(self):
        rest = self.buf
        self.buf = ""
        if self.first and self._is_fence(rest):
            rest = ""
        stripped = rest.rstrip()
        if stripped.endswith("```"):
            cut = stripped[:-3]
            nl = cut.rfind("\n")
            if nl >= 0 and cut[nl + 1:].strip() == "":
                rest = cut[:nl + 1]
            elif cut.strip() == "":
                rest = ""
        if self.newline is False:
            rest = rest.rstrip("\n")
        elif self.newline is True:
            rest = rest.rstrip("\n")
            if rest:
                rest += "\n"
            elif self.last and self.last != "\n":
                rest = "\n"
        self._write(rest)


# ------------------------------------------------------------- anchors
# A `?` answer points at the text by quoting it; a quote the text does
# not contain is a fabrication (an earlier tool of ours misquoted "plum"
# as "plume"). Every quoted span on every line is checked against the
# text the question was about, and the ones that do not anchor are
# marked where they stand, so the reader (and the editor's jump key)
# knows which quotes to trust.
QUOTE = re.compile(r'"([^"\n]{3,200})"|“([^”\n]{3,200})”|`([^`\n]{3,200})`')
ANCHOR_MARK = " [not in the text]"
PROPOSED_MARK = " [proposed]"


PROPOSAL = re.compile(r"(->|→|=>)\s*$")


def quotes(line):
    """[(span, start, end)] -- every quoted span on one line (double
    quotes, curly double quotes or backticks; 3..200 chars) with the index
    of its opening mark and the one just past its closing mark. A span
    right after an arrow (`"was" -> "should be"`) is the model's own
    proposal, not a quote of the text: left out."""
    return [(m.group(m.lastindex), m.start(), m.end()) for m in QUOTE.finditer(line)
            if not PROPOSAL.search(line[:m.start()])]


_MARKS = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "'": '"'})


def fold(s):
    """Whitespace runs to one space, every quote mark to ", lower case:
    the shapes a faithful quote may still differ in (a line break, a
    capital at the start of a sentence, "hum" written 'hum'). Public: the
    grounded contracts fold their own units this way too."""
    return " ".join(s.split()).translate(_MARKS).lower()


# The floor a span must clear to count as grounding evidence: after
# fold, at least two words or twelve characters, and not made entirely
# of stop words. "the" anchors in any English text and grounds nothing;
# the list is short and named, so it can be argued with (ask._GENERIC is
# the shape).
_STOP_WORDS = frozenset((
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "these", "those", "for", "with", "as", "by", "not", "no", "so", "if",
    "he", "she", "they", "we", "you", "i", "his", "her", "their", "our",
))


def substantial(span):
    """Does this span clear the floor to count as grounding evidence:
    after fold, at least two words or twelve characters, and not made
    entirely of stop words."""
    f = fold(span)
    words = [w for w in (t.strip('.,;:!?"()[]') for t in f.split()) if w]
    if not words:
        return False
    if len(words) < 2 and len(f) < 12:
        return False
    return not all(w in _STOP_WORDS for w in words)


def anchor(span, data, folded=None):
    """Is `span` in `data`: verbatim; else folded on both sides
    (whitespace, quote marks, case); else with the punctuation the model
    tucked inside the closing quote stripped. `folded` is fold(data)
    when the caller has it already. A span that is nothing after fold
    anchors nowhere -- the verbatim check runs after that guard, so
    three spaces cannot anchor in a run of spaces."""
    folded = fold(data) if folded is None else folded
    f = fold(span)
    if not f:
        return False
    if span in data:
        return True
    if f in folded:
        return True
    f = f.rstrip(".,;:!?")
    return bool(f) and f in folded


# ------------------------------------------------------------ grounding
# The law contracts 10 to 13 share: what a model says about a text is
# checked against that text before the reader sees it. anchor() above is
# the span level -- is this quote in the source. Ground is the unit level
# -- is this whole note, question or claim worth printing; Gate is the
# stream that drops the ones that are not, so a contract can refuse
# instead of invent. The judge is one, so "grounded" means the same thing
# in every contract that uses the word.
GROUNDED, UNGROUNDED, UNQUOTED = "grounded", "ungrounded", "unquoted"


class Ground:
    """One source text, a verdict per unit (a line, a note, a question):

      GROUNDED    it quotes the source and at least one quote anchors
      UNGROUNDED  it quotes and not one quote anchors -- fluent invention,
                  the failure these contracts exist to make impossible
      UNQUOTED    it quotes nothing, which only a contract can judge (a
                  claim about a source must quote it; a question need not)

    A unit with one good quote and one bad is GROUNDED, the bad one in
    `misses`: it does point at the text, and mark() says which half to
    distrust."""

    def __init__(self, data):
        self.data = data
        self.folded = fold(data)

    def verdict(self, unit):
        """(GROUNDED | UNGROUNDED | UNQUOTED, [spans the source lacks]).
        Only a span past the floor (substantial) counts as grounding
        evidence: quoting "the" against any English text proves nothing,
        so a unit whose only spans fail the floor is UNQUOTED -- the
        contracts that demand a quote refuse it."""
        spans = [q[0] for q in quotes(unit) if substantial(q[0])]
        if not spans:
            return UNQUOTED, []
        misses = [q for q in spans if not anchor(q, self.data, self.folded)]
        return (UNGROUNDED if len(misses) == len(spans) else GROUNDED), misses

    def mark(self, unit):
        """`unit` with ANCHOR_MARK after every span the source does not
        hold, and PROPOSED_MARK after every span that is the model's own
        proposal (after an arrow) -- unchecked, and it must not read as
        a quotation of the text. The marking rule, one unit at a time."""
        out, last = [], 0
        for m in QUOTE.finditer(unit):
            span, end = m.group(m.lastindex), m.end()
            if PROPOSAL.search(unit[:m.start()]):
                out.append(unit[last:end] + PROPOSED_MARK)
                last = end
            elif not anchor(span, self.data, self.folded):
                out.append(unit[last:end] + ANCHOR_MARK)
                last = end
        out.append(unit[last:])
        return "".join(out)


class Gate:
    """A line-buffered filter between a model's stream and the reader: one
    line is one unit, `keep(line, verdict, misses)` decides, and a line it
    refuses never reaches the stream. What is kept is written marked, so
    the quotes a reader does see are the ones that stood up. write(s) a
    chunk at a time; close() flushes the last unterminated line (without a
    newline, the way the model left it).

    `quoted` and `missed` count spans, `kept` and `dropped` count units,
    and `spoke` says the model wrote something at all: `spoke` with
    `kept` 0 is the moment a contract says so in one line and stops --
    and, because nothing was written, that line stands alone.

    keep=None keeps every line and drops nothing: that is `Anchors`,
    contract 10's marker, whose only job is to say which quotes to
    trust."""

    def __init__(self, stream, data, keep=None):
        self.stream, self.data = stream, data
        self.ground = Ground(data)
        self.keep = keep
        self.buf = ""
        self.quoted = self.missed = self.kept = self.dropped = 0
        self.spoke = False

    def _unit(self, line, newline):
        if line.strip():
            self.spoke = True
        if self.keep is not None:
            if not line.strip():
                return                      # a blank line is not a unit
            verdict, misses = self.ground.verdict(line)
            if not self.keep(line, verdict, misses):
                self.dropped += 1
                return
            self.kept += 1
        qs = quotes(line)
        self.quoted += len(qs)
        self.missed += sum(1 for q, _s, _e in qs if not anchor(q, self.data, self.ground.folded))
        self.stream.write(self.ground.mark(line) + ("\n" if newline else ""))

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self._unit(line, True)
        self.stream.flush()

    def flush(self):
        self.stream.flush()

    def close(self):
        if self.buf:
            line, self.buf = self.buf, ""
            self._unit(line, False)
        self.stream.flush()


class Anchors(Gate):
    """Contract 10's stream: every line written on, every quoted span the
    text does not hold followed by ANCHOR_MARK where it stands. `quoted`
    and `missed` count."""

    def __init__(self, stream, data):
        Gate.__init__(self, stream, data, keep=None)
