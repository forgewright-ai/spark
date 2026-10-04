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
# CLAUDE.md's voice file entry holds the keys voice.mint writes, both
# widgets read FACE_IDLE, and grammar rule 6 names every kind in
# look.PROGRESS; one test list (v1.79): every
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
CORE_IN_DOCS = ("INSTALL.md", "CHEATSHEET.txt", "CHANGELOG.md", "ROADMAP.md", "CONTRIBUTING.md")
DOCS_DIR = CORE_IN_DOCS
CUSTOMER_DOCS = ("README.md", "docs/INSTALL.md", "docs/CHEATSHEET.txt")
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
    # the voice (v1.70): Linux's sound layer
    "ALSA",
    # what the code prints: the gate's marker, the three row categories
    "NOTICE", "SOFTWARE", "CAPABILITY", "NONFUNCTIONAL",
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
    ("land.sh", "the landing command, not a test: land_test.sh proves it"),
    ("audition.py", "needs a live model"),
    ("line_audition.py", "needs a live model; smoke.py runs its selftest"),
    ("forge_probe.py", "asks a live server"),
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
    check("tests/gate.sh\" fast" in read(".githooks/pre-commit"), ".githooks/pre-commit runs tests/gate.sh fast")
    check("tests/gate.sh" not in read(".githooks/pre-push") and "tests/land.sh\" --passed" in read(".githooks/pre-push"),
          ".githooks/pre-push runs no test: it asks tests/land.sh --passed")
    ci = read(".github/workflows/ci.yml")
    check(ci.count('run: sh tests/gate.sh full "$GROUP"') == 2 and ci.count("group: [smoke, serve, rest]") == 2,
          "ci.yml: linux and macos run tests/gate.sh full, one job per group (smoke, serve, rest)")
    groups = set(re.findall(r"(?m)^\s+(\w+)\)\s+group_\w+ ;;$", read("tests/gate.sh")))
    check(groups == {"smoke", "serve", "rest"}, "tests/gate.sh full takes the groups ci.yml names (smoke, serve, rest)")
    check("tags:" not in ci.split("\njobs:")[0], "ci.yml runs on no tag push: the tag's commit already passed")
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
    """`spark keys` (v1.81) as the tree holds it: the names and default
    keys of keys.NAMES are the two widgets' own, every name is in INSTALL
    and in the verb's usage and both completion files, the verb is in the
    cheatsheet, SITE_KEYS is a key of config, site.env.example, env.sh,
    INSTALL's table and CLAUDE.md's contract 3, and SPARK_OFF is told."""
    from spark import keys as keysmod
    inst, cheat, claude = read("docs/INSTALL.md"), read("docs/CHEATSHEET.txt"), read("CLAUDE.md")
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
    check("SITE_KEYS" in config.SITE_KEYS, "config.SITE_KEYS holds SITE_KEYS")
    check(re.search(r"(?m)^SITE_KEYS=on$", read("site.env.example")) is not None, "site.env.example: SITE_KEYS=on")
    check(re.search(r"(?m)^\| `SITE_KEYS`", inst) is not None, "docs/INSTALL.md's key table has a SITE_KEYS row")
    check('"${SITE_KEYS:=on}"' in read("lib/env.sh"), "lib/env.sh defaults SITE_KEYS to on")
    m = re.search(r"- `site\.env`: `([A-Z_\s]+)`", claude)
    check(m is not None and m.group(1).split() == list(config.SITE_KEYS),
          "CLAUDE.md contract 3 lists site.env's keys as config.SITE_KEYS holds them")
    check("keys.env" in claude and "replaced." in claude, "CLAUDE.md names keys.env and the widgets' record")


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
    CLAUDE.md and AGENTS.md name is in voice.py; CLAUDE.md's voice file
    entry names the keys voice.mint writes and never FAMILY; AGENTS.md no
    longer says the face shows only while spark waits; both widgets read
    FACE_IDLE, every FACE_<MOOD> they read is a mood look.py knows, and
    CLAUDE.md states how many calls carry SPARK_HINT_ROW; grammar rule 6
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
    claude, agents = read("CLAUDE.md"), read("AGENTS.md")
    for doc, text in (("CLAUDE.md", claude), ("AGENTS.md", agents)):
        names = sorted(set(re.findall(r"(?<![\w./-])voice\.([A-Za-z_]\w*)", text)) - {"env", "py", "wav"})
        lost = [n for n in names if not hasattr(voicemod, n)]
        check(not lost, "%s: every voice.NAME it names is in voice.py (%d names)%s"
              % (doc, len(names), "" if not lost else " (lost %s)" % ", ".join(lost)))
    # contract 3's entry for the voice file: the keys mint writes
    keys = sorted(voicemod.mint("plain", "docs"))
    m = re.search(r"(?ms)^   - `~/\.config/spark/voice`:(.*?)^   - ", claude)
    entry = m.group(1) if m else ""
    check(bool(keys) and bool(entry) and all(re.search(r"\b%s\b" % k, entry) for k in keys),
          "CLAUDE.md's voice file entry names the keys voice.mint writes (%s)" % " ".join(keys))
    check(re.search(r"\bFAMILY\b", claude) is None, "CLAUDE.md: the voice file has no FAMILY")
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
          "CLAUDE.md contract 4: the widgets set SPARK_HINT_ROW on %d calls, both alike" % calls[0])
    # grammar rule 6: every progress kind by name, every pace
    m = re.search(r"(?ms)^6\. One progress vocabulary\.(.*?)^7\. ", claude)
    rule = m.group(1) if m else ""
    check(bool(rule), "CLAUDE.md has grammar rule 6, one progress vocabulary")
    for kind in look.PROGRESS:
        check("`%s`" % kind in rule, "CLAUDE.md's grammar rule 6 names the progress kind %s (look.PROGRESS)" % kind)
    for step in sorted(set(look.STEPS.values())):
        check("%.2f" % step in rule, "CLAUDE.md's grammar rule 6 states the pace %.2f (look.STEPS)" % step)


