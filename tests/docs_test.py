#!/usr/bin/env python3
# docs_test.py -- the docs say what the tree holds. Every fact below is
# derived from the tree and looked up in the doc that states it, so a
# package, a model row or a check row cannot land without its credit or
# its count following: every package a distro/<id>.env names and every
# model row's license upstream is in CREDITS.md; the check-row count the
# docs state is the count in check.py; the model count they state is the
# count in models.env; every docs/X a doc names exists, every document in
# docs/ is pointed to and the root holds four; no doc names the lists that
# are gone; the living prompt's verbs, keys and temperaments are in the
# cheatsheet and INSTALL, and nothing calls awaken minting;
# no doc but the CHANGELOG and no line of `spark help` names a spelling
# v1.64 folded into `spark serve` or `spark model --chat`, and help's
# server group is in the cheatsheet; every chat command
# (forge.SLASH_VERBS) is in the cheatsheet and INSTALL's chat table;
# the docs a new user reads speak two nouns (spark, spark apps) and no
# doc names what is private; spark voice (v1.70): every voice.env
# licence upstream is in CREDITS.md and the SBOM holds voice.env's pins,
# every word of `spark voice` is in the cheatsheet, every key the two
# widgets bind (Esc k, Esc v, ...) is in the cheatsheet and INSTALL, and
# every SPARK_VOICE* key is a row of INSTALL's key table, and the sizes
# INSTALL, the cheatsheet and the CHANGELOG state are voice.env's; the voice's
# mechanical half (docs/CONTRIBUTING.md
# "## Voice") holds over every doc, its two measures included (a sentence
# of 30 words at most, prose within 72 columns), and the two nouns hold
# in `spark help` and every usage text too; a plain voice and the face
# (v1.80): no doc but the CHANGELOG names a removed voice character,
# docs/REFERENCE.md's voice file entry holds the keys voice.mint writes, both
# widgets read FACE_IDLE, and grammar rule 6 names every kind in
# look.PROGRESS; the prompt warns (v1.82): every flag of `spark check`
# completes, the docs name `spark check --history`, the state files and
# state/alert, and bootstrap's knowledge row asks before it builds;
# one test list (v1.79): every
# tests/ file is run by tests/gate.sh or named in NOT_IN_GATE, and the
# hooks and the workflows name no test file themselves.
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
# lib/spark/forge/fonts/, each file by the sha256 of upstream's bytes
FONTS = {"atkinson-hyperlegible-next-latin-ext.woff2": "7dae0c6c66af1aec82e096186aeb1f0e6fa36ab8061ed65422f2b7daf4dd93f3",
         "atkinson-hyperlegible-next-latin.woff2": "18b2a1a39a2fa298b0ba5390aca68462669826c90925656f1c1f6796e0e1bbaf",
         "monaspace-neon-400.woff2": "6b6980f24d115e98e96b1a5d06a5a7fe6454de9b216d479a7e6923c0456a5f41",
         "monaspace-neon-700.woff2": "37f1c50c462e51d871d52c36b190628e94c379c7157e07e04e1e2f943f07f54f",
         "monaspace-xenon-400.woff2": "eb34d971e2bf956230ba2e5bd621af7310d4c739057ae7df7b8a38ca95b03cf6",
         "monaspace-xenon-700.woff2": "c156f532e8ca566d5f5e6854cac1fdb1f614127b2f8b5d6a6d62aa7b29282c14"}
