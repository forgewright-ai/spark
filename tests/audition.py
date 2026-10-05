#!/usr/bin/env python3
# audition.py -- the editor's briefs, judged blind. Eight fixtures (a poem,
# a chapter, a README, a commit message, Portuguese prose, Go, Python,
# shell) go through the real `spark edit` -- complete, rewrite, ? -- against
# whatever brain this machine answers from (a client asks its peer), and
# mechanical lints score every answer: no fence, no preamble, code still
# compiles, the language holds, at most five notes, every quote anchors,
# no "X" -> "X", no praise opener. A rewrite is held to what its own
# instruction asks: "shorter" is shorter, "tighten the last stanza"
# leaves the other stanzas as they were, and a paragraph wrapped again is
# the same paragraph. Nothing prints an answer unless -v: the lints are
# the judge, never the reader's taste.
#
#   python3 tests/audition.py [--times N] [--kind complete|rewrite|ask]
#                             [--fixture NAME] [--json] [-v]
#   python3 tests/audition.py --ground [--times N] [--json] [-v]
#   python3 tests/audition.py --selftest
#
# --ground runs the grounded contracts' 10 cases and nothing else; a run
# without it runs the editor's fixtures alone. --selftest needs no model:
# it proves the rewrite lints and the counting on canned rewrites.
#
# Not part of the gate (it needs a live brain; it skips, exit 0, when none
# answers). A change to any edit-* brief carries this table's before and
# after totals in the PR (AGENTS.md). --json appends one record -- the
# model, the briefs' sha256s, the totals -- to STATE_DIR/audition.jsonl,
# so two briefs are compared by number.

import glob
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SPARK = os.path.join(REPO, "bin", "spark")
FIX = os.path.join(HERE, "audition")
sys.path.insert(0, os.path.join(REPO, "lib"))
from spark import STATE_DIR, persona, text as textmod  # noqa: E402

