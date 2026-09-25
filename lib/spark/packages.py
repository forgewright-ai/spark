# spark.packages -- the package family this machine belongs to and the
# questions its package manager is asked: what is installed, what is
# pending, how a human installs or removes a list. The names are data
# (distro/<id>.env, one file per family; Brewfile on macOS); the verbs are
# here, switched once on the manager -- bootstrap.sh's pkg_* functions are
# the sh twin. Nothing here installs anything: bootstrap does that.

import os
import re

from . import IS_MAC, REPO, config, distro, run

KEYS = ("PM", "PM_INSTALL", "PM_TARGET", "PKG_CORE", "PKG_ENGINE", "PKG_AI")
GROUPS = ("PKG_CORE", "PKG_ENGINE", "PKG_AI")
NEVER_REMOVED = ("bash",)          # the login shell, whatever the family


def table(repo=REPO):
    """The distro file's KEY=value dict ({} on macOS or an unknown Linux)."""
    d = distro()
    return config.parse_env(os.path.join(repo, "distro", d + ".env")) if d else {}


def groups(repo=REPO):
    """{group: [names]} for the three groups (empty lists when no file)."""
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
    if pm == "pacman":
        # stdout is the answer: -Qq prints the installed ones and exits 1
        # when any name is missing
        rc, out = run(["pacman", "-Qq"] + list(pkgs), timeout=30)
        if rc == -1:
            return None
        return set(out.split())
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
    if pm == "pacman":
        # checkupdates (pacman-contrib) counts against a private copy of the
        # database: safe on a rolling distro (2 = nothing pending); without
        # it, -Qu counts against the last refresh
        rc, out = run(["checkupdates"], timeout=120)
        if rc == 2:
            return 0
        if rc == 0:
            return len(out.splitlines())
        rc, out = run(["pacman", "-Qu"], timeout=60)
        return -1 if rc == -1 else len(out.splitlines())
    return -1


def upgrade_line():
    """The one line a human runs to take the pending updates."""
    return {"brew": "brew upgrade", "apt": "sudo apt upgrade", "pacman": "sudo pacman -Syu"}.get(manager(), "")


# the pending row's words for an Arch box with no arch-audit: the
# security upgrades are there, unnamed, and one package names them
SECURITY_UNNAMED = "security upgrades unnamed (pacman -S arch-audit)"


def parse_apt_security(out):
    """How many lines of an `apt list --upgradable` transcript come from a
    security source: `name/suite version arch [upgradable from: ...]`,
    the suite one or more comma-joined names, a security one ending in
    -security (bookworm-security, noble-security). Pure, so a pasted
    transcript proves it; the `Listing...` header has no slash."""
    n = 0
    for line in out.splitlines():
        name, slash, rest = line.partition("/")
        if not slash or not name.strip() or " " in name.strip():
            continue
        suites = rest.split()[0] if rest.split() else ""
        if any(s.endswith("-security") for s in suites.split(",")):
            n += 1
    return n


def parse_arch_audit(out):
    """The package names `arch-audit -q` prints, one per line, nothing
    else (a clean box prints nothing). Pure; sorted, each once."""
    return sorted(set(l.strip() for l in out.splitlines()
                      if l.strip() and " " not in l.strip() and not l.startswith(("error", "warning"))))


def security():
    """How many of the pending updates are security upgrades. apt: the
    upgradable lines from a -security source. pacman: what arch-audit
    names; None when arch-audit is not installed (the row then says
    SECURITY_UNNAMED, no warning). -1 when the manager was asked and
    could not answer. brew and an unknown Linux: None -- nothing there
    names a security upgrade, and the row leaves the question alone."""
    pm = manager()
    if pm == "apt":
        rc, out = run(["apt", "list", "--upgradable"], timeout=60)
        return -1 if rc != 0 else parse_apt_security(out)
    if pm == "pacman":
        rc, out = run(["arch-audit", "-q"], timeout=120)
        if rc == -1:
            return None
        return -1 if rc != 0 else len(parse_arch_audit(out))
    return None


def install_line(pkgs):
    """The line a human runs to install pkgs here (every remedy says it)."""
    if IS_MAC:
        return "brew install " + " ".join(pkgs)
    t = table()
    return ("%s %s" % (t.get("PM_INSTALL", "install"), " ".join(pkgs))).strip()