CORE_IN_DOCS = ("INSTALL.md", "CHEATSHEET.txt", "CHANGELOG.md", "ROADMAP.md", "CONTRIBUTING.md", "REFERENCE.md")
DOCS_DIR = CORE_IN_DOCS
CUSTOMER_DOCS = ("README.md", "docs/INSTALL.md", "docs/CHEATSHEET.txt")
ALL_DOCS = ROOT_DOCS + tuple("docs/" + f for f in DOCS_DIR) + ("site.env.example",)
# the voice (docs/CONTRIBUTING.md "## Voice"), its mechanical half: an
# ALL-CAPS word of four or more letters is an acronym or a constant, never
# emphasis. The acronyms a doc may keep are listed here; every KEY= name in
# the two env examples and every NAME_LIKE_THIS constant is allowed too
CAPS_OK = {
    "ASCII", "ARCH", "CPU", "GPU", "RAM", "LAN", "WLAN", "HTTP", "HTTPS", "JSON", "URL", "GGUF",
    "UKI", "WSL", "SSH", "TLS", "SGR", "SBOM", "API", "TODO", "KEY", "NAME", "WORDS", "PATH", "CERT",
    "FILE", "HOME", "ADDR", "PORT", "USER", "HOST", "MODEL", "THEME", "SITE", "SPARK", "XDG",
    "PID", "EOF", "UTF", "POSIX", "GRUB", "EFI", "DRM", "AMD", "NVIDIA", "CUDA", "OK", "FAIL",
    "WARN", "NA", "TTY", "VT", "QR", "PR", "CI", "ID", "OS", "LICENSE", "README", "CREDITS",
    "CLAUDE", "AGENTS", "REFERENCE", "INSTALL", "CHEATSHEET", "CHANGELOG", "ROADMAP", "CONTRIBUTING", "TOUR",
    "APPS", "IDEAS", "TROUBLESHOOTING", "DOCUMENTS", "MIT", "ISC", "BSD", "CC", "GPL", "LGPL",
    "MPL", "RFC", "ChaCha20", "AEAD", "HMAC", "CSRF", "SSE", "MB", "GB", "KB", "TB", "DNS", "IP",
    "IPV4", "IPV6", "RSA", "ED25519", "SHA256", "ROUTES", "SENDS", "MODES", "PREFERRED", "VERBS",
    "USAGE", "KNOWN", "GONE", "ALPM", "WIFI",
    # found in the docs at v1.49: real acronyms and names
    "APFS", "BIOS", "DHCP", "VRAM", "SIGINT", "SIGTERM", "ENOSPC", "BSSID", "RSSI", "SLAAC", "SSID",
    "HEAD", "POST",
    # the voice (v1.70): Linux's sound layer
    "ALSA",
    # what the code prints: the gate's marker, the three row categories
    "NOTICE", "SOFTWARE", "CAPABILITY", "NONFUNCTIONAL",
    # contract 16 (v1.90): the placeholders of spark mcp call NAME TOOL and spark steps < TOOLS
    "TOOL", "TOOLS",
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


# the tests/ files tests/gate.sh does not run, each with its reason
NOT_IN_GATE = (
    ("gate.sh", "the gate itself"),
    ("fixtures.py", "test-only host facts, exercised by platform_test.py"),
    ("platform_test.py", "synthetic platform and safety regressions, run by smoke.py"),
    ("land.sh", "the landing command, not a test: land_test.sh proves it"),
    ("tag.sh", "the tagging command, not a test: tag_test.sh proves it"),
    ("audition.py", "needs a live model"),
    ("model_validation.py", "needs pinned local artifacts; bench_smoke.py runs its selftest"),
    ("line_audition.py", "needs a live model; smoke.py runs its selftest"),
    ("forge_probe.py", "asks a live server"),
    ("context_bench.py", "manual synthetic context scaling measurements"),
    ("check_selftest.py", "an entry to spark check --selftest, which the gate runs"),
)
# who may name a test file: nobody but the gate. The hooks and ci.yml
# call tests/gate.sh (and tests/land.sh, the one check "ci.yml passed")
GATE_CALLERS = (".githooks/pre-commit", ".githooks/pre-push", ".githooks/commit-msg",
                ".github/workflows/ci.yml", ".github/workflows/release.yml")


def tests_gated():
    """One test list (v1.79): every tests/*.py and tests/*.sh is on a `run`
    line of tests/gate.sh or in NOT_IN_GATE with its reason, never both;
    the hooks and the workflows name no test file but gate.sh and land.sh,
    and each calls the gate the way the docs say."""
    names = sorted(n for n in os.listdir(os.path.join(ROOT, "tests")) if n.endswith((".py", ".sh")))
    lines = [ln for ln in read("tests/gate.sh").splitlines() if not ln.lstrip().startswith("#")]
    ran = set()
    for ln in lines:
        m = re.search(r"(?:^|[\s)])run\s+\S.*?\btests/(\w+\.(?:py|sh))(?=\s|$)", ln)
        if m:
            ran.add(m.group(1))
    out = dict(NOT_IN_GATE)
    for name in names:
        check((name in ran) != (name in out),
              "tests/%s is run by tests/gate.sh or named in NOT_IN_GATE, one of the two" % name)
    for name in sorted(out):
        check(name in names, "NOT_IN_GATE names a file tests/ holds (%s)" % name)
    for name in sorted(ran):
        check(name in names, "tests/gate.sh runs a file tests/ holds (%s)" % name)
    for f in GATE_CALLERS:
        named = sorted(set(re.findall(r"tests/(\w+\.(?:py|sh))\b", read(f))) - {"gate.sh", "land.sh"})
        check(not named, "%s names no test file but tests/gate.sh and tests/land.sh%s"
              % (f, "" if not named else " (found %s)" % ", ".join(named)))
    # gate.weights names every suite gate.sh runs, by its label, and no other
    code = "\n".join(ln for ln in read("tests/gate.sh").splitlines() if not ln.lstrip().startswith("#"))
    labels = set(m.group(1) or m.group(2) for m in re.finditer(r'(?:^|[\s)])run\s+(?:"([^"]+)"|(\S+))\s', code, re.M))
    weighed = set(ln.split("\t")[0] for ln in read("tests/gate.weights").splitlines() if ln and not ln.startswith("#"))
    check(labels == weighed, "tests/gate.weights has one row per suite of tests/gate.sh%s"
          % ("" if labels == weighed else " (gate only: %s; weights only: %s)" % (sorted(labels - weighed), sorted(weighed - labels))))
    check("tests/gate.sh\" fast" in read(".githooks/pre-commit"), ".githooks/pre-commit runs tests/gate.sh fast")
    check("tests/gate.sh" not in read(".githooks/pre-push") and "tests/land.sh\" --passed" in read(".githooks/pre-push"),
          ".githooks/pre-push runs no test: it asks tests/land.sh --passed")
    ci = read(".github/workflows/ci.yml")
    check(ci.count('run: sh tests/gate.sh full "$GROUP"') == 2 and ci.count("group: [smoke, serve, rest]") == 2,
          "ci.yml: linux and macos run tests/gate.sh full, one job per group (smoke, serve, rest)")
    groups = set(re.findall(r"(?m)^\s+(\w+)\)\s+group_\w+ ;;$", read("tests/gate.sh")))
    check(groups == {"lint", "smoke", "serve", "rest"}, "tests/gate.sh full takes the groups ci.yml names (lint, smoke, serve, rest)")
    check('run: sh tests/gate.sh full lint' in ci and ci.count("    needs: lint\n") == 7,
          "ci.yml: the lint job runs tests/gate.sh full lint, and every other job but green needs it")
    check("tags:" not in ci.split("\njobs:")[0], "ci.yml runs on no tag push: the tag's commit already passed")
    jobs = set(re.findall(r"(?m)^  ([a-z]+):$", ci.split("\njobs:")[1]))
    m = re.search(r"(?ms)^  green:\n.*?^    needs: \[([^\]]+)\]", ci)
    needs = set(x.strip() for x in m.group(1).split(",")) if m else set()
    check(m is not None and needs == jobs - {"green"},
          "ci.yml: the green job needs every other job (%s)" % ", ".join(sorted(jobs - {"green"})))
    check("sh tests/land.sh --passed" in read(".github/workflows/release.yml"),
          "release.yml asks tests/land.sh --passed before it releases")


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
    no contraction, capitals only for acronyms -- a fence or a code span is not prose -- and a customer doc
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


URL = re.compile(r"https?://")
BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s")
SENTENCE_END = re.compile(r"[.?!] ")
WORD = re.compile(r"[A-Za-z0-9']+")


def prose_lines(text):
    """Each prose line of a Markdown doc as (line number, text), None for a
    boundary. Out: a fenced block, an indented block (a paragraph whose
    first line is 4 spaces in and no bullet), a table row (starts with
    `|`), a line holding a URL, a heading. Each is a boundary, as a blank
    line is."""
    out, fence, para_code = [], False, False
    lines = text.split("\n")
    for n, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            fence = not fence
            out.append(None)
            continue
        if not line.strip():
            para_code = False
            out.append(None)
            continue
        if n == 1 or not lines[n - 2].strip():
            para_code = line.startswith("    ") and not BULLET.match(line)
        if fence or para_code or line.lstrip().startswith(("|", "#")) or URL.search(line):
            out.append(None)
            continue
        out.append((n, line))
    return out


def sentences(text):
    """(line, words) for every sentence of a Markdown doc's prose. A
    sentence ends at ". ", "? " or "! " (a line's end counts as a space);
    a boundary (prose_lines) or a bullet starts a new one. A code span and
    a **bold** mark are taken out first: a span counts as one word, and
    its dots end nothing. Words are runs of letters, digits and
    apostrophes."""
    runs, cur = [], []
    for item in prose_lines(text) + [None]:
        if item is None or BULLET.match(item[1]):
            if cur:
                runs.append(cur)
            cur = [] if item is None else [item]
        else:
            cur.append(item)
    for run in runs:
        joined, starts = "", []
        for n, line in run:
            starts.append((len(joined), n))
            joined += line.strip() + " "
        # a span becomes one word of the same length, so offsets hold
        joined = SPAN.sub(lambda m: "x" * len(m.group(0)), joined).replace("**", "  ")
        at = 0
        for m in list(SENTENCE_END.finditer(joined)) + [None]:
            end = m.end() if m else len(joined)
            words = len(WORD.findall(joined[at:end]))
            line = max(n for off, n in starts if off <= at)
            if words:
                yield line, words
            at = end


def measures():
    """docs/CONTRIBUTING.md "## Voice", the two measures, over every
    Markdown doc but the CHANGELOG (history stays as written; the
    cheatsheet has its own 80 columns): no sentence over 30 words, no
    prose line over 72 columns. A failure names the file, the line and
    the count."""
    for doc in ALL_DOCS:
        if not doc.endswith(".md") or doc == "docs/CHANGELOG.md":
            continue
        text = read(doc)
        wide = ["%d (%d)" % (n, len(line)) for n, line in filter(None, prose_lines(text)) if len(line) > 72]
        check(not wide, "%s: prose within 72 columns%s"
              % (doc, "" if not wide else " (line %s)" % ", ".join(wide)))
        long = ["%d (%d words)" % (n, w) for n, w in sentences(text) if w > 30]
        check(not long, "%s: no sentence over 30 words%s"
              % (doc, "" if not long else " (line %s)" % ", ".join(long)))


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



def page_words():
    """The page in the browser speaks the README's words, says chat where
    a person reads, keeps the retired nouns out, serves every file in
    its folder and no other, and its tokens.css defines night and day
    alike (spark.forgewright.ai copies that file at the tag)."""
    import html as html_mod
    from spark import forgeserve
    page = read("lib/spark/forge/index.html")

    def plain(s):
        s = html_mod.unescape(re.sub(r"<[^>]+>", "", s))
        return re.sub(r"\s+", " ", s.replace("`", "")).strip()
    docs = {name: re.sub(r"\s+", " ", read(name).replace("`", "")).lower() for name in ("README.md", "docs/INSTALL.md")}
    found = re.findall(r'<(p|span)([^>]*)data-doc="([^"]+)"[^>]*>(.*?)</\1>', page, re.S)
    check(len(found) >= 7, "index.html marks its spark sentences data-doc (%d)" % len(found))
    for _tag, _attrs, src, body in found:
        text = plain(body)
        check(text.lower() in docs.get(src, ""), "index.html: a data-doc sentence is in %s, word for word: %s" % (src, text[:50]))
    # one noun for a conversation where a person reads: chat (the API keeps thread)
    visible = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    check("thread" not in visible.lower(), "index.html says chat, never thread, where a person reads")
    js = read("lib/spark/forge/spark.js")
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', js)
    shown = [x for x in strings if re.search(r"\bthreads?\b", x) and "/api/" not in x and " " in x
             and not x.startswith(("#", "."))]   # a selector is not a word a person reads
    check(not shown, "spark.js shows chat, never thread, in its strings%s" % ("" if not shown else ": " + shown[0][:40]))
    # the retired nouns stay out of the page (the site holds the same rule)
    for name in ("lib/spark/forge/index.html", "lib/spark/forge/spark.js"):
        txt = re.sub(r"/\*.*?\*/", "", read(name), flags=re.S)
        txt = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
        m = re.search(r"\b(the|a) forge\b|\b(the|an) ember\b|\bthe brain\b|\bsmart (app|apps|os)\b|\bthe seed\b", txt, re.I)
        check(m is None, "%s: no retired noun where a person reads%s" % (name, " (found '%s')" % m.group(0) if m else ""))
    # every file under lib/spark/forge is served: STATIC names it (the
    # font files included), and nothing served is missing from the tree
    forge = os.path.join(ROOT, "lib", "spark", "forge")
    on_disk = set()
    for root, _dirs, files in os.walk(forge):
        for f in files:
            if not f.startswith("."):
                on_disk.add(os.path.relpath(os.path.join(root, f), forge))
    off = sorted(on_disk ^ set(forgeserve.STATIC))
    check(not off, "forgeserve.STATIC names every file under lib/spark/forge and nothing else%s" % ("" if not off else " (%s)" % off[:3]))
    # tokens.css: the one source of the look; night defines every token,
    # the two day blocks (data-theme, the system's) the same set as each other
    tokens = read("lib/spark/forge/tokens.css")
    blocks = re.findall(r"\{([^{}]*)\}", tokens)
    roots = [set(re.findall(r"(--[a-z0-9-]+):", b)) for b in blocks if "--page:" in b]
    check(len(roots) == 3 and roots[0] >= roots[1] and roots[1] == roots[2],
          "tokens.css: a night block with every token, two day blocks alike")
    check("@font-face" in tokens and tokens.count("url(fonts/") == 6, "tokens.css: six font faces by relative path")
    # the six files by their sha256: a font is a binary the privacy grep
    # does not read and every browser parses; these are upstream's bytes
    # (Monaspace v1.400's webfont release, Fontsource's Atkinson
    # Hyperlegible Next 5.2.2), and a swap is a finding here
    import hashlib
    for name, digest in FONTS.items():
        with open(os.path.join(ROOT, "lib", "spark", "forge", "fonts", name), "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()
        check(got == digest, "fonts/%s is upstream's file, by sha256 (got %s)" % (name, got[:12]))
    check(read("lib/spark/forge/theme.js").strip() != "", "theme.js is there (the chosen theme before first paint)")

def living():
    """The living prompt (v1.59) as the tree holds it: every verb of `spark
    help`'s interface block, and `Esc k`, in the cheatsheet and INSTALL;
    SPARK_LOOK, the one switch, and SPARK_HEIGHT (config.SPARK_KEYS) a
    row of INSTALL's key table; every shipped temperament (words.d/) named in
    INSTALL; no doc calls awaken minting; and no shipped line claims
    where data goes -- README.md says what leaves."""
    import subprocess
    out = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "spark"), "help"],
                         capture_output=True, text=True).stdout
    m = re.search(r"(?m)^the living prompt\n(.*?)(?:\n\n|\Z)", out, re.S)
    verbs = sorted(set(re.findall(r"(?m)^ spark ([a-z]+)", m.group(1)))) if m else []
    check(bool(verbs), "spark help has a living prompt block with verbs")
    cheat, inst = read("docs/CHEATSHEET.txt"), read("docs/INSTALL.md")
    for v in verbs + ["Esc k"]:
        word = v if v == "Esc k" else "spark " + v
        for name, text in (("docs/CHEATSHEET.txt", cheat), ("docs/INSTALL.md", inst)):
            check(re.search(r"\b%s\b" % re.escape(word), text) is not None,
                  "%s names %s (spark help, the living prompt)" % (name, word))
    table = set(re.findall(r"(?m)^\| `([A-Z_]+)`", inst))
    keys = [k for k in config.SPARK_KEYS if k.startswith("SPARK_LOOK") or k == "SPARK_HEIGHT"]
    check(keys == ["SPARK_LOOK", "SPARK_HEIGHT"],
          "config.SPARK_KEYS holds SPARK_LOOK (one switch, no SPARK_LOOK_* part) and SPARK_HEIGHT")
    for k in keys:
        check(k in table, "docs/INSTALL.md's key table has a row for %s" % k)
    shipped = os.path.join(ROOT, "home", ".config", "spark", "words.d")
    tempers = sorted(f for f in os.listdir(shipped) if not f.startswith("."))
    check(bool(tempers), "home/.config/spark/words.d ships a temperament")
    for t in tempers:
        check(re.search(r"\b%s\b" % re.escape(t), inst) is not None,
              "docs/INSTALL.md names the temperament %s (words.d/%s)" % (t, t))
    minted = re.compile(r"\bmint\w*\b[^.\n]{0,60}\bawak|\bawak\w*\b[^.\n]{0,60}\bmint", re.I)
    for doc in ALL_DOCS:
        if doc == "docs/CHANGELOG.md":
            continue
        m = minted.search(" ".join(read(doc).split()))
        check(m is None, "%s: awaken never mints%s" % (doc, " (found '%s')" % m.group(0) if m else ""))
    claim = re.compile(r"\b(leaves?|privacy|private|cloud|sends?|sent|offline)\b", re.I)
    for t in tempers:
        text = "\n".join(l.split("\t", 1)[-1] for l in read(os.path.join(shipped, t)).split("\n")
                         if l and not l.startswith("#"))
        m = claim.search(text)
        check(m is None, "words.d/%s: no line claims where data goes%s" % (t, " (found '%s')" % m.group(0) if m else ""))


