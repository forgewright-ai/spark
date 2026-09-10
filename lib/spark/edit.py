# spark.edit -- contract 10: the editor's protocol, the text on stdin.
#
# Three kinds by the words: --at N completes at that byte offset, words
# rewrite the text, `?` asks about it. Raw streamed text out -- no mark,
# no wrap, a code fence around the answer removed -- because the reply
# goes back into a buffer. No path is ever sent and no thread is kept
# unless the client names one: an editor, a pipe or a script is a client
# with nothing to install. The turn record is numbers only.

import os
import sys

from . import MARK, config, die, forge, ledger, persona, say, session, wire
from . import text as textmod

# what the editor sends at most
EDIT_BEFORE, EDIT_AFTER = 4000, 2000   # a completion: around the cursor
EDIT_MAX = 12000                        # a rewrite: the whole text, or nothing
EDIT_SEL_MAX = 12000                    # a selection inside a ?: whole up to this, else head + tail
EDIT_WINDOW = 16000                     # a ? with --sel: the selection and the file around it
EDIT_TIMEOUT = 180                      # a big selection takes a while to read

EDIT_USAGE = """spark edit -- the editor's protocol (contract 10): the text on stdin

  spark edit --at N           prints what goes at byte offset N (a completion)
  spark edit <words>          prints the text rewritten as the words ask
  spark edit ? [words]        answers about the text; ? alone reviews it
  --type FT                   the editor's filetype, a hint (markdown, python)
  --name NAME                 the file's name, a hint -- never its path
  --about TEXT                what the author says the text is, when it
                              should not guess ("a novel chapter")
  --part                      the text is a selection from a larger file:
                              a rewrite replaces exactly that part
  --sel A B                   ?: stdin is the whole file; the question is
                              about bytes A..B, the file around it context
  --thread ID                 ?: keep the exchange under ID (yours to name,
                              [A-Za-z0-9_-]); the same ID again continues it
  --decline --name NAME       keep the note on stdin as declined for NAME: a
                              later ? about NAME is told not to raise it
  --ledger [clear] --name NAME  the notes declined for NAME (every file's
                              without a name), newest first; clear drops them

  raw streamed text: no mark, no wrap, a code fence around the answer is
  removed; an empty text with words is written from nothing (a new file);
  exit 1 when ? or --at find no text, or no brain answers. In an editor:
  its plugin, github.com/forgewright-ai/spark-<app> (micro, neovim, vim,
  helix, nano), or its filter (:'<,'>!  |  ^T |) with the same words.
  From a pipe: spark edit fix grammar < draft.md
"""


def _edit_args(args):
    """(options, words) -- ValueError names a flag that lacks its value."""
    opts = {"type": "", "name": "", "about": "", "at": None, "part": False, "sel": None, "thread": "", "decline": False,
            "ledger": None}
    words, rest = [], list(args)
    while rest:
        a = rest.pop(0)
        if a == "--part":
            opts["part"] = True
        elif a == "--decline":
            opts["decline"] = True
        elif a == "--ledger":
            opts["ledger"] = "clear" if rest[:1] == ["clear"] else "list"
            if opts["ledger"] == "clear":
                rest.pop(0)
        elif a == "--sel":
            if len(rest) < 2:
                raise ValueError(a)
            opts["sel"] = (rest.pop(0), rest.pop(0))
        elif a in ("--type", "--name", "--about", "--at", "--thread"):
            if not rest:
                raise ValueError(a)
            opts[a[2:]] = rest.pop(0)
        else:
            words.append(a)
    return opts, words


def _edit_label(name, ftype, part=False):
    what = "File %s" % name if name else "Text"
    if part:
        what = "Selected part of %s" % name if name else "Selected text"
    return what + (" (%s):" % ftype if ftype else ":")


def _edit_window(data, a, b):
    """The context of a ? about a selection: the selection whole (head +
    cut mark + tail past EDIT_SEL_MAX) between two mark lines the brief
    knows, and as much of the file around it as EDIT_WINDOW leaves,
    split evenly, a side's unused room going to the other; a cut mark
    where the file goes on."""
    sel = data[a:b]
    if len(sel) > EDIT_SEL_MAX:
        sel = sel[:4000] + "\n[... %d chars cut ...]\n" % (len(sel) - EDIT_SEL_MAX) + sel[-(EDIT_SEL_MAX - 4000):]
    room = max(0, EDIT_WINDOW - len(sel))
    half = room // 2
    before_all, after_all = data[:a], data[b:]
    before = before_all[-(half + max(0, half - len(after_all))):] if room else ""
    after = after_all[:room - len(before)] if room else ""
    if len(before) < len(before_all):
        before = "[... %d chars cut ...]\n" % (len(before_all) - len(before)) + before
    if len(after) < len(after_all):
        after = after + "\n[... %d chars cut ...]" % (len(after_all) - len(after))
    return "%s\n[selection starts]\n%s\n[selection ends]\n%s" % (before, sel, after)


