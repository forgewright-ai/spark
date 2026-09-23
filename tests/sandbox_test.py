#!/usr/bin/env python3
"""spark do --sandbox's core (lib/spark/sandbox.py), in a throwaway HOME.

First the review and the apply on fabricated trees, so every named line
is proven without a sandbox: the Linux upper walk (added, changed, mode,
link, binary; a whiteout and an opaque dir where the kernel lets a user
make them), VISIBLE (a control character in a text or a name is shown as
an escape and flagged), every named refusal of the apply (a git lock, a
conflict by mtime or ctime, the copy changed after the review, GITDIR /
GIT_KEEP / GITFILE, setuid masked, a link out refused, a fifo refused, an
overlay mark refused, a link in the project cannot carry a write outside
it), REVIEW_MAX, the run's life (the lock its driver holds, claim, a
crashed driver, the cap's lock, the detach lock, the dir gone after the
end), the records (meta.json's fields and modes, the id's shape), the ~
and / refusal, the waiting cap, and the argv a step runs under
(Linux-shaped even on a Mac). Then, only when probe() says this machine
can, a REAL section: steps run contained, the review sees them, apply
applies them, a background writer after the review is refused, and every
escape fails -- a file planted in HOME, /etc/spark/token, the network, a
write to /etc, a unix socket, sudo, an exported variable; on macOS the
extended denies (the temp dirs, the keychains, Shortcuts, Automator,
defaults, Launch Services, the daemons behind them) while the ordinary
tools still work. Exit 0 with a skip line where a primitive is absent.
"""
import fcntl
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

# a throwaway HOME before spark is imported: its paths are read at import
HOME = os.path.realpath(tempfile.mkdtemp(prefix="spark-sandbox-test-"))
for _k in list(os.environ):
    if _k.startswith(("SPARK_", "XDG_", "SITE_")):
        del os.environ[_k]
os.environ.update({"HOME": HOME, "XDG_CONFIG_HOME": HOME + "/.config", "XDG_STATE_HOME": HOME + "/.local/state",
                   "XDG_DATA_HOME": HOME + "/.local/share", "SPARK_NO_REFRESH": "1", "SPARK_YES": "1",
                   "SPARK_TEST_EXPORTED": "exported-value-never-inside"})
LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
sys.path.insert(0, LIB)
from spark import IS_MAC, sandbox  # noqa: E402

IS_LINUX = sys.platform.startswith("linux")
FAILED = 0
SKIPPED = []
ESC, RLO, SURR = chr(0x1b), chr(0x202e), chr(0xdcff)


def check(name, cond, detail=""):
    global FAILED
    if cond:
        print("ok   %s" % name)
    else:
        FAILED += 1
        print("FAIL %s%s" % (name, ("\n  " + sandbox.visible(str(detail))) if detail else ""))


def skip(name, why):
    SKIPPED.append(name)
    print("skip %s -- %s" % (name, why))


def refused(name, fn, contains=""):
    """fn() raises SandboxError whose text holds `contains`; returns it."""
    global FAILED
    try:
        fn()
    except sandbox.SandboxError as e:
        if contains and contains not in str(e):
            FAILED += 1
            print("FAIL %s -- refused, but with: %s" % (name, e))
        else:
            print("ok   %s" % name)
        return e
    except Exception as e:
        FAILED += 1
        print("FAIL %s -- %s: %s" % (name, type(e).__name__, e))
        return None
    FAILED += 1
    print("FAIL %s -- went through instead of refusing" % name)
    return None


_N = [0]


def project(files):
    """A fresh project dir under HOME: {rel: text or bytes or (data, mode)}."""
    _N[0] += 1
    root = os.path.join(HOME, "proj%d" % _N[0])
    os.makedirs(root)
    for rel, v in files.items():
        put(root, rel, v)
    return root


def put(root, rel, v):
    data, mode = v if isinstance(v, tuple) else (v, 0o644)
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data.encode("utf-8", "surrogateescape") if isinstance(data, str) else data)
    os.chmod(p, mode)
    return p


def read(p):
    with open(p, "rb") as f:
        return f.read().decode()


def by_path(entries):
    return {e["path"]: e for e in entries}


def linux_run(files, upper, before=None):
    """A Linux-shaped run: the project (before(root) finishes it, before
    the run begins), then the upper dir a step would have left
    (fabricated -- no bwrap needed). The run's lock is this process's."""
    root = project(files)
    if before:
        before(root)
    run = sandbox.new_run(root, "thread-0", platform="linux")
    up = os.path.join(run["dir"], "up")
    for rel, v in upper.items():
        put(up, rel, v)
    return root, run, up


def clear_runs():
    """Every run dir goes (a test that failed half-way may have left one
    whose lock this process still holds)."""
    try:
        names = os.listdir(sandbox.RUNS_DIR)
    except OSError:
        return
    for n in names:
        if sandbox.ID_SHAPE.match(n):
            sandbox._rmtree(os.path.join(sandbox.RUNS_DIR, n))


def gone(run):
    """The run ended: its whole dir is removed, and load() says so."""
    try:
        sandbox.load(run["id"])
        loads = True
    except sandbox.SandboxError as e:
        loads = "no sandboxed run" not in str(e)
    return not os.path.lexists(run["dir"]) and not loads


def whiteout(path):
    """The overlay's delete mark; False where a user cannot make one."""
    try:
        os.mknod(path, stat.S_IFCHR | 0o600, 0)
        return True
    except (OSError, AttributeError):
        return False


# ------------------------------------------------------------------ the review
def test_upper_walk():
    lower = {"keep.txt": "a\n", "edit.txt": "one\n", "mode.sh": "echo\n", "gone.txt": "bye\n",
             "dir/inner.txt": "in\n"}
    upper = {"keep.txt": "a\n",                     # a copy-up with nothing changed: no entry
             "edit.txt": "one\ntwo\n",
             "new.txt": "new\n",
             "mode.sh": ("echo\n", 0o755),
             "bin.dat": b"\x00\x01\x02",
             "sub/new/deep.txt": "deep\n",
             "su.sh": ("#!/bin/sh\n", 0o4755)}
    root, run, up = linux_run(lower, upper)
    os.symlink("keep.txt", os.path.join(up, "link_in"))
    os.symlink("../../outside", os.path.join(up, "link_out"))
    os.symlink("/etc/passwd", os.path.join(up, "link_abs"))
    os.mkfifo(os.path.join(up, "pipe"))
    e = by_path(sandbox.changes(run))
    check("walk: an unchanged copy-up is no change", "keep.txt" not in e, sorted(e))
    check("walk: a changed text carries old and new",
          e.get("edit.txt", {}).get("status") == "changed" and e["edit.txt"]["old"] == "one\n"
          and e["edit.txt"]["new"] == "one\ntwo\n", e.get("edit.txt"))
    check("walk: a new file is added", e.get("new.txt", {}).get("status") == "added")
    check("walk: same bytes, new mode = mode, +x marked",
          e.get("mode.sh", {}).get("status") == "mode" and e["mode.sh"]["exec_added"], e.get("mode.sh"))
    check("walk: a binary is one line", e.get("bin.dat", {}).get("status") == "binary", e.get("bin.dat"))
    check("walk: new directories are added top-down",
          [e.get(p, {}).get("status") for p in ("sub", "sub/new", "sub/new/deep.txt")] == ["added"] * 3)
    check("walk: a link inside the project is a link",
          e.get("link_in", {}).get("status") == "link" and e["link_in"]["new"] == "keep.txt")
    check("LINK_OUT: a relative link out of the project is refused",
          e.get("link_out", {}).get("status") == "refused" and e["link_out"]["reason"] == sandbox.LINK_OUT)
    check("LINK_OUT: an absolute link out is refused", e.get("link_abs", {}).get("status") == "refused")
    check("SPECIAL: a fifo is refused",
          e.get("pipe", {}).get("status") == "refused" and e["pipe"]["reason"] == sandbox.SPECIAL)
    check("SETID: a setuid file is noted", e.get("su.sh", {}).get("reason") == sandbox.SETID, e.get("su.sh"))
    import hashlib
    check("sha: a file's entry carries the sha256 of its new bytes, a link its target, a dir none",
          e["edit.txt"]["sha"] == hashlib.sha256(b"one\ntwo\n").hexdigest()
          and e["mode.sh"]["sha"] == hashlib.sha256(b"echo\n").hexdigest()
          and e["link_in"]["sha"] == "keep.txt" and e["sub"]["sha"] is None, e["edit.txt"])
    for s in {x["status"] for x in e.values()}:
        check("walk: status %s is one of STATUSES" % s, s in sandbox.STATUSES)
    text = sandbox.diff_text(list(e.values()))
    check("diff: the unified diff shows the new line", "+two" in text and "--- a/edit.txt" in text, text)
    check("diff: +x is marked", "(+x)" in text)
    check("diff: refused links are listed with the reason", "refused    link_out -- " + sandbox.LINK_OUT in text)
    check("diff: a new file diffs from /dev/null", "--- /dev/null" in text)
    sandbox.discard(run)
    check("discard: the run's whole dir goes", gone(run))