# v1.64: one server. The spellings `spark serve` and `spark model --chat`
# took over stay as aliases, named in no doc but the CHANGELOG and never
# in `spark help`. Read with the whitespace folded, so a command wrapped
# over a line break is still one. `FORGE`, the code's name, and the
# `spark-forge` unit are not commands; `spark brain --porcelain` is
# contract 5 and stays.
OLD_SPELLING = re.compile(
    r"\bspark (?:forge|ember|headless|share)\b(?!-)"
    r"|\bspark brain\b(?! --porcelain)"
    r"|(?<![\w-])forge (?:on|off|--print-url|--print-client|audit|token)\b"
    r"|(?<![\w-])ember (?:list|auto|none|NAME)\b")
SERVER_GROUP = "the model and the server"


def one_server():
    """The v1.64 verbs, as the docs and the help say them: no doc but the
    CHANGELOG and no line of `spark help` names an old spelling; every
    command of help's "the model and the server" group is in the
    cheatsheet."""
    import subprocess
    for doc in ALL_DOCS:
        if doc == "docs/CHANGELOG.md":
            continue
        m = OLD_SPELLING.search(" ".join(read(doc).split()))
        check(m is None, "%s: no old server spelling%s" % (doc, " (found '%s')" % m.group(0) if m else ""))
    out = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "spark"), "help"],
                         capture_output=True, text=True).stdout
    m = OLD_SPELLING.search(" ".join(out.split()))
    check(m is None, "spark help: no old server spelling%s" % (" (found '%s')" % m.group(0) if m else ""))
    m = re.search(r"(?m)^%s\n(.*?)(?:\n\n|\Z)" % re.escape(SERVER_GROUP), out, re.S)
    check(m is not None, "spark help has a '%s' group" % SERVER_GROUP)
    cheat = read("docs/CHEATSHEET.txt")
    for line in (m.group(1).split("\n") if m else []):
        if not line.startswith(" spark "):
            continue
        # the command column ends at two spaces, its words at a
        # placeholder ([on|off], NAME)
        words = []
        for w in re.split(r"\s{2,}", line.strip())[0].split():
            if w.startswith("[") or re.match(r"^[A-Z]+$", w):
                break
            words.append(w)
        cmd = " ".join(words)
        check(re.search(re.escape(cmd) + r"(?![\w-])", cheat) is not None,
              "docs/CHEATSHEET.txt names %s (spark help, %s)" % (cmd, SERVER_GROUP))


def chat_commands():
    """Every command of the chat (forge.SLASH_VERBS, what /help lists)
    is in the cheatsheet and in docs/INSTALL.md's chat table: a command
    added without its doc line fails here."""
    from spark import forge
    cheat = read("docs/CHEATSHEET.txt")
    inst = read("docs/INSTALL.md")
    for verb in sorted(forge.SLASH_VERBS):
        pat = re.escape(verb) + r"(?![\w-])"
        check(re.search(pat, cheat) is not None,
              "docs/CHEATSHEET.txt names %s (forge.SLASH_VERBS)" % verb)
        check(re.search(r"(?m)^\| `" + pat, inst) is not None,
              "docs/INSTALL.md's chat table has a row for %s (forge.SLASH_VERBS)" % verb)


