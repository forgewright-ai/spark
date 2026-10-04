# spark.cli -- the client subcommands: line (what the widgets call),
# explain, last, brain, status, off, on, history, ver, and the thin
# wrappers to soul / memory / chat / do / lua (imported only when
# called). Dispatch lives in bin/spark's VERBS table; main() here is the
# fallback -- bare spark, or a question.

import json
import os
import re
import sys
import time

from . import CONFIG_DIR, MARK, OFF_FLAG, REPO, WIDGETS_DIR, config, die, glyph, paged, paint, say, state_dir
from . import bar, engine, forge, ledger, persona, session, version, wire
from . import text as textmod

HINT_COLS = 80             # a hint labels a command: terse
ANSWER_MAX = 300           # an answer IS the content: the widget fits it
                           # to the terminal's own width
STDIN_TAIL = 6000          # what `explain` sends at most: the last 6 kB

# Grammar rule 4: every verb answers -h first, signed per contract 8.
LINE_USAGE = """spark line -- the prompt line, for the shell widgets

  spark line --cwd D --shell S   read the prompt line on stdin; print the
                                 command or the answer, then the hint, then
                                 a check that it worked, when there is one
  spark line --paste             a pasted block on stdin: one line on what
                                 it does; nothing runs
"""
EXPLAIN_USAGE = """spark explain -- what went wrong, and the fix

  cmd 2>&1 | explain [words]  explain the output piped in (its last 6 kB)
  --reveal [N|auto|off]       the reply pace at a terminal
"""
LAST_USAGE = """spark last -- the last exchange

  spark last                  the last question, the answer, the model and
                              its speed
"""
STATUS_USAGE = """spark status -- what answers, and how this machine is set

  spark status                the model, the prompt line, the server, the
                              soul, the memory and the last answer
  spark brain --porcelain     for a program: url<TAB>model<TAB>forge|model,
                              exit 1 when nothing answers (--fresh asks again)
"""
OFF_USAGE = """spark off -- turn the prompt line off, in every shell

  spark off                   stop the ? line and the failure hint; Esc s
                              still works
"""
ON_USAGE = """spark on -- turn the prompt line back on

  spark on                    ? words and words? ask the model again
"""
HISTORY_USAGE = """spark history -- the threads kept on this machine

  spark history               the newest threads and the fixes remembered
  spark clear --history       remove every thread but the kept ones
"""
CLEAR_USAGE = """spark clear -- remove the history this machine keeps

  spark clear --history       remove every turn and thread but the kept
                              ones (/keep in spark chat)
"""
VER_USAGE = """spark ver -- the version

  spark ver                   the logo and the version
  spark ver --credits         who made spark and what it uses
  spark ver --sbom            what spark depends on, as CycloneDX JSON
"""


