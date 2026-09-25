#!/usr/bin/env python3
# docs_test.py -- the docs say what the tree holds. Every fact below is
# derived from the tree and looked up in the doc that states it, so a
# palette, a model row or a check row cannot land without its credit or
# its count following: every themes/*.env upstream is in CREDITS.md; every
# model row's license upstream is in CREDITS.md; the check-row count the
# docs state is the count in check.py; the model count they state is the
# count in models.env; every docs/X a doc names exists, every document in
# docs/ is pointed to and the root holds four; no doc names the lists that
# are gone;
# the docs a new user reads speak two nouns (spark, spark apps) and no
# doc names what is private; the voice's mechanical half (docs/CONTRIBUTING.md
# "## Voice") holds over every doc, and the two nouns hold in `spark help`
# and every usage text too.
# Hermetic, stdlib, fast.
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
from spark import config  # noqa: E402

fails = []
# the four documents at the root; the core docs that live in docs/ since
# v1.38 (still release-gated by the landing rule); the documents beside the
# core (docs/, not tied to a release); what docs/ holds, exactly; the docs a
# new user reads (the voice checks below); and every doc
ROOT_DOCS = ("README.md", "CREDITS.md", "CLAUDE.md", "AGENTS.md")
CORE_IN_DOCS = ("INSTALL.md", "CHEATSHEET.txt", "CHANGELOG.md", "ROADMAP.md", "CONTRIBUTING.md")
BESIDE = ("TOUR.md", "APPS.md", "IDEAS.md", "TROUBLESHOOTING.md")
DOCS_DIR = CORE_IN_DOCS + BESIDE
CUSTOMER_DOCS = ("README.md", "docs/INSTALL.md", "docs/CHEATSHEET.txt", "docs/TOUR.md", "docs/TROUBLESHOOTING.md")
ALL_DOCS = ROOT_DOCS + tuple("docs/" + f for f in DOCS_DIR) + ("site.env.example",)
# the voice (docs/CONTRIBUTING.md "## Voice"), its mechanical half: an
# ALL-CAPS word of four or more letters is an acronym or a constant, never
# emphasis. The acronyms a doc may keep are listed here; every KEY= name in
# the two env examples and every NAME_LIKE_THIS constant is allowed too
CAPS_OK = {
    "ASCII", "ARCH", "CPU", "GPU", "RAM", "LAN", "WLAN", "HTTP", "HTTPS", "JSON", "URL", "GGUF",
    "UKI", "WSL", "SSH", "TLS", "SGR", "SBOM", "API", "TODO", "KEY", "NAME", "WORDS", "PATH",
    "FILE", "HOME", "ADDR", "PORT", "USER", "HOST", "MODEL", "THEME", "SITE", "SPARK", "XDG",
    "PID", "EOF", "UTF", "POSIX", "GRUB", "EFI", "DRM", "AMD", "NVIDIA", "CUDA", "OK", "FAIL",
    "WARN", "NA", "TTY", "VT", "QR", "PR", "CI", "ID", "OS", "LICENSE", "README", "CREDITS",
    "CLAUDE", "AGENTS", "INSTALL", "CHEATSHEET", "CHANGELOG", "ROADMAP", "CONTRIBUTING", "TOUR",
    "APPS", "IDEAS", "TROUBLESHOOTING", "DOCUMENTS", "MIT", "ISC", "BSD", "CC", "GPL", "LGPL",
    "MPL", "RFC", "ChaCha20", "AEAD", "HMAC", "CSRF", "SSE", "MB", "GB", "KB", "TB", "DNS", "IP",
    "IPV4", "IPV6", "RSA", "ED25519", "SHA256", "ROUTES", "SENDS", "MODES", "PREFERRED", "VERBS",
    "USAGE", "KNOWN", "GONE", "ALPM", "WIFI",
    # found in the docs at v1.49: real acronyms and names
    "APFS", "BIOS", "DHCP", "VRAM", "SIGINT", "SIGTERM", "ENOSPC", "BSSID", "RSSI", "SLAAC", "SSID",
    "HEAD", "POST",
    # what the code prints: the gate's marker, the three row categories
    "NOTICE", "SOFTWARE", "CAPABILITY", "NONFUNCTIONAL",
    # the help's placeholders (spark font FACE SIZE)
    "FACE", "SIZE",
}
# a contraction, any case: the n't family and the pronoun+verb pairs
CONTRACTION = re.compile(
    r"\b\w+n't\b|\bit's\b|\byou'll\b|\bwe're\b|\bthey're\b|\bdon't\b|\bcan't\b"
    r"|\byou're\b|\bwe've\b|\byou've\b|\bthey've\b|\bwe'll\b|\bthey'll\b|\bit'll\b"
    r"|\bthat's\b|\bthere's\b|\bhere's\b|\bwhat's\b|\bwhere's\b|\bwho's\b|\blet's\b"
    r"|\bI'm\b|\bI've\b|\bI'll\b", re.I)
