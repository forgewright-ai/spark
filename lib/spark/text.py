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


def quotes(line):
    """[(span, end)] -- every quoted span on one line (double quotes,
    curly double quotes or backticks; 3..200 chars) and the index just
    past its closing mark."""
    return [(m.group(m.lastindex), m.end()) for m in QUOTE.finditer(line)]


def _fold(s):
    return " ".join(s.split())


def anchor(span, data, folded=None):
    """Is `span` in `data`: verbatim; else with whitespace folded on both
    sides (a quote across a line break); else with the punctuation the
    model tucked inside the closing quote stripped. `folded` is
    _fold(data) when the caller has it already."""
    if span in data:
        return True
    folded = _fold(data) if folded is None else folded
    f = _fold(span)
    if f and f in folded:
        return True
    f = f.rstrip(".,;:!?")
    return bool(f) and f in folded


class Anchors:
    """A line-buffered stream: each line is held until its newline, every
    quoted span on it checked against `data`, ANCHOR_MARK appended after
    each one that does not anchor, and the line written on. close()
    writes the last unterminated line. `quoted` and `missed` count."""

    def __init__(self, stream, data):
        self.stream, self.data = stream, data
        self.folded = _fold(data)
        self.buf = ""
        self.quoted = self.missed = 0

    def _mark(self, line):
        out, last = [], 0
        for span, end in quotes(line):
            self.quoted += 1
            if not anchor(span, self.data, self.folded):
                self.missed += 1
                out.append(line[last:end] + ANCHOR_MARK)
                last = end
        out.append(line[last:])
        return "".join(out)

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.stream.write(self._mark(line) + "\n")
        self.stream.flush()

    def flush(self):
        self.stream.flush()

    def close(self):
        if self.buf:
            self.stream.write(self._mark(self.buf))
            self.buf = ""
        self.stream.flush()
