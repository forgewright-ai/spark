# spark.sandbox -- spark do --sandbox: every step runs in a copy it cannot leave.
#
# The OS is the harness: the kernel's containment replaces the per-step
# Enter, and the person's Enter moves to the apply, after a review of what
# changed. Nothing here talks to a model or a terminal: values in, values
# out; spark do (lib/spark/do.py) drives it.
#
#   Linux      one bwrap per step: the whole machine read-only, the homes,
#              /run, /tmp, /var/tmp and spark's own token hidden under
#              empty tmpfs, the project an overlay whose upper dir
#              (STATE/runs/<id>/up) catches every write, no network, no new
#              privileges (bwrap sets no_new_privs always: sudo and setuid
#              do not elevate).
#   macOS      an APFS clone of the project (cp -c) and sandbox-exec with
#              a profile that denies the network, reads under /Users,
#              /Volumes, the temp dirs and the keychains (the clone and the
#              git config files excepted), every write outside the clone and
#              the run's own home, and the services that run work outside
#              any sandbox (Launch Services, Apple events, Shortcuts, login
#              items, preferences).
#   review     changes(): what the steps left, as entries -- added, changed,
#              deleted, mode, link, binary, and the two that never apply:
#              held (inside a git directory, everything but its objects,
#              refs, logs, index and HEAD files; a `.git` file) and refused
#              (a link out, a device, a fifo, a socket, an overlay mark).
#              diff_text() shows every control character as an escape, so
#              a review cannot be redrawn by the text it reviews.
#   apply      apply(run, reviewed): what the person reviewed, or nothing
#              (a fingerprint of the entries, every file's sha256 checked
#              again as it is copied); all or nothing on a lock or a
#              conflict; deletes first, then creates top-down, every write
#              walked fd-relative with O_NOFOLLOW per component, so a
#              symlink in the project cannot carry a write outside it.
#   runs       running -> waiting -> applied | discarded. The process that
#              drives a run holds its flock (runs/<id>/lock); apply, discard
#              and claim refuse while another process holds it, and a run
#              whose driver died waits. Applied or discarded, the run's dir
#              goes whole.
#   records    meta.json holds numbers and names -- id, thread id, cwd,
#              start, os, state -- never the goal's words (those live in
#              the sealed thread); run dirs 0700, files 0600.
#
# Every list below that decides something is a named line with its reason,
# so any one of them can be argued with; tests/sandbox_test.py names each.

import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time

from . import CONFIG_DIR, HOME, OS, STATE_DIR, state_dir

RUNS_DIR = os.path.join(STATE_DIR, "runs")
RUNS_LOCK = os.path.join(RUNS_DIR, ".lock")     # new_run's count and mkdir, one process at a time
DETACH_LOCK = "detach.lock"                     # in RUNS_DIR: one detached run at a time
RUN_LOCK = "lock"                               # in a run's dir: held by the process driving it
PROBE_DIR = os.path.join(STATE_DIR, "sandbox")
PROBE_FILE = os.path.join(PROBE_DIR, "probe.json")

SANDBOX_MAX_ENTRIES = 50000     # a macOS clone copies at most this many entries...
SANDBOX_LIST_SECONDS = 10.0     # ...listed within this long (the persona.blast pattern)
SANDBOX_MAX_BYTES = 1 << 30     # what one run may write: RLIMIT_FSIZE a file, the upper dir in all
SANDBOX_MAX_WAITING = 5         # runs running or waiting for review; a sixth is refused
BWRAP_MIN = (0, 11)             # --overlay arrived in bubblewrap 0.11
DIFF_MAX = 256 * 1024           # a text larger than this is one line in the review, not a diff
REVIEW_MAX = 2 * 1024 * 1024    # old + new text one review shows; past it, headings only
PROBE_TIMEOUT = 20

# a run's id: the time it began and six hex digits -- load() refuses any
# other shape before it touches the filesystem, so an id is never a path
ID_SHAPE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
# what meta.json may hold: numbers and names, never the goal's words
META_FIELDS = ("id", "thread", "cwd", "start", "os", "state")
# a run's life: its driver holds the lock while it runs; it waits for a
# review; applied or discarded, its dir is removed
STATES = ("running", "waiting", "applied", "discarded")

NEEDS_PROJECT = "the sandbox needs a project directory, not ~ or /"
OTHER_VOLUME = "the sandbox clones the project on its own volume, and spark's state is on another"
CHANGED = "the copy changed after the review -- nothing applied"
RUNNING = "run %s is still running"
NO_RUN = "no sandboxed run %s -- spark do --review lists them"
DETACHED = "a detached run is already running"
TOO_LARGE = "too large to show"

# ------------------------------------------------------------------ Linux
# What a step never sees: an empty tmpfs over each that exists, parents
# first (the project and the git config files are mounted back after).
HIDDEN = (
    "/home",        # every user's home: keys, tokens, shell history, other projects
    "$HOME",        # this user's home when it is not under /home (/var/home, /root, a test's)
    "/root",        # root's home
    "/run",         # the runtime dirs: the session bus, ssh-agent, gpg-agent, the system bus
    "/tmp",         # other programs' temp files and sockets (X11, tmux); the step gets its own
    "/var/tmp",     # the temp files that outlive a reboot, other programs' too
    "/media",       # removable drives
    "/mnt",         # mounted drives
    "/etc/spark",   # the shared engine's token (spark share)
)
# The git config a commit inside needs, read-only -- file by file, never
# the directory: git's credential store can live beside them.
GIT_FILES = (
    ".gitconfig",               # the name a commit carries, the aliases
    ".config/git/config",       # the same, in its XDG place
    ".config/git/ignore",       # the global excludes
    ".config/git/attributes",   # the global attributes
)
BWRAP_FLAGS = (
    "--unshare-user",           # its own user namespace: root inside is nobody outside
    "--unshare-ipc",            # no shared memory with the desktop
    "--unshare-pid",            # sees only its own processes (a fresh /proc)
    "--unshare-net",            # no network at all: a loopback that goes nowhere
    "--unshare-uts",            # its own hostname
    "--unshare-cgroup-try",     # its own cgroup view, where the kernel has one
    "--disable-userns",         # and no second user namespace to climb out of this one
    "--die-with-parent",        # spark's leash kills bwrap, and everything inside dies
    "--new-session",            # no controlling terminal: no TIOCSTI into the caller's
)
# the environment a step gets, besides PATH, HOME and LANG -- nothing else
# of the caller's crosses (bwrap --clearenv; a clean env on macOS): a
# token in an exported variable stays outside
STEP_ENV = (
    ("TERM", "dumb"),                   # no pager, no colour, no cursor games
    ("GIT_CONFIG_COUNT", "1"),          # git inside never repacks on its own:
    ("GIT_CONFIG_KEY_0", "gc.auto"),    # an auto gc would rewrite .git/objects
    ("GIT_CONFIG_VALUE_0", "0"),        # wholesale and swamp the review
)

# the overlay's own marks in the upper dir
OPAQUE_XATTR = "user.overlay.opaque"      # b"y" = the step replaced this directory whole
WHITEOUT_XATTR = "user.overlay.whiteout"  # an xattr whiteout (kernel 6.7+), defensive
# Only b"y" is opaque. b"x" marks a directory that CONTAINS xattr
# whiteouts and is not opaque; read as opaque it would delete every
# lower file the step never touched.
OPAQUE_VALUE = b"y"
# an upper entry carrying either names data or a place that is not in the
# upper dir itself: never applied (bwrap's userxattr overlay makes neither;
# defensive)
OVERLAY_REFUSED = (
    ("user.overlay.metacopy", "an overlay metacopy: the data it names lives elsewhere"),
    ("user.overlay.redirect", "an overlay redirect: the directory it names lives elsewhere"),
)

# ------------------------------------------------------------------ macOS
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/"
              "LaunchServices.framework/Versions/A/Support/lsregister")
QLMANAGE = ("/System/Library/Frameworks/QuickLook.framework/Versions/A/Resources/qlmanage.app/Contents/"
            "MacOS/qlmanage")    # /usr/bin/qlmanage is a link: exec matches the real path
