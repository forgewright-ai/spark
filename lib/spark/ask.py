# spark.ask -- contract 12: the questions this text does not answer.
#
# The text on stdin -- a plan, a draft, a decision -- and the reply is
# questions about it and nothing else. The law is mechanical, not a
# request in a brief: every line of the output ends in a question mark or
# it never reaches you. A model that can only ask cannot assert a false
# fact, and "is this a question" is something a machine can decide.
#
# Three more filters stand between the model and the reader, each one
# checkable without a second model:
#
#   grounded   a question whose every quoted span is missing from the
#              text is fluent invention: dropped (text.Gate, text.Ground)
#   its own    a question that could be asked of any plan is dropped --
#              a short list of phrases, forgiven only when the question
#              shares a word with the text (a timeline the text itself
#              raises is fair to ask about)
#   answered   a question you have already answered (spark ask --answered)
#              is not asked again (ledger, kind ask)
#
# Three at most, and none is a floor: when nothing survives, that is the
# answer -- one line on stderr and exit 1, so a client can tell "no
# question" from "a question" without reading prose. Nothing is written
# to stdout in that case, so the line stands alone.
#
# No path is ever sent, no [cwd] line, no thread unless the client names
# one: the same law as contract 10, and the same reason -- an editor, a
# pipe or a script is a client with nothing to install.

import os
import re
import sys

from . import MARK, config, die, forge, ledger, say, session, wire
from . import text as textmod

ASK_MAX = 12000         # the text a question round reads, or it refuses
ASK_CAP = 3             # questions kept, at most -- never a target
ASK_TOKENS = 400
ASK_TIMEOUT = 180

ASK_USAGE = """spark ask -- the questions a text does not answer (contract 12): on stdin

  spark ask                   at most three questions about the text
  spark ask <words>           the same, told what you are deciding
  --name NAME                 the text's name, a hint -- never its path
  --about TEXT                what you say the text is ("a migration plan")
  --thread ID                 keep the exchange under ID (yours to name,
                              [A-Za-z0-9_-]); the same ID again continues it
  --answered --name NAME      keep the question on stdin as answered for
                              NAME: it is not asked again
  --ledger [clear] --name NAME  the questions answered for NAME, newest
                              first; clear drops them

  every line out is a question: one that does not end in `?`, one whose
  every quote is not in the text, and one that could be asked of any
  plan never reach you. Nothing survives -> one line and exit 1: a
  reader with nothing to ask says nothing. At most 12000 chars in.
  From a pipe: spark ask < plan.md
"""

# A question that could be asked of any plan says nothing about this one.
# The list is short and named, so it can be argued with; a match is
# forgiven when the question shares a word of its own with the text --
# a timeline the text itself raises is a fair thing to ask about.
_GENERIC = tuple(re.compile(p) for p in (
    r"\btime ?line\b",
    r"\bhave you considered\b",
    r"\bwhat are the risks?\b",
    r"\bwhat could go wrong\b",
    r"\bwhat does success look like\b",
    r"\bhow will you measure success\b",
    r"\bwho are the stakeholders\b",
    r"\bwhat is the budget\b",
    r"\bwhat are the next steps?\b",
))
_STOP = frozenset((
    "this", "that", "these", "those", "what", "when", "which", "where", "your", "yours",
    "have", "will", "with", "from", "they", "them", "then", "than", "does", "done",
    "would", "could", "should", "about", "there", "their", "been", "being", "into",
    "plan", "make", "made", "much", "many", "more", "most", "same", "such", "here",
))
_WORD = re.compile(r"[a-z0-9]{4,}")
_LEAD = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*")


def bare(question):
    """A question without the enumeration a model puts in front of it:
    what two askings of the same question have in common."""
    return textmod.fold(_LEAD.sub("", question))


def generic(question, data):
    """True when this question could be asked of any plan: it matches one
    of the phrases above and shares no word of its own with the text. The
    text's own words are what tell a stock question from a real one."""
    f = bare(question)
    if not any(p.search(f) for p in _GENERIC):
        return False
    theirs = set(_WORD.findall(textmod.fold(data)))
    return not any(w in theirs for w in _WORD.findall(f) if w not in _STOP)


def _args(args):
    """(options, words) -- ValueError names a flag that lacks its value."""
    opts = {"name": "", "about": "", "thread": "", "answered": False, "ledger": None}
    words, rest = [], list(args)
    while rest:
        a = rest.pop(0)
        if a == "--answered":
            opts["answered"] = True
        elif a == "--ledger":
            opts["ledger"] = "clear" if rest[:1] == ["clear"] else "list"
            if opts["ledger"] == "clear":
                rest.pop(0)
        elif a in ("--name", "--about", "--thread"):
            if not rest:
                raise ValueError(a)
            opts[a[2:]] = rest.pop(0)
        else:
            words.append(a)
    return opts, words


def _label(name, about):
    head = "The author says: %s\n" % about if about else ""
    return head, ("Plan %s:" % name if name else "Text:")


