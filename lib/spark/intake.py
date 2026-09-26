# spark.intake -- the Intake context: what this machine can run, read into
# the store outside the prompt line. Sources give entries; the store keeps
# them; refresh() rebuilds what changed. Nothing here asks a model, and
# nothing here runs on the prompt line's hot path.
#
#   a source   where entries come from: programs (their manuals, or their
#              --help run only inside spark's sandbox), apps (.desktop and
#              .app bundles), spark (its own verbs, from the tree)
#   an entry   one thing a person can run, as spark read it
#   the store  STATE_DIR/knowledge/: index.json (the searchable words) and
#              entries/<sha256(name)[:32]>.json (one entry each), dir 0700,
#              files 0600; beside them docs.json (each entry's words and
#              stamp, what the next refresh reuses) and meta.json (what
#              status() says)
#
# Every text an entry holds went through text.scrub, the home shown as ~,
# and text.hold_secrets: the store never keeps a secret shape. The import
# rule (a smoke test holds it): this module imports only spark/__init__,
# text and sandbox.
#
# Programs: every executable on the absolute PATH (the PATH of this build,
# the standard dirs, and the dirs an earlier build saw -- a timer's PATH is
# not the shell's), the first of a name wins. A dir on a remote filesystem
# (9p, drvfs, cifs, nfs, fuse: WSL 2's /mnt/c) is never listed. A dir or
# file owned by anyone but root or this user, and a world-writable dir,
# is skipped and counted.
# Manuals are read as files, never through a whatis database (Void's is
# stale, macOS has none): the page tied to the binary (its real dir's
# ../share/man and ../man), then every man dir, section 1, 8, then 6. A
# page's `.so` is followed only inside its own man root. mandoc renders it
# where mandoc is on the PATH, else `man -l`: a clean environment, cwd the
# man root, 5 seconds and 256 kB, the process group killed. Kept: NAME's
# words, SYNOPSIS (3 lines), the option lines with their first sentence,
# and an OptionSet read from the whole page -- never EXAMPLES, SEE ALSO,
# AUTHORS, BUGS or HISTORY lines. A page H-S whose H is a program gives the
# entry "H S" (git-log -> git log): no table of subcommands.
# --help: only for a program with no manual, only inside sandbox.contained
# (no sandbox here: skipped and counted), never as root, never an Xcode
# stub, every attempt stamped so it never runs again until the program
# changes, HELP_PER_SLICE a 5-second slice.
# Apps: .desktop files (the program in Exec, its basename only; Name and
# Comment) and macOS .app bundles (Info.plist: CFBundleName,
# CFBundleExecutable, CFBundleIdentifier), keyed by the executable's name.
# An app whose program is already an entry folds into it. No app is named
# in this file.
# spark: its verbs and their words from completion.bash (the list smoke's
# drift guard holds equal to bin/spark; the palettes and models its
# helpers fill, read from the tree), their slots from bin/spark's
# USAGE_* text, and each verb's `spark VERB -h`, run with an empty home.
# A new spark tree rebuilds every entry: the parsers may have changed.

import glob
import gzip
import hashlib
import io
import json
import os
import plistlib
import re
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from . import BIN_DIR, HOME, IS_MAC, REPO, STATE_DIR, log_exc, run
from . import sandbox
from . import text as textmod

# the options a manual or a --help names, the three shapes a flag takes:
# long ("--all"), short ("-a"; a synopsis's [-abc] gives each letter) and
# words ("-name", a single dash before a word, find's shape). For a spark
# verb, `words` holds the plain words it takes after it (on, off, list).
OptionSet = namedtuple("OptionSet", "long short words")

# kind: program | app | spark; source: man | help | pkg | desktop | app |
# tree; what: one line, what it is; synopsis: how it is called, 3 lines at
# most; lines: its option lines, each with its first sentence (a spark
# verb's: its -h lines); origin: who installed it (dpkg:coreutils,
# xbps:runit, brew:jq, macos, flatpak, local); stamp: (mtime, size) of
# what it was read from
Entry = namedtuple("Entry", "name kind source what synopsis options lines origin stamp")

KNOW_DIR = os.path.join(STATE_DIR, "knowledge")
INDEX_FILE = "index.json"
META_FILE = "meta.json"
DOCS_FILE = "docs.json"
ENTRIES_DIR = "entries"
LOCK_FILE = ".lock"

# a name spark stores: a plain command name, no path, no option (do's
# man_excerpt reads the same shape); each word of an "H S" name too
NAME_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")

SECTIONS = ("1", "8", "6")          # user commands, administration, games
PAGE_FILE = re.compile(r"^(?P<name>.+)\.(?P<sec>[168][A-Za-z0-9]*)(?P<gz>\.gz)?$")
REMOTE_FS = ("9p", "drvfs", "cifs", "smb3", "smbfs", "nfs", "nfs4", "afpfs", "webdav")
# the dirs every build lists besides the PATH: where the OS itself keeps
# programs, so a timer's short PATH still sees them
STANDARD_BIN = ("/usr/local/bin", "/usr/local/sbin", "/usr/bin", "/usr/sbin", "/bin", "/sbin",
                "/opt/homebrew/bin", "/opt/homebrew/sbin")
STANDARD_MAN = ("/usr/local/share/man", "/usr/local/man", "/usr/share/man", "/opt/homebrew/share/man",
                "/Library/Developer/CommandLineTools/usr/share/man",
                "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/share/man",
                "/Applications/Xcode.app/Contents/Developer/usr/share/man")
# the files that name more man dirs: macOS's, man-db's and mandoc's
MANPATH_FILES = ("/etc/manpaths", "/etc/manpath.config", "/etc/man_db.conf", "/etc/man.conf")
MANPATH_D = "/etc/manpaths.d"
SKIP_SECTIONS = ("EXAMPLES", "EXAMPLE", "SEE ALSO", "AUTHORS", "AUTHOR", "BUGS", "REPORTING BUGS",
                 "HISTORY", "COPYRIGHT")
# the package databases: a change to any of them is a change to what is
# installed (the fingerprint), and they answer who installed a file
DPKG_STATUS = "/var/lib/dpkg/status"
DPKG_INFO = "/var/lib/dpkg/info"
PACMAN_LOCAL = "/var/lib/pacman/local"
XBPS_DB = "/var/db/xbps"
BREW_ROOTS = ("/opt/homebrew", "/usr/local", os.path.join("/home", "linuxbrew", ".linuxbrew"))
MACOS_VERSION = "/System/Library/CoreServices/SystemVersion.plist"
# a program in one of these (by real path) is the OS's own on macOS
MACOS_DIRS = ("/bin/", "/sbin/", "/usr/bin/", "/usr/sbin/", "/usr/libexec/", "/System/",
              "/Library/Apple/", "/Library/Developer/CommandLineTools/")
MAC_APP_DIRS = ("/Applications", "/Applications/Utilities", "/System/Applications",
                "/System/Applications/Utilities", "~/Applications")
FLATPAK_APPS = ("/var/lib/flatpak/exports/share/applications", "~/.local/share/flatpak/exports/share/applications")
DESKTOP_CODES = re.compile(r"%[fFuUdDnNickvm]")

MAN_TIMEOUT = 5              # seconds a page may take to render
MAN_WIDTH = 80               # the page's columns
MAN_FILE_MAX = 1 << 20       # a page file larger than this (compressed) is not read
MAN_TEXT_MAX = 256 * 1024    # a rendered page is cut here
RENDERERS = 4                # pages rendered at once
SYNOPSIS_LINES = 3
SYNOPSIS_CHARS = 240
OPTION_LINES = 60            # option lines an entry keeps
OPTION_CHARS = 100           # characters each
OPTION_SET_MAX = 500         # flags of each shape an entry keeps
HELP_PER_SLICE = 16          # --help runs a 5-second slice may make
SLICE = 5
SPARK_SECONDS = 5            # a verb's -h
BUILD_CAP = 180              # seconds one refresh may take at most
LOCK_WAIT = 180              # seconds a waiting refresh (bootstrap) waits for the lock
MAX_ENTRIES = 20000
INDEX_MAX = 8 << 20          # an index.json larger than this is no evidence
ENTRY_MAX = 64 * 1024        # an entry file's bytes at most
PLIST_MAX = 1 << 20
DESKTOP_MAX = 64 * 1024
# "who" is not one: it asks after a person (who is logged in, who has an
# account, who spark is) and names who(1); which and what only pick
STOPWORDS = frozenset((
    "a an and are as at be by can do does for from has have how i if in into is it its me my of on "
    "or so that the their them then there these this to use used using was what when where which "
    "why will with you your").split())