# The profile, a named line each; paths only ever arrive as -D parameters
# (realpath'd), never pasted into the text. Later rules win. The default
# stays allow: a deny-default profile breaks dyld and every tool, so the
# reads below are the places that hold what is the user's, and the
# services below the ones that run work outside any sandbox.
PROFILE = (
    ("(version 1)", ""),
    ("(allow default)", "what is not denied below runs as the user"),
    ("(deny network*)", "no network: no socket out, no unix socket in or out"),
    ('(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/etc/spark")'
     ' (subpath (param "HOME")) (subpath (param "STATE")) (subpath (param "CONFIG")))',
     "no home, no other volume, no spark token or state"),
    ('(deny file-read* (subpath "/private/var/folders") (subpath "/private/tmp")'
     ' (subpath "/private/var/tmp"))',
     "no user's temp and cache dirs, no other program's temp files"),
    ('(deny file-read* (subpath "/Library/Keychains") (subpath "/private/var/root"))',
     "no system keychain, no root's home"),
    ('(deny file-read* (subpath "/opt/homebrew/etc") (subpath "/usr/local/etc"))',
     "no package manager's service config (a database's password, a registry token)..."),
    ('(allow file-read* (regex #"^/(opt/homebrew|usr/local)/etc/(gitconfig|paths|nanorc)$")'
     ' (regex #"^/(opt/homebrew|usr/local)/etc/(openssl[^/]*|ca-certificates|gnutls|clang|fonts'
     '|bash_completion\\.d)(/|$)"))',
     "...but the public files git, openssl, node and clang read as they start"),
    ('(allow file-read* (require-all (subpath (param "UVAR")) (regex #"/xcrun_db$")))',
     "xcrun's cache, read-only, so python3, cc and make stay quiet (never written: an entry names a tool to run)"),
    ("@ANC", "the way down to the clone may be looked up, never listed"),
    ('(allow file-read* (subpath (param "CLONE")) (subpath (param "RHOME")) (subpath (param "TMP"))@GIT)',
     "the clone, the run's own home and temp, and the git config files"),
    ("(deny file-write*)", "nothing is written anywhere..."),
    ('(allow file-write* (subpath (param "CLONE")) (subpath (param "RHOME")) (subpath (param "TMP"))'
     ' (literal "/dev/null") (literal "/dev/zero") (regex #"^/dev/fd/"))',
     "...but the clone, the run's home and temp, and the null devices"),
    ('(deny file-read* file-write* (literal "/dev/tty") (regex #"^/dev/ttys[0-9]+$"))',
     "no terminal: nothing typed into the caller's shell"),
    ("(deny appleevent-send)", "no scripting other apps"),
    ("(deny lsopen)", "no opening apps or URLs"),
    ('(deny mach-lookup (global-name "com.apple.pasteboard.1") (global-name "com.apple.SecurityServer")'
     ' (global-name "com.apple.securityd.xpc"))', "no clipboard, no keychain"),
    ('(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd") (global-name-regex #"^com\\.apple\\.lsd\\.")'
     ' (global-name "com.apple.coreservices.appleevents"))',
     "no Launch Services and no Apple events: nothing opened, registered or scripted through them"),
    ('(deny mach-lookup (global-name "com.apple.siriactionsd.xpc") (global-name "com.apple.siri.VoiceShortcuts.xpc")'
     ' (global-name "com.apple.synapse.DocumentWorkflowsService"))',
     "no Shortcuts and no workflow runner: they run what they are handed outside any sandbox"),
    ('(deny mach-lookup (global-name-regex #"^com\\.apple\\.backgroundtaskmanagement")'
     ' (global-name-regex #"^com\\.apple\\.xpc\\.launchd\\.domain\\."))',
     "no login item, no launchd job registered"),
    ('(deny mach-lookup (global-name "com.apple.cfprefsd.daemon") (global-name "com.apple.cfprefsd.agent"))',
     "no preferences written through the daemons that write them"),
    ('(deny mach-lookup (global-name "com.apple.coreservices.sharedfilelistd.xpc") (global-name "com.apple.pluginkit.pkd")'
     ' (global-name "com.apple.DiskArbitration.diskarbitrationd") (global-name "com.apple.FileProvider")'
     ' (global-name "com.apple.bird") (global-name "com.apple.tccd") (global-name "com.apple.tccd.system"))',
     "no recent items, no plugin registry, no mounts, no iCloud or file providers, no privacy consent"),
    ('(deny process-exec (literal "/usr/bin/osascript") (literal "/usr/bin/osacompile") (literal "/usr/bin/open")'
     ' (literal "/bin/launchctl") (literal "/usr/bin/sudo") (literal "/usr/bin/security") (literal "/usr/bin/pbpaste")'
     ' (literal "/usr/bin/pbcopy"))',
     "no scripting, no opening, no services, no root, no keychain, no clipboard"),
    ('(deny process-exec (literal "/usr/bin/shortcuts") (literal "/usr/bin/automator") (literal "/usr/bin/defaults")'
     ' (literal "/usr/bin/sfltool") (literal "/usr/sbin/screencapture") (literal (param "LSREGISTER"))'
     ' (literal "/usr/bin/lsappinfo") (literal "/usr/bin/pluginkit") (literal (param "QLMANAGE"))'
     ' (literal "/usr/bin/tccutil") (literal "/usr/bin/hdiutil") (literal "/usr/sbin/diskutil")'
     ' (literal "/usr/bin/tmutil") (literal "/usr/bin/crontab") (literal "/usr/bin/at")'
     ' (literal "/usr/bin/fileproviderctl") (literal "/usr/bin/brctl"))',
     "no tool that hands work to a daemon outside: shortcuts, workflows, preferences, recent items, the screen,"
     " app registration, plugins, previews, consent, disk images, mounts, backups, cron and at, iCloud"),
)
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_CS_DARWIN_USER_TEMP_DIR = 65537     # confstr: /var/folders/xx/yyyy/T/

# ------------------------------------------------------------------ review
# What a review shows as an escape, never as itself: every C0 control but
# TAB (a newline too: in a path or a link it is not a line break), DEL,
# the C1 controls, the bidi controls (U+061C, U+200E-200F, U+202A-202E,
# U+2066-2069: text that reads in another order than it runs) and a lone
# surrogate (a name that was not UTF-8). ESC[2K and a cursor move would
# otherwise erase the lines above them -- the review itself.
VISIBLE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
# in a text, the newline is the line break, not a character to show
_VISIBLE_TEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ud800-\udfff]")

# GITDIR: a directory is a git directory, whatever its name, when it is
# named `.git` (case folded, and with the characters HFS+ and git's own
# check ignore taken out: `.GIT` is `.git` on a Mac), or when it holds a
# HEAD file and an objects/ directory -- in the project or in the copy.
GIT_NAME_IGNORED = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u206a-\u206f\ufeff]")
# GIT_KEEP: all that applies from inside a git directory -- git's own
# bookkeeping, none of which names a program to run. Everything else there
# (config, hooks/**, commondir, gitdir, worktrees/**, modules/**,
# info/attributes, ...) is held back.
GIT_KEEP = (
    (re.compile(r"objects(?:/.+)?"), "the object store: content, named by its own hash"),
    (re.compile(r"refs(?:/.+)?"), "the branches and tags"),
    (re.compile(r"logs(?:/.+)?"), "the reflogs"),
    (re.compile(r"index"), "the staging area"),
    (re.compile(r"HEAD|ORIG_HEAD|FETCH_HEAD|MERGE_HEAD|packed-refs"), "where the branches point"),
    (re.compile(r"MERGE_MSG|COMMIT_EDITMSG|description"), "messages, plain text"),
    (re.compile(r"info(?:/exclude)?"), "the repository's own ignore list (and the directory that holds it)"),
)
# ...but inside objects/, the one file that points the store elsewhere
GIT_KEEP_NOT = re.compile(r"objects/info/(?:http-)?alternates")
# why a held item is held, by its first part inside the git directory
GIT_WHY = (
    (re.compile(r"hooks(?:/|$)"), "a git hook would run outside the sandbox on the next git command"),
    (re.compile(r"config(?:\.worktree)?$"), "git config can name a hooks path, a pager, an editor or an ssh command"),
    (re.compile(r"(?:commondir|gitdir)$"), "it points git at another directory's config and hooks"),
    (re.compile(r"(?:modules|worktrees)(?:/|$)"), "a submodule's or a worktree's own repository: its hooks and config"),
    (re.compile(r""), "inside a git directory only objects, refs, logs, the index and HEAD files apply"),
)
# GITFILE: a `.git` that is not a directory -- `gitdir: <path>` sends git
# to another directory, with that directory's hooks
GITFILE = "a .git file points git at another directory, with its own hooks"
# git was mid-command in the copy: its files are half-written -- the
# whole apply is refused, never a part of it
LOCK = re.compile(r"(?:^|/)\.git/(?:.+/)?[^/]+\.lock$")
# refused, listed with the reason
LINK_OUT = "the link leads out of the project"
SPECIAL = "a device, fifo or socket is never applied"
# noted: apply writes mode & 0o777 only
SETID = "the setuid/setgid bit is dropped"
# the statuses an entry can carry (the porcelain's review event names them)
STATUSES = ("added", "changed", "deleted", "mode", "link", "held", "refused", "binary")