WIDGETS = ("home/.config/spark/widget.zsh", "home/.config/spark/widget.bash")


def spoken():
    """spark voice (v1.70) as the tree holds it, in the docs that state it:
    every licence voice.env names is credited (its URL, and its name
    right after it, in CREDITS.md); the SBOM holds voice.env's pins, one
    sherpa-onnx component per runtime flavour and one model per model
    row, by sha256; every word of `spark voice` (voice.VOICE_USAGE) is on
    a `spark voice` line of the cheatsheet; the keys the widgets bind,
    `Esc <letter>`, are the same in both widgets and each is in the
    cheatsheet and INSTALL; every SPARK_VOICE* key (config.SPARK_KEYS)
    is a row of INSTALL's key table."""
    from spark import sbom, voice as voicemod
    pins = config.parse_env(os.path.join(ROOT, "voice.env"))
    credits = " ".join(read("CREDITS.md").split())
    lic = sorted(k for k in pins if k.endswith("_LICENSE"))
    check(bool(lic), "voice.env names a licence for its parts")
    for key in lic:
        words = pins[key].split()
        name, url = (words[0], words[-1]) if len(words) > 1 else ("?", "?")
        check(upstream(url) in credits and ("%s -- %s" % (url, name)) in credits,
              "CREDITS.md names %s -- %s (voice.env %s)" % (url, name, key))
    rows = {k: v.split() for k, v in pins.items()
            if k.startswith("VOICE_") and not k.endswith(("_LICENSE", "_VERSION")) and len(v.split()) == 3}
    want = sorted(w[2] for w in rows.values())
    got = sorted(c["hashes"][0]["content"] for c in sbom.build(ROOT)["components"]
                 if c["name"] == "sherpa-onnx" or c["type"] == "machine-learning-model")
    check(bool(want) and got == want, "the SBOM holds voice.env's pins, by sha256 (%d rows)" % len(want))
    cheat, inst = read("docs/CHEATSHEET.txt"), read("docs/INSTALL.md")
    verbs = sorted(set(re.findall(r"(?m)^  spark voice ([a-z]+)", voicemod.VOICE_USAGE)))
    check(bool(verbs), "voice.VOICE_USAGE names the words of spark voice")
    for w in verbs:
        check(re.search(r"(?m)^\s*spark voice\b[^\n]*\b%s\b" % re.escape(w), cheat) is not None,
              "docs/CHEATSHEET.txt has a spark voice line with %s (voice.VOICE_USAGE)" % w)
    bound = []
    for f in WIDGETS:
        bound.append(sorted(set(re.findall(r"\b_spark_k_[a-z]+='Esc ([a-z])'", read(f)))))
    check(bool(bound[0]) and bound[0] == bound[1], "the two widgets bind the same Esc keys (%s)" % " ".join(bound[0]))
    for k in bound[0]:
        for name, text in (("docs/CHEATSHEET.txt", cheat), ("docs/INSTALL.md", inst)):
            check(re.search(r"\bEsc %s\b" % k, text) is not None, "%s names Esc %s (the widgets bind it)" % (name, k))
    # the sizes the docs state are voice.env's: the mouth's row in
    # INSTALL's engine table, and the total per OS (the runtime of that
    # OS and the three models) in INSTALL, the cheatsheet and somewhere in
    # the CHANGELOG (new sizes need a new line there; the top section may
    # be about something else)
    mb = {k: int(round(int(w[1]) / 1e6)) for k, w in rows.items()}
    models = sum(int(rows[k][1]) for k in ("VOICE_MOUTH", "VOICE_EARS", "VOICE_VAD") if k in rows)
    linux = int(round((int(rows["VOICE_RUNTIME_LINUX_X64"][1]) + models) / 1e6)) if rows else 0
    mac = int(round((int(rows["VOICE_RUNTIME_MACOS"][1]) + models) / 1e6)) if rows else 0
    flat = lambda text: " ".join(text.split())     # noqa: E731
    check(re.search(r"(?m)^\| the mouth \| [^|]*\| %d MB \|" % mb.get("VOICE_MOUTH", -1), inst) is not None,
          "docs/INSTALL.md's engine table gives the mouth's size, %d MB (voice.env)" % mb.get("VOICE_MOUTH", -1))
    pair = "%d MB on Linux" % linux, "%d MB on macOS" % mac
    for name, text in (("docs/INSTALL.md", inst), ("docs/CHEATSHEET.txt", cheat),
                       ("docs/CHANGELOG.md", read("docs/CHANGELOG.md"))):
        check(all(p in flat(text) for p in pair), "%s states the engine as %s and %s (voice.env)" % ((name,) + pair))
    table = set(re.findall(r"(?m)^\| `([A-Z_]+)`", inst))
    keys = [k for k in config.SPARK_KEYS if k.startswith("SPARK_VOICE")]
    check(bool(keys), "config.SPARK_KEYS holds the SPARK_VOICE keys")
    for k in keys:
        check(k in table, "docs/INSTALL.md's key table has a row for %s" % k)


def shell_keys():
    """`spark keys` (v1.83) as the tree holds it: the names and default
    keys of keys.NAMES are the two widgets' own, every name is in INSTALL
    and in the verb's usage and both completion files, the verb is in the
    cheatsheet, both widgets read the KEYS=off line of keys.env, the old
    site.env switch is gone, docs/REFERENCE.md's contract 3 lists site.env's keys,
    and SPARK_OFF is told."""
    from spark import keys as keysmod
    inst, cheat, claude = read("docs/INSTALL.md"), read("docs/CHEATSHEET.txt"), read("docs/REFERENCE.md")
    want = sorted((n, k) for n, k, _ in keysmod.NAMES)
    for f in WIDGETS:
        text = read(f)
        got = sorted(re.findall(r"\b_spark_k_([a-z]+)='([^']+)'", text))
        check(got == want, "%s: the keys and their defaults are keys.NAMES (%s)" % (f, " ".join(n for n, _ in want)))
        for n, _ in want:
            check(re.search(r"(?m)^\s*KEYS_%s\) _spark_k_%s=" % (n.upper(), n), text) is not None
                  and re.search(r"\b_spark_key %s \S+" % n, text) is not None,
                  "%s reads KEYS_%s and binds %s through _spark_key" % (f, n.upper(), n))
        check("Ctrl-[%s]" % keysmod.CTRL_OK in text, "%s takes the Ctrl letters keys.CTRL_OK names" % f)
    for n, _ in want:
        check(re.search(r"`%s`" % n, inst) is not None, "docs/INSTALL.md names the key %s (keys.NAMES)" % n)
        check(re.search(r"\b%s\b" % n, keysmod.USAGE) is not None, "spark keys -h names %s" % n)
        for f in ("home/.config/spark/completion.bash", "home/.config/spark/completion.zsh"):
            m = re.search(r"(?m)^\s*keys\)\s+(?:words=\"|comp=\()([^\")]*)", read(f))
            check(m is not None and n in m.group(1).split(), "%s completes spark keys %s" % (f, n))
    for word in ("spark keys", "spark keys off", "SPARK_OFF=1"):
        check(word in inst, "docs/INSTALL.md says %s" % word)
    check(re.search(r"(?m)^\s*spark keys\b", cheat) is not None, "docs/CHEATSHEET.txt has a spark keys line")
    check("spark keys" in read("README.md"), "README.md names spark keys where it says spark adds one rc line")
    for f in WIDGETS:
        check("KEYS=*" in read(f) and "=none _spark_k_recall=none" in read(f),
              "%s reads keys.env's KEYS line and binds none of the keys when it is off" % f)
    for f in ("lib/spark/config.py", "site.env.example", "lib/env.sh", "bootstrap.sh", "docs/INSTALL.md",
              "docs/REFERENCE.md", "README.md", "lib/spark/keys.py", "lib/spark/setup.py"):
        check("SITE_" + "KEYS=" not in read(f) and '"SITE_' + 'KEYS"' not in read(f) and "`SITE_" + "KEYS`" not in read(f),
              "%s holds no SITE_" "KEYS: keys.env's KEYS line is the one switch" % f)
    check("`KEYS` is `on` or `off`" in claude, "docs/REFERENCE.md contract 3 says keys.env's KEYS line")
    m = re.search(r"- `site\.env`: `([A-Z_\s]+)`", claude)
    check(m is not None and m.group(1).split() == list(config.SITE_KEYS),
          "docs/REFERENCE.md contract 3 lists site.env's keys as config.SITE_KEYS holds them")
    check("keys.env" in claude and "replaced." in claude, "docs/REFERENCE.md names keys.env and the widgets' record")


