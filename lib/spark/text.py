# spark.text -- wrap a streamed answer at the terminal's width, a word at a
# time, keeping the model's own line breaks. A line beginning with four
# spaces or a ``` fence is left verbatim, unwrapped, to its own end (code,
# already-formatted output). The mark (glyph("hammer") + " ") prints once,
# before the first character; close() writes it alone when nothing arrived.

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