def cmd_edit(args):
    """The editor's protocol: the text on stdin, raw text out (no mark, no
    wrap -- the text goes back into a buffer). Three kinds by the words:
    --at N completes at that byte offset, words rewrite, `?` asks. No
    thread is kept and no path is sent: the turn record is numbers only."""
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(EDIT_USAGE.rstrip())
        return 0
    try:
        opts, words = _edit_args(args)
    except ValueError as e:
        say("%s edit -- %s needs a value" % (MARK, e))
        return 2
    at = opts["at"]
    if at is not None:
        try:
            at = max(0, int(at))
        except ValueError:
            say("%s edit -- --at N is a byte offset" % MARK)
            return 2
    if opts["ledger"]:
        # the pane's ledger: what was declined for this file, or drop it; no text needed
        name = opts["name"] or None
        if opts["ledger"] == "clear":
            n = ledger.clear(name)
            say("dropped %d note%s%s" % (n, "" if n == 1 else "s", (" for " + name) if name else ""))
        else:
            for line in ledger.listing(name):
                say(line)
        return 0
    if at is None and not words and not opts["decline"]:
        say(EDIT_USAGE.rstrip())
        return 2
    data = "" if sys.stdin.isatty() else sys.stdin.read()
    if not data:
        # an empty buffer (a new file in the editor): words write it from
        # nothing; ? and --at have nothing to read or continue, and say so
        # in one line an infobar can show
        if opts["decline"]:
            die("edit --decline reads the note on stdin")
        if at is not None:
            die("nothing to continue yet -- say what to write: spark> words")
        if words[0] == "?":
            die("nothing to ask about yet -- write something first")
    if opts["decline"]:
        # the pane's d key: the note on stdin retires for this file name
        try:
            ledger.decline(opts["name"], data, config.load())
        except ledger.Refused as e:
            say("%s edit --decline -- %s" % (MARK, e.hint))
            return 2
        except OSError as e:
            die("the ledger could not be written: %s" % e)
        return 0
    sel = None
    if opts["sel"] is not None:
        try:
            sel = (int(opts["sel"][0]), int(opts["sel"][1]))
        except ValueError:
            sel = (-1, -1)
        if not 0 <= sel[0] <= sel[1] <= len(data):
            say("%s edit -- --sel A B are byte offsets, 0 <= A <= B <= %d" % (MARK, len(data)))
            return 2
    tid = opts["thread"].strip()
    if tid and not forge.valid_id(tid):
        say("%s edit -- --thread ID is [A-Za-z0-9_-]" % MARK)
        return 2
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    ftype = opts["type"].strip() if opts["type"].strip() != "unknown" else ""
    label = _edit_label(os.path.basename(opts["name"].strip()), ftype, opts["part"])
    about = opts["about"].strip()
    head = "The author says: %s\n" % about if about else ""
    cfg = config.load()
    if at is not None:
        kind, role, max_tokens = "complete", "spark", 160
        text = "Continue at the cursor."
        before, after = data[max(0, at - EDIT_BEFORE):at], data[at:at + EDIT_AFTER]
        context = head + label + "\nBefore the cursor:\n" + before
        if after:
            context += "\n\nAfter the cursor:\n" + after
    elif words[0] == "?":
        kind, role, max_tokens = "answer", "ember", 600
        text = " ".join(words[1:]).strip() or persona.REVIEW
        # a thread: the same id again continues it -- the words alone when
        # the text is the one the first turn carried, else the text again
        tid = forge.open_thread(cfg, tid) if tid else None
        history = forge.history(tid) if tid else []
        sha = forge.text_sha(data)
        if history:
            context = "" if forge.same_text(tid, sha) else head + label.replace(":", ", as it is now:") + "\n" + forge.clip(data)
        elif sel:
            read, tail = session.reading(cfg, data, shell, start=max(0, sel[0] - 200))
            context = (head + read + ledger.block(cfg, opts["name"], data) + label[:-1]
                       + " -- the question is about the part between the marks:\n"
                       + _edit_window(data, sel[0], sel[1]) + tail)
        else:
            read, tail = session.reading(cfg, data, shell)
            context = head + read + ledger.block(cfg, opts["name"], data) + label + "\n" + forge.clip(data) + tail
    else:
        kind, role = "rewrite", "ember"
        if len(data) > EDIT_MAX:
            die("the text is %d chars; a rewrite takes at most %d -- select less" % (len(data), EDIT_MAX))
        max_tokens = min(6000, len(data) // 2 + 200) if data else 1500
        text = " ".join(words).strip()
        context = head + label + "\n" + (data or "(no text yet: write it, as the instruction asks)")
    # a rewrite keeps the text's own final-newline shape: the editor splices
    # the reply over the selection, and a model that drops or adds the last
    # newline would join or split lines
    # an answer's quotes are checked against the text, line by line, and
    # the ones the text does not hold are marked where they stand
    anchors = textmod.Anchors(sys.stdout, data) if kind == "answer" else None
    fence = textmod.Fence(anchors or sys.stdout, newline=(data.endswith("\n") if data else True) if kind == "rewrite" else None)

    def done():
        fence.close()
        if anchors:
            anchors.close()
    try:
        s = session.Session(cfg, "edit-" + kind, shell, "", role=role,
                            history=history if kind == "answer" else None)
        out, ms = s.ask_stream(text, context, fence.feed, max_tokens=max_tokens, timeout=EDIT_TIMEOUT)
    except wire.BrainError as e:
        done()
        die(e.hint)
    except KeyboardInterrupt:
        done()
        raise
    done()
    counts = {"quotes": anchors.quoted, "unanchored": anchors.missed} if anchors else {}
    if kind == "answer" and tid:
        forge.append(cfg, tid, "user", persona.user_message(text, "", context), text_sha=sha)
        forge.append(cfg, tid, "assistant", out or "")
        counts["thread"] = tid
    s.record(kind=kind, chars=len(data), ms=ms, **counts)
    return 0
