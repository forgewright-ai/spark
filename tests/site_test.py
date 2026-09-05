#!/usr/bin/env python3
# site_test.py -- www/build.py renders the docs into a site; these are the
# invariants of that rendering, not a case list: every heading survives,
# every fenced block is a <pre>, every table keeps its rows, HTML in a doc
# is text (`<file>` is a file), no placeholder is left, the output is ASCII
# (the docs are), and every page the nav names exists.
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = {"install": "INSTALL.md", "changelog": "CHANGELOG.md", "roadmap": "ROADMAP.md",
        "contributing": "CONTRIBUTING.md", "credits": "CREDITS.md"}
fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
    print(("ok   " if cond else "FAIL ") + what)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def outside_fences(text):
    keep, on = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            on = not on
            continue
        if not on:
            keep.append(line)
    return keep


def main():
    out = tempfile.mkdtemp(prefix="spark-www-")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "www", "build.py"), out],
                       capture_output=True, text=True)
    check(r.returncode == 0, "build exits 0" + ("" if r.returncode == 0 else ": " + r.stderr.strip()))
    if r.returncode:
        return finish()
    pages = {"": read(os.path.join(out, "index.html"))}
    for slug in list(DOCS) + ["cheatsheet", "models"]:
        p = os.path.join(out, slug, "index.html")
        check(os.path.exists(p), "page %s/ exists" % slug)
        pages[slug] = read(p) if os.path.exists(p) else ""
    for name, text in pages.items():
        label = name or "index"
        check("{{" not in text, "%s: no placeholder left" % label)
        check(all(ord(c) < 128 for c in text), "%s: ASCII" % label)
    # every nav target is a page that exists
    for href in set(re.findall(r'<nav>.*?</nav>', pages["install"], re.S)[0].split('href="')[1:]):
        href = href.split('"')[0]
        if href.startswith("http"):
            continue
        target = os.path.normpath(os.path.join(out, "install", href, "index.html"))
        check(os.path.exists(target), "nav target %s exists" % href)
    for slug, doc in DOCS.items():
        src, page = read(os.path.join(ROOT, doc)), pages[slug]
        lines = outside_fences(src)
        for line in lines:
            m = re.match(r"^(#{1,3}) (.*)$", line)
            if m:
                # the heading's plain words survive rendering (code spans and bold aside)
                words = re.sub(r"[`*]", "", m.group(2)).split()
                tag = "<h%d>" % len(m.group(1))
                hit = any(all(w in re.sub(r"<[^>]+>", "", h) for w in words)
                          for h in re.findall(r"%s(.*?)</h\d>" % tag, page))
                check(hit, "%s: heading kept: %s" % (slug, m.group(2)[:50]))
        fences = src.count("\n```") // 2 + (1 if src.startswith("```") else 0)
        check(page.count("<pre>") == fences, "%s: %d fenced blocks -> %d <pre>" % (slug, fences, page.count("<pre>")))
        table_rows = sum(1 for l in lines if l.startswith("|") and not re.fullmatch(r"[|:\- ]+", l))
        check(page.count("<tr>") == table_rows, "%s: %d table rows -> %d <tr>" % (slug, table_rows, page.count("<tr>")))
        angle = sum(1 for l in lines if "<file>" in l)
        if angle:
            check("&lt;file&gt;" in page and "<file>" not in page, "%s: <file> is text" % slug)
        items = sum(1 for l in lines if re.match(r"^([-*]|\d+\.) ", l))
        check(page.count("<li>") >= items, "%s: %d list items -> %d <li>" % (slug, items, page.count("<li>")))
    check("<pre>SPARK CHEATSHEET" in pages["cheatsheet"], "cheatsheet: the text, verbatim")
    curated = sum(1 for l in read(os.path.join(ROOT, "models.env")).split("\n") if re.match(r'^MODEL_[A-Z0-9_]+="', l))
    check(pages["models"].count("<tr>") >= curated + 1, "models: every curated row is on the page")
    check("banner.svg" in pages[""] and 'id="ol"' in pages[""], "index: the banner and the one-liner")
    return finish()


def finish():
    if fails:
        print("site_test: %d failed" % len(fails))
        return 1
    print("site_test: all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
