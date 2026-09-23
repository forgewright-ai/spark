#!/usr/bin/env python3
"""spark do --sandbox's core (lib/spark/sandbox.py), in a throwaway HOME.

First the review and the apply on fabricated trees, so every named line
is proven without a sandbox: the Linux upper walk (added, changed, mode,
link, binary; a whiteout and an opaque dir where the kernel lets a user
make them), every named refusal of the apply (a git lock, a conflict,
git's hooks and config held back, setuid masked, a link out refused, a
fifo refused, a link in the project cannot carry a write outside it),
the records (meta.json's fields and modes, the id's shape), the ~ and /
refusal, the waiting cap, and the argv a step runs under (Linux-shaped
even on a Mac). Then, only when probe() says this machine can, a REAL
section: steps run contained, the review sees them, apply applies them,
and every escape fails -- a file planted in HOME, /etc/spark/token, the
network, a write to /etc, a unix socket, sudo, an exported variable.
Exit 0 with a skip line where a primitive is absent.
"""
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

# a throwaway HOME before spark is imported: its paths are read at import
HOME = os.path.realpath(tempfile.mkdtemp(prefix="spark-sandbox-test-"))
for _k in list(os.environ):
    if _k.startswith(("SPARK_", "XDG_", "SITE_")):
        del os.environ[_k]
os.environ.update({"HOME": HOME, "XDG_CONFIG_HOME": HOME + "/.config", "XDG_STATE_HOME": HOME + "/.local/state",
                   "XDG_DATA_HOME": HOME + "/.local/share", "SPARK_NO_REFRESH": "1", "SPARK_YES": "1",
                   "SPARK_TEST_EXPORTED": "exported-value-never-inside"})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from spark import IS_MAC, sandbox  # noqa: E402

IS_LINUX = sys.platform.startswith("linux")
FAILED = 0
SKIPPED = []