def test_visible():
    v = sandbox.visible
    check("VISIBLE: ESC, a C1, DEL and a newline are escapes; TAB stays",
          v("a" + ESC + "[2Kb" + chr(0x85) + chr(0x7f) + "\n\t") == "a\\x1b[2Kb\\x85\\x7f\\x0a\t")
    check("VISIBLE: the bidi controls and a lone surrogate are escapes",
          v(RLO + chr(0x2066) + chr(0x200e) + chr(0x61c) + SURR) == "\\u202e\\u2066\\u200e\\u061c\\udcff")
    check("VISIBLE: plain text and other letters pass as they are", v("caf" + chr(0xe9) + " ok") == "caf" + chr(0xe9) + " ok")
    evil_line = "safe line\n" + ESC + "[1A" + ESC + "[2Kerased the line above\n"
    name = "note" + RLO + "txt.sh"
    root, run, up = linux_run({"a.txt": "a\n"}, {"a.txt": "a\n" + evil_line, name: "hi\n", "plain.txt": "p\n"})
    entries = sandbox.changes(run)
    e = by_path(entries)
    check("VISIBLE: a text with an escape sequence is flagged", e["a.txt"]["control"], e["a.txt"])
    check("VISIBLE: a name with a bidi control is flagged", e[name]["control"], e[name])
    check("VISIBLE: a plain file is not", not e["plain.txt"]["control"])
    text = sandbox.diff_text(entries)
    check("diff: no raw control character reaches the review",
          not any(c in text for c in (ESC, RLO)) and "\\x1b[1A\\x1b[2Kerased" in text, text)
    check("diff: the flagged file and name say so in their heading",
          "changed    a.txt (control characters)" in text
          and "added      note\\u202etxt.sh (control characters)" in text
          and "b/note\\u202etxt.sh" in text, text)
    check("diff: a clean heading carries no flag", "added      plain.txt\n" in text, text)
    # a name that was not UTF-8 (a lone surrogate as os.listdir gives it)
    if IS_LINUX:
        put(up, "raw" + SURR, "x\n")
        text = sandbox.diff_text(sandbox.changes(run))
        check("VISIBLE: a name that was not UTF-8 shows as \\udcff", "raw\\udcff (control characters)" in text, text)
    else:
        skip("VISIBLE: a name that was not UTF-8", "APFS refuses a name that is not UTF-8")
    sandbox.discard(run)


def test_whiteout_and_opaque():
    if not IS_LINUX:
        skip("whiteout and opaque dir", "a char device 0/0 and user.overlay.* xattrs are Linux's")
        return
    root, run, up = linux_run({"gone.txt": "bye\n", "d/a": "a\n", "d/b": "b\n", "tree/x/y": "y\n",
                               "xw.txt": "x\n"}, {})
    if not whiteout(os.path.join(up, "gone.txt")):
        skip("whiteout", "mknod of a char device 0/0 refused here")
    else:
        whiteout(os.path.join(up, "tree"))
        e = by_path(sandbox.changes(run))
        check("whiteout: a char 0/0 is a delete", e.get("gone.txt", {}).get("status") == "deleted", e)
        check("whiteout: a whited-out dir is one delete",
              e.get("tree", {}).get("status") == "deleted" and "tree/x" not in e, sorted(e))
    # the defensive xattr whiteout: a 0-byte file carrying user.overlay.whiteout
    p = put(up, "xw.txt", "")
    try:
        os.setxattr(p, sandbox.WHITEOUT_XATTR, b"")
        e = by_path(sandbox.changes(run))
        check("WHITEOUT_XATTR: an xattr whiteout is a delete", e.get("xw.txt", {}).get("status") == "deleted", e)
    except OSError as err:
        skip("xattr whiteout", "user xattrs not supported here (%s)" % err.strerror)
    os.makedirs(os.path.join(up, "d"))
    put(up, "d/a", "a2\n")
    try:
        os.setxattr(os.path.join(up, "d"), sandbox.OPAQUE_XATTR, b"x")
        e = by_path(sandbox.changes(run))
        check("OPAQUE_VALUE: 'x' is not opaque -- no lower file deleted", "d/b" not in e, sorted(e))
        os.setxattr(os.path.join(up, "d"), sandbox.OPAQUE_XATTR, sandbox.OPAQUE_VALUE)
        e = by_path(sandbox.changes(run))
        check("OPAQUE_VALUE: an opaque dir deletes the lower children it lacks",
              e.get("d/b", {}).get("status") == "deleted" and e.get("d/a", {}).get("status") == "changed", e)
        n, problems = sandbox.apply(run)
        check("opaque: apply deletes the lower child", not os.path.exists(os.path.join(root, "d/b"))
              and read(os.path.join(root, "d/a")) == "a2\n", problems)
    except OSError as err:
        skip("opaque dir", "user xattrs not supported here (%s)" % err.strerror)
        sandbox.discard(run)


def test_overlay_marks():
    """OVERLAY_REFUSED: an upper entry carrying a metacopy or a redirect
    mark is refused (the xattr read faked: bwrap's overlay makes neither)."""
    root, run, up = linux_run({"a.txt": "a\n", "d/x": "x\n"}, {"a.txt": "a2\n", "meta.txt": "m\n", "d/y": "y\n"})
    real = sandbox._xattr
    marks = {os.path.join(up, "meta.txt"): "user.overlay.metacopy", os.path.join(up, "d"): "user.overlay.redirect"}
    os.chmod(os.path.join(up, "d"), 0o700)      # a mode change, so the dir is an entry of its own
    sandbox._xattr = lambda path, name: b"" if marks.get(path) == name else real(path, name)
    try:
        e = by_path(sandbox.changes(run))
    finally:
        sandbox._xattr = real
    names = dict(sandbox.OVERLAY_REFUSED)
    check("OVERLAY_REFUSED: a metacopy upper file is refused",
          e.get("meta.txt", {}).get("status") == "refused"
          and e["meta.txt"]["reason"] == names["user.overlay.metacopy"], e.get("meta.txt"))
    check("OVERLAY_REFUSED: a redirect upper dir is refused",
          e.get("d", {}).get("status") == "refused" and e["d"]["reason"] == names["user.overlay.redirect"], e.get("d"))
    check("OVERLAY_REFUSED: an unmarked entry is not", e.get("a.txt", {}).get("status") == "changed")
    if not IS_MAC:
        sandbox.discard(run)
        return
    sandbox.discard(run)
    # macOS: the clone carries no overlay marks, and none is asked for
    check("OVERLAY_REFUSED: the macOS clone is never asked", sandbox._overlay_mark({"os": "macos"}, "/x") == "")


def test_review_max():
    big = "x" * 200000 + "\n"
    n = 12
    root, run, up = linux_run({}, {"f%02d.txt" % i: big for i in range(n)})
    entries = sandbox.changes(run)
    shown = [e for e in entries if e["new"] is not None]
    held = [e for e in entries if e["new"] is None]
    total = sum(len(e["new"]) for e in shown)
    check("REVIEW_MAX: the review carries texts up to its cap, no further",
          shown and held and total <= sandbox.REVIEW_MAX and len(shown) + len(held) == n
          and [e["path"] for e in entries[:len(shown)]] == [e["path"] for e in shown], (len(shown), total))
    check("REVIEW_MAX: past it, the texts are gone and the reason says so",
          all(e["reason"] == sandbox.TOO_LARGE and e["old"] is None for e in held), held[:1])
    check("REVIEW_MAX: every file still carries its sha (the apply checks it)", all(e["sha"] for e in entries))
    text = sandbox.diff_text(entries)
    check("REVIEW_MAX: the diff shows a heading for each held text", text.count("-- " + sandbox.TOO_LARGE) == len(held))
    sandbox.apply(run)
    check("REVIEW_MAX: a heading-only entry still applies", read(os.path.join(root, "f%02d.txt" % (n - 1))) == big)


