#!/usr/bin/env python3
"""The knowledge intake (lib/spark/intake.py) on a fixture machine, in a
throwaway HOME.

The fixture is a PATH, a MANPATH and an app dir of its own, pointed at
through the seams (SPARK_KNOWLEDGE_PATH, SPARK_KNOWLEDGE_MANPATH,
SPARK_KNOWLEDGE_APPS, SPARK_KNOWLEDGE_DIR, SPARK_KNOWLEDGE_SOURCES), so
nothing of this machine's /usr is read. Proven: a man(7) page tied to its
program and an mdoc page found on the MANPATH, a gzipped page, a `.so`
followed inside its man root and one leaving it refused, an `H-S` page
becoming the entry "H S", a .desktop app (its program's name only, never
its arguments) and a .desktop that folds into a program, a macOS .app's
Info.plist, a manual line holding a secret shape held, a program with no
manual on a machine with no sandbox skipped and counted, a world-writable
dir skipped and counted, a --help run contained and stamped so it never
runs again, the store's modes (dir 0700, files 0600) and shapes (index,
entries named by sha256), a second refresh incremental and fast, a held
lock returning at once, the fingerprint moving when a PATH dir gains a
file, the package databases' parsers, spark's own verbs from the tree,
the bootstrap row's words, and -- where probe() says this machine has a
sandbox -- the real containment of a --help run.
"""
import fcntl
import gzip
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

# a throwaway HOME before spark is imported: its paths are read at import
T = os.path.realpath(tempfile.mkdtemp(prefix="spark-knowledge-test-"))
HOME = os.path.join(T, "home")
os.makedirs(HOME)
for _k in list(os.environ):
    if _k.startswith(("SPARK_", "XDG_", "SITE_", "MANPATH")):
        del os.environ[_k]
os.environ.update({"HOME": HOME, "XDG_CONFIG_HOME": HOME + "/.config", "XDG_STATE_HOME": HOME + "/.local/state",
                   "XDG_DATA_HOME": HOME + "/.local/share", "SPARK_NO_REFRESH": "1"})
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, LIB)
from spark import IS_MAC, intake, sandbox  # noqa: E402

FAILED = 0
SKIPPED = []
GH = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"   # a GitHub token's shape  spark:allow-secret


def check(name, cond, detail=""):
    global FAILED
    if cond:
        print("ok   %s" % name)
    else:
        FAILED += 1
        print("FAIL %s%s" % (name, ("\n  " + str(detail)[:600]) if detail else ""))


def write(path, body, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = body if isinstance(body, bytes) else body.encode()
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, mode)


def prog(path, body="#!/bin/sh\necho hi\n"):
    write(path, body, 0o755)


