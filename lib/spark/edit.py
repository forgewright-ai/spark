# spark.edit -- contract 10: the editor's protocol, the text on stdin.
#
# Three kinds by the words: --at N completes at that byte offset, words
# rewrite the text, `?` asks about it. Raw streamed text out -- no mark,
# no wrap, a code fence around the answer removed -- because the reply
# goes back into a buffer. No path is ever sent and no thread is kept
# unless the client names one: an editor, a pipe or a script is a client
# with nothing to install. The turn record is numbers only.

import difflib
import io
import os
import re
import sys
import time

from . import MARK, config, die, forge, ledger, persona, say, session, wire
from . import text as textmod

# what the editor sends at most
EDIT_BEFORE, EDIT_AFTER = 4000, 2000   # a completion: around the cursor
EDIT_MAX = 12000                        # a rewrite: the whole text, or nothing
EDIT_SEL_MAX = 12000                    # a selection inside a ?: whole up to this, else head + tail
EDIT_WINDOW = 16000                     # a ? with --sel: the selection and the file around it
EDIT_TIMEOUT = 180                      # a big selection takes a while to read
EDIT_WATCH_POLL = 3                     # --watch: seconds between looks at the file
EDIT_WATCH_IDLE = 90                    # --watch: a pause this long earns a whole-draft review

EDIT_USAGE = """spark edit -- write and review text with spark (text on stdin)

  spark edit <words>          rewrite the text as the words ask
  spark edit ? [words]        ask about the text; ? alone reviews it
  spark edit --at N           what comes next at byte N (a completion)
  spark edit --watch FILE     comments on a draft as you save it
  --type FT                   the kind of file (markdown, python)
  --name NAME                 the file's name (never its path)
  --about TEXT                what the text is ("a novel chapter")
  --part                      the text is part of a larger file
  --sel A B                   ?: ask about bytes A to B of the whole file
  --thread ID                 ?: keep the exchange; the same ID continues it
  --source                    ?: the text is someone else's: discuss it,
                              never edit it (secrets in it are held back)
  --decline --name NAME       never raise the note on stdin again
  --ledger [clear] --name NAME  the declined notes; clear forgets them
  --                          the rest are words, not options

  Prints plain text. Exit 1 when there is no text or no model answers.
  Editors: github.com/forgewright-ai/spark-<app> (micro, neovim, vim,
  helix, nano). From a pipe: spark edit fix grammar < draft.md
"""


def _edit_args(args):
    """(options, words) -- ValueError names a flag that lacks its value."""
    opts = {"type": "", "name": "", "about": "", "at": None, "part": False, "sel": None, "thread": "", "decline": False,
            "ledger": None, "watch": "", "source": False}
    words, rest = [], list(args)
    while rest:
        a = rest.pop(0)
        if a == "--":
            # the end of the options: every word after it is a word, so a
            # question that says "--name" cannot eat the flag after it
            words.extend(rest)
            break
        if a == "--part":
            opts["part"] = True
        elif a == "--source":
            opts["source"] = True
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
        elif a in ("--type", "--name", "--about", "--at", "--thread", "--watch"):
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


def _review_context(cfg, shell, data, name, head, label, answer="source"):
    """The context a plain `?`/review carries: the reading restated, any
    notes declined for this name, the label and the text. Shared by the
    one-shot `?` and the --watch loop so they ground a comment the same way.
    `answer` names the reply language the reading pass asks for (see
    session.reading): "source" for an author's draft, "question" for a
    reader discussing a published source (`--source`)."""
    read, tail = session.reading(cfg, data, shell, answer=answer)
    return head + read + ledger.block(cfg, name, data) + label + "\n" + forge.clip(data) + tail


def stanzas(text):
    """The text's units, split on blank lines: what --watch comments on one
    at a time, so a comment lands on the paragraph just written, not the
    whole draft each save."""
    return [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]


def _printable_feed(feed, data):
    """The model's chunks through text.Printable before `feed`: an escape
    or a control character never reaches the terminal or the editor's
    buffer, a rewrite and a completion included. A carriage return stays
    when the text on stdin has one (a file with CRLF line ends)."""
    p = textmod.Printable(keep="\t\n\r" if "\r" in (data or "") else "\t\n")
    return lambda chunk: feed(p.feed(chunk))


def _crlf(data):
    """Does every line of the text end CRLF (a file written on Windows)?"""
    ends = data.count("\n")
    return bool(ends) and data.count("\r\n") == ends


