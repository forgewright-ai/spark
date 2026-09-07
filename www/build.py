#!/usr/bin/env python3
# www/build.py -- spark's page, spark.forgewright.ai, rendered from the
# repository's own files into www/dist/: the index is the front, an
# onboarding page in three stages (the OS, the one line, spark apps) whose
# every command is a line of INSTALL.md or the README (tests/site_test.py
# checks); every other page IS a doc (INSTALL.md,
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
    new user there), so the sign line and the install agree."""
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

def slug_id(heading_html, seen):
    """A heading's id, from its own words: the table of contents and any
    outside link can point at a section."""
    s = re.sub(r"<[^>]+>", "", heading_html)
    s = re.sub(r"&[a-z]+;", " ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "section"
    n = seen.get(s, 0) + 1
    seen[s] = n
    return s if n == 1 else "%s-%d" % (s, n)


def markdown(text, base):
    """The subset the docs use: # to ###, paragraphs, fenced code, pipe
    tables, bullet and numbered lists (one nesting level, continuation
    lines indented), bold, code spans. Everything else is a paragraph;
    HTML in the source is text (the docs are read on the console, and
    `<file>` means a file). Headings carry an id from their own words."""
    out = []
    lines = text.split("\n")
    i, n = 0, len(lines)
    para = []
    seen = {}

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
            h = inline(m.group(2), base)
            out.append('<h%d id="%s">%s</h%d>' % (level, slug_id(h, seen), h, level))
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
            items = []          # per item, parts in order: ("t", text) ("s", [subitems]) ("h", html)
            while i < n:
                cur = lines[i]
                strip = cur.strip()
                m = ITEM_RE.match(cur)
                if m and not m.group(1):
                    items.append([["t", m.group(3)]])
                elif m and items:
                    if items[-1][-1][0] == "s":
                        items[-1][-1][1].append(m.group(3))
                    else:
                        items[-1].append(["s", [m.group(3)]])
                elif strip.startswith(FENCE) and cur.startswith(" ") and items:
                    # a fenced block indented inside the item (the docs' step
                    # by step voice: a code block per numbered step)
                    ind = len(cur) - len(cur.lstrip())
                    j = i + 1
                    block = []
                    while j < n and not lines[j].strip().startswith(FENCE):
                        block.append(lines[j][ind:] if not lines[j][:ind].strip() else lines[j].strip())
                        j += 1
                    items[-1].append(["h", "<pre>%s</pre>" % html.escape("\n".join(block), quote=False)])
                    i = j + 1
                    continue
                elif not strip and items and i + 1 < n and (
                        ITEM_RE.match(lines[i + 1]) or lines[i + 1].startswith(" ")) and lines[i + 1].strip():
                    pass    # a blank inside the list: the item or the list goes on
                elif cur.startswith(" ") and strip and items:
                    if items[-1][-1][0] == "t":
                        items[-1][-1][1] += " " + strip
                    else:
                        items[-1].append(["t", strip])
                else:
                    break
                i += 1
            li = []
            for parts in items:
                h = []
                for kind, val in parts:
                    if kind == "t":
                        h.append(inline(val, base))
                    elif kind == "s":
                        h.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(x, base) for x in val))
                    else:
                        h.append(val)
                li.append("<li>%s</li>" % "".join(h))
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


def toc(body):
    """A long doc gets a small table of contents from its h2 ids (three or
    more). An aside, not a nav: the site nav stays the page's first <nav>
    (site_test reads it there)."""
    hs = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    if len(hs) < 3:
        return ""
    li = "".join('<li><a href="#%s">%s</a></li>' % (hid, re.sub(r"<[^>]+>", "", t))
                 for hid, t in hs)
    return '<aside class="toc"><p>on this page</p><ul>%s</ul></aside>' % li


# the header nav keeps to what a new user reaches for; the rest is the footer's
NAV = ["install", "cheatsheet", "models", "changelog"]


# the octocat, one path (Simple Icons, CC0; named in CREDITS.md)
GITHUB_PATH = "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"



def s_mark():
    """The spark S for the footer: the banner's first eight columns (the
    letter), transparent ground, one svg per theme -- cut from the same
    banner files the header uses, never drawn twice."""
    out = []
    for fname, cls in (("banner.svg", "s b-dark"), ("banner-light.svg", "s b-light")):
        svg = open(os.path.join(ROOT, "assets", fname), encoding="utf-8").read()
        rects = [r for r in re.findall(r'<rect [^>]+/>', svg)
                 if float(re.search(r'x="([0-9.]+)"', r).group(1)) < 80]
        out.append('<svg class="%s" viewBox="0 0 80 108" aria-hidden="true">%s</svg>'
                   % (cls, "".join(rects)))
    return "".join(out)


def nav_html(here, base):
    items = [("", "spark")] + [(slug + "/", slug) for slug in NAV]
    parts = []
    for href, title in items:
        cls = ' class="here"' if href.rstrip("/") == here else ""
        parts.append('<a%s href="%s%s">%s</a>' % (cls, base, href, title))
    parts.append('<a class="gh" href="https://github.com/forgewright-ai/spark">'
                 '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="%s"/></svg>github</a>' % GITHUB_PATH)
    return "\n".join(parts)


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
    template = template.replace("{{SMARK}}", s_mark())
    ver = version()
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    for f in ("favicon.svg", "og.png", "CNAME"):
        shutil.copy(os.path.join(HERE, f), out)
    shutil.copy(os.path.join(ROOT, "assets", "banner.svg"), out)
    shutil.copy(os.path.join(ROOT, "assets", "banner-light.svg"), out)
    index = read(os.path.join(HERE, "index.html"))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page(template, "", "spark -- own your AI", index, "", ver))
    for slug, title, source, kind in PAGES:
        base = "../"
        if kind == "md":
            text = read(source)
            if source == "CHANGELOG.md":
                text = unreleased(text, ver)
            rendered = markdown(text, base)
            body = toc(rendered) + '<section class="doc">%s</section>' % rendered
        elif kind == "text":
            body = '<section class="doc"><pre>%s</pre></section>' % html.escape(read(source).rstrip("\n"), quote=False)
        else:
            body = models_page(base)
        src = source or "models.env"
        body += ('<p class="hint src">source: <a href="https://github.com/'
                 'forgewright-ai/spark/blob/main/%s">%s</a> on GitHub -- this page '
                 'is that file, rendered on every push</p>' % (src, src))
        os.makedirs(os.path.join(out, slug))
        with open(os.path.join(out, slug, "index.html"), "w", encoding="utf-8") as f:
            f.write(page(template, slug, "spark . " + title, body, base, ver))
    print("%s: index + %d pages, spark %s" % (os.path.relpath(out, os.getcwd()), len(PAGES), ver))


if __name__ == "__main__":
    main()