def mode_of(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


# ------------------------------------------------------------ the fixture
FX = os.path.join(T, "fx")                 # a prefix: bin/ and share/man/
BIN = os.path.join(FX, "bin")
MAN = os.path.join(T, "man")               # the MANPATH
APPS = os.path.join(T, "apps")
WW = os.path.join(T, "ww")                 # a world-writable dir on the PATH
STORE = os.path.join(T, "store")

MAN7 = """.TH ALPHA 1
.SH NAME
alpha \\- print the \\fBalpha\\fR report
.SH SYNOPSIS
.B alpha
[\\-v] [\\-\\-format=\\fIFMT\\fR] [\\fIfile\\fR]
.SH OPTIONS
.TP
.B \\-v
Say more. It keeps going.
.TP
.B \\-\\-format=FMT
Write the report as FMT.
.SH EXAMPLES
.TP
.B \\-\\-example\\-only
Never an option line.
.SH SEE ALSO
beta(1)
"""
MDOC = """.Dd January 1, 2026
.Dt BETA 1
.Os
.Sh NAME
.Nm beta
.Nd count the beta widgets
.Sh SYNOPSIS
.Nm
.Op Fl ab
.Op Fl -long-one
.Sh DESCRIPTION
.Bl -tag -width Ds
.It Fl a
Count all of them.
.It Fl b
Count the blue ones. Then stop.
.It Fl -long-one
The long one.
.El
"""
GZ = """.TH GAMMA 8
.SH NAME
gamma \\- restart the gamma daemon
.SH SYNOPSIS
.B gamma
[\\-\\-now]
.SH OPTIONS
.TP
.B \\-\\-now
Restart at once.
"""
SUB = """.TH TOOL-SUB 1
.SH NAME
tool-sub \\- the sub command of tool
.SH SYNOPSIS
.B tool sub
[\\-\\-deep]
.SH OPTIONS
.TP
.B \\-\\-deep
Go deep.
"""
SECRET = """.TH SECRETIVE 1
.SH NAME
secretive \\- keeps a token in its manual
.SH OPTIONS
.TP
.B \\-\\-token
The token, for example %s here.
""" % GH


def fixture():
    prog(os.path.join(BIN, "alpha"))
    prog(os.path.join(BIN, "beta"))
    prog(os.path.join(BIN, "gamma"))
    prog(os.path.join(BIN, "tool"))
    prog(os.path.join(BIN, "delta"))
    prog(os.path.join(BIN, "evil"))
    prog(os.path.join(BIN, "nomanual"))
    prog(os.path.join(BIN, "secretive"))
    prog(os.path.join(BIN, "-rf"))                   # not a name spark stores
    write(os.path.join(BIN, "notexec"), "plain\n")    # not a program
    write(os.path.join(FX, "share", "man", "man1", "alpha.1"), MAN7)          # tied to the binary
    write(os.path.join(MAN, "man1", "beta.1"), MDOC)                          # on the MANPATH, mdoc
    write(os.path.join(MAN, "man8", "gamma.8.gz"), gzip.compress(GZ.encode()))
    write(os.path.join(MAN, "man1", "tool-sub.1"), SUB)                       # H-S: tool sub
    write(os.path.join(MAN, "man1", "delta.1"), ".\\\" a comment\n.so man1/beta.1\n")   # .so inside the root
    write(os.path.join(MAN, "man1", "evil.1"), ".so ../../../../../etc/passwd\n")         # .so out of it
    write(os.path.join(MAN, "man1", "secretive.1"), SECRET)
    os.makedirs(os.path.join(WW, "bin"))
    prog(os.path.join(WW, "bin", "wwprog"))
    os.chmod(os.path.join(WW, "bin"), 0o777)
    write(os.path.join(APPS, "fixture.desktop"),
          "[Desktop Entry]\nType=Application\nName=Fixture Viewer\nComment=Views the fixtures\n"
          "Exec=/opt/fixture/bin/fxview --open %U --token=" + GH + "\n")  # spark:allow-secret
    write(os.path.join(APPS, "alpha.desktop"),
          "[Desktop Entry]\nType=Application\nName=Alpha Reports\nComment=The alpha report, in a window\n"
          "Exec=alpha --gui %f\n")
    write(os.path.join(APPS, "hidden.desktop"), "[Desktop Entry]\nType=Application\nName=Hidden\nExec=hid\nNoDisplay=true\n")
    write(os.path.join(APPS, "gone.desktop"), "[Desktop Entry]\nType=Application\nName=Gone\nExec=gone\nTryExec=gone\n")
    write(os.path.join(APPS, "Fake.app", "Contents", "Info.plist"),
          plistlib.dumps({"CFBundleName": "Fake", "CFBundleExecutable": "FakeExec",
                          "CFBundleIdentifier": "org.example.fake", "NSSecret": GH}))  # spark:allow-secret
    os.environ.update({"SPARK_KNOWLEDGE_PATH": BIN + os.pathsep + os.path.join(WW, "bin"),
                       "SPARK_KNOWLEDGE_MANPATH": MAN, "SPARK_KNOWLEDGE_APPS": APPS,
                       "SPARK_KNOWLEDGE_DIR": STORE, "SPARK_KNOWLEDGE_SOURCES": "programs,apps"})


def renderer():
    ap = intake.abs_path()
    return shutil.which("mandoc", path=ap) or shutil.which("man", path=ap)


# ------------------------------------------------------------ the tests
def test_words():
    check("words: lowercase, stopwords out, crude suffixes off",
          intake.words("Listing the Files in a directory, sorted by size") == ["list", "file", "directory", "sort", "size"],
          intake.words("Listing the Files in a directory, sorted by size"))
    check("words: a flag's words split on the dashes", intake.words("--human-readable") == ["human", "readable"])


def test_parsers():
    what = intake.page_what(MAN7)
    check("page_what: man(7) NAME after `name \\-`, fonts dropped", what == "print the alpha report", what)
    check("page_what: mdoc's .Nd", intake.page_what(MDOC) == "count the beta widgets", intake.page_what(MDOC))
    o = intake.option_set("usage: x [-abc] [--long-one]\n  -name PATTERN\n  -v  verbose\n", "x [-abc] [--long-one]")
    check("option_set: long, short (a synopsis [-abc] gives each letter), words",
          "--long-one" in o.long and {"-a", "-b", "-c", "-v"} <= set(o.short) and "-name" in o.words, o)
    ls = intake.option_lines(["     -v      Say more. It keeps going.", "     --format=FMT", "             Write it. Twice.",
                              "     - a bullet, not a flag"])
    check("option_lines: the flag and its first sentence, from the line or the one under it",
          ls == ["-v  Say more.", "--format=FMT  Write it."], ls)
    check("parse_dpkg_status: package -> its Description's first line",
          intake.parse_dpkg_status("Package: coreutils\nStatus: install ok installed\nDescription: GNU core utilities\n"
                                   " more lines\n\nPackage: jq\nDescription: JSON processor\n")
          == {"coreutils": "GNU core utilities", "jq": "JSON processor"})
    check("parse_pacman_desc and parse_pacman_files",
          intake.parse_pacman_desc("%NAME%\ncoreutils\n\n%VERSION%\n9.5-1\n\n%DESC%\nThe basic tools\n\n")
          == ("coreutils", "The basic tools")
          and intake.parse_pacman_files("%FILES%\nusr/\nusr/bin/\nusr/bin/ls\n\n%BACKUP%\netc/x\n") == ["/usr/bin/ls"])
    check("parse_xbps_list and parse_xbps_owners",
          intake.parse_xbps_list("ii runit-2.1.2_18      A UNIX init scheme\nii xbps-0.60.3_1  The package system\n")
          == {"runit": "A UNIX init scheme", "xbps": "The package system"}
          and intake.parse_xbps_owners("runit-2.1.2_18: /usr/bin/sv (regular file)\n") == {"/usr/bin/sv": "runit"})
    check("parse_desktop: the [Desktop Entry] group, unlocalised keys",
          intake.parse_desktop("[Desktop Entry]\nName=A\nName[de]=B\nExec=a %U\n[Desktop Action x]\nExec=evil\n")
          == {"Name": "A", "Exec": "a %U"})
    check("_exec_name: the program's basename only, never its arguments; env and field codes skipped",
          intake._exec_name("env FOO=1 /usr/bin/app --flag %U") == "app" and intake._exec_name("sh -c 'x'") == "sh"
          and intake._exec_name("%U") == "")


def test_owners():
    pl = os.path.join(T, "pacman-local")
    write(os.path.join(pl, "fxpkg-1.0-1", "desc"), "%NAME%\nfxpkg\n\n%DESC%\nThe fixture package\n")
    write(os.path.join(pl, "fxpkg-1.0-1", "files"), "%FILES%\n" + os.path.join(BIN, "nomanual").lstrip("/") + "\n")
    saved = (intake.DPKG_INFO, intake.PACMAN_LOCAL)
    intake.DPKG_INFO, intake.PACMAN_LOCAL = os.path.join(T, "no-dpkg"), pl
    try:
        o = intake.Owners({os.path.join(BIN, "nomanual")})
        got = o.of(os.path.join(BIN, "nomanual"))
    finally:
        intake.DPKG_INFO, intake.PACMAN_LOCAL = saved
    check("Owners: pacman's local database names the owner and its summary",
          got == ("pacman:fxpkg", "The fixture package"), got)
    check("Owners: a Homebrew Cellar path is brew:<formula>",
          intake.Owners(set()).of("/x", "/opt/homebrew/Cellar/jq/1.8/bin/jq")[0] == "brew:jq")


def build(no_sandbox=True):
    saved = sandbox.probe
    if no_sandbox:
        sandbox.probe = lambda fresh=False, platform=None: (False, "no sandbox (the test)")
    try:
        t0 = time.monotonic()
        st = intake.refresh()
        return st, time.monotonic() - t0
    finally:
        sandbox.probe = saved


def test_build():
    shutil.rmtree(STORE, ignore_errors=True)
    calls = {"render": 0}
    orig = intake.render

    def counted(path, root):
        calls["render"] += 1
        return orig(path, root)
    intake.render = counted
    try:
        (counts, built, stale, skipped), t1 = build()
        first = calls["render"]
        s = intake.LocalStore()
        check("refresh: built, not stale, counts by kind", built and not stale and counts.get("program", 0) >= 8
              and counts.get("app") == 2, (counts, built, stale))
        check("refresh: nomanual and tool (no manual, no sandbox) and the world-writable dir's program are "
              "skipped and counted", skipped == 3 and s.entry("wwprog") is None, skipped)
        check("refresh: `-rf` (no plain name) and a file without x are no entries",
              s.entry("-rf") is None and s.entry("notexec") is None)
        # the store's shape and modes
        check("store: dir and entries/ 0700", mode_of(STORE) == 0o700 and mode_of(os.path.join(STORE, "entries")) == 0o700,
              oct(mode_of(STORE)))
        files = [os.path.join(STORE, f) for f in ("index.json", "meta.json", "docs.json")]
        files += [os.path.join(STORE, "entries", f) for f in os.listdir(os.path.join(STORE, "entries"))]
        check("store: every file 0600", all(mode_of(f) == 0o600 for f in files),
              [(f, oct(mode_of(f))) for f in files if mode_of(f) != 0o600])
        check("store: an entry file is sha256(name)[:32].json",
              os.path.exists(os.path.join(STORE, "entries", hashlib.sha256(b"alpha").hexdigest()[:32] + ".json")))
        idx = s.index()
        check("index: v %d, names, post as `i:tf` strings (tf the BM25F weight, two decimals)" % intake.INDEX_V,
              idx and idx["v"] == intake.INDEX_V and idx["names"] == sorted(idx["names"])
              and all(re.match(r"^(\d+:\d+(\.\d{1,2})? ?)+$", v) for v in idx["post"].values()), idx and list(idx))
        docs = json.load(open(os.path.join(STORE, "docs.json"), encoding="utf-8"))
        check("docs: each entry's words counted per field (%s)" % ", ".join(intake.FIELDS),
              all(isinstance(c, list) and len(c) == len(intake.FIELDS)
                  for d in docs.values() for c in d["tf"].values()))
        check("LocalStore.names: every entry", sorted(s.names()) == sorted(idx["names"]))
        if not renderer():
            SKIPPED.append("no mandoc and no man here: the page contents are not checked")
            return
        a = s.entry("alpha")
        check("alpha: the man(7) page tied to its program (../share/man) -- what, synopsis, option lines",
              a and a.kind == "program" and a.source == "man" and a.what == "print the alpha report"
              and a.synopsis.startswith("alpha") and any(l.startswith("-v") and "Say more." in l for l in a.lines),
              a)
        check("alpha: EXAMPLES and SEE ALSO never become option lines",
              a and not any("example-only" in l or "beta(1)" in l for l in a.lines), a and a.lines)
        check("alpha: the OptionSet read from the whole page",
              a and "-v" in a.options.short and "--format" in a.options.long, a and a.options)
        check("alpha: the .desktop that runs it folds in (its name and comment, its program's name)",
              a and any(l.startswith("app: Alpha Reports -- The alpha report, in a window (alpha)") for l in a.lines),
              a and a.lines[:2])
        b = s.entry("beta")
        check("beta: an mdoc page found on the MANPATH (.Nd, Fl flags)",
              b and b.what == "count the beta widgets" and {"-a", "-b"} <= set(b.options.short)
              and "--long-one" in b.options.long, b)
        g = s.entry("gamma")
        check("gamma: a gzipped section-8 page", g and g.source == "man" and g.what == "restart the gamma daemon"
              and "--now" in g.options.long, g)
        d = s.entry("delta")
        check("delta: a .so inside its man root is followed", d and d.source == "man" and d.what == "count the beta widgets", d)
        e = s.entry("evil")
        check("evil: a .so that leaves its man root is never read", e and e.source != "man", e)
        ts = s.entry("tool sub")
        check("tool-sub.1 with tool on the PATH is the entry `tool sub`", ts and ts.what == "the sub command of tool"
              and "--deep" in ts.options.long, ts)
        sec = s.entry("secretive")
        raw = json.dumps(sec._asdict()) if sec else ""
        check("secretive: the token in its manual is held, never stored", sec and GH not in raw and "[held]" in raw, raw[:300])
        allraw = "".join(open(f, encoding="utf-8").read() for f in files)
        check("store: no secret shape anywhere (the .desktop's and the plist's never read)", GH not in allraw)
        fx = s.entry("fxview")
        check(".desktop: keyed by its program's name, its display name and comment kept, no argument stored",
              fx and fx.kind == "app" and fx.synopsis == "fxview" and "Fixture Viewer -- Views the fixtures" in fx.what
              and "--open" not in json.dumps(fx._asdict()), fx)
        check(".desktop: NoDisplay and a TryExec not on the PATH are skipped",
              s.entry("hid") is None and s.entry("gone") is None)
        fk = s.entry("FakeExec")
        check(".app: Info.plist's executable is the key, `open -a NAME` its synopsis",
              fk and fk.kind == "app" and fk.synopsis == "open -a Fake" and fk.what.startswith("Fake"), fk)
        n = s.entry("nomanual")
        check("nomanual: no manual, no sandbox -- an entry all the same, source pkg", n and n.source == "pkg", n)
        # the second refresh: nothing re-read
        calls["render"] = 0
        (counts2, built2, stale2, skipped2), t2 = build()
        check("second refresh: incremental -- no page rendered again, same counts",
              calls["render"] == 0 and counts2 == counts and skipped2 == skipped, (calls, counts2, skipped2))
        check("second refresh: fast (%.2f s, the first %.2f s with %d pages)" % (t2, t1, first), t2 < 1.0 and t2 < t1 + 0.05)
    finally:
        intake.render = orig


def test_fingerprint():
    _c, _b, stale, _s = intake.status()
    check("status: fresh after a refresh", not stale and intake.fresh())
    time.sleep(0.02)
    prog(os.path.join(BIN, "newcomer"))
    _c, _b, stale, _s = intake.status()
    check("fingerprint: a PATH dir that gains a file makes the store stale", stale and not intake.fresh())
    build()
    s = intake.LocalStore()
    check("the next refresh reads the new program", s.entry("newcomer") is not None and not intake.status()[2])
    # a store an older spark wrote (index v1, flat term counts) is stale,
    # answers no index, and the next refresh reads everything again
    for f in ("meta.json", "index.json"):
        p = os.path.join(STORE, f)
        d = json.load(open(p, encoding="utf-8"))
        d["v"] = 1
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    check("an older index shape: stale, not fresh, no index read",
          intake.status()[2] and not intake.fresh() and intake.LocalStore().index() is None)
    build()
    idx = intake.LocalStore().index()
    check("the next refresh rebuilds it in this shape",
          idx is not None and idx["v"] == intake.INDEX_V and not intake.status()[2] and intake.fresh())


def test_help_contained():
    """A program with no manual on a machine WITH a sandbox: its --help,
    contained, parsed; stamped, so it never runs again."""
    calls = []

    def fake(argv, **kw):
        calls.append(list(argv))
        return 0, "usage: nomanual [-q] [--dry-run] FILE\n  -q         quiet. Very.\n  --dry-run  show only\n"
    saved = (sandbox.contained, sandbox.probe)
    sandbox.contained = fake
    sandbox.probe = lambda fresh=False, platform=None: (True, "the test")
    try:
        intake.refresh()
        n = intake.LocalStore().entry("nomanual")
        check("--help: run contained, as [real path, --help]",
              [os.path.realpath(os.path.join(BIN, "nomanual")), "--help"] in calls, calls)
        check("--help: its usage and options parsed into the entry", n and n.source == "help"
              and "--dry-run" in n.options.long and "-q" in n.options.short and n.synopsis.startswith("usage"), n)
        runs = len(calls)
        intake.refresh()
        check("--help: stamped -- the next refresh does not run it again", len(calls) == runs, calls)
    finally:
        sandbox.contained, sandbox.probe = saved


def test_lock():
    fd = os.open(os.path.join(STORE, ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        before = os.stat(os.path.join(STORE, "meta.json")).st_mtime_ns
        t0 = time.monotonic()
        intake.refresh()
        took = time.monotonic() - t0
        check("a held lock: refresh returns at once and builds nothing",
              took < 0.5 and os.stat(os.path.join(STORE, "meta.json")).st_mtime_ns == before, took)
    finally:
        os.close(fd)


def test_missing_store():
    s = intake.LocalStore(os.path.join(T, "nowhere"))
    check("a missing store: no names, no entry, no index -- never an error",
          s.names() == [] and s.entry("ls") is None and s.index() is None)


def test_spark_and_row():
    """spark's own verbs from the tree, and the bootstrap row's words from
    `python3 -m spark.intake build` in a fixture environment."""
    env = dict(os.environ, SPARK_KNOWLEDGE_SOURCES="spark", SPARK_KNOWLEDGE_DIR=os.path.join(T, "store-spark"),
               PYTHONPATH=LIB)
    p = subprocess.run([sys.executable, "-m", "spark.intake", "fresh"], env=env, capture_output=True, text=True)
    check("`python3 -m spark.intake fresh`: exit 1 before any build", p.returncode == 1, p.stderr)
    p = subprocess.run([sys.executable, "-m", "spark.intake", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("`python3 -m spark.intake build`: the row's words",
          p.returncode == 0 and re.match(r"^0 programs, 0 manuals, 0 apps, \d+ spark verbs \(\d+\.\d s\)$", p.stdout.strip()),
          p.stdout + p.stderr)
    p2 = subprocess.run([sys.executable, "-m", "spark.intake", "fresh"], env=env, capture_output=True, text=True)
    check("`python3 -m spark.intake fresh`: exit 0 once built", p2.returncode == 0, p2.stderr)
    s = intake.LocalStore(os.path.join(T, "store-spark"))
    m = s.entry("spark model")
    check("spark model: its -h first line, the USAGE slot, its words (list, auto, none) from completion.bash",
          m and m.kind == "spark" and m.what == "which model this machine serves"
          and "spark model [NAME|auto|none]" in m.synopsis and {"list", "auto", "none"} <= set(m.options.words), m)
    names = intake.tree_names()["_spark_model_names"]
    check("spark model: the models completion fills from models.env ride in its words too",
          m and names and set(names) <= set(m.options.words) and not any(n.endswith("-license") for n in names),
          m and m.options.words)
    top = s.entry("spark")
    check("spark: the help itself is an entry", top and top.what.startswith("your own AI"), top)
    raw = "".join(open(os.path.join(T, "store-spark", "entries", f), encoding="utf-8").read()
                  for f in os.listdir(os.path.join(T, "store-spark", "entries")))
    check("spark entries: the empty home they ran in is never named", T not in raw and HOME not in raw)


def test_real_contained():
    """Only where probe() says this machine has a sandbox: a --help run
    really contained -- no home, no /tmp, no bus, no network, no write."""
    good, detail = sandbox.probe()
    if not good:
        SKIPPED.append("no sandbox here (%s): the real containment is not run" % detail)
        return
    secret = os.path.join(HOME, "secret.txt")
    write(secret, "the home is readable\n")
    rc, out = sandbox.contained(["/bin/cat", secret])
    check("contained: the home is not readable inside", "the home is readable" not in out, out)
    out_file = os.path.join(T, "written-from-inside")
    rc, out = sandbox.contained(["/bin/sh", "-c", "echo x > %s" % out_file])
    check("contained: nothing outside is writable", not os.path.exists(out_file), out)
    rc, out = sandbox.contained([sys.executable, "-c",
                                 "import socket\ntry:\n socket.create_connection(('192.0.2.1', 9), 2)\n print('NET UP')\n"
                                 "except OSError as e:\n print('down', e)\n"])
    check("contained: no network", "NET UP" not in out and "down" in out, out)
    t0 = time.monotonic()
    rc, out = sandbox.contained(["/bin/sleep", "30"], seconds=1)
    check("contained: killed at its seconds (rc 124)", rc == 124 and time.monotonic() - t0 < 3, (rc, out))
    rc, out = sandbox.contained(["/usr/bin/yes"], cap=4096)
    check("contained: cut at its cap", len(out) <= 4096 and out.startswith("y"), len(out))
    if IS_MAC:
        rc, out = sandbox.contained(["/bin/sh", "-c", "/bin/echo forked; echo after"])
        check("contained (macOS): no child process", "forked" not in out and "fork" in out, out)
    else:
        uid = os.getuid()
        rc, out = sandbox.contained(["/bin/sh", "-c", "test -S /run/user/%d/bus && echo BUS; echo tmp: $(ls -A /tmp); "
                                     "echo proc: /proc/[0-9]*" % uid])
        tmp = next((l for l in out.splitlines() if l.startswith("tmp:")), "")
        proc = next((l for l in out.splitlines() if l.startswith("proc:")), "")
        check("contained (Linux): no session bus, /tmp holds only its own home, /proc shows only the sandbox",
              "BUS" not in out and tmp.split() == ["tmp:", "h"] and 1 < len(proc.split()) <= 6, out)


def main():
    fixture()
    for t in (test_words, test_parsers, test_owners, test_build, test_fingerprint, test_help_contained, test_lock,
              test_missing_store, test_spark_and_row, test_real_contained):
        try:
            t()
        except Exception as e:
            global FAILED
            FAILED += 1
            import traceback
            traceback.print_exc()
            print("FAIL %s crashed: %s" % (t.__name__, e))
    if SKIPPED:
        print("%d skipped: %s" % (len(SKIPPED), "; ".join(SKIPPED)))
    if FAILED:
        print("%d failed" % FAILED)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(T, ignore_errors=True)
