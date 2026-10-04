# spark.text -- wrap a streamed answer at the terminal's width, a word at a
# time, keeping the model's own line breaks. A line beginning with four
# spaces or a ``` fence is left verbatim, unwrapped, to its own end (code,
# already-formatted output). The mark (glyph("hammer") + " ") prints once,
# before the first character; close() writes it alone when nothing arrived.

import os
import re
import shutil
import sys
import threading
import time
import unicodedata

from . import glyph, paint

SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
# a list line (living only): up to 3 spaces, then `-`, `*` or a number
# with `.` or `)`, then a space; BULLET_START is a head that may still
# become one
BULLET = re.compile(r"^( {0,3})([-*]|\d{1,3}[.)]) $")
BULLET_START = re.compile(r"^ {0,3}(?:[-*]|\d{1,3}[.)]?)$")


class Wrap:
    """feed(delta) a chunk at a time; close() when the stream ends. Width is
    the terminal's columns at a tty, 80 when piped (an explicit isatty
    check, not the COLUMNS environment, which leaks into test subprocesses).
    `col` (the cursor's column) and `need_space` (a space is owed before the
    next word) are kept apart so the mark's own trailing space is never
    doubled."""

    def __init__(self, stream=sys.stdout, mark=True, cps=0, lead=None, hang=False):
        self.stream = stream
        self.mark = mark
        self.clean = Printable()  # what feed lets through of the model's text
        # lead (a tty only): a string that opens the reply in the mark's
        # place -- the face. The reply's later lines start at column 0,
        # so a code block copies clean; hang=True indents them by the
        # lead's visible width instead (the escapes not counted). Piped,
        # the lead is ignored: the bytes are today's.
        self.lead = lead if lead and stream.isatty() else ""
        self.lead_cols = len(SGR_RE.sub("", self.lead))
        self.indent = self.lead_cols if hang else 0
        self.owed = False         # a new line's indent, written before its first char
        # the reveal: cps > 0 at a tty paces every visible character (the
        # same clock as spark reveal: a stall is never repaid as a burst);
        # 0, or piped, writes as the chunks come
        self.cps = cps if stream.isatty() else 0
        self.due = 0.0
        self.width = shutil.get_terminal_size((80, 24)).columns if stream.isatty() else 80
        self.col = 0
        self.need_space = False
        self.started = False
        self.word = ""            # the word being built
        self.line_head = ""       # a line's first chars, while undecided
        self.deciding = True      # still buffering line_head
        self.verbatim = False     # this line passes through unwrapped
        # Markdown, drawn at a tty (raw when piped): `**bold**` as bold and
        # `*em*` as plain, a `# heading` line bold, marks dropped only when
        # they open before a letter and close after one (`*.txt`, `**/`
        # pass through); a ``` fence opens a block that passes through whole
        self.render = stream.isatty()
        self.fenced = False       # inside ``` ... ```: every line verbatim
        self.stars = ""           # a run of `*` waiting for the char after
        self.prev = ""            # the char before that run
        self.bold = False
        self.em = False
        self.heading = False
        # awakened (look.awake), at a tty: `inline code` bold in the
        # accent, its backticks dropped; a `- `, `* ` or `N. ` line a
        # bullet with a hanging indent; and the reveal breathes at the
        # punctuation, its average pace the chosen one, pauses included.
        # Unawakened, every byte is today's.
        self.living = False
        if self.render:
            try:
                from . import look
                self.living = look.awake()
            except Exception:       # noqa: BLE001 -- a look file is never a reason to fail
                self.living = False
        self.code = False         # inside `...`
        self.hang = 0             # a bullet's hanging indent
        self.step = self.base = 0.0
        if self.cps:
            from . import reveal
            # prose runs faster between its breaths (BREATH_SCALE), so its
            # average is the chosen pace; a code line has no breath, so it
            # keeps the chosen pace itself (base), never faster
            self.base = 1.0 / self.cps
            self.step = self.base * (reveal.BREATH_SCALE if self.living else 1.0)

    def pace(self, cps):
        """The reveal's pace from here on, characters a second (the
        chat's voice sets it a sentence at a time); 0 writes as the
        chunks come. Piped, nothing changes: the bytes are never paced."""
        if not self.stream.isatty():
            return
        self.cps = cps
        if cps:
            from . import reveal
            self.base = 1.0 / cps
            self.step = self.base * (reveal.BREATH_SCALE if self.living else 1.0)

    def _emit(self, s, pause=0):
        """Every write goes through here: unpaced, one write; paced (cps),
        a character at a time with an escape sequence written free, then
        `pause` more steps of breath after the last one (living only)."""
        if self.owed and s and s[0] != "\n":
            # a line under the lead: its indent comes before its first
            # char, so a blank line stays blank (no trailing spaces);
            # written free, like an escape -- the reveal paces words, not
            # the margin
            self.owed = False
            self.stream.write(" " * self.indent)
        if not self.cps or not s:
            self.stream.write(s)
            return
        step = self.base if self.verbatim else self.step
        pos = 0
        for m in SGR_RE.finditer(s):
            for ch in s[pos:m.start()]:
                self._tick(ch, step)
            self.stream.write(m.group(0))
            pos = m.end()
        for ch in s[pos:]:
            self._tick(ch, step)
        if pause and self.living:
            # a breath is a later due, never a sleep: a stall that comes
            # after it swallows it, and nothing is repaid
            self.due += step * pause

    def _breath(self, w):
        """The steps of breath after the word `w`: a comma or a semicolon
        a short one, a sentence's end a long one."""
        if not (self.cps and self.living):
            return 0
        from . import reveal
        tail = SGR_RE.sub("", w).rstrip(")\"']")
        if tail.endswith((",", ";")):
            return reveal.BREATH_COMMA
        if tail.endswith((".", "?", "!")):
            return reveal.BREATH_STOP
        return 0

    def _tick(self, ch, step):
        now = time.monotonic()
        delay = self.due - now
        if delay > 0:
            time.sleep(delay)
            now = self.due
        self.stream.write(ch)
        self.stream.flush()
        self.due = now + step

    def _start(self):
        if not self.started:
            self.started = True
            if self.lead:
                # the lead (the face) in the mark's place; the caller
                # paints it, col counts what is visible
                self._emit(self.lead)
                self.col += self.lead_cols
            elif self.mark:
                # the mark in the accent at a tty (paint: plain when piped
                # or unset); col counts what is visible, never the escape
                self._emit(paint(glyph("hammer"), "accent", self.stream) + " ")
                self.col += len(glyph("hammer")) + 1

    def _word_out(self, w):
        if not w:
            return
        self._start()
        n = len(SGR_RE.sub("", w))          # what is visible, never the escapes
        if self.need_space:
            if self.col + 1 + n > self.width - 1:
                self._emit("\n")
                self.col = 0
                if self.hang or self.indent:
                    # a bullet's hang counts from the lead's indent
                    # already; written free, never paced
                    self.owed = False
                    self.stream.write(" " * max(self.hang, self.indent))
                    self.col = max(self.hang, self.indent)
            else:
                self._emit(" ")
                self.col += 1
        self._emit(w, self._breath(w))
        self.col += n
        self.need_space = True
        self.stream.flush()

    # --- the marks: a run of `*` is decided by the char after it
    def _stars_out(self, nxt):
        run, self.stars = self.stars, ""
        if not self.render or not run or len(run) > 3:
            self.word += run
            return
        # left-flanking opens (a letter after, no letter before), right-
        # flanking closes (a letter before, none after): 2*3*4 stays
        opens = (nxt.isalnum() or nxt in "\"'([`") and not self.prev.isalnum()
        closes = self.prev != "" and not self.prev.isspace() and not nxt.isalnum()
        kinds = [("bold", 2)] if run == "**" else [("em", 1)] if run == "*" else [("bold", 2), ("em", 1)]
        for kind, width in kinds:
            on = getattr(self, kind)
            if not on and opens:
                setattr(self, kind, True)
                if kind == "bold":
                    self.word += "\033[1m"
            elif on and closes:
                setattr(self, kind, False)
                if kind == "bold" and not self.heading:
                    self.word += "\033[22m"
            else:
                self.word += "*" * width

    def _reset_marks(self):
        if self.render and (self.bold or self.heading or self.code):
            self.stream.write("\033[0m")
        self.bold = self.em = self.heading = self.code = False
        self.stars = ""
        self.prev = ""

    def _code_mark(self):
        """`inline code` (living only): its backticks go, and the span is
        drawn in the accent (bold when the accent is unset)."""
        self.code = not self.code
        if self.code:
            from . import sgr
            self.word += "\033[%sm" % (sgr("accent", stream=self.stream) or "1")
        else:
            self.word += "\033[0m" + ("\033[1m" if self.bold or self.heading else "")

    def _char(self, ch):
        if self.verbatim:
            self._start()
            self._emit(ch)
            self.col += 1
            self.stream.flush()
            return
        if ch == "`" and self.living:
            if self.stars:
                self._stars_out(ch)
            self._code_mark()
            return
        if ch == "*" and self.render and not self.code:
            if not self.stars:
                self.prev = self.word[-1:] if self.word else " "
            self.stars += ch
            return
        if self.stars:
            self._stars_out(ch)
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
        if self.stars:
            self._stars_out("\n")
        if self.word:
            self._word_out(self.word)
            self.word = ""
        blank = self.col <= (self.indent if self.started else 0) and not self.verbatim and not self.fenced
        self._start()
        self._reset_marks()
        # a blank line between paragraphs breathes like a sentence's end
        self._emit("\n", self._breath(".") if blank else 0)
        self.stream.flush()
        # under a lead, the next line starts at its indent: owed, and
        # written with that line's first char
        self.col = self.indent
        self.owed = bool(self.indent)
        self.hang = 0
        self.need_space = False
        self.verbatim = False
        self.line_head = ""
        self.deciding = True

    def feed(self, delta):
        # the model's text loses its escapes and controls first, at a tty
        # and piped alike (a sequence split across chunks dropped whole);
        # the wrap's own marks (bold, the accent) are drawn after
        delta = self.clean.feed(delta)
        for ch in delta:
            if ch == "\n":
                self._new_line()
                continue
            if self.deciding:
                self.line_head += ch
                spaces = self.line_head == " " * len(self.line_head)
                fence = self.line_head == "`" * len(self.line_head)
                if self.fenced:
                    # inside a fence every line is verbatim; three
                    # backticks at the start close it
                    if fence and len(self.line_head) < 3:
                        continue
                    self.deciding = False
                    self.verbatim = True
                    if fence:
                        self.fenced = False
                    pending, self.line_head = self.line_head, ""
                    self._start()
                    self._emit(pending)
                    self.col += len(pending)
                    self.stream.flush()
                    continue
                head = self.line_head
                hashes = head.rstrip(" ") == "#" * len(head.rstrip(" ")) and 0 < len(head.rstrip(" ")) <= 3
                if spaces and len(head) < 4:
                    continue
                if fence and len(head) < 3:
                    continue
                if self.render and hashes and not head.endswith(" ") and len(head) <= 3:
                    continue
                if self.living and not spaces and BULLET_START.match(head):
                    continue            # `-`, `*`, `12.`: a bullet or not, the next char says
                bullet = BULLET.match(head) if self.living else None
                if bullet:
                    # a bullet: `-` for `-` and `*`, a number kept; the
                    # wrapped lines hang under its first word
                    self.deciding = False
                    self.line_head = ""
                    mark = bullet.group(2)
                    lead = bullet.group(1) + ("-" if mark in "-*" else mark) + " "
                    self._start()
                    self._emit(lead)
                    self.col += len(lead)
                    self.hang = self.col if self.col < self.width // 2 else 0
                    self.need_space = False
                    continue
                self.deciding = False
                if self.render and hashes and head.endswith(" "):
                    # a heading: the marks go, the line is bold
                    self.heading = True
                    self.line_head = ""
                    self._start()
                    self.stream.write("\033[1m")
                    continue
                self.verbatim = spaces or fence
                if fence:
                    self.fenced = True
                pending, self.line_head = self.line_head, ""
                if self.verbatim:
                    self._start()
                    self._emit(pending)
                    self.col += len(pending)
                    self.stream.flush()
                else:
                    for c2 in pending:
                        self._char(c2)
                continue
            self._char(ch)

    def close(self):
        self.clean.close()
        if self.deciding and self.line_head:
            self.deciding = False
            pending, self.line_head = self.line_head, ""
            for ch in pending:
                self._char(ch)
        if self.stars:
            self._stars_out("\n")
        if self.word:
            self._word_out(self.word)
            self.word = ""
        self._start()
        self._reset_marks()
        self.stream.write("\n")
        self.stream.flush()


