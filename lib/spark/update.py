# spark.update -- `spark update`: move this checkout to the newest tag (a
# release clone) or pull main (a developer clone on a branch), then
# converge -- bootstrap.sh applies whatever changed and check re-reads.
# The converge runs in a fresh exec of the NEW tree: this process was
# imported from the old one, and mixing the two ends in ImportError.
#
# A release is a signed tag: before a release clone moves, the tag's ssh
# signature is verified against the tree's own `allowed-signers` (one
# line per key, principal `spark-release`), and a tag nobody known
# signed is refused with nothing moved. Whoever can push a tag does not
# thereby run code on every install; whoever holds a key in that file does.
# The signature covers the tag object, not the ref that names it: an old
# signed release pushed again as `v99.0` verifies. So the name inside the
# object must be the ref's name, the tag must be at or ahead of HEAD
# (forward only), and the walk takes the newest tag that passes all
# three, saying which newer ones it passed over and why -- a bad tag is
# skipped, never a freeze.

import fcntl
import os
import re
import shutil
import subprocess
import sys

from . import MARK, REPO, STATE_DIR, run, say, state_dir
from .text import pulse as _pulse   # the fetch, the pull, the move

UPDATE_LOCK = os.path.join(STATE_DIR, "update.lock")
SIGNERS = "allowed-signers"     # at the repo root: `spark-release namespaces="git" <keytype> <base64>`

USAGE = """%s update -- get the newest spark and set it up

  spark update             the newest signed release, or main on a branch
  spark update --dry-run   say what it would do; nothing changes
""" % MARK


def _git(args, timeout=15):
    return run(["git", "-C", REPO] + list(args), timeout=timeout)


NOT_SIGNED = "not signed by a known key"
BEHIND = "behind this checkout"


def _named(tag, repo=None):
    """"" when `tag` is an annotated tag whose object says `tag <tag>`,
    else one short reason. A lightweight tag carries no signature; an
    object named otherwise is another release under a new name."""
    repo = repo or REPO
    ref = "refs/tags/" + tag
    rc, kind = run(["git", "-C", repo, "cat-file", "-t", ref], timeout=15)
    if rc != 0 or kind.strip() != "tag":
        return NOT_SIGNED
    rc, body = run(["git", "-C", repo, "cat-file", "tag", ref], timeout=15)
    name = ""
    for line in body.splitlines():
        if not line:
            break               # the headers end at the first blank line
        if line.startswith("tag "):
            name = line[4:]
            break
    if rc == 0 and name == tag:
        return ""
    return "named %s inside" % (re.sub(r"[^A-Za-z0-9._+-]", "?", name)[:40] or "nothing")


def verified(tag, repo=None):
    """(principal, why): who signed `tag` per the tree's allowed-signers
    ("spark-release", ""), or ("", one short reason) when nobody known
    did or the object inside names another tag (_named). `git
    verify-tag` reads the ssh signature itself (git >= 2.34) and hands
    it to ssh-keygen; its verdict comes back on stderr, so this is the
    one git call here that does not go through run()."""
    repo = repo or REPO
    if not shutil.which("ssh-keygen"):
        return "", "unverifiable: no ssh-keygen here (openssh)"
    why = _named(tag, repo)
    if why:
        return "", why
    cmd = ["git", "-C", repo, "-c", "gpg.ssh.allowedSignersFile=" + os.path.join(repo, SIGNERS),
           "verify-tag", tag]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "", "unverifiable: git verify-tag did not run"
    m = re.search(r'^Good "git" signature for (\S+) with ', p.stdout, re.M)
    if p.returncode == 0 and m:
        return m.group(1), ""
    _, v = run(["git", "--version"])
    m = re.search(r"(\d+)\.(\d+)", v)
    if m and (int(m.group(1)), int(m.group(2))) < (2, 34):
        return "", "unverifiable by git %s.%s: an ssh signature needs git >= 2.34" % m.groups()
    return "", NOT_SIGNED


def here(repo=None):
    """The release tag HEAD sits on: the newest v* tag at HEAD whose
    object names it, else what `git describe --exact-match` says (a
    lightweight tag, put there by hand), else ""."""
    repo = repo or REPO
    rc, out = run(["git", "-C", repo, "tag", "--points-at", "HEAD", "-l", "v[0-9]*",
                   "--sort=-v:refname"], timeout=15)
    for t in out.split() if rc == 0 else []:
        if not _named(t, repo):
            return t
    rc, out = run(["git", "-C", repo, "describe", "--tags", "--exact-match"], timeout=15)
    return out.strip() if rc == 0 else ""