def _as_crlf(text):
    """`text` with every line ending CRLF, never a CR doubled."""
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


class _CRLF:
    """A rewrite streamed to `stream` (a --part selection) with every
    line ending CRLF, the way the text's own lines end: the model writes
    LF. A CR that ends one chunk waits for the next, so a CRLF split
    across two chunks is never doubled."""

    def __init__(self, stream):
        self.stream, self.cr = stream, ""

    def write(self, s):
        s, self.cr = self.cr + s, ""
        if s.endswith("\r"):
            s, self.cr = s[:-1], "\r"
        self.stream.write(_as_crlf(s))

    def flush(self):
        self.stream.flush()

    def close(self):
        if self.cr:
            self.stream.write(self.cr)
            self.cr = ""
        self.stream.flush()


_WORD = re.compile(r"\w{3,}")
_HEADING = re.compile(r"(#{1,6}) ")
PLACE_LIKE = 0.6        # a reply's unit is like one of the text's at this similarity of its characters,
PLACE_WORDS = 0.5       # or this share of its words in that unit...
PLACE_CLEAR = 0.2       # ...and only when that beats the next best by this much


def _units(text, lines=False):
    """The text's units, as (start, end) offsets: each run of non-blank
    lines (a paragraph), or each non-blank line, from the start of its
    first line to the end of its last (the line break not included)."""
    out, start, end, pos = [], None, 0, 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            if start is None:
                start = pos
            end = pos + len(line.rstrip("\r\n"))
            if lines:
                out.append((start, end))
                start = None
        elif start is not None:
            out.append((start, end))
            start = None
        pos += len(line)
    if start is not None:
        out.append((start, end))
    return out


def _clear(scores):
    """The index whose score is clearly the best, at least PLACE_CLEAR
    above the second, or None."""
    order = sorted(range(len(scores)), key=lambda k: -scores[k])
    if not order or scores[order[0]] <= 0:
        return None
    second = scores[order[1]] if len(order) > 1 else 0.0
    return order[0] if scores[order[0]] - second >= PLACE_CLEAR else None


def _anchor(unit, texts, firsts, words):
    """The index of the text's unit this reply unit rewrites, or None when
    that is not sure: its first line equal to exactly one unit's first
    line, else a unit clearly the most like it, by its characters or by
    the share of its words, with the other measure not clearly pointing
    elsewhere. A tie never places it."""
    first = unit.split("\n", 1)[0].strip()
    if _WORD.search(first) and firsts.count(first) == 1:
        return firsts.index(first)
    flat = " ".join(unit.split())
    chars = [difflib.SequenceMatcher(None, flat, " ".join(t.split()), autojunk=False).ratio() for t in texts]
    mine = set(_WORD.findall(unit.lower()))
    share = [len(mine & w) / len(mine) if len(mine & w) >= 3 else 0.0 for w in words]
    by_chars, by_words = _clear(chars), _clear(share)
    if by_chars is not None and by_words not in (None, by_chars):
        return None
    if by_chars is not None and chars[by_chars] >= PLACE_LIKE:
        return by_chars
    if by_words is not None and share[by_words] >= PLACE_WORDS:
        return by_words
    return None


def _header(first):
    """A unit's first line that opens a section: ("md", level) for a
    markdown heading, ("code", indentation) for a line ending in ':' or
    '{'; None for anything else."""
    m = _HEADING.match(first)
    if m:
        return "md", len(m.group(1))
    if first.rstrip().endswith((":", "{")):
        return "code", len(first) - len(first.lstrip())
    return None


def _opens(first, head):
    """Does this first line end the section `head` opened: a heading at
    its level or above, or code no deeper than its header?"""
    if head[0] == "md":
        m = _HEADING.match(first)
        return bool(m) and len(m.group(1)) <= head[1]
    return len(first) - len(first.lstrip()) <= head[1]


def _section(texts, i):
    """The end of the section unit i opens (_header): the next unit that
    opens one at its level or above. A closing bracket at the header's
    own indentation belongs to the section."""
    head = _header(texts[i].split("\n", 1)[0])
    for k in range(i + 1, len(texts)):
        first = texts[k].split("\n", 1)[0]
        if _opens(first, head):
            closing = head[0] == "code" and first.lstrip()[:1] in "}])" and len(first) - len(first.lstrip()) == head[1]
            return k + 1 if closing else k
    return len(texts)