# ------------------------------------------------------------------ the apply
def test_apply():
    lower = {"edit.txt": "one\n", "mode.sh": "echo\n", "dir/inner.txt": "in\n"}
    upper = {"edit.txt": "one\ntwo\n", "new.txt": "new\n", "mode.sh": ("echo\n", 0o755),
             "sub/new/deep.txt": "deep\n", "su.sh": ("#!/bin/sh\n", 0o6755), "bin.dat": b"\x00\xff"}
    root, run, up = linux_run(lower, upper)
    os.symlink("edit.txt", os.path.join(up, "link_in"))
    os.symlink("/etc", os.path.join(up, "link_out"))
    os.mkfifo(os.path.join(up, "pipe"))
    reviewed = sandbox.changes(run)
    n, problems = sandbox.apply(run, reviewed)
    check("apply: the reviewed changes apply (the fingerprint matches)", n > 0, problems)
    check("apply: the changed text lands", read(os.path.join(root, "edit.txt")) == "one\ntwo\n")
    check("apply: the added files land", read(os.path.join(root, "new.txt")) == "new\n"
          and read(os.path.join(root, "sub/new/deep.txt")) == "deep\n")
    check("apply: a mode-only change lands", stat.S_IMODE(os.stat(os.path.join(root, "mode.sh")).st_mode) == 0o755)
    check("SETID: the setuid/setgid bits are masked",
          stat.S_IMODE(os.stat(os.path.join(root, "su.sh")).st_mode) == 0o755)
    check("apply: a binary lands", open(os.path.join(root, "bin.dat"), "rb").read() == b"\x00\xff")
    check("apply: a link inside is copied as a link", os.readlink(os.path.join(root, "link_in")) == "edit.txt")
    check("LINK_OUT: the link out is not applied", not os.path.lexists(os.path.join(root, "link_out")))
    check("SPECIAL: the fifo is not applied", not os.path.lexists(os.path.join(root, "pipe")))
    check("apply: refusals are reported", any("link_out" in p for p in problems)
          and any("pipe" in p for p in problems), problems)
    check("apply: no temp file left", not [f for f in os.listdir(root) if f.startswith(".spark-apply")])
    check("apply: the run's whole dir goes; load says there is no such run", gone(run))
    refused("apply: an applied run cannot apply twice", lambda: sandbox.apply(run), "no sandboxed run")


def test_reviewed():
    """CHANGED: apply(run, reviewed) applies what was reviewed or nothing."""
    root, run, up = linux_run({"a.txt": "a\n"}, {"a.txt": "a2\n", "b.txt": "b\n"})
    reviewed = sandbox.changes(run)
    put(up, "b.txt", "b, and a line written after the review\n")       # a background writer
    refused("CHANGED: a copy that changed after the review is refused whole",
            lambda: sandbox.apply(run, reviewed), sandbox.CHANGED)
    check("CHANGED: nothing applied", read(os.path.join(root, "a.txt")) == "a\n"
          and not os.path.exists(os.path.join(root, "b.txt")))
    check("CHANGED: the run is still there, its lock still this process's",
          os.path.isdir(run["dir"]) and run.get("lock") is not None)
    put(up, "c.txt", "c\n")                                            # a new file, too
    refused("CHANGED: a file added after the review is refused whole",
            lambda: sandbox.apply(run, sandbox.changes(run)[:-1]), sandbox.CHANGED)
    # the hash while copying: a source whose bytes are not the reviewed ones
    root_fd, src_fd = os.open(root, os.O_RDONLY), os.open(up, os.O_RDONLY)
    try:
        refused("CHANGED: _write_file hashes as it copies and aborts on a mismatch",
                lambda: sandbox._write_file(root_fd, src_fd, "b.txt", 0o644, "0" * 64), sandbox.CHANGED)
    finally:
        os.close(root_fd)
        os.close(src_fd)
    check("CHANGED: the aborted copy leaves no temp and no file",
          not os.path.exists(os.path.join(root, "b.txt"))
          and not [f for f in os.listdir(root) if f.startswith(".spark-apply")])
    n, problems = sandbox.apply(run, sandbox.changes(run))
    check("CHANGED: a fresh review applies", n == 3 and read(os.path.join(root, "b.txt")).startswith("b, and")
          and gone(run), (n, problems))
    root, run, up = linux_run({"a.txt": "a\n"}, {"a.txt": "a2\n"})
    put(up, "late.txt", "late\n")
    n, problems = sandbox.apply(run)
    check("CHANGED: reviewed=None (a non-interactive accept) applies what the copy holds now",
          n == 2 and os.path.exists(os.path.join(root, "late.txt")), (n, problems))


def test_lock_refused():
    root, run, up = linux_run({"a.txt": "a\n", ".git/HEAD": "ref\n"},
                              {"b.txt": "b\n", ".git/index.lock": "x"})
    e = refused("LOCK: a git lock in the change set refuses the whole apply", lambda: sandbox.apply(run),
                "mid-command")
    check("LOCK: nothing applied", not os.path.exists(os.path.join(root, "b.txt")))
    check("LOCK: the lock is named", e is not None and e.paths == [".git/index.lock"], e and e.paths)
    check("LOCK: the run is still there", os.path.isdir(run["dir"]) and sandbox.load(run["id"])["id"] == run["id"])
    sandbox.discard(run)


def test_conflict_refused():
    root, run, up = linux_run({"a.txt": "a\n", "b.txt": "b\n"}, {"a.txt": "a from the run\n", "c.txt": "c\n"})
    later = run["start"] + 10 ** 9
    os.utime(os.path.join(root, "a.txt"), ns=(later, later))
    e = refused("CONFLICT: a touched file newer than the run's start refuses the whole apply",
                lambda: sandbox.apply(run), "changed here since the run began")
    check("CONFLICT: the conflict is listed", e is not None and e.paths == ["a.txt"], e and e.paths)
    check("CONFLICT: nothing applied", read(os.path.join(root, "a.txt")) == "a\n"
          and not os.path.exists(os.path.join(root, "c.txt")))
    # the mtime set back (touch -d, os.utime) moves the ctime forward: still a conflict
    os.utime(os.path.join(root, "a.txt"), ns=(run["start"] - 10 ** 9,) * 2)
    check("CONFLICT: the mtime set back to before the run", os.stat(os.path.join(root, "a.txt")).st_mtime_ns
          < run["start"] < os.stat(os.path.join(root, "a.txt")).st_ctime_ns)
    refused("CONFLICT: the ctime still says it changed since the run began", lambda: sandbox.apply(run),
            "changed here since the run began")
    sandbox.discard(run)
    root, run, up = linux_run({"a.txt": "a\n", "b.txt": "b\n"}, {"a.txt": "a from the run\n"})
    with open(os.path.join(root, "b.txt"), "a") as f:     # untouched by the run: no conflict
        f.write("edited here\n")
    n, problems = sandbox.apply(run)
    check("CONFLICT: a file changed here that the run did not touch is no conflict",
          read(os.path.join(root, "a.txt")) == "a from the run\n", problems)


