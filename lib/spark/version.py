# spark.version -- the version, straight from git: no constant to keep in
# sync with the tag. "1.0" exactly at a tag, "1.0+3" three commits past it,
# "0+<sha7>" with no tag reachable (a shallow clone), "dev" with no git at
# all. Cached in STATE_DIR/version, keyed to the sha HEAD resolves to (two
# file reads, no subprocess), so an unchanged HEAD never runs `git describe`
# again -- version() is called only by `spark ver`, `spark check` and
# `spark forge`; nothing on the `spark line` path touches it.

import json
import os
import re

from . import REPO, STATE_DIR, run, state_dir


def _git_dir():
    """REPO's .git: a directory in a plain checkout, or the file a linked
    worktree leaves behind (`gitdir: <path>`) -- read either way."""
    p = os.path.join(REPO, ".git")
    if os.path.isdir(p):
        return p
    try:
        with open(p, encoding="utf-8") as f:
            line = f.read().strip()
    except OSError:
        return p
    if line.startswith("gitdir:"):
        gd = line[len("gitdir:"):].strip()
        return gd if os.path.isabs(gd) else os.path.normpath(os.path.join(REPO, gd))
    return p


def _common_dir(git_dir):
    """The shared repo dir (refs, packed-refs): git_dir itself, or the one a
    worktree's private gitdir points back to via `commondir`."""
    try:
        with open(os.path.join(git_dir, "commondir"), encoding="utf-8") as f:
            cd = f.read().strip()
    except OSError:
        return git_dir
    return cd if os.path.isabs(cd) else os.path.normpath(os.path.join(git_dir, cd))


def _head_sha():
    """The sha HEAD resolves to: read .git/HEAD; a ref (the normal case)
    names a file under refs/ or, once git has packed it, a line in
    packed-refs. "" when this is not a git checkout at all (a tarball)."""
    git_dir = _git_dir()
    try:
        with open(os.path.join(git_dir, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
    except OSError:
        return ""
    if not head.startswith("ref:"):
        return head          # detached: HEAD holds the sha directly
    ref = head[4:].strip()
    common = _common_dir(git_dir)
    for base in (git_dir, common):
        try:
            with open(os.path.join(base, ref), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    try:
        with open(os.path.join(common, "packed-refs"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.endswith(" " + ref):
                    return line.split()[0]
    except OSError:
        pass
    return ""


def _describe(sha):
    """One `git describe`, and the only git subprocess version() ever runs
    (2 s timeout, never blocks). It stays one call because tags here are
    annotated: peeling a tag object down to the commit it names, and
    counting commits back to the nearest reachable one, is exactly what
    `git describe` already does; walking that by hand without git is not
    simple, so one bounded subprocess buys it instead."""
    rc, out = run(["git", "-C", REPO, "describe", "--tags", "--abbrev=7"], timeout=2)
    if rc == -1:
        return "dev"
    out = out.strip()
    if rc != 0 or not out:
        return "0+" + sha[:7]
    if out.startswith("v"):
        out = out[1:]
    m = re.match(r"^(\d+\.\d+)-(\d+)-g[0-9a-f]+$", out)
    if m:
        return "%s+%s" % (m.group(1), m.group(2))
    if re.match(r"^\d+\.\d+$", out):
        return out
    return "0+" + sha[:7]


def version():
    """The version string, cached by sha so an unchanged checkout never pays
    for `git describe` twice. Never raises: any failure yields the best
    fallback for what could be read."""
    sha = _head_sha()
    if not sha:
        return "dev"          # no checkout, or a branch with no commit yet
    path = os.path.join(STATE_DIR, "version")
    try:
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("sha") == sha and cached.get("v"):
            return cached["v"]
    except (OSError, ValueError, KeyError):
        pass
    v = _describe(sha)
    try:
        state_dir()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"sha": sha, "v": v}, f)
    except OSError:
        pass
    return v
