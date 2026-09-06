#!/usr/bin/env python3
# www/build.py -- spark's page, spark.forgewright.ai, rendered from the
# repository's own files into www/dist/: the index is the banner, the
# one-liner and two demos; every other page IS a doc (INSTALL.md,
# CHEATSHEET.txt, the model list, CHANGELOG.md, ROADMAP.md,
# CONTRIBUTING.md, CREDITS.md) rendered as it is. Nothing is written here
# twice: a doc change is a site change. Stdlib only; the markdown subset is
# the one the docs use (tests/site_test.py holds the invariants).
#
#   python3 www/build.py [OUT_DIR]           default www/dist
#   python3 -m http.server -d www/dist       then http://localhost:8000/
#
# Links are relative, so one build serves forgewright-ai.github.io/spark/,
# spark.forgewright.ai and a local server alike.
import html
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
from spark import config  # noqa: E402  (the model list, parsed by spark itself)

# slug -> (title, source file, kind)
PAGES = [
    ("install", "install", "INSTALL.md", "md"),
    ("cheatsheet", "cheatsheet", "CHEATSHEET.txt", "text"),
    ("models", "models", None, "models"),
    ("changelog", "changelog", "CHANGELOG.md", "md"),
    ("roadmap", "roadmap", "ROADMAP.md", "md"),
    ("contributing", "contributing", "CONTRIBUTING.md", "md"),
    ("credits", "credits", "CREDITS.md", "md"),
]
# a doc's own name in the text links to its page
DOC_LINKS = {
    "README.md": "", "INSTALL.md": "install/", "CHEATSHEET.txt": "cheatsheet/",
    "CHANGELOG.md": "changelog/", "ROADMAP.md": "roadmap/",
    "CONTRIBUTING.md": "contributing/", "CREDITS.md": "credits/",
    "models.env": "models/",
}
DOC_RE = re.compile(r"\b(%s)\b" % "|".join(re.escape(k) for k in DOC_LINKS))
URL_RE = re.compile(r"https?://[^\s<>\"]+")
HEADING_RE = re.compile(r"^(#{1,3}) (.*)$")
ITEM_RE = re.compile(r"^( *)([-*]|\d+\.) (.*)$")
FENCE = "```"


RELEASES = "https://github.com/forgewright-ai/spark/releases"


def version():
    """The newest tag: the version the one-liner installs (get lands a
    stranger there), so the sign line and the install agree."""
    try:
        out = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        return out[1:] if out.startswith("v") else out
    except (OSError, subprocess.CalledProcessError):
        return "dev"


# --- inline markdown: code spans, bold, bare URLs, doc names -----------------

def _text(s, base):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    def url(m):
        u = m.group(0)
        tail = ""
        while u and u[-1] in ".,;:)":
            tail = u[-1] + tail
            u = u[:-1]
        return '<a href="%s">%s</a>%s' % (u, u, tail)
    s = URL_RE.sub(url, s)
    return DOC_RE.sub(lambda m: '<a href="%s%s">%s</a>' % (base, DOC_LINKS[m.group(1)], m.group(1)), s)


def inline(s, base):
    out = []
    for i, part in enumerate(re.split(r"(`[^`]+`)", s)):
        if i % 2:
            code = html.escape(part[1:-1], quote=False)
            code = DOC_RE.sub(lambda m: '<a href="%s%s">%s</a>' % (base, DOC_LINKS[m.group(1)], m.group(1)), code)
            out.append("<code>%s</code>" % code)
        else:
            out.append(_text(part, base))
    return "".join(out)


# --- block markdown ---------------------------------------------------------

def markdown(text, base):
    """The subset the docs use: # to ###, paragraphs, fenced code, pipe
    tables, bullet and numbered lists (one nesting level, continuation
    lines indented), bold, code spans. Everything else is a paragraph;
    HTML in the source is text (the docs are read on the console, and
    `<file>` means a file)."""
    out = []
    lines = text.split("\n")
    i, n = 0, len(lines)
    para = []

    def flush():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para), base))
            del para[:]

    while i < n:
        line = lines[i]
        if line.startswith(FENCE):
            flush()
            j = i + 1
            block = []
            while j < n and not lines[j].startswith(FENCE):
                block.append(lines[j])
                j += 1
            out.append("<pre>%s</pre>" % html.escape("\n".join(block), quote=False))
            i = j + 1
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        m = HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, inline(m.group(2), base), level))
            i += 1
            continue
        if line.startswith("<img ") and "banner" in line:     # the README's banner: the page has one
            i += 1
            continue
        if line.startswith("|"):
            flush()
            rows = []
            while i < n and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            head, body = rows[0], rows[1:]
            out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
                "".join("<th>%s</th>" % inline(c, base) for c in head),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c, base) for c in r) for r in body)))
            continue
        m = ITEM_RE.match(line)
        if m and not m.group(1):
            flush()
            tag = "ol" if m.group(2)[0].isdigit() else "ul"
            items = []          # [text, [subitems]]
            while i < n:
                m = ITEM_RE.match(lines[i])
                if m and not m.group(1):
                    items.append([m.group(3), []])
                elif m and items:
                    items[-1][1].append(m.group(3))
                elif lines[i].startswith(" ") and items:
                    items[-1][0] += " " + lines[i].strip()
                else:
                    break
                i += 1
            li = []
            for text_, subs in items:
                sub = "<ul>%s</ul>" % "".join("<li>%s</li>" % inline(s, base) for s in subs) if subs else ""
                li.append("<li>%s%s</li>" % (inline(text_, base), sub))
            out.append("<%s>%s</%s>" % (tag, "".join(li), tag))
            continue
        para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


