#!/usr/bin/env python3
# audition.py -- the editor's briefs, judged blind. Eight fixtures (a poem,
# a chapter, a README, a commit message, Portuguese prose, Go, Python,
# shell) go through the real `spark edit` -- complete, rewrite, ? -- against
# whatever brain this machine answers from (a client asks its peer), and
# mechanical lints score every answer: no fence, no preamble, a poem keeps
# its lines, code still compiles, the language holds, at most five notes,
# every quote anchors, no "X" -> "X", no praise opener. Nothing prints an
# answer unless -v: the lints are the judge, never the reader's taste.
#
#   python3 tests/audition.py [--times N] [--kind complete|rewrite|ask]
#                             [--fixture NAME] [--json] [-v]
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
FIXTURES = {
    "poem.txt": dict(ft="text", lang="en", at="eleven, then the loose twelfth board,\n",
                     rewrite="tighten the last stanza", ask="?", first=None),
    "chapter.md": dict(ft="markdown", lang="en", at="each\ntime it said the same thing in the same careful hand: ",
                       rewrite="cut the adverbs", ask="? is the ending earned",
                       sel=("The island rose", "look like patience."), first=None),
    "README.md": dict(ft="markdown", lang="en", at="Exit codes: 0 when every file was read, 1 when one could not be, ",
                      rewrite="make the install section clearer", ask="?", first=None),
    "commit.txt": dict(ft="gitcommit", lang="en", at="The reader keeps the raw length before decoding, ",
                       rewrite="shorter", ask="? is the subject line right", first=None),
    "prosa.md": dict(ft="markdown", lang="pt", at="Trazia o café num garrafão e as notícias da noite: ",
                     rewrite="deixe o segundo parágrafo mais curto", ask="?",
                     sel=("O neto vinha", "que era o bastante."), first=None),
    "main.go": dict(ft="go", lang="code", at="\tif len(os.Args) < 2 {\n", rewrite="add a comment to each function",
                    ask="? any bug", first="\t"),
    "tool.py": dict(ft="python", lang="code", at="def main(argv):\n", rewrite="add type hints",
                    ask="? review the error handling", first=" "),
    "setup.sh": dict(ft="shell", lang="code", at='mkdir -p "$BIN"\n', rewrite="add a --uninstall flag",
                     ask="?", first=None),
}
KINDS = ("complete", "rewrite", "ask")
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


def lint_rewrite(out, inp, fx, ft):
    for r in common(out):
        yield r
    yield "changed", out.strip() != inp.strip()
    yield "final newline kept", out.endswith("\n") == inp.endswith("\n")
    li, lo = inp.count("\n"), out.count("\n")
    if fx is FIXTURES["poem.txt"]:
        yield "poem: every line and stanza", lo == li and out.count("\n\n") == inp.count("\n\n")
    else:
        yield "lines within 30 %", abs(lo - li) <= max(2, int(li * 0.3))
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


def one(name, fx, kind, verbose):
    """[(lint, ok)], ms, the answer (or the error)."""
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        inp = f.read()
    base = ["--type", fx["ft"], "--name", name]
    if kind == "complete":
        at = inp.index(fx["at"]) + len(fx["at"])
        rc, out, err, ms = run_edit(base + ["--at", str(at)], inp)
        lints = list(lint_complete(out, inp[:at], fx)) if rc == 0 else []
    elif kind == "rewrite":
        rc, out, err, ms = run_edit(base + fx["rewrite"].split(), inp)
        lints = list(lint_rewrite(out, inp, fx, fx["ft"])) if rc == 0 else []
    else:
        sel = fx.get("sel")
        args = base + fx["ask"].split()
        if sel:
            a = inp.index(sel[0])
            b = inp.index(sel[1]) + len(sel[1])
            args += ["--sel", str(a), str(b)]
        rc, out, err, ms = run_edit(args, inp)
        lints = list(lint_ask(out, inp, fx, bool(sel))) if rc == 0 else []
    if rc != 0:
        lints = [("spark edit answered", False)]
        out = err.strip()
    if verbose:
        print("--- %s %s (%d ms)\n%s\n---" % (name, kind, ms, out.rstrip()))
    return lints, ms, out


def brain_up():
    rc, _out, err, _ms = run_edit(["--type", "text", "--at", "6"], "Hello ")
    return rc == 0, err.strip()


def briefs():
    return dict((k, hashlib.sha256(persona.MODES[k].encode()).hexdigest()[:12])
                for k in ("edit-complete", "edit-rewrite", "edit-ask", "edit-read"))


def last_model():
    try:
        names = sorted(glob.glob(os.path.join(STATE_DIR, "turns", "*.jsonl")))
        lines = [l for l in open(names[-1], encoding="utf-8").read().splitlines() if l.strip()]
        return json.loads(lines[-1]).get("model", "?")
    except (IndexError, OSError, ValueError):
        return "?"


def main(argv):
    times, kinds, names, as_json, verbose = 1, list(KINDS), list(FIXTURES), False, False
    it = iter(argv)
    for a in it:
        if a == "--times":
            times = int(next(it))
        elif a == "--kind":
            kinds = [next(it)]
        elif a == "--fixture":
            names = [next(it)]
        elif a == "--json":
            as_json = True
        elif a == "-v":
            verbose = True
        else:
            print(__doc__ or "usage: audition.py [--times N] [--kind K] [--fixture NAME] [--json] [-v]")
            return 2
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
                lints, ms, _out = one(name, fx, kind, verbose)
                ms_by_kind[kind].append(ms)
                for what, ok in lints:
                    total += 1
                    passed += bool(ok)
                    if not ok:
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
    print("  %-11s %d/%d passed, %d %%   (median: %s)" % ("all", grand[0], grand[1], 100 * grand[0] // max(1, grand[1]), med))
    if as_json:
        os.makedirs(STATE_DIR, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "model": last_model(), "briefs": briefs(), "times": times,
               "passed": grand[0], "total": grand[1],
               "cells": dict(("%s %s" % k, {"passed": v[0], "total": v[1]}) for k, v in cells.items())}
        with open(os.path.join(STATE_DIR, "audition.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("  recorded in %s" % os.path.join(STATE_DIR, "audition.jsonl"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