def _help(args, usage):
    """True (and the usage printed) when args ask for help."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(usage.rstrip())
        return True
    return False


def _one_line(s, width=HINT_COLS):
    """One line, cut at a word when it must be cut -- and the ellipsis
    from the glyph table, so a console shows ... and not a blank box.
    Escape sequences and control characters are scrubbed first: the
    widgets print this into a live terminal."""
    s = " ".join(textmod.scrub(s or "").split())
    if len(s) <= width:
        return s
    e = glyph("cut")
    s = s[:width - len(e)]
    if " " in s[-20:]:
        s = s[:s.rfind(" ")]
    return s + e


# The model's own name as a word, lowercase as spark writes it: never a
# piece of a path, a flag, a file name or a longer name.
SPARK_WORD = re.compile(r"(?<![\w/.~$=-])(?<!Apache )Spark(?![\w/-]|\.\w)")


def _tidy(s, hint=True, head=""):
    """The model's words as the hint row paints them. `Spark` as a word
    becomes `spark`, outside backticks (a command is never touched). A
    hint, not an answer, is a whole sentence: its first letter a capital
    and a full stop at its end (kept, or added after anything but `?`,
    `!` and an ellipsis). The capital never touches a command or a
    quoted span: not a first word in backticks or quotes, not spark's
    own name, not a word holding anything but letters, not `head` (the
    command's program)."""
    parts = (s or "").split("`")
    parts[::2] = [SPARK_WORD.sub("spark", p) for p in parts[::2]]
    s = "`".join(parts)
    if hint:
        s = _capital(s.strip(), head)
        if s and not s.endswith((".", "?", "!", glyph("cut"))):
            s += "."
    return s


def _capital(s, head=""):
    """`s` with its first letter a capital when its first word is a plain
    lowercase word: never a word in backticks or quotes, never spark's own
    name, never one holding anything but letters, never `head`."""
    first = s.split(" ", 1)[0].rstrip(",;:")
    if first.isalpha() and first.isascii() and first.islower() and first not in ("spark", head):
        return s[0].upper() + s[1:]
    return s


def _shell_default():
    return os.path.basename(os.environ.get("SHELL") or "sh")


# ------------------------------------------------------------------- line
def _last_proposed(history):
    """The last command a thread's assistant turns proposed: the text
    between the first backticks of the newest cmd-shaped message."""
    for m in reversed(history or []):
        c = m.get("content", "")
        if m.get("role") == "assistant" and c.startswith("`") and "`" in c[1:]:
            return c[1:1 + c[1:].index("`")]
    return None


def _bench_history(path):
    """SPARK_LINE_BENCH_HISTORY's file: a JSON list of {role, content},
    user and assistant turns only; anything else is no history."""
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return []
    return [{"role": m["role"], "content": m["content"]} for m in (got if isinstance(got, list) else [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]


def _failed_cmd():
    """The failing command and its exit code the widget exports for a
    failure turn (SPARK_EXPLAIN_CMD / _RC), or ('', None). The same two
    variables `explain` reads: a failure turn rides them into the line."""
    cmd = os.environ.get("SPARK_EXPLAIN_CMD", "").strip()
    rc = os.environ.get("SPARK_EXPLAIN_RC", "").strip()
    return cmd, (int(rc) if rc.isdigit() else None)


def _install_line(binary):
    """The `cmd\tinstall-line` for a known missing tool, computed here with
    no model call, or ('', ''). Only tools spark itself installs; anything
    else the model names."""
    from . import packages
    pkg = packages.package_for(binary)
    if not pkg:
        return "", ""
    return packages.install_line([pkg]), "%s installs %s (%s)" % (
        "brew" if packages.IS_MAC else packages.manager(), binary, pkg)


PASTE_MAX = 8000        # what a paste inspection reads, or it says so and sends nothing
# a paste that looks like a secret never leaves this machine: the list
# and the look live in spark.text (SECRET_SHAPES, secret_shape), beside
# the source's own (SOURCE_SHAPES, hold_secrets); the names stay here too
SECRET_SHAPES = textmod.SECRET_SHAPES
secret_shape = textmod.secret_shape


def _paste_verdict(shell):
    """`spark line --paste`: the pasted lines on stdin, no command back --
    one `answer` or `danger` line naming what the paste does (contract
    4's shape, without a command to land: the paste stays in the buffer
    and nothing runs). Over PASTE_MAX is one line saying so, NO model
    call; a paste that looks like a secret (SECRET_SHAPES) is one line
    naming the shape, NO model call, the turn recorded as numbers; a
    line the danger set knows forces `danger` whatever the model says."""
    data = textmod.stdin_text()
    if not data.strip():
        say("error")
        say("nothing pasted")
        return 1
    if len(data) > PASTE_MAX:
        say("answer")
        say("too big to check (%d characters) -- nothing sent" % len(data))
        return 0
    cfg = config.load()
    what = secret_shape(data)
    if what:
        say("answer")
        say("looks like a secret (%s) -- not sent" % what)
        session.record(cfg, mode="paste", kind="paste", chars=len(data), held=True)
        return 0
    # the reading of the whole paste (it skips a here-document's body),
    # then the patterns line by line, as do._dangerous reads a block
    local_danger = persona.is_dangerous(data) or any(persona.danger_shape(l) for l in data.splitlines())
    try:
        with textmod.Busy.hint_row(kind="read"):       # a text being read
            s = session.Session(cfg, "paste", shell, "", role="spark")
            reply, ms = s.ask_json(data, persona.PASTE_SCHEMA, max_tokens=120)
    except wire.BrainError as e:
        if local_danger:
            say("danger")
            say(_one_line("a pasted line can destroy -- read it before Enter", ANSWER_MAX))
            return 0
        say("error")
        say(_one_line(e.hint))
        return 1
    summary = _one_line(_tidy(str(reply.get("summary") or ""), hint=False), ANSWER_MAX) or "a paste"
    danger = bool(reply.get("danger")) or local_danger
    say("danger" if danger else "answer")
    say(summary)
    s.record(kind="paste", chars=len(data), ms=ms, danger=danger)
    return 0


# A model's command reaches line 1 only without these: C0 but the three
# whitespaces (a newline folds to a space, as it always has), DEL, C1 and
# the bidi controls -- do.CONTROL's set. Escapes a terminal would act on,
# and text that reads one way and runs another, refuse the reply whole.
LINE_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]")
LINE_REFUSED = "the model's command carried control characters -- refused"
LINE_TOKENS = 200          # what a line reply may write: five short fields


def _line_ask(s, text, on_delta=None, context=""):
    """One prompt-line request: streamed, the line's schema, the line's own
    slot (wire.LINE_SLOT), every chunk to on_delta as it comes. Returns
    (reply, ms). A reply that is not one JSON object is BrainError `bad`,
    worded as chat_json words it. `context` is a Reference block (the
    knowledge's evidence): it rides the user message, never the prefix."""
    t0 = time.time()
    raw, s.timings = s._retry_fresh(lambda: wire.chat_stream(
        s.cfg, s.url, s._messages(text, context), on_delta or (lambda d: None), max_tokens=LINE_TOKENS,
        temperature=0.2, forge=s.forge, model=s.role, schema=persona.LINE_SCHEMA, slot=wire.LINE_SLOT))
    try:
        reply = json.loads(raw)
        if not isinstance(reply, dict):
            raise ValueError
    except ValueError:
        raise wire.BrainError("bad", "the model did not return JSON: %s" % raw[:80].replace("\n", " "))
    return reply, int((time.time() - t0) * 1000)


def _reason(e):
    """A failure as line 2 says it: the hint, without the tail a streamed
    verb adds for an answer printed above it -- the line has none."""
    return _one_line(e.hint.split(" -- the answer above is incomplete")[0])


class _Fields:
    """The line's JSON object as it streams. feed(delta) returns the
    (key, value) pairs whose values closed in it, in order; `fields`
    holds every pair so far. One flat object of strings (escapes and all),
    booleans, numbers and null: the line's schema. Anything else stops it
    (`bad`), and the whole reply, parsed at the end, decides. A key seen
    twice keeps its first value: the one already printed."""

    def __init__(self):
        self.fields = {}
        self.state = "start"        # start key? key colon value string atom next done bad
        self.buf = ""
        self.key = None
        self.esc = False

    def _close(self, value, out):
        if self.key not in self.fields:
            self.fields[self.key] = value
            out.append((self.key, value))
        self.state, self.buf = "next", ""

    def _atom(self, out):
        try:
            self._close(json.loads(self.buf), out)
        except ValueError:
            self.state = "bad"

    def feed(self, delta):
        out = []
        for ch in delta:
            st = self.state
            if st in ("done", "bad"):
                break
            if st in ("key", "string"):
                if self.esc or ch == "\\":
                    self.esc = not self.esc
                    self.buf += ch
                elif ch != '"':
                    self.buf += ch
                else:
                    try:
                        text = json.loads('"' + self.buf + '"')
                    except ValueError:
                        self.state = "bad"
                        break
                    if st == "key":
                        self.key, self.state, self.buf = text, "colon", ""
                    else:
                        self._close(text, out)
                continue
            if st == "atom":
                if ch in " \t\r\n,}":
                    self._atom(out)
                    if self.state == "bad" or ch in " \t\r\n":
                        continue
                    st = "next"
                else:
                    self.buf += ch
                    continue
            if ch in " \t\r\n":
                continue
            if st == "start":
                self.state = "key?" if ch == "{" else "bad"
            elif st == "key?":
                self.state = "key" if ch == '"' else ("done" if ch == "}" and not self.fields else "bad")
            elif st == "colon":
                self.state = "value" if ch == ":" else "bad"
            elif st == "value":
                if ch == '"':
                    self.state = "string"
                elif ch in "tfn-0123456789":
                    self.state, self.buf = "atom", ch
                else:
                    self.state = "bad"
            elif st == "next":
                self.state = "key?" if ch == "," else ("done" if ch == "}" else "bad")
        return out


class _Pulse(textmod.Busy):
    """The line's pulse: text.Busy in the hint row until line 1 is out,
    then the reply's own mark (`*`, or `!` whole in warn) until line 2 --
    and stop() then leaves the row as it is, for the widget paints it
    next: the mark never blinks out while the command sits in the line.
    Where the look draws the face it stays beside the dots: thinking
    after line 1 (`* (o.O) ..`), puzzled while a re-ask runs, alarmed on
    a warn-marked row (`! (O.O) ..`)."""

    warn = False
    keep = False
    words = ""          # what the row says while a re-ask runs (tell)
    _was = None         # (warn, words, keep) of the frame before: a mood's score starts at its change
    _from = 0

    def _faced(self):
        return self.scan and self.face is not None

    def tell(self, words):
        """A whole sentence in the row, the dots after it, until line 1:
        cut to the terminal, so the saved cursor never wraps away."""
        try:
            cols = os.get_terminal_size(self.stream.fileno()).columns
        except (AttributeError, OSError, ValueError):
            cols = HINT_COLS
        room = cols - 6 - (len(self._face(0, "puzzled")) + 1 if self._faced() else 0)
        self.words = _one_line(words, max(20, min(HINT_COLS, room))) if words else ""

    def _body(self, i):
        # the mark and the words keep the dots in either motion: the row
        # is the reply's own now, and a scanner there would read as a wait
        if not self.warn and not self.words and not (self.keep and self._faced()):
            return super()._body(i)
        dots = self._dots(i)
        face = ""
        if self._faced():
            now = (self.warn, bool(self.words), self.keep)
            if now != self._was:
                self._was, self._from = now, i
            mood = "alarmed" if self.warn else "puzzled" if self.words else "thinking"
            face = self._face(i - self._from, mood)
        if self.warn:
            return paint(self.mark + " " + (face + " " if face else "") + dots, "warn", self.stream)
        head = paint(self.mark, "accent", self.stream) + " "
        if face:
            head += paint(face, "accent", self.stream) + " "
        return head + self.words + paint(dots, "muted", self.stream)

    def _clear(self):
        return "" if self.keep else super()._clear()


# ------------------------------------------------------ the line's knowledge
# The judge arms (v1.53): the verdict runs before line 1 is written; a
# command it finds wrong is asked again ONCE with the tool's own manual
# lines, and line 1 is never repainted. SPARK_KNOWLEDGE=off is the v1.52
# line exactly (arm off). The measuring seam SPARK_LINE_KNOW (under
# SPARK_LINE_BENCH=1 alone) picks an arm for the audition's A/B: judge =
# the verdict and the one re-ask; full = judge plus evidence up front.
# The shipped arm is one constant: full ships only when the A/B shows it
# earns its prefill (>= 5 points for <= 0.3 s median on the 4B). It did
# (G4, the box, qwen3-4b): full 82 % tools and 66 % spark core against
# judge's 80 % and 38 %, command ready 2.2 s either way.
LINE_KNOW_DEFAULT = "full"
LINE_KNOW_ARMS = ("off", "judge", "full")
ASK_AGAIN = "Answer again with a command that works on this machine."
REPEATED = "that exact command was already tried and failed; propose a different one."
NOTE_WORD = 24             # a flag or a head in a note: never the whole hint
NOTE_ROOM = 24             # a hint cut shorter than this beside a note is dropped


class _Stop(Exception):
    """The judge found the first command wrong before line 1: raised from
    the stream's own delta callback, so the response closes there (the
    server drops the task) and line 1 is never painted with it."""


def _line_arm(cfg, bench):
    """off | judge | full: SPARK_KNOWLEDGE (on = LINE_KNOW_DEFAULT), or the
    measuring seam SPARK_LINE_KNOW under SPARK_LINE_BENCH=1 alone."""
    if bench and os.environ.get("SPARK_LINE_KNOW") in LINE_KNOW_ARMS:
        return os.environ["SPARK_LINE_KNOW"]
    return LINE_KNOW_DEFAULT if cfg.knowledge else "off"


def _head(command):
    """A command's program: the first word past sudo, env, nohup and any
    assignment -- the head a `??` asks the index about."""
    words = (command or "").split()
    while words and (words[0] in ("sudo", "env", "nohup") or "=" in words[0]):
        words = words[1:]
    return words[0] if words else ""


class _Know:
    """One turn's knowledge: the arm, a verdict per command (kept, so the
    stream and the end never judge twice), the evidence, and the numbers
    the turn records -- know_ms (the index read and every verdict),
    evidence_chars, reasked, findings. Numbers alone: no word of it."""

    def __init__(self, arm):
        self.arm = arm
        self.ms = 0.0
        self.chars = 0
        self.reasked = 0
        self.findings = 0
        self.says = ""              # an answer's note: the manual the evidence named
        self._seen = {}

    def _timed(self, fn, *args, **kw):
        t0 = time.time()
        try:
            return fn(*args, **kw)
        finally:
            self.ms += (time.time() - t0) * 1000

    def verdict(self, command):
        """The findings on `command`: () when the judge finds nothing."""
        if command not in self._seen:
            from . import judge
            self._seen[command] = tuple(self._timed(judge.verdict, command).findings)
        return self._seen[command]

    def evidence(self, question, heads=(), confident=False):
        from . import grounding
        ev = self._timed(grounding.evidence, question, tuple(h for h in heads if h), confident=confident)
        self.chars += ev.chars
        return ev

    def upfront(self, question, previous):
        """Arm full: the Reference block the first request carries (the
        question, and on ?? the head last proposed) when grounding is
        confident of it; '' in the others."""
        if self.arm != "full":
            return ""
        ev = self.evidence(question, [_head(previous)] if previous else (), confident=True)
        if ev.names:
            from . import grounding
            try:
                e = grounding.default_store().entry(ev.names[0])
            except (OSError, ValueError, TypeError, AttributeError):
                e = None
            if e is not None and getattr(e, "source", "") == "man":
                self.says = ", says the %s manual" % _one_line(ev.names[0], NOTE_WORD)
        return ev.text

    def flagged(self, command, model_danger, rode):
        """The `!`: persona.is_dangerous always wins. In the judge arms
        the model's own flag is lowered when spark's read-only argv proof
        (judge.read_only, the proof lists unchanged) holds for every
        stage, and a command whose effect the line cannot show
        (persona.opaque) is marked whenever evidence rode the request
        that produced it. Arm off: v1.52's rule."""
        if persona.is_dangerous(command):
            return True
        if self.arm == "off":
            return bool(model_danger)
        if rode and persona.opaque(command):
            return True
        from . import judge
        return bool(model_danger) and not judge.read_only(command)

    def numbers(self):
        out = {"arm": self.arm, "reasked": self.reasked}
        if self.arm != "off":
            out.update(know_ms=int(round(self.ms)), evidence_chars=self.chars, findings=self.findings)
        return out


def _nw(s):
    return _one_line(s, NOTE_WORD)


def _said(f):
    """A finding as the re-ask tells the model: one whole sentence."""
    if f.kind == "missing":
        return "%s is not installed on this machine." % f.head
    if f.kind == "flag":
        return "%s is not in %s's manual here." % (f.word, f.head)
    if f.kind == "command":
        return "%s is not a command in %s's manual here." % (f.word, f.head)
    if f.kind == "verb":
        if f.head == "spark":
            return "spark has no %s command." % f.word
        return "%s is not a word %s takes." % (f.word, f.head)
    return "%s is a placeholder; write the real name, or leave it out." % f.word


def _gap(f):
    """A finding as the hint row says it: lowercase, no end mark."""
    if f.kind == "missing":
        return "%s is not on this machine" % _nw(f.head)
    if f.kind == "flag":
        return "the %s manual has no %s" % (_nw(f.head), _nw(f.word))
    if f.kind == "command":
        return "%s has no command %s" % (_nw(f.head), _nw(f.word))
    if f.kind == "verb":
        if f.head == "spark":
            return "spark has no %s command" % _nw(f.word)
        return "%s takes no %s" % (_nw(f.head), _nw(f.word))
    return "the command still holds %s" % _nw(f.word)


def _left(f):
    """The note on a command that still has a finding after the re-ask:
    it lands (never blocked) and the hint says what to check."""
    if f.kind == "placeholder":
        name = " ".join(f.word.strip("<>[]").replace("_", " ").replace("-", " ").split())
        return "type the %s before Enter" % ("file name" if name in ("file", "filename") else _nw(name))
    if f.kind == "command":
        return "the %s manual has no command %s -- check it before Enter" % (_nw(f.head), _nw(f.word))
    return _gap(f) + " -- check it before Enter"


def _noted(lead, hint, note, width=HINT_COLS):
    """lead + hint + note as one line within `width`. The cut eats the
    model's words, never the lead (a danger's facts) or the note. A note
    starting with a comma follows the words; any other is a clause of
    its own after `; `. The model's end mark goes before a note, and a
    hint with less than NOTE_ROOM columns left is dropped whole rather
    than cut to a fragment (one that fits whole stays)."""
    if not note:
        return _one_line(lead + hint, width)
    hint = (hint or "").rstrip().rstrip(".").rstrip()
    tail = note if note.startswith(",") else "; " + note
    room = width - len(lead) - len(tail)
    if not hint or room < min(len(hint), NOTE_ROOM):
        return _one_line(lead + note.lstrip(", "), width)
    return _one_line(lead + _one_line(hint, room) + tail, width)


def _sentence(build, width=HINT_COLS):
    """A hint line as a whole sentence within `width`: build(width), and a
    full stop at its end when it has none (a note's words, which _noted
    places after the model's own end mark was taken) -- built again one
    column narrower when the stop would not fit."""
    line = build(width)
    if not line or line.endswith((".", "?", "!", glyph("cut"))):
        return line
    if len(line) >= width:
        line = build(width - 1)
        if not line or line.endswith((".", "?", "!", glyph("cut"))):
            return line
    return line + "."


class _Early:
    """Contract 4's lines, written the moment the stream makes each one
    certain. Line 1 goes out only when nothing after it can change it: the
    kind known; for a cmd, the command closed and cut to one line, free of
    LINE_CONTROL, earning no guard (a `??` that repeats the failed command;
    in the judge arms a verdict with a finding, which stops the stream --
    in arm off a head word nothing here answers to) and its danger known
    (_Know.flagged). Anything short of that waits for the whole reply and
    the path it always took. Line 2 follows when its field closes, a
    danger's blast facts first, a note last; line 3 is left to the end,
    after persona.proof_ok. A re-ask's stream (retry) lands only a
    command early, and never stops."""

    def __init__(self, cwd, more, history, busy, know=None, rode=False, retry=False, note="", t0=None):
        self.cwd, self.more, self.history, self.busy = cwd, more, history, busy
        self.know = know or _Know("off")
        self.rode = rode            # evidence rode the request this reply answers
        self.retry = retry
        self.note = note            # line 2's last words on a command (_noted)
        self.says = ""              # line 2's last words on an answer
        self.parse = _Fields()
        self.t0 = time.time() if t0 is None else t0
        self.head = None            # cmd | danger | answer, once line 1 is out
        self.command = ""
        self.hint = None            # line 2, once out
        self.cmd_ms = None
        self.off = False            # something the end must weigh: no early line

    def ms(self):
        return int((time.time() - self.t0) * 1000)

    def feed(self, delta):
        self.parse.feed(delta)
        if not self.off:
            self._advance()

    def line1(self, head, command=""):
        """Line 1, from whichever path gets there: the time is cmd_ms."""
        self.head, self.command = head, command
        self.cmd_ms = int((time.time() - self.t0) * 1000)
        say(head + "\t" + command if command else head)

    def line2(self, text):
        self.busy.stop()
        self.hint = text
        say(text)

    def _try_first(self, f):
        """Line 1 when the fields so far make it certain: True once out."""
        if "kind" not in f:
            return False
        raw = f.get("command")
        if f["kind"] == "cmd":
            if raw is None:
                return False
            if not isinstance(raw, str) or LINE_CONTROL.search(raw):
                self.off = True
                return False
        command = _one_line(raw, 1000) if f["kind"] == "cmd" else ""
        if not command:
            if self.retry:
                self.off = True             # a re-ask lands a command early, or waits for the end
                return False
            return self._first("answer")
        if self.more and command == _last_proposed(self.history):
            self.off = True
            return False
        if self.know.arm == "off":
            if persona.missing_word(command):
                self.off = True
                return False
        elif self.know.verdict(command):
            # the judge found it wrong: line 1 never shows it. The first
            # stream stops here; a re-ask's runs on, for the end weighs
            # it whole against the first
            self.off = True
            if not self.retry:
                raise _Stop()
            return False
        if not persona.is_dangerous(command) and "danger" not in f:
            return False
        danger = self.know.flagged(command, f.get("danger"), self.rode)
        return self._first("danger" if danger else "cmd", command)

    def _advance(self):
        f = self.parse.fields
        if (self.head is None and not self._try_first(f)) or self.hint is not None:
            return
        text = self.second(f)
        if text is not None:
            self.line2(text)

    def second(self, f, final=False):
        """Line 2 from the fields, or None while they cannot tell it yet
        (never None when `final`: the reply is whole)."""
        def s(k):
            v = f.get(k)
            return v if isinstance(v, str) else ""
        hint = f.get("hint")
        if self.head == "answer":
            # an answer is the content, not a label: its budget is
            # characters, and the widget trims to the terminal's own width
            if not final and (hint is None or (not hint and "command" not in f)):
                return None
            return _noted("", _tidy(s("hint"), hint=False) or s("command"), self.says, ANSWER_MAX)
        if hint is None and not final:
            return None
        return self.label(_one_line(s("hint")))

    def label(self, hint):
        """A command's line 2: a danger's persona.blast facts first, the
        model's words (_tidy), then the note -- so contract 4's 80-char
        cut eats the model's words before the numbers or the note."""
        facts = persona.blast(self.command, self.cwd) if self.head == "danger" else ""
        lead = "<- " + facts + " -- " if facts else ""
        head = _head(self.command)
        return _capital(_sentence(lambda w: _noted(lead, _tidy(hint, head=head), self.note, w)), head)

    def _first(self, head, command=""):
        # the pulse turns to the reply's own mark before the line leaves,
        # so the row never shows the old one beside the landed command
        self.busy.words = ""
        self.busy.mark = "!" if head == "danger" else "*"
        self.busy.warn = head == "danger"
        self.busy.keep = True
        self.line1(head, command)
        return True


def _guards(s, reply, command, hint, text, cwd, more, history, ms):
    """The two re-asks a cmd reply may earn, then the danger verdict:
    (reply, command, hint, kind, ms) with kind `cmd` or `danger`."""
    # the head-word guard: a command whose head word nothing here
    # answers to is re-asked once; failing that, the hint says so.
    # Never blocks, never errors -- the user still sees a reply.
    missing = persona.missing_word(command)
    if missing:
        try:
            s.history.extend([{"role": "user", "content": persona.user_message(text, cwd)},
                              {"role": "assistant", "content": "`%s` -- %s" % (command, hint)}])
            retry, ms2 = _line_ask(s, "%s is not installed on this machine; use only commands that exist here." % missing)
            ms += ms2
            c2 = _one_line(retry.get("command", ""), 1000)
            if retry.get("kind") == "cmd" and c2 and not persona.missing_word(c2):
                reply, command, missing = retry, c2, ""
                hint = _one_line(retry.get("hint", ""))
        except wire.BrainError:
            pass
        if missing:
            hint = _one_line("%s: not on this machine -- %s" % (missing, hint))
    if more and command == _last_proposed(history):
        # the repair guard: a ?? turn must not re-serve the very command
        # the user just said failed. One re-ask; then honesty.
        try:
            s.history.extend([{"role": "user", "content": persona.user_message(text, cwd)},
                              {"role": "assistant", "content": "`%s` -- %s" % (command, hint)}])
            retry, ms2 = _line_ask(s, "that exact command was already tried and failed; propose a different one.")
            ms += ms2
            c3 = _one_line(retry.get("command", ""), 1000)
            if retry.get("kind") == "cmd" and c3 and c3 != command:
                reply, command = retry, c3
                hint = _one_line(retry.get("hint", ""))
            else:
                hint = _one_line("already tried above -- %s" % hint)
        except wire.BrainError:
            hint = _one_line("already tried above -- %s" % hint)
    flagged = bool(reply.get("danger")) or persona.is_dangerous(command)
    return reply, command, hint, "danger" if flagged else "cmd", ms


def _line_stream(s, text, early, context=""):
    """One streamed ask through `early`: (reply, ms, error). A _Stop ends
    the stream at the command the judge found wrong -- the reply is the
    fields so far. A BrainError comes back third, never raised."""
    try:
        reply, ms = _line_ask(s, text, early.feed, context)
        return dict(reply, **early.parse.fields), ms, None     # a key's first value is the one printed
    except _Stop:
        return dict(early.parse.fields), early.ms(), None
    except wire.BrainError as e:
        return None, early.ms(), e


def _judged(s, reply, command, hint, text, asked, ms, know, early):
    """The judge arms' guard, one re-ask per turn at most. The verdict on
    the command and a `??` that repeats the failed one fold into ONE
    re-ask: a whole sentence per finding, the found heads' evidence as
    its Reference, the pulse saying why. The re-ask streams through a
    fresh _Early sharing the pulse, which paints the moment its command
    passes, the hint then saying what it was checked against. Else the
    reply with fewer findings lands (the re-ask on a tie: the first was
    stopped before its hint), never blocked, its hint naming what is
    left. Returns (reply, command, hint, kind, ms, early, error):
    `early` is the one that painted, or that paints at the end."""
    found = know.verdict(command)
    know.findings = len(found)
    repeat = early.more and command == _last_proposed(early.history)
    rode = early.rode
    if found or repeat:
        said = [_said(f) for f in found] + ([REPEATED] if repeat else [])
        # a head that is not here: the installed programs that do its job
        # are named, and their entries ride as the evidence
        gone = [f.head for f in found if f.kind == "missing"]
        from . import judge
        alike = know._timed(judge.installed_alike, text, gone) if gone else []
        if alike:
            said.append("Installed here: %s." % ", ".join("%s (%s)" % (n, w) if w else n for n, w in alike))
        ev = know.evidence(text, [f.head for f in found if f.kind != "missing"] + [n for n, _w in alike])
        if found:
            early.busy.tell(_gap(found[0]) + " -- asking again")
        s.history.extend([{"role": "user", "content": asked},
                          {"role": "assistant", "content": "`%s`" % command}])
        again = _Early(early.cwd, early.more, early.history, early.busy, know, rode=bool(ev.text),
                       retry=True, t0=early.t0)
        retry, ms2, err = _line_stream(s, " ".join(said) + " " + ASK_AGAIN, again, ev.text)
        know.reasked, ms = 1, ms + ms2
        if again.head is not None:
            return retry or dict(again.parse.fields), again.command, again.hint or "", again.head, ms, again, err
        early.busy.tell("")
        raw = (retry or {}).get("command")
        c2 = _one_line(raw, 1000) if isinstance(raw, str) and not LINE_CONTROL.search(raw) else ""
        if retry and retry.get("kind") == "cmd" and c2:
            left = know.verdict(c2)
            rep2 = early.more and c2 == _last_proposed(early.history)
            if len(left) + rep2 <= len(found) + repeat:
                reply, command, rode, repeat = retry, c2, bool(ev.text), rep2
                hint = _one_line(retry.get("hint", ""))
                found = left
        if found:
            early.note = _left(found[0])
        if repeat:
            hint = _one_line("already tried above -- %s" % hint)
    kind = "danger" if know.flagged(command, reply.get("danger"), rode) else "cmd"
    return reply, command, hint, kind, ms, early, None


class _Tee:
    """stdout as it was, every byte the same, and a copy kept: what clear
    mode reads once spark line has written its lines."""

    def __init__(self, out):
        self.out, self.kept = out, []

    def write(self, s):
        self.kept.append(s)
        return self.out.write(s)

    def flush(self):
        self.out.flush()

    def lines(self):
        return "".join(self.kept).splitlines()

    def __getattr__(self, name):
        return getattr(self.out, name)


def cmd_line(args):
    """Contract 4. stdin = the prompt buffer. stdout line 1 = cmd<TAB>command
    | danger<TAB>command | answer | error; line 2 = hint / answer / reason.
    SPARK_VOICE=clear: the lines, once written, are read aloud by a
    detached process (voice.aloud_later) -- the widget waits for no
    speech, and stdout stays byte for byte contract 4. Never in mode on.
    The mode is read from the config alone: the line imports no voice
    unless it speaks."""
    try:
        clear = config.load().get("SPARK_VOICE", "off").strip().lower() == "clear"
    except Exception:       # noqa: BLE001 -- the voice never breaks the line
        clear = False
    if not clear:
        return _cmd_line(args)
    from . import voice
    tee = sys.stdout = _Tee(sys.stdout)
    try:
        return _cmd_line(args)
    finally:
        sys.stdout = tee.out
        if not (args[:1] and args[0] in ("-h", "--help", "help")):
            voice.aloud_later(None, voice.line_words(tee.lines()))


def _cmd_line(args):
    if _help(args, LINE_USAGE):
        return 0
    cwd, shell = "", _shell_default()
    if "--paste" in args:
        return _paste_verdict(shell)
    it = iter(args)
    for a in it:
        if a == "--cwd":
            cwd = next(it, "")
        elif a == "--shell":
            shell = next(it, shell)
    text = textmod.stdin_text().strip()
    more = text.startswith("??")            # `?? words`: go on with the newest thread
    if more:
        text = text[2:].strip()
    elif text.startswith("? "):
        text = text[2:].strip()
    elif text.startswith("?"):
        text = text[1:].strip()
    if text.endswith("?"):
        text = text[:-1].rstrip() + "?"
    if not text.strip("? "):
        say("error")
        say("nothing to ask")
        return 1
    # command not found (127): the failed head word names a tool. If spark
    # installs it, the install line is known here with no model call; else
    # the model is told what is missing and asked to name its package.
    fcmd, frc = _failed_cmd()
    install_ctx = ""
    if frc == 127 and fcmd:
        head = fcmd.split()[0] if fcmd.split() else ""
        while head in ("sudo", "env", "nohup"):
            rest = fcmd.split()[1:]
            head = rest[0] if rest else ""
            fcmd = " ".join(rest)
        line, why = _install_line(head)
        if line:
            say("cmd\t" + line)
            say(_one_line(why))
            return 0
        install_ctx = ("Command not found: %s. Reply with the single command "
                       "that installs it on this machine, and a hint naming the "
                       "package." % head)
    elif frc is not None and fcmd and text.strip().lower() in ("fix it", "? fix it", "fix"):
        # a second Esc s after an explain: correct the command that failed
        install_ctx = ("The command `%s` failed with exit %d. Reply with a "
                       "corrected command that does what it was trying to do."
                       % (fcmd, frc))
    cfg = config.load()
    # `??` on a logged-in client of a FORGE continues the newest thread
    # ON THE FORGE -- one identity, every door: the box's prompt, this
    # prompt and the page share it. Any trouble falls back to the local
    # store, as before.
    remote = False
    thread, history = None, []
    # a measuring run (spark bench --line, the prompt-line audition) keeps
    # the turn's numbers, marked bench, and no thread: its questions are
    # not the person's history
    bench = os.environ.get("SPARK_LINE_BENCH") == "1"
    if more and cfg.client and not bench:
        got = forge.peer_newest(cfg)
        if got:
            thread, history = got
            remote = True
    if not remote and not bench:
        thread, history = forge.pick(cfg, more)
    elif bench and more and os.environ.get("SPARK_LINE_BENCH_HISTORY"):
        # the audition's `??` pair: a bench turn keeps no thread, so the
        # first turn rides this file (a measuring seam; nothing written)
        history = _bench_history(os.environ["SPARK_LINE_BENCH_HISTORY"])
    ask_text = (install_ctx + "\n\n" + text) if install_ctx else text
    # the knowledge's arm; in arm full the question's evidence rides the
    # first request's user message (the prefix never changes)
    know = _Know(_line_arm(cfg, bench))
    context = know.upfront(text, _last_proposed(history) if more else None)
    # the pulse in the hint row (SPARK_HINT_ROW=1, the widgets' word) from
    # the ask to line 1 -- through the guards' re-asks when a reply earns
    # one -- then in the reply's own mark until line 2
    busy = _Pulse.hint_row().start()
    early = _Early(cwd, more, history, busy, know, rode=bool(context))
    early.says = know.says
    s, extra, err = None, ({"bench": 1} if bench else {}), None
    try:
        s = session.Session(cfg, "line", shell, cwd, history)
    except wire.BrainError as e:
        err = e
    if s is not None and bench and os.environ.get("SPARK_LINE_ROLE") in ("spark", "ember"):
        # the measuring seam (the audition's --role, SPARK_LINE_BENCH=1
        # alone): the line's own prompt, asked of that role
        prefix = s._system()
        s.role, s._system = os.environ["SPARK_LINE_ROLE"], (lambda: prefix)
        sys.stderr.write("spark: SPARK_LINE_ROLE=%s -- a test seam: the line asks that role\n" % s.role)
    if s is not None:
        reply, ms, err = _line_stream(s, ask_text, early, context)
    if err is None and early.head is None:
        # nothing went early: the whole reply, the guards, then the lines
        kind = reply.get("kind")
        command = _one_line(reply.get("command", ""), 1000)
        hint = _one_line(reply.get("hint", ""))
        is_cmd = kind == "cmd" and bool(command)
        refused = is_cmd and LINE_CONTROL.search(str(reply.get("command")))
        if is_cmd and not refused:
            if know.arm == "off":
                n = len(s.history)
                reply, command, hint, kind, ms = _guards(s, reply, command, hint, text, cwd, more, history, ms)
                know.reasked = int(len(s.history) > n)
            else:
                asked = persona.user_message(ask_text, cwd, context)
                reply, command, hint, kind, ms, early, err = _judged(s, reply, command, hint, text, asked,
                                                                     ms, know, early)
            refused = LINE_CONTROL.search(str(reply.get("command")))      # a re-ask's command too
    extra = dict(extra, **know.numbers())
    if err is not None:
        busy.stop()
        if early.head is None:
            say("error")
            say(_reason(err))
            return 1
        ms = early.ms()
        if early.hint is None:
            # line 1 is out: the reason is line 2, and the exit says so
            early.line2(_reason(err))
            s.record(kind=early.head, failed=err.kind, cmd_ms=early.cmd_ms, ms=ms, thread=thread, **extra)
            return 1
        # lines 1 and 2 are whole: the reply stands, without its proof
        reply, extra = dict(early.parse.fields, proof=""), dict(extra, failed=err.kind)
    if early.head is None:
        busy.stop()
        if refused:
            say("error")
            say(LINE_REFUSED)
            s.record(kind="refused", ms=ms, thread=thread, **extra)
            return 1
        if is_cmd:
            early.line1(kind, command)
            early.line2(early.label(hint))
        else:
            early.line1("answer")
            early.line2(early.second(reply, final=True))
    else:
        busy.stop()
        kind, command, is_cmd = early.head, early.command, early.head != "answer"
        if early.hint is None:
            early.line2(early.second(reply, final=True))
        hint = early.hint
    if is_cmd:
        # contract 4's optional third line: one read-only command that
        # shows the change happened. A proof that is not read-only
        # (persona.proof_ok's allowlist) is refused here, never printed.
        proof = _one_line(reply.get("proof", ""), 1000)
        if proof and persona.proof_ok(proof):
            say("proof\t" + proof)
        else:
            proof = ""
        shown = "`%s` -- %s" % (command, hint)
        s.record(kind=kind, line=text, command=command, hint=hint, proof=proof, ms=ms,
                 cmd_ms=early.cmd_ms, thread=thread, **extra)
    else:
        kind = "answer"
        shown = hint
        s.record(kind=kind, line=text, answer=shown, ms=ms, cmd_ms=early.cmd_ms, thread=thread, **extra)
    if remote:
        forge.peer_append(cfg, thread, "user", text, mode="line")
        forge.peer_append(cfg, thread, "assistant", shown, kind=kind)
    else:
        forge.append(cfg, thread, "user", text, mode="line", cwd=cwd)
        forge.append(cfg, thread, "assistant", shown, kind=kind)
    _prune(cfg)
    return 0


def _prune(cfg):
    session.prune(cfg)
    forge.prune(cfg)


# ---------------------------------------------------------------- ask etc.
def _stdin_context():
    if sys.stdin.isatty():
        return ""
    data = textmod.stdin_text(source=True)
    if len(data) > STDIN_TAIL:
        data = "[... %d chars cut ...]\n" % (len(data) - STDIN_TAIL) + data[-STDIN_TAIL:]
    return data


def reveal_flag(args):
    """`--reveal [N|auto|off]` anywhere in args -> (args without it, pace):
    the word after it when it is one of those (N in reveal's 5..200,
    else a refusal, exit 2), `auto` with no word; no flag -> the
    standing choice, SPARK_REVEAL in spark.env (off by default). The
    pace is "auto", 0 (off) or N; stream_turn resolves auto at the turn.
    Piped, the wrap ignores it anyway."""
    from . import reveal
    args = list(args)
    if "--reveal" not in args:
        return args, config.load().reveal
    i = args.index("--reveal")
    word = "auto"
    rest = args[:i] + args[i + 1:]
    if i < len(args) - 1 and (args[i + 1].isdigit() or args[i + 1] in ("auto", "off")):
        word = args[i + 1]
        rest = args[:i] + args[i + 2:]
    return rest, reveal_word(word, lambda m: die(m))


def reveal_word(word, refuse):
    """auto -> "auto", off -> 0, N -> N within reveal's range; anything
    else -> refuse(message), whose return is handed back."""
    from . import reveal
    if word == "auto":
        return "auto"
    if word == "off":
        return 0
    try:
        n = int(word)
    except ValueError:
        n = -1
    if not reveal.CPS_MIN <= n <= reveal.CPS_MAX:
        return refuse("--reveal takes N (%d to %d), auto or off" % (reveal.CPS_MIN, reveal.CPS_MAX))
    return n


def stream_turn(cfg, mode, text, files=(), context="", thread=None, line=None, mark=True, cps=0,
                said=None, voice=None, linger=False):
    """One turn through forge.reply, wrapped to the terminal (80 when
    piped): the mark (mark=False keeps a conversation bare -- a dialog
    needs no mark), the answer as it streams, a trailing newline. `said`
    (a list) gains the turn's two messages, as forge.reply keeps them. `voice` (the chat's
    forge._Spoken, a reply read aloud): with the reveal on at a terminal
    of this machine, the text follows the voice -- each sentence shown as
    its sound starts, at its pace; else the voice has each chunk once the
    wrap wrote it, never ahead of the screen. Where the look's motion and
    words are active the face leads the reply in the mark's place
    (text.reply_face, or the voice's own): it talks while the text
    flows, and rests on a mood's still when the reply ends -- pleased,
    puzzled when the cap cut it, alarmed when the model failed. Nothing
    is drawn after this returns, unless `linger` (the chat: a prompt
    waits next, so the mood's score may play; forge.FACE holds the face
    until a key rests it). Returns the thread id. RefError,
    BrainError and KeyboardInterrupt pass through -- the wrap is closed
    first so a half-printed answer still ends in a newline; forge.reply
    keeps the raw text for the thread record."""
    if cps == "auto":
        from . import reveal
        cps = reveal.auto_cps(cfg)
    # a spoken reply in the chat opens with the talking face where the
    # look draws one (forge._Spoken.screen): its stream and its lead
    out, lead = voice.screen() if voice is not None else (sys.stdout, None)
    if lead is None and mark:
        # a reply not read aloud: the face leads it too, talking while
        # its text flows (a pipe, an unawakened machine: stdout, no lead)
        forge._face_rest()
        out, lead = textmod.reply_face(sys.stdout)
    face = out if lead else None
    wrap = textmod.Wrap(out, mark=mark, cps=cps, lead=lead)
    # the pulse on stderr from the request until the first chunk (a tty
    # only: piped, nothing is drawn); the wrap's mark takes over from it
    busy = textmod.Busy(sys.stderr).start()
    follow = voice is not None and bool(wrap.cps) and voice.follows()
    if follow:
        voice.begin(wrap, busy)
    # the model's escapes and controls go before anything shows or speaks
    # them (the wrap scrubs again: the same text passes unchanged)
    clean = textmod.Printable()

    def feed(delta):
        delta = clean.feed(delta)
        if not delta:
            return
        if follow:
            voice.take(delta)
            return
        busy.stop()
        wrap.feed(delta)
        if voice is not None:
            try:
                voice.feed(delta)
            except Exception:  # noqa: BLE001 -- the voice never breaks the reply it speaks
                pass
    try:
        thread, _, _ = forge.reply(cfg, thread, text, files, os.getcwd(), _shell_default(), mode, feed, context, line,
                                   said=said)
        mood = "puzzled" if forge.FINISH[0] == "length" else "pleased"
        if face:
            face.mood = mood        # known before the voice ends: its thread may finish first
        if follow:
            try:
                voice.end()
            except KeyboardInterrupt as e:
                e.thread = thread
                raise
        elif voice is not None:
            try:
                voice.flush()
            except Exception:  # noqa: BLE001
                pass
    except (wire.BrainError, KeyboardInterrupt) as e:
        if follow:
            voice.stop(rest=isinstance(e, wire.BrainError))
        busy.stop()
        wrap.close()
        if face:
            face.settle("alarmed" if isinstance(e, wire.BrainError) else "idle")
        raise
    except BaseException:
        if face:
            face.rest()
        raise
    finally:
        busy.stop()
    wrap.close()
    if face:
        face.settle(mood, play=linger)
        if linger:
            forge.FACE[0] = face
    _prune(cfg)
    return thread


def _stream(mode, text, files=(), context="", thread=None, line=None, mark=True, cps=0):
    """stream_turn as a command: a refusal or a dead brain ends with exit 1."""
    try:
        stream_turn(config.load(), mode, text, files, context, thread, line, mark, cps)
    except forge.RefError as e:
        die(e.hint)
    except wire.BrainError as e:
        print(textmod.faced("! " + e.hint, "alarmed", sys.stderr), file=sys.stderr, flush=True)
        sys.exit(1)
    return 0


def cmd_ask(words):
    words, cps = reveal_flag(words)
    words, paths = forge.refs(words)
    q = " ".join(words).strip()
    ctx = _stdin_context()
    if not q and not ctx and not paths:
        return cmd_status([])
    mode = "explain" if ctx and not q else "answer"
    return _stream(mode, q, paths, ctx, line=None if q or paths else "[explain]", cps=cps)


def cmd_explain(words):
    if _help(words, EXPLAIN_USAGE):
        return 0
    words, cps = reveal_flag(words)
    ctx = _stdin_context()
    # the widget's Esc s rides the failed command and its exit code along
    # (one-shot variables, cleared at the next prompt): with them, the
    # answer can name the command and correct it -- and a command that
    # failed in silence still gets an answer instead of a refusal
    cmd = os.environ.get("SPARK_EXPLAIN_CMD", "").strip()
    rc = os.environ.get("SPARK_EXPLAIN_RC", "").strip()
    if not ctx and not cmd:
        die("explain reads what is piped in -- cmd 2>&1 | explain")
    if cmd:
        if rc.isdigit() and rc != "0":
            # failure memory: remember this failure's shape until a fix
            # works (ledger.fail_fix, the widgets' second Esc s)
            first = next((l for l in ctx.splitlines() if l.strip()), "") if ctx else ""
            ledger.fail_pending(cmd, int(rc), first)
        ctx = "Command: %s\nExit: %s\nOutput:\n%s" % (cmd, rc or "unknown", ctx or "(none)\n")
    return _stream("explain", " ".join(words).strip(), context=ctx, line="[explain] " + " ".join(words), cps=cps)


# ------------------------------------------------------------ last/status
def _first_line(text, width=70):
    """The first line of a reply that is neither blank nor a code fence,
    cut at a word to about `width` characters (status's one line)."""
    line = next((l.strip() for l in text.splitlines()
                 if l.strip() and not textmod.Fence._is_fence(l)), "")
    if len(line) <= width:
        return line
    cut = line[:width - 3].rsplit(" ", 1)[0].rstrip()
    return (cut or line[:width - 3]) + "..."


def _fmt_turn(t, short=False):
    # a turn is numbers only (session.TEXT_FIELDS); the words come from
    # the sealed thread it names, when this machine can open it. short:
    # status's form, the reply's first line of words only
    if not t:
        return "none yet"
    line = body = ""
    if t.get("thread"):
        msgs = forge.load(t["thread"])
        asked = [m for m in msgs if m.get("role") == "user"]
        replied = [m for m in msgs if m.get("role") == "assistant"]
        # the thread keeps the model's own bytes: its escapes and controls
        # go before they reach a terminal (`spark last`, /last)
        line = textmod.printable(asked[-1]["text"]) if asked else ""
        body = textmod.printable(replied[-1]["text"]) if replied else ""
        if short:
            body = _first_line(body) or body.strip()[:70]
    head = "%s  %s  %s" % (t.get("ts", "?"), t.get("kind", "?"), line)
    mark = glyph("warn") if t.get("kind") == "danger" else glyph("hammer")
    body = "  %s %s" % (mark, body) if body else "  (the words are gone)"
    tail = "  %s, %s" % (config.model_name(t.get("model") or "?"), speed(t))
    if t.get("thread"):
        tail += "  thread %s" % t["thread"]
    return "\n".join([head, body, tail])


def speed(t):
    """'12.3 tok/s (prompt 96 tok/s, 1.1 s)' for a turn, or just the time"""
    ms = t.get("ms")
    secs = "%.1f s" % (ms / 1000.0) if isinstance(ms, (int, float)) else "?"
    if t.get("tg_tps"):
        return "%.1f tok/s (prompt %.0f tok/s, %s)" % (t["tg_tps"], t.get("pp_tps") or 0, secs)
    return secs


RECALL_USAGE = """spark recall -- find a command you ran by what it did

  <history> | spark recall <words>   the history on stdin; up to 5 lines
                                     of it that match, best first (Esc r
                                     at the prompt does this)
"""


def cmd_recall(args):
    """Intent search over the shell's own history (given on stdin). The
    model matches meaning; every candidate is then checked against the
    history with text.anchor, so a line that was not in it is dropped and
    the answer is always a command that ran. One per line; none -> one line
    on stderr, exit 1. A span that looks like a secret (text.SOURCE_SHAPES)
    is held back before the history leaves, one stderr line says so, and
    the turn records `held`. Nothing is written; the turn record is
    numbers."""
    if _help(args, RECALL_USAGE):
        return 0
    intent = " ".join(args).strip()
    history = textmod.stdin_text()
    if not intent:
        print("! say what the command did -- spark recall <words>", file=sys.stderr)
        return 1
    if not history.strip():
        print("! no history on stdin", file=sys.stderr)
        return 1
    cfg = config.load()
    # the history is held back line by line before it rides the request
    # (an `export TOKEN=...` the user once typed is not the model's): a
    # held line keeps its place, so an answer quoting it maps back to the
    # line that ran, and that one, the user's own text, is printed
    orig = history.splitlines()
    sent, held, names = [], 0, []
    for l in orig:
        spans, found = textmod.held_spans(l)
        sent.append(textmod.hold_spans(l, spans) if spans else l)
        held += len(spans)
        names += found
    if held:
        history = "\n".join(sent) + ("\n" if history.endswith("\n") else "")
        print(textmod.held_line(held, textmod.shape_order(names)), file=sys.stderr, flush=True)
    prompt = "What I am looking for: %s\n\nMy shell history:\n%s" % (intent, history)
    try:
        # the pulse in the hint row while the model looks (SPARK_HINT_ROW,
        # the widgets' word on Esc r: contract 4's row); silent by hand
        with textmod.Busy.hint_row():
            s = session.Session(cfg, "recall", _shell_default(), "", role="spark")
            reply, ms = s.ask_json(prompt, persona.RECALL_SCHEMA, max_tokens=300)
    except wire.BrainError as e:
        print(textmod.faced("! " + e.hint, "alarmed", sys.stderr), file=sys.stderr)
        return 1
    raw = reply.get("candidates") or []
    # the promise is line-level: a candidate is kept only when it equals
    # a line of the history after fold -- a substring ("rm -rf /" inside
    # "rm -rf /tmp/build") is not a command that ran
    # -- and what prints is the history's own line, as it ran (bash's `fc
    # -ln` indent off): a held one matches as the model saw it ([held])
    # and prints as the user typed it
    lines = {}
    for l, h in zip(orig, sent):
        if l.strip():
            lines.setdefault(textmod.fold(h), l.strip())
            lines.setdefault(textmod.fold(l), l.strip())
    seen, out = set(), []
    for c in raw:
        ran = lines.get(textmod.fold(str(c).strip()))
        if ran is None:
            continue                        # grounding: only a line that ran
        if ran in seen:
            continue
        seen.add(ran)
        out.append(ran)
        if len(out) >= 5:
            break
    s.record(kind="recall", chars=len(history), ms=ms, candidates=len(out), **({"held": held} if held else {}))
    if not out:
        print("! nothing in the history matches", file=sys.stderr)
        return 1
    for line in out:
        # a line that can destroy carries the warn mark, so the widget
        # can show ! before the user re-runs it
        print(("!\t" + line) if persona.is_dangerous(line.strip()) else line)
    return 0


def cmd_last(args):
    if _help(args, LAST_USAGE):
        return 0
    say(_fmt_turn(session.last_turn()))
    return 0


def _role_rows(cfg, url, is_forge):
    """[(role, stem, loaded)] when the brain serves both roles (spark
    first), [] for one model -- the callers then say nothing extra."""
    try:
        rows = wire.models(cfg, url, forge=is_forge)
    except wire.BrainError:
        return []
    if len(rows) < 2:
        return []
    order = {"spark": 0, "ember": 1}
    return sorted(rows, key=lambda r: (order.get(r[0], 2), r[0]))


def cmd_brain(args):
    """`spark brain --porcelain` is contract 5, exactly; bare `spark
    brain` is an older spelling of `spark status`, named nowhere."""
    if _help(args, STATUS_USAGE):
        return 0
    if "--porcelain" not in args:
        return cmd_status([a for a in args if a != "--fresh"])
    cfg = config.load()
    try:
        url, model, is_forge = wire.resolve_brain(cfg, fresh="--fresh" in args)
    except wire.BrainError:
        return 1
    say("%s\t%s\t%s" % (url, model, "forge" if is_forge else "model"))   # contract 5: the spark role's stem
    return 0


def live_widgets():
    """[(shell, pid)] of shells that sourced the widget and are still alive"""
    out = []
    try:
        for name in os.listdir(WIDGETS_DIR):
            try:
                with open(os.path.join(WIDGETS_DIR, name), encoding="utf-8") as f:
                    shell, pid, _ = (f.read().split() + ["", "", ""])[:3]
                os.kill(int(pid), 0)
                out.append((shell, int(pid)))
            except (OSError, ValueError):
                try:
                    os.remove(os.path.join(WIDGETS_DIR, name))
                except OSError:
                    pass
    except OSError:
        pass
    return out


def cmd_status(args, _bare=False):
    if _help(args, STATUS_USAGE):
        return 0
    # a clone with no site.env yet, at a terminal: the offer, not a status
    from . import SITE_ENV
    if not os.path.exists(SITE_ENV) and sys.stdout.isatty():
        from . import setup
        banner()
        say(setup.SIGN)
        return 0
    cfg = config.load()
    if _bare:
        # bare spark is one line; spark status is the full report
        try:
            url, model, is_forge = wire.resolve_brain(cfg)
            # only a machine that really serves an ember role says "ember";
            # a single model is just the model
            ember = next((s for role, s, _l in _role_rows(cfg, url, is_forge) if role == "ember"), None)
            say("%s %s at %s%s" % (glyph("hammer"), config.model_name(ember or model), url, bar.waiting(", ")))
        except wire.BrainError as e:
            say("%s %s" % (glyph("warn"), e.hint))
        return 0
    from . import is_wsl
    say("%s %s's spark on %s%s" % (glyph("hammer"), cfg.user, cfg.name, " (WSL 2)" if is_wsl() else ""))
    t0 = time.time()
    try:
        url, model, is_forge = wire.resolve_brain(cfg, fresh=True)
        rows = _role_rows(cfg, url, is_forge)
        ms = int((time.time() - t0) * 1000)
        if rows:
            for role, stem, _loaded in rows:
                say("  %-8s %s" % ({"spark": "line", "ember": "chat"}.get(role, role), config.model_name(stem)))
        else:
            say("  model    %s" % config.model_name(model))
        say("  server   %s%s, %d ms" % (url, " (the page too)" if is_forge else "", ms))
    except wire.BrainError as e:
        say("  model    " + e.hint)
    w = live_widgets()
    say("  prompt   %s" % ("off -- spark on turns it on" if os.path.exists(OFF_FLAG)
                           else "on in %s" % ", ".join(sorted({x[0] for x in w})) if w else "on, no shell loaded yet"))
    st = engine.service_state(cfg)
    say("  service  %s" % {"loaded": "always on", "disabled": "off -- spark serve on starts it",
                           "absent": "starts when needed"}[st])
    from . import memory, soul
    _, source = soul.read(cfg)
    if source == "file":
        say("  soul     yours, %d characters" % len(soul.text(cfg)))
    elif source == "env":
        say("  soul     from SPARK_PERSONA_EXTRA -- spark soul edit moves it")
    else:
        say("  soul     built in -- spark soul edit makes it yours")
    nf = len(memory.facts(cfg))
    say("  memory   %s" % ("%d fact%s" % (nf, "" if nf == 1 else "s") if cfg.memory else "off"))
    n = len(forge.list_threads(10**6))
    say("  history  %s" % ("off" if cfg.history <= 0 else "%d days, %d thread%s"
                           % (cfg.history, n, "" if n == 1 else "s")))
    say("  last     " + _fmt_turn(session.last_turn(), short=True).replace("\n", "\n           "))
    runs = bar.waiting()
    if runs:
        say("  runs     %s -- spark do --review" % runs)
    return 0


def _short(path):
    """`path` with the home directory as ~ -- its real path too (a
    sandboxed run's cwd is real)."""
    for home in (os.path.expanduser("~"), os.path.realpath(os.path.expanduser("~"))):
        if path.startswith(home + "/"):
            return "~" + path[len(home):]
    return path


def cmd_off(args):
    if _help(args, OFF_USAGE):
        return 0
    state_dir()
    was = os.path.exists(OFF_FLAG)
    open(OFF_FLAG, "a").close()
    if not was:
        say("%s the prompt line is off -- spark on turns it back on" % glyph("hammer"))
    from . import check
    check.refresh()
    return 0


def cmd_on(args):
    if _help(args, ON_USAGE):
        return 0
    try:
        os.remove(OFF_FLAG)
        say("%s the prompt line is on" % glyph("hammer"))
    except OSError:
        pass
    from . import check
    check.refresh()
    return 0


def cmd_history(args):
    if _help(args, HISTORY_USAGE):
        return 0
    if args[:1] == ["--fix-worked"]:
        # plumbing, the widgets' second Esc s: the fix that worked for
        # the pending failure lands in the ledger and the fails index
        return ledger.fail_fix(" ".join(args[1:]), config.load())
    if args[:1] == ["clear"]:
        return _clear_history()      # the older spelling of spark clear --history, kept working
    return paged(_history_show)


def cmd_clear(args):
    """spark clear --history: every turn day file and every regular thread
    go, the kept threads stay and are counted. One flag, nothing bare: a
    clear names what it removes."""
    if _help(args, CLEAR_USAGE):
        return 0
    if not args:
        say(CLEAR_USAGE.rstrip())
        return 2
    if args != ["--history"]:
        bad = next((a for a in args if a != "--history"), args[0])
        say("spark clear -- no word %s; spark clear -h lists them" % bad)
        return 2
    return _clear_history()


def _clear_history():
    n = session.clear()
    m = forge.clear()
    k = forge.kept_count()
    say("%s removed %d day%s of turns and %d thread%s%s" % (
        glyph("hammer"), n, "" if n == 1 else "s", m, "" if m == 1 else "s",
        "" if not k else "; %d kept thread%s stay%s" % (k, "" if k == 1 else "s", "s" if k == 1 else "")))
    return 0


def _history_show():
    cfg = config.load()
    say("%s history %s" % (glyph("hammer"), "off" if cfg.history <= 0 else "kept %d days" % cfg.history))
    held = forge.list_threads(10**6)       # the count status and spark user say
    threads = held[:5]
    if threads:
        say("  threads%s (?? words goes on with the newest):"
            % (", newest 5 of %d" % len(held) if len(held) > 5 else ""))
        for th in threads:
            say("  %s  %d turn%s  %s%s" % (th["id"], th["turns"], "" if th["turns"] == 1 else "s", th["title"],
                                         "  (kept)" if th.get("kept") else ""))
    k = forge.kept_count()
    if k:
        say("  %d kept thread%s" % (k, "" if k == 1 else "s"))
    fixes = [e for e in ledger.entries(kind=ledger.KIND_FAIL)
             if not ledger._retired(e, "path", None)]
    if fixes:
        say("  fixes remembered:")
        for e in reversed(fixes[-5:]):
            say("  %-10s exit %-3s x%-2d %s" % (e.get("head", "?"), e.get("rc", "?"),
                                                int(e.get("count", 1)), e["note"][:48]))
    return 0


_ORIGIN_RE = re.compile(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$")


def credits():
    """`by <org> <sep> github.com/<org>/<repo>`, derived from this clone's
    `origin` remote so a fork shows its own name; the literal fallback
    (2 s timeout, never blocks) when there is no remote to read."""
    from . import run
    rc, out = run(["git", "-C", REPO, "remote", "get-url", "origin"], timeout=2)
    m = _ORIGIN_RE.search(out.strip()) if rc == 0 else None
    org, repo = m.groups() if m else ("forgewright-ai", "spark")
    return "by %s%sgithub.com/%s/%s" % (org, glyph("sep"), org, repo)


LOGO_COLOURS = {"black": 0, "red": 1, "green": 2, "yellow": 3, "blue": 4, "magenta": 5, "cyan": 6, "white": 7}


def recolour(names, logo):
    """The banner's rows in the colours THEME_LOGO names -- one name per
    row, `bright-` allowed, the first row bold -- a row without a name
    keeps its own. The banner file holds the text \\033, not the byte."""
    lines = logo.split("\n")
    for i, name in enumerate(names[: len(lines)]):
        n = LOGO_COLOURS.get(name.replace("bright-", ""))
        if n is None:
            continue
        code = (90 if name.startswith("bright-") else 30) + n
        sgr = "\\033[%s%dm" % ("1;" if i == 0 else "", code)
        lines[i] = re.sub(r"^\\033\[[0-9;]*m", lambda m: sgr, lines[i], count=1)
    return "\n".join(lines)


def logo_names():
    """THEME_LOGO from theme.env (the palette in force), or None."""
    try:
        with open(os.path.join(CONFIG_DIR, "theme.env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("THEME_LOGO="):
                    return line[len("THEME_LOGO="):].strip().strip('"').split()
    except OSError:
        pass
    return None


def cmd_ver(args):
    """the logo and the version; --credits adds who made it"""
    if _help(args, VER_USAGE):
        return 0
    if args[:1] == ["--sbom"]:
        # the JSON and one newline, nothing else: no banner, no pager
        from . import sbom
        sys.stdout.write(sbom.dumps())
        sys.stdout.flush()
        return 0
    banner()
    if args[:1] == ["--credits"]:
        say(credits())
        say("engine llama.cpp %s (MIT) -- CREDITS.md names the rest" % engine.pinned_version())
    return 0


def banner():
    """The logo and `spark X.Y`: the login's lines, and the setup offer's."""
    for path in (os.path.join(CONFIG_DIR, "banner"), os.path.join(REPO, "home", ".config", "spark", "banner")):
        try:
            with open(path, encoding="utf-8") as f:
                logo = f.read()
            break
        except OSError:
            logo = ""
    say()
    if logo:
        names = logo_names()
        if names:
            logo = recolour(names, logo)
        logo = logo.replace("\\033", "\033") if sys.stdout.isatty() else re.sub(r"\\033\[[0-9;]*m", "", logo)
        say(logo.rstrip("\n"))
        say()
    # this line is the login greeting, so the version is the cached one
    # (lib/spark/version.py): no blocking git call on the common path.
    say("%s %s" % (MARK, version.version()))


# ---------------------------------------------------- soul and memory
# Imported when called: `spark line` (every Enter) must start light.
def cmd_soul(args):
    from . import soul
    return soul.cmd_soul(args)


def cmd_memory(args):
    from . import memory
    return memory.cmd_memory(args)


def cmd_chat(args):
    return forge.cmd_chat(args)


def cmd_lua(args):
    from . import lua
    return lua.cmd_lua(args)


def cmd_do(args):
    from . import do
    return do.cmd_do(args)


# --------------------------------------------------------------- dispatch
def main(argv):
    """The fallback behind bin/spark's VERBS table: bare spark is the
    status in one line, anything else is a question."""
    if not argv:
        return cmd_status([], _bare=True)
    return cmd_ask(argv)
