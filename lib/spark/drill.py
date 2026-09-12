# spark.drill -- contract 13: questions the source itself answers.
#
# Contract 13. `spark drill` is the practice protocol: the source on
# stdin, one question at a time on stdout, your answer on the terminal;
# never a path. Mode from the argument shape, no mode flags.
#
#   what grounds it   both the question AND the correct answer come from
#                     the source. The model composes neither: it proposes
#                     a span of the source as the answer and a question
#                     whose answer is that span, and a question whose
#                     answer does not anchor in the source (text.anchor)
#                     is dropped before it is ever asked. A drill built
#                     on an invented answer teaches the invention.
#   when it fails     material too thin for questions is said in ONE
#                     line -- the source's own opening words, exit 1 --
#                     never padded from the model's own knowledge, which
#                     is the one thing a drill must not contain: the
#                     learner cannot tell the padding from the source.
#   caps              DRILL_MAX in, ITEMS_MAX items a session.
#   grading           self-graded against the sourced answer: you see the
#                     span the source holds and say whether you had it.
#                     Model-grading is a second model's opinion of a first
#                     model's question, and neither is the source.
#   ledger            kind `drill`, and it schedules rather than
#                     suppresses -- the inversion of every other kind. A
#                     missed item comes BACK, at INTERVALS[n] days, until
#                     it has been answered right RIGHT_TWICE times in a
#                     row (schedule() is the policy). So its records carry
#                     state the others do not (misses, streak, due) and,
#                     alone among the kinds, they never age out:
#                     ledger.RULES has drill age=False, because a schedule
#                     that expires is not a schedule. Only --name keeps a
#                     schedule; a bare session is practice, kept nowhere.
#   what leaves       the source's text, to the model this machine answers
#                     from. Your answers are graded here, against the
#                     source; they are never sent.

import os
import sys

from . import MARK, config, die, ledger, log_exc, persona, say, session, wire
from . import text as textmod
from .read import opening

DRILL_MAX = 16000       # the source one session reads
ITEMS_MAX = 10          # items proposed for one session
INTERVALS = (1, 3, 7, 21, 60)   # days: a missed item comes back, widening
RIGHT_TWICE = 2         # answered right this many times in a row: it rests
MODE = "drill-items"    # persona.MODES key
DRILL_TOKENS = 700
DRILL_TIMEOUT = 180

# a test seam: the answers come from here instead of /dev/tty, one per
# line (reveal, then yes/no, per item). Real use never sets it.
ANSWER_TTY = "SPARK_DRILL_TTY"

DRILL_USAGE = """spark drill -- practice against a source (contract 13)

  spark drill < FILE          the source becomes questions it answers; each
                              one you try, then see the source's own words
  --name NAME                 keep a schedule for this source: a missed item
                              comes back on a widening interval until it is
                              right twice; without --name, nothing is kept
  --ledger [clear] [--name NAME]  the schedule, soonest due first; clear drops it

  both the question and its answer are spans of the source -- an invented
  answer is dropped before it is ever asked. Too little to drill is one
  line and exit 1, never padded from the model's own knowledge.
  From a pipe: w3m -dump URL | spark drill --name page
"""


def schedule(misses, streak, right):
    """The policy, pure: (misses, streak, days-until-due) after one grade,
    where days is None when the item has rested. Right twice in a row rests
    it; a miss resets the streak and widens the interval (INTERVALS)."""
    if right:
        streak += 1
        return misses, streak, (None if streak >= RIGHT_TWICE else INTERVALS[0])
    misses += 1
    return misses, 0, INTERVALS[min(misses - 1, len(INTERVALS) - 1)]


def _args(args):
    """(options, words) -- ValueError names a flag that lacks its value."""
    opts = {"name": "", "ledger": None}
    words, rest = [], list(args)
    while rest:
        a = rest.pop(0)
        if a == "--ledger":
            opts["ledger"] = "clear" if rest[:1] == ["clear"] else "list"
            if opts["ledger"] == "clear":
                rest.pop(0)
        elif a == "--name":
            if not rest:
                raise ValueError(a)
            opts["name"] = rest.pop(0)
        else:
            words.append(a)
    return opts, words


