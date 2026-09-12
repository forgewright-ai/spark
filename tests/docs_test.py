#!/usr/bin/env python3
# docs_test.py -- the docs say what the tree holds. Every fact below is
# derived from the tree and looked up in the doc that states it, so a
# palette, a model row or a check row cannot land without its credit or
# its count following: every themes/*.env upstream is in CREDITS.md; every
# model row's license upstream is in CREDITS.md; the check-row count the
# docs state is the count in check.py; the model count they state is the
# count in models.env; every page www/build.py renders has its source
# file; no doc names the lists that are gone; the docs a new user reads
# speak two nouns (spark, spark apps) and no doc names what is private.
# Hermetic, stdlib, fast.
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
from spark import config  # noqa: E402

fails = []
# the docs a new user reads (the voice checks below), and every doc
CUSTOMER_DOCS = ("README.md", "INSTALL.md", "CHEATSHEET.txt", "www/index.html")
ALL_DOCS = ("README.md", "INSTALL.md", "CLAUDE.md", "CHEATSHEET.txt", "CREDITS.md", "CONTRIBUTING.md",
            "AGENTS.md", "ROADMAP.md", "CHANGELOG.md", "site.env.example", "www/index.html")


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
    # the package families: every distro/<id>.env has the same eight keys
    # (contract 3), and every package it names is credited
    from spark import packages
    for f in sorted(os.listdir(os.path.join(ROOT, "distro"))):
        if not f.endswith(".env"):
            continue
        t = config.parse_env(os.path.join(ROOT, "distro", f))
        check(tuple(sorted(t)) == tuple(sorted(packages.KEYS)), "distro/%s: exactly the keys %s" % (f, " ".join(packages.KEYS)))
        for g in packages.GROUPS:
            for name in t.get(g, "").split():
                check(re.search(r"(?m)^- %s -- " % re.escape(name), credits) is not None, "CREDITS.md names %s (distro/%s %s)" % (name, f, g))
        # the family's name in the docs is the file's PM_TARGET, verbatim
        for doc in ("README.md", "INSTALL.md"):
            check(t.get("PM_TARGET", "") in read(doc), "%s names %s (distro/%s PM_TARGET)" % (doc, t.get("PM_TARGET", "?"), f))
    # counts the docs state
    n_rows = sum(1 for line in read(os.path.join("lib", "spark", "check.py")).split("\n") if line.startswith("@row"))
    for doc in ("CLAUDE.md", "INSTALL.md"):
        for m in re.finditer(r"spark check`?\s+(?:has )?(\d+) rows", read(doc)):
            check(int(m.group(1)) == n_rows, "%s: '%s' is check.py's count (%d)" % (doc, m.group(0), n_rows))
    # the split by category CLAUDE.md states ("12 SOFTWARE, 17 CAPABILITY, 9 NONFUNCTIONAL")
    src_rows = read(os.path.join("lib", "spark", "check.py"))
    for cat in ("SOFTWARE", "CAPABILITY", "NONFUNCTIONAL"):
        n_cat = len(re.findall(r'^@row\("%s"' % cat, src_rows, re.M))
        m = re.search(r"(\d+)\s+%s" % cat, read("CLAUDE.md"))
        check(m is not None and int(m.group(1)) == n_cat, "CLAUDE.md: %d %s rows (check.py says %d)" % (int(m.group(1)) if m else -1, cat, n_cat))
    # the chaos scenarios: a count a doc spells out is chaos.py's own
    n_sc = sum(1 for line in read(os.path.join("lib", "spark", "chaos.py")).split("\n")
               if line.startswith("@scenario"))
    spelled = "zero one two three four five six seven eight nine ten eleven twelve".split()
    if n_sc < len(spelled):
        rx = re.compile(r"\b(%s) (?:failures|scenarios)\b" % "|".join(spelled), re.I)
        for doc in ("ROADMAP.md", "CHANGELOG.md", "README.md", "INSTALL.md", "CLAUDE.md", "AGENTS.md"):
            for m in rx.finditer(read(doc)):
                check(m.group(1).lower() == spelled[n_sc],
                      "%s: '%s' is chaos.py's count (%s)" % (doc, m.group(0), spelled[n_sc]))
    # a contract written down and not built says so in three places: its
    # module, the roadmap and CLAUDE.md. Check the claims, not the prose --
    # and check that nothing quietly started dispatching to it
    verbs = read(os.path.join("bin", "spark"))
    roadmap, claude = read("ROADMAP.md"), read("CLAUDE.md")
    reserved = 0
    for f in sorted(os.listdir(os.path.join("lib", "spark"))):
        head = read(os.path.join("lib", "spark", f))[:600] if f.endswith(".py") else ""
        if "NOT BUILT" not in head:
            continue
        reserved += 1
        name = f[:-3]
        m = re.search(r"contract (\d+)", head)
        n = m.group(1) if m else "?"
        check('"%s":' % name not in verbs,
              "bin/spark does not dispatch %s (contract %s is not built)" % (name, n))
        check(re.search(r"(?m)^## Contract %s: spark %s$" % (n, name), roadmap) is not None,
              "ROADMAP.md has '## Contract %s: spark %s'" % (n, name))
        check(re.search(r"(?m)^%s\. `spark %s` -- reserved, not built" % (n, name), claude) is not None,
              "CLAUDE.md reserves contract %s for spark %s" % (n, name))
    # reserved may be zero once the last one is built; the loop still guards
    # any that remain (a module marked NOT BUILT that quietly gets dispatched)
    # contract 8: a signed line is `spark <verb> -- <one line>`, and the
    # verb it names has to be one that exists. Renaming a verb leaves these
    # behind -- `spark stop -- stopped` outlived `spark stop` by a whole
    # release -- and nothing else looks at them.
    known = set(re.findall(r'"([a-z-]+)": \("', read(os.path.join("bin", "spark"))))
    stale = []
    libdir = os.path.join(ROOT, "lib", "spark")
    for f in sorted(os.listdir(libdir)):
        if not f.endswith(".py"):
            continue
        for m in re.finditer(r'"%s ([a-z]+(?: [a-z]+)?) --[ "]', read(os.path.join("lib", "spark", f))):
            if m.group(1).split()[0] not in known:
                stale.append("%s: '%s'" % (f, m.group(1)))
    check(not stale, "every signed line names a verb that exists%s"
          % ("" if not stale else " (found %s)" % ", ".join(stale[:3])))
    # the roadmap starts where the changelog's top section is
    top = re.search(r"^## v(\d+\.\d+)", read("CHANGELOG.md"), re.M).group(1)
    m = re.search(r"What comes after v(\d+\.\d+)", read("ROADMAP.md"))
    check(m is not None and m.group(1) == top, "ROADMAP.md: 'What comes after v%s' names CHANGELOG.md's top section" % top)
    # the gated row lists: CLAUDE.md states their counts, and names the
    # client's rows one by one
    src = read(os.path.join("lib", "spark", "check.py"))
    claude = read("CLAUDE.md")
    named = {}
    for const in ("WSL_ROWS", "ARCH_ROWS", "CLIENT_ROWS"):
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
    pages = re.findall(r'\("([a-z-]+)", "([a-z -]+)", "([A-Za-z0-9./_-]+)", "(?:md|text)"\)', build)
    check(len(pages) >= 6, "www/build.py: PAGES parsed (%d doc pages)" % len(pages))
    for _slug, _title, src in pages:
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
    # the customer-facing docs speak two nouns, spark and spark apps: the
    # names the code keeps (the FORGE, an ember, the brain, the seed) stay
    # in the maintainer's docs; no doc calls the shell layer frozen or
    # deprecated, and nobody is called a stranger
    taxonomy = r"\b(the|a) forge\b|\b(the|an) ember\b|\bthe brain\b|\bsmart (app|apps|os)\b|\bthe seed\b"
    for doc in CUSTOMER_DOCS:
        m = re.search(taxonomy, read(doc), re.I)
        check(m is None, "%s: two nouns, spark and spark apps%s" % (doc, " (found '%s')" % m.group(0) if m else ""))
    for doc in ALL_DOCS:
        m = re.search(r"\b(frozen|deprecated|strangers?)\b", read(doc), re.I)
        check(m is None, "%s: no '%s'" % (doc, m.group(0) if m else "frozen/deprecated/stranger"))
    # what is private is named nowhere in the tree's docs
    for doc in ALL_DOCS:
        check(not re.search(r"\bfactor(y|ies)\b", read(doc), re.I), "%s: no factory" % doc)
    # APPS.md is where the apps live now: the customer docs a new user reads
    # are the core, and the apps and the shell layer are beside it, in their
    # own files, outside the landing rule. Every app APPS.md names still has
    # to be credited and on the page front -- those two are not optional.
    apps = sorted(set(re.findall(r"github\.com/forgewright-ai/(spark-[a-z0-9]+)", read("APPS.md"))))
    check(bool(apps), "APPS.md names at least one spark app repo")
    for app in apps:
        for doc in ("CREDITS.md", "www/index.html"):
            check(app in read(doc), "%s names %s (APPS.md does)" % (doc, app))
    # and the two documents beside the core exist and say they are not
    # tied to a release, so nobody files them back under the landing rule
    for doc in ("APPS.md", "SHELL.md"):
        check("not tied to a spark release" in read(doc), "%s says it is not release-gated" % doc)
    # the lists that are gone stay gone
    for doc in ("README.md", "INSTALL.md", "CLAUDE.md", "CHEATSHEET.txt", "CREDITS.md", "CONTRIBUTING.md",
                "AGENTS.md", "ROADMAP.md", "site.env.example"):
        check(not re.search(r"embers\.env|community\.env|\bcurated\b|PKG_QA|PKG_EDITOR|micro-aspell|\bbootconfig\b|SITE_SHELL|PKG_SHELL|PKG_CLI", read(doc)),
              "%s: no retired list word" % doc)
    # the page and the FORGE page share the ember palette: www/template.html's
    # tokens mirror lib/spark/forge/spark.css, dark and light alike
    def css_tokens(text, anchor):
        i = text.index(anchor)
        block = text[i:text.index("}", i)]
        return {k: v.strip() for k, v in re.findall(r"--([a-z0-9-]+)\s*:\s*([^;]+);", block)}
    tpl, forge_css = read("www/template.html"), read("lib/spark/forge/spark.css")
    t_dark = css_tokens(tpl, ":root {")
    t_light = css_tokens(tpl, ':root[data-theme="light"]')
    c_dark = css_tokens(forge_css, ":root {")
    c_light = css_tokens(forge_css[forge_css.index("@media (prefers-color-scheme: light)"):], ":root")
    for a, b in (("ground", "bg"), ("ink", "fg"), ("rule", "line"), ("panel", "tint"),
                 ("y2", "accent"), ("accent", "accent"), ("muted", "muted")):
        check(t_dark.get(a) == c_dark.get(b), "template dark --%s is spark.css --%s (%s vs %s)"
              % (a, b, t_dark.get(a), c_dark.get(b)))
    for a, b in (("ground", "bg"), ("ink", "fg"), ("rule", "line"), ("panel", "tint"),
                 ("accent", "accent"), ("muted", "muted-text")):
        check(t_light.get(a) == c_light.get(b), "template light --%s is spark.css light --%s (%s vs %s)"
              % (a, b, t_light.get(a), c_light.get(b)))
    if fails:
        print("docs_test: %d failed" % len(fails))
        return 1
    print("docs_test: all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