def main():
    tests_named()
    tests_gated()
    credits = read("CREDITS.md")
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
    # the split by category CLAUDE.md states ("8 SOFTWARE, 22 CAPABILITY, 9 NONFUNCTIONAL")
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
    for const in ("WSL_ROWS", "ARCH_ROWS", "VOID_ROWS", "CLIENT_ROWS"):
        m = re.search(r"^%s = \(([^)]*)\)" % const, src, re.M)
        named[const] = re.findall(r'"([a-z]+)"', m.group(1)) if m else []
        # ARCH_ROWS and VOID_ROWS may be empty: nothing a family lacks
        check(m is not None, "check.py defines %s" % const)
        for c in re.finditer(r"the (\d+) rows?\s+in\s+`check\.%s`" % const, claude):
            check(int(c.group(1)) == len(named[const]),
                  "CLAUDE.md: '%s' is check.py's count (%d)" % (" ".join(c.group(0).split()), len(named[const])))
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
    # every one is in CLAUDE.md's Layout and is pointed to from the README
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
        check(name in layout, "CLAUDE.md's Layout names docs/%s" % name)
    # every package family's data file is named on the Layout's distro/ line
    for f in sorted(os.listdir(os.path.join(ROOT, "distro"))):
        if f.endswith(".env"):
            check(f in layout, "CLAUDE.md's Layout names distro/%s" % f)
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
    # the removed keys: CLAUDE.md alone names them, as keys an older file
    # may hold that still load and that nothing reads
    keys = re.compile(r"\bSITE_QUIET_(?:START|AUDIO)\b|\bSPARK_LOOK_[A-Z]+|\bquiet_(?:start|audio)\b")
    for doc in ALL_DOCS + ("home/.config/spark/spark.env.example",):
        if doc == "docs/CHANGELOG.md":
            continue
        m = gone.search(read(doc)) or (keys.search(read(doc)) if doc != "CLAUDE.md" else None)
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
    # the release key get carries is allowed-signers, byte for byte: a
    # fresh install verifies against the key in get, never the clone's
    # file, so a key rotation changes both in one commit
    m = re.search(r"^SIGNERS='([^']*)'$", read("get"), re.M)
    check(m is not None, "get embeds the release key as SIGNERS='...'")
    check(m is not None and m.group(1) + "\n" == read("allowed-signers"),
          "get's embedded release key is allowed-signers, byte for byte")
    # the living prompt: its verbs, keys and temperaments in the docs
    living()
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