def pick(tags, repo=None, forward=True):
    """(tag, principal, skipped): the first of `tags` (newest first) that
    is a release to land on -- named as its object says, at or ahead of
    HEAD when `forward` (an update; a fresh clone has nothing to be
    ahead of), signed by a known key -- and [(tag, why)] for each one
    passed over on the way. ("", "", skipped) when none passes. An
    unverifiable signature (no ssh-keygen, an old git) ends the walk:
    no other tag would fare better."""
    repo = repo or REPO
    skipped = []
    for t in tags:
        why = _named(t, repo)
        if not why and forward:
            rc, _ = run(["git", "-C", repo, "merge-base", "--is-ancestor", "HEAD", t], timeout=15)
            why = "" if rc == 0 else BEHIND
        who = ""
        if not why:
            who, why = verified(t, repo)
        if who:
            return t, who, skipped
        skipped.append((t, why))
        if why.startswith("unverifiable"):
            break
    return "", "", skipped


def skipped_line(skipped):
    """The tags a walk passed over, each with its reason, three at most."""
    shown = ", ".join("%s (%s)" % tw for tw in skipped[:3])
    more = len(skipped) - 3
    return shown + (" and %d more" % more if more > 0 else "")


def _door():
    """The suggestion to awaken, once ever (setup.door marks it offered)."""
    try:
        from . import setup
        setup.door(once=True)
    except Exception:       # noqa: BLE001 -- a suggestion is never a reason to fail
        pass


def _voice_pins(cfg):
    """The voice follows its pins: with it on or clear, a part whose pin
    changed (its sha file differs) is fetched again, the old one removed
    (voice._fetch_said: the size said first). A failure is said, never
    the update's."""
    try:
        from . import voice
        if voice.mode(cfg) != "off" and voice.missing() and not os.environ.get("SPARK_NO_APPLY"):
            voice._fetch_said(cfg)
    except Exception:       # noqa: BLE001 -- the voice never fails an update
        pass


def _converge():
    """bootstrap.sh over the tree. At a terminal it owns the screen (a
    sudo prompt, curl's bar), so no pulse draws over it; captured, it is
    silent, and the pulse shows the wait."""
    from . import site
    if sys.stdout.isatty():
        return site.apply((), stream=True)
    with _pulse():
        return site.apply((), stream=True)


def _restart_units(cfg):
    """Restart every loaded unit on the tree at hand: the engine, the page,
    and on runit spark-check too (runit has no timer: that loop holds the
    old tree and its environment until runsv restarts it)."""
    from . import engine
    units = ["serve", "forge"] + (["check"] if engine.init_shape() == "runit" else [])
    for unit in units:
        if engine.service_state(cfg, unit) == "loaded" and engine.kickstart(cfg, unit, restart=True):
            say("* the %s restarted" % {"serve": "engine", "forge": "page"}.get(unit, unit))


def _page_is_stale():
    """True when the page's server here answers /api/health with a version
    other than this tree's; False when it matches, or nothing answers."""
    from . import forge_url, version, wire
    url = forge_url()
    h = wire.forge_health(url) if url else None
    return isinstance(h, dict) and bool(h.get("version")) and h.get("version") != version.version()