def _same(unit):
    """A unit as compared for being the text's own, unchanged: its lines,
    trailing space aside."""
    return tuple(line.rstrip() for line in unit.splitlines())


def _part_again(data, first, again):
    """The re-ask's verdict on a reply that was part of the text,
    unchanged ("part"): the same part again is the deletion it is; a reply
    that is not part of the text goes through the placement; another part
    is not sure."""
    whole, how = _place(data, again)
    if how != "part":
        return whole, how
    if [_same(again[a:b]) for a, b in _units(again)] == [_same(first[a:b]) for a, b in _units(first)]:
        return again, "whole"
    return None, "unplaced"


def _draws_inner(mine, at, rare):
    """Does a reply that opens and ends with the text's own opening and
    closing draw on what lies between them: more than half of the text's
    inner units, and two at least, found by a unit of the reply's middle
    or by their own words in it? Fewer is the fragment shape: the opening,
    the part asked about and the closing, with the rest gone (a mail's
    one paragraph, a file's one function), never a shorter whole."""
    inner = range(1, len(rare) - 1)
    said = set(_WORD.findall(" ".join(mine[1:-1]).lower()))
    found = {k for k in at[1:-1] if k in inner} | {k for k in inner if rare[k] & said}
    return len(found) >= 2 and len(found) * 2 > len(inner)


def _place(data, reply):
    """A rewrite of the whole text, made sure to be whole: (text, how).

    A small model asked to change one part of a text often answers with
    that part alone, and an editor splices the reply over the whole file,
    so the rest would be deleted. A placement is sure or does nothing. The
    units are paragraphs, or lines when the text has no blank line. A
    reply that is fewer of the text's own units, unchanged, is a deletion
    or a part left untouched: ("part"), for the caller to ask once more
    (_part_again). The reply is the whole ("whole") when it is all of the
    text's units unchanged, when it has about as many units as the text,
    when it spans the text's first unit to its last, when it opens and
    ends with them and draws on what lies between (a shorter whole,
    _draws_inner), when it holds a unit from outside its own run (a
    merge: not a local edit), or when it is placed nowhere and draws on
    most of the text (a new text).
    A run of the text's units, each found for sure (_anchor), goes back in
    their place ("spliced") when nothing of the text is missing inside it
    and nothing new sits at an edge the text goes on past. A reply that
    opens with a header the text holds once (a heading, a `def ...:`) and
    stays inside that header's section replaces the section. Anything else
    is not sure: (None, "unplaced"), and nothing is printed."""
    src = _units(data)
    lines = len(src) < 2
    if lines:
        src = _units(data, lines=True)
    rep = _units(reply, lines=lines)
    if len(src) < 2 or not rep:
        return reply, "whole"
    texts = [data[a:b] for a, b in src]
    mine = [reply[a:b] for a, b in rep]
    own = {_same(t) for t in texts}
    if all(_same(t) in own for t in mine):
        # the text's own units, unchanged: all of them is the text as it
        # was; fewer is a deletion or a part left untouched, which the
        # reply alone cannot tell apart (the caller asks once more)
        return reply, ("part" if len(mine) < len(src) else "whole")
    if len(rep) * 4 >= len(src) * 3:
        return reply, "whole"
    words = [set(_WORD.findall(t.lower())) for t in texts]
    seen = {}
    for w in words:
        for x in w:
            seen[x] = seen.get(x, 0) + 1
    rare = [{x for x in w if seen[x] == 1} for w in words]     # a unit's words no other unit has
    said = set(_WORD.findall(reply.lower()))
    firsts = [t.split("\n", 1)[0].strip() for t in texts]
    at = [_anchor(t, texts, firsts, words) for t in mine]
    placed = [k for k in at if k is not None]
    if not placed:
        short = len(reply.strip()) * 2 < len(data.strip())
        if short and sum(1 for r in rare if r & said) * 2 < len(src):
            return None, "unplaced"
        return reply, "whole"
    if placed != sorted(placed):
        return None, "unplaced"
    i, j = placed[0], placed[-1] + 1
    sure, last, between = True, None, 0
    for k in at:                      # every unit of the run is in the reply, or rewritten between
        if k is None:
            between += 1
            continue
        if last is not None and k > last + 1 and not between:
            sure = False
        last, between = k, 0
    if sure and i == 0 and j == len(src):
        return reply, "whole"
    if at[0] == 0 and at[-1] == len(src) - 1 and _draws_inner(mine, at, rare):
        # it opens with the text's opening and ends with its closing: the
        # whole text, however much shorter (a mail cut to half its length)
        return reply, "whole"
    if (at[0] is None and i > 0) or (at[-1] is None and j < len(src)):
        sure = False
    if not sure:
        # a reply that opens with a header the text holds once, and stays
        # inside its section, is that section rewritten
        head = _header(texts[i].split("\n", 1)[0])
        if at[0] != i or not head or mine[0].split("\n", 1)[0].strip() != firsts[i]:
            return None, "unplaced"
        j = _section(texts, i)
        if placed[-1] >= j or any(_opens(t.split("\n", 1)[0], head) for t in mine[1:]):
            return None, "unplaced"
    outside = [k for k in range(len(src)) if k < i or k >= j]
    flat = " ".join(reply.split())
    taken = set().union(*(rare[k] for k in outside)) & said
    if (len(taken) >= 3 and len(taken) * 10 >= len(said) * 3) or any(
            len(words[k]) >= 3 and " ".join(texts[k].split()) in flat for k in outside):
        return reply, "whole"
    body = reply[rep[0][0]:rep[-1][1]]
    if "\r\n" in data:
        body = body.replace("\r\n", "\n").replace("\n", "\r\n")
    return data[:src[i][0]] + body + data[src[j - 1][1]:], "spliced"