def check(name, cond, detail=""):
    global FAILED
    if cond:
        print("ok   %s" % name)
    else:
        FAILED += 1
        print("FAIL %s%s" % (name, ("\n  " + str(detail)) if detail else ""))


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
        f.write(data.encode() if isinstance(data, str) else data)
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
    (fabricated -- no bwrap needed)."""
    root = project(files)
    if before:
        before(root)
    run = sandbox.new_run(root, "thread-0", platform="linux")
    up = os.path.join(run["dir"], "up")
    for rel, v in upper.items():
        put(up, rel, v)
    return root, run, up


def clear_runs():
    for r in sandbox.runs():
        sandbox.discard(r)


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
    for s in {x["status"] for x in e.values()}:
        check("walk: status %s is one of STATUSES" % s, s in sandbox.STATUSES)
    text = sandbox.diff_text(list(e.values()))
    check("diff: the unified diff shows the new line", "+two" in text and "--- a/edit.txt" in text, text)
    check("diff: +x is marked", "(+x)" in text)
    check("diff: refused links are listed with the reason", "refused    link_out -- " + sandbox.LINK_OUT in text)
    check("diff: a new file diffs from /dev/null", "--- /dev/null" in text)
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


# ------------------------------------------------------------------ the apply
def test_apply():
    lower = {"edit.txt": "one\n", "mode.sh": "echo\n", "dir/inner.txt": "in\n"}
    upper = {"edit.txt": "one\ntwo\n", "new.txt": "new\n", "mode.sh": ("echo\n", 0o755),
             "sub/new/deep.txt": "deep\n", "su.sh": ("#!/bin/sh\n", 0o6755), "bin.dat": b"\x00\xff"}
    root, run, up = linux_run(lower, upper)
    os.symlink("edit.txt", os.path.join(up, "link_in"))
    os.symlink("/etc", os.path.join(up, "link_out"))
    os.mkfifo(os.path.join(up, "pipe"))
    n, problems = sandbox.apply(run)
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
    check("apply: the run is applied, its data gone",
          sandbox.load(run["id"])["state"] == "applied" and not os.path.exists(up))
    refused("apply: an applied run cannot apply twice", lambda: sandbox.apply(sandbox.load(run["id"])), "already")


def test_lock_refused():
    root, run, up = linux_run({"a.txt": "a\n", ".git/HEAD": "ref\n"},
                              {"b.txt": "b\n", ".git/index.lock": "x"})
    e = refused("LOCK: a git lock in the change set refuses the whole apply", lambda: sandbox.apply(run),
                "mid-command")
    check("LOCK: nothing applied", not os.path.exists(os.path.join(root, "b.txt")))
    check("LOCK: the lock is named", e is not None and e.paths == [".git/index.lock"], e and e.paths)
    check("LOCK: the run still waits", sandbox.load(run["id"])["state"] == "waiting")
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
    os.utime(os.path.join(root, "b.txt"), ns=(later, later))     # untouched by the run: no conflict
    os.utime(os.path.join(root, "a.txt"), ns=(run["start"] - 10 ** 9,) * 2)
    n, problems = sandbox.apply(run)
    check("CONFLICT: a newer file the run did not touch is no conflict",
          read(os.path.join(root, "a.txt")) == "a from the run\n", problems)


def test_git_held():
    root, run, up = linux_run({".git/HEAD": "ref: refs/heads/main\n", ".git/config": "[core]\n",
                               "sub/.git/config": "[core]\n"},
                              {".git/HEAD": "ref: refs/heads/other\n", ".git/objects/ab/cd": b"\x78\x01",
                               ".git/hooks/pre-commit": ("#!/bin/sh\necho owned\n", 0o755),
                               ".git/config": "[core]\n\thooksPath = /tmp\n",
                               ".git/modules/lib/hooks/post-checkout": "#!/bin/sh\n",
                               ".git/modules/lib/config": "[core]\n",
                               ".git/worktrees/w/config.worktree": "[core]\n",
                               "sub/.git/config": "[core]\n\tpager = sh\n"})
    entries = sandbox.changes(run)
    e = by_path(entries)
    held = sorted(p for p, x in e.items() if x["status"] == "held")
    check("HELD: .git/hooks/** is held back", ".git/hooks" in held or ".git/hooks/pre-commit" in held, held)
    check("HELD: .git/config is held back", ".git/config" in held, held)
    check("HELD: a submodule's hooks and config are held back",
          any(p.startswith(".git/modules/lib/hooks") for p in held) and ".git/modules/lib/config" in held, held)
    check("HELD: a worktree's config is held back", ".git/worktrees/w/config.worktree" in held, held)
    check("HELD: a nested repo's config is held back", "sub/.git/config" in held, held)
    g = e.get(".git", {})
    items = [i["path"] for i in g.get("items", [])]
    check("git: its own files are one summary with a count",
          g.get("status") == "changed" and g.get("count") == len(items) and ".git/HEAD" in items
          and ".git/objects/ab/cd" in items and ".git/HEAD" not in e, g)
    check("git: nothing held rides inside the summary",
          not [i for i in g.get("items", []) if i["status"] in ("held", "refused")])
    text = sandbox.diff_text(entries)
    check("diff: held back is listed with the reason", "held back  .git/config -- " in text, text)
    n, problems = sandbox.apply(run)
    check("HELD: the hook is never applied", not os.path.exists(os.path.join(root, ".git/hooks")))
    check("HELD: the config is never applied", read(os.path.join(root, ".git/config")) == "[core]\n"
          and read(os.path.join(root, "sub/.git/config")) == "[core]\n")
    check("git: the rest of .git applies", read(os.path.join(root, ".git/HEAD")) == "ref: refs/heads/other\n"
          and os.path.isfile(os.path.join(root, ".git/objects/ab/cd")) and n == len(items), (n, problems))
    check("HELD: the held are reported", any(p.startswith("held back .git/config") for p in problems), problems)


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
          not went and not os.path.exists(os.path.join(outside, "evil.txt")))
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
    check("discard: a mode-000 work dir goes", not os.path.exists(os.path.join(run["dir"], "wk"))
          and not os.path.exists(up))
    check("discard: the run is discarded, not waiting",
          sandbox.load(run["id"])["state"] == "discarded" and run["id"] not in [r["id"] for r in sandbox.runs()])


# ------------------------------------------------------------------ the records
def mode_of(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_records():
    clear_runs()
    root = project({"a.txt": "a\n"})
    run = sandbox.new_run(root, "thread-7", platform="linux")
    meta_path = os.path.join(run["dir"], "meta.json")
    import json
    with open(meta_path) as f:
        meta = json.load(f)
    check("META_FIELDS: meta.json holds only numbers and names",
          sorted(meta) == sorted(sandbox.META_FIELDS), sorted(meta))
    check("META_FIELDS: no goal words", "goal" not in read(meta_path) and meta["thread"] == "thread-7"
          and isinstance(meta["start"], int) and meta["state"] == "waiting" and meta["cwd"] == root)
    check("records: meta.json is 0600", mode_of(meta_path) == 0o600, oct(mode_of(meta_path)))
    for p in (sandbox.RUNS_DIR, run["dir"], os.path.join(run["dir"], "up"), os.path.join(run["dir"], "wk")):
        check("records: %s is 0700" % os.path.relpath(p, HOME), mode_of(p) == 0o700, oct(mode_of(p)))
    check("records: runs() lists the waiting run", [r["id"] for r in sandbox.runs()] == [run["id"]])
    sandbox.discard(run)


def test_ids():
    check("ID_SHAPE: a new id has the shape", bool(sandbox.ID_SHAPE.match("20260922-101500-a1b2c3")))
    for bad in ("../../etc", "", None, "20260922-101500-a1b2cg", "20260922-101500-a1b2c3/..", "x" * 200):
        refused("ID_SHAPE: load(%r) is refused before the filesystem" % (bad if not bad or len(bad) < 30 else "x*200"),
                lambda b=bad: sandbox.load(b), "not a sandboxed run's id")
    refused("load: a well-shaped id that does not exist", lambda: sandbox.load("20000101-000000-000000"),
            "no sandboxed run")


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
    refused("SANDBOX_MAX_WAITING: a sixth waiting run is refused",
            lambda: sandbox.new_run(root, "t", platform="linux"), "spark do --review")
    for r in made:
        sandbox.discard(r)


# ------------------------------------------------------------------ the argv
def test_step_linux_shape():
    root = project({"a.txt": "a\n"})
    run = sandbox.new_run(root, "t", platform="linux")
    argv, cwd, env = sandbox.step(run, "sh", "echo hi", platform="linux")
    check("step: argv is the linux argv", argv == sandbox.step_argv(run, "sh", "echo hi", platform="linux"))
    check("step: the root is read-only first", argv[1:4] == ["--ro-bind", "/", "/"], argv[:4])
    tmpfs = [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]
    check("HIDDEN: HOME is under an empty tmpfs", HOME in tmpfs or any(HOME.startswith(t + "/") for t in tmpfs),
          tmpfs)
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
    params = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-D")
    check("PROFILE: the clone, home and temp are the run's", params.get("CLONE") == os.path.realpath(d + "/clone")
          and params.get("RHOME") == os.path.realpath(d + "/home"), params)
    check("step: the step runs in the clone with the run's home", cwd == os.path.realpath(d + "/clone")
          and env["HOME"] == os.path.realpath(d + "/home") and env["TMPDIR"] == os.path.realpath(d + "/tmp"))
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
    check("manifest: a hook is held back", e.get(".git/hooks", {}).get("status") == "held", sorted(e))
    n, problems = sandbox.apply(run)
    check("manifest: apply lands every change", read(os.path.join(root, "edit.txt")) == "one\ntwo\n"
          and read(os.path.join(root, "new.txt")) == "new\n" and not os.path.exists(os.path.join(root, "gone.txt"))
          and mode_of(os.path.join(root, "run.sh")) == 0o755 and not os.path.exists(os.path.join(root, "tree")),
          (n, problems))
    check("manifest: held and refused stay out", not os.path.exists(os.path.join(root, ".git", "hooks"))
          and not os.path.lexists(os.path.join(root, "link_out")) and not os.path.lexists(os.path.join(root, "pipe")))
    check("manifest: the clone is gone after the apply", not os.path.exists(clone))
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
def step(run, cmd, timeout=30):
    argv, cwd, env = sandbox.step(run, "/bin/sh", cmd)
    p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, preexec_fn=sandbox.preexec, start_new_session=True,
                       timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace")


PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"


def test_real():
    good, detail = sandbox.probe(fresh=True)
    print("     probe: %s %s" % ("ok" if good else "na", detail))
    cached = sandbox.probe()
    check("probe: the cache answers the same", cached == (good, detail), cached)
    if not good:
        skip("REAL section", "this machine cannot run the sandbox: %s" % detail)
        return
    root = project({"keep.txt": "k\n", "gone.txt": "bye\n", "run.sh": "echo\n", ".git/HEAD": "ref\n",
                    ".git/hooks/.keep": ""})
    run = sandbox.new_run(root, "t")
    rc, out = step(run, "echo new > added.txt && rm gone.txt && printf 'more\\n' >> keep.txt"
                        " && chmod +x run.sh && printf '#!/bin/sh\\necho owned\\n' > .git/hooks/pre-commit"
                        " && cat keep.txt")
    check("real: a step runs in the copy", rc == 0 and "more" in out, out)
    check("real: the project is untouched until the apply", read(os.path.join(root, "keep.txt")) == "k\n"
          and not os.path.exists(os.path.join(root, "added.txt")) and os.path.exists(os.path.join(root, "gone.txt")))
    e = by_path(sandbox.changes(run))
    check("real: the review sees every change",
          [e.get(p, {}).get("status") for p in ("added.txt", "gone.txt", "keep.txt", "run.sh", ".git/hooks/pre-commit")]
          == ["added", "deleted", "changed", "mode", "held"], {p: x["status"] for p, x in e.items()})
    check("real: the size helper sees the writes", 0 < sandbox.used_bytes(run) < sandbox.SANDBOX_MAX_BYTES
          and not sandbox.over_cap(run))
    n, problems = sandbox.apply(run)
    check("real: apply applies", read(os.path.join(root, "keep.txt")) == "k\nmore\n"
          and read(os.path.join(root, "added.txt")) == "new\n" and not os.path.exists(os.path.join(root, "gone.txt"))
          and mode_of(os.path.join(root, "run.sh")) & 0o100, (n, problems))
    check("real: the planted hook never reaches the project",
          not os.path.exists(os.path.join(root, ".git/hooks/pre-commit")), problems)

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
    net = ("import socket\ns = socket.socket()\ns.settimeout(5)\n"
           "try:\n    s.connect(('192.0.2.1', 9)); print('CONNECTED')\n"
           "except socket.timeout:\n    print('TIMEOUT')\n"
           "except OSError as e:\n    print('REFUSED', e.errno)\n")
    rc, out = step(run, "%s -c \"$(printf '%%s' %s)\"" % (PY, _sh_quote(net)))
    check("escape: the network is down (refused at once, not a timeout)", "REFUSED" in out, out)
    sock_path = os.path.join(HOME, "s.sock")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(sock_path)
    srv.listen(1)
    try:
        unix = ("import socket\ns = socket.socket(socket.AF_UNIX)\n"
                "try:\n    s.connect(%r); print('CONNECTED')\n"
                "except OSError as e:\n    print('REFUSED', e.errno)\n" % sock_path)
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
    sandbox.discard(run)


def _sh_quote(s):
    from shlex import quote
    return quote(s)


def main():
    for t in (test_upper_walk, test_whiteout_and_opaque, test_apply, test_lock_refused, test_conflict_refused,
              test_git_held, test_symlink_redirect, test_discard_mode000, test_records, test_ids,
              test_home_and_root, test_waiting_cap, test_step_linux_shape, test_step_mac_shape,
              test_mac_manifest, test_check_row, test_real):
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
