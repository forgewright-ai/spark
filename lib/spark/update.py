# spark.update -- `spark update`: move this checkout to the newest tag (a
# release clone) or pull main (a developer clone on a branch), then
# converge -- bootstrap.sh applies whatever changed and check re-reads.

from . import MARK, REPO, run, say

USAGE = """%s update -- move this checkout to the newest tag or main, then converge

  spark update             pull main (a branch), or move to the newest tag
                            (a detached checkout); then applies and rechecks
  spark update --dry-run   say what would happen, change nothing
""" % MARK


def _git(args, timeout=15):
    return run(["git", "-C", REPO] + list(args), timeout=timeout)


def cmd_update(args):
    dry = False
    for a in args:
        if a in ("-h", "--help"):
            say(USAGE.rstrip())
            return 0
        if a == "--dry-run":
            dry = True
            continue
        say("spark update: no option %s -- spark update -h" % a)
        return 2

    rc, out = _git(["status", "--porcelain"])
    if rc != 0:
        say("spark update: not a git repository: %s" % REPO)
        return 1
    if out.strip():
        say("spark update: the tree is dirty -- commit or stash first (git -C %s status)" % REPO)
        return 1

    rc, _ = _git(["fetch", "-q", "--tags", "origin"], timeout=30)
    if rc != 0:
        say("spark update: git fetch --tags origin failed")
        return 1

    rc, _ = _git(["symbolic-ref", "-q", "HEAD"])
    if rc == 0:
        rc, _ = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
        if rc != 0:
            say("spark update: no upstream set -- git -C %s branch --set-upstream-to=origin/<branch>" % REPO)
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
            rc, _ = _git(["pull", "-q", "--ff-only"])
            if rc != 0:
                say("spark update: git pull --ff-only failed -- git -C %s status says why" % REPO)
                return 1
            say("%s update -- %s: %d new commit%s" % (MARK, branch, n, "" if n == 1 else "s"))
    else:
        rc, cur = _git(["describe", "--tags", "--exact-match"])
        cur = cur.strip() if rc == 0 else ""
        rc, tags = _git(["tag", "-l", "v[0-9]*", "--sort=-v:refname"])
        newest = tags.split()[0] if rc == 0 and tags.split() else ""
        if not newest:
            say("spark update: no v* tag found -- git -C %s checkout main" % REPO)
            return 1
        if cur == newest:
            say("%s update -- already at %s" % (MARK, cur))
        elif dry:
            say("%s update -- would move to %s (was %s)" % (MARK, newest, cur or "an untagged commit"))
        else:
            rc, _ = _git(["checkout", "-q", "--detach", newest])
            if rc != 0:
                say("spark update: git checkout --detach %s failed" % newest)
                return 1
            say("%s update -- %s (was %s)" % (MARK, newest, cur or "an untagged commit"))

    if dry:
        return 0
    from . import site
    return site.apply((), stream=True)
