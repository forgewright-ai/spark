#!/usr/bin/env python3
# site_test.py -- www/build.py renders the docs into a site; these are the
# invariants of that rendering, not a case list: every heading survives,
# every fenced block is a <pre>, every table keeps its rows, HTML in a doc
# is text (`<file>` is a file), no placeholder is left, the output is ASCII
# (the docs are), and every page the nav names exists.
import html as html_mod
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
                lvl = len(m.group(1))
                hit = any(all(w in re.sub(r"<[^>]+>", "", h) for w in words)
                          for h in re.findall(r"<h%d[^>]*>(.*?)</h\d>" % lvl, page))
                check(hit, "%s: heading kept: %s" % (slug, m.group(2)[:50]))
        fences = sum(1 for l in src.split("\n") if l.lstrip().startswith("```")) // 2
        check(page.count("<pre>") == fences, "%s: %d fenced blocks -> %d <pre>" % (slug, fences, page.count("<pre>")))
        table_rows = sum(1 for l in lines if l.startswith("|") and not re.fullmatch(r"[|:\- ]+", l))
        check(page.count("<tr>") == table_rows, "%s: %d table rows -> %d <tr>" % (slug, table_rows, page.count("<tr>")))
        angle = sum(1 for l in lines if "<file>" in l)
        if angle:
            check("&lt;file&gt;" in page and "<file>" not in page, "%s: <file> is text" % slug)
        items = sum(1 for l in lines if re.match(r"^([-*]|\d+\.) ", l))
        check(page.count("<li>") >= items, "%s: %d list items -> %d <li>" % (slug, items, page.count("<li>")))
    check("<pre>SPARK CHEATSHEET" in pages["cheatsheet"], "cheatsheet: the text, verbatim")
    rows = sum(1 for l in read(os.path.join(ROOT, "models.env")).split("\n")
               if re.match(r'^MODEL_[A-Z0-9_]+="', l) and not re.match(r'^MODEL_[A-Z0-9_]+_(LICENSE|NOTE|TESTED)=', l))
    check(pages["models"].count("<tr>") == rows + 1, "models: every row of models.env is on the page (%d)" % rows)
    check("banner.svg" in pages[""] and 'id="ol"' in pages[""], "index: the banner and the one-liner")
    check("spark chat" in pages[""], "index: spark chat and the prompt line")
    apps = sorted(set(re.findall(r"github\.com/forgewright-ai/(spark-[a-z0-9]+)",
                                 read(os.path.join(ROOT, "README.md")))))
    for app in apps:
        check(app in pages[""], "index: the front names %s (the README does)" % app)
    check("spark shell" not in pages[""], "index: the front is spark and spark apps; the shell layer is SHELL.md's")
    # the front's stages: an OS panel each, and every marked command is a
    # line the docs have (the front never teaches what a doc does not)
    for os_id in ("debian", "arch", "macos", "windows"):
        check('data-os="%s"' % os_id in pages[""], "index: an OS panel for %s" % os_id)
    # APPS.md joins the sources: the app lines the front shows moved there
    # when the core docs stopped naming the apps
    docs_text = (read(os.path.join(ROOT, "INSTALL.md")) + read(os.path.join(ROOT, "README.md"))
                 + read(os.path.join(ROOT, "APPS.md")))
    blocks = re.findall(r"<pre data-doc>(.*?)</pre>", pages[""], re.S)
    blocks += re.findall(r'<code id="ol2?">(.*?)</code>', pages[""])
    check(len(blocks) >= 8, "index: the doc-verbatim blocks (%d)" % len(blocks))
    for b in blocks:
        for line in html_mod.unescape(re.sub(r"<[^>]+>", "", b)).split("\n"):
            if line.strip():
                check(line.strip() in docs_text, "index: a doc's line: %s" % line.strip()[:60])
    # the template: both palettes, the toggle, the pre-paint snippet
    tpl = read(os.path.join(ROOT, "www", "template.html"))
    check(':root[data-theme="light"]' in tpl and 'id="theme"' in tpl and tpl.count("spark-theme") >= 2,
          "template: a light palette, the toggle and the pre-paint snippet")
    # install/: unique h2 ids, and the table of contents points at them
    ids = re.findall(r'<h2 id="([^"]+)"', pages["install"])
    check(bool(ids) and len(ids) == len(set(ids)), "install: every h2 has a unique id")
    m = re.search(r'<aside class="toc">.*?</aside>', pages["install"], re.S)
    check(bool(m), "install: a table of contents")
    for target in re.findall(r'href="#([^"]+)"', m.group(0) if m else ""):
        check(target in ids, "install: toc target #%s exists" % target)
    # a CHANGELOG section above the newest tag is marked unreleased on the page
    sys.path.insert(0, os.path.join(ROOT, "www"))
    import build
    marked = build.unreleased("## v9.9\n\n## v1.0\n", "1.5")
    check(marked == "## v9.9 (unreleased)\n\n## v1.0\n", "changelog: a section above the newest tag reads (unreleased)")
    check(build.unreleased("## v1.5\n", "dev") == "## v1.5\n", "changelog: no tag, no mark")
    return finish()


def finish():
    if fails:
        print("site_test: %d failed" % len(fails))
        return 1
    print("site_test: all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