def quiet():
    """v1.72, less noise, as the docs state it: `spark ver` prints the
    logo and the version and no credits line, `spark ver --credits`
    adds them; `spark check`'s usage names --all, and the cheatsheet and
    INSTALL name `spark check --all` and `spark ver --credits`."""
    import subprocess
    spark = [sys.executable, os.path.join(ROOT, "bin", "spark")]
    ver = subprocess.run(spark + ["ver"], capture_output=True, text=True).stdout
    cred = subprocess.run(spark + ["ver", "--credits"], capture_output=True, text=True).stdout
    last = [l for l in ver.split("\n") if l.strip()][-1:] or [""]
    check(re.match(r"^spark \S+$", last[0]) is not None and "CREDITS.md" not in ver,
          "spark ver ends with spark X.Y and prints no credits line")
    check("CREDITS.md" in cred, "spark ver --credits names CREDITS.md")
    from spark import check as checkmod
    check(re.search(r"(?m)^  spark check --all\b", checkmod.USAGE) is not None,
          "spark check's usage names --all")
    for name in ("docs/CHEATSHEET.txt", "docs/INSTALL.md"):
        text = " ".join(read(name).split())
        for cmd in ("spark check --all", "spark ver --credits"):
            check(cmd in text, "%s names %s (v1.72)" % (name, cmd))


# v1.80: the voice's four characters are gone. A name of one is stale
# only where the voice is the subject: `radio` is a fair word in a line
# about Wi-Fi, so a hit needs a voice word within NEAR characters
GONE_VOICES = re.compile(r"\b(?:radio|choir|eightbit|eight[- ]bit|robot)\b", re.I)
VOICE_WORD = re.compile(r"\b(?:voices?|characters?|speakers?|effects?|chains?|aloud|awaken)\b", re.I)
NEAR = 200
# what voice.py held for them: gone from the module, named by no doc
GONE_VOICE_NAMES = ("CHAINS", "RECIPES", "TEMPER_FAMILY", "FAMILY_SIDS", "chain", "character")


def presence():
    """v1.80, a plain voice and a face with presence, as the tree holds
    them: no doc but the CHANGELOG names a removed voice character where
    the voice is the subject, and voice.py holds none; every `voice.NAME`
    docs/REFERENCE.md and AGENTS.md name is in voice.py; docs/REFERENCE.md's voice file
    entry names the keys voice.mint writes and never FAMILY; AGENTS.md no
    longer says the face shows only while spark waits; both widgets read
    FACE_IDLE, every FACE_<MOOD> they read is a mood look.py knows, and
    docs/REFERENCE.md states how many calls carry SPARK_HINT_ROW; grammar rule 6
    names every kind in look.PROGRESS and every pace in look.STEPS."""
    from spark import look, voice as voicemod
    for doc in ALL_DOCS:
        if doc == "docs/CHANGELOG.md":
            continue
        text = " ".join(read(doc).split())
        hit = ""
        for m in GONE_VOICES.finditer(text):
            if VOICE_WORD.search(text[max(0, m.start() - NEAR):m.end() + NEAR]):
                hit = m.group(0)
                break
        check(not hit, "%s: no removed voice character%s" % (doc, " (found '%s')" % hit if hit else ""))
    held = [n for n in GONE_VOICE_NAMES if hasattr(voicemod, n)]
    check(not held, "voice.py holds no character chain%s" % ("" if not held else " (found %s)" % ", ".join(held)))
    claude, agents = read("docs/REFERENCE.md"), read("AGENTS.md")
    for doc, text in (("docs/REFERENCE.md", claude), ("AGENTS.md", agents)):
        names = sorted(set(re.findall(r"(?<![\w./-])voice\.([A-Za-z_]\w*)", text)) - {"env", "py", "wav"})
        lost = [n for n in names if not hasattr(voicemod, n)]
        check(not lost, "%s: every voice.NAME it names is in voice.py (%d names)%s"
              % (doc, len(names), "" if not lost else " (lost %s)" % ", ".join(lost)))
    # contract 3's entry for the voice file: the keys mint writes
    keys = sorted(voicemod.mint("plain", "docs"))
    m = re.search(r"(?ms)^   - `~/\.config/spark/voice`:(.*?)^   - ", claude)
    entry = m.group(1) if m else ""
    check(bool(keys) and bool(entry) and all(re.search(r"\b%s\b" % k, entry) for k in keys),
          "docs/REFERENCE.md's voice file entry names the keys voice.mint writes (%s)" % " ".join(keys))
    check(re.search(r"\bFAMILY\b", claude) is None, "docs/REFERENCE.md: the voice file has no FAMILY")
    flat = " ".join(agents.split())
    check("only while spark waits" not in flat, "AGENTS.md: the face is not only the wait")
    check("rests above an idle prompt" in flat, "AGENTS.md: the face rests above an idle prompt")
    # the widgets: the faces they read, and the calls that carry the row
    moods = set(look.MOODS) | {"blink", "glance"}
    calls = []
    for f in WIDGETS:
        src = read(f)
        read_faces = set(re.findall(r"(?m)^\s*FACE_([A-Z]+)\) ", src))
        check("IDLE" in read_faces, "%s reads FACE_IDLE from the look file" % f)
        off = sorted(x for x in read_faces if x.lower() not in moods)
        check(not off, "%s: every FACE_<MOOD> it reads is a mood look.py knows%s"
              % (f, "" if not off else " (found %s)" % ", ".join(off)))
        check(re.search(r"(?m)^\s*(?:\.|source)\s+\S*\$f\b|(?:\.|source)\s+\S*/look\b", src) is None,
              "%s never sources the look file" % f)
        calls.append(sum(1 for line in src.split("\n")
                         if "SPARK_HINT_ROW=$_spark_height" in line and not line.lstrip().startswith("#")))
    check(calls[0] == calls[1] and ("The widgets set it on those %d calls" % calls[0]) in " ".join(claude.split()),
          "docs/REFERENCE.md contract 4: the widgets set SPARK_HINT_ROW on %d calls, both alike" % calls[0])
    # grammar rule 6: every progress kind by name, every pace
    m = re.search(r"(?ms)^6\. One progress vocabulary\.(.*?)^7\. ", claude)
    rule = m.group(1) if m else ""
    check(bool(rule), "docs/REFERENCE.md has grammar rule 6, one progress vocabulary")
    for kind in look.PROGRESS:
        check("`%s`" % kind in rule, "docs/REFERENCE.md's grammar rule 6 names the progress kind %s (look.PROGRESS)" % kind)
    for step in sorted(set(look.STEPS.values())):
        check("%.2f" % step in rule, "docs/REFERENCE.md's grammar rule 6 states the pace %.2f (look.STEPS)" % step)


COMPLETIONS = ("home/.config/spark/completion.bash", "home/.config/spark/completion.zsh")
# v1.82: words that named what the code no longer does
GONE_WORDS = ("TRAPINT", "new programs missing")