def _ask_again(s, text, context, reply, data, max_tokens):
    """The one re-ask of a rewrite that came back as part of the text,
    unchanged: the first exchange rides as history and the model hears
    persona.EDIT_PART_AGAIN. (reply, ms), the reply held like the first."""
    s.history = [{"role": "user", "content": persona.user_message(text, "", context)},
                 {"role": "assistant", "content": reply}]
    held_out = io.StringIO()
    fence = textmod.Fence(held_out, newline=data.endswith("\n"))
    busy = textmod.wait("read")
    try:
        busy.start()
        _out, ms = s.ask_stream(persona.EDIT_PART_AGAIN, "", _printable_feed(fence.feed, data),
                                max_tokens=max_tokens, timeout=EDIT_TIMEOUT)
    except wire.BrainError as e:
        die(e.hint)
    finally:
        busy.stop()
    fence.close()
    return held_out.getvalue(), ms


def _comment(cfg, shell, whole, piece, name, words):
    """One grounded comment: on `piece` (a fresh stanza) if given, else a
    review of `whole` (the idle pass). The comment's quotes are checked
    against the text it is about (textmod.Anchors), and a transient brain
    gap is skipped in silence -- the watch goes on."""
    data = piece if piece is not None else whole
    question = " ".join(words).strip() or persona.REVIEW
    label = _edit_label(name, "", part=piece is not None)
    context = _review_context(cfg, shell, data, name, "", label)
    anchors = textmod.Anchors(sys.stdout, data)
    fence = textmod.Fence(anchors, newline=None)
    feed = _printable_feed(fence.feed, data)

    def run(s):
        return s.ask_stream(question, context, feed, max_tokens=600, timeout=EDIT_TIMEOUT)

    ok, _res = session.once(lambda: session.Session(cfg, "edit-answer", shell, "", role="ember"), run)
    fence.close()
    anchors.close()
    if ok and anchors.spoke:
        sys.stdout.write("\n")
        sys.stdout.flush()