# --- the pages --------------------------------------------------------------

def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def unreleased(text, ver):
    """The CHANGELOG's top section is written before its tag (CLAUDE.md,
    Releasing), so a `## vX.Y` above the newest tag is work not yet
    released: the page says so in the heading, and the sign line (the
    newest tag) and the changelog never disagree."""
    def key(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return ()
    cur = key(ver)
    if not cur:
        return text
    return re.sub(r"^## v(\d+\.\d+)$",
                  lambda m: m.group(0) + (" (unreleased)" if key(m.group(1)) > cur else ""),
                  text, flags=re.M)


def models_page(base):
    """The one list as spark's own parser reads it (config.model_tables),
    the user's file left out: this is the repository's page. One table:
    model, file, RAM, license, tested; the tested rows under an open
    license are the ones `auto` picks."""
    rows = [r for r in config.model_tables(ROOT) if r[6] != "user"]
    h = ["<p class=\"cmd\"><span class=\"p\">~ &gt; </span>spark model list<span class=\"k\"> -- %d models, one list</span></p>" % len(rows),
         "<table><thead><tr><th>model</th><th class=\"r\">file</th><th class=\"r\">RAM</th><th>license</th><th>tested</th></tr></thead><tbody>"]
    for r in rows:
        name, fname, url, nbytes, sha, ram, src, tested, lic, note = r
        lic_name, lic_url = (lic.split() + [""])[:2]
        lic_html = '<a href="%s">%s</a>' % (html.escape(lic_url, quote=True), html.escape(lic_name.replace("-", " "))) if lic_url else html.escape(lic_name)
        h.append("<tr><td><a href=\"%s\">%s</a></td><td class=\"r\">%.1f GB</td><td class=\"r\">%d GB</td><td>%s</td><td>%s</td></tr>"
                 % (html.escape(url, quote=True), html.escape(name), int(nbytes) / 2**30, int(ram),
                    lic_html, "yes" if tested else ""))
    h.append("</tbody></table>")
    h.append("<p class=\"hint\"><code>spark model NAME</code> serves one; <code>spark ember NAME</code> adds a second, for conversations. "
             "<code>auto</code> picks among the rows tested on the line under Apache-2.0 or MIT; any other license is shown and asked about before the download. "
             "Every file is sha256-verified. Your own rows: <code>spark model add URL --license</code>. A row is a pull request: CONTRIBUTING.md.</p>")
    return "<section class=\"doc\">%s</section>" % "\n".join(inline_hints(b, base) for b in h)


def inline_hints(s, base):
    """Doc names inside the hand-written hints link like everywhere else."""
    return DOC_RE.sub(lambda m: '<a href="%s%s">%s</a>' % (base, DOC_LINKS[m.group(1)], m.group(1)), s)


def nav_html(here, base):
    items = [("", "spark")] + [(slug + "/", title) for slug, title, _, _ in PAGES]
    parts = []
    for href, title in items:
        cls = ' class="here"' if href.rstrip("/") == here else ""
        parts.append('<a%s href="%s%s">%s</a>' % (cls, base, href, title))
    parts.append('<a href="https://github.com/forgewright-ai/spark">github</a>')
    return " . ".join(parts)


def page(template, slug, title, body, base, ver):
    return (template.replace("{{TITLE}}", html.escape(title))
            .replace("{{NAV}}", nav_html(slug, base))
            .replace("{{BODY}}", body)
            .replace("{{VERSION}}", html.escape(ver))
            .replace("{{RELEASE}}", RELEASES + ("/tag/v" + ver if re.match(r"^\d+\.\d+$", ver) else ""))
            .replace("{{SLUG}}", slug + "/" if slug else "")
            .replace("{{BASE}}", base))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "dist")
    template = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    ver = version()
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    for f in ("favicon.svg", "og.png", "CNAME"):
        shutil.copy(os.path.join(HERE, f), out)
    shutil.copy(os.path.join(ROOT, "assets", "banner.svg"), out)
    index = read(os.path.join(HERE, "index.html"))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page(template, "", "spark -- your own AI, on your own machine, at no cost", index, "", ver))
    for slug, title, source, kind in PAGES:
        base = "../"
        if kind == "md":
            text = read(source)
            if source == "CHANGELOG.md":
                text = unreleased(text, ver)
            body = '<section class="doc">%s</section>' % markdown(text, base)
        elif kind == "text":
            body = '<section class="doc"><pre>%s</pre></section>' % html.escape(read(source).rstrip("\n"), quote=False)
        else:
            body = models_page(base)
        os.makedirs(os.path.join(out, slug))
        with open(os.path.join(out, slug, "index.html"), "w", encoding="utf-8") as f:
            f.write(page(template, slug, "spark . " + title, body, base, ver))
    print("%s: index + %d pages, spark %s" % (os.path.relpath(out, os.getcwd()), len(PAGES), ver))


if __name__ == "__main__":
    main()