class SandboxError(Exception):
    """A refusal: the text is the signed line after `spark do -- `;
    `paths` names what it is about (the conflicts, the locks)."""

    def __init__(self, text, paths=()):
        Exception.__init__(self, text)
        self.paths = list(paths)


# ------------------------------------------------------------------ small parts
def visible(s):
    """s with every character VISIBLE names shown as an escape (`\\x1b`,
    `\\u202e`, `\\udcff`), never interpreted by a terminal."""
    return VISIBLE.sub(lambda m: ("\\x%02x" if ord(m.group()) < 0x100 else "\\u%04x") % ord(m.group()), s)


def _control(e):
    """The entry's name, link target or text holds a VISIBLE character."""
    if VISIBLE.search(e["path"]):
        return True
    for t in (e.get("old"), e.get("new")):
        if isinstance(t, str) and (VISIBLE if e.get("kind") == "link" else _VISIBLE_TEXT).search(t):
            return True
    return False


def mkdirs(path):
    """path and every level under STATE_DIR, each 0700 (os.makedirs
    applies its mode only to the leaf; the users.make_dirs pattern)."""
    state_dir()
    levels = []
    p = path
    while p and p != STATE_DIR and p.startswith(STATE_DIR + os.sep):
        levels.append(p)
        p = os.path.dirname(p)
    for p in reversed(levels):
        os.makedirs(p, mode=0o700, exist_ok=True)
        os.chmod(p, 0o700)
    return path


def _write_private(path, data):
    from . import vault
    vault.write_private(path, data)


def _inside(path, root):
    """path is root or under it (both realpath'd)."""
    root = root.rstrip("/") or "/"
    return path == root or path.startswith(root if root == "/" else root + "/")


def _lstat(path):
    try:
        return os.lstat(path)
    except OSError:
        return None


def _lower(low, rel):
    """lstat of the project's rel, or None -- None too when a directory on
    the way is a link or not a directory: a lower path is never read
    through a link (it would be some other place's file)."""
    parts = rel.split("/")
    p = low
    for part in parts[:-1]:
        p = os.path.join(p, part)
        st = _lstat(p)
        if st is None or not stat.S_ISDIR(st.st_mode):
            return None
    return _lstat(os.path.join(low, rel))


def _kind(st):
    if st is None:
        return ""
    m = st.st_mode
    return "dir" if stat.S_ISDIR(m) else "file" if stat.S_ISREG(m) else "link" if stat.S_ISLNK(m) else "other"


def _xattr(path, name):
    if not hasattr(os, "getxattr"):
        return None
    try:
        return os.getxattr(path, name, follow_symlinks=False)
    except OSError:
        return None


def _rmtree(path):
    """Remove a run's data even where the kernel or the step left a
    directory without permissions (overlay's work dir is mode 000)."""
    if not os.path.lexists(path):
        return
    if not os.path.isdir(path) or os.path.islink(path):
        os.remove(path)
        return
    # every directory 0700 first, top-down, so each can be listed and
    # emptied; a link is never chmodded (that would follow it)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    for root, dirs, _files in os.walk(path):
        for d in dirs:
            p = os.path.join(root, d)
            if not os.path.islink(p):
                try:
                    os.chmod(p, 0o700)
                except OSError:
                    pass
    shutil.rmtree(path, ignore_errors=True)


def _walk(root, cap=None, seconds=None):
    """{rel: lstat} of everything under root, never following a link.
    Over `cap` entries or `seconds` it refuses (the persona.blast bound)."""
    out = {}
    deadline = time.time() + seconds if seconds else None
    stack = [""]
    while stack:
        rel = stack.pop()
        try:
            it = os.scandir(os.path.join(root, rel) if rel else root)
        except OSError:
            continue
        with it:
            for e in it:
                r = rel + "/" + e.name if rel else e.name
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                out[r] = st
                if stat.S_ISDIR(st.st_mode):
                    stack.append(r)
                if cap and len(out) > cap:
                    raise SandboxError("the sandbox copies at most %d files, and this directory holds more"
                                       " -- run it in a smaller one" % cap)
        if deadline and time.time() > deadline:
            raise SandboxError("this directory took over %d s to list -- run the sandbox in a smaller one"
                               % seconds)
    return out


def _meta(st):
    """What the manifest keeps of an entry: type, size, mtime_ns, mode --
    and ctime_ns, which no step can set back."""
    return [_kind(st), st.st_size, st.st_mtime_ns, stat.S_IMODE(st.st_mode), st.st_ctime_ns]


def _sha(path):
    """sha256 hex of the file's bytes (never through a link), None when it
    does not open."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    h = hashlib.sha256()
    with os.fdopen(fd, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ locks
_LOCK_FLAGS = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_lock(path):
    """A lock file's fd: created 0600, never through a link, never
    inherited by a step."""
    return os.open(path, _LOCK_FLAGS, 0o600)


def detach_lock():
    """The one detached run: an flock on runs/detach.lock, held until the
    fd is closed or the process ends (the kernel lets go when it dies, so
    no stale lock outlives a killed run). SandboxError(DETACHED) while
    another process holds it."""
    mkdirs(RUNS_DIR)
    fd = _open_lock(os.path.join(RUNS_DIR, DETACH_LOCK))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise SandboxError(DETACHED)
    return fd


def _take(run):
    """Take the run's lock for this call (non-blocking): True when taken
    here, False when the run already carries this process's lock. Refuses
    while another process holds it, and when the run is gone."""
    if run.get("lock") is not None:
        return False
    try:
        fd = _open_lock(os.path.join(run["dir"], RUN_LOCK))
    except FileNotFoundError:
        raise SandboxError(NO_RUN % run["id"])
    except OSError as e:
        raise SandboxError("run %s's lock does not open (%s)" % (run["id"], e.strerror or e))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise SandboxError(RUNNING % run["id"])
    if not os.path.isfile(os.path.join(run["dir"], "meta.json")):     # removed before we had it
        os.close(fd)
        raise SandboxError(NO_RUN % run["id"])
    run["lock"] = fd
    return True


def release(run):
    """Let go of the run's lock, when this process holds it."""
    fd = run.pop("lock", None)
    if fd is not None:
        os.close(fd)