def _watch_draft(cfg, shell, path, words, name):
    """--watch: comment on each stanza as it is saved, review the whole
    draft after a pause. Mirrors the proven companion loop -- poll the file
    by mtime (an atomic save swaps the inode; re-opening by path catches
    it, and a read that fails mid-swap just waits for the next tick), and a
    draft that already holds work owes it a review rather than baselining
    it into `seen` unseen. Ctrl-C ends it."""
    if not os.path.isfile(path):
        die("no such file: %s" % path)
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        die("cannot read %s: %s" % (path, e))
    seen = set(stanzas(text))
    last_mtime = os.path.getmtime(path)
    started = bool(text.strip())
    last_change = time.time() if started else None   # a non-empty draft owes a review
    reviewed = not started
    say("%s edit --watch %s -- comments as you save; Ctrl-C ends" % (MARK, os.path.basename(path)))
    poll = float(os.environ.get("SPARK_EDIT_WATCH_POLL") or EDIT_WATCH_POLL)   # a test seam
    try:
        while True:
            time.sleep(poll)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime != last_mtime:
                last_mtime = mtime
                try:
                    text = open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue                     # save race: next tick wins
                fresh = [s for s in stanzas(text) if s not in seen]
                if not fresh:
                    continue
                seen.update(fresh)
                last_change, reviewed = time.time(), False
                _comment(cfg, shell, text, fresh[-1], name, words)
            elif last_change is not None and not reviewed and time.time() - last_change >= EDIT_WATCH_IDLE:
                reviewed = True
                _comment(cfg, shell, text, None, name, words)
    except wire.BrainError as e:
        # a transient gap was already ridden out (session.once); this is a
        # rotated token or a broken server -- one line, not a traceback
        print("%s edit --watch -- %s" % (MARK, e.hint), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def cmd_edit(args):
    """The editor's protocol: the text on stdin, raw text out (no mark, no
    wrap -- the text goes back into a buffer). Three kinds by the words:
    --at N completes at that byte offset, words rewrite, `?` asks. No
    thread is kept and no path is sent: the turn record is numbers only."""
    if args and args[0] in ("-h", "--help", "help"):
        say(EDIT_USAGE.rstrip())
        return 0
    try:
        opts, words = _edit_args(args)
    except ValueError as e:
        say("%s edit -- %s needs a value" % (MARK, e))
        return 2
    if opts["watch"]:
        # a live draft, not a one-shot: the file is the input, the writer's
        # editor saves it, and the comments go to stdout. No stdin is read.
        shell = os.path.basename(os.environ.get("SHELL") or "sh")
        return _watch_draft(config.load(), shell, opts["watch"], words, os.path.basename(textmod.utf8(opts["name"]).strip()))
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
            try:
                n = ledger.clear(name)
            except ledger.Refused as e:
                say("%s edit --ledger -- %s" % (MARK, e.hint))
                return 2
            if n:
                say("* dropped %d note%s%s" % (n, "" if n == 1 else "s", (" for " + name) if name else ""))
        else:
            for line in ledger.listing(name):
                say(line)
        return 0
    if at is None and not words and not opts["decline"]:
        say(EDIT_USAGE.rstrip())
        return 2
    data = "" if sys.stdin.isatty() else textmod.stdin_text()
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
    # a source (`? --source`: a page, a mail) is someone else's text: what
    # looks like a secret in it is held back here, before the reading, the
    # context, the anchors and the thread's text_sha see it -- they all see
    # what the model sees. A rewrite, --at and a plain ? are the author's
    # own text, untouched (a rewrite replaces its input)
    # the hints ride in the same message (a mail's subject as --name), so
    # they are held the same way; the ledger keeps the name as given
    held, names = 0, []
    sent = {k: opts[k] for k in ("name", "about", "type")}
    if opts["source"] and at is None and words[0] == "?":
        spans, names = textmod.held_spans(data)
        if spans:
            if sel:
                sel = (textmod.held_offset(spans, sel[0]), textmod.held_offset(spans, sel[1], end=True))
            data, held = textmod.hold_spans(data, spans), len(spans)
        for k in sent:
            hs, hn = textmod.held_spans(sent[k])
            if hs:
                sent[k], held, names = textmod.hold_spans(sent[k], hs), held + len(hs), names + hn
        names = textmod.shape_order(names)
    tid = opts["thread"].strip()
    if tid and not forge.valid_id(tid):
        say("%s edit -- --thread ID is 1 to 64 of [A-Za-z0-9_-]" % MARK)
        return 2
    if held:        # said once nothing can refuse any more: the text is on its way
        print(textmod.held_line(held, names), file=sys.stderr, flush=True)
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    ftype = sent["type"].strip() if sent["type"].strip() != "unknown" else ""
    label = _edit_label(os.path.basename(textmod.utf8(sent["name"]).strip()), ftype, opts["part"])
    about = sent["about"].strip()
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
        # a reader (--source) is answered in the language they ask in,
        # not the source's; an author reviewing a draft in the draft's
        ans = "question" if opts["source"] else "source"
        # a thread: the same id again continues it -- the words alone when
        # the text is the one the first turn carried, else the text again
        tid = forge.open_thread(cfg, tid) if tid else None
        history = forge.history(tid) if tid else []
        sha = forge.text_sha(data)
        if history:
            context = "" if forge.same_text(tid, sha) else head + label.replace(":", ", as it is now:") + "\n" + forge.clip(data)
        elif sel:
            read, tail = session.reading(cfg, data, shell, start=max(0, sel[0] - 200), answer=ans)
            context = (head + read + ledger.block(cfg, opts["name"], data) + label[:-1]
                       + " -- the question is about the part between the marks:\n"
                       + _edit_window(data, sel[0], sel[1]) + tail)
        else:
            context = _review_context(cfg, shell, data, opts["name"], head, label, answer=ans)
    else:
        kind, role = "rewrite", "ember"
        if len(data) > EDIT_MAX:
            die("the text is %d characters; a rewrite takes at most %d -- select less" % (len(data), EDIT_MAX))
        max_tokens = min(6000, len(data) // 2 + 200) if data else 1500
        text = " ".join(words).strip()
        context = head + label + "\n" + (data or "(no text yet: write it, as the instruction asks)")
    # a rewrite keeps the text's own final-newline shape: the editor splices
    # the reply over the selection, and a model that drops or adds the last
    # newline would join or split lines
    # an answer's quotes are checked against the text, line by line, and
    # the ones the text does not hold are marked where they stand
    # A reader's source (--source) proposes nothing, so a span after an
    # arrow there is a quote like any other, checked
    anchors = textmod.Anchors(sys.stdout, data, proposals=not opts["source"]) if kind == "answer" else None
    # a rewrite of the whole text is held until it ends: it is printed only
    # once it is known to be whole (_place). A selection (--part) and a text
    # written from nothing stream, since their reply is all there is
    held_out = io.StringIO() if kind == "rewrite" and data and not opts["part"] else None
    # a rewrite of a text whose every line ends CRLF ends its lines so too
    crlf = kind == "rewrite" and _crlf(data)
    streamed = _CRLF(sys.stdout) if crlf and held_out is None else None
    fence = textmod.Fence(anchors or held_out or streamed or sys.stdout,
                          newline=(data.endswith("\n") if data else True) if kind == "rewrite" else None)

    def done():
        fence.close()
        if anchors:
            anchors.close()
        if streamed:
            streamed.close()
    # --source picks the reading-discussion posture (a published source
    # the reader discusses, not their draft) over the editor's review
    # brief, keeping the kind -- the turn record and the Anchors gate --
    # unchanged. The reading surfaces pass it; the editors never do.
    mode = "edit-discuss" if (kind == "answer" and opts["source"]) else "edit-" + kind
    # the wait at a terminal: a pulse until the first chunk, only where a
    # person watches (text.wait: stdout and stderr both terminals, the
    # look on). An editor pipes stdout, so its plugin never sees a frame
    busy = textmod.wait("read")
    feed = _printable_feed(fence.feed, data)

    def first(chunk):
        if held_out is None:     # a held rewrite shows nothing until it ends: the pulse goes on
            busy.stop()
        feed(chunk)
    try:
        s = session.Session(cfg, mode, shell, "", role=role,
                            history=history if kind == "answer" else None)
        busy.start()
        out, ms = s.ask_stream(text, context, first, max_tokens=max_tokens, timeout=EDIT_TIMEOUT)
    except wire.BrainError as e:
        busy.stop()
        done()
        die(e.hint)
    except KeyboardInterrupt:
        busy.stop()
        done()
        raise
    finally:
        busy.stop()
    done()
    counts = {"quotes": anchors.quoted, "unanchored": anchors.missed} if anchors else {}
    if held:
        counts["held"] = held
    if held_out is not None:
        reply = held_out.getvalue()
        whole, how = _place(data, reply)
        if how == "part":
            # part of the text, unchanged: a deletion or a part left as it
            # was. The model hears so and is asked once more
            again = _ask_again(s, text, context, reply, data, max_tokens)
            whole, how = _part_again(data, reply, again[0])
            ms += again[1]
            counts["again"] = 1
        if whole is None:
            s.record(kind=kind, chars=len(data), ms=ms, unplaced=1, **counts)
            die("the reply is not the whole text, and its place in it is not sure; nothing changed -- select the part and ask again")
        sys.stdout.write(_as_crlf(whole) if crlf else whole)
        sys.stdout.flush()
        if how == "spliced":
            counts["spliced"] = 1
    if kind == "answer" and tid:
        forge.append(cfg, tid, "user", persona.user_message(text, "", context), text_sha=sha)
        forge.append(cfg, tid, "assistant", out or "")
        counts["thread"] = tid
    s.record(kind=kind, chars=len(data), ms=ms, **counts)
    return 0
