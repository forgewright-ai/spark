# spark.packages -- the package family this machine belongs to and the
# questions its package manager is asked: what is installed, what is
# pending, how a human installs or removes a list. The names are data
# (distro/<id>.env, one file per family; Brewfile on macOS); the verbs are
# here, switched once on the manager -- bootstrap.sh's pkg_* functions are
# the sh twin. Nothing here installs anything: bootstrap does that.

import os
import re

from . import IS_MAC, REPO, config, distro, run

KEYS = ("PM", "PM_INSTALL", "PM_TARGET", "PKG_CORE", "PKG_ENGINE", "PKG_AI", "PKG_SHELL", "PKG_CLI")
GROUPS = ("PKG_CORE", "PKG_ENGINE", "PKG_AI", "PKG_SHELL", "PKG_CLI")
NEVER_REMOVED = ("bash",)          # the login shell, whatever the family


def table(repo=REPO):
    """The distro file's KEY=value dict ({} on macOS or an unknown Linux)."""
    d = distro()
    return config.parse_env(os.path.join(repo, "distro", d + ".env")) if d else {}


def groups(repo=REPO):
    """{group: [names]} for the five groups (empty lists when no file)."""
    t = table(repo)
    return {g: t.get(g, "").split() for g in GROUPS}


def manager():
    """brew on macOS, else the family's PM ('' on an unknown Linux)."""
    return "brew" if IS_MAC else table().get("PM", "")


def installed(pkgs):
    """The set of pkgs the manager reports installed; None when it cannot
    be asked (no manager, or the tool is not found)."""
    pm = manager()
    if pm == "apt":
        rc, out = run(["dpkg-query", "-W", "-f", "${Package} ${Status}\n"] + list(pkgs), timeout=30)
        if rc == -1:
            return None
        return {l.split()[0] for l in out.splitlines() if l.endswith("install ok installed")}
    return None


def pending():
    """How many updates the manager holds back, or -1 when it cannot say."""
    pm = manager()
    if pm == "brew":
        rc, out = run(["brew", "outdated", "--quiet"], timeout=120)
        return -1 if rc != 0 else len(out.split())
    if pm == "apt":
        rc, out = run(["apt", "list", "--upgradable"], timeout=60)
        return -1 if rc != 0 else len([l for l in out.splitlines() if "/" in l])
    return -1


def upgrade_line():
    """The one line a human runs to take the pending updates."""
    return {"brew": "brew upgrade", "apt": "sudo apt upgrade"}.get(manager(), "")


def install_line(pkgs):
    """The line a human runs to install pkgs here (every remedy says it)."""
    if IS_MAC:
        return "brew install " + " ".join(pkgs)
    t = table()
    return ("%s %s" % (t.get("PM_INSTALL", "install"), " ".join(pkgs))).strip()


def remove_argv(pkgs):
    """The manager's own removal, as root on Linux (dependencies stay, as
    apt-get remove leaves them)."""
    if IS_MAC:
        return ["brew", "uninstall"] + list(pkgs)
    return {"apt": ["apt-get", "remove", "-y"]}.get(manager(), []) + list(pkgs)


def remove_line(pkgs):
    argv = remove_argv(pkgs)
    return ("" if IS_MAC else "sudo ") + " ".join(argv)


def essential(pkg):
    """A package the manager refuses to remove (apt: dpkg's Essential flag;
    ncurses-bin is one): it never appears in a removal list."""
    if manager() == "apt":
        rc, out = run(["dpkg-query", "-W", "-f=${Essential}", pkg], timeout=10)
        return rc == 0 and out.strip() == "yes"
    return False


def removable(repo=REPO):
    """What spark uninstall names: the Brewfile's entries on macOS; on Linux
    every group but PKG_CORE (the AI's four prerequisites stay), minus the
    login shell and anything the manager calls essential."""
    if IS_MAC:
        try:
            with open(os.path.join(repo, "Brewfile"), encoding="utf-8") as f:
                return re.findall(r'^(?:brew|cask) "([^"]+)"', f.read(), re.M)
        except OSError:
            return []
    out = []
    for g in ("PKG_ENGINE", "PKG_AI", "PKG_SHELL", "PKG_CLI"):
        out += [p for p in groups(repo)[g] if p not in NEVER_REMOVED and not essential(p)]
    return out