# name: filetype, language, the cursor (after this substring), the rewrite
# instruction, the question (+ the selected span for two of them), the
# first character a completion must begin with (None: not judged).
# What the rewrite instruction asks of the result's size, said beside it
# so the lint grades the instruction and not one rule for all:
#   fit    "shorter" (the instruction says shorter: fewer characters),
#          "no longer" (it tightens or cuts: never more), or absent
#   part   the first words of the one stanza or paragraph the instruction
#          names; the rest of the text must come back unchanged
#   lines  True where a line break is part of the text (a poem)
FIXTURES = {
    "poem.txt": dict(ft="text", lang="en", at="eleven, then the loose twelfth board,\n",
                     rewrite="tighten the last stanza", fit="no longer", part="Outside the street", lines=True,
                     ask="?", first=None),
    "chapter.md": dict(ft="markdown", lang="en", at="each\ntime it said the same thing in the same careful hand: ",
                       rewrite="cut the adverbs", fit="no longer", ask="? is the ending earned",
                       sel=("The island rose", "look like patience."), first=None),
    "README.md": dict(ft="markdown", lang="en", at="Exit codes: 0 when every file was read, 1 when one could not be, ",
                      rewrite="make the install section clearer", ask="?", first=None),
    "commit.txt": dict(ft="gitcommit", lang="en", at="The reader keeps the raw length before decoding, ",
                       rewrite="shorter", fit="shorter", ask="? is the subject line right", first=None),
    "prosa.md": dict(ft="markdown", lang="pt", at="Trazia o café num garrafão e as notícias da noite: ",
                     rewrite="deixe o segundo parágrafo mais curto", fit="shorter", part="O neto vinha", ask="?",
                     sel=("O neto vinha", "que era o bastante."), first=None),
    "main.go": dict(ft="go", lang="code", at="\tif len(os.Args) < 2 {\n", rewrite="add a comment to each function",
                    ask="? any bug", first="\t"),
    "tool.py": dict(ft="python", lang="code", at="def main(argv):\n", rewrite="add type hints",
                    ask="? review the error handling", first=" "),
    "setup.sh": dict(ft="shell", lang="code", at='mkdir -p "$BIN"\n', rewrite="add a --uninstall flag",
                     ask="?", first=None),
}
KINDS = ("complete", "rewrite", "ask")
# The grounded contracts, scored the same blind way: a source and a
# question crafted to invite invention. expect "refuse" means silence /
# exit 1 is the RIGHT answer (a kept line is false grounding); expect
# "answer" means a kept answer is right (silence is over-refusal), and
# `quote`, when set, must appear in it.
GROUND_DIR = os.path.join(FIX, "ground")
GROUND = {
    # a question the pamphlet does not touch: it names no price and sells
    # nothing. (Until v1.87 the question was when to water the trees --
    # which the pamphlet does answer, by sending the reader to the county
    # agent's soil card, so a line quoting that was right and counted
    # wrong.)
    "read-unanswered": dict(verb="read", src="orchard.txt",
                            words="what does a box of apples cost", expect="refuse"),
    "read-answered": dict(verb="read", src="orchard.txt",
                          words="how many rows of apple trees are there", expect="answer",
                          quote="forty rows"),
    "read-about": dict(verb="read", src="orchard.txt",
                       words="what is this text about", expect="answer", quote=""),
    # a note that leaves nothing to ask: the day and the hours, the place,
    # who it is for, who pays, what there is to eat, the rain, the shifts
    "ask-complete": dict(verb="ask", src="note.txt", words="", expect="refuse"),
    "ask-plan": dict(verb="ask", src="plan.txt", words="", expect="answer", quote=""),
    "watch-quiet": dict(verb="watch", src="log-quiet.txt",
                        words="when a 500 appears", expect="refuse"),
    "watch-hit": dict(verb="watch", src="log-500.txt",
                      words="when a 500 appears", expect="answer", quote="500"),
    "drill-thin": dict(verb="drill", src="thin.txt", words="", expect="refuse"),
    "drill-facts": dict(verb="drill", src="facts.txt", words="", expect="answer", quote=""),
    # the reading-discussion posture (spark edit ? --source): a published
    # source discussed, not a draft reviewed. The failure this pins
    # (2026-09-14): gemma reviewed a priced page and said it named no
    # price. Right = the answer names the price AND carries no editorial
    # verb (`forbid`).
    "discuss-price": dict(verb="edit", src="pricing.txt",
                          words="? --source does it name a price", expect="answer",
                          quote="$39",
                          forbid=r"(?i)\b(rephrase|consider adding|break (it|this) into|"
                                 r"could be clearer|i would (change|suggest)|a numbered)\b"),
}
EN = ("the", "and", "of", "to", "is", "in", "that", "it", "was", "with")
PT = ("de", "que", "não", "uma", "com", "para", "os", "as", "do", "da", "em", "é", "um", "se")
PREAMBLE = re.compile(r"^\s*(here is|here's|sure|certainly|of course|aqui está|claro|segue)", re.I)
PRAISE = re.compile(r"^\s*(great|nice|well done|excellent|wonderful|lovely|this is a (strong|great|good|fine|lovely))", re.I)
DEGENERATE = re.compile(r'"([^"\n]+)"\s*(->|→|becomes|to)\s*"\1"')


def lang_of(s):
    words = re.findall(r"[a-zA-Záéíóúâêôãõç]+", s.lower())
    en = sum(w in EN for w in words)
    pt = sum(w in PT for w in words)
    if en == pt == 0:
        return "?"
    return "pt" if pt > en else "en"


def compiles(ft, out):
    """(judged, ok): code must still parse; a missing tool leaves it unjudged."""
    with tempfile.NamedTemporaryFile("w", suffix={"python": ".py", "shell": ".sh", "go": ".go"}[ft], delete=False) as f:
        f.write(out)
        p = f.name
    try:
        if ft == "python":
            r = subprocess.run([sys.executable, "-m", "py_compile", p], capture_output=True)
        elif ft == "shell":
            r = subprocess.run(["sh", "-n", p], capture_output=True)
        else:
            if not shutil.which("gofmt"):
                return False, True
            r = subprocess.run(["gofmt", "-e", "-l", p], capture_output=True)
        return True, r.returncode == 0
    finally:
        os.unlink(p)


