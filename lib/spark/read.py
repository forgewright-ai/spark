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
#   what leaves       the source's text and the question, to the model
#                     this machine answers from. No name, no path, no
#                     cwd: --name stays in the ledger on this machine.

import os
import sys

from . import MARK, config, die, ledger, log_exc, say, session, wire
from . import text as textmod

READ_MAX = 16000        # the source one part reads
PART_OVERLAP = 400      # a part carries this much of the one before it
MODE = "read-source"    # persona.MODES key
READ_TOKENS = 500
READ_TIMEOUT = 180
OPEN_MAX = 60           # chars of the source the refusal line shows

READ_USAGE = """spark read -- what a source says, and only what it says (contract 11)

  spark read <words>          the answer, every line quoting the source
  spark read                  the same, asked what the source covers
  --part N                    a source past 16000 chars is parts; read one,
                              and the answer's first line names it
  --name NAME                 the ledger's name for this source: the question
                              is recorded under it, never sent anywhere
  --ledger [clear] [--name NAME]  the questions asked, newest first;
                              clear drops them

  every line out quotes the source and the quote is checked: a line whose
  quotes are not in it, or that quotes nothing, never reaches you. When
  the source does not answer, the reply is one line showing its opening
  words -- composed here, never the model's guess -- and exit 1.
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

    def write(self, s):
        if self.header:
            self.stream.write(self.header + "\n")
            self.header = ""
        self.stream.write(s)

    def flush(self):
        self.stream.flush()


def _args(args):
    """(options, words) -- ValueError names a flag that lacks its value."""
    opts = {"name": "", "part": None, "ledger": None}
    words, rest = [], list(args)
    while rest:
        a = rest.pop(0)
        if a == "--ledger":
            opts["ledger"] = "clear" if rest[:1] == ["clear"] else "list"
            if opts["ledger"] == "clear":
                rest.pop(0)
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
    name = os.path.basename(opts["name"].strip())
    if opts["ledger"]:
        if opts["ledger"] == "clear":
            n = ledger.clear(name or None, ledger.KIND_READ)
            say("dropped %d question%s%s" % (n, "" if n == 1 else "s", (" for " + name) if name else ""))
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
    data = "" if sys.stdin.isatty() else sys.stdin.read()
    if not data:
        # at a terminal with nothing piped in, this is almost always a
        # question meant for the prompt: say where it goes, do not guess
        say(READ_USAGE.rstrip())
        say("\n  a question for spark itself is: spark %s" % (" ".join(words) or "<words>"))
        return 2
    total = parts_of(len(data))
    if total > 1 and want is None:
        die("the source is %d chars, %d parts of %d -- read one: --part N"
            % (len(data), total, READ_MAX))
    if want is not None and want > total:
        say("%s read -- the source is %d part%s; there is no part %d"
            % (MARK, total, "" if total == 1 else "s", want))
        return 2
    want = want or 1
    part = part_slice(data, want)
    cfg = config.load()
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    text = " ".join(words).strip() or "What does this source cover?"
    read, tail = session.reading(cfg, part, shell)
    context = read + "Source:\n" + part + tail

    def keep(_line, verdict, _misses):
        return verdict == textmod.GROUNDED  # it quotes, and a quote anchors

    header = "[part %d of %d]" % (want, total) if total > 1 else ""
    gate = textmod.Gate(_Part(sys.stdout, header), part, keep)
    fence = textmod.Fence(gate, newline=None)

    def done():
        fence.close()
        gate.close()
    try:
        s = session.Session(cfg, MODE, shell, "", role="ember")
        _out, ms = s.ask_stream(text, context, fence.feed, max_tokens=READ_TOKENS, timeout=READ_TIMEOUT)
    except wire.BrainError as e:
        done()
        die(e.hint)
    except KeyboardInterrupt:
        done()
        raise
    done()
    if gate.kept and name:
        # the record a second reader sees: what was asked, of which part
        note = ("part %d of %d: " % (want, total) if total > 1 else "") + text
        try:
            ledger.keep(ledger.KIND_READ, name, note, cfg)
        except (ledger.Refused, OSError):
            log_exc("read ledger")
    s.record(kind="read", chars=len(part), ms=ms, part=want, parts=total,
             kept=gate.kept, dropped=gate.dropped, quotes=gate.quoted, unanchored=gate.missed)
    if not gate.kept:
        where = "part %d of %d" % (want, total) if total > 1 else "the source"
        die('%s does not answer -- it opens: "%s"' % (where, opening(part)))
    return 0