def warns():
    """v1.82, the prompt warns and the check remembers, as the tree holds
    them: every --flag of check.USAGE is in both completion files; the
    cheatsheet and INSTALL name `spark check --history`, and help's line
    for `spark clear --history` names it too; docs/REFERENCE.md's runtime paths
    name the three files the merge writes beside check.json, by the
    names in lib/spark/__init__.py; AGENTS.md's hook rule names
    state/alert, and neither widget sources or writes that file;
    bootstrap's knowledge row asks `fresh` (`fresh whole` on a client)
    and then runs `build`; the knowledge row's remedy is spark update;
    no doc names a word that is gone."""
    import spark
    from spark import check as checkmod, cli
    flags = sorted(set(re.findall(r"(?m)^  spark check (--[a-z]+)", checkmod.USAGE)))
    check(len(flags) > 1, "check.USAGE names its flags (%s)" % " ".join(flags))
    for f in COMPLETIONS:
        m = re.search(r'(?m)^\s*check\)\s+(?:words="([^"]*)"|comp=\(([^)]*)\))', read(f))
        words = (m.group(1) or m.group(2) or "").split() if m else []
        lost = [x for x in flags if x not in words]
        check(bool(words) and not lost, "%s completes every flag of spark check%s"
              % (f, "" if not lost else " (lacks %s)" % " ".join(lost)))
    check("--history" in flags, "check.USAGE names --history")
    for name in ("docs/CHEATSHEET.txt", "docs/INSTALL.md"):
        check("spark check --history" in " ".join(read(name).split()), "%s names spark check --history" % name)
    check("spark check --history" in " ".join(cli.CLEAR_USAGE.split()),
          "cli.CLEAR_USAGE says spark clear --history drops what spark check --history shows")
    claude = read("docs/REFERENCE.md")
    m = re.search(r"(?ms)^State is `~/\.local/state/spark/`.*?^Data is ", claude)
    paths = m.group(0) if m else ""
    check(bool(paths), "docs/REFERENCE.md has the runtime paths of the state directory")
    for const in ("CHECK_JSON", "CHECK_LOCK", "CHECK_HISTORY", "ALERT_FILE"):
        base = os.path.basename(getattr(spark, const, "") or "?")
        check("`%s`" % base in paths, "docs/REFERENCE.md's runtime paths name %s (spark.%s)" % (base, const))
    alert = "state/" + os.path.basename(spark.ALERT_FILE)
    check("`%s`" % alert in read("AGENTS.md"), "AGENTS.md names %s among the hook's reads" % alert)
    for f in WIDGETS:
        src = "\n".join(line for line in read(f).split("\n") if not line.lstrip().startswith("#"))
        check(re.search(r"\$SPARK_DIR/alert\b", src) is not None, "%s reads the alert file" % f)
        check(re.search(r"(?:^|[;&|]\s*|\s)(?:\.|source|eval)\s+[^\n]*/alert\b", src) is None
              and re.search(r">>?\s*\"?\$(?:f|SPARK_DIR/alert)\b", src) is None,
              "%s never sources and never writes the alert file" % f)
    # bootstrap: the question first, the build only when it says no
    boot = read("bootstrap.sh")
    m = re.search(r"(?ms)^knowledge_fresh\(\) \{\n(.*?)^\}\n(.*?)^fi$", boot)
    body, row = (m.group(1), m.group(2)) if m else ("", "")
    check("knowledge fresh whole" in body and re.search(r"else knowledge fresh;", body) is not None,
          "bootstrap.sh's knowledge_fresh asks `fresh`, and `fresh whole` on a client")
    ask, build = row.find("if knowledge_fresh"), row.find("knowledge build")
    check(0 <= ask < build, "bootstrap.sh's knowledge row asks knowledge_fresh, then runs `knowledge build`")
    src = read(os.path.join("lib", "spark", "check.py"))
    m = re.search(r"(?ms)^def row_knowledge\(ctx\):(.*?)^(?:def |@row)", src)
    check(m is not None and re.search(r'fix = "spark update"', m.group(1)) is not None,
          "the knowledge row's remedy is spark update, the command that runs bootstrap's row")
    for doc in ALL_DOCS:
        text = " ".join(read(doc).split())
        for word in GONE_WORDS:
            check(word not in text, "%s does not say '%s'" % (doc, word))


# the labels the patch lane's agent sets (AGENTS.md, The patch lane); the
# first nine a reporter sees, so CONTRIBUTING explains them
LANE_LABELS = ("triage", "S1", "S2", "S3", "S4", "approved", "needs-steps", "arc", "not-a-bug",
               "in-progress", "needs-human")


def patch_lane():
    """The patch lane as the docs state it is what the tree does: the bug
    form requires its fields and lands as triage; blank issues are off and
    questions go to Discussions; AGENTS.md's brief names every label and
    CONTRIBUTING the ones a reporter sees; README and CONTRIBUTING point
    to Issues and Discussions; the weekly day tag.sh defaults to is the
    day the docs name; the fence's cap is the number the docs state."""
    form = read(".github/ISSUE_TEMPLATE/bug.yml")
    check(form.count("required: true") >= 5 and "label: Steps to reproduce" in form,
          "the bug form requires at least five fields, steps to reproduce among them")
    check("labels: [bug, triage]" in form, "a bug report lands labelled bug and triage")
    check("Paste freely" not in form and "GitHub issues are public" in form,
          "the bug form says reports are public without a blanket paste claim")
    for field in ("steps", "saw", "report"):
        m = re.search(r"(?ms)^    id: %s\n(.*?)(?=^  - type:|\Z)" % field, form)
        check(m is not None and "description:" in m.group(1),
              "the bug form has guidance beside %s" % field)
    check("spark check --report" in form and "login QR" in form,
          "the bug form prefers a status report and protects login QR codes")
    readme, inst = read("README.md"), read("docs/INSTALL.md")
    check("## Bugs\n" in readme and "GitHub issues are public" in readme and
          "spark check --report" in readme and re.search(r"README\.md says\s+the same under Bugs", inst),
          "README and INSTALL lead reporters to the same public-report guidance")
    cfg = read(".github/ISSUE_TEMPLATE/config.yml")
    check("blank_issues_enabled: false" in cfg and "github.com/forgewright-ai/spark/discussions" in cfg,
          ".github/ISSUE_TEMPLATE/config.yml turns blank issues off and points questions to Discussions")
    check(not os.path.exists(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "bug.md")),
          "the markdown bug template is gone: the form requires its fields")
    agents = read("AGENTS.md")
    m = re.search(r"^## The patch lane\n(.*?)(?=^## )", agents, re.S | re.M)
    check(m is not None, "AGENTS.md has a '## The patch lane' section")
    lane = m.group(1) if m else ""
    contrib = read("docs/CONTRIBUTING.md")
    for label in LANE_LABELS:
        check("`%s`" % label in lane, "AGENTS.md, The patch lane, names the label `%s`" % label)
    for label in LANE_LABELS[:9]:
        check("`%s`" % label in contrib, "docs/CONTRIBUTING.md explains the label `%s`" % label)
    for doc in ("README.md", "docs/CONTRIBUTING.md"):
        text = read(doc)
        check("github.com/forgewright-ai/spark/issues" in text and "github.com/forgewright-ai/spark/discussions" in text,
              "%s points to Issues and to Discussions" % doc)
    m = re.search(r"^weekday=\$\{SPARK_TAG_WEEKDAY:-(\d)\}$", read("tests/tag.sh"), re.M)
    day = {"1": "Monday", "2": "Tuesday", "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday", "7": "Sunday"}
    check(m is not None, "tests/tag.sh has a default weekly day")
    if m:
        for doc in ("docs/CONTRIBUTING.md", "docs/REFERENCE.md", "AGENTS.md"):
            check(day[m.group(1)] in read(doc), "%s names tag.sh's weekly day, %s" % (doc, day[m.group(1)]))
    m = re.search(r"^cool=\$\{SPARK_TAG_COOL:-(\d+)\}$", read("tests/tag.sh"), re.M)
    check(m is not None, "tests/tag.sh has default cooling hours")
    if m:
        for doc in ("docs/REFERENCE.md", "AGENTS.md", "docs/CONTRIBUTING.md"):
            check(re.search(r"\b%s hours\b" % m.group(1), read(doc)) is not None,
                  "%s states tag.sh's cooling hours, %s" % (doc, m.group(1)))
    m = re.search(r"^PATCH_MAX_LINES = (\d+)$", read("tests/patch_test.py"), re.M)
    check(m is not None, "tests/patch_test.py has PATCH_MAX_LINES")
    if m:
        for doc in ("docs/REFERENCE.md", "AGENTS.md"):
            check(re.search(r"\b%s (changed )?lines\b" % m.group(1), read(doc)) is not None,
                  "%s states the fence's cap, %s lines" % (doc, m.group(1)))