def test_git():
    """GITDIR, GIT_KEEP, GITFILE: inside any git directory only git's own
    bookkeeping applies; every git item is its own entry."""
    root, run, up = linux_run({".git/HEAD": "ref: refs/heads/main\n", ".git/config": "[core]\n",
                               "sub/.git/config": "[core]\n"},
                              {".git/HEAD": "ref: refs/heads/other\n", ".git/objects/ab/cd": b"\x78\x01",
                               ".git/refs/heads/other": "0" * 40 + "\n", ".git/index": b"DIRC",
                               ".git/logs/HEAD": "log\n", ".git/info/exclude": "*.o\n",
                               ".git/COMMIT_EDITMSG": "msg\n",
                               ".git/hooks/pre-commit": ("#!/bin/sh\necho owned\n", 0o755),
                               ".git/config": "[core]\n\thooksPath = /tmp\n",
                               ".git/commondir": "../elsewhere\n",
                               ".git/info/attributes": "* filter=x\n",
                               ".git/objects/info/alternates": "/elsewhere/objects\n",
                               ".git/modules/lib/hooks/post-checkout": "#!/bin/sh\n",
                               ".git/modules/lib/config": "[core]\n",
                               ".git/worktrees/w/config.worktree": "[core]\n",
                               "sub/.git/config": "[core]\n\tpager = sh\n"})
    entries = sandbox.changes(run)
    e = by_path(entries)
    held = sorted(p for p, x in e.items() if x["status"] == "held")
    for p in (".git/hooks", ".git/hooks/pre-commit", ".git/config", ".git/commondir", ".git/info/attributes",
              ".git/objects/info/alternates", ".git/modules/lib/config", ".git/modules/lib/hooks/post-checkout",
              ".git/worktrees/w/config.worktree", "sub/.git/config"):
        check("GIT_KEEP: %s is held" % p, p in held, held)
    kept = [".git/HEAD", ".git/objects/ab/cd", ".git/refs/heads/other", ".git/index", ".git/logs/HEAD",
            ".git/info/exclude", ".git/COMMIT_EDITMSG"]
    for p in kept:
        check("GIT_KEEP: %s applies" % p, e.get(p, {}).get("status") in ("added", "changed", "binary"), e.get(p))
    check("GIT_KEEP: the held carry their reason",
          e[".git/hooks/pre-commit"]["reason"].startswith("a git hook")
          and e[".git/config"]["reason"].startswith("git config")
          and "another directory" in e[".git/commondir"]["reason"], e[".git/commondir"])
    check("git: every git item is its own entry, naming its git directory",
          not [x for x in entries if "items" in x] and e[".git/objects/ab/cd"]["git"] == ".git"
          and e["sub/.git/config"]["git"] == "sub/.git" and sandbox.count(entries) == len(entries))
    text = sandbox.diff_text(entries)
    check("diff: a count line for each git directory, then every item listed",
          "git        .git/ -- " in text and "held back" in text.split("git        .git/ -- ")[1].split("\n")[0]
          and all(("held back  %s -- " % p) in text for p in held), text)
    check("diff: git's own files are headings, not diffs", "--- a/.git" not in text and "+++ b/.git" not in text)
    n, problems = sandbox.apply(run)
    check("GIT_KEEP: the hook is never applied", not os.path.exists(os.path.join(root, ".git/hooks")))
    check("GIT_KEEP: the configs are never applied", read(os.path.join(root, ".git/config")) == "[core]\n"
          and read(os.path.join(root, "sub/.git/config")) == "[core]\n"
          and not os.path.exists(os.path.join(root, ".git/commondir"))
          and not os.path.exists(os.path.join(root, ".git/objects/info/alternates")))
    check("GIT_KEEP: objects, refs, the index and HEAD apply",
          read(os.path.join(root, ".git/HEAD")) == "ref: refs/heads/other\n"
          and os.path.isfile(os.path.join(root, ".git/objects/ab/cd"))
          and os.path.isfile(os.path.join(root, ".git/refs/heads/other"))
          and os.path.isfile(os.path.join(root, ".git/index"))
          and read(os.path.join(root, ".git/info/exclude")) == "*.o\n", (n, problems))
    check("GIT_KEEP: the held are reported", any(p.startswith("held back .git/config") for p in problems), problems)


def test_gitfile_bypass():
    """The verified bypass: a `.git` FILE saying `gitdir: ../fakegit`, and
    fakegit/ with a config naming hooksPath and an executable hook."""
    root, run, up = linux_run({"sub/a.txt": "a\n"},
                              {"sub/.git": "gitdir: ../fakegit\n",
                               "fakegit/HEAD": "ref: refs/heads/main\n", "fakegit/objects/.keep": "",
                               "fakegit/refs/heads/.keep": "",
                               "fakegit/config": "[core]\n\thooksPath = hooks\n",
                               "fakegit/hooks/pre-commit": ("#!/bin/sh\necho owned\n", 0o755),
                               "fakegit/description": "x\n", "notgit/config": "[core]\n"})
    e = by_path(sandbox.changes(run))
    check("GITFILE: a .git that is a file is held",
          e.get("sub/.git", {}).get("status") == "held" and e["sub/.git"]["reason"] == sandbox.GITFILE,
          e.get("sub/.git"))
    check("GITDIR: a directory holding HEAD and objects/ is a git directory, whatever its name",
          e.get("fakegit/config", {}).get("status") == "held"
          and e.get("fakegit/hooks/pre-commit", {}).get("status") == "held"
          and e["fakegit/config"]["git"] == "fakegit", {p: x["status"] for p, x in e.items()})
    check("GITDIR: its GIT_KEEP files still apply",
          [e.get(p, {}).get("status") for p in ("fakegit/HEAD", "fakegit/description")] == ["added", "added"])
    check("GITDIR: a directory without HEAD and objects/ is not one",
          e.get("notgit/config", {}).get("status") == "added" and not e["notgit/config"]["git"])
    sandbox.apply(run)
    check("GITFILE: the redirect and the hook never reach the project",
          not os.path.lexists(os.path.join(root, "sub/.git"))
          and not os.path.exists(os.path.join(root, "fakegit/hooks"))
          and not os.path.exists(os.path.join(root, "fakegit/config"))
          and os.path.isfile(os.path.join(root, "fakegit/HEAD")))
    # a link named .git is a .git that is not a directory too
    root, run, up = linux_run({"a.txt": "a\n"}, {})
    os.symlink("fakegit", os.path.join(up, ".git"))
    e = by_path(sandbox.changes(run))
    check("GITFILE: a link named .git is held", e.get(".git", {}).get("status") == "held", e.get(".git"))
    sandbox.discard(run)


def test_git_shapes():
    # the lower half of the shape counts too: HEAD in the project, objects/ in the copy
    root, run, up = linux_run({"store/HEAD": "ref: refs/heads/main\n", "store/description": "d\n"},
                              {"store/objects/aa/bb": b"\x78\x01", "store/config": "[core]\n",
                               "store/hooks/post-update": ("#!/bin/sh\n", 0o755), "store/description": "d2\n"})
    e = by_path(sandbox.changes(run))
    check("GITDIR: a bare-shaped git directory under another name holds its config and hooks",
          [e.get(p, {}).get("status") for p in ("store/config", "store/hooks/post-update")] == ["held", "held"], e)
    check("GITDIR: ...and applies GIT_KEEP (objects, description)",
          e.get("store/objects/aa/bb", {}).get("status") in ("added", "binary")
          and e.get("store/description", {}).get("status") == "changed", e)
    sandbox.discard(run)
    # a case-folded .GIT is .git on a case-insensitive filesystem (a Mac's)
    root, run, up = linux_run({"a.txt": "a\n"}, {".GIT/hooks/pre-commit": ("#!/bin/sh\n", 0o755),
                                                 ".GIT/config": "[core]\n"})
    e = by_path(sandbox.changes(run))
    check("GITDIR: .GIT is a git directory (case folded)",
          e.get(".GIT/hooks/pre-commit", {}).get("status") == "held"
          and e.get(".GIT/config", {}).get("status") == "held", {p: x["status"] for p, x in e.items()})
    sandbox.discard(run)
    check("GITDIR: .Git and a .git with a character HFS+ ignores are .git, .gitx is not",
          sandbox._git_name(".Git") and sandbox._git_name(".g" + chr(0x200c) + "it")
          and sandbox._git_name(chr(0xfeff) + ".git") and not sandbox._git_name(".gitx"))
    # the project itself is a git directory (a bare repository): nothing but GIT_KEEP applies
    root, run, up = linux_run({"HEAD": "ref: refs/heads/main\n", "objects/.keep": "", "refs/.keep": ""},
                              {"hooks/pre-receive": ("#!/bin/sh\n", 0o755), "config": "[core]\n",
                               "refs/heads/x": "0" * 40 + "\n"})
    e = by_path(sandbox.changes(run))
    check("GITDIR: in a project that is itself a git directory, hooks and config are held",
          [e.get(p, {}).get("status") for p in ("hooks", "hooks/pre-receive", "config")] == ["held"] * 3
          and e["config"]["git"] == ".", {p: x["status"] for p, x in e.items()})
    check("GITDIR: ...and refs apply", e.get("refs/heads/x", {}).get("status") == "added")
    sandbox.discard(run)