# the binary a shell tries to run, to the package that provides it: the
# tools an exit-127 hint may name, where the package name differs from
# the command or a family renames it (Debian ships fd as fd-find, bat as
# batcat). Anything not here is left to the model to name -- this map
# only spares a model call for tools spark already knows.
_TOOL_PKG = {
    "fd": {"apt": "fd-find", "pacman": "fd", "brew": "fd"},
    "fdfind": {"apt": "fd-find", "pacman": "fd", "brew": "fd"},
    "rg": {"apt": "ripgrep", "pacman": "ripgrep", "brew": "ripgrep"},
    "bat": {"apt": "bat", "pacman": "bat", "brew": "bat"},
    "batcat": {"apt": "bat", "pacman": "bat", "brew": "bat"},
    "eza": {"apt": "eza", "pacman": "eza", "brew": "eza"},
    "fzf": {"apt": "fzf", "pacman": "fzf", "brew": "fzf"},
    "zoxide": {"apt": "zoxide", "pacman": "zoxide", "brew": "zoxide"},
    "btop": {"apt": "btop", "pacman": "btop", "brew": "btop"},
    "jq": {"apt": "jq", "pacman": "jq", "brew": "jq"},
    "tmux": {"apt": "tmux", "pacman": "tmux", "brew": "tmux"},
    "starship": {"apt": "starship", "pacman": "starship", "brew": "starship"},
}


def package_for(binary):
    """The package that provides `binary` on this machine, when spark knows
    it (`_TOOL_PKG`), else '' -- the caller then asks the model. The family
    is this machine's: fd is fd-find on Debian, fd on Arch and macOS."""
    row = _TOOL_PKG.get(binary)
    if not row:
        return ""
    pm = "brew" if IS_MAC else manager()
    return row.get(pm, binary)


def remove_argv(pkgs):
    """The manager's own removal, as root on Linux (dependencies stay, as
    apt-get remove leaves them)."""
    if IS_MAC:
        return ["brew", "uninstall"] + list(pkgs)
    return {"apt": ["apt-get", "remove", "-y"], "pacman": ["pacman", "-R", "--noconfirm"]}.get(manager(), []) + list(pkgs)


def remove_line(pkgs):
    argv = remove_argv(pkgs)
    return ("" if IS_MAC else "sudo ") + " ".join(argv)


def parse_apt_removal(out):
    """The package names an `apt-get -s remove` transcript says would go:
    the `Remv <name> [version]` lines. Pure, so a fixture can prove it."""
    return sorted(set(re.findall(r"(?m)^Remv (\S+)", out)))


def parse_pacman_removal(out):
    """The names `pacman -Rp --print-format %n` prints, one per line."""
    return sorted(set(l.strip() for l in out.splitlines()
                      if l.strip() and not l.startswith(("error", "warning", ":"))))


def remove_would(pkgs):
    """What the manager would REALLY remove for `pkgs`: apt takes the
    reverse dependencies with it (libvulkan1 -> libgl1-mesa-dri -> ... ->
    a desktop), so the caller must see the whole list before any removal.
    A simulation, no root; None when the manager cannot say."""
    pm = manager()
    if pm == "apt":
        rc, out = run(["apt-get", "-s", "remove"] + list(pkgs), timeout=180)
        return parse_apt_removal(out) if rc == 0 else None
    if pm == "pacman":
        rc, out = run(["pacman", "-Rp", "--print-format", "%n"] + list(pkgs), timeout=180)
        return parse_pacman_removal(out) if rc == 0 else None
    return None


def essential(pkg):
    """A package the manager refuses to remove (apt: dpkg's Essential flag,
    ncurses-bin is one; pacman: one another package requires): it never
    appears in a removal list."""
    pm = manager()
    if pm == "apt":
        rc, out = run(["dpkg-query", "-W", "-f=${Essential}", pkg], timeout=10)
        return rc == 0 and out.strip() == "yes"
    if pm == "pacman":
        # pacman refuses -R on a package another one requires (gcc-libs,
        # ncurses, bash): Required By says so
        rc, out = run(["pacman", "-Qi", pkg], timeout=10)
        m = re.search(r"^Required By\s*:\s*(.*)$", out, re.M)
        return rc == 0 and bool(m) and m.group(1).strip() != "None"
    return False


def removable(repo=REPO):
    """What spark uninstall names: nothing on macOS (the mac core installs
    no package); on Linux the engine and AI groups, minus anything the
    manager calls essential (the four PKG_CORE prerequisites stay)."""
    if IS_MAC:
        return []
    out = []
    for g in ("PKG_ENGINE", "PKG_AI"):
        out += [p for p in groups(repo)[g] if p not in NEVER_REMOVED and not essential(p)]
    return out