def tests_brief():
    """CLAUDE.md is what a Claude session loads: short, it imports
    AGENTS.md, and every section it names is one of docs/REFERENCE.md's
    (a ## heading or an Adding-things bullet)."""
    brief = read("CLAUDE.md")
    lines = brief.split("\n")
    check(len(lines) <= 200, "CLAUDE.md stays under 200 lines (%d)" % len(lines))
    check("@AGENTS.md" in lines, "CLAUDE.md imports AGENTS.md on a line of its own")
    ref = read("docs/REFERENCE.md")
    sections = set(re.findall(r"^#+ (.+)$", ref, re.M)) | set(re.findall(r"^- \*\*(.+?)\.\*\*", ref, re.M))
    for name in sorted(set(" ".join(n.split()) for n in re.findall(r'"([^"]+)"', brief))):   # a quote wrapped by the prose
        if name == "The patch lane":
            check("## The patch lane" in read("AGENTS.md"), "AGENTS.md has the section CLAUDE.md names, %s" % name)
            continue
        check(name in sections, "docs/REFERENCE.md has the section CLAUDE.md names, %s" % name)
    # the project skills: a directory with a SKILL.md each, named after
    # its directory, with a description, and named in the Layout
    layout = re.search(r"## Layout\n\n```\n(.*?)\n```", ref, re.S)
    layout = layout.group(1) if layout else ""
    skills = sorted(os.listdir(os.path.join(ROOT, ".claude", "skills")))
    check(skills == ["spark-add-check-row", "spark-land", "spark-release"], ".claude/skills/ holds the three skills (%s)" % ", ".join(skills))
    for name in skills:
        text = read(os.path.join(".claude", "skills", name, "SKILL.md"))
        check(re.search(r"^name: %s$" % re.escape(name), text, re.M) is not None, "skill %s: name is its directory" % name)
        check(re.search(r"^description: \S", text, re.M) is not None, "skill %s: has a description" % name)
        check(name in layout and name in read("AGENTS.md"), "skill %s: the Layout and AGENTS.md name it" % name)


