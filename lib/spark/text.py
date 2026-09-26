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

from . import glyph, paint

SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


class Wrap:
    """feed(delta) a chunk at a time; close() when the stream ends. Width is
    the terminal's columns at a tty, 80 when piped (an explicit isatty
    check, not the COLUMNS environment, which leaks into test subprocesses).
    `col` (the cursor's column) and `need_space` (a space is owed before the
    next word) are kept apart so the mark's own trailing space is never
    doubled."""

    def __init__(self, stream=sys.stdout, mark=True, cps=0):
        self.stream = stream
        self.mark = mark
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

    def _emit(self, s):
        """Every write goes through here: unpaced, one write; paced (cps),
        a character at a time with an escape sequence written free."""
        if not self.cps or not s:
            self.stream.write(s)
            return
        step = 1.0 / self.cps
        pos = 0
        for m in SGR_RE.finditer(s):
            for ch in s[pos:m.start()]:
                self._tick(ch, step)
            self.stream.write(m.group(0))
            pos = m.end()
        for ch in s[pos:]:
            self._tick(ch, step)

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
            if self.mark:
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
            else:
                self._emit(" ")
                self.col += 1
        self._emit(w)
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
        if self.render and (self.bold or self.heading):
            self.stream.write("\033[0m")
        self.bold = self.em = self.heading = False
        self.stars = ""
        self.prev = ""

    def _char(self, ch):
        if self.verbatim:
            self._start()
            self._emit(ch)
            self.col += 1
            self.stream.flush()
            return
        if ch == "*" and self.render:
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
        self._start()
        self._reset_marks()
        self._emit("\n")
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
    cursor, up one, clear, draw, restore -- one write per frame); else it
    draws on the cursor's own row. stop() ends the thread, then clears
    once from the calling thread; idempotent; a context manager. Any
    OSError or ValueError on the stream goes silent -- the pulse is never
    a reason to fail."""

    FRAMES = (".", "..", "...")
    STEP = 0.35

    def __init__(self, stream=sys.stderr, above=False, mark=None, close=False):
        self.stream = stream
        self.above = above
        self.mark = glyph("hammer") if mark is None else mark
        self.close = close                      # close the stream in stop() (hint_row's /dev/tty)
        self.on = False
        self._stop = threading.Event()
        self._thread = None
        try:
            self.live = bool(stream) and stream.isatty()
        except (AttributeError, ValueError, OSError):
            self.live = False

    @classmethod
    def hint_row(cls):
        """The widgets' pulse: with SPARK_HINT_ROW=1 in the environment
        (the widgets set it around `spark line`; a hand-run spark line
        never touches the row above), a Busy drawing above the cursor on
        /dev/tty; otherwise, or when /dev/tty will not open, a silent
        one."""
        if os.environ.get("SPARK_HINT_ROW") == "1":
            try:
                return cls(open("/dev/tty", "w"), above=True, close=True)
            except OSError:
                pass
        return cls(None)

    def _frame(self, dots):
        body = paint(self.mark, "accent", self.stream) + " " + paint(dots, "muted", self.stream)
        if self.above:
            return "\x1b7\x1b[1A\r\x1b[2K" + body + "\x1b8"
        return "\r\x1b[2K" + body

    def _clear(self):
        return "\x1b7\x1b[1A\r\x1b[2K\x1b8" if self.above else "\r\x1b[2K"

    def _write(self, s):
        try:
            self.stream.write(s)
            self.stream.flush()
        except (OSError, ValueError):
            self.live = False

    def _run(self):
        i = 0
        while not self._stop.is_set() and self.live:
            self._write(self._frame(self.FRAMES[i % len(self.FRAMES)]))
            i += 1
            self._stop.wait(self.STEP)

    def start(self):
        if self.on or not self.live:
            return self
        self.on = True
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
# line the widgets print into a live terminal or a gate writes to
# stdout: a model -- or a log line it quotes -- could otherwise retitle
# the window, move the cursor or repaint the screen
_CSI = re.compile(r"\x1b\[[0-9;:?<=>!\"'#$%&*+,\-./ ]*[@-~]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")
_ESC_OTHER = re.compile(r"\x1b.?")


# man's bold (X\bX) and underline (_\bX) as a pager sees them: mandoc
# (Void) and macOS's man keep them in a pipe, man-db (Debian, Arch) does
# not. Dropping the backspace alone left "NNAAMMEE" for the model
_OVERSTRIKE = re.compile(".\x08")


def unstrike(s):
    """`s` with man's overstrikes gone, the letters kept."""
    return _OVERSTRIKE.sub("", s)


def scrub(s, keep="\t\n"):
    """`s` without terminal escape sequences (CSI, OSC and the rest),
    without man's overstrikes (the letter stays), and without control
    characters (\\x00-\\x1f, \\x7f) -- tabs and newlines excepted where
    they belong (`keep`)."""
    s = unstrike(s)
    s = _CSI.sub("", s)
    s = _OSC.sub("", s)
    s = _ESC_OTHER.sub("", s)
    return "".join(ch for ch in s if ch in keep or (ord(ch) >= 32 and ord(ch) != 127))


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
    return "spark: held back %d %s (%s) -- the model saw %s" % (n, what, ", ".join(names), HELD)


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