def _ground(items, source):
    """The model's items, keeping only those whose answer is a verbatim
    span of the source (text.anchor); duplicates folded away, ITEMS_MAX
    at most. An invented answer teaches the invention, so it never asks."""
    out, seen = [], set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        q = " ".join(str(it.get("question", "")).split())
        a = " ".join(str(it.get("answer", "")).split())
        if not q or not a or not textmod.anchor(a, source):
            continue
        key = textmod.fold(q)
        if key in seen:
            continue
        seen.add(key)
        out.append({"question": q, "answer": a})
        if len(out) >= ITEMS_MAX:
            break
    return out


def _propose(s, source, cfg, shell):
    """The grounded items the model proposes for this source (may be [])."""
    read, tail = session.reading(cfg, source, shell)
    text = read + "Turn this source into practice questions.\nSource:\n" + source + tail
    reply, _ms = s.ask_json(text, persona.DRILL_SCHEMA, max_tokens=DRILL_TOKENS, timeout=DRILL_TIMEOUT)
    items = reply.get("items") if isinstance(reply, dict) else []
    return _ground(items, source)


def cmd_drill(args):
    """Contract 13: the source on stdin, one question at a time, your answer
    on the terminal -- both the question and the answer the source's own."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(DRILL_USAGE.rstrip())
        return 0
    try:
        opts, words = _args(args)
    except ValueError as e:
        say("%s drill -- %s needs a value" % (MARK, e))
        return 2
    name = os.path.basename(opts["name"].strip())
    if opts["ledger"]:
        if opts["ledger"] == "clear":
            n = ledger.clear(name or None, ledger.KIND_DRILL)
            say("dropped %d item%s%s" % (n, "" if n == 1 else "s", (" for " + name) if name else ""))
        else:
            for line in ledger.drill_listing(name or None):
                say(line)
        return 0
    source = "" if sys.stdin.isatty() else sys.stdin.read()
    if not source.strip():
        # a terminal with nothing piped: almost always a question for the
        # prompt -- say where it goes, do not guess
        say(DRILL_USAGE.rstrip())
        say("\n  a question for spark itself is: spark %s" % (" ".join(words) or "<words>"))
        return 2
    source = source[:DRILL_MAX]
    cfg = config.load()
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    s = session.Session(cfg, MODE, shell, "", role="ember")
    try:
        items = _propose(s, source, cfg, shell)
    except wire.BrainError as e:
        die(e.hint)
    # scheduled items already due for this source come back first
    if name:
        have = set(textmod.fold(i["question"]) for i in items)
        for rec in ledger.drill_due(name):
            if textmod.fold(rec.get("note", "")) in have:
                continue
            if textmod.anchor(rec.get("answer", ""), source):
                items.insert(0, {"question": rec["note"], "answer": rec["answer"]})
        items = items[:ITEMS_MAX]
    if not items:
        die('too little here to drill -- it opens: "%s"' % opening(source))
    # the source came on stdin, so the answers come from the terminal
    ans_path = os.environ.get(ANSWER_TTY) or "/dev/tty"
    try:
        tty = open(ans_path)
    except OSError:
        die("no terminal to answer at -- the source came on stdin, so drill needs /dev/tty")

    def prompt(msg):
        sys.stderr.write(msg)
        sys.stderr.flush()

    right = wrong = 0
    for i, it in enumerate(items, 1):
        prompt("\n%s drill %d/%d: %s\n  your answer (Enter to reveal): " % (MARK, i, len(items), it["question"]))
        tty.readline()
        prompt("  the source says: %s\n  had it? yes/NO: " % it["answer"])
        got = tty.readline().strip().lower() in ("y", "yes")
        right, wrong = right + got, wrong + (not got)
        if name:
            try:
                ledger.drill_grade(name, it["question"], it["answer"], got, cfg)
            except (ledger.Refused, OSError):
                log_exc("drill ledger")
    prompt("\n%s drill -- %d right, %d to revisit%s\n" % (MARK, right, wrong, ", scheduled" if name else ""))
    s.record(kind="drill", chars=len(source), ms=0, items=len(items), right=right, wrong=wrong)
    return 0