class Busy:
    """The pulse while a reply is on its way (grammar rule 6's other half,
    beside wait_ready's dots for a server coming up): the mark and `.`
    `..` `...` redrawn every 0.35 s on a daemon thread, ASCII always, the
    mark in the accent and the dots muted (paint: colour only at a tty
    and only from the three env vars). Silent unless `stream` is a tty,
    so a pipe never sees a byte of it. above=True draws in the row above
    the cursor and comes back (the widgets' own hint-row frame: save the
    cursor, up `row` rows, clear, draw, restore -- one write per frame);
    else it draws on the cursor's own row. stop() ends the thread, then
    clears once from the calling thread; idempotent; a context manager.
    Any OSError or ValueError on the stream goes silent -- the pulse is
    never a reason to fail.

    Awakened, with the motion part active on the stream (look.active),
    the dots become the SCANNER on every terminal: `* FACE [  =     ]`,
    8 cells, a frame every look.Anim.step seconds (0.12; a temperament
    changes the pace alone), ssh and the console included: every frame
    is ASCII. `kind` (look.PROGRESS) picks what moves in the cells, so
    the motion says what spark is doing: think (a reply on its way, the
    default), read, steps, swell, march. `mood` picks the face's score
    (the face only while the words part is active): thinking by default,
    blinking every look.blink() frames and glancing every third blink.
    The frames are look.Anim's; this class places and paints them.
    Either way the wait escalates, never louder: from 2 seconds the
    elapsed seconds, from TIER_LONG seconds (or three quarters of
    `timeout`, whichever is sooner) one sentence saying what to do.
    Unawakened, every byte is today's, whatever the kind."""

    FRAMES = (".", "..", "...")
    STEP = 0.35
    CELLS = 8
    TIER_SECONDS = 2
    TIER_LONG = 15
    LONG = "Ctrl-C stops it."

    def __init__(self, stream=sys.stderr, above=False, mark=None, close=False, timeout=None, row=1,
                 kind="think", mood="thinking"):
        self.stream = stream
        self.kind, self.mood = kind, mood
        self.anim = None
        self.above = above
        self.row = row if isinstance(row, int) and 1 <= row <= 5 else 1
        self.mark = glyph("hammer") if mark is None else mark
        self.close = close                      # close the stream in stop() (hint_row's /dev/tty)
        self.on = False
        self._stop = threading.Event()
        self._thread = None
        self.started = 0.0
        try:
            self.live = bool(stream) and stream.isatty()
        except (AttributeError, ValueError, OSError):
            self.live = False
        # the living layer: off unless awakened and the part is active on
        # this very stream; any trouble reading it is today's pulse
        self.moving = self.scan = False
        self.face = None
        self.blink = 0
        self.long_at = self.TIER_LONG
        if timeout:
            try:
                self.long_at = min(self.TIER_LONG, 0.75 * float(timeout))
            except (TypeError, ValueError):
                pass
        if self.live:
            try:
                from . import look
                self.moving = look.active("motion", stream)
                self.scan = self.moving and look.scanner(stream)
                if self.moving:
                    self.anim = look.Anim()
                    if look.active("words", stream):
                        self.face = self.anim.faces
                        self.blink = self.anim.blink
            except Exception:       # noqa: BLE001 -- the pulse is never a reason to fail
                self.moving = self.scan = False
                self.face = self.anim = None
        self.step = self.anim.step if self.scan else self.STEP
        self.cols = 80
        if self.moving:
            try:
                self.cols = os.get_terminal_size(stream.fileno()).columns
            except (AttributeError, OSError, ValueError):
                self.cols = 80

    @classmethod
    def hint_row(cls, kind="think", mood="thinking"):
        """The widgets' pulse: with SPARK_HINT_ROW=N in the environment (a
        digit 1..5, the height: the widgets set it around `spark line`
        and `spark recall`; a hand-run one never touches the rows above),
        a Busy drawing N rows above the cursor on /dev/tty; otherwise, or
        when /dev/tty will not open, a silent one."""
        n = os.environ.get("SPARK_HINT_ROW", "")
        if len(n) == 1 and n in "12345":
            try:
                return cls(open("/dev/tty", "w"), above=True, close=True, row=int(n), kind=kind, mood=mood)
            except OSError:
                pass
        return cls(None)

    # --- one frame: the mark, the moving piece, the tier
    def _dots(self, i):
        """The dots for frame i: a new one every 0.35 s in either motion."""
        per = 3 if self.scan else 1
        return self.FRAMES[(i // per) % len(self.FRAMES)]

    def _face(self, i, mood=None):
        """The face for frame i: the mood's score (look.Anim), a blink
        every `blink` frames, a glance every third blink. Deterministic."""
        return self.anim.face(mood or self.mood, i)

    def _scanner(self, i):
        """The scanner for frame i, painted: the brackets muted, what
        moves in the accent (a resting dot muted), CELLS cells of the
        wait's kind (look.Anim.cells)."""
        out = paint("[", "muted", self.stream)
        for run in re.split("( +)", self.anim.cells(self.kind, i)):
            if run.strip():
                run = paint(run, "muted" if run == "." else "accent", self.stream)
            out += run
        return out + paint("]", "muted", self.stream)

    def _piece(self, i):
        """The moving piece, painted: the dots, or the face and the scanner."""
        if not self.scan:
            return paint(self._dots(i), "muted", self.stream)
        if self.face is not None:
            return paint(self._face(i), "accent", self.stream) + " " + self._scanner(i)
        return self._scanner(i)

    def _visible(self, i):
        """The frame's width before the tier: mark, space, piece."""
        n = len(self.mark) + 1
        if self.scan:
            n += self.CELLS + 2 + (len(self._face(i)) + 1 if self.face is not None else 0)
        else:
            n += len(self._dots(i))
        return n

    def _tier(self, i, used=None):
        """The escalation after the piece: from 2 s the elapsed seconds,
        from long_at one sentence -- normal colour, each dropped when the
        row cannot hold it (a wrapped row loses the saved cursor)."""
        if not self.moving or not self.started:
            return ""
        secs = int(time.monotonic() - self.started)
        if secs < self.TIER_SECONDS:
            return ""
        used = self._visible(i) if used is None else used
        out = " %d s" % secs
        if secs >= self.long_at:
            out += "  " + self.LONG
        room = self.cols - 1 - used
        if len(out) > room:
            out = " %d s" % secs
        return out if len(out) <= room else ""

    def _body(self, i):
        return paint(self.mark, "accent", self.stream) + " " + self._piece(i) + self._tier(i)

    def _place(self, body):
        if self.above:
            return "\x1b7\x1b[%dA\r\x1b[2K" % self.row + body + "\x1b8"
        return "\r\x1b[2K" + body

    def _frame(self, i):
        return self._place(self._body(i))

    def _clear(self):
        return ("\x1b7\x1b[%dA\r\x1b[2K\x1b8" % self.row) if self.above else "\r\x1b[2K"

    def _write(self, s):
        try:
            self.stream.write(s)
            self.stream.flush()
        except (OSError, ValueError):
            self.live = False

    def _run(self):
        i = 0
        while not self._stop.is_set() and self.live:
            self._write(self._frame(i))
            i += 1
            self._stop.wait(self.step)

    def start(self):
        if self.on or not self.live:
            return self
        self.on = True
        self.started = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self.on:
            self.on = False
            self._stop.set()
            if self._thread is not None:
                self._thread.join()
                self._thread = None
            if self.live:
                self._write(self._clear())
        if self.close and self.stream is not None:
            try:
                self.stream.close()
            except (OSError, ValueError):
                pass
            self.close = False
            self.live = False

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def pulse(stream=None):
    """Awakened, at a terminal: a Busy on `stream` (stderr) around a silent
    step, its cells marching (update, model verify). Anywhere else a
    context that draws nothing, so an unawakened machine and a log keep
    today's bytes."""
    import contextlib
    stream = sys.stderr if stream is None else stream
    try:
        from . import look
        if look.active("motion", stream):
            return Busy(stream, kind="march")
    except Exception:       # noqa: BLE001 -- the pulse is never a reason to fail
        pass
    return contextlib.nullcontext()


class Estimate(Busy):
    """The wait for a model to load, with an estimate: at a terminal whose
    motion part is active, `* FACE waking [=========>          ] 45%`, 20
    cells, the fill the elapsed time over `expected_s` (the last load of
    that model file, engine.last_load) and never past 95 % of the cells,
    so a gap always shows until the engine answers. Past the estimate the
    percent gives way to `longer than last time (N s) -- spark check says
    why`. The face wakes once over the first third: the waking score (a
    yawn) stretched over it, then idle. No estimate (None or 0) is a Busy
    whose cells swell, with the elapsed seconds. Unawakened it is today's
    pulse; piped it draws nothing. start(), stop() and the context
    manager are Busy's."""

    WIDTH = 20
    CAP = 0.95

    def __init__(self, label, expected_s, stream=sys.stderr):
        Busy.__init__(self, stream, kind="swell")
        self.label = label or ""
        try:
            self.expected = max(0.0, float(expected_s or 0))
        except (TypeError, ValueError):
            self.expected = 0.0
        self.bar = self.moving and self.expected > 0
        if self.bar and not self.scan:
            self.step = self.STEP           # ssh and the console: a calmer redraw

    def _waking_face(self, t):
        third = self.expected / 3.0
        n = self.anim.length("waking")
        if n:
            return self.anim.face("waking", int(n * t / third) if t < third else n)
        # a waking face edited by hand: its still, between the blink and idle
        if t < third / 2:
            return self.face["blink"]
        if t < third:
            return self.face["waking"]
        return self.face["idle"]

    def fill(self, t):
        """(the bar's cells, the percent) at `t` seconds: never full."""
        frac = min(t / self.expected, self.CAP)
        n = int(frac * (self.WIDTH - 1))
        return "=" * n + ">" + " " * (self.WIDTH - 1 - n), int(frac * 100)

    def _body(self, i):
        if not self.bar:
            return Busy._body(self, i)
        t = time.monotonic() - self.started if self.started else 0.0
        cells, pct = self.fill(t)
        head = paint(self.mark, "accent", self.stream) + " "
        used = len(self.mark) + 1
        if self.face is not None:
            face = self._waking_face(t)
            head += paint(face, "accent", self.stream) + " "
            used += len(face) + 1
        if self.label:
            head += self.label + " "
            used += len(self.label) + 1
        bar = paint("[", "muted", self.stream) + paint(cells, "accent", self.stream) + paint("]", "muted", self.stream)
        used += self.WIDTH + 2
        room = self.cols - 1
        if t <= self.expected:
            tail = " %d%%" % pct
            return head + bar + (tail if used + len(tail) <= room else "")
        # past the estimate the sentence matters more than the bar: a row
        # too narrow for both keeps the words
        tail = "longer than last time (%d s) -- spark check says why" % round(self.expected)
        if used + 1 + len(tail) <= room:
            return head + bar + " " + tail
        if used - self.WIDTH - 2 + len(tail) <= room:
            return head + tail
        return head + bar


def wait(kind="read", stream=None):
    """A Busy on `stream` (stderr) for a verb that had no pulse (spark
    edit, read, drill): only where a person watches -- stdout and the
    stream both terminals, the look's motion active. Anywhere else a
    silent one: an editor's plugin pipes stdout and never sees a frame,
    and an unawakened machine keeps today's bytes."""
    stream = sys.stderr if stream is None else stream
    try:
        from . import look
        if sys.stdout.isatty() and look.active("motion", stream):
            return Busy(stream, kind=kind)
    except Exception:       # noqa: BLE001 -- the pulse is never a reason to fail
        pass
    return Busy(None)


MARKED = re.compile(r"^((?:\x1b\[[0-9;]*m)*[*!](?:\x1b\[[0-9;]*m)*) ")


def faced(line, mood, stream=None, plain=False):
    """`line` with the mood's resting face after its leading mark, where
    the look's motion and words are active on `stream` (stdout by
    default): `! no model answers` -> `! (O.O) no model answers`. The
    face is painted in the accent; plain=True leaves it bare, for a line
    its caller paints whole. Anywhere else -- a pipe, an unawakened
    machine, the look off, a line with no mark -- the line as it came."""
    stream = sys.stdout if stream is None else stream
    try:
        from . import look
        m = MARKED.match(line)
        if m is None or not (look.active("motion", stream) and look.active("words", stream)):
            return line
        face = look.Anim().rest(mood)
        return m.group(0) + (face if plain else paint(face, "accent", stream)) + " " + line[m.end():]
    except Exception:       # noqa: BLE001 -- a face is never a reason to fail
        return line


class FaceLead:
    """The face that leads a reply, and the stream the reply's wrap writes
    through. The face stands in the mark's place (`lead`, the idle face
    and a space). While the reply comes it moves on that first row: talk
    frames while text flows (a write in the last FLOW seconds), thinking
    frames when the stream pauses. settle(mood) ends it on the mood's
    resting still.

    Every write is counted in rows (a line feed, a line the terminal
    wrapped), under one lock with the redraw. The redraw saves the
    cursor, goes up the rows the reply has taken, writes the frame there
    and restores. Before the lead's row would scroll off (the rows reach
    the terminal's height - 2) the face settles where it is; a resized
    terminal stops it as it stands. The frames are look.Anim's.

    A subclass names its own source of "is it speaking" (_speaking):
    forge._Face asks the voice."""

    FLOW = 0.3          # text flows this long after a write
    TICK = 0.05         # how often the redraw thread looks

    def __init__(self, stream, anim=None):
        from . import look
        self.stream = stream
        self.anim = anim or look.Anim()
        idle = self.anim.talk(False)
        frames = [idle, self.anim.talk(True), self.anim.faces["blink"], self.anim.faces["glance"]]
        for mood in ("thinking", "pleased", "puzzled", "alarmed"):
            frames += [self.anim.rest(mood)] + [f for f, _n in self.anim.scores[mood]]
        self.width = max(len(f.rstrip()) for f in frames)
        self.lead = self._paint(idle) + " "
        self.lock = threading.Lock()
        self.rows = self.col = 0
        self.size = self._size()
        self.started = False        # the lead is written: the row exists
        self.shown = idle           # the frame on the lead's row
        self.open = False           # the talking frame is the one drawn
        self.mood = None            # what it settles on, once known
        self.closed = self.halt = self.lost = False
        self.last = 0.0             # the newest write
        self._quit = threading.Event()
        self._going = False
        self.thread = threading.Thread(target=self._run, name="spark-face", daemon=True)

    def _paint(self, frame):
        f = frame.rstrip()
        return paint(f, "accent", self.stream) + " " * (self.width - len(f))

    def _size(self):
        try:
            cols, lines = os.get_terminal_size(self.stream.fileno())
        except (AttributeError, OSError, ValueError):
            return (80, 24)
        return (cols or 80, lines or 24)        # a pty that was never sized answers 0 by 0

    def _mouth(self):
        from . import look
        return look.MOUTH_STEP

    # --- the stream the wrap writes through
    def isatty(self):
        return self.stream.isatty()

    def fileno(self):
        return self.stream.fileno()

    def flush(self):
        self.stream.flush()

    def write(self, s):
        with self.lock:
            if s and not self.started:
                self.started = True
            self.last = time.monotonic()
            self._count(s)
            self.stream.write(s)
            if self.started and not self.halt and self.rows >= self.size[1] - 2:
                # the lead's row is about to leave the screen: the face
                # settles while it can still be reached
                if self._draw(self.anim.rest(self.mood) if self.mood else self.anim.talk(False), must=True):
                    self.halt = True
        if s and not self._going:
            self.start()

    def line(self):
        """A blank line of the chat's own after the reply, counted."""
        self.write("\n")
        self.flush()

    def _count(self, s):
        """(the lock held) The cursor's row below the lead and its column
        after `s`: a line feed, or a character past the last column, is
        a row more (a wide character two columns, an escape none)."""
        width = self.size[0]
        for ch in SGR_RE.sub("", s):
            if ch == "\n":
                self.rows, self.col = self.rows + 1, 0
            elif ch == "\r":
                self.col = 0
            elif ch == "\t":
                self.col = min(width, (self.col // 8 + 1) * 8)
            elif ch >= " " and not unicodedata.combining(ch):
                w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
                if self.col + w > width:
                    self.rows, self.col = self.rows + 1, 0
                self.col += w

    # --- the face
    def start(self):
        if not self._going:
            self._going = True
            self.thread.start()
        return self

    def close(self):
        """No more of the reply comes: the thread ends once nothing
        speaks, resting on the mood settle() named, else idle."""
        self.closed = True

    def settle(self, mood="pleased", play=False):
        """The reply is over: the face rests on the mood's still, drawn
        once, and moves no more -- nothing is drawn after this returns.
        play=True (the chat, where a prompt waits next) lets the mood's
        score play first, on the thread; rest() stops it at the still."""
        with self.lock:
            self.mood = mood
            self.closed = True
            if not play:
                if not self.lost:
                    self._draw(self.anim.rest(mood))
                self.halt = True
        if not play:
            self._quit.set()

    def rest(self):
        """At rest now, and no redraw after it: a key typed, a reply
        stopped, a line of the caller's own about to print. The still is
        the settled mood's, else idle."""
        with self.lock:
            if not self.halt and not self.lost:
                self._draw(self.anim.rest(self.mood) if self.mood else self.anim.talk(False))
            self.halt = True
        self._quit.set()

    def _draw(self, frame, must=False):
        """(the lock held) The frame on the lead's row; True when it is
        there. Skipped while the cursor waits at the last column (a
        restore there may lose the wrap). Once that row is out of reach --
        scrolled off, the terminal resized -- the face is lost and moves
        no more."""
        if not self.started:
            return True
        if self.rows > self.size[1] - 1 or self._size() != self.size:
            self.halt = self.lost = True
            return False
        if self.col >= self.size[0]:
            return not must
        if frame != self.shown:
            up = "\033[%dA" % self.rows if self.rows else ""
            self.stream.write("\x1b7" + up + "\r" + self._paint(frame) + "\x1b8")
            self.stream.flush()
            self.shown = frame
        self.open = frame == self.anim.talk(True) and frame != self.anim.talk(False)
        return True

    def _speaking(self):
        """"now" while text flows, "pause" while the stream waits, "" once
        the reply is over. Waits a tick first."""
        self._quit.wait(self.TICK)
        if self.closed:
            return ""
        return "now" if time.monotonic() - self.last < self.FLOW else "pause"

    def _run(self):
        flip, since = 0.0, None
        try:
            while True:
                state = self._speaking()
                with self.lock:
                    if self.halt:
                        return
                    now = time.monotonic()
                    if state == "now":
                        since = None
                        if now >= flip:
                            self._draw(self.anim.talk(not self.open))
                            flip = now + self._mouth()
                    elif state == "pause":
                        since = now if since is None else since
                        self._draw(self.anim.face("thinking", int((now - since) / self.anim.step)))
                    else:
                        since = None
                        self._draw(self.anim.talk(False))
                        if state == "" and self.closed:
                            break
            self._finish()
        except Exception:   # noqa: BLE001 -- a face is never a reason to fail
            from . import log_exc
            log_exc("text: the leading face")

    def _finish(self):
        """The settled mood's score, once, then its still; idle when no
        mood was named."""
        mood = self.mood
        for k in range(self.anim.length(mood) if mood else 0):
            with self.lock:
                if self.halt:
                    return
                self._draw(self.anim.face(mood, k))
            if self._quit.wait(self.anim.step):
                return
        with self.lock:
            if not self.halt:
                self._draw(self.anim.rest(mood) if mood else self.anim.talk(False))
                self.halt = True


def reply_face(stream=None):
    """(the stream a reply's wrap writes through, its lead) for a reply
    on `stream` (stdout by default): a FaceLead and its face where the
    look's motion and words are active there, else the stream itself and
    None -- a pipe, an unawakened machine and the look off keep their
    bytes."""
    stream = sys.stdout if stream is None else stream
    try:
        from . import look
        if look.active("motion", stream) and look.active("words", stream):
            face = FaceLead(stream)
            return face, face.lead
    except Exception:       # noqa: BLE001 -- a face is never a reason to fail
        pass
    return stream, None


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

# terminal escape sequences and control characters have no place in a
# line the widgets print into a live terminal, a gate writes to stdout
# or a reply streams to a terminal or a pipe: a model -- or a log line it
# quotes -- could otherwise retitle the window, move the cursor, repaint
# the screen, write the clipboard (OSC 52) or hide a link (OSC 8). A
# file a pipe wrote replays them at the next `cat`, so a pipe loses them
# too; the printable text stays byte for byte. The bidi controls reorder
# what a reader sees, so they go as well.
_BIDI = "؜‎‏‪‫‬‭‮⁦⁧⁨⁩"
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f" + _BIDI + "]")
_TEXT, _ESC, _ESC_INT, _CSI, _STR, _STR_ESC = range(6)


class Printable:
    """A model's words fit for a screen, a chunk at a time: feed(chunk)
    returns what may be printed, close() ends the stream. A sequence split
    across chunks is kept in the state and dropped whole: ESC and 8-bit
    CSI with their parameters, OSC, DCS, SOS, PM and APC to their BEL or
    ST (or CAN, SUB, or the line's end -- a stray ESC ] costs one line,
    never the rest of the reply). Every other control character goes:
    C0 but those in `keep`, DEL, C1, the bidi controls."""

    def __init__(self, keep="\t\n"):
        self.keep = keep
        self.state = _TEXT

    def feed(self, s):
        if self.state == _TEXT and not _UNSAFE.search(s):
            return s                    # the common chunk: nothing to look at
        out = []
        for ch in s:
            while not self._step(ch, out):
                pass
        return "".join(out)

    def close(self):
        """The stream ended: a sequence still open is dropped."""
        self.state = _TEXT
        return ""

    def _step(self, ch, out):
        """One character in the current state; False when the state
        changed and `ch` must be looked at again in the new one."""
        st, o = self.state, ord(ch)
        if st == _TEXT:
            if ch == "\x1b":
                self.state = _ESC
            elif ch == "\x9b":
                self.state = _CSI
            elif ch in "\x90\x98\x9d\x9e\x9f":       # DCS, SOS, OSC, PM, APC
                self.state = _STR
            elif ch in self.keep or not _UNSAFE.match(ch):
                out.append(ch)
            return True
        if st == _ESC:
            if ch == "[":
                self.state = _CSI
            elif ch in "]PX^_":
                self.state = _STR
            elif 0x20 <= o <= 0x2f:
                self.state = _ESC_INT
            elif 0x30 <= o <= 0x7e:
                self.state = _TEXT
            elif ch != "\x1b":
                self.state = _TEXT
                return False
            return True
        if st == _ESC_INT:
            if 0x20 <= o <= 0x2f:
                return True
            self.state = _TEXT
            return 0x30 <= o <= 0x7e
        if st == _CSI:
            if 0x20 <= o <= 0x3f:
                return True
            self.state = _TEXT
            return 0x40 <= o <= 0x7e
        if st == _STR:
            if ch == "\x1b":
                self.state = _STR_ESC
            elif ch in "\x07\x9c\x18\x1a":
                self.state = _TEXT
            elif ch == "\n":
                self.state = _TEXT
                return False
            return True
        # _STR_ESC: ESC \ ends the string; any other ESC starts a new sequence
        if ch == "\\":
            self.state = _TEXT
            return True
        self.state = _ESC
        return False


def printable(s, keep="\t\n"):
    """`s` fit for a screen (Printable), whole."""
    p = Printable(keep)
    return p.feed(s) + p.close()


# man's bold (X\bX) and underline (_\bX) as a pager sees them: mandoc
# (Void) and macOS's man keep them in a pipe, man-db (Debian, Arch) does
# not. Dropping the backspace alone left "NNAAMMEE" for the model
_OVERSTRIKE = re.compile(".\x08")


def unstrike(s):
    """`s` with man's overstrikes gone, the letters kept."""
    return _OVERSTRIKE.sub("", s)


def scrub(s, keep="\t\n"):
    """`s` without terminal escape sequences (CSI, OSC, DCS and the rest,
    7-bit and 8-bit), without man's overstrikes (the letter stays), and
    without control characters (C0, DEL, C1, the bidi controls) -- tabs
    and newlines excepted where they belong (`keep`): `printable`."""
    return printable(unstrike(s), keep)


def cols(s):
    """The columns `s` takes at a terminal: a wide character (East Asian
    wide or fullwidth, most emoji) two, a combining mark none, the rest
    one."""
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in s)


def cut_cols(s, n):
    """The longest head of `s` that fits `n` columns (cols)."""
    used = 0
    for i, ch in enumerate(s):
        used += cols(ch)
        if used > n:
            return s[:i]
    return s


_SURROGATE = re.compile("[\ud800-\udfff]")


def utf8(s):
    """`s` as strict UTF-8 text: a lone surrogate (what surrogateescape
    keeps for a byte that was not UTF-8) becomes the replacement mark.
    The engine's JSON parser refuses a lone surrogate with an HTTP 500,
    so none may reach the wire or the stores."""
    return _SURROGATE.sub("\ufffd", s)


def clean(o):
    """`o` with every string strict UTF-8 (utf8), lists and dicts walked:
    the last gate before the wire and before a store. A lone surrogate
    (what surrogateescape keeps for a byte that was not UTF-8, in argv
    or the environment under the box's POSIX locale -- a w3m page title
    was one) is an HTTP 500 from the engine's JSON parser on the wire,
    and a UnicodeEncodeError at a store's strict encode."""
    if isinstance(o, str):
        return utf8(o)
    if isinstance(o, list):
        return [clean(x) for x in o]
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    return o


def stdin_text(source=False):
    """stdin as text on every locale: the raw bytes decoded as UTF-8
    with the replacement mark -- never a crash on a strict locale, never
    a lone surrogate from a surrogateescape one (C.UTF-8 turns Python's
    UTF-8 mode on, and a page piped in with one Latin-1 byte poisoned
    every request built from it). A `source` to read (read, ask, drill,
    a context) loses man's overstrikes; a text to edit keeps its bytes."""
    buf = getattr(sys.stdin, "buffer", None)
    if buf is None:                       # a test's StringIO stand-in
        s = utf8(sys.stdin.read())
    else:
        s = buf.read().decode("utf-8", "replace")
    return unstrike(s) if source else s


# ------------------------------------------------------------ held back
# a paste that looks like a secret never leaves this machine: a local
# look before anything is sent (a pasted private key or .env would
# otherwise ride to the brain -- over the LAN, on a client). A named
# line each, with what the verdict calls it; a false positive only
# withholds the verdict, the paste itself always lands in the buffer.
# `spark line --paste` reads this list; the pre-commit hook scans the
# staged diff with it (minus the lines tuned for a paste). A named group
# `s` is the part hold_secrets replaces; without one, the whole match.
SECRET_SHAPES = (
    ("a private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("an AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("a GitHub token", r"\bghp_[A-Za-z0-9]{30,}"),
    ("a Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    ("an API key", r"\bsk-[A-Za-z0-9]{20,}"),
    ("a credential line", r"(?i)\b(?:password|passwd|token|secret|api[_-]?key|private[_-]?key)\b\s*[=:]\s*(?P<s>\S{8,})"),
    ("a long base64 run", r"[A-Za-z0-9+/=]{64,}"),
)

# a source -- a page, a mail, a feed item the reader discusses (`spark
# read`, `spark edit ? --source`) -- is someone else's text: it can carry
# the reader's one-time code or a reset link's token, which are not the
# reader's to hand to a model. Held back before the text leaves the
# process (so also before a client sends it over the LAN): the secret
# shapes above, and the lines only a source needs, a named line each so
# it can be argued with. A false positive hides a span, never the rest.
# A line's pattern is a regex, or a pair (OUTER, INNER): every INNER
# match inside each OUTER match -- a URL found first, then each of its
# parameters, so no pattern ever scans the text for both at once (one
# regex doing both backtracks for seconds on a crafted megabyte).
_OTP_WORD = r"\b(?:code|otp|pin|passcode|verification)"
# 4-8 digits, or split once or twice by a space or a hyphen (482 913,
# 48-29-13); never part of a longer digit run
_OTP_DIGITS = r"(?<!\d)(?P<s>\d{4,8}|\d{2,4}(?:[ -]\d{2,4}){1,2})(?!\d)"
SOURCE_SHAPES = SECRET_SHAPES + (
    # the digits within ~30 chars after the word that names them:
    # "Your verification code is 482913", "PIN: 48-29-13"
    ("a one-time code", "(?i)" + _OTP_WORD + r"[^\d]{0,30}?" + _OTP_DIGITS),
    # ... or before it: "482913 is your verification code",
    # "G-482 913 is your Google verification code"
    ("a one-time code", "(?i)" + _OTP_DIGITS + r"[^\d]{0,30}?" + _OTP_WORD),
    # the value (12+ chars) of every token-like parameter of an http(s)
    # URL: ?token=, &key=, #access_token=, ?reset=, &sig=, &oobCode=,
    # ?resetToken=, &otp=, ?X-Amz-Signature=, &auth= -- each one held
    ("a link token", (r"(?i)\bhttps?://\S+",
                      r"(?i)[?&#;][\w.-]{0,64}?(?:token|key|code|reset|sig|signature|auth|otp)"
                      r"=(?P<s>[A-Za-z0-9%._~+/=-]{12,})")),
)

HELD = "[held]"


def secret_shape(data):
    """What in the text looks like a secret (SECRET_SHAPES' name), or ''."""
    for what, pat in SECRET_SHAPES:
        if re.search(pat, data):
            return what
    return ""


def _matches(pat, data):
    """Every match of a SOURCE_SHAPES pattern: a regex's, or for a pair
    (OUTER, INNER) every INNER match inside each OUTER match."""
    if isinstance(pat, str):
        return re.finditer(pat, data)
    outer, inner = re.compile(pat[0]), re.compile(pat[1])
    return (m for o in outer.finditer(data) for m in inner.finditer(data, o.start(), o.end()))


def shape_order(names):
    """`names`, distinct, in SOURCE_SHAPES order."""
    order = []
    for what, _pat in SOURCE_SHAPES:
        if what in names and what not in order:
            order.append(what)
    return order


def held_spans(data, exact=()):
    """([(start, end)], names): every SOURCE_SHAPES match in `data` (its
    `s` group when it has one, else the whole match), and every copy of
    each `exact` (name, string) pair's string, overlapping or touching
    spans merged into one, in order; the names of the shapes that
    matched, distinct, in SOURCE_SHAPES order, then the exact pairs'.
    Every shape reads the text as it came, so one shape's match cannot
    hide or feed another."""
    spans, names = [], []
    for what, pat in SOURCE_SHAPES:
        for m in _matches(pat, data):
            s, e = m.span("s") if "s" in m.re.groupindex else m.span()
            if e > s:
                spans.append((s, e))
                if what not in names:
                    names.append(what)
    for what, value in exact:
        at = data.find(value) if value else -1
        while at >= 0:
            spans.append((at, at + len(value)))
            if what not in names:
                names.append(what)
            at = data.find(value, at + 1)
    merged = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged, names


def hold_spans(data, spans):
    """`data` with each (start, end) span of held_spans replaced by HELD."""
    out, last = [], 0
    for s, e in spans:
        out.append(data[last:s] + HELD)
        last = e
    out.append(data[last:])
    return "".join(out)


def held_offset(spans, x, end=False):
    """Where offset `x` of the original text lands in the held one: past
    a span it moves by what the span lost; inside one it goes to the
    HELD's start (`end` False) or its end (`end` True)."""
    shift = 0
    for s, e in spans:
        if x <= s:
            break
        if x < e:
            return s - shift + (len(HELD) if end else 0)
        shift += (e - s) - len(HELD)
    return x - shift


def hold_secrets(data):
    """(held_text, names): `data` with every span that looks like a secret
    (SOURCE_SHAPES) replaced by HELD, and the names of the shapes held."""
    spans, names = held_spans(data)
    return hold_spans(data, spans), names


def held_line(n, names):
    """The one stderr line a verb prints when it held something back."""
    what = "span that looks like a secret" if n == 1 else "spans that look like secrets"
    return "! held back %d %s (%s)" % (n, what, ", ".join(names))


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


def anchor(span, data, folded=None, whole=False):
    """Is `span` in `data`: verbatim; else folded on both sides
    (whitespace, quote marks, case); else with the punctuation the model
    tucked inside the closing quote stripped. `folded` is fold(data)
    when the caller has it already. A span that is nothing after fold
    anchors nowhere -- the verbatim check runs after that guard, so
    three spaces cannot anchor in a run of spaces. `whole=True` matches
    at word boundaries in the folded text: "500" must not anchor in a
    window holding only "1500ms" (spark watch, spark recall)."""
    folded = fold(data) if folded is None else folded
    f = fold(span)
    if not f:
        return False
    if whole:
        for cand in (f, f.rstrip(".,;:!?")):
            if cand and re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(cand), folded):
                return True
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

    def __init__(self, data, whole=False):
        self.data = data
        self.folded = fold(data)
        self.whole = whole      # word-boundary anchoring (watch, recall)

    def verdict(self, unit):
        """(GROUNDED | UNGROUNDED | UNQUOTED, [spans the source lacks]).
        Only a span past the floor (substantial) counts as grounding
        evidence: quoting "the" against any English text proves nothing,
        so a unit whose only spans fail the floor is UNQUOTED -- the
        contracts that demand a quote refuse it."""
        spans = [q[0] for q in quotes(unit) if substantial(q[0])]
        if not spans:
            return UNQUOTED, []
        misses = [q for q in spans if not anchor(q, self.data, self.folded, whole=self.whole)]
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
            elif not anchor(span, self.data, self.folded, whole=self.whole):
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

    def __init__(self, stream, data, keep=None, whole=False):
        self.stream, self.data = stream, data
        self.ground = Ground(data, whole)
        self.keep = keep
        self.buf = ""
        self.quoted = self.missed = self.kept = self.dropped = 0
        self.spoke = False

    def _unit(self, line, newline):
        if line.strip():
            self.spoke = True
        if self.keep is not None:
            # a line for a reader or a pipe (ask, read, watch): the
            # model's trailing spaces (a Markdown hard break) go; Anchors
            # (keep=None) keeps the editor's bytes
            line = line.rstrip()
            if not line:
                return                      # a blank line is not a unit
            verdict, misses = self.ground.verdict(line)
            if not self.keep(line, verdict, misses):
                self.dropped += 1
                return
            self.kept += 1
        qs = quotes(line)
        self.quoted += len(qs)
        self.missed += sum(1 for q, _s, _e in qs
                           if not anchor(q, self.data, self.ground.folded, whole=self.ground.whole))
        self.stream.write(scrub(self.ground.mark(line), keep="\t") + ("\n" if newline else ""))

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
            # a dropping gate (watch, read) writes lines for a reader or a
            # pipe: the last kept unit ends its line too, so two matches
            # never concatenate and `| while read` fires. Anchors
            # (keep=None) keeps the model's own shape -- raw text back
            # into an editor's buffer.
            self._unit(line, self.keep is not None)
        self.stream.flush()


class Anchors(Gate):
    """Contract 10's stream: every line written on, every quoted span the
    text does not hold followed by ANCHOR_MARK where it stands. `quoted`
    and `missed` count."""

    def __init__(self, stream, data):
        Gate.__init__(self, stream, data, keep=None)