def _lock():
    """Take the update lock, or None when another update holds it. The
    lock covers the half that cannot be run twice -- the fetch and the
    move -- and is dropped before the converge exec: two bootstraps at
    once are idempotent, two checkouts of the same tree are not."""
    state_dir()
    fd = os.open(UPDATE_LOCK, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def cmd_update(args):
    dry = False
    for a in args:
        if a in ("-h", "--help"):
            say(USAGE.rstrip())
            return 0
        if a == "--dry-run":
            dry = True
            continue
        if a == "--converge":
            # internal: the post-move half, running in the new tree
            from . import config
            rc = _converge()
            if rc == 0:
                # the tree moved under the running units: without a
                # restart the API keeps serving the OLD code with every
                # row green
                cfg = config.load()
                _restart_units(cfg)
                _voice_pins(cfg)
                # the look file follows the new tree (an awakened machine only)
                try:
                    from . import look
                    look.fresh(cfg)
                except Exception:       # noqa: BLE001 -- derived state, rebuilt at the next look
                    pass
                _door()
            return rc
        say("%s update -- no word %s; spark update -h lists them" % (MARK, a))
        return 2
    moved = False

    lock = None if dry else _lock()
    if not dry and lock is None:
        say("%s update -- another spark update is running" % MARK)
        return 2

    rc, out = _git(["status", "--porcelain"])
    if rc != 0:
        say("%s update -- not a git checkout: %s" % (MARK, REPO))
        return 1
    if out.strip():
        say("%s update -- the clone is dirty: commit or stash first (git -C %s status)" % (MARK, REPO))
        return 1

    with _pulse():
        rc, _ = _git(["fetch", "-q", "--tags", "origin"], timeout=30)
    if rc != 0:
        say("%s update -- could not reach origin (git fetch failed)" % MARK)
        return 1
    # a fetched tag can land on the sha already cached: drop the version
    # cache so `spark ver` says the release, not <old>+N (the box said
    # 1.2+29 at the very commit v1.3 pointed to)
    try:
        from . import STATE_DIR
        os.unlink(os.path.join(STATE_DIR, "version"))
    except OSError:
        pass

    rc, _ = _git(["symbolic-ref", "-q", "HEAD"])
    if rc == 0:
        rc, _ = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
        if rc != 0:
            say("%s update -- no upstream: git -C %s branch --set-upstream-to=origin/<branch>" % (MARK, REPO))
            return 1
        _, branch = _git(["symbolic-ref", "--short", "HEAD"])
        branch = branch.strip()
        rc, out = _git(["rev-list", "--count", "HEAD..@{upstream}"])
        n = int(out.strip()) if rc == 0 and out.strip() else 0
        if n == 0:
            say("%s update -- up to date" % MARK)
        elif dry:
            say("%s update -- would pull %s: %d new commit%s" % (MARK, branch, n, "" if n == 1 else "s"))
        else:
            with _pulse():
                rc, _ = _git(["pull", "-q", "--ff-only"])
            if rc != 0:
                say("%s update -- git pull failed: git -C %s status" % (MARK, REPO))
                return 1
            say("%s update -- %s: %d new commit%s" % (MARK, branch, n, "" if n == 1 else "s"))
            moved = True
    else:
        cur = here()
        rc, tags = _git(["tag", "-l", "v[0-9]*", "--sort=-v:refname"])
        tags = tags.split() if rc == 0 else []
        if not tags:
            say("%s update -- no release found: git -C %s checkout main" % (MARK, REPO))
            return 1
        # the name, the direction and the signature, --dry-run or not: a
        # tag that fails one moves nothing and the walk goes on to the
        # next newest, so a bad tag is skipped, never a freeze; a dry run
        # says the same
        newest, who, skipped = pick(tags)
        if skipped and skipped[-1][1].startswith("unverifiable"):
            say("%s update -- %s is %s: refused" % ((MARK,) + skipped[-1]))
            return 1
        if skipped:
            say("! skipped %s" % skipped_line(skipped))
        if not newest:
            say("%s update -- no signed release ahead of this checkout: it stays at %s"
                % (MARK, cur or "an untagged commit"))
            return 1
        _, at = _git(["rev-parse", "HEAD"])
        _, there = _git(["rev-parse", newest + "^{commit}"])
        if at.strip() == there.strip():
            say("%s update -- already at %s" % (MARK, newest))
        else:
            if dry:
                say("%s update -- would move to %s (signed by %s; was %s)"
                    % (MARK, newest, who, cur or "an untagged commit"))
            else:
                with _pulse():
                    rc, _ = _git(["checkout", "-q", "--detach", newest])
                if rc != 0:
                    say("%s update -- could not move to %s (git checkout failed)" % (MARK, newest))
                    return 1
                say("%s update -- %s (signed by %s; was %s)" % (MARK, newest, who, cur or "an untagged commit"))
                moved = True

    if dry:
        return 0
    # the move is done: the converge is idempotent, and holding a lock
    # across an exec only leaks it into bootstrap's own children
    os.close(lock)
    if moved:
        os.execv(sys.executable, [sys.executable, os.path.join(REPO, "bin", "spark"),
                                  "update", "--converge"])
    rc = _converge()
    if rc == 0:
        # nothing moved, yet the units may run an older tree (a pull by
        # hand, an update whose restart failed): the page says which
        # version it runs, and a stale one is restarted like a move
        from . import config, engine
        _voice_pins(config.load())
        if _page_is_stale():
            cfg = config.load()
            _restart_units(cfg)
            if engine.service_state(cfg, "forge") != "loaded":
                # a page started by hand is nobody's to restart here
                say("%s update -- the page runs an older spark, started by hand: "
                    "spark serve off; spark serve on" % MARK)

        _door()
    return rc