def _busy(run):
    """Another process (or another fd of this one) holds the run's lock."""
    try:
        fd = os.open(os.path.join(run["dir"], RUN_LOCK), os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


# ------------------------------------------------------------------ runs
def _run_dir(rid):
    return os.path.join(RUNS_DIR, rid)


def _save(run):
    meta = {k: run[k] for k in META_FIELDS}
    _write_private(os.path.join(run["dir"], "meta.json"), json.dumps(meta, sort_keys=True).encode())


def load(rid):
    """The run with this id, its lock not taken -- the id's shape is
    checked before any path is built from it."""
    if not isinstance(rid, str) or not ID_SHAPE.match(rid):
        raise SandboxError("that is not a sandboxed run's id -- spark do --review lists them")
    d = _run_dir(rid)
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        raise SandboxError(NO_RUN % rid)
    if not isinstance(meta, dict) or meta.get("id") != rid or meta.get("state") not in STATES \
            or meta.get("os") not in ("linux", "macos"):
        raise SandboxError("run %s's record does not read -- spark do --discard %s" % (rid, rid))
    run = {k: meta.get(k) for k in META_FIELDS}
    run["dir"] = d
    return run


def claim(rid):
    """The run with this id, its lock held by this process (release()
    lets go; apply and discard end it): what --review, --accept and
    --discard act on. Refuses while another process holds the lock (RUNNING)
    and when the run is gone; a run whose driver died waits."""
    run = load(rid)
    _take(run)
    try:
        fresh = load(rid)       # re-read under the lock: it may have ended meanwhile
    except SandboxError:
        release(run)
        raise
    run.update({k: fresh[k] for k in META_FIELDS})
    if run["state"] == "running":       # the lock was free: its driver died
        run["state"] = "waiting"
        _save(run)
    if run["state"] != "waiting":
        release(run)
        raise SandboxError("run %s is %s already" % (rid, run["state"]))
    return run


def runs():
    """The runs not yet ended, oldest first, each with `running`: True
    while a process holds its lock (a driver, a review), False when it
    waits. A run recorded as running whose lock is free lost its driver:
    its state reads waiting."""
    try:
        names = sorted(os.listdir(RUNS_DIR))
    except OSError:
        return []
    out = []
    for n in names:
        if not ID_SHAPE.match(n):
            continue
        try:
            r = load(n)
        except SandboxError:
            continue
        if r["state"] not in ("running", "waiting"):
            continue
        r["running"] = _busy(r)
        if r["state"] == "running" and not r["running"]:
            r["state"] = "waiting"
        out.append(r)
    return out


def mark(run, state):
    """Record a run's state (one of STATES)."""
    if state not in STATES:
        raise ValueError(state)
    run["state"] = state
    _save(run)


def new_run(cwd, thread, platform=None):
    """A new run of the project at cwd, for the sealed thread `thread`,
    state running, its lock held by this process (run["lock"]; release()
    lets go). Refuses (SandboxError) when the run dir would be inside
    cwd -- that covers ~ and / -- and when SANDBOX_MAX_WAITING runs are
    already running or waiting: the count and the mkdir hold runs/.lock,
    so two processes cannot both take the last place."""
    plat = platform or OS
    cwd = os.path.realpath(cwd)
    runs_real = os.path.realpath(mkdirs(RUNS_DIR))
    if _inside(runs_real, cwd):
        raise SandboxError(NEEDS_PROJECT)
    if not os.path.isdir(cwd):
        raise SandboxError("%s is not a directory" % cwd)
    cap = _open_lock(RUNS_LOCK)
    try:
        fcntl.flock(cap, fcntl.LOCK_EX)
        if len(runs()) >= SANDBOX_MAX_WAITING:
            raise SandboxError("%d sandboxed runs wait for review -- spark do --review" % SANDBOX_MAX_WAITING)
        while True:
            rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
            d = _run_dir(rid)
            try:
                os.mkdir(d, 0o700)
                break
            except FileExistsError:
                continue
        os.chmod(d, 0o700)
        run = {"id": rid, "thread": thread or "", "cwd": cwd, "start": 0, "os": plat, "state": "running", "dir": d}
        try:
            fd = _open_lock(os.path.join(d, RUN_LOCK))
            run["lock"] = fd
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # the start stamp on the filesystem's own clock, before the copy
            # exists: a project file newer than it changed during the run
            stamp = os.path.join(d, ".start")
            os.close(os.open(stamp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            run["start"] = os.lstat(stamp).st_mtime_ns
            os.remove(stamp)
            _save(run)
        except BaseException:
            _remove(run)
            raise
    finally:
        os.close(cap)
    try:
        if plat == "macos":
            _clone(run)
        else:
            for sub in ("up", "wk"):
                os.mkdir(os.path.join(d, sub), 0o700)
    except BaseException:
        _remove(run)
        raise
    return run


def _clone(run):
    """macOS: cp -c (APFS clonefile) of the project into the run, on the
    same volume, bounded; then the manifest of the clone as it began."""
    d, cwd = run["dir"], run["cwd"]
    if os.stat(cwd).st_dev != os.stat(d).st_dev:
        raise SandboxError(OTHER_VOLUME)
    _walk(cwd, SANDBOX_MAX_ENTRIES, SANDBOX_LIST_SECONDS)
    clone = os.path.join(d, "clone")
    try:
        p = subprocess.run(["/bin/cp", "-c", "-R", "-p", cwd, clone], capture_output=True, text=True,
                           timeout=120)
        rc, err = p.returncode, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        rc, err = 1, str(e)
    if rc != 0:
        raise SandboxError("the copy failed: %s" % ((err or "").strip().splitlines() or ["cp -c"])[0])
    manifest = {r: _meta(st) for r, st in _walk(clone, SANDBOX_MAX_ENTRIES, SANDBOX_LIST_SECONDS).items()}
    _write_private(os.path.join(d, "manifest.json"), json.dumps(manifest).encode())
    for sub in ("home", "tmp"):
        os.mkdir(os.path.join(d, sub), 0o700)
    _link_git_files(os.path.join(d, "home"))


def _link_git_files(rhome):
    """The run's own home points at the git config files (read-only by the
    profile), so a commit inside still carries the user's name."""
    for g in GIT_FILES:
        src = os.path.join(HOME, g)
        if os.path.isfile(src):
            dst = os.path.join(rhome, g)
            os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
            os.symlink(os.path.realpath(src), dst)


def _remove(run):
    """The run ends: its whole dir goes (the kernel leaves overlay's work
    dir mode 000; _rmtree opens it), then its lock."""
    _rmtree(run["dir"])
    release(run)


# ------------------------------------------------------------------ steps
def _hidden(home):
    """HIDDEN as real paths (a /home that is a link to /var/home hides
    /var/home), those that exist, parents first."""
    out = []
    for h in HIDDEN:
        if h == "$HOME":
            if _inside(home, os.path.realpath("/home")):
                continue
            h = home
        if os.path.lexists(h):
            h = os.path.realpath(h)
            if h not in out:
                out.append(h)
    return sorted(out, key=lambda p: (p.count("/"), p))


def _step_env(home, tmp):
    env = {"PATH": os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin",
           "HOME": home, "LANG": os.environ.get("LANG") or "C.UTF-8", "TMPDIR": tmp}
    env.update(STEP_ENV)
    return env


def step_cwd(run, platform=None):
    """The directory a step runs in: the clone on macOS (the `[cwd]` a
    sandboxed goal names), the project itself on Linux (the overlay)."""
    if (platform or run.get("os") or OS) == "macos":
        return os.path.realpath(os.path.join(run["dir"], "clone"))
    return run["cwd"]


def step(run, shell, cmd, platform=None):
    """(argv, cwd, env) for one step of `cmd` through `shell -c`, contained.
    Run it on do.run's leash (its own session, killpg on the timeout),
    stdin from /dev/null, with preexec_fn=preexec."""
    plat = platform or run.get("os") or OS
    if plat == "macos":
        return _mac_step(run, shell, cmd)
    cwd, d = run["cwd"], run["dir"]
    home = os.path.realpath(HOME)
    argv = [shutil.which("bwrap") or "bwrap", "--ro-bind", "/", "/"]
    for h in _hidden(home):
        argv += ["--tmpfs", h]
    for g in GIT_FILES:
        p = os.path.join(home, g)
        argv += ["--ro-bind-try", p, p]
    argv += ["--dev", "/dev", "--proc", "/proc",
             "--overlay-src", cwd, "--overlay", os.path.join(d, "up"), os.path.join(d, "wk"), cwd,
             "--chdir", cwd]
    argv += list(BWRAP_FLAGS)
    argv.append("--clearenv")
    for k, v in sorted(_step_env(home, "/tmp").items()):
        argv += ["--setenv", k, v]
    argv += [shell, "-c", cmd]
    return argv, step_cwd(run, plat), {"PATH": os.environ.get("PATH") or "/usr/bin:/bin"}


def _uvar():
    """The per-user temp and cache root (/private/var/folders/xx/yyyy)."""
    try:
        t = os.confstr(_CS_DARWIN_USER_TEMP_DIR)
    except (OSError, ValueError):
        t = ""
    if t:
        return os.path.realpath(os.path.dirname(t.rstrip("/")))
    return "/private/var/empty/spark-none"


def _mac_step(run, shell, cmd):
    d = run["dir"]
    clone, rhome, tmp = (os.path.realpath(os.path.join(d, s)) for s in ("clone", "home", "tmp"))
    params = [("HOME", os.path.realpath(HOME)), ("STATE", os.path.realpath(STATE_DIR)),
              ("CONFIG", os.path.realpath(CONFIG_DIR)), ("UVAR", _uvar()),
              ("CLONE", clone), ("RHOME", rhome), ("TMP", tmp),
              ("LSREGISTER", LSREGISTER), ("QLMANAGE", QLMANAGE)]
    anc, p = [], os.path.dirname(clone)
    while p and p != "/":
        anc.append(p)
        p = os.path.dirname(p)
    git = [os.path.realpath(os.path.join(HOME, g)) for g in GIT_FILES if os.path.isfile(os.path.join(HOME, g))]
    params += [("ANC_%d" % i, a) for i, a in enumerate(anc)]
    params += [("GIT_%d" % i, g) for i, g in enumerate(git)]
    lines = []
    for line, why in PROFILE:
        if line == "@ANC":
            if not anc:        # an empty filter would allow every path
                continue
            line = "(allow file-read-metadata %s)" % " ".join('(literal (param "ANC_%d"))' % i
                                                            for i in range(len(anc)))
        line = line.replace("@GIT", "".join(' (literal (param "GIT_%d"))' % i for i in range(len(git))))
        lines.append(line + ("   ; " + why if why else ""))
    profile = os.path.join(d, "profile.sb")
    _write_private(profile, ("\n".join(lines) + "\n").encode())
    argv = [SANDBOX_EXEC]
    for k, v in params:
        argv += ["-D", "%s=%s" % (k, v)]
    argv += ["-f", profile, shell, "-c", cmd]
    return argv, clone, _step_env(rhome, tmp)


def preexec():
    """preexec_fn for a step: no file it writes grows past SANDBOX_MAX_BYTES."""
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    cap = SANDBOX_MAX_BYTES
    if hard == resource.RLIM_INFINITY or hard > cap:
        hard = cap
    if soft == resource.RLIM_INFINITY or soft > hard:
        soft = hard
    resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))


def used_bytes(run, seconds=SANDBOX_LIST_SECONDS):
    """What the run has written so far: the upper dir (Linux), the clone's
    new and changed files (macOS)."""
    d = run["dir"]
    try:
        if run["os"] == "macos":
            man = _manifest(run)
            return sum(st.st_size for r, st in _walk(os.path.join(d, "clone"), None, seconds).items()
                       if man.get(r) != _meta(st))
        return sum(st.st_size for st in _walk(os.path.join(d, "up"), None, seconds).values())
    except SandboxError:
        return SANDBOX_MAX_BYTES + 1     # too big to list in time is too big


def over_cap(run):
    """The run wrote more than SANDBOX_MAX_BYTES: the caller stops it."""
    return used_bytes(run) > SANDBOX_MAX_BYTES


# ------------------------------------------------------------------ probe
def _bwrap_version():
    exe = shutil.which("bwrap")
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out or "")
    return m.group(0) if m else "?"