def common(out):
    yield "no fence", "```" not in out
    yield "no preamble", not PREAMBLE.match(out)
    yield "no placeholder", not re.search(r"\[\.\.\.\]|\bTODO\b|<placeholder>", out)


def blocks(text):
    """A text's stanzas or paragraphs: what the blank lines part."""
    return [b for b in re.split(r"\n[ \t]*\n", text.strip("\n")) if b.strip()]


def size(text):
    """A text's length however it is wrapped: its characters, every run of
    white space counted as one."""
    return len(" ".join(text.split()))


def lint_fit(out, inp, fx):
    """The size and shape a rewrite must come back in, read from what its
    instruction asks (the fixture's fit, part and lines). Code keeps its
    line count within 30 %. Prose is measured in words and characters,
    never lines: a paragraph wrapped again is the same paragraph. An
    instruction that says shorter must come back shorter, one that
    tightens or cuts never longer. One that names a stanza or a
    paragraph holds only that part to it, and the rest of the text must
    come back as it was -- line for line in a poem, word for word in
    prose."""
    fit, part = fx.get("fit"), fx.get("part")
    if fx["lang"] == "code":
        li, lo = inp.count("\n"), out.count("\n")
        yield "lines within 30 %", abs(lo - li) <= max(2, int(li * 0.3))
        return
    if part is None:
        if fit == "shorter":
            yield "shorter", size(out) < size(inp)
            return
        wi, wo = len(inp.split()), len(out.split())
        yield "words within 30 %", abs(wo - wi) <= max(2, int(wi * 0.3))
        if fit == "no longer":
            yield "no longer", size(out) <= size(inp)
        return
    bi, bo = blocks(inp), blocks(out)
    k = next(i for i, b in enumerate(bi) if b.startswith(part))
    kept = len(bo) == len(bi)

    def same(a, b):
        if fx.get("lines"):
            return [l.rstrip() for l in a.split("\n")] == [l.rstrip() for l in b.split("\n")]
        return a.split() == b.split()
    yield "the rest unchanged", kept and all(same(a, b) for i, (a, b) in enumerate(zip(bi, bo)) if i != k)
    ok = kept and (size(bo[k]) < size(bi[k]) if fit == "shorter" else size(bo[k]) <= size(bi[k]))
    if ok and fx.get("lines"):
        ok = bo[k].count("\n") <= bi[k].count("\n")
    yield "the named part %s" % fit, ok


def lint_rewrite(out, inp, fx, ft):
    for r in common(out):
        yield r
    yield "changed", out.strip() != inp.strip()
    yield "final newline kept", out.endswith("\n") == inp.endswith("\n")
    for r in lint_fit(out, inp, fx):
        yield r
    if fx["lang"] == "code":
        judged, ok = compiles(ft, out)
        if judged:
            yield "still compiles", ok
    else:
        yield "language kept", lang_of(out) == fx["lang"]
    if ft == "gitcommit":
        lines = out.splitlines()
        yield "subject <= 72, blank second line", bool(lines) and len(lines[0]) <= 72 and (len(lines) < 2 or lines[1] == "")


def lint_ask(out, inp, fx, sel):
    for r in common(out):
        yield r
    notes = re.findall(r"^\s*\d+[.)]\s", out, re.M)
    yield "at most five notes", len(notes) <= 5
    yield "no markdown marks", not re.search(r"\*\*|^#|^\|", out, re.M)
    yield "every quote anchors", textmod.ANCHOR_MARK not in out
    yield "quotes at all", bool(textmod.quotes(out.replace("\n", " "))) or bool(re.search(r"nothing (i would|to) change|change nothing", out, re.I))
    yield "no praise opener", not PRAISE.match(out)
    yield "no X -> X", not DEGENERATE.search(out)
    if fx["lang"] != "code":
        yield "answer in the text's language", lang_of(out) == fx["lang"]
    if sel:
        yield "no note on the mark lines", "selection starts" not in out and "selection ends" not in out