class _Unwrap:
    """A model told to weave a quote into its question sometimes wraps the
    whole question in quotes instead -- every line then ends in a quote
    mark and the law would drop all of them. A line that IS one wrapped
    question (it opens with a quote and closes with a question mark inside
    one) is unwrapped before the gate reads it; its inner quotes are then
    exactly the spans the grounding law should judge. Anything else passes
    untouched."""

    def __init__(self, stream):
        self.stream, self.buf = stream, ""

    @staticmethod
    def _line(line):
        t = line.rstrip()
        if t.startswith('"') and t.endswith('?"'):
            return t[1:-1]
        return line

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.stream.write(self._line(line) + "\n")

    def flush(self):
        self.stream.flush()

    def close(self):
        if self.buf:
            self.stream.write(self._line(self.buf))
            self.buf = ""


def cmd_ask(args):
    """Contract 12: the text on stdin, questions out, one per line. The
    interrogative shape is the law -- a line that is not a question never
    reaches stdout -- so no assertion of the model's can pass as a fact
    about the text."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(ASK_USAGE.rstrip())
        return 0
    try:
        opts, words = _args(args)
    except ValueError as e:
        say("%s ask -- %s needs a value" % (MARK, e))
        return 2
    name = os.path.basename(opts["name"].strip())
    if opts["ledger"]:
        if opts["ledger"] == "clear":
            n = ledger.clear(name or None, ledger.KIND_ASK)
            say("dropped %d question%s%s" % (n, "" if n == 1 else "s", (" for " + name) if name else ""))
        else:
            for line in ledger.listing(name or None, ledger.KIND_ASK,
                                       "no question answered (spark ask --answered --name NAME)",
                                       noun="question"):
                say(line)
        return 0
    data = "" if sys.stdin.isatty() else sys.stdin.read()
    if not data:
        # at a terminal with nothing piped in, this is almost always a
        # question meant for the prompt: say where it goes, do not guess
        say(ASK_USAGE.rstrip())
        say("\n  a question for spark itself is: spark %s" % (" ".join(words) or "<words>"))
        return 2
    if opts["answered"]:
        try:
            ledger.keep(ledger.KIND_ASK, name, data, config.load(),
                        missing="an answered question needs --name NAME (the text's name)")
        except ledger.Refused as e:
            say("%s ask --answered -- %s" % (MARK, e.hint))
            return 2
        except OSError as e:
            die("the ledger could not be written: %s" % e)
        return 0
    if len(data) > ASK_MAX:
        die("the text is %d chars; ask takes at most %d -- select less" % (len(data), ASK_MAX))
    tid = opts["thread"].strip()
    if tid and not forge.valid_id(tid):
        say("%s ask -- --thread ID is [A-Za-z0-9_-]" % MARK)
        return 2
    cfg = config.load()
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    head, label = _label(name, opts["about"].strip())
    text = " ".join(words).strip() or "What does this not answer?"
    tid = forge.open_thread(cfg, tid) if tid else None
    history = forge.history(tid) if tid else []
    sha = forge.text_sha(data)
    answered_block, answered = ledger.answered(cfg, name)
    if history:
        # a continued round: the same text rides as the words alone
        context = "" if forge.same_text(tid, sha) else head + label.replace(":", ", as it is now:") + "\n" + forge.clip(data)
    else:
        read, tail = session.reading(cfg, data, shell, act="Ask")
        context = head + read + answered_block + label + "\n" + forge.clip(data) + tail

    kept = []

    def keep(line, verdict, _misses):
        q = line.rstrip()
        if not q.endswith("?"):
            return False                    # the law: it is a question or it is not output
        if verdict == textmod.UNGROUNDED:
            return False                    # every quote invented
        if len(kept) >= ASK_CAP:
            return False                    # three at most, never a target
        f = bare(q)
        if not f or f in kept or f in answered:
            return False
        if generic(q, data):
            return False
        kept.append(f)
        return True

    gate = textmod.Gate(sys.stdout, data, keep)
    unwrap = _Unwrap(gate)
    fence = textmod.Fence(unwrap, newline=None)

    def done():
        fence.close()
        unwrap.close()
        gate.close()
    try:
        s = session.Session(cfg, "ask-questions", shell, "", role="ember", history=history)
        out, ms = s.ask_stream(text, context, fence.feed, max_tokens=ASK_TOKENS, timeout=ASK_TIMEOUT)
    except wire.BrainError as e:
        done()
        die(e.hint)
    except KeyboardInterrupt:
        done()
        raise
    done()
    counts = {"asked": gate.kept, "dropped": gate.dropped, "quotes": gate.quoted, "unanchored": gate.missed}
    # a refused round is not a turn to follow up on: nothing goes on the
    # thread, so the next `--thread ID` continues the last real exchange
    if tid and gate.kept:
        forge.append(cfg, tid, "user", text, text_sha=sha)
        forge.append(cfg, tid, "assistant", out or "")
        counts["thread"] = tid
    s.record(kind="questions", chars=len(data), ms=ms, **counts)
    if not gate.kept:
        die("nothing to ask -- no question came back that this text does not answer")
    return 0