def _probe_key(plat):
    key = {"os": plat, "kernel": os.uname().release}
    if plat == "macos":
        key["tool"] = SANDBOX_EXEC if os.access(SANDBOX_EXEC, os.X_OK) else ""
        return key
    key["bwrap"] = _bwrap_version()
    try:
        with open("/proc/sys/kernel/apparmor_restrict_unprivileged_userns", encoding="utf-8") as f:
            key["userns"] = f.read().strip()
    except OSError:
        key["userns"] = ""
    return key


def install_hint():
    """The line that installs bubblewrap here, when that is what the probe
    lacks (Linux, bwrap absent or too old); else ''."""
    if OS == "macos":
        return ""
    v = _bwrap_version()
    if v and v != "?" and tuple(int(x) for x in v.split(".")[:2]) >= BWRAP_MIN:
        return ""
    from . import packages
    return packages.install_line(["bubblewrap"])


def probe(fresh=False, platform=None):
    """(ok, detail): can this machine run a sandboxed step? One real run,
    cached in STATE/sandbox/probe.json until the bwrap version, the kernel
    or the AppArmor userns switch changes (fresh=True asks again)."""
    plat = platform or OS
    key = _probe_key(plat)
    if not fresh:
        try:
            with open(PROBE_FILE, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("key") == key:
                return bool(c.get("ok")), str(c.get("detail") or "")
        except (OSError, ValueError, AttributeError):
            pass
    try:
        mkdirs(PROBE_DIR)
        good, detail = _probe_mac(key) if plat == "macos" else _probe_linux(key)
    except (OSError, SandboxError) as e:
        good, detail = False, "the probe could not run: %s" % e
    try:
        _write_private(PROBE_FILE, json.dumps({"key": key, "ok": good, "detail": detail}).encode())
    except OSError:
        pass
    return good, detail


def _first_line(s, default):
    for line in (s or "").splitlines():
        if line.strip():
            return line.strip()[:160]
    return default


def _probe_run(run, script, plat):
    argv, cwd, env = step(run, "/bin/sh", script, platform=plat)
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=PROBE_TIMEOUT, start_new_session=True)
        return p.returncode, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "the probe step did not finish in %d s" % PROBE_TIMEOUT
    except OSError as e:
        return 127, str(e)


def _probe_linux(key):
    v = key["bwrap"]
    if not v:
        return False, "no bwrap on PATH (the bubblewrap package)"
    try:
        have = tuple(int(x) for x in v.split(".")[:2])
    except ValueError:
        have = (0, 0)
    if have < BWRAP_MIN:
        return False, "bwrap %s is older than %d.%d (no overlay)" % ((v,) + BWRAP_MIN)
    d = tempfile.mkdtemp(prefix="probe.", dir=PROBE_DIR)
    try:
        lower = os.path.join(d, "lower")
        for sub in ("lower", "up", "wk"):
            os.mkdir(os.path.join(d, sub), 0o700)
        for name, body in (("keep", "a\n"), ("gone", "b\n")):
            with open(os.path.join(lower, name), "w") as f:
                f.write(body)
        marker = os.path.join(d, "marker")
        with open(marker, "w") as f:
            f.write("m\n")
        from shlex import quote
        script = "\n".join((
            'fail() { echo "$1" >&2; exit 3; }',
            "echo c >new || fail 'the copy is not writable'",
            "rm gone || fail 'a file in the copy would not go'",
            "if (: >/etc/.spark-probe) 2>/dev/null; then fail '/etc is writable inside'; fi",
            "if test -e %s; then fail 'spark state is visible inside'; fi" % quote(marker),
            "if [ \"$(grep -c : /proc/net/dev)\" != 1 ]; then fail 'the network is up inside'; fi",
            "if [ -n \"$(ls -A /etc/spark 2>/dev/null)\" ]; then fail '/etc/spark is visible inside'; fi",
        ))
        run = {"id": "probe", "cwd": lower, "dir": d, "os": "linux"}
        rc, err = _probe_run(run, script, "linux")
        if rc != 0:
            return False, _first_line(err, "the probe step exited %d" % rc)
        new, gone = _lstat(os.path.join(d, "up", "new")), _lstat(os.path.join(d, "up", "gone"))
        if not (new and stat.S_ISREG(new.st_mode) and gone and stat.S_ISCHR(gone.st_mode) and gone.st_rdev == 0):
            return False, "the overlay did not record the probe's changes"
        return True, "bwrap %s overlay" % v
    finally:
        _rmtree(d)