def test_symlink_redirect():
    outside = os.path.join(HOME, "outside")
    os.makedirs(outside)
    root, run, up = linux_run({"a.txt": "a\n"}, {"out/evil.txt": "evil\n", "b.txt": "b\n"},
                              before=lambda r: os.symlink(outside, os.path.join(r, "out")))
    root_fd = os.open(root, os.O_RDONLY)
    src_fd = os.open(up, os.O_RDONLY)
    try:
        sandbox._write_file(root_fd, src_fd, "out/evil.txt", 0o644)
        went = True
    except OSError:
        went = False
    finally:
        os.close(root_fd)
        os.close(src_fd)
    check("O_NOFOLLOW: a write through a project link refuses",
          not went and not os.path.exists(os.path.join(outside, "evil.txt"))
          and not [f for f in os.listdir(root) if f.startswith(".spark-apply")])
    n, problems = sandbox.apply(run)
    check("O_NOFOLLOW: the apply replaces the link, never writes through it",
          not os.path.exists(os.path.join(outside, "evil.txt"))
          and not os.path.islink(os.path.join(root, "out"))
          and read(os.path.join(root, "out/evil.txt")) == "evil\n", problems)


def test_discard_mode000():
    root, run, up = linux_run({"a.txt": "a\n"}, {"b.txt": "b\n"})
    work = os.path.join(run["dir"], "wk", "work")
    os.makedirs(os.path.join(work, "x"))
    os.chmod(work, 0)
    sandbox.discard(run)
    check("discard: a mode-000 work dir goes with the whole run", gone(run))
    check("discard: the run is listed no more", run["id"] not in [r["id"] for r in sandbox.runs()])
    check("discard: its lock is let go", "lock" not in run)