# the names the code keeps: what a new user reads speaks two nouns
TWO_NOUNS = re.compile(r"\b(the|a) forge\b|\b(the|an) ember\b|\bthe brain\b|\bsmart (app|apps|os)\b|\bthe seed\b", re.I)


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


FENCE = re.compile(r"(?ms)^[ \t]*```.*?^[ \t]*```[ \t]*$")
# a code span: a run of backticks closed by the same run (a double run may
# hold a single backtick, as Markdown reads it); it may wrap over a line
# break (prose wraps at 72), never over a blank line
SPAN = re.compile(r"(?<!`)(`+)(?!`)(?:[^`\n]|\n(?!\n)|(?!\1)`)*?\1(?!`)")


def prose(text):
    """The text with its fenced blocks and inline code spans taken out: a
    command, a key or a quoted message is not the writer's prose."""
    return SPAN.sub("", FENCE.sub("", text))


def caps_allowed():
    ok = set(CAPS_OK)
    for f in ("site.env.example", "home/.config/spark/spark.env.example"):
        ok.update(re.findall(r"(?m)^\s*#?\s*([A-Z][A-Z0-9_]*)=", read(f)))
    return ok


def voice():
    """docs/CONTRIBUTING.md "## Voice", the mechanical half over every doc
    but the CHANGELOG (history): every backtick opens or closes a span,
    Wi-Fi and characters spelled out, no contraction, capitals only for
    acronyms -- a fence or a code span is not prose -- and a customer doc
    under 80 columns outside a fence or a table row. Each failure names
    the file and the words."""
    allowed = caps_allowed()
    constant = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]*$")
    for doc in ALL_DOCS:
        if doc == "docs/CHANGELOG.md":
            continue
        # a lone backtick that opens no span and closes none mis-pairs every
        # span after it in its paragraph (Markdown reads it the same way) and
        # hides the words the checks below read: the paragraph (blank line
        # to blank line) is named. A longer unmatched run is literal text.
        odd, at = [], 1
        for para in re.split(r"\n[ \t]*\n", FENCE.sub("", read(doc))):
            if re.search(r"(?<!`)`(?!`)", SPAN.sub("", para)):
                odd.append(at)
            at += para.count("\n") + 2
        check(not odd, "%s: every backtick opens or closes a code span%s"
              % (doc, "" if not odd else " (odd in the paragraph at line %s)" % ", ".join(str(n) for n in odd)))
        text = prose(read(doc))
        caps = text
        if doc == "docs/CHEATSHEET.txt":
            # the card's headers are its column-0 lines, in capitals by the
            # file's own shape (the DOCUMENTS block is pinned above)
            caps = "\n".join(line for line in text.split("\n") if line[:1] in ("", " "))
        check(re.search(r"\bWiFi\b", text) is None, "%s: write Wi-Fi%s"
              % (doc, "" if re.search(r"\bWiFi\b", text) is None else " (found 'WiFi')"))
        check(re.search(r"\bchars\b", text) is None, "%s: write characters%s"
              % (doc, "" if re.search(r"\bchars\b", text) is None else " (found 'chars')"))
        hits = sorted(set(m.group(0) for m in CONTRACTION.finditer(text)))
        check(not hits, "%s: no contraction%s" % (doc, "" if not hits else " (found %s)" % ", ".join("'%s'" % w for w in hits)))
        # a $VARIABLE is code; a NAME_LIKE_THIS is a constant
        hits = sorted(set(w for w in re.findall(r"(?<!\$)\b[A-Z][A-Z0-9_]*\b", caps)
                          if sum(c.isalpha() for c in w) >= 4 and w not in allowed and not constant.match(w)))
        check(not hits, "%s: capitals only for acronyms%s" % (doc, "" if not hits else " (found %s)" % ", ".join(hits)))
    for doc in CUSTOMER_DOCS:
        wide, fence = [], False
        for n, line in enumerate(read(doc).split("\n"), 1):
            if line.strip().startswith("```"):
                fence = not fence
            elif not fence and "|" not in line and len(line) > 80:
                wide.append("%d (%d)" % (n, len(line)))
        check(not wide, "%s: no line over 80 columns outside a fence or a table%s"
              % (doc, "" if not wide else " (line %s)" % ", ".join(wide)))