def lint_complete(out, before, fx):
    for r in common(out):
        yield r
    yield "at most six lines", out.count("\n") <= 6
    tail = before[-30:].strip()
    yield "no repeat of the text before", not (tail and tail in out)
    if fx["first"] is not None:
        yield "begins with the expected character", out.startswith(fx["first"])


def run_edit(args, stdin):
    t0 = time.time()
    p = subprocess.run([sys.executable, SPARK, "edit"] + args, input=stdin, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout, p.stderr, int((time.time() - t0) * 1000)


def run_ground(verb, words, stdin):
    """One grounded-contract run; drill answers come from a seam file
    (blank reveal + no, enough for ITEMS_MAX)."""
    env = dict(os.environ)
    tmp = None
    if verb == "drill":
        tmp = tempfile.NamedTemporaryFile("w", suffix=".answers", delete=False)
        tmp.write("\nno\n" * 20)
        tmp.close()
        env["SPARK_DRILL_TTY"] = tmp.name
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, SPARK, verb] + (words.split() if words else []),
                           input=stdin, capture_output=True, text=True, timeout=300, env=env)
    finally:
        if tmp:
            os.unlink(tmp.name)
    return p.returncode, p.stdout, p.stderr, int((time.time() - t0) * 1000)


def ground_one(name, g, verbose):
    """(right, kept_bad, over_refused, detail) for one ground fixture."""
    with open(os.path.join(GROUND_DIR, g["src"]), encoding="utf-8") as f:
        src = f.read()
    rc, out, err, ms = run_ground(g["verb"], g["words"], src)
    if verbose:
        print("--- ground %s (%d ms, rc %d)\n%s\n---" % (name, ms, rc, (out or err).rstrip()))
    kept = [l for l in out.splitlines() if l.strip()]
    if g["verb"] == "drill":
        kept = [l for l in (out + err).splitlines() if "the source says:" in l]
    if g["expect"] == "refuse":
        if kept:
            return 0, len(kept), 0, "kept %d line%s it should have refused" % (len(kept), "" if len(kept) == 1 else "s")
        return 1, 0, 0, "refused, rightly"
    if not kept:
        return 0, 0, 1, "refused an answer the source holds"
    if g.get("quote") and g["quote"].lower() not in out.lower():
        return 0, len(kept), 0, "answered without quoting %r" % g["quote"]
    if g.get("forbid") and re.search(g["forbid"], out):
        return 0, len(kept), 0, "answered but slipped into the editor's posture"
    return 1, 0, 0, "answered, grounded"


def one(name, fx, kind, verbose):
    """[(lint, ok)], ms, the answer (or the error), spark edit's exit code.
    When spark edit gives no answer (a non-zero exit), every lint the
    run would have had is failed: a run with no answer weighs what a
    judged run does, never one check."""
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        inp = f.read()
    base = ["--type", fx["ft"], "--name", name]
    if kind == "complete":
        at = inp.index(fx["at"]) + len(fx["at"])
        args = base + ["--at", str(at)]

        def judge(out):
            return lint_complete(out, inp[:at], fx)
    elif kind == "rewrite":
        args = base + fx["rewrite"].split()

        def judge(out):
            return lint_rewrite(out, inp, fx, fx["ft"])
    else:
        sel = fx.get("sel")
        args = base + fx["ask"].split()
        if sel:
            a = inp.index(sel[0])
            b = inp.index(sel[1]) + len(sel[1])
            args += ["--sel", str(a), str(b)]

        def judge(out):
            return lint_ask(out, inp, fx, bool(sel))
    rc, out, err, ms = run_edit(args, inp)
    if rc == 0:
        lints = list(judge(out))
    else:
        # the lints' names, read off the text itself: the full set
        lints = [(what, False) for what, _ok in judge(inp)]
        out = err.strip()
    if verbose:
        print("--- %s %s (%d ms)\n%s\n---" % (name, kind, ms, out.rstrip()))
    return lints, ms, out, rc