# The index (index.json): BM25F over an entry's fields. Each field's word
# count is normalized by that field's length against the store's average
# for it (b), weighted (w) and summed into one term frequency per entry --
# a number that does not depend on the question, so the build stores it
# and a search only saturates it (grounding.K1). A tag is what an option
# line names before its first gap of two spaces (-h, --human-readable,
# spark serve on) plus, for a spark verb, the words TAB completes. The
# weights were fitted on the audition's recall cases, tuned on half of
# them and checked on the other half (tests/line_audition.py recall).
INDEX_V = 2
FIELDS = ("name", "what", "synopsis", "tags", "lines")
FIELD_W = (4.0, 3.0, 1.0, 0.5, 0.5)
FIELD_B = (0.75, 0.75, 0.75, 0.3, 0.3)


# ------------------------------------------------------------ processes
def abs_path():
    """$PATH with its empty and relative entries dropped: an entry like
    `.` or `bin` resolves against a directory someone else chose -- a
    `man` or a HEAD planted there is not the machine's."""
    return os.pathsep.join(d for d in (os.environ.get("PATH") or "").split(os.pathsep) if os.path.isabs(d))


def killpg(p):
    """SIGKILL to a process's whole group (its own session)."""
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass


def bounded(argv, cwd, env, seconds, cap):
    """(rc, text) of `argv` in its own session, stdout only, read in a
    bounded loop: `cap` bytes at most, `seconds` at most (rc 124), the
    process group killed either way. (-1, '') when it cannot start."""
    try:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return -1, ""
    buf, fd, end, timed = b"", p.stdout.fileno(), time.monotonic() + seconds, False
    try:
        while len(buf) < cap:
            left = end - time.monotonic()
            if left <= 0:
                timed = True
                break
            if not select.select([fd], [], [], min(left, 0.2))[0]:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
        if not timed and len(buf) < cap:
            try:
                p.wait(timeout=max(0.05, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed = True
    finally:
        killpg(p)                     # groff and friends must not linger
        p.stdout.close()
        try:
            p.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    return (124 if timed else p.returncode), buf[:cap].decode("utf-8", "replace")


def _man_env():
    """The one environment a manual renders in: nothing of the caller's
    but PATH and HOME (no MANOPT, MANROFFOPT, GROFF_* or pager)."""
    return {"PATH": abs_path(), "HOME": HOME, "LC_ALL": "C", "MANWIDTH": str(MAN_WIDTH),
            "MANPAGER": "cat", "PAGER": "cat"}


def man_page(head):
    """`man HEAD` as text -- man found on abs_path, run from /, in the
    one clean environment (MANPAGER=cat: `man -P cat` fails on the mandoc
    man Void ships), overstrikes and escapes dropped; '' when man is
    missing, fails, or outlives MAN_TIMEOUT."""
    man = shutil.which("man", path=abs_path())
    if not man:
        return ""
    rc, out = bounded([man, head], "/", _man_env(), MAN_TIMEOUT, MAN_TEXT_MAX)
    return textmod.scrub(out) if rc == 0 else ""


def render(path, root):
    """The page file `path` as text: mandoc -T ascii where mandoc is on
    the PATH, else `man -l`; cwd the man root `root`; '' on failure."""
    ap = abs_path()
    mandoc = shutil.which("mandoc", path=ap)
    if mandoc:
        argv = [mandoc, "-T", "ascii", "-O", "width=%d" % MAN_WIDTH, path]
    else:
        man = shutil.which("man", path=ap)
        if not man:
            return ""
        argv = [man, "-l", path]
    rc, out = bounded(argv, root if os.path.isdir(root) else "/", _man_env(), MAN_TIMEOUT, MAN_TEXT_MAX)
    return _scrub(out) if out.strip() and rc != 124 else ""


_CONTROL = re.compile("[\x00-\x09\x0b-\x1f\x7f]")


def _scrub(s):
    """text.scrub, newlines kept, tabs as spaces -- and fast: a page with
    no control character left once the overstrikes are gone (most pages)
    skips scrub's character walk."""
    s = textmod.unstrike(s or "").expandtabs(8)
    return textmod.scrub(s, keep="\n") if _CONTROL.search(s) else s


# ------------------------------------------------------------ words
def _stem(w):
    """Crude suffixes off, the same way for a question and an entry."""
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes", "zes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def words(text):
    """The searchable words of `text`: lowercase, split on anything not a
    letter or a digit, one-letter words and STOPWORDS dropped, crude
    suffixes off. The one tokenizer: grounding reads questions with it."""
    out = []
    for w in re.split(r"[^a-z0-9]+", (text or "").lower()):
        if len(w) < 2 or w in STOPWORDS:
            continue
        out.append(_stem(w))
    return out


def line_parts(line):
    """(tag, sentence) of an option line: a (tag, sentence) pair as it is;
    a string split at its first gap of two spaces (a line with no gap is
    all tag)."""
    if isinstance(line, (list, tuple)):
        return (str(line[0]) if line else ""), " ".join(str(x) for x in line[1:] if x)
    parts = re.split(r"\s{2,}|\t", str(line or "").strip(), maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def entry_terms(e):
    """{term: [count in each of FIELDS]} of an entry (a dict or an Entry):
    name, what, synopsis, the option lines' tags (and a spark verb's
    completed words), the option lines' sentences."""
    get = e.get if isinstance(e, dict) else (lambda k, d=None: getattr(e, k, d))
    opts = get("options") or {}
    said = opts.get("words", ()) if isinstance(opts, dict) else getattr(opts, "words", ())
    pairs = [line_parts(l) for l in get("lines") or ()]
    extra = [w for w in said or () if not str(w).startswith("-")] if get("kind") == "spark" else []
    syn = get("synopsis") or ""
    bodies = (get("name") or "", get("what") or "", syn if isinstance(syn, str) else "\n".join(syn),
              "\n".join([p[0] for p in pairs] + extra), "\n".join(p[1] for p in pairs))
    tf = {}
    for f, body in enumerate(bodies):
        for t in words(body):
            tf.setdefault(t, [0] * len(FIELDS))[f] += 1
    return tf


def index_of(tfs):
    """index.json's searchable half over [(name, entry_terms(entry))], names
    sorted: {"v", "names", "post"}, post term -> "i:tf ..." with tf the
    entry's BM25F term frequency (FIELD_W, FIELD_B, each field against
    the store's average length for it), two decimals."""
    n = len(FIELDS)
    tfs = sorted(((name, {t: c for t, c in (tf or {}).items() if isinstance(c, list) and len(c) == n})
                  for name, tf in tfs), key=lambda nt: nt[0])
    lens = [[sum(c[f] for c in tf.values()) for f in range(n)] for _name, tf in tfs]
    avg = [(sum(l[f] for l in lens) / float(len(lens)) if lens else 0.0) or 1.0 for f in range(n)]
    post = {}
    for i, (_name, tf) in enumerate(tfs):
        norm = [FIELD_W[f] / (1 - FIELD_B[f] + FIELD_B[f] * lens[i][f] / avg[f]) for f in range(n)]
        for t in sorted(tf):
            x = sum(c * norm[f] for f, c in enumerate(tf[t]) if c)
            if x > 0:
                post.setdefault(t, []).append("%d:%s" % (i, ("%.2f" % max(x, 0.01)).rstrip("0").rstrip(".")))
    return {"v": INDEX_V, "names": [name for name, _tf in tfs], "post": {t: " ".join(v) for t, v in post.items()}}


# ------------------------------------------------------------ text
_ROFF = (
    (re.compile(r"\\f(?:\[[^\]]*\]|\(..|.)"), ""),   # font changes
    (re.compile(r"\\s[+-]?\d+"), ""),                 # size changes
    (re.compile(r"\\\*(?:\[[^\]]*\]|\(..|.)"), ""),  # strings
    (re.compile(r"\\\((?:em|en|hy)"), "-"),
    (re.compile(r"\\\((?:lq|rq|dq)"), '"'),
    (re.compile(r"\\\((?:aq|oq|cq)"), "'"),
    (re.compile(r"\\\(.."), ""),
    (re.compile(r"\\\[[^\]]*\]"), ""),
    (re.compile(r"\\[-]"), "-"),
    (re.compile(r"\\[&|^c%]"), ""),
    (re.compile(r"\\[ ~0]"), " "),
    (re.compile(r"\\e"), "\\\\"),
)


def _roff_text(s):
    for pat, rep in _ROFF:
        s = pat.sub(rep, s)
    return " ".join(s.replace('"', " ").split()) if s.count('"') > 1 and s.startswith('"') else " ".join(s.split())


def page_what(src):
    """The one line a page's NAME section says, from its source: mdoc's
    `.Nd`, or the words after `name \\-` below `.SH NAME`; '' when neither."""
    m = re.search(r"^\.Nd\s+(.+)$", src, re.M)
    if m:
        return _roff_text(m.group(1))
    m = re.search(r'^\.S[Hh]\s+"?NAME"?\s*$', src, re.M)
    if not m:
        return ""
    got = []
    for line in src[m.end():].splitlines():
        if line.startswith((".SH", ".Sh", ".SS", ".Ss")):
            break
        if line.startswith((".", "'")):
            parts = line.split(None, 1)
            if parts and parts[0] in (".B", ".I", ".BR", ".IR", ".RB", ".RI", ".BI", ".IB", ".Nm") and len(parts) > 1:
                got.append(parts[1])
            continue
        got.append(line)
        if len(" ".join(got)) > 400:
            break
    text = _roff_text(" ".join(got))
    for sep in (" - ", " -- "):
        if sep in text:
            return text.split(sep, 1)[1].strip()
    return ""


_FLAG = re.compile(r"(?<![\w/.:=+\-])(--?)([A-Za-z0-9?@#][A-Za-z0-9_.+#?@-]*)")
_BRACKET = re.compile(r"\[-([A-Za-z0-9@%#,]+)\]")


def option_set(text, synopsis=""):
    """The OptionSet a text names: every `--word` long, every `-x` short,
    every `-word` a word; a synopsis's `[-abc]` gives each letter."""
    long_, short, words_ = set(), set(), set()
    for m in _FLAG.finditer(text):
        dash, body = m.group(1), m.group(2).rstrip(".-,")
        if not body:
            continue
        if dash == "--":
            if len(body) > 1:
                long_.add("--" + body)
        elif len(body) == 1:
            short.add("-" + body)
        else:
            words_.add("-" + body)
    for m in _BRACKET.finditer(synopsis):
        for ch in m.group(1):
            if ch.isalnum() or ch in "@%#":
                short.add("-" + ch)
    cut = lambda s: tuple(sorted(s)[:OPTION_SET_MAX])     # noqa: E731
    return OptionSet(cut(long_), cut(short), cut(words_))


_HEAD = re.compile(r"^([A-Z][A-Z0-9 ,/&()'-]*[A-Z0-9)])\s*$")


def sections(text):
    """[(heading, [lines])] of a rendered page: a heading is an all-caps
    line at column 0 (the running header and footer carry lower case)."""
    out, cur = [], None
    for line in text.splitlines():
        if line and not line[0].isspace() and _HEAD.match(line):
            cur = (line.strip(), [])
            out.append(cur)
        elif cur is not None:
            cur[1].append(line.rstrip())
    return out


def _first_sentence(s):
    s = " ".join(s.split())
    m = re.search(r"(?<=[a-z0-9)\]'\"])\.(?:\s|$)", s)
    return s[:m.start() + 1] if m else s


def option_lines(lines, limit=OPTION_LINES):
    """Each line that starts with a flag, with its first sentence: from the
    same line past a gap of 2 spaces, else from the lines indented under
    it. OPTION_CHARS each, `limit` lines."""
    out = []
    for i, line in enumerate(lines):
        s = line.strip()
        if len(s) < 2 or s[0] != "-" or s[1] in " -\t" and not s.startswith("--"):
            continue
        if s.startswith("--") and (len(s) < 3 or not s[2].isalnum()):
            continue
        indent = len(line) - len(line.lstrip())
        parts = re.split(r"\s{2,}|\t", s, maxsplit=1)
        flag, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        if not rest:
            more = []
            for nxt in lines[i + 1:i + 6]:
                if not nxt.strip() or len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                more.append(nxt.strip())
            rest = " ".join(more)
        sent = _first_sentence(rest)
        out.append((flag + ("  " + sent if sent else ""))[:OPTION_CHARS].rstrip())
        if len(out) >= limit:
            break
    return out


def read_page(text, src_what=""):
    """(what, synopsis, lines, options) of a rendered page."""
    what, syn, lines, keep = src_what, [], [], []
    for head, body in sections(text):
        if head == "NAME" and not what:
            joined = " ".join(" ".join(body).split())
            for sep in (" - ", " -- "):
                if sep in joined:
                    what = joined.split(sep, 1)[1].strip()
                    break
        elif head == "SYNOPSIS":
            syn = [" ".join(l.split()) for l in body if l.strip()]
        elif head not in SKIP_SECTIONS and head != "NAME":
            keep.extend(body)
    synopsis = _cut_lines(syn, SYNOPSIS_LINES, SYNOPSIS_CHARS)
    lines = option_lines(keep)
    return what, synopsis, lines, option_set(text, "\n".join(syn))


def _cut_lines(lines, n, chars):
    out = "\n".join(lines[:n])
    return out if len(out) <= chars else out[:chars].rsplit(" ", 1)[0]


def read_help(text):
    """(what, synopsis, lines, options) of a --help text, or None when it
    names no option and says no `usage` (not a help text at all)."""
    opts = option_set(text)
    if not (opts.long or opts.short or opts.words) and "usage" not in text.lower():
        return None
    ls = [l.rstrip() for l in text.splitlines()]
    usage = [" ".join(l.split()) for l in ls if l.strip().lower().startswith("usage")]
    what = next((" ".join(l.split()) for l in ls if l.strip() and not l.strip().lower().startswith("usage")
                 and not l.strip().startswith("-")), "")
    return what[:OPTION_CHARS], _cut_lines(usage, SYNOPSIS_LINES, SYNOPSIS_CHARS), option_lines(ls), opts


class _Clean:
    """Every harvested text: scrubbed, the home as ~, secrets held; the
    spans held counted."""

    def __init__(self, extra=()):
        homes = {HOME, os.path.realpath(HOME)} | set(extra)
        self.homes = sorted((h for h in homes if h and h != "/"), key=len, reverse=True)
        self.held = 0

    def __call__(self, s):
        s = textmod.utf8(_scrub(s))
        for h in self.homes:
            s = s.replace(h, "~")
        spans, _names = textmod.held_spans(s)
        if spans:
            self.held += len(spans)
            s = textmod.hold_spans(s, spans)
        return s

    def parsed(self, what, synopsis, lines, opts):
        """A parsed page or help, every kept field through this: the whole
        text is parsed as it came, and only what is kept is held -- the
        hold's regexes over a 256 kB page cost seconds a build. A flag
        that looks like a secret is dropped and counted."""
        def flags(ts):
            if not textmod.held_spans("\n".join(ts))[0]:
                return tuple(ts)                  # one look for the common case
            keep = []
            for t in ts:
                if textmod.held_spans(t)[0]:
                    self.held += 1
                else:
                    keep.append(t)
            return tuple(keep)
        return (self(what), self(synopsis), [self(l) for l in lines],
                OptionSet(flags(opts.long), flags(opts.short), flags(opts.words)))


def _visible_name(s, n=80):
    return sandbox.visible(textmod.scrub(s or ""))[:n].strip()


# ------------------------------------------------------------ files
def _stamp(st):
    return [int(st.st_mtime), st.st_size]


def _key_st(st):
    return [st.st_mtime_ns, st.st_size, st.st_ino]


def _trusted(st, directory=False):
    """Owned by root or this user; a directory not world-writable."""
    if st.st_uid not in (0, os.geteuid()):
        return False
    return not (directory and st.st_mode & stat.S_IWOTH)


def _remote_mounts():
    """[(mount point, fstype)] of the remote filesystems (Linux)."""
    out = []
    try:
        with open("/proc/self/mounts", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split()
                if len(p) >= 3 and (p[2] in REMOTE_FS or p[2].startswith("fuse")):
                    out.append(p[1].replace("\\040", " "))
    except OSError:
        pass
    return out


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _read_bytes(path, cap):
    try:
        st = os.stat(path)
        if st.st_size > cap:
            return None
        with open(path, "rb") as f:
            return f.read(cap + 1)[:cap]
    except OSError:
        return None


def _page_source(path):
    """A page file's text, gunzipped, or None (missing, too large)."""
    data = _read_bytes(path, MAN_FILE_MAX)
    if data is None:
        return None
    if path.endswith(".gz"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                data = g.read(4 * MAN_FILE_MAX)
        except (OSError, EOFError):
            return None
    return data.decode("utf-8", "replace")


_SO = re.compile(r"\A(?:(?:\.\\\"|'\\\"|\.\s*$)[^\n]*\n|\s*\n)*\.so\s+(\S+)", re.M)


def resolve(path, root, hops=3):
    """(page file, its source) after following `.so` lines inside the man
    root `root` -- never an absolute target, never out through `..`;
    (None, None) when it leaves, loops or is missing."""
    real_root = os.path.realpath(root)
    for _ in range(hops + 1):
        src = _page_source(path)
        if src is None:
            return None, None
        m = _SO.match(src)
        if not m:
            return path, src
        target = m.group(1)
        if target.startswith("/") or ".." in target.split("/"):
            return None, None
        cand = os.path.join(root, target)
        if not os.path.exists(cand) and os.path.exists(cand + ".gz"):
            cand += ".gz"
        if not _under(os.path.realpath(cand), real_root):
            return None, None
        path = cand
    return None, None


# ------------------------------------------------------------ the places
def _tilde(p):
    return os.path.join(HOME, p[2:]) if p.startswith("~/") else p


def program_dirs(remembered=()):
    """The dirs programs are read from, in order: SPARK_KNOWLEDGE_PATH
    alone when set (tests), else the absolute PATH, the standard dirs,
    ~/.local/bin and the dirs an earlier build saw -- each once (by real
    path), each a directory."""
    seam = os.environ.get("SPARK_KNOWLEDGE_PATH")
    if seam is not None:
        cands = seam.split(os.pathsep)
    else:
        cands = abs_path().split(os.pathsep) + list(STANDARD_BIN) + [BIN_DIR] + list(remembered)
    out, seen = [], set()
    for d in cands:
        if not d or not os.path.isabs(d) or not os.path.isdir(d):
            continue
        r = os.path.realpath(d)
        if r not in seen:
            seen.add(r)
            out.append(d)
    return out


def _manpath_files():
    out = []
    for f in MANPATH_FILES + tuple(sorted(glob.glob(os.path.join(MANPATH_D, "*")))):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    w = line.split("#", 1)[0].split()
                    if not w:
                        continue
                    if len(w) == 1 and w[0].startswith("/"):
                        out.append(w[0])                    # /etc/manpaths: one dir a line
                    elif w[0] in ("MANDATORY_MANPATH", "MANDB_MAP", "manpath") and len(w) > 1:
                        out.append(w[1])
                    elif w[0] == "MANPATH_MAP" and len(w) > 2:
                        out.append(w[2])
        except OSError:
            pass
    return out


def man_dirs(prog_dirs):
    """The man roots, in order: SPARK_KNOWLEDGE_MANPATH alone when set
    (tests), else $MANPATH, each program dir's ../share/man and ../man,
    the files that list man dirs, and the standard ones."""
    seam = os.environ.get("SPARK_KNOWLEDGE_MANPATH")
    if seam is not None:
        cands = seam.split(os.pathsep)
    else:
        cands = [d for d in (os.environ.get("MANPATH") or "").split(os.pathsep)]
        for d in prog_dirs:
            cands += [os.path.join(os.path.dirname(d), "share", "man"), os.path.join(os.path.dirname(d), "man")]
        cands += _manpath_files() + list(STANDARD_MAN)
    out, seen = [], set()
    for d in cands:
        if not d or not os.path.isabs(d) or not os.path.isdir(d):
            continue
        r = os.path.realpath(d)
        if r not in seen:
            seen.add(r)
            out.append(d)
    return out


def app_dirs():
    """Where .desktop files and .app bundles live: SPARK_KNOWLEDGE_APPS
    alone when set (tests), else the XDG data dirs' applications/, the
    flatpak exports and, on macOS, the Applications folders."""
    seam = os.environ.get("SPARK_KNOWLEDGE_APPS")
    if seam is not None:
        cands = seam.split(os.pathsep)
    else:
        data = [os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")]
        data += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(os.pathsep)
        cands = [os.path.join(d, "applications") for d in data] + [_tilde(d) for d in FLATPAK_APPS]
        if IS_MAC:
            cands += [_tilde(d) for d in MAC_APP_DIRS]
    return [d for d in dict.fromkeys(cands) if d and os.path.isabs(d) and os.path.isdir(d)]


def _db_paths():
    out = [DPKG_STATUS, PACMAN_LOCAL, XBPS_DB, MACOS_VERSION]
    for r in BREW_ROOTS:
        out += [os.path.join(r, "Cellar"), os.path.join(r, "Caskroom")]
    return out


def tree_stamp():
    """spark's own tree, as a stamp: bin/spark, completion.bash and every
    lib/spark/*.py (mtime, size). A new one rebuilds every entry."""
    files = [os.path.join(REPO, "bin", "spark"), os.path.join(REPO, "home", ".config", "spark", "completion.bash")]
    files += sorted(glob.glob(os.path.join(REPO, "lib", "spark", "*.py")))
    h = hashlib.sha256()
    for f in files:
        try:
            st = os.stat(f)
            h.update(("%s %d %d\n" % (os.path.basename(f), st.st_mtime_ns, st.st_size)).encode())
        except OSError:
            h.update(("%s -\n" % f).encode())
    return h.hexdigest()[:24]


def _places(meta):
    progs = program_dirs(meta.get("path") or ())
    mans = man_dirs(progs)
    return progs, mans, app_dirs()


def stamps(meta=None):
    """What this machine has, path by path: the package databases, the
    program dirs, the man dirs (and their sections), the app dirs --
    each one's "mtime size" (or "-" when absent), and spark's tree. A
    cheap stat each; fingerprint() hashes it, changed() compares it."""
    progs, mans, apps = _places(meta or {})
    paths = list(progs) + list(apps) + _db_paths()
    for m in mans:
        paths.append(m)
        paths += [os.path.join(m, "man" + s) for s in SECTIONS]
    out = {}
    for p in paths:
        try:
            st = os.stat(p)
            out[p] = "%d %d" % (st.st_mtime_ns, st.st_size)
        except OSError:
            out[p] = "-"
    out["spark tree"] = tree_stamp()
    return out


def fingerprint(meta=None, stamped=None):
    """The machine's stamps() as one short hash."""
    h = hashlib.sha256()
    for p, v in (stamped if stamped is not None else stamps(meta)).items():
        h.update(("%s %s\n" % (p, v)).encode())
    return h.hexdigest()[:32]


def changed(meta=None):
    """The paths whose stamp moved since the build (a stale store's why):
    [path], empty when the store is fresh or keeps no stamps."""
    meta = meta if meta is not None else summary()
    was = meta.get("stamps") or {}
    now = stamps(meta)
    return sorted(p for p in set(was) | set(now) if was.get(p) != now.get(p))


# ------------------------------------------------------------ owners
class Owners:
    """Who installed a file, and the package's one-line summary: dpkg,
    pacman, xbps or Homebrew, asked once per build and only for the paths
    a rebuilt entry needs; the OS's own dirs on macOS are "macos". The
    database roots are module names, so a test can point them anywhere."""

    def __init__(self, paths):
        self.paths = set(p for p in paths if p)
        self.owner, self.summary, self._brew = {}, {}, {}
        try:
            if os.path.isdir(DPKG_INFO):
                self._dpkg()
            elif os.path.isdir(PACMAN_LOCAL):
                self._pacman()
            elif os.path.isdir(XBPS_DB):
                self._xbps()
        except Exception:
            log_exc("intake.Owners")

    def _dpkg(self):
        for f in os.listdir(DPKG_INFO):
            if not f.endswith(".list"):
                continue
            pkg = f[:-5].split(":")[0]
            try:
                with open(os.path.join(DPKG_INFO, f), encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        p = line.rstrip("\n")
                        if p in self.paths:
                            self.owner[p] = "dpkg:" + pkg
            except OSError:
                pass
        try:
            with open(DPKG_STATUS, encoding="utf-8", errors="replace") as fh:
                self.summary.update(parse_dpkg_status(fh.read()))
        except OSError:
            pass

    def _pacman(self):
        for d in os.listdir(PACMAN_LOCAL):
            base = os.path.join(PACMAN_LOCAL, d)
            try:
                with open(os.path.join(base, "desc"), encoding="utf-8", errors="replace") as fh:
                    name, desc = parse_pacman_desc(fh.read())
            except OSError:
                continue
            if name:
                self.summary[name] = desc
            try:
                with open(os.path.join(base, "files"), encoding="utf-8", errors="replace") as fh:
                    for p in parse_pacman_files(fh.read()):
                        if p in self.paths:
                            self.owner[p] = "pacman:" + name
            except OSError:
                pass

    def _xbps(self):
        rc, out = run(["xbps-query", "-l"], timeout=30)
        if rc == 0:
            self.summary.update(parse_xbps_list(out))
        for d in sorted({os.path.dirname(p) for p in self.paths}):
            rc, out = run(["xbps-query", "-o", os.path.join(d, "*")], timeout=30)
            if rc == 0:
                for p, pkg in parse_xbps_owners(out).items():
                    if p in self.paths:
                        self.owner[p] = "xbps:" + pkg

    def _brew_desc(self, cellar, pkg, ver):
        k = (cellar, pkg)
        if k not in self._brew:
            src = _read_bytes(os.path.join(cellar, pkg, ver, ".brew", pkg + ".rb"), 256 * 1024)
            m = re.search(r'^\s*desc\s+"((?:[^"\\]|\\.)*)"', (src or b"").decode("utf-8", "replace"), re.M)
            self._brew[k] = m.group(1) if m else ""
        return self._brew[k]

    def of(self, path, real=None):
        """(origin, summary) of a file."""
        real = real or path
        for p in (path, real):
            if p in self.owner:
                o = self.owner[p]
                return o, self.summary.get(o.split(":", 1)[1], "")
        m = re.search(r"^(.*/Cellar)/([^/]+)/([^/]+)/", real)
        if m:
            return "brew:" + m.group(2), self._brew_desc(m.group(1), m.group(2), m.group(3))
        if IS_MAC and real.startswith(MACOS_DIRS):
            return "macos", ""
        return "local", ""


def parse_dpkg_status(text):
    """{package: its Description's first line} from /var/lib/dpkg/status."""
    out = {}
    for block in text.split("\n\n"):
        name = re.search(r"^Package:\s*(\S+)", block, re.M)
        desc = re.search(r"^Description:\s*(.*)$", block, re.M)
        if name:
            out[name.group(1)] = desc.group(1).strip() if desc else ""
    return out


def parse_pacman_desc(text):
    """(name, description) from a pacman local/<pkg>/desc file."""
    fields, key = {}, None
    for line in text.splitlines():
        if line.startswith("%") and line.endswith("%"):
            key = line.strip("%")
        elif key and line and key not in fields:
            fields[key] = line
    return fields.get("NAME", ""), fields.get("DESC", "")


def parse_pacman_files(text):
    """Every path a pacman local/<pkg>/files file lists, absolute."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("%"):
            inside = line == "%FILES%"
        elif inside and line and not line.endswith("/"):
            out.append("/" + line)
    return out


def _pkgname(pkgver):
    return pkgver.rsplit("-", 1)[0] if "-" in pkgver else pkgver


def parse_xbps_list(text):
    """{package: summary} from `xbps-query -l` (ii NAME-VER_REV summary)."""
    out = {}
    for line in text.splitlines():
        p = line.split(None, 2)
        if len(p) >= 2:
            out[_pkgname(p[1])] = p[2].strip() if len(p) > 2 else ""
    return out


def parse_xbps_owners(text):
    """{path: package} from `xbps-query -o PATTERN` (NAME-VER_REV: PATH (type))."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(\S+):\s+(/\S+)", line)
        if m:
            out[m.group(2)] = _pkgname(m.group(1))
    return out


# ------------------------------------------------------------ sources
Prog = namedtuple("Prog", "name path real st home")


def scan_programs(dirs):
    """({name: Prog}, skipped): the first executable of each name; a dir
    on a remote filesystem not listed; a dir or file of another owner, a
    world-writable dir, skipped and counted; spark's own tree is spark's
    source, not a program."""
    progs, skipped = {}, 0
    remote = _remote_mounts() if not IS_MAC else []
    home = os.path.realpath(HOME)
    repo = os.path.realpath(REPO)
    for d in dirs:
        real_d = os.path.realpath(d)
        if any(_under(real_d, m) for m in remote):
            continue
        try:
            dst = os.stat(d)
            names = sorted(os.listdir(d))
        except OSError:
            continue
        if not _trusted(dst, directory=True):
            skipped += len(names)
            continue
        for n in names:
            if n in progs or not NAME_SHAPE.match(n):
                continue
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or not st.st_mode & 0o111:
                continue
            real = os.path.realpath(p)
            if _under(real, repo):
                continue
            if not _trusted(st):
                skipped += 1
                continue
            progs[n] = Prog(n, p, real, st, _under(real, home))
            if len(progs) >= MAX_ENTRIES:
                return progs, skipped
    return progs, skipped


def _root_pages(root, cache):
    """{name: page file} of one man root (sections 1, 8, 6), cached."""
    if root in cache:
        return cache[root]
    out = {}
    try:
        rst = os.stat(root)
        ok = _trusted(rst, directory=True)
    except OSError:
        ok = False
    if ok:
        for sec in SECTIONS:
            d = os.path.join(root, "man" + sec)
            try:
                if not _trusted(os.stat(d), directory=True):
                    continue
                files = sorted(os.listdir(d))
            except OSError:
                continue
            for f in files:
                m = PAGE_FILE.match(f)
                if m and m.group("sec")[0] == sec and NAME_SHAPE.match(m.group("name")):
                    out.setdefault(m.group("name"), os.path.join(d, f))
    cache[root] = out
    return out


def page_index(roots, cache):
    """{name: (root, page file)}: section 1 in every root first, then 8,
    then 6 -- the order man searches."""
    idx = {}
    for sec in SECTIONS:
        for root in roots:
            for name, path in _root_pages(root, cache).items():
                if name not in idx and os.path.basename(os.path.dirname(path)) == "man" + sec:
                    idx[name] = (root, path)
    return idx


def tied_page(prog, idx, cache):
    """(root, page) of a program: its real dir's ../share/man and ../man
    first (by its name, then its real name), then the index."""
    base = os.path.dirname(os.path.dirname(prog.real))
    names = [prog.name] + ([os.path.basename(prog.real)] if os.path.basename(prog.real) != prog.name else [])
    for root in (os.path.join(base, "share", "man"), os.path.join(base, "man")):
        if os.path.isdir(root):
            pages = _root_pages(root, cache)
            for n in names:
                if n in pages:
                    return root, pages[n]
    for n in names:
        if n in idx:
            return idx[n]
    return None


def parse_desktop(text):
    """{key: value} of a .desktop file's [Desktop Entry] group, the
    unlocalised keys only."""
    group, d = None, {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            group = line
            continue
        if group != "[Desktop Entry]" or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if "[" not in k:
            d.setdefault(k, v.strip())
    return d


def _exec_name(value):
    """The program an Exec or TryExec line runs, its basename only, never
    its arguments ('' when there is none a name can hold)."""
    value = DESKTOP_CODES.sub("", value or "").replace("%%", "%")
    try:
        argv = shlex.split(value)
    except ValueError:
        argv = value.split()
    while argv and (argv[0] == "env" or "=" in argv[0]):
        argv = argv[1:]
    name = os.path.basename(argv[0]) if argv else ""
    return name if NAME_SHAPE.match(name) else ""


App = namedtuple("App", "name display comment run origin file st source")


def scan_apps(dirs, progs, owners_of):
    """{key: App}: each .desktop and each .app bundle in `dirs`, keyed by
    the name of the program it runs; the first of a key wins."""
    apps = {}
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        flat = "/flatpak/exports/" in d.replace(os.sep, "/")
        for f in names:
            p = os.path.join(d, f)
            if f.endswith(".desktop"):
                app = _desktop_app(p, f, flat, progs, owners_of)
            elif f.endswith(".app") and os.path.isdir(p):
                app = _bundle_app(p, f)
            else:
                continue
            if app and app.name not in apps:
                apps[app.name] = app
    return apps


def _desktop_app(p, f, flat, progs, owners_of):
    try:
        st = os.stat(p)
    except OSError:
        return None
    if not _trusted(st):
        return None
    data = _read_bytes(p, DESKTOP_MAX)
    if data is None:
        return None
    d = parse_desktop(data.decode("utf-8", "replace"))
    if d.get("Type", "Application") != "Application" or d.get("NoDisplay") == "true" or d.get("Hidden") == "true":
        return None
    try_exec = d.get("TryExec", "")
    if try_exec:
        t = _exec_name(try_exec)
        if not t or (t not in progs and not (os.path.isabs(try_exec) and os.access(try_exec, os.X_OK))):
            return None
    if flat:
        key = f[:-len(".desktop")]
        if not NAME_SHAPE.match(key):
            return None
        return App(key, _visible_name(d.get("Name", key)), d.get("Comment") or d.get("GenericName", ""),
                   "flatpak run " + key, "flatpak", p, st, "desktop")
    key = _exec_name(d.get("Exec", ""))
    if not key:
        return None
    return App(key, _visible_name(d.get("Name", key)), d.get("Comment") or d.get("GenericName", ""),
               key, owners_of(p), p, st, "desktop")


def _bundle_app(p, f):
    plist = os.path.join(p, "Contents", "Info.plist")
    try:
        st = os.stat(plist)
    except OSError:
        return None
    if not _trusted(st):
        return None
    data = _read_bytes(plist, PLIST_MAX)
    if data is None:
        return None
    try:
        info = plistlib.loads(data)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    exe = info.get("CFBundleExecutable")
    key = os.path.basename(exe) if isinstance(exe, str) else ""
    if not NAME_SHAPE.match(key or ""):
        return None
    display = _visible_name(f[:-len(".app")])
    if not display:
        return None
    origin = "macos" if p.startswith("/System/") else "local"
    return App(key, display, "", "open -a " + shlex.quote(display), origin, plist, st, "app")


def _app_line(app):
    what = (app.display + (" -- " + " ".join(app.comment.split()) if app.comment else ""))[:120]
    return "app: %s (%s)" % (what, app.run)


# ------------------------------------------------------------ spark's tree
def spark_words():
    """({verb: [words it takes]}, [verbs]) from completion.bash -- the
    list smoke's drift guard holds equal to bin/spark's VERBS."""
    path = os.path.join(REPO, "home", ".config", "spark", "completion.bash")
    try:
        with open(path, encoding="utf-8") as f:
            comp = f.read()
    except OSError:
        return {}, []
    m = re.search(r'COMP_CWORD"? -eq 1 \]; then\s*words="([^"]*)"', comp)
    verbs = m.group(1).split() if m else []
    fills = tree_names()
    subs = {}
    for arm, ws in re.findall(r"^\s*([a-z][a-z |-]*)\)\s+words=\"([^\"]*)\"", comp, re.M):
        plain = re.sub(r"\$\((\w+)\)", lambda m: " %s " % " ".join(fills.get(m.group(1), ())), ws)
        plain = re.sub(r"\$\([^)]*\)", " ", plain).split()
        for v in arm.split("|"):
            subs[v.strip()] = plain
    return subs, verbs


def tree_names():
    """What completion.bash's helpers fill a slot with, read from the tree
    the same way they read it: {"_spark_theme_names": the palettes in
    themes/, "_spark_model_names": models.env's MODEL_X keys as x (the
    _LICENSE, _NOTE and _TESTED keys are not models)}. The repository's
    own only: a person's palettes and models are theirs."""
    themes = sorted(f[:-4] for f in _listdir(os.path.join(REPO, "themes")) if f.endswith(".env"))
    try:
        with open(os.path.join(REPO, "models.env"), encoding="utf-8") as f:
            keys = re.findall(r"^MODEL_([A-Z0-9_]*)=", f.read(), re.M)
    except OSError:
        keys = []
    models = [k.lower().replace("_", "-") for k in keys if not k.endswith(("_LICENSE", "_NOTE", "_TESTED"))]
    return {"_spark_theme_names": themes, "_spark_model_names": list(dict.fromkeys(models))}


def _listdir(d):
    try:
        return os.listdir(d)
    except OSError:
        return []


def spark_slots():
    """{verb: [(slot, what)]} from bin/spark's USAGE_* text: the column
    before 30 is the slot, after it the words; a verb is the word after
    `spark` (and after each `|`)."""
    try:
        with open(os.path.join(REPO, "bin", "spark"), encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return {}
    out, last = {}, None
    for block in re.findall(r'^USAGE_\w+ = """(.*?)"""', src, re.S | re.M):
        for line in block.splitlines():
            if not line.startswith(" ") or not line.strip():
                last = None
                continue
            left, right = line[:30].strip(), " ".join(line[30:].split())
            if not left and last is not None:
                last[1].append(right)
                continue
            w = left.split()
            if len(w) < 2 or w[0] != "spark" or not NAME_SHAPE.match(w[1]):
                last = None
                continue
            vs = [w[1]] + [w[i + 1] for i, x in enumerate(w[:-1]) if x == "|" and NAME_SHAPE.match(w[i + 1])]
            last = (left, [right] if right else [])
            for v in vs:
                out.setdefault(v, []).append(last)
    return {v: [(s, " ".join(ws)) for s, ws in lst] for v, lst in out.items()}


def spark_entry(verb, body, subs, slots):
    """(name, what, synopsis, options, lines) of `spark VERB -h`'s text
    (`spark help`'s for None): what from its first line (`spark serve --
    the engine...`, else the help's words for it), the synopsis from the
    help's column, the options it names plus the words TAB completes,
    the rest of its lines as its lines. The one reading: the store's and
    the audition's snapshot store's spark entries are the same."""
    name = "spark" if verb is None else "spark " + verb
    ls = [l.strip() for l in (body or "").splitlines() if l.strip()]
    what = ""
    if ls:
        m = re.match(r"^spark(?: \S+)? -- (.*)$", ls[0])
        what = m.group(1) if m else ""
    sl = slots.get(verb, []) if verb else []
    what = what or (sl[0][1] if sl else "")
    synopsis = _cut_lines([s for s, _w in sl], SYNOPSIS_LINES, SYNOPSIS_CHARS)
    opts = option_set(body or "")
    extra = subs.get(verb, []) if verb else []
    long_ = tuple(sorted(set(opts.long) | {w for w in extra if w.startswith("--")}))
    plain = tuple(sorted({w for w in extra if not w.startswith("-")}))
    opts = OptionSet(long_, opts.short, plain if verb else opts.words)
    lines = [l[:OPTION_CHARS] for l in ls[1:1 + OPTION_LINES]]
    return name, what, synopsis, opts, lines


def spark_help(verb, scratch):
    """`spark VERB -h` (`spark help` for None) from the repo's own
    bin/spark with this python, an empty home and config, 5 seconds."""
    env = {"PATH": abs_path(), "HOME": scratch, "LC_ALL": "C", "TERM": "dumb", "NO_COLOR": "1",
           "XDG_CONFIG_HOME": os.path.join(scratch, "config"), "XDG_STATE_HOME": os.path.join(scratch, "state"),
           "XDG_DATA_HOME": os.path.join(scratch, "data")}
    argv = [sys.executable, os.path.join(REPO, "bin", "spark")] + (["help"] if verb is None else [verb, "-h"])
    rc, out = bounded(argv, "/", env, SPARK_SECONDS, 65536)
    return out if rc == 0 else ""


# ------------------------------------------------------------ the store
def _know_dir(root=None):
    """The store: `root`, else SPARK_KNOWLEDGE_DIR (a fixture's), else
    STATE_DIR/knowledge."""
    return root or os.environ.get("SPARK_KNOWLEDGE_DIR") or KNOW_DIR


SOURCES = ("programs", "apps", "spark")


def _sources():
    """The sources a build reads: SPARK_KNOWLEDGE_SOURCES (a comma list,
    a fixture's) or all of SOURCES."""
    seam = os.environ.get("SPARK_KNOWLEDGE_SOURCES")
    if seam is None:
        return SOURCES
    return tuple(s.strip() for s in seam.split(",") if s.strip() in SOURCES)


def entry_file(name):
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:32] + ".json"


def _load(path, cap=INDEX_MAX):
    try:
        if os.path.getsize(path) > cap:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, obj, sync=True):
    """tmp in the same dir (0600), fsync (`sync`), os.replace. An entry
    skips the fsync: thousands of them cost seconds, and one lost to a
    crash reads as no entry and is rebuilt; the index, docs and meta
    never skip it."""
    data = json.dumps(textmod.clean(obj), separators=(",", ":"), sort_keys=True).encode("utf-8")
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp.", dir=d)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            if sync:
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _entry_from(d):
    try:
        o = d.get("options") or {}
        return Entry(str(d["name"]), str(d["kind"]), str(d["source"]), str(d.get("what", "")),
                     str(d.get("synopsis", "")),
                     OptionSet(tuple(o.get("long", ())), tuple(o.get("short", ())), tuple(o.get("words", ()))),
                     tuple(d.get("lines", ())), str(d.get("origin", "")), tuple(d.get("stamp", ())))
    except (KeyError, TypeError, AttributeError):
        return None


class Store:
    """The repository of entries. LocalStore is this machine's; the
    audition's SnapshotStore reads an OS's help snapshot instead, so a
    question can be grounded in another OS's manuals."""

    def names(self):
        """Every entry's name."""
        raise NotImplementedError

    def entry(self, name):
        """The Entry named `name`, or None."""
        raise NotImplementedError

    def index(self):
        """The searchable words, index_of's shape: {"v", "names", "post"}
        (see grounding), or None when there is no index yet."""
        raise NotImplementedError


class LocalStore(Store):
    """STATE_DIR/knowledge/ on this machine (`root` another). A missing
    store answers empty: no index is no evidence, never an error. The
    index is read once and kept until its file changes; one over
    INDEX_MAX is no index."""

    def __init__(self, root=None):
        self.root = _know_dir(root)
        self._index, self._seen = None, None

    def names(self):
        idx = self.index()
        return list(idx.get("names", ())) if idx else []

    def entry(self, name):
        if not isinstance(name, str) or not name:
            return None
        d = _load(os.path.join(self.root, ENTRIES_DIR, entry_file(name)), ENTRY_MAX)
        if not isinstance(d, dict) or d.get("name") != name:
            return None
        return _entry_from(d)

    def index(self):
        path = os.path.join(self.root, INDEX_FILE)
        try:
            st = os.stat(path)
        except OSError:
            return None
        seen = (st.st_mtime_ns, st.st_size)
        if seen != self._seen:
            d = _load(path, INDEX_MAX)
            self._index = d if isinstance(d, dict) and d.get("v") == INDEX_V else None
            self._seen = seen
        return self._index


def summary(root=None):
    """meta.json as the last build wrote it ({} when none): built, seconds,
    counts by kind, programs, manuals, apps, verbs, skipped, held,
    partial, fingerprint, path."""
    d = _load(os.path.join(_know_dir(root), META_FILE), 1 << 20)
    return d if isinstance(d, dict) else {}


def status():
    """(counts by kind, built epoch or None, stale bool, skipped count) --
    what the check row and the bootstrap row say. Stale: never built, a
    build cut short, or the machine's fingerprint moved since."""
    meta = summary()
    built = meta.get("built")
    counts = dict(meta.get("counts") or {})
    stale = (not built or bool(meta.get("partial")) or meta.get("v") != INDEX_V
             or meta.get("fingerprint") != fingerprint(meta))
    return counts, built, bool(stale), int(meta.get("skipped") or 0)


def fresh():
    """Built, and the machine's fingerprint unchanged since: what the
    bootstrap row asks. --help runs a build left to the timer (meta's
    `pending`) do not make it stale there, so a converged machine stays
    `Nothing to do`."""
    meta = summary()
    return (bool(meta.get("built")) and meta.get("v") == INDEX_V
            and meta.get("fingerprint") == fingerprint(meta))


def row_words(meta=None):
    """The bootstrap row's words: `N programs, M manuals, A apps, S spark
    verbs (T s)`."""
    m = meta if meta is not None else summary()
    return "%d programs, %d manuals, %d apps, %d spark verbs (%.1f s)" % (
        m.get("programs", 0), m.get("manuals", 0), m.get("apps", 0), m.get("verbs", 0), m.get("seconds", 0.0))


def _open_store(root):
    """The store dir, 0700, made here; None when it is another user's or
    a link (nothing is written through it)."""
    os.makedirs(root, mode=0o700, exist_ok=True)
    st = os.lstat(root)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
        return None
    os.chmod(root, 0o700)
    ed = os.path.join(root, ENTRIES_DIR)
    os.makedirs(ed, mode=0o700, exist_ok=True)
    est = os.lstat(ed)
    if not stat.S_ISDIR(est.st_mode) or est.st_uid != os.geteuid():
        return None
    os.chmod(ed, 0o700)
    return root


def _take_lock(root, wait):
    """The store's flock (sandbox._open_lock: O_NOFOLLOW), or None: held
    elsewhere and `wait` False, or still held after LOCK_WAIT."""
    import fcntl
    fd = sandbox._open_lock(os.path.join(root, LOCK_FILE))
    end = time.monotonic() + (LOCK_WAIT if wait else 0)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= end:
                os.close(fd)
                return None
            time.sleep(0.2)


def refresh(deadline=None, wait=False):
    """Rebuild what changed since the last fingerprint, within `deadline`
    seconds when given (BUILD_CAP at most); never raises. A refresh that
    finds the store's lock held returns at once (`wait` True -- bootstrap
    -- waits up to LOCK_WAIT). Nothing runs as root. Returns status()."""
    try:
        if os.geteuid() == 0:
            return status()
        root = _open_store(_know_dir())
        if root is None:
            return status()
        fd = _take_lock(root, wait)
        if fd is None:
            return status()
        try:
            _Build(root, deadline).run()
        finally:
            os.close(fd)
    except Exception:
        log_exc("intake.refresh")
    return status()


# ------------------------------------------------------------ the build
class _Build:
    """One refresh: list the sources, keep every entry whose stamp holds,
    read the rest (pages and spark's -h on RENDERERS threads, then the
    contained --help runs the same way), write entries, then the index,
    then meta."""

    def __init__(self, root, deadline):
        self.root = root
        self.t0 = time.monotonic()
        budget = BUILD_CAP if deadline is None else max(0.0, min(float(deadline), BUILD_CAP))
        self.end = self.t0 + budget
        # --help runs: HELP_PER_SLICE for each 5 seconds of a deadline, one
        # slice's worth without one (bootstrap) -- the timer's refreshes
        # run the rest, so a first build stays a few seconds
        self.help_left = HELP_PER_SLICE * (max(1, int(-(-budget // SLICE))) if deadline is not None else 1)
        self.pending = 0
        self.prev_meta = summary(root)
        self.docs = {}              # name -> {"key", "file", "kind", "source", "tf"}
        self.skipped = 0
        self.partial = False
        self.stamped = {}
        self.lock = threading.Lock()

    def late(self):
        return time.monotonic() >= self.end

    def run(self):
        tree = tree_stamp()
        prev = _load(os.path.join(self.root, DOCS_FILE), 32 << 20) or {}
        if not isinstance(prev, dict) or self.prev_meta.get("tree") != tree \
                or self.prev_meta.get("v") != INDEX_V:
            prev = {}               # a new spark tree, or index shape, reads everything again
        progs_dirs, man_roots, apps_dirs = _places(self.prev_meta)
        # stamped from exactly the dirs this build stores (fresh() asks the
        # same question later); read again at the end: a machine that moved
        # during the build is partial, so the next refresh reads it again
        self.stamped = stamps({"path": progs_dirs})
        fp = fingerprint(stamped=self.stamped)
        src = _sources()
        progs, self.skipped = scan_programs(progs_dirs) if "programs" in src else ({}, 0)
        if "spark" in src:
            progs.pop("spark", None)        # the name is spark's own source's
        cache = {}
        idx = page_index(man_roots, cache) if "programs" in src else {}
        jobs = []                   # (name, key, kind, reader)
        # apps first: a program an app runs folds the app into its entry
        apps = scan_apps(apps_dirs, progs, lambda p: "local") if "apps" in src else {}
        for name, prog in progs.items():
            app = apps.get(name)
            akey = [app.file] + _key_st(app.st) if app else []
            found = tied_page(prog, idx, cache)
            if found:
                root, page = found
                try:
                    pst = os.stat(page)
                except OSError:
                    pst = None
                if pst is not None and _trusted(pst):
                    key = ["man", page] + _key_st(pst) + _key_st(prog.st) + akey
                    jobs.append((name, key, "man", (prog, root, page, app)))
                    continue
            state = self._help_state(prog)
            key = ["help", state] + _key_st(prog.st) + akey
            jobs.append((name, key, "help", (prog, state, app)))
        for name, (root, page) in idx.items():
            sub = self._subcommand(name, progs)
            if not sub:
                continue
            try:
                pst = os.stat(page)
            except OSError:
                continue
            if _trusted(pst):
                jobs.append((sub, ["man", page] + _key_st(pst), "sub", (sub, root, page)))
        for key_name, app in apps.items():
            if key_name not in progs:
                jobs.append((key_name, [app.source, app.file] + _key_st(app.st), "app", app))
        if "spark" in src:
            jobs.append(("spark", ["tree", tree], "spark", None))
        jobs = jobs[:MAX_ENTRIES]
        todo = []
        for name, key, kind, arg in jobs:
            old = prev.get(name)
            if old and old.get("key") == key and self._kept(old):
                self.docs[name] = old
                if kind == "spark":             # the verbs ride the tree's one stamp
                    self.docs.update({n: d for n, d in prev.items()
                                      if d.get("kind") == "spark" and d.get("key") == key and self._kept(d)})
            else:
                todo.append((name, key, kind, arg))
        if todo:
            self._read(todo)
        same = not todo and set(self.docs) == set(prev) and os.path.exists(os.path.join(self.root, INDEX_FILE))
        self._finish(fp, tree, progs_dirs, len(progs), same)

    def _kept(self, doc):
        f = doc.get("file", "") if isinstance(doc, dict) else ""
        return bool(f) and os.path.exists(os.path.join(self.root, ENTRIES_DIR, f))

    # -- states
    def _sandbox_state(self):
        """ok, none (probe() says no sandbox, or SPARK_KNOWLEDGE_SANDBOX=none,
        a fixture's) or root; asked once, and only when a program needs it."""
        if not hasattr(self, "_sb"):
            if os.geteuid() == 0:
                self._sb = "root"
            elif os.environ.get("SPARK_KNOWLEDGE_SANDBOX") == "none":
                self._sb = "none"
            else:
                try:
                    good, _d = sandbox.probe()
                except Exception:
                    good = False
                self._sb = "ok" if good else "none"
        return self._sb

    def _help_state(self, prog):
        """Why a --help may or may not run for `prog`: ok, none (no
        sandbox), root, home (a program under the home, on macOS), stub
        (an Xcode stub with no developer tools)."""
        sandbox_ok = self._sandbox_state()
        if sandbox_ok != "ok":
            return sandbox_ok
        if IS_MAC and prog.home:
            return "home"
        if IS_MAC and prog.real.startswith("/usr/bin/") and not self._xcode():
            return "stub"
        return "ok"

    def _xcode(self):
        if not hasattr(self, "_xc"):
            rc, _out = run(["xcode-select", "-p"], timeout=5)
            self._xc = rc == 0
        return self._xc

    @staticmethod
    def _subcommand(name, progs):
        """"H S" for a page H-S whose H is a program and which is not a
        program itself (the longest H wins), else ''."""
        if "-" not in name or name in progs:
            return ""
        parts = name.split("-")
        for k in range(len(parts) - 1, 0, -1):
            head, sub = "-".join(parts[:k]), "-".join(parts[k:])
            if head in progs and NAME_SHAPE.match(head) and NAME_SHAPE.match(sub):
                return head + " " + sub
        return ""

    # -- reading
    def _read(self, todo):
        paths = set()
        for name, key, kind, arg in todo:
            if kind in ("man", "help"):
                paths.update((arg[0].path, arg[0].real))
            if kind in ("man", "sub"):
                paths.add(arg[2])
        owners = Owners(paths)
        pages = {}
        for name, key, kind, arg in todo:
            if kind in ("man", "sub"):
                root, page = (arg[1], arg[2])
                pages.setdefault(os.path.realpath(page), (root, page))
        rendered = {}

        def one_page(real):
            if self.late():
                return
            root, page = pages[real]
            path, src = resolve(page, root)
            if path is None:
                rendered[real] = None
                return
            text = render(path, root)
            rendered[real] = (page_what(src), text) if text else None

        scratch = tempfile.mkdtemp(prefix="spark-intake.")
        spark_out = {}

        def one_verb(verb):
            if self.late():
                return
            spark_out[verb] = spark_help(verb, scratch)
        try:
            spark_todo = [t for t in todo if t[2] == "spark"]
            verbs = []
            if spark_todo:
                subs, verbs = spark_words()
                verbs = [v for v in verbs if NAME_SHAPE.match(v) and v != "help"]
            with ThreadPoolExecutor(max_workers=RENDERERS) as pool:
                list(pool.map(one_page, list(pages)))
                if spark_todo:
                    list(pool.map(one_verb, [None] + verbs))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        if any(r not in rendered for r in pages):
            self.partial = True
        for name, key, kind, arg in todo:
            if kind == "man":
                prog, root, page, app = arg
                got = rendered.get(os.path.realpath(page))
                if got is None and os.path.realpath(page) not in rendered:
                    continue                         # past the deadline: next refresh
                self._program(name, key, prog, owners, got, page, app)
            elif kind == "sub":
                got = rendered.get(os.path.realpath(arg[2]))
                if got is None:
                    continue
                self._put(name, key, "program", "man", got, arg[2], owners.of(arg[2])[0], None)
            elif kind == "app":
                self._app(name, key, arg)
        for name, key, kind, arg in todo:
            if kind == "spark":
                self._spark(key, spark_out, verbs)
        helps = [(name, key) + tuple(arg) for name, key, kind, arg in todo if kind == "help"]
        if helps:
            with ThreadPoolExecutor(max_workers=RENDERERS) as pool:
                list(pool.map(lambda h: self._help(h[0], h[1], h[2], h[3], owners, h[4]), helps))

    def _program(self, name, key, prog, owners, got, page, app):
        origin, summ = owners.of(prog.path, prog.real)
        if got is None:                          # a page that would not render: the package's words
            self._bare(name, key, prog, origin, summ, app)
            return
        self._put(name, key, "program", "man", got, page, origin, app, summ)

    def _put(self, name, key, kind, source, got, page, origin, app, summ=""):
        src_what, text = got
        clean = _Clean()
        what, synopsis, lines, opts = clean.parsed(*read_page(_scrub(text), _scrub(src_what)))
        what = what or clean(summ)
        if app:
            lines = [clean(_app_line(app))] + lines
        try:
            st = os.stat(page)
            stamp = _stamp(st)
        except OSError:
            stamp = []
        self._save(name, key, kind, source, what, synopsis, opts, lines, origin, stamp, clean.held)

    def _bare(self, name, key, prog, origin, summ, app, skipped=0):
        clean = _Clean()
        lines = [clean(_app_line(app))] if app else []
        self._save(name, key, "program", "pkg", clean(summ), "", OptionSet((), (), ()), lines, origin,
                   _stamp(prog.st), clean.held, skipped)

    def _help(self, name, key, prog, state, owners, app):
        """One program with no manual: its --help, contained, or its
        package's words. Every attempt is stamped (key): run again only
        when the program changes -- or, past this slice's HELP_PER_SLICE
        or the deadline, in the next refresh."""
        origin, summ = owners.of(prog.path, prog.real)
        if state != "ok":
            self._bare(name, key, prog, origin, summ, app, skipped=1)
            return
        with self.lock:
            go = self.help_left > 0 and not self.late()
            if go:
                self.help_left -= 1
            else:
                self.partial = True
                self.pending += 1
        if not go:
            self._bare(name, ["pending"] + key, prog, origin, summ, app)    # never matches: the next slice runs it
            return
        bind = [prog.real] if prog.home else []
        try:
            got = sandbox.contained([prog.real, "--help"], bind=bind)
        except Exception:
            log_exc("intake.contained")
            got = None
        if got is None:
            self._bare(name, key, prog, origin, summ, app, skipped=1)
            return
        clean = _Clean()
        parsed = read_help(_scrub(got[1]))
        if parsed is None:
            self._bare(name, key, prog, origin, summ, app)
            return
        what, synopsis, lines, opts = clean.parsed(*parsed)
        what = clean(summ) or what
        if app:
            lines = [clean(_app_line(app))] + lines
        self._save(name, key, "program", "help", what, synopsis, opts, lines, origin, _stamp(prog.st), clean.held)

    def _app(self, name, key, app):
        clean = _Clean()
        what = clean(app.display + (" -- " + app.comment if app.comment else ""))[:160]
        self._save(name, key, "app", app.source, what, clean(app.run), OptionSet((), (), ()), [], app.origin,
                   _stamp(app.st), clean.held)

    def _spark(self, key, out, verbs):
        subs, _v = spark_words()
        slots = spark_slots()
        for verb in [None] + verbs:
            text = out.get(verb)
            if text is None:
                self.partial = True
                continue
            clean = _Clean()
            name, what, synopsis, opts, lines = spark_entry(verb, clean(text), subs, slots)
            self._save(name, key, "spark", "tree", clean(what), synopsis, opts, lines, "spark", [], clean.held)

    def _save(self, name, key, kind, source, what, synopsis, opts, lines, origin, stamp, held, skipped=0):
        e = {"name": name, "kind": kind, "source": source, "what": " ".join((what or "").split())[:200],
             "synopsis": synopsis or "", "options": {"long": list(opts.long), "short": list(opts.short),
                                                     "words": list(opts.words)},
             "lines": list(lines), "origin": origin, "stamp": list(stamp), "held": held}
        data = json.dumps(e)
        while len(data.encode("utf-8")) > ENTRY_MAX and (e["lines"] or e["options"]["words"]):
            if e["lines"]:
                e["lines"] = e["lines"][:len(e["lines"]) // 2]
            else:
                for k in ("words", "long", "short"):
                    e["options"][k] = e["options"][k][:len(e["options"][k]) // 2]
            data = json.dumps(e)
        f = entry_file(name)
        _write(os.path.join(self.root, ENTRIES_DIR, f), e, sync=False)
        with self.lock:
            self.docs[name] = {"key": key, "file": f, "kind": kind, "source": source, "held": held,
                               "skipped": skipped, "tf": entry_terms(e)}

    # -- the index and meta
    def _finish(self, fp, tree, dirs, programs, same=False):
        """Drop the entries no source gave, then docs.json and index.json
        (unless nothing changed: `same`), then meta.json."""
        if not same:
            self._write_index(fp)
        self._write_meta(fp, tree, dirs, programs)

    def _write_index(self, fp):
        keep = {d["file"] for d in self.docs.values()}
        ed = os.path.join(self.root, ENTRIES_DIR)
        try:
            for f in os.listdir(ed):
                if f not in keep:
                    try:
                        os.unlink(os.path.join(ed, f))
                    except OSError:
                        pass
        except OSError:
            pass
        _write(os.path.join(self.root, DOCS_FILE), self.docs)
        index = index_of((n, d["tf"]) for n, d in self.docs.items())
        index.update(built=int(time.time()), fingerprint=fp)
        _write(os.path.join(self.root, INDEX_FILE), index)

    def _write_meta(self, fp, tree, dirs, programs):
        built = int(time.time())
        if stamps({"path": [d for d in dirs if os.path.isabs(d)]}) != self.stamped:
            self.partial = True
        vals = list(self.docs.values())
        counts = {"program": sum(1 for d in vals if d["kind"] == "program"),
                  "manual": sum(1 for d in vals if d["kind"] == "program" and d["source"] == "man"),
                  "app": sum(1 for d in vals if d["kind"] == "app"),
                  "spark": sum(1 for n, d in self.docs.items() if d["kind"] == "spark" and n != "spark")}
        meta = {"v": INDEX_V, "built": built, "seconds": round(time.monotonic() - self.t0, 1), "fingerprint": fp,
                "tree": tree, "counts": counts, "programs": counts["program"], "manuals": counts["manual"],
                "apps": counts["app"], "verbs": counts["spark"], "executables": programs,
                "skipped": self.skipped + sum(d.get("skipped", 0) for d in vals),
                "held": sum(d.get("held", 0) for d in vals),
                "partial": self.partial, "pending": self.pending, "path": [d for d in dirs if os.path.isabs(d)],
                "stamps": self.stamped}
        _write(os.path.join(self.root, META_FILE), meta)


# ------------------------------------------------------------ bootstrap
def _main(argv):
    """`python3 -m spark.intake fresh` exits 0 when the store is fresh;
    `build` refreshes it (waiting for the lock) and prints the row's
    words."""
    if argv[:1] == ["fresh"]:
        if fresh():
            return 0
        for p in changed()[:20]:
            print("changed since the build: %s" % p, file=sys.stderr)
        return 1
    if argv[:1] == ["build"]:
        refresh(wait=True)
        print(row_words())
        return 0
    print("usage: python3 -m spark.intake fresh|build", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