def main():
    tests_brief()
    tests_named()
    tests_gated()
    readme, inst, cheat, cli = (read(f) for f in
                                ("README.md", "docs/INSTALL.md", "docs/CHEATSHEET.txt", "bin/spark"))
    for name, body in (("README.md", readme), ("docs/INSTALL.md", inst),
                       ("docs/CHEATSHEET.txt", cheat), ("bin/spark", cli)):
        check("nothing leaves" not in body and
              ("no telemetry" in body.lower() or "no account or telemetry" in body.lower()),
              "%s has qualified privacy wording without a blanket claim" % name)
    check("### HTTPS for the page" in inst and
          "docs/INSTALL.md#https-for-the-page" in readme and
          "only shows certificate status" in inst,
          "README links to the HTTPS procedure and INSTALL distinguishes status")
    credits = read("CREDITS.md")
    # models: every row's license upstream is credited
    rows = [r for r in config.model_tables(ROOT) if r[6] == "repo"]
    sizes = [round(r[3] / 2**30, 1) for r in rows]
    budgets = [r[5] for r in rows]
    for doc in ("README.md", "docs/INSTALL.md"):
        intro = read(doc).split("curl -fsSL", 1)[0]
        check("%.1f to %.1f GB" % (min(sizes), max(sizes)) in intro and
              "%d to %d GB" % (min(budgets), max(budgets)) in intro,
              "%s gives model file sizes and memory budgets before install" % doc)
    inst = read("docs/INSTALL.md")
    check(inst.index("## Before you start") < inst.index("## Install on an existing computer") <
          inst.index("## 1. A machine from zero"),
          "INSTALL leads with requirements and a signed existing-computer path")
    check("Developer-only alternative" in inst and "without signed-release verification" in inst,
          "INSTALL states the clone-from-main tradeoff beside that path")
    # the docs rendered outside this tree (docs/REFERENCE.md, "A doc") draw code
    # spans, bold, bare URLs and doc names, and nothing else: a markdown
    # link or an emphasis there shows as typed
    for doc in ("docs/INSTALL.md", "docs/CHANGELOG.md", "docs/ROADMAP.md", "docs/CONTRIBUTING.md", "CREDITS.md"):
        hits = re.findall(r"\]\(|(?<![*\w])\*[A-Za-z][^*\n]*\*(?![*\w])", prose(read(doc)))
        check(not hits, "%s uses no markdown link or emphasis, which the page shows as typed%s"
              % (doc, ": " + ", ".join(h[:40] for h in hits[:3]) if hits else ""))
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
    for doc in ("docs/REFERENCE.md", "docs/INSTALL.md"):
        for m in re.finditer(r"spark check`?\s+(?:has )?(\d+) rows", read(doc)):
            check(int(m.group(1)) == n_rows, "%s: '%s' is check.py's count (%d)" % (doc, m.group(0), n_rows))
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
    # the split by category docs/REFERENCE.md states ("8 SOFTWARE, 22 CAPABILITY, 9 NONFUNCTIONAL")
    src_rows = read(os.path.join("lib", "spark", "check.py"))
    for cat in ("SOFTWARE", "CAPABILITY", "NONFUNCTIONAL"):
        n_cat = len(re.findall(r'^@row\("%s"' % cat, src_rows, re.M))
        m = re.search(r"(\d+)\s+%s" % cat, read("docs/REFERENCE.md"))
        check(m is not None and int(m.group(1)) == n_cat, "docs/REFERENCE.md: %d %s rows (check.py says %d)" % (int(m.group(1)) if m else -1, cat, n_cat))
    # the chaos scenarios: a count a doc spells out is chaos.py's own
    n_sc = sum(1 for line in read(os.path.join("lib", "spark", "chaos.py")).split("\n")
               if line.startswith("@scenario"))
    spelled = "zero one two three four five six seven eight nine ten eleven twelve".split()
    if n_sc < len(spelled):
        rx = re.compile(r"\b(%s) (?:failures|scenarios)\b" % "|".join(spelled), re.I)
        for doc in ("docs/ROADMAP.md", "docs/CHANGELOG.md", "README.md", "docs/INSTALL.md", "docs/REFERENCE.md", "AGENTS.md"):
            for m in rx.finditer(read(doc)):
                check(m.group(1).lower() == spelled[n_sc],
                      "%s: '%s' is chaos.py's count (%s)" % (doc, m.group(0), spelled[n_sc]))
    # a contract written down and not built says so in three places: its
    # module, the roadmap and docs/REFERENCE.md. Check the claims, not the prose --
    # and check that nothing quietly started dispatching to it
    verbs = read(os.path.join("bin", "spark"))
    roadmap, claude = read("docs/ROADMAP.md"), read("docs/REFERENCE.md")
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
              "docs/REFERENCE.md reserves contract %s for spark %s" % (n, name))
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
    top = re.search(r"^## v(\d+\.\d+)(?:\.\d+)?$", read("docs/CHANGELOG.md"), re.M).group(1)
    m = re.search(r"What comes after v(\d+\.\d+)", read("docs/ROADMAP.md"))
    check(m is not None and m.group(1) == top, "docs/ROADMAP.md: 'What comes after v%s' names docs/CHANGELOG.md's top section" % top)
    # the gated row lists: docs/REFERENCE.md states their counts, and names the
    # client's rows one by one
    src = read(os.path.join("lib", "spark", "check.py"))
    claude = read("docs/REFERENCE.md")
    named = {}
    for const in ("WSL_ROWS", "ARCH_ROWS", "VOID_ROWS", "CLIENT_ROWS"):
        m = re.search(r"^%s = \(([^)]*)\)" % const, src, re.M)
        named[const] = re.findall(r'"([a-z]+)"', m.group(1)) if m else []
        # ARCH_ROWS and VOID_ROWS may be empty: nothing a family lacks
        check(m is not None, "check.py defines %s" % const)
        for c in re.finditer(r"the (\d+) rows?\s+in\s+`check\.%s`" % const, claude):
            check(int(c.group(1)) == len(named[const]),
                  "docs/REFERENCE.md: '%s' is check.py's count (%d)" % (" ".join(c.group(0).split()), len(named[const])))
    m = re.search(r"`check\.CLIENT_ROWS` \(([^)]*)\)", claude)
    listed = re.split(r",\s+", " ".join(m.group(1).split())) if m else []
    check(listed == named["CLIENT_ROWS"],
          "docs/REFERENCE.md names check.CLIENT_ROWS in order (%s)" % ", ".join(named["CLIENT_ROWS"]))
    n_models = len(rows)
    for doc in ("README.md", "docs/INSTALL.md"):
        for m in re.finditer(r"(\d+) (models|rows), each with its license", read(doc)):
            check(int(m.group(1)) == n_models, "%s: '%s' is models.env's count (%d)" % (doc, m.group(0), n_models))
    # the CHANGELOG's top section is the newest tag or the one right after it
    # (written before its tag, docs/REFERENCE.md Releasing) -- never further ahead,
    # never behind. After a tag a.b or a.b.c the one right after is its next
    # patch (a.b.1, a.b.c+1), the next minor (a.b+1) or the next major (a+1.0)
    import subprocess
    try:
        tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()[1:]
    except (OSError, subprocess.CalledProcessError):
        tag = ""
    top = re.search(r"^## v(\d+)\.(\d+)(?:\.(\d+))?$", read("docs/CHANGELOG.md"), re.M)
    if tag and top and re.match(r"^\d+\.\d+(?:\.\d+)?$", tag):
        head = (int(top.group(1)), int(top.group(2)), int(top.group(3) or 0))
        t = [int(x) for x in tag.split(".")] + [0]
        tmaj, tmin, tpat = t[0], t[1], t[2]
        allowed = ((tmaj, tmin, tpat), (tmaj, tmin, tpat + 1), (tmaj, tmin + 1, 0), (tmaj + 1, 0, 0))
        check(head in allowed,
              "docs/CHANGELOG.md: the top section v%s is the newest tag v%s, its next patch, the next minor or the next major"
              % (top.group(0)[4:], tag))
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
    # the README's Apps section lists the apps: every app it names is
    # credited, and the page front checks itself the same way where the
    # page is rendered
    m = re.search(r"## Apps\n(.*?)(?:\n## |\Z)", read("README.md"), re.S)
    apps = sorted(set(re.findall(r"github\.com/forgewright-ai/(spark-[a-z0-9]+)", m.group(1) if m else "")))
    check(bool(apps), "README.md's Apps section names at least one spark app repo")
    for app in apps:
        check(app in read("CREDITS.md"), "CREDITS.md names %s (README.md's Apps does)" % app)
    # docs/ holds exactly the five core docs that moved there with v1.38.
    # (release-gated, so none carries the "not tied to a release" line);
    # every one is in docs/REFERENCE.md's Layout and is pointed to from the README
    have = sorted(f for f in os.listdir(os.path.join(ROOT, "docs")) if not f.startswith("."))
    check(have == sorted(DOCS_DIR), "docs/ holds exactly %s%s"
          % (", ".join(DOCS_DIR), "" if have == sorted(DOCS_DIR) else " (found %s)" % ", ".join(have)))
    m = re.search(r"## Layout\n\n```\n(.*?)\n```", claude, re.S)
    layout = m.group(1) if m else ""
    for name in CORE_IN_DOCS:
        check("This document is not tied to a spark release" not in read("docs/" + name),
              "docs/%s is core (the landing rule): it does not carry the beside-the-core line" % name)
        check("docs/" + name in readme, "README.md points to docs/%s" % name)
    for name in DOCS_DIR:
        check(name in layout, "docs/REFERENCE.md's Layout names docs/%s" % name)
    # every package family's data file is named on the Layout's distro/ line
    for f in sorted(os.listdir(os.path.join(ROOT, "distro"))):
        if f.endswith(".env"):
            check(f in layout, "docs/REFERENCE.md's Layout names distro/%s" % f)
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
    # CHANGELOG is history; docs/REFERENCE.md's Layout block names files by their
    # bare name under the docs/ entry, as every entry there does
    old = re.compile(r"(?<!docs/)(?<![\w.-])(INSTALL\.md|CHEATSHEET\.txt|CHANGELOG\.md|ROADMAP\.md|CONTRIBUTING\.md)\b")
    scan = list(live) + ["bin/spark"] + sorted(os.path.join("lib", "spark", f) for f in os.listdir(libdir) if f.endswith(".py"))
    for d, _, fs in os.walk(os.path.join(ROOT, "templates")):
        scan += [os.path.relpath(os.path.join(d, f), ROOT) for f in fs]
    for doc in scan:
        text = read(doc)
        if doc == "docs/REFERENCE.md":
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
    # v1.62: the machine's look left core -- no doc but the CHANGELOG
    # names the verbs that set it
    for doc in ALL_DOCS:
        if doc in ("docs/CHANGELOG.md", "site.env.example"):
            continue
        m = re.search(r"\bspark (?:theme|font)\b|\bspark quiet (?:login|boot)\b|--theme\b|\bthemes/", read(doc))
        check(m is None, "%s: the look is not core%s" % (doc, " (found '%s')" % m.group(0) if m else ""))
    # v1.69: no spark quiet, and the look is one switch -- no doc but the
    # CHANGELOG names the verb, its keys, or a part of the look as a word
    # of spark look
    gone = re.compile(r"\bspark quiet\b|\bspark look (?:PART|motion|colou?r|words|reveal)\b")
    # the removed keys: docs/REFERENCE.md alone names them, as keys an older file
    # may hold that still load and that nothing reads
    keys = re.compile(r"\bSITE_QUIET_(?:START|AUDIO)\b|\bSPARK_LOOK_[A-Z]+|\bquiet_(?:start|audio)\b")
    for doc in ALL_DOCS + ("home/.config/spark/spark.env.example",):
        if doc == "docs/CHANGELOG.md":
            continue
        m = gone.search(read(doc)) or (keys.search(read(doc)) if doc != "docs/REFERENCE.md" else None)
        check(m is None, "%s: no spark quiet, the look one switch (v1.69)%s"
              % (doc, " (found '%s')" % m.group(0) if m else ""))
    # v1.48: the core knows nothing of a shell layer, and neither does a
    # doc -- the generic contracts (theme.env, the six SPARK_*_SGR
    # variables, spark bar line) are described as generic; the
    # CHANGELOG alone keeps the history
    for doc in ALL_DOCS:
        if doc == "docs/CHANGELOG.md":
            continue
        m = re.search(r"spark-shell|(?i:shell layer)|SHELL\.md|THEME_BTOP", read(doc))
        check(m is None, "%s: no shell layer%s" % (doc, " (found '%s')" % m.group(0) if m else ""))
    # contract 9: the route table docs/REFERENCE.md prints is forgeserve.ROUTES,
    # entry for entry -- a route added without its row, or a row without
    # its route, fails here (the block is METHOD  PATH  ROLE lines)
    from spark import forgeserve
    m = re.search(r"```\n((?:[ ]*(?:GET|POST|DELETE)\s+\S+\s+(?:none|user|admin)\n)+)[ ]*```", claude)
    check(m is not None, "docs/REFERENCE.md contract 9 prints the route table (METHOD  PATH  ROLE)")
    doc_routes = {}
    for line in (m.group(1).split("\n") if m else []):
        if line.strip():
            method, path, role = line.split()
            doc_routes[(method, path)] = role
    off = sorted(k for k in set(doc_routes) | set(forgeserve.ROUTES) if doc_routes.get(k) != forgeserve.ROUTES.get(k))
    check(not off, "docs/REFERENCE.md's route table is forgeserve.ROUTES, entry for entry%s"
          % ("" if not off else " (differs at %s)" % ", ".join("%s %s" % k for k in off[:3])))
    # the release key get carries is allowed-signers, byte for byte: a
    # fresh install verifies against the key in get, never the clone's
    # file, so a key rotation changes both in one commit
    m = re.search(r"^SIGNERS='([^']*)'$", read("get"), re.M)
    check(m is not None, "get embeds the release key as SIGNERS='...'")
    check(m is not None and m.group(1) + "\n" == read("allowed-signers"),
          "get's embedded release key is allowed-signers, byte for byte")
    # the living prompt: its verbs, keys and temperaments in the docs
    living()
    # the page's words: a paragraph marked data-doc in index.html is a
    # sentence of README.md or docs/INSTALL.md, word for word (whitespace
    # and backticks aside) -- the page says nothing of its own about spark
    page_words()
    # the patch lane: the form, the labels, the weekly day, the fence
    patch_lane()
    # one server: the old spellings nowhere, the group in the cheatsheet
    one_server()
    # the chat's commands: each in the cheatsheet and INSTALL's table
    chat_commands()
    # the voice: its credits, its pins in the SBOM, its words and keys
    spoken()
    # v1.72: spark ver without credits, spark check --all
    quiet()
    shell_keys()
    # v1.80: a plain voice, the face's presence, the progress kinds
    presence()
    # v1.82: the prompt warns, the check remembers, the knowledge row
    warns()
    # the voice's mechanical half, and the two nouns in what spark prints
    voice()
    measures()
    help_voice()
    if fails:
        print("docs_test: %d failed" % len(fails))
        return 1
    print("docs_test: all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