def tally(notes):
    """Every run's note, each said once with how many runs gave it: the
    last run's note never stands for the others."""
    if len(notes) == 1:
        return notes[0]
    seen = {}
    for note in notes:
        seen[note] = seen.get(note, 0) + 1
    return "; ".join("%dx %s" % (n, note) for note, n in seen.items())


def brain_up():
    rc, _out, err, _ms = run_edit(["--type", "text", "--at", "6"], "Hello ")
    return rc == 0, err.strip()


def briefs():
    # the editor's four, plus the grounded contracts' own: a ground score
    # is only comparable under the briefs that produced it
    keys = ("edit-complete", "edit-rewrite", "edit-answer", "edit-read",
            "read-source", "ask-questions", "watch-stream", "drill-items")
    return dict((k, hashlib.sha256(persona.MODES[k].encode()).hexdigest()[:12])
                for k in keys if k in persona.MODES)


def last_model():
    try:
        names = sorted(glob.glob(os.path.join(STATE_DIR, "turns", "*.jsonl")))
        lines = [l for l in open(names[-1], encoding="utf-8").read().splitlines() if l.strip()]
        return json.loads(lines[-1]).get("model", "?")
    except (IndexError, OSError, ValueError):
        return "?"


def selftest():
    """The rewrite lints and the counting, with no model: canned rewrites
    of the real fixtures. A rewrite that does what its instruction asks
    passes -- wrapped again or not -- and each way to miss it fails on
    the lint that names it."""
    import textwrap
    fails = []

    def check(ok, what, detail=""):
        print(("ok   " if ok else "FAIL ") + what + ("" if ok or not detail else "  -- %s" % (detail,)))
        if not ok:
            fails.append(what)

    def read(name):
        with open(os.path.join(FIX, name), encoding="utf-8") as f:
            return f.read()

    def failed(name, out):
        fx = FIXTURES[name]
        return sorted(what for what, ok in lint_rewrite(out, read(name), fx, fx["ft"]) if not ok)

    def rewrap(text, width):
        return "\n\n".join(b if b.startswith("#") else textwrap.fill(" ".join(b.split()), width)
                           for b in blocks(text)) + "\n"

    poem = read("poem.txt")
    head = poem.rsplit("\n\n", 1)[0]
    tight = head + "\n\nOutside, the street is a rumour.\nA bus goes by, empty.\nI hold the cup\nand give the day a minute.\n"
    fewer = head + "\n\nThe street is a rumour, the bus empty.\nI hold the cup and give the day a minute.\n"
    check(failed("poem.txt", tight) == [] and failed("poem.txt", fewer) == [],
          "tighten the last stanza: a tighter stanza passes, with fewer lines too", failed("poem.txt", fewer))
    check(failed("poem.txt", tight.replace("The kettle learns", "A kettle learns")) == ["the rest unchanged"],
          "tighten the last stanza: another stanza touched fails")
    check(failed("poem.txt", head + "\n\nOutside the street is still only a rumour of itself.\nA bus goes by "
                 "with no one at all inside it.\nI hold the cup with both my hands\nand give the day another minute.\n")
          == ["the named part no longer"], "tighten the last stanza: a longer stanza fails")
    commit = read("commit.txt")
    short = ("tally: count bytes as well as characters\n\nUTF-8 has more bytes than characters, so the bytes column was\n"
             "missed. It is off by default; the README says so.\n")
    check(failed("commit.txt", short) == [], "shorter: a shorter message passes, whatever its line count",
          failed("commit.txt", short))
    check(failed("commit.txt", commit.replace("confused", "at a loss")) == ["shorter"],
          "shorter: a message that is not shorter fails")
    chapter = read("chapter.md")
    cut = chapter
    for adverb in (" exactly", " very much", " always"):
        cut = cut.replace(adverb, "")
    cut = rewrap(cut, 40)
    grew = abs(cut.count("\n") - chapter.count("\n")) > max(2, int(chapter.count("\n") * 0.3))
    check(grew and failed("chapter.md", cut) == [],
          "cut the adverbs: paragraphs wrapped again pass (the line count no longer judges prose)",
          failed("chapter.md", cut))
    check(failed("chapter.md", rewrap(chapter.replace("which she had\nnot.", "which she had\nnot expected at all, not once."), 40))
          == ["no longer"], "cut the adverbs: a longer text fails")
    prosa = read("prosa.md")
    pb = blocks(prosa)
    k = next(i for i, b in enumerate(pb) if b.startswith(FIXTURES["prosa.md"]["part"]))
    one_sentence = pb[k].split(". ")[0].replace("\n", " ") + "."
    shorter = rewrap("\n\n".join(pb[:k] + [one_sentence] + pb[k + 1:]), 50)
    check(failed("prosa.md", shorter) == [],
          "make the second paragraph shorter: it is shorter, the rest wrapped again: passes", failed("prosa.md", shorter))
    check(failed("prosa.md", "\n\n".join(pb[:k - 1] + [pb[k - 1].split(". ")[0] + "."] + [one_sentence] + pb[k + 1:]) + "\n")
          == ["the rest unchanged"], "make the second paragraph shorter: another paragraph cut fails")
    check(failed("prosa.md", rewrap(prosa, 50)) == ["the named part shorter"],
          "make the second paragraph shorter: the paragraph as long as before fails", failed("prosa.md", rewrap(prosa, 50)))

    # no answer from spark edit: the run's full set of lints is failed
    def with_edit(answer, name, kind):
        real = globals()["run_edit"]
        globals()["run_edit"] = answer
        try:
            return one(name, FIXTURES[name], kind, False)
        finally:
            globals()["run_edit"] = real
    for name, kind in (("poem.txt", "rewrite"), ("chapter.md", "ask"), ("tool.py", "complete")):
        lints, _ms, out, rc = with_edit(lambda args, stdin: (1, "", "no model answers\n", 5), name, kind)
        judged = with_edit(lambda args, stdin: (0, stdin, "", 5), name, kind)[0]
        check(rc == 1 and out == "no model answers" and len(lints) > 1 and not any(ok for _w, ok in lints)
              and [w for w, _ok in lints] == [w for w, _ok in judged],
              "%s %s: no answer fails every lint a judged run has (%d), not one" % (name, kind, len(lints)))
    check(tally(["refused, rightly"]) == "refused, rightly"
          and tally(["refused, rightly", "kept 1 line it should have refused", "refused, rightly"])
          == "2x refused, rightly; 1x kept 1 line it should have refused",
          "the grounded cases: every run's note is kept, each with its count")
    with open(os.path.join(GROUND_DIR, "orchard.txt"), encoding="utf-8") as f:
        orchard = f.read().lower()
    asked = GROUND["read-unanswered"]["words"]
    check(not any(w in orchard for w in ("cost", "price", "box", "sell", "sold", "buy")) and "cost" in asked,
          "read-unanswered: the pamphlet does not touch what the question asks")
    print("audition selftest: %d failed" % len(fails) if fails else "audition selftest: all ok")
    return 1 if fails else 0


