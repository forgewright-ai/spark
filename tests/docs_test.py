#!/usr/bin/env python3
# docs_test.py -- the docs say what the tree holds. Every fact below is
# derived from the tree and looked up in the doc that states it, so a
# palette, a model row or a check row cannot land without its credit or
# its count following: every themes/*.env upstream is in CREDITS.md; every
# model row's license upstream is in CREDITS.md; the check-row count the
# docs state is the count in check.py; the model count they state is the
# count in models.env; every page www/build.py renders has its source
# file; no doc names the lists that are gone. Hermetic, stdlib, fast.
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
from spark import config  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
    print(("ok   " if cond else "FAIL ") + what)


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def upstream(url):
    """scheme://host/first-segment -- the org page a license URL lives under
    (https://huggingface.co/Qwen/Qwen3-8B -> https://huggingface.co/Qwen;
    https://ai.google.dev/gemma/terms -> https://ai.google.dev/gemma)."""
    m = re.match(r"(https?://[^/]+/[^/]+)", url)
    return m.group(1) if m else url


def tests_named():
    """Every tests/*.py and tests/*.sh is named in AGENTS.md (the gate list
    or the audition section): a test nobody is told to run drifts."""
    agents = read("AGENTS.md")
    for name in sorted(os.listdir(os.path.join(ROOT, "tests"))):
        if name.endswith((".py", ".sh")):
            check(name in agents, "AGENTS.md names tests/%s" % name)


def main():
    tests_named()
    credits = read("CREDITS.md")
    # palettes: the header comment of every themes/*.env names its upstream URL
    for f in sorted(os.listdir(os.path.join(ROOT, "themes"))):
        if not f.endswith(".env"):
            continue
        head = read(os.path.join("themes", f)).split("\n", 1)[0]
        m = re.search(r"https?://\S+?(?=[\s)]|$)", head)
        check(bool(m), "themes/%s: the header names its upstream URL" % f)
        if m:
            check(m.group(0) in credits, "CREDITS.md names %s (%s)" % (f[:-4], m.group(0)))
    # models: every row's license upstream is credited
    rows = [r for r in config.model_tables(ROOT) if r[6] == "repo"]
    seen = set()
    for r in rows:
        up = upstream(r[8].split()[-1])
        if up in seen:
            continue
        seen.add(up)
        check(up in credits, "CREDITS.md names %s (%s)" % (up, r[0]))
    # counts the docs state
    n_rows = sum(1 for line in read(os.path.join("lib", "spark", "check.py")).split("\n") if line.startswith("@row"))
    for doc in ("CLAUDE.md", "INSTALL.md"):
        for m in re.finditer(r"spark check`?\s+(?:has )?(\d+) rows", read(doc)):
            check(int(m.group(1)) == n_rows, "%s: '%s' is check.py's count (%d)" % (doc, m.group(0), n_rows))
    # the gated row lists: CLAUDE.md states their counts, and names the
    # client's rows one by one
    src = read(os.path.join("lib", "spark", "check.py"))
    claude = read("CLAUDE.md")
    named = {}
    for const in ("SHELL_ROWS", "CLIENT_ROWS"):
        m = re.search(r"^%s = \(([^)]*)\)" % const, src, re.M)
        named[const] = re.findall(r'"([a-z]+)"', m.group(1)) if m else []
        check(bool(named[const]), "check.py defines %s" % const)
        for c in re.finditer(r"the (\d+) rows in `check\.%s`" % const, claude):
            check(int(c.group(1)) == len(named[const]),
                  "CLAUDE.md: '%s' is check.py's count (%d)" % (c.group(0), len(named[const])))
    m = re.search(r"`check\.CLIENT_ROWS` \(([^)]*)\)", claude)
    listed = re.split(r",\s+", " ".join(m.group(1).split())) if m else []
    check(listed == named["CLIENT_ROWS"],
          "CLAUDE.md names check.CLIENT_ROWS in order (%s)" % ", ".join(named["CLIENT_ROWS"]))
    n_models = len(rows)
    for doc in ("README.md", "INSTALL.md"):
        for m in re.finditer(r"(\d+) (models|rows), each with its license", read(doc)):
            check(int(m.group(1)) == n_models, "%s: '%s' is models.env's count (%d)" % (doc, m.group(0), n_models))
    # the page renders docs that exist, and nothing else is named as a page
    build = read(os.path.join("www", "build.py"))
    for src in re.findall(r'\("[a-z]+", "[a-z]+", "([A-Za-z.]+)", "(?:md|text)"\)', build):
        check(os.path.exists(os.path.join(ROOT, src)), "www/build.py renders %s, which exists" % src)
    # the CHANGELOG's top section is the newest tag or the one right after it
    # (written before its tag, CLAUDE.md Releasing) -- never further ahead,
    # never behind
    import subprocess
    try:
        tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()[1:]
    except (OSError, subprocess.CalledProcessError):
        tag = ""
    top = re.search(r"^## v(\d+)\.(\d+)$", read("CHANGELOG.md"), re.M)
    if tag and top and re.match(r"^\d+\.\d+$", tag):
        major, minor = int(top.group(1)), int(top.group(2))
        tmaj, tmin = (int(x) for x in tag.split("."))
        check((major, minor) in ((tmaj, tmin), (tmaj, tmin + 1), (tmaj + 1, 0)),
              "CHANGELOG.md: the top section v%d.%d is the newest tag v%s or the next release" % (major, minor, tag))
    # the lists that are gone stay gone
    for doc in ("README.md", "INSTALL.md", "CLAUDE.md", "CHEATSHEET.txt", "CREDITS.md", "CONTRIBUTING.md",
                "AGENTS.md", "ROADMAP.md", "site.env.example"):
        check(not re.search(r"embers\.env|community\.env|\bcurated\b", read(doc)), "%s: no retired list word" % doc)
    if fails:
        print("docs_test: %d failed" % len(fails))
        return 1
    print("docs_test: all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