# ------------------------------------------------------------------ the run's life
HOLDER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
time.sleep(60)
"""


def hold(path):
    """A process holding the flock on path until it is killed."""
    p = subprocess.Popen([sys.executable, "-c", HOLDER, path], stdout=subprocess.PIPE)
    p.stdout.readline()
    return p


def test_run_lock():
    clear_runs()
    root = project({"a.txt": "a\n"})
    run = sandbox.new_run(root, "t", platform="linux")
    check("STATES: a new run is running, its lock this process's",
          run["state"] == "running" and run.get("lock") is not None
          and sandbox.load(run["id"])["state"] == "running" and set(sandbox.STATES) >= {"running", "waiting"})
    check("lock: runs/<id>/lock is 0600", stat.S_IMODE(os.stat(os.path.join(run["dir"], sandbox.RUN_LOCK)).st_mode)
          == 0o600)
    listed = sandbox.runs()
    check("runs: a run whose lock is held is listed, flagged running",
          [(r["id"], r["running"]) for r in listed] == [(run["id"], True)], listed)
    refused("claim: refused while another holder has the run", lambda: sandbox.claim(run["id"]),
            sandbox.RUNNING % run["id"])
    refused("apply: refused while another holder has the run", lambda: sandbox.apply(sandbox.load(run["id"])),
            "still running")
    refused("discard: refused while another holder has the run", lambda: sandbox.discard(sandbox.load(run["id"])),
            "still running")
    # another process holds it
    sandbox.release(run)
    holder = hold(os.path.join(run["dir"], sandbox.RUN_LOCK))
    try:
        refused("claim: refused while another process holds the lock", lambda: sandbox.claim(run["id"]),
                "still running")
        check("runs: ...and it is listed as running", [r["running"] for r in sandbox.runs()] == [True])
    finally:
        holder.kill()
        holder.wait()
    # the holder died with the record still saying running: a crashed driver
    listed = sandbox.runs()
    check("runs: a run whose driver died waits (state waiting, not running)",
          [(r["state"], r["running"]) for r in listed] == [("waiting", False)], listed)
    got = sandbox.claim(run["id"])
    check("claim: a crashed run is claimed, recorded waiting, its lock taken",
          got["state"] == "waiting" and sandbox.load(run["id"])["state"] == "waiting" and got.get("lock") is not None)
    refused("claim: a second claim is refused while the first holds", lambda: sandbox.claim(run["id"]), "still running")
    sandbox.release(got)
    got = sandbox.claim(run["id"])
    sandbox.discard(got)
    check("discard: the claimed run's whole dir goes", gone(run))
    refused("claim: an unknown id", lambda: sandbox.claim(run["id"]), "no sandboxed run " + run["id"])


CAPPER = """
import os, sys
sys.path.insert(0, sys.argv[1])
from spark import sandbox
r = sandbox.new_run(sys.argv[2], "t", platform="linux")
print(r["id"], flush=True)
"""


def test_cap_lock():
    """RUNS_LOCK: new_run's count and mkdir wait for the lock, so two
    processes cannot both take the last place."""
    clear_runs()
    root = project({"a.txt": "a\n"})
    sandbox.mkdirs(sandbox.RUNS_DIR)
    fd = os.open(sandbox.RUNS_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    p = subprocess.Popen([sys.executable, "-c", CAPPER, LIB, root], stdout=subprocess.PIPE)
    try:
        time.sleep(0.8)
        check("RUNS_LOCK: a new run waits while another process counts", p.poll() is None and not sandbox.runs())
    finally:
        os.close(fd)
    out, _ = p.communicate(timeout=30)
    rid = out.decode().strip()
    check("RUNS_LOCK: ...and is made once the lock is free", p.returncode == 0 and bool(sandbox.ID_SHAPE.match(rid))
          and [r["id"] for r in sandbox.runs()] == [rid], out)
    check("lock files: runs/.lock is 0600", stat.S_IMODE(os.stat(sandbox.RUNS_LOCK).st_mode) == 0o600)
    clear_runs()


def test_detach_lock():
    fd = sandbox.detach_lock()
    refused("detach_lock: a second detached run is refused", sandbox.detach_lock, sandbox.DETACHED)
    holder = None
    os.close(fd)
    try:
        fd = sandbox.detach_lock()
        os.close(fd)
        check("detach_lock: free again once the first lets go", True)
        holder = hold(os.path.join(sandbox.RUNS_DIR, sandbox.DETACH_LOCK))
        refused("detach_lock: refused while another process holds it", sandbox.detach_lock, sandbox.DETACHED)
    finally:
        if holder:
            holder.kill()
            holder.wait()
    check("detach_lock: runs/detach.lock is 0600",
          stat.S_IMODE(os.stat(os.path.join(sandbox.RUNS_DIR, sandbox.DETACH_LOCK)).st_mode) == 0o600)


# ------------------------------------------------------------------ the records
def mode_of(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_records():
    clear_runs()
    root = project({"a.txt": "a\n"})
    run = sandbox.new_run(root, "thread-7", platform="linux")
    meta_path = os.path.join(run["dir"], "meta.json")
    with open(meta_path) as f:
        meta = json.load(f)
    check("META_FIELDS: meta.json holds only numbers and names",
          sorted(meta) == sorted(sandbox.META_FIELDS), sorted(meta))
    check("META_FIELDS: no goal words", "goal" not in read(meta_path) and meta["thread"] == "thread-7"
          and isinstance(meta["start"], int) and meta["state"] == "running" and meta["cwd"] == root)
    check("records: meta.json is 0600", mode_of(meta_path) == 0o600, oct(mode_of(meta_path)))
    for p in (sandbox.RUNS_DIR, run["dir"], os.path.join(run["dir"], "up"), os.path.join(run["dir"], "wk")):
        check("records: %s is 0700" % os.path.relpath(p, HOME), mode_of(p) == 0o700, oct(mode_of(p)))
    sandbox.mark(run, "waiting")
    check("records: mark() records the state", sandbox.load(run["id"])["state"] == "waiting")
    check("records: runs() lists the run", [r["id"] for r in sandbox.runs()] == [run["id"]])
    sandbox.discard(run)


def test_ids():
    check("ID_SHAPE: a new id has the shape", bool(sandbox.ID_SHAPE.match("20260922-101500-a1b2c3")))
    for bad in ("../../etc", "", None, "20260922-101500-a1b2cg", "20260922-101500-a1b2c3/..", "x" * 200):
        refused("ID_SHAPE: load(%r) is refused before the filesystem" % (bad if not bad or len(bad) < 30 else "x*200"),
                lambda b=bad: sandbox.load(b), "not a sandboxed run's id")
        refused("ID_SHAPE: claim(%r) too" % (bad if not bad or len(bad) < 30 else "x*200"),
                lambda b=bad: sandbox.claim(b), "not a sandboxed run's id")
    refused("load: a well-shaped id that does not exist", lambda: sandbox.load("20000101-000000-000000"),
            "no sandboxed run 20000101-000000-000000")


def test_home_and_root():
    e = refused("NEEDS_PROJECT: ~ is refused", lambda: sandbox.new_run(HOME, "t", platform="linux"))
    check("NEEDS_PROJECT: the text is the signed line's", e is not None and str(e) == sandbox.NEEDS_PROJECT, e)
    refused("NEEDS_PROJECT: / is refused", lambda: sandbox.new_run("/", "t", platform="linux"),
            sandbox.NEEDS_PROJECT)
    refused("NEEDS_PROJECT: a parent of spark's state is refused",
            lambda: sandbox.new_run(os.path.join(HOME, ".local"), "t", platform="linux"), sandbox.NEEDS_PROJECT)


def test_waiting_cap():
    clear_runs()
    root = project({"a.txt": "a\n"})
    made = [sandbox.new_run(root, "t", platform="linux") for _ in range(sandbox.SANDBOX_MAX_WAITING)]
    for r in made[:2]:
        sandbox.mark(r, "waiting")
        sandbox.release(r)
    refused("SANDBOX_MAX_WAITING: a sixth run, running or waiting, is refused",
            lambda: sandbox.new_run(root, "t", platform="linux"), "spark do --review")
    for r in made:
        sandbox.discard(r)
    check("SANDBOX_MAX_WAITING: an ended run frees its place", sandbox.new_run(root, "t", platform="linux")
          is not None)
    clear_runs()


# ------------------------------------------------------------------ the argv
def test_step_linux_shape():
    root = project({"a.txt": "a\n"})
    run = sandbox.new_run(root, "t", platform="linux")
    argv, cwd, env = sandbox.step(run, "sh", "echo hi", platform="linux")
    check("step_cwd: a Linux step runs in the project (the overlay)",
          cwd == root == sandbox.step_cwd(run, platform="linux"))
    check("step: the root is read-only first", argv[1:4] == ["--ro-bind", "/", "/"], argv[:4])
    tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    check("HIDDEN: HOME is under an empty tmpfs", HOME in tmpfs or any(HOME.startswith(t + "/") for t in tmpfs),
          tmpfs)
    check("HIDDEN: /var/tmp is under an empty tmpfs", "/var/tmp" in sandbox.HIDDEN
          and (not os.path.lexists("/var/tmp") or os.path.realpath("/var/tmp") in tmpfs), tmpfs)
    check("HIDDEN: only paths that exist", all(os.path.lexists(t) for t in tmpfs), tmpfs)
    ov = argv.index("--overlay-src")
    check("step: the overlay, lower then upper then work, onto the project",
          argv[ov:ov + 8] == ["--overlay-src", root, "--overlay", os.path.join(run["dir"], "up"),
                              os.path.join(run["dir"], "wk"), root, "--chdir", root], argv[ov:ov + 8])
    check("step: every tmpfs and git bind comes before the overlay",
          all(i < ov for i, a in enumerate(argv) if a in ("--tmpfs", "--ro-bind-try")))
    binds = [argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind-try"]
    check("GIT_FILES: the git config files, file by file",
          binds == [os.path.join(HOME, g) for g in sandbox.GIT_FILES], binds)
    check("GIT_FILES: never the directory (credentials live there)",
          os.path.join(HOME, ".config", "git") not in binds)
    for flag in sandbox.BWRAP_FLAGS:
        check("BWRAP_FLAGS: %s" % flag, flag in argv)
    check("step: --clearenv before any --setenv", argv.index("--clearenv") < argv.index("--setenv"))
    setenv = {argv[i + 1]: argv[i + 2] for i, a in enumerate(argv) if a == "--setenv"}
    for k, v in sandbox.STEP_ENV:
        check("STEP_ENV: %s=%s" % (k, v), setenv.get(k) == v, setenv)
    check("STEP_ENV: HOME is the (hidden) home, TMPDIR the step's /tmp",
          setenv.get("HOME") == HOME and setenv.get("TMPDIR") == "/tmp", setenv)
    check("STEP_ENV: nothing exported crosses", "exported-value-never-inside" not in " ".join(argv)
          and "SPARK_TEST_EXPORTED" not in setenv)
    check("step: the shell runs last", argv[-3:] == ["sh", "-c", "echo hi"], argv[-3:])
    check("step: step_argv is gone (step(...)[0] is the argv)", not hasattr(sandbox, "step_argv"))
    sandbox.discard(run)


def test_step_mac_shape():
    d = tempfile.mkdtemp(dir=HOME, prefix="macshape.")
    for sub in ("clone", "home", "tmp"):
        os.mkdir(os.path.join(d, sub))
    run = {"id": "20260922-000000-000000", "cwd": os.path.join(HOME, "proj"), "dir": d, "os": "macos"}
    argv, cwd, env = sandbox.step(run, "zsh", "echo hi", platform="macos")
    prof = argv[argv.index("-f") + 1]
    text = read(prof)
    check("PROFILE: sandbox-exec with a profile file", argv[0] == sandbox.SANDBOX_EXEC and os.path.isfile(prof))
    check("PROFILE: the profile is 0600", mode_of(prof) == 0o600, oct(mode_of(prof)))
    check("PROFILE: paths arrive as parameters, never in the text", HOME not in text and d not in text, text)
    for line, why in sandbox.PROFILE:
        if not line.startswith("@"):
            check("PROFILE: %s" % (why or line), line.split("@")[0] in text)
    check("PROFILE: no filterless allow (an empty literal list would allow all)",
          "(allow file-read-metadata)" not in text)
    check("PROFILE: the default stays allow, the network denied",
          "(allow default)" in text and "(deny network*)" in text)
    for path in ("/private/var/folders", "/private/tmp", "/private/var/tmp", "/Library/Keychains", "/private/var/root",
                 "/opt/homebrew/etc", "/usr/local/etc"):
        check("PROFILE: reads under %s are denied" % path, '(subpath "%s")' % path in text)
    for exe in ("shortcuts", "automator", "defaults", "osacompile", "pbcopy", "sfltool", "screencapture"):
        check("PROFILE: %s does not run" % exe, '/%s")' % exe in text)
    for svc in ("com.apple.coreservices.launchservicesd", "com\\.apple\\.lsd\\.", "com.apple.coreservices.appleevents",
                "com.apple.siriactionsd.xpc", "com\\.apple\\.backgroundtaskmanagement", "com.apple.cfprefsd.daemon"):
        check("PROFILE: mach-lookup of %s is denied" % svc, svc in text)
    params = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-D")
    check("PROFILE: the clone, home and temp are the run's", params.get("CLONE") == os.path.realpath(d + "/clone")
          and params.get("RHOME") == os.path.realpath(d + "/home"), params)
    check("PROFILE: lsregister and qlmanage by their real paths",
          params.get("LSREGISTER") == sandbox.LSREGISTER and params.get("QLMANAGE") == sandbox.QLMANAGE
          and (not IS_MAC or (os.path.realpath("/usr/bin/qlmanage") == sandbox.QLMANAGE
                              and os.path.realpath(sandbox.LSREGISTER) == sandbox.LSREGISTER)), params)
    check("step: the step runs in the clone with the run's home", cwd == os.path.realpath(d + "/clone")
          == sandbox.step_cwd(run) and env["HOME"] == os.path.realpath(d + "/home")
          and env["TMPDIR"] == os.path.realpath(d + "/tmp"))
    check("STEP_ENV: a clean environment", set(env) == {"PATH", "HOME", "LANG", "TMPDIR"} | {k for k, _ in sandbox.STEP_ENV},
          sorted(env))
    check("step: the shell runs last", argv[-3:] == ["zsh", "-c", "echo hi"])
    shutil.rmtree(d)


# ------------------------------------------------------------------ macOS: the manifest path
def test_mac_manifest():
    if not IS_MAC:
        skip("macOS manifest", "cp -c (APFS clonefile) is macOS's")
        return
    root = project({"edit.txt": "one\n", "gone.txt": "bye\n", "run.sh": "echo\n", "tree/x/y.txt": "y\n",
                    "keep.txt": "k\n"})
    run = sandbox.new_run(root, "t", platform="macos")
    clone = os.path.join(run["dir"], "clone")
    check("clone: a copy of the project", read(os.path.join(clone, "edit.txt")) == "one\n")
    check("clone: the manifest is 0600", mode_of(os.path.join(run["dir"], "manifest.json")) == 0o600)
    check("clone: no change yet", sandbox.changes(run) == [])
    with open(os.path.join(clone, "edit.txt"), "a") as f:
        f.write("two\n")
    put(clone, "new.txt", "new\n")
    os.remove(os.path.join(clone, "gone.txt"))
    os.chmod(os.path.join(clone, "run.sh"), 0o755)
    shutil.rmtree(os.path.join(clone, "tree"))
    os.symlink("/etc", os.path.join(clone, "link_out"))
    os.mkfifo(os.path.join(clone, "pipe"))
    put(clone, ".git/hooks/pre-commit", "#!/bin/sh\n")
    os.utime(os.path.join(clone, "keep.txt"))     # touched, same bytes: no change
    e = by_path(sandbox.changes(run))
    check("manifest: changed / added / deleted / mode",
          [e.get(p, {}).get("status") for p in ("edit.txt", "new.txt", "gone.txt", "run.sh")]
          == ["changed", "added", "deleted", "mode"], {p: x["status"] for p, x in e.items()})
    check("manifest: a deleted tree is one entry", e.get("tree", {}).get("status") == "deleted"
          and "tree/x" not in e and "tree/x/y.txt" not in e, sorted(e))
    check("manifest: touched but the same is no change", "keep.txt" not in e)
    check("manifest: a link out and a fifo are refused",
          e.get("link_out", {}).get("status") == "refused" and e.get("pipe", {}).get("status") == "refused")
    check("manifest: a hook is held back", e.get(".git/hooks", {}).get("status") == "held"
          and e.get(".git/hooks/pre-commit", {}).get("status") == "held", sorted(e))
    n, problems = sandbox.apply(run)
    check("manifest: apply lands every change", read(os.path.join(root, "edit.txt")) == "one\ntwo\n"
          and read(os.path.join(root, "new.txt")) == "new\n" and not os.path.exists(os.path.join(root, "gone.txt"))
          and mode_of(os.path.join(root, "run.sh")) == 0o755 and not os.path.exists(os.path.join(root, "tree")),
          (n, problems))
    check("manifest: held and refused stay out", not os.path.exists(os.path.join(root, ".git", "hooks"))
          and not os.path.lexists(os.path.join(root, "link_out")) and not os.path.lexists(os.path.join(root, "pipe")))
    check("manifest: the run's whole dir is gone after the apply", gone(run))
    # a conflict on the manifest path
    run = sandbox.new_run(root, "t", platform="macos")
    put(os.path.join(run["dir"], "clone"), "edit.txt", "from the run\n")
    later = run["start"] + 10 ** 9
    os.utime(os.path.join(root, "edit.txt"), ns=(later, later))
    refused("CONFLICT: on the manifest path too", lambda: sandbox.apply(run), "since the run began")
    sandbox.discard(run)
    # the entry cap, the persona.blast pattern
    was = sandbox.SANDBOX_MAX_ENTRIES
    sandbox.SANDBOX_MAX_ENTRIES = 3
    try:
        refused("SANDBOX_MAX_ENTRIES: a larger project is refused before the copy",
                lambda: sandbox.new_run(root, "t", platform="macos"), "at most 3 files")
    finally:
        sandbox.SANDBOX_MAX_ENTRIES = was
    check("SANDBOX_MAX_ENTRIES: a refused run leaves nothing", sandbox.runs() == [])


# ------------------------------------------------------------------ the check row
def test_check_row():
    from spark import check as checkmod
    ctx = checkmod.Ctx()
    r = checkmod.row_sandbox(ctx)
    check("row: sandbox is ok or na, never warn or fail", r.status in (checkmod.OK, checkmod.NA), (r.status, r.value))
    spec = [s for s in checkmod.SPECS if s.name == "sandbox"]
    check("row: CAPABILITY, fixture=False with a reason",
          spec and spec[0].category == "CAPABILITY" and not spec[0].fixture and spec[0].reason)
    print("     sandbox row: %s %s" % (r.status, r.value))


# ------------------------------------------------------------------ REAL
def step(run, cmd, timeout=60):
    argv, cwd, env = sandbox.step(run, "/bin/sh", cmd)
    p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, preexec_fn=sandbox.preexec, start_new_session=True,
                       timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace")


PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"
# python3 and cc under /usr/bin are the command line tools' shims on a Mac:
# without the tools installed they offer an install instead of running
HAVE_CLT = not IS_MAC or os.path.isdir("/Library/Developer/CommandLineTools") or \
    subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True).returncode == 0


def test_real():
    good, detail = sandbox.probe(fresh=True)
    print("     probe: %s %s" % ("ok" if good else "na", detail))
    cached = sandbox.probe()
    check("probe: the cache answers the same", cached == (good, detail), cached)
    if not good:
        skip("REAL section", "this machine cannot run the sandbox: %s" % detail)
        return
    clear_runs()
    root = project({"keep.txt": "k\n", "gone.txt": "bye\n", "run.sh": "echo\n", ".git/HEAD": "ref\n",
                    ".git/hooks/.keep": ""})
    run = sandbox.new_run(root, "t")
    rc, out = step(run, "echo new > added.txt && rm gone.txt && printf 'more\\n' >> keep.txt"
                        " && chmod +x run.sh && printf '#!/bin/sh\\necho owned\\n' > .git/hooks/pre-commit"
                        " && cat keep.txt")
    check("real: a step runs in the copy", rc == 0 and "more" in out, out)
    check("real: the project is untouched until the apply", read(os.path.join(root, "keep.txt")) == "k\n"
          and not os.path.exists(os.path.join(root, "added.txt")) and os.path.exists(os.path.join(root, "gone.txt")))
    reviewed = sandbox.changes(run)
    e = by_path(reviewed)
    check("real: the review sees every change",
          [e.get(p, {}).get("status") for p in ("added.txt", "gone.txt", "keep.txt", "run.sh", ".git/hooks/pre-commit")]
          == ["added", "deleted", "changed", "mode", "held"], {p: x["status"] for p, x in e.items()})
    check("real: the size helper sees the writes", 0 < sandbox.used_bytes(run) < sandbox.SANDBOX_MAX_BYTES
          and not sandbox.over_cap(run))
    n, problems = sandbox.apply(run, reviewed)
    check("real: apply applies what was reviewed", read(os.path.join(root, "keep.txt")) == "k\nmore\n"
          and read(os.path.join(root, "added.txt")) == "new\n" and not os.path.exists(os.path.join(root, "gone.txt"))
          and mode_of(os.path.join(root, "run.sh")) & 0o100 and gone(run), (n, problems))
    check("real: the planted hook never reaches the project",
          not os.path.exists(os.path.join(root, ".git/hooks/pre-commit")), problems)

    # a background writer the step left behind: the review is not what apply would copy
    if IS_MAC:
        run = sandbox.new_run(root, "t")
        rc, out = step(run, "echo a > a.txt; (sleep 1; echo x >> a.txt) >/dev/null 2>&1 &")
        reviewed = sandbox.changes(run)
        time.sleep(2.5)
        refused("CHANGED (real): a background writer after the review makes apply refuse",
                lambda: sandbox.apply(run, reviewed), sandbox.CHANGED)
        check("CHANGED (real): nothing applied, the run still there",
              not os.path.exists(os.path.join(root, "a.txt")) and os.path.isdir(run["dir"]))
        sandbox.discard(run)
    else:
        skip("CHANGED (real): a background writer", "bwrap's pid namespace ends every process with the step")

    # the escapes: every one fails
    secret = put(HOME, ".ssh/id_test", "SECRET-IN-HOME\n")
    run = sandbox.new_run(root, "t")
    rc, out = step(run, "cat %s" % secret)
    check("escape: a file planted in HOME is unreadable", rc != 0 and "SECRET-IN-HOME" not in out, out)
    if os.path.exists("/etc/spark/token"):
        try:
            token = read("/etc/spark/token").strip()     # this user may be in the spark group
        except OSError:
            token = ""
        rc, out = step(run, "cat /etc/spark/token")
        check("escape: /etc/spark/token is unreadable", rc != 0 and (not token or token not in out),
              "rc %d" % rc)
    else:
        skip("escape: /etc/spark/token", "no /etc/spark/token here")
    net = ("import socket, time\ns = socket.socket()\ns.settimeout(5)\nt = time.time()\n"
           "try:\n    s.connect(('192.0.2.1', 9)); print('CONNECTED')\n"
           "except socket.timeout:\n    print('TIMEOUT')\n"
           "except OSError as e:\n    print('REFUSED', e.errno, round(time.time() - t, 1))\n")
    if HAVE_CLT:
        rc, out = step(run, "%s -c \"$(printf '%%s' %s)\"" % (PY, _sh_quote(net)))
        check("escape: the network is down (refused at once, not a timeout)", "REFUSED" in out
              and float(out.split()[-1]) < 2, out)
    t0 = time.time()
    rc, out = step(run, "curl -sS -m 5 http://192.0.2.1:9/ 2>&1; echo rc=$?")
    check("escape: curl fails at once (no network)", "rc=0" not in out and time.time() - t0 < 4, out)
    sock_path = os.path.join(HOME, "s.sock")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(sock_path)
    srv.listen(1)
    try:
        unix = ("import socket\ns = socket.socket(socket.AF_UNIX)\n"
                "try:\n    s.connect(%r); print('CONNECTED')\n"
                "except OSError as e:\n    print('REFUSED', e.errno)\n" % sock_path)
        if HAVE_CLT:
            rc, out = step(run, "%s -c \"$(printf '%%s' %s)\"" % (PY, _sh_quote(unix)))
            check("escape: a unix socket outside is unreachable", "REFUSED" in out, out)
    finally:
        srv.close()
    bus = "/run/user/%d/bus" % os.getuid()
    if os.path.exists(bus):
        rc, out = step(run, "test -e %s && echo SEEN || echo HIDDEN" % bus)
        check("escape: the session bus is hidden", "HIDDEN" in out, out)
    else:
        skip("escape: the session bus", "no %s here" % bus)
    rc, out = step(run, "touch /etc/spark-sandbox-test")
    check("escape: /etc is not writable", rc != 0 and not os.path.exists("/etc/spark-sandbox-test"), out)
    outside = os.path.join(HOME, "outside.txt")
    rc, out = step(run, "echo x > %s" % outside)     # Linux: lands in the step's own tmpfs HOME, gone after
    check("escape: nothing is written outside the copy", not os.path.exists(outside), out)
    rc, out = step(run, "sudo -n true")
    check("escape: sudo does not elevate", rc != 0, out)
    rc, out = step(run, "echo \"[$SPARK_TEST_EXPORTED]\"")
    check("escape: an exported variable does not cross", rc == 0 and "[]" in out, out)
    check("escape: nothing the escapes tried is a change", sandbox.changes(run) == [], sandbox.changes(run))
    if IS_MAC:
        mac_denies(run)
        mac_tools(run)
    sandbox.discard(run)


MACH = """
import ctypes, sys
libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
bp = ctypes.c_uint.in_dll(libc, "bootstrap_port")
for name in sys.argv[1:]:
    port = ctypes.c_uint(0)
    print(name, libc.bootstrap_look_up(bp, name.encode(), ctypes.byref(port)))