def _probe_mac(key):
    if not key.get("tool"):
        return False, "no %s" % SANDBOX_EXEC
    d = tempfile.mkdtemp(prefix="probe.", dir=PROBE_DIR)
    try:
        src, clone = os.path.join(d, "src"), os.path.join(d, "clone")
        for sub in ("src", "clone", "home", "tmp"):
            os.mkdir(os.path.join(d, sub), 0o700)
        with open(os.path.join(src, "keep"), "w") as f:
            f.write("a\n")
        p = subprocess.run(["/bin/cp", "-c", "-p", os.path.join(src, "keep"), os.path.join(clone, "keep")],
                           capture_output=True, text=True, timeout=10)
        if p.returncode != 0:
            return False, _first_line(p.stderr, "cp -c failed")
        marker, outside = os.path.join(d, "marker"), os.path.join(d, "outside")
        with open(marker, "w") as f:
            f.write("m\n")
        from shlex import quote
        # the network: a connect to TEST-NET-1 is refused at once, never a
        # timeout (an unsandboxed one would hang past PROBE_TIMEOUT)
        script = "\n".join((
            'fail() { echo "$1" >&2; exit 3; }',
            "echo c >new || fail 'the copy is not writable'",
            "if (: >%s) 2>/dev/null; then fail 'a write outside the copy went through'; fi" % quote(outside),
            "if cat %s >/dev/null 2>&1; then fail 'the home directory is readable inside'; fi" % quote(marker),
            "net=$(/bin/bash -c ': </dev/tcp/192.0.2.1/9' 2>&1) && fail 'the network is up inside'",
            'case $net in *"not permitted"*) ;; *) fail "the network is not denied inside" ;; esac',
        ))
        run = {"id": "probe", "cwd": src, "dir": d, "os": "macos"}
        rc, err = _probe_run(run, script, "macos")
        if rc != 0:
            return False, _first_line(err, "the probe step exited %d" % rc)
        if not os.path.isfile(os.path.join(clone, "new")) or os.path.lexists(outside):
            return False, "the sandbox did not hold the probe's writes"
        return True, "sandbox-exec"
    finally:
        _rmtree(d)


# ------------------------------------------------------------------ changes
def _manifest(run):
    try:
        with open(os.path.join(run["dir"], "manifest.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise SandboxError("run %s's manifest does not read -- spark do --discard %s" % (run["id"], run["id"]))


def _src_root(run):
    return os.path.join(run["dir"], "clone" if run["os"] == "macos" else "up")


def _is_whiteout(path, st):
    if stat.S_ISCHR(st.st_mode) and st.st_rdev == 0:
        return True     # the overlay's own: a char device 0/0
    return stat.S_ISREG(st.st_mode) and st.st_size == 0 and _xattr(path, WHITEOUT_XATTR) is not None


def _upper_raw(up, low):
    """Linux: (rel, new lstat or None, lower lstat or None) from the upper
    dir. A whiteout is a delete; an opaque dir deletes every lower child
    it does not carry."""
    raw = []
    stack = [""]
    while stack:
        rel = stack.pop()
        udir = os.path.join(up, rel) if rel else up
        try:
            names = os.listdir(udir)
        except OSError:
            continue
        for n in names:
            r = rel + "/" + n if rel else n
            p = os.path.join(up, r)
            st = _lstat(p)
            if st is None:
                continue
            old = _lower(low, r)
            if _is_whiteout(p, st):
                if old is not None:
                    raw.append((r, None, old))
                continue
            raw.append((r, st, old))
            if stat.S_ISDIR(st.st_mode):
                stack.append(r)
        if rel and _xattr(udir, OPAQUE_XATTR) == OPAQUE_VALUE:
            ldir = os.path.join(low, rel)
            lst = _lstat(ldir)
            if lst is not None and stat.S_ISDIR(lst.st_mode):
                for n in os.listdir(ldir):
                    if n not in names:
                        r = rel + "/" + n
                        raw.append((r, None, _lower(low, r)))
    return raw


def _clone_raw(run):
    """macOS: the clone against its manifest; the lower as it is now."""
    man = _manifest(run)
    clone, low = os.path.join(run["dir"], "clone"), run["cwd"]
    now = _walk(clone, SANDBOX_MAX_ENTRIES * 2, SANDBOX_LIST_SECONDS * 3)
    raw = []
    for r, st in now.items():
        m = man.get(r)
        if m is not None and m == _meta(st):
            continue
        raw.append((r, st, _lower(low, r)))
    for r in man:
        if r in now:
            continue
        parent = os.path.dirname(r)
        if parent and parent in man and parent not in now:
            continue            # the parent's delete covers it
        old = _lower(low, r)
        if old is not None:
            raw.append((r, None, old))
    return raw


def _read(path, limit):
    """The file's bytes, or None when larger than limit or unreadable."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(limit + 1)
    return None if len(data) > limit else data


def _text(data):
    if data is None or b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _same(a, b):
    """Two regular files with the same bytes."""
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                x, y = fa.read(65536), fb.read(65536)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def _escapes(cwd, rel, target):
    """A link at rel whose target resolves outside cwd -- lexically, and
    through whatever the project's own links are."""
    base = os.path.dirname(os.path.join(cwd, rel))
    t = os.path.normpath(target if os.path.isabs(target) else os.path.join(base, target))
    if not _inside(t, cwd):
        return True
    return not _inside(os.path.realpath(t), os.path.realpath(cwd))


def _overlay_mark(run, src):
    """The reason an upper entry is refused for an overlay mark, or ''."""
    if run["os"] == "macos":
        return ""
    for name, why in OVERLAY_REFUSED:
        if _xattr(src, name) is not None:
            return why
    return ""


def _classify(run, r, st, old):
    """The review entries for one raw change (none when nothing changed,
    two when the type changed: the old one goes, the new one comes)."""
    if st is not None and old is not None and _kind(st) != _kind(old):
        return _classify(run, r, None, old) + _classify(run, r, st, None)
    src, low = os.path.join(_src_root(run), r), os.path.join(run["cwd"], r)
    e = {"path": r, "status": "", "kind": _kind(st if st is not None else old), "old": None, "new": None,
         "mode_old": stat.S_IMODE(old.st_mode) if old is not None else None,
         "mode_new": stat.S_IMODE(st.st_mode) if st is not None else None,
         "exec_added": False, "reason": "", "sha": None, "control": False, "git": ""}
    k = e["kind"]
    mark = _overlay_mark(run, src) if st is not None else ""
    if st is None:
        e["status"] = "deleted"
        if k == "file":
            e["old"] = _text(_read(low, DIFF_MAX))
        elif k == "link":
            e["old"] = os.readlink(low)
    elif mark:
        e["status"], e["reason"] = "refused", mark
    elif k == "dir":
        if old is None:
            e["status"] = "added"
        elif e["mode_old"] != e["mode_new"]:
            e["status"] = "mode"
        else:
            return []
    elif k == "link":
        target = os.readlink(src)
        e["new"] = e["sha"] = target
        if old is not None:
            e["old"] = os.readlink(low)
            if e["old"] == target:
                return []
        e["status"] = "link"
        if _escapes(run["cwd"], r, target):
            e["status"], e["reason"] = "refused", LINK_OUT
    elif k == "file":
        e["exec_added"] = bool(st.st_mode & 0o111) and not (old is not None and old.st_mode & 0o111)
        if st.st_mode & (stat.S_ISUID | stat.S_ISGID):
            e["reason"] = SETID
        e["sha"] = _sha(src)
        if old is not None and st.st_size == old.st_size and _same(src, low):
            if (e["mode_old"] & 0o777) == (e["mode_new"] & 0o777):
                return []
            e["status"] = "mode"
        else:
            new = _read(src, DIFF_MAX)
            e["status"] = "added" if old is None else "changed"
            e["new"] = _text(new)
            if new is not None and e["new"] is None:
                e["status"] = "binary"
                e["reason"] = e["reason"] or ("%s, %d bytes" % ("added" if old is None else "changed", st.st_size))
            elif new is None:
                e["reason"] = e["reason"] or "%d bytes: %s" % (st.st_size, TOO_LARGE)
            elif old is not None:
                e["old"] = _text(_read(low, DIFF_MAX))
    else:
        e["status"], e["reason"] = "refused", SPECIAL
    return [e]


def _git_name(name):
    """The name is `.git` to git on some filesystem (GITDIR's first half)."""
    return GIT_NAME_IGNORED.sub("", name).casefold() == ".git"


def _bare_shape(*dirs):
    """GITDIR's second half: a HEAD file and an objects/ directory, across
    the given views of one directory (the project's, the copy's)."""
    head = objects = False
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            f = n.casefold()
            if f == "head":
                head = True
            elif f == "objects":
                st = _lstat(os.path.join(d, n))
                objects = objects or bool(st and stat.S_ISDIR(st.st_mode))
    return head and objects


def _cwd_git(cwd):
    """Where the project itself sits inside a git directory: its path from
    the outermost one ('' when it is one), or None."""
    parts = [p for p in cwd.split("/") if p]
    for i in range(len(parts) + 1):
        d = "/" + "/".join(parts[:i])
        if (i and _git_name(parts[i - 1])) or _bare_shape(d):
            return "/".join(parts[i:])
    return None


def _git_keep(inner):
    """GIT_KEEP: inner (a path inside a git directory) applies."""
    if not inner:
        return True         # the git directory itself
    if GIT_KEEP_NOT.fullmatch(inner):
        return False
    return any(p.fullmatch(inner) for p, _why in GIT_KEEP)


def _git_why(inner):
    for p, why in GIT_WHY:
        if p.match(inner):
            return why
    return GIT_WHY[-1][1]


def _mark_git(run, entries):
    """GITDIR, GIT_KEEP and GITFILE over the entries: each git item stays
    its own entry, `git` naming its git directory ('.' when the project is
    inside one), and everything GIT_KEEP does not name is held."""
    low, src = run["cwd"], _src_root(run)
    base = _cwd_git(low)
    seen = {}

    def gitdir(d):
        if d not in seen:
            seen[d] = _git_name(d.rsplit("/", 1)[-1]) or _bare_shape(os.path.join(low, d), os.path.join(src, d))
        return seen[d]

    for e in entries:
        parts = e["path"].split("/")
        git, inner = None, ""
        if base is not None:
            git, inner = ".", "/".join(p for p in (base, e["path"]) if p)
        else:
            for i in range(1, len(parts)):
                d = "/".join(parts[:i])
                if gitdir(d):
                    git, inner = d, "/".join(parts[i:])
                    break
            if git is None and e["kind"] == "dir" and gitdir(e["path"]):
                git = e["path"]         # the git directory itself: shown with its items
        held = ""
        if _git_name(parts[-1]) and e["kind"] != "dir":
            held = GITFILE
        elif git is not None and not _git_keep(inner):
            held = _git_why(inner)
        if git is not None:
            e["git"] = git
        if held and e["status"] != "refused":
            e["status"], e["reason"] = "held", held


def _budget(entries):
    """REVIEW_MAX: the texts one review carries; past it, every later
    entry is a heading, its reason TOO_LARGE."""
    total, over = 0, False
    for e in entries:
        if e["kind"] != "file" or (e["old"] is None and e["new"] is None):
            continue
        total += len(e["old"] or "") + len(e["new"] or "")
        over = over or total > REVIEW_MAX
        if over:
            e["old"] = e["new"] = None
            e["reason"] = e["reason"] + "; " + TOO_LARGE if e["reason"] else TOO_LARGE


def changes(run):
    """The review: entries sorted by path, each {path, status, kind, old,
    new, mode_old, mode_new, exec_added, reason, sha, control, git};
    old/new are the texts (a link's targets), None where there is none to
    show; sha is the sha256 hex of a file's new bytes (a link's target,
    None for a delete or a directory); control says the name or the text
    holds a VISIBLE character; git names the git directory an item is in.
    Every git item is its own entry."""
    raw = _clone_raw(run) if run["os"] == "macos" else _upper_raw(os.path.join(run["dir"], "up"), run["cwd"])
    raw.sort(key=lambda t: t[0].split("/"))
    entries = []
    for r, st, old in raw:
        entries.extend(_classify(run, r, st, old))
    # a deleted directory speaks for everything under it (an opaque one's
    # children, a type change's)
    gone = [e["path"] for e in entries if e["status"] == "deleted" and e["kind"] == "dir"]
    entries = [e for e in entries if not (e["status"] == "deleted" and
                                          any(e["path"].startswith(g + "/") for g in gone))]
    _mark_git(run, entries)
    for e in entries:
        e["control"] = _control(e)
    _budget(entries)
    return entries


def _flatten(entries):
    out = []
    for e in entries:
        out.extend(e["items"] if "items" in e else [e])
    return out


def count(entries):
    """How many changes the review names (git's items counted each)."""
    return len(_flatten(entries))


def fingerprint(entries):
    """What a review showed, as one sha256 hex: every entry's path, status,
    kind, modes and sha -- apply(run, reviewed) applies only a copy that
    still has it."""
    rows = sorted([e["path"], e["status"], e["kind"], e.get("mode_old"), e.get("mode_new"), e.get("sha")]
                  for e in _flatten(entries))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=True).encode()).hexdigest()