def main(argv):
    times, kinds, names, as_json, verbose = 1, list(KINDS), list(FIXTURES), False, False
    ground_only = False
    if argv == ["--selftest"]:
        return selftest()
    it = iter(argv)
    for a in it:
        if a == "--times":
            times = int(next(it))
        elif a == "--kind":
            kinds = [next(it)]
        elif a == "--fixture":
            names = [next(it)]
        elif a == "--ground":
            ground_only = True
        elif a == "--json":
            as_json = True
        elif a == "-v":
            verbose = True
        else:
            print(__doc__ or "usage: audition.py [--times N] [--kind K] [--fixture NAME] [--ground] [--json] [-v]")
            return 2
    if ground_only:
        names = []
    up, why = brain_up()
    if not up:
        print("audition: no brain answers -- skipped (%s)" % why)
        return 0
    cells, ms_by_kind = {}, dict((k, []) for k in kinds)
    for name in names:
        fx = FIXTURES[name]
        for kind in kinds:
            passed = total = 0
            failed = []
            for _ in range(times):
                lints, ms, _out, rc = one(name, fx, kind, verbose)
                ms_by_kind[kind].append(ms)
                if rc != 0:
                    failed.append("spark edit answered")     # the reason, said once: its lints all count below
                for what, ok in lints:
                    total += 1
                    passed += bool(ok)
                    if not ok and rc == 0:
                        failed.append(what)
            cells[(name, kind)] = (passed, total, failed)
            print("  %-11s %-8s %2d/%-2d %s" % (name, kind, passed, total, "" if not failed else "-- " + ", ".join(sorted(set(failed)))))
    print("")
    print("  %-11s %s" % ("", "".join("%-9s" % k for k in kinds) + "total"))
    grand = [0, 0]
    for name in names:
        row = ""
        for kind in kinds:
            p, t, _ = cells[(name, kind)]
            row += "%-9s" % ("%d/%d" % (p, t))
        rp = sum(cells[(name, k)][0] for k in kinds)
        rt = sum(cells[(name, k)][1] for k in kinds)
        grand[0] += rp
        grand[1] += rt
        print("  %-11s %s%d/%d" % (name, row, rp, rt))
    med = "  ".join("%s %d ms" % (k, statistics.median(v)) for k, v in ms_by_kind.items() if v)
    if names:
        print("  %-11s %d/%d passed, %d %%   (median: %s)" % ("all", grand[0], grand[1], 100 * grand[0] // max(1, grand[1]), med))
    # the grounded contracts: under --ground alone, so a run of the
    # editor's fixtures never asks them a second time
    g_cells, g_notes, g_right, g_kept_bad, g_over = {}, {}, 0, 0, 0
    if ground_only:
        print("")
        print("  the grounded contracts (right runs; false grounding; over-refusal):")
        for gname, g in GROUND.items():
            right = kept_bad = over = 0
            notes = []
            for _ in range(times):
                r, kb, ov, detail = ground_one(gname, g, verbose)
                right += r
                kept_bad += kb
                over += ov
                notes.append(detail)
            g_right += right
            g_kept_bad += kept_bad
            g_over += over
            g_cells[gname] = (right, times)
            g_notes[gname] = notes
            print("  %-16s %d/%d  %s" % (gname, right, times, "-- " + tally(notes)))
        print("  %-16s %d/%d right, %d falsely grounded line%s, %d over-refusal%s"
              % ("ground", g_right, len(GROUND) * times, g_kept_bad,
                 "" if g_kept_bad == 1 else "s", g_over, "" if g_over == 1 else "s"))
    if as_json:
        os.makedirs(STATE_DIR, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "model": last_model(), "briefs": briefs(), "times": times,
               "passed": grand[0], "total": grand[1],
               "cells": dict(("%s %s" % k, {"passed": v[0], "total": v[1]}) for k, v in cells.items())}
        if g_cells:
            rec["ground"] = {"right": g_right, "total": len(GROUND) * times,
                             "false_grounding": g_kept_bad, "over_refusals": g_over,
                             "cells": dict((k, {"right": v[0], "total": v[1], "notes": g_notes[k]})
                                           for k, v in g_cells.items())}
        with open(os.path.join(STATE_DIR, "audition.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("  recorded in %s" % os.path.join(STATE_DIR, "audition.jsonl"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