"""


def mac_denies(run):
    """PROFILE's extended lines, for real: the reads, the delegating tools
    and the services behind them."""
    for path in ("/private/var/folders", "/private/tmp", "/private/var/tmp", "/Library/Keychains",
                 "/opt/homebrew/etc"):
        if os.path.isdir(path):
            rc, out = step(run, "ls %s" % path)
            check("mac: reads under %s are denied" % path, rc != 0 and "not permitted" in out, out)
    tools = [("shortcuts list", "shortcuts"), ("automator /dev/null", "automator"),
             ("defaults write spark.sandbox-test k v", "defaults write"), ("open .", "open"),
             ("osascript -e 1", "osascript"), ("osacompile -e 1 -o x.scpt", "osacompile"),
             ("echo x | pbcopy", "pbcopy"), ("sfltool list", "sfltool"), ("screencapture -x s.png", "screencapture"),
             ("'%s' -dump" % sandbox.LSREGISTER, "lsregister"), ("qlmanage -m", "qlmanage (a link to its real path)"),
             ("lsappinfo list", "lsappinfo"), ("crontab -l", "crontab")]
    for cmd, name in tools:
        rc, out = step(run, cmd)
        check("mac: %s does not run" % name, rc != 0 and "not permitted" in out, out)
    rc, out = step(run, "defaults read spark.sandbox-test k")
    check("mac: nothing was written to the preferences", "k v" not in out and rc != 0, out)
    if not HAVE_CLT:
        skip("mac: the mach-lookup denies", "no command line tools: no python3 to ask with")
        return
    services = ("com.apple.coreservices.launchservicesd", "com.apple.lsd.open", "com.apple.lsd.modifydb",
                "com.apple.coreservices.appleevents", "com.apple.siriactionsd.xpc",
                "com.apple.backgroundtaskmanagement.registrar", "com.apple.cfprefsd.daemon",
                "com.apple.cfprefsd.agent", "com.apple.pasteboard.1", "com.apple.coreservices.sharedfilelistd.xpc",
                "com.apple.tccd")
    rc, out = step(run, "%s -c \"$(printf '%%s' %s)\" %s" % (PY, _sh_quote(MACH), " ".join(services)))
    got = dict(line.split() for line in out.splitlines() if line.startswith("com.apple."))
    for svc in services:
        check("mac: mach-lookup of %s is denied" % svc, got.get(svc) not in (None, "0"), out)


def mac_tools(run):
    """The ordinary tools still work inside, with every deny in place."""
    for cmd, want in (("sh -c 'echo sh-ok'", "sh-ok"), ("ls", "keep.txt"), ("cat keep.txt", "k"),
                      ("grep -c k keep.txt", "1"), ("sed -n 1p keep.txt", "k"), ("awk 'NR==1' keep.txt", "k"),
                      ("find . -name keep.txt", "./keep.txt"), ("tar cf t.tar keep.txt && tar tf t.tar", "keep.txt")):
        rc, out = step(run, cmd)
        check("mac: %s works inside" % cmd.split()[0], rc == 0 and want in out, out)
    if shutil.which("git") and (HAVE_CLT or not shutil.which("git").startswith("/usr/bin/")):
        rc, out = step(run, "mkdir g && cd g && echo g > g.txt && git init -q . && git add -A && git -c user.name=t -c user.email=you@example.com "
                            "commit -qm first && git status --short && git log --oneline | wc -l")
        check("mac: git init, add, commit, status and log work inside", rc == 0 and out.strip().endswith("1"), out)
    else:
        skip("mac: git inside", "no git here")
    if HAVE_CLT:
        for cmd, want in (("%s -c 'print(6*7)'" % PY, "42"), ("make -v", "GNU Make"), ("cc --version", "clang")):
            rc, out = step(run, cmd)
            check("mac: %s works inside" % cmd.split()[0].rsplit("/", 1)[-1], rc == 0 and want in out, out)
    else:
        skip("mac: python3, make, cc inside", "no command line tools here")


def _sh_quote(s):
    from shlex import quote
    return quote(s)


def main():
    for t in (test_upper_walk, test_visible, test_whiteout_and_opaque, test_overlay_marks, test_review_max,
              test_apply, test_reviewed, test_lock_refused, test_conflict_refused, test_git, test_gitfile_bypass,
              test_git_shapes, test_symlink_redirect, test_discard_mode000, test_run_lock, test_cap_lock,
              test_detach_lock, test_records, test_ids, test_home_and_root, test_waiting_cap,
              test_step_linux_shape, test_step_mac_shape, test_mac_manifest, test_check_row, test_real):
        try:
            t()
        except Exception as e:
            global FAILED
            FAILED += 1
            import traceback
            traceback.print_exc()
            print("FAIL %s crashed: %s" % (t.__name__, e))
        clear_runs()
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
        for root, dirs, _f in os.walk(HOME):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o700)
                except OSError:
                    pass
        shutil.rmtree(HOME, ignore_errors=True)