def _lines(t):
    """A text's lines, split at the newline alone (str.splitlines would
    break at a form feed or a U+2028 as well, and hide it)."""
    if not t:
        return []
    out = t.split("\n")
    return out[:-1] if out[-1] == "" else out


def diff_text(entries):
    """The review as text: one heading line an entry, a unified diff under
    a text that changed, `(+x)` where a file became executable, `(control
    characters)` where a name or a text held one; every git directory a
    count line, then each of its items on a line of its own, the held with
    their reason. Every line passes visible()."""
    import difflib
    gits = {}
    for e in entries:
        if e.get("git"):
            n, held = gits.get(e["git"], (0, 0))
            gits[e["git"]] = (n + 1, held + (e["status"] == "held"))
    out, shown = [], set()
    for e in entries:
        p, st, g = e["path"], e["status"], e.get("git")
        if g and g not in shown:
            shown.add(g)
            n, held = gits[g]
            out.append("git        %s/ -- %d item%s inside git's own directory, %d held back"
                       % (g, n, "" if n == 1 else "s", held))
        x = " (+x)" if e.get("exec_added") else ""
        c = " (control characters)" if e.get("control") or _control(e) else ""
        why = (" -- " + e["reason"]) if e.get("reason") else ""
        if st == "held":
            out.append("held back  %s%s%s" % (p, c, why))
        elif st == "refused":
            out.append("refused    %s%s%s" % (p, c, why))
        elif st == "mode":
            out.append("mode       %s  %o -> %o%s%s%s" % (p, (e["mode_old"] or 0) & 0o7777,
                                                          (e["mode_new"] or 0) & 0o7777, x, c, why))
        elif st == "link":
            out.append("link       %s -> %s%s" % (p, e["new"], c))
        elif e["kind"] == "dir":
            out.append("%-10s %s/%s" % (st, p, c))
        elif e["kind"] == "link":
            out.append("%-10s %s -> %s%s" % (st, p, e["old"], c))
        elif g or st == "binary" or (e["old"] is None and e["new"] is None):
            out.append("%-10s %s%s%s%s" % (st, p, x, c, why))
        else:
            out.append("%-10s %s%s%s%s" % (st, p, x, c, why))
            out.extend(difflib.unified_diff(_lines(e["old"]), _lines(e["new"]),
                                            "/dev/null" if e["old"] is None else "a/" + p,
                                            "/dev/null" if e["new"] is None else "b/" + p, lineterm=""))
    return "".join(visible(line) + "\n" for line in out)


# ------------------------------------------------------------------ apply
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW


def _walk_to(root_fd, rel, create):
    """(parent dir fd, last name) of rel under root_fd: every component
    opened fd-relative with O_NOFOLLOW, so a symlink on the way refuses
    (ELOOP) instead of carrying the write elsewhere."""
    parts = rel.split("/")
    if any(p in ("", ".", "..") or "\0" in p for p in parts):
        raise OSError(errno.EINVAL, "not a relative path", rel)
    fd = os.dup(root_fd)
    try:
        for p in parts[:-1]:
            try:
                nfd = os.open(p, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(p, 0o700, dir_fd=fd)
                nfd = os.open(p, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd, parts[-1]


def _rm(pfd, name):
    """Remove name (a tree when it is a directory) under pfd, never
    following a link."""
    try:
        st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(st.st_mode):
        os.unlink(name, dir_fd=pfd)
        return
    fd = os.open(name, _DIR_FLAGS, dir_fd=pfd)
    try:
        for n in os.listdir(fd):
            _rm(fd, n)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=pfd)


def _unlink(dfd, name):
    try:
        os.unlink(name, dir_fd=dfd)
    except OSError:
        pass


def _stage(root_fd, src_fd, rel, mode, sha=None):
    """rel's bytes from the source tree into a private temp in the
    project's top directory, hashed as they are copied: the temp's name.
    A hash that is not `sha` (what the review saw): the temp goes, and
    SandboxError(CHANGED) -- the copy changed after the review."""
    spfd, sname = _walk_to(src_fd, rel, False)
    try:
        sfd = os.open(sname, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=spfd)
    finally:
        os.close(spfd)
    tmp = ".spark-apply-%s.tmp" % secrets.token_hex(6)
    try:
        wfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
    except BaseException:
        os.close(sfd)
        raise
    kept = False
    try:
        h = hashlib.sha256()
        try:
            while True:
                chunk = os.read(sfd, 1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                view = memoryview(chunk)
                while view:
                    view = view[os.write(wfd, view):]
            os.fchmod(wfd, mode & 0o777)
        finally:
            os.close(wfd)
            os.close(sfd)
        if sha is not None and h.hexdigest() != sha:
            raise SandboxError(CHANGED, [rel])
        kept = True
        return tmp
    finally:
        if not kept:
            _unlink(root_fd, tmp)


def _place(root_fd, tmp, rel):
    """A staged temp renamed onto rel (never written through it)."""
    pfd, name = _walk_to(root_fd, rel, True)
    try:
        os.rename(tmp, name, src_dir_fd=root_fd, dst_dir_fd=pfd)
    finally:
        os.close(pfd)


def _write_file(root_fd, src_fd, rel, mode, sha=None):
    """rel's bytes from the source tree into the project: staged and
    hashed, then renamed over the old name (never through it)."""
    tmp = _stage(root_fd, src_fd, rel, mode, sha)
    try:
        _place(root_fd, tmp, rel)
    except BaseException:
        _unlink(root_fd, tmp)
        raise


def _write_link(root_fd, rel, target):
    pfd, name = _walk_to(root_fd, rel, True)
    try:
        tmp = ".spark-apply-%s.tmp" % secrets.token_hex(6)
        os.symlink(target, tmp, dir_fd=pfd)
        try:
            os.rename(tmp, name, src_dir_fd=pfd, dst_dir_fd=pfd)
        except OSError:
            os.unlink(tmp, dir_fd=pfd)
            raise
    finally:
        os.close(pfd)


def _make_dir(root_fd, rel):
    pfd, name = _walk_to(root_fd, rel, True)
    try:
        try:
            os.mkdir(name, 0o700, dir_fd=pfd)
        except FileExistsError:
            st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
            if not stat.S_ISDIR(st.st_mode):
                raise
    finally:
        os.close(pfd)


def _chmod(root_fd, rel, mode):
    pfd, name = _walk_to(root_fd, rel, False)
    try:
        st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            raise OSError(errno.ELOOP, "a link, not a file", rel)
        os.chmod(name, mode & 0o777, dir_fd=pfd)
    finally:
        os.close(pfd)


def _delete(root_fd, rel):
    pfd, name = _walk_to(root_fd, rel, False)
    try:
        _rm(pfd, name)
    finally:
        os.close(pfd)


def _newer(st, start):
    """Changed after the run began: its mtime -- or its ctime, which a
    step or a person cannot set back the way `touch -d` sets back mtime."""
    return st.st_mtime_ns > start or st.st_ctime_ns > start


def _conflicts(run, flat):
    """The project paths the run touches that changed after it began."""
    out = []
    for e in flat:
        if e["status"] in ("held", "refused"):
            continue
        low = os.path.join(run["cwd"], e["path"])
        st = _lower(run["cwd"], e["path"])
        if st is None:
            continue
        if e["kind"] == "dir" and e["status"] != "deleted":
            continue     # a directory's times move whenever anything in it does
        if stat.S_ISDIR(st.st_mode) and e["status"] == "deleted":
            try:
                tree = _walk(low, SANDBOX_MAX_ENTRIES, SANDBOX_LIST_SECONDS)
            except SandboxError:
                tree = {}
            if any(_newer(s, run["start"]) for s in tree.values()):
                out.append(e["path"])
                continue
        if _newer(st, run["start"]):
            out.append(e["path"])
    return out


def apply(run, reviewed=None):
    """Apply the run's changes to its project: (applied, problems); the
    run's dir goes. `reviewed` is the entries the person was shown: a copy
    whose changes() no longer has their fingerprint is refused whole
    (CHANGED), and every file's bytes are hashed against it as they are
    copied, before anything is written; None (a non-interactive accept)
    applies what the copy holds now. Refuses whole (SandboxError, nothing
    applied, the run waits) while another process holds the run, on a git
    lock in the change set, on a conflict. Held and refused entries are
    skipped and reported."""
    acquired = _take(run)
    try:
        applied, problems = _apply(run, reviewed)
    except BaseException:
        if acquired:
            release(run)
        raise
    run["state"] = "applied"
    _remove(run)
    return applied, problems


def _apply(run, reviewed):
    if run["state"] not in ("running", "waiting"):
        raise SandboxError("run %s is %s already" % (run["id"], run["state"]))
    entries = changes(run)
    if reviewed is not None and fingerprint(reviewed) != fingerprint(entries):
        raise SandboxError(CHANGED)
    flat = _flatten(entries)
    locks = [e["path"] for e in flat if LOCK.search(e["path"])]
    if locks:
        raise SandboxError("git was mid-command in the copy (%s) -- nothing applied; spark do --discard %s"
                           % (visible(locks[0]), run["id"]), locks)
    conflicts = _conflicts(run, flat)
    if conflicts:
        n = len(conflicts)
        named = ", ".join(visible(c) for c in conflicts[:3]) + (", ..." if n > 3 else "")
        raise SandboxError("%d file%s changed here since the run began (%s) -- nothing applied; spark do "
                           "--discard %s" % (n, "" if n == 1 else "s", named, run["id"]), conflicts)
    problems = ["%s %s -- %s" % ("held back" if e["status"] == "held" else "refused", visible(e["path"]),
                                 e["reason"]) for e in flat if e["status"] in ("held", "refused")]
    todo = [e for e in flat if e["status"] not in ("held", "refused")]
    depth = lambda e: e["path"].count("/")      # noqa: E731
    applied = 0
    try:
        root_fd = os.open(run["cwd"], _DIR_FLAGS)
    except OSError as err:
        raise SandboxError("%s does not open (%s) -- nothing applied" % (run["cwd"], err.strerror or err))
    src_fd = os.open(_src_root(run), _DIR_FLAGS)
    staged = {}

    def attempt(fn, e, *args):
        try:
            fn(*args)
            return True
        except OSError as err:
            problems.append("not applied %s -- %s" % (visible(e["path"]), err.strerror or err))
            return False
    try:
        # every file's bytes first, hashed against the review: a copy that
        # changed since refuses here, before the project is touched
        files = [e for e in todo if e["status"] in ("added", "changed", "binary") and e["kind"] == "file"]
        for e in files:
            try:
                staged[e["path"]] = _stage(root_fd, src_fd, e["path"], e["mode_new"], e["sha"])
            except OSError as err:
                problems.append("not applied %s -- %s" % (visible(e["path"]), err.strerror or err))
        # deletes, deepest first
        for e in sorted((e for e in todo if e["status"] == "deleted"), key=depth, reverse=True):
            applied += attempt(_delete, e, root_fd, e["path"])
        # then creates, top-down
        for e in sorted((e for e in todo if e["status"] in ("added", "changed", "binary", "link")),
                        key=lambda e: (depth(e), e["path"])):
            if e["kind"] == "dir":
                applied += attempt(_make_dir, e, root_fd, e["path"])
            elif e["kind"] == "link":
                applied += attempt(_write_link, e, root_fd, e["path"], e["new"])
            elif e["path"] in staged:
                if attempt(_place, e, root_fd, staged[e["path"]], e["path"]):
                    del staged[e["path"]]
                    applied += 1
        # then modes, deepest first (a directory's last, so its own mode
        # never locks the walk to its children)
        for e in sorted((e for e in todo if e["status"] == "mode" or (e["status"] == "added" and e["kind"] == "dir")),
                        key=depth, reverse=True):
            ok = attempt(_chmod, e, root_fd, e["path"], e["mode_new"])
            applied += ok if e["status"] == "mode" else 0
    finally:
        for tmp in staged.values():
            _unlink(root_fd, tmp)
        os.close(root_fd)
        os.close(src_fd)
    return applied, problems


def discard(run):
    """Drop the run: its whole dir goes. Refuses while another process
    holds it."""
    _take(run)
    run["state"] = "discarded"
    _remove(run)