def help_voice():
    """The two nouns hold in what spark prints too: `spark help` and every
    *USAGE string in lib/spark (lua aside: nobody is told about it)."""
    import importlib
    import subprocess
    p = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "spark"), "help"], capture_output=True, text=True)
    m = TWO_NOUNS.search(p.stdout)
    check(p.returncode == 0 and m is None, "spark help: two nouns, spark and spark apps%s"
          % (" (found '%s')" % m.group(0) if m else "" if p.returncode == 0 else " (exit %d)" % p.returncode))
    for f in sorted(os.listdir(os.path.join(ROOT, "lib", "spark"))):
        if not f.endswith(".py") or f in ("__init__.py", "lua.py"):
            continue
        try:
            mod = importlib.import_module("spark." + f[:-3])
        except Exception as e:  # noqa: BLE001 -- the failure is the finding
            check(False, "lib/spark/%s imports (%s)" % (f, e))
            continue
        for attr in sorted(vars(mod)):
            text = vars(mod)[attr]
            if attr.endswith("USAGE") and isinstance(text, str):
                m = TWO_NOUNS.search(text)
                check(m is None, "lib/spark/%s %s: two nouns, spark and spark apps%s"
                      % (f, attr, " (found '%s')" % m.group(0) if m else ""))


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
        for doc in ("README.md", "docs/INSTALL.md"):
            check(t.get("PM_TARGET", "") in read(doc), "%s names %s (distro/%s PM_TARGET)" % (doc, t.get("PM_TARGET", "?"), f))
    # the SBOM (spark ver --sbom, lib/spark/sbom.py) says what the tree
    # holds: its model set (name + sha256) is config.model_tables()'s and
    # its engine flavours are the ones engine.env pins
    from spark import sbom
    from spark.engine import FLAVOURS
    doc = sbom.build(ROOT)
    got_models = {(c["name"], c["hashes"][0]["content"]) for c in doc["components"] if c["type"] == "data"}
    want_models = {(r[0], r[4]) for r in config.model_tables(ROOT)}
    pins = config.parse_env(os.path.join(ROOT, "engine.env"))
    got_flav = sorted(p["value"] for c in doc["components"] if c["name"] == "llama.cpp"
                      for p in c["properties"] if p["name"] == "spark:flavour")
    want_flav = sorted(name for name, key in FLAVOURS.values() if key in pins)
    check(got_models == want_models and got_flav == want_flav,
          "the SBOM's models are config.model_tables()'s and its flavours engine.env's (%d models, %d flavours)"
          % (len(want_models), len(want_flav)))
    # what leaves this machine: every sender in persona.SENDS is named in
    # the README's disclosure section -- a new sender fails here until it
    # is disclosed
    from spark import persona
    readme = read("README.md")
    m = re.search(r"## What leaves this machine\n(.*?)(?:\n## |\Z)", readme, re.S)
    check(m is not None, "README.md has a 'What leaves this machine' section")
    section = m.group(1) if m else ""
    for kind, _cap in persona.SENDS:
        check(re.search(r"\b%s\b" % re.escape(kind), section) is not None,
              "README.md 'What leaves this machine' names %s (persona.SENDS)" % kind)
    # a sender's row that names a man page (do's excerpt) is disclosed
    # as one: the section says "man page" too
    if any("man page" in cap for _kind, cap in persona.SENDS):
        check("man page" in " ".join(section.split()),
              "README.md 'What leaves this machine' names the man page lines (persona.SENDS)")
    # and what a source has held back before it leaves: every shape in
    # text.SOURCE_SHAPES is named there, so a new shape is disclosed too
    from spark import text as textmod
    folded = " ".join(section.split())
    for what, _pat in textmod.SOURCE_SHAPES:
        check(what in folded,
              "README.md 'What leaves this machine' names '%s' (text.SOURCE_SHAPES)" % what)
    # counts the docs state
    n_rows = sum(1 for line in read(os.path.join("lib", "spark", "check.py")).split("\n") if line.startswith("@row"))
    for doc in ("CLAUDE.md", "docs/INSTALL.md"):
        for m in re.finditer(r"spark check`?\s+(?:has )?(\d+) rows", read(doc)):
            check(int(m.group(1)) == n_rows, "%s: '%s' is check.py's count (%d)" % (doc, m.group(0), n_rows))
    for m in re.finditer(r"spark check` answers (\d+)", read("docs/IDEAS.md")):
        check(int(m.group(1)) == n_rows, "docs/IDEAS.md: '%s' is check.py's count (%d)" % (m.group(0), n_rows))
    # the threat model: the section exists and names the one remedy
    inst = read("docs/INSTALL.md")
    m = re.search(r"## 8\. What an attacker can and cannot do\n(.*?)(?:\n## )", inst, re.S)
    check(m is not None, "docs/INSTALL.md has the threat model section (8)")
    check(m is not None and "spark user token" in m.group(1) and "--new" in m.group(1),
          "the threat model names spark user token --new")
    # contract 3: every MODEL_*_GROUND in models.env has the audition's
    # shape, "<kept>/<run> <YYYY-MM-DD>" (config refuses others at parse;
    # this keeps the file honest without running spark)
    for m in re.finditer(r'(?m)^(MODEL_[A-Z_0-9]+_GROUND)="?([^"\n]*)"?\s*$', read("models.env")):
        check(re.match(r"^\d+/\d+ \d{4}-\d{2}-\d{2}$", m.group(2)) is not None,
              "models.env: %s is '<kept>/<run> <YYYY-MM-DD>' (got %r)" % (m.group(1), m.group(2)))
    # the split by category CLAUDE.md states ("11 SOFTWARE, 20 CAPABILITY, 9 NONFUNCTIONAL")
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
        for doc in ("docs/ROADMAP.md", "docs/CHANGELOG.md", "README.md", "docs/INSTALL.md", "CLAUDE.md", "AGENTS.md"):
            for m in rx.finditer(read(doc)):
                check(m.group(1).lower() == spelled[n_sc],
                      "%s: '%s' is chaos.py's count (%s)" % (doc, m.group(0), spelled[n_sc]))
    # a contract written down and not built says so in three places: its
    # module, the roadmap and CLAUDE.md. Check the claims, not the prose --
    # and check that nothing quietly started dispatching to it
    verbs = read(os.path.join("bin", "spark"))
    roadmap, claude = read("docs/ROADMAP.md"), read("CLAUDE.md")
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
              "docs/ROADMAP.md has '## Contract %s: spark %s'" % (n, name))
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
    top = re.search(r"^## v(\d+\.\d+)", read("docs/CHANGELOG.md"), re.M).group(1)
    m = re.search(r"What comes after v(\d+\.\d+)", read("docs/ROADMAP.md"))
    check(m is not None and m.group(1) == top, "docs/ROADMAP.md: 'What comes after v%s' names docs/CHANGELOG.md's top section" % top)
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
    for doc in ("README.md", "docs/INSTALL.md"):
        for m in re.finditer(r"(\d+) (models|rows), each with its license", read(doc)):
            check(int(m.group(1)) == n_models, "%s: '%s' is models.env's count (%d)" % (doc, m.group(0), n_models))
    # the CHANGELOG's top section is the newest tag or the one right after it
    # (written before its tag, CLAUDE.md Releasing) -- never further ahead,
    # never behind
    import subprocess
    try:
        tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()[1:]
    except (OSError, subprocess.CalledProcessError):
        tag = ""
    top = re.search(r"^## v(\d+)\.(\d+)$", read("docs/CHANGELOG.md"), re.M)
    if tag and top and re.match(r"^\d+\.\d+$", tag):
        major, minor = int(top.group(1)), int(top.group(2))
        tmaj, tmin = (int(x) for x in tag.split("."))
        check((major, minor) in ((tmaj, tmin), (tmaj, tmin + 1), (tmaj + 1, 0)),
              "docs/CHANGELOG.md: the top section v%d.%d is the newest tag v%s or the next release" % (major, minor, tag))
    # the customer-facing docs speak two nouns, spark and spark apps: the
    # names the code keeps (the FORGE, an ember, the brain, the seed) stay
    # in the maintainer's docs; no doc calls anything frozen or
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
    # docs/APPS.md is where the apps live now: the customer docs a new user
    # reads are the core, and the apps are beside it, in their own file,
    # outside the landing rule. Every app it names
    # still has to be credited -- that one is not optional; the page front
    # checks itself the same way where the page is rendered.
    apps = sorted(set(re.findall(r"github\.com/forgewright-ai/(spark-[a-z0-9]+)", read("docs/APPS.md"))))
    check(bool(apps), "docs/APPS.md names at least one spark app repo")
    for app in apps:
        for doc in ("CREDITS.md",):
            check(app in read(doc), "%s names %s (docs/APPS.md does)" % (doc, app))
    # docs/ holds exactly the nine: the five core docs that moved there with
    # v1.38 and the four beside the core. A beside doc says it is not tied
    # to a release (so nobody files it back under the landing rule); a core
    # doc there does NOT (it is still release-gated); every one is in
    # CLAUDE.md's Layout and is pointed to -- a doc nobody is sent to is dead
    have = sorted(f for f in os.listdir(os.path.join(ROOT, "docs")) if not f.startswith("."))
    check(have == sorted(DOCS_DIR), "docs/ holds exactly %s%s"
          % (", ".join(DOCS_DIR), "" if have == sorted(DOCS_DIR) else " (found %s)" % ", ".join(have)))
    m = re.search(r"## Layout\n\n```\n(.*?)\n```", claude, re.S)
    layout = m.group(1) if m else ""
    pointing = "".join(read(d) for d in ("README.md", "docs/INSTALL.md", "docs/CHEATSHEET.txt", "docs/ROADMAP.md"))
    for name in BESIDE:
        check("This document is not tied to a spark release" in read("docs/" + name), "docs/%s says it is not release-gated" % name)
        check("docs/" + name in pointing, "README, INSTALL, CHEATSHEET or ROADMAP points to docs/%s" % name)
    for name in CORE_IN_DOCS:
        check("This document is not tied to a spark release" not in read("docs/" + name),
              "docs/%s is core (the landing rule): it does not carry the beside-the-core line" % name)
        check("docs/" + name in readme, "README.md points to docs/%s" % name)
    for name in DOCS_DIR:
        check(name in layout, "CLAUDE.md's Layout names docs/%s" % name)
    # every docs/X a doc or the help names exists (the successor of the
    # page-source check; the CHANGELOG is history and may name what moved),
    # and README and the CHEATSHEET send a new user to the same set
    live = tuple(d for d in ALL_DOCS if d != "docs/CHANGELOG.md")
    named = set()
    for doc in live + ("bin/spark",):
        named.update(re.findall(r"docs/([A-Z]+\.(?:md|txt))", read(doc)))
    for name in sorted(named):
        check(name in DOCS_DIR, "docs/%s, which a doc names, exists" % name)
    m = re.search(r"## Documents\n(.*?)(?:\n## |\Z)", readme, re.S)
    in_readme = set(re.findall(r"docs/([A-Z]+\.(?:md|txt))", m.group(1) if m else ""))
    m = re.search(r"^DOCUMENTS[^\n]*\n(.*?)(?:\n\n|\Z)", read("docs/CHEATSHEET.txt"), re.S | re.M)
    in_cheat = set(re.findall(r"docs/([A-Z]+\.(?:md|txt))", m.group(1) if m else ""))
    check(in_readme == set(DOCS_DIR) and in_cheat == set(DOCS_DIR),
          "README's Documents and the CHEATSHEET's DOCUMENTS name every file in docs/ (%s)" % ", ".join(DOCS_DIR))
    # a moved doc is named only by its new path: INSTALL.md, CHEATSHEET.txt,
    # CHANGELOG.md, ROADMAP.md and CONTRIBUTING.md live in docs/ since v1.38,
    # so a bare name (or ~/.spark/CHEATSHEET.txt) is a broken pointer. The
    # CHANGELOG is history; CLAUDE.md's Layout block names files by their
    # bare name under the docs/ entry, as every entry there does
    old = re.compile(r"(?<!docs/)(?<![\w.-])(INSTALL\.md|CHEATSHEET\.txt|CHANGELOG\.md|ROADMAP\.md|CONTRIBUTING\.md)\b")
    scan = list(live) + ["bin/spark"] + sorted(os.path.join("lib", "spark", f) for f in os.listdir(libdir) if f.endswith(".py"))
    for d, _, fs in os.walk(os.path.join(ROOT, "templates")):
        scan += [os.path.relpath(os.path.join(d, f), ROOT) for f in fs]
    for doc in scan:
        text = read(doc)
        if doc == "CLAUDE.md":
            text = text.replace(layout, "")
        m = old.search(text)
        check(m is None, "%s: no old root path%s" % (doc, " (found '%s')" % m.group(0) if m else ""))
    # the root holds only the four (the check that would have caught a
    # stray folder), the page's source is named by no doc but the CHANGELOG,
    # and neither it nor the old folder exists
    loose = sorted(f for f in os.listdir(ROOT) if f.endswith((".md", ".txt")) and f not in ROOT_DOCS)
    check(not loose, "the root holds only README.md, CREDITS.md, CLAUDE.md, AGENTS.md%s"
          % ("" if not loose else " (found %s)" % ", ".join(loose)))
    stale = [d for d in live if "www/" in read(d)]
    check(not stale, "www/ is gone%s" % ("" if not stale else " (named in %s)" % ", ".join(stale)))
    for gone in ("www", "user guide"):
        check(not os.path.exists(os.path.join(ROOT, gone)), "%s does not exist" % gone)
    # the lists that are gone stay gone
    for doc in ROOT_DOCS + ("docs/INSTALL.md", "docs/CHEATSHEET.txt", "docs/CONTRIBUTING.md", "docs/ROADMAP.md", "site.env.example"):
        check(not re.search(r"embers\.env|community\.env|\bcurated\b|PKG_QA|PKG_EDITOR|micro-aspell|\bbootconfig\b|SITE_SHELL|PKG_SHELL|PKG_CLI", read(doc)),
              "%s: no retired list word" % doc)
    # v1.48: the core knows nothing of a shell layer, and neither does a
    # doc -- the generic contracts (theme.env, the console, the three
    # SPARK_*_SGR variables, spark bar line) are described as generic; the
    # CHANGELOG alone keeps the history
    for doc in ALL_DOCS:
        if doc == "docs/CHANGELOG.md":
            continue
        m = re.search(r"spark-shell|(?i:shell layer)|SHELL\.md|THEME_BTOP", read(doc))
        check(m is None, "%s: no shell layer%s" % (doc, " (found '%s')" % m.group(0) if m else ""))
    # contract 9: the route table CLAUDE.md prints is forgeserve.ROUTES,
    # entry for entry -- a route added without its row, or a row without
    # its route, fails here (the block is METHOD  PATH  ROLE lines)
    from spark import forgeserve
    m = re.search(r"```\n((?:[ ]*(?:GET|POST|DELETE)\s+\S+\s+(?:none|user|admin)\n)+)[ ]*```", claude)
    check(m is not None, "CLAUDE.md contract 9 prints the route table (METHOD  PATH  ROLE)")
    doc_routes = {}
    for line in (m.group(1).split("\n") if m else []):
        if line.strip():
            method, path, role = line.split()
            doc_routes[(method, path)] = role
    off = sorted(k for k in set(doc_routes) | set(forgeserve.ROUTES) if doc_routes.get(k) != forgeserve.ROUTES.get(k))
    check(not off, "CLAUDE.md's route table is forgeserve.ROUTES, entry for entry%s"
          % ("" if not off else " (differs at %s)" % ", ".join("%s %s" % k for k in off[:3])))
    # the voice's mechanical half, and the two nouns in what spark prints
    voice()
    help_voice()
    if fails:
        print("docs_test: %d failed" % len(fails))
        return 1
    print("docs_test: all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
