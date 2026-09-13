# spark.uninstall -- `spark uninstall`: take spark off this machine.
#
# Everything spark made goes: the units, the look, the console palette, the
# rc line, the engine and the models, the state, the links, the clone.
# What is yours stays -- the soul, the memory, the sealed users' stores
# (and the account keys that open them), your models.env, your themes,
# privacy-terms -- unless --purge. The packages spark installed are a
# question. The plan prints first (bootstrap's row shape), then the typed
# word `yes` (spark do's danger shape); --dry-run shows only.
#
# Order matters (the traps): the one bootstrap pass -- headless and quiet
# undone through their own rows first, so bootstrap
# does not skip them -- runs BEFORE anything is removed; nothing calls
# bootstrap or check.refresh after that (each would put things back).
# Root steps try sudo and become a `todo` row naming the command when it
# refuses; the clone goes last, only when it is the default clone and
# clean.

import glob
import os
import shutil
import subprocess
import sys

from . import (BIN_DIR, CONFIG_DIR, DATA_DIR, FORGE_PID, FORGE_URL_FILE, HOME, IS_MAC, MARK, REPO, STATE_DIR,
               config, distro, is_wsl, run, say)
from . import packages as pkg

USAGE = """%s uninstall -- remove spark from this machine: shows first, then asks for the word yes

  spark uninstall              the plan (every row), then: remove all of it? type yes
  spark uninstall --dry-run    the plan only, nothing changes
  spark uninstall --yes        no question (SPARK_YES=1 too); a script's form
  --purge                      your soul, memory, sealed users, models.env,
                               themes and privacy-terms go too (kept otherwise)
  --packages | --keep-packages the installed packages: answer up front
                               (asked at a terminal; kept when nobody answers)

  What stays, always: what spark could not record before it changed it --
  the hostname it set, macOS's pmset, a console font set before v1.12 --
  each named with the line that puts it back. The clone goes only when it
  is the one `get` made (~/.spark, or SPARK_HOME) and clean.
""" % MARK

KEEP_CONFIG = ("soul", "memory", "models.env", "themes", "privacy-terms")
KEEP_STATE = ("users", "account", "account-key")
SPARK_CONFIG = ("site.env", "spark.env", "theme.env", "console-colors", "console-colors.rgb", "check.log")
UNITS_LINUX = ("spark-serve.service", "spark-forge.service", "spark-check.timer", "spark-check.service")
CONSOLE_UNIT = "/etc/systemd/system/spark-console.service"
CONSOLE_SETUP = "/etc/default/console-setup"
CONSOLE_ORIG = CONSOLE_SETUP + ".spark-orig"
RC_CANDIDATES = (".bashrc", ".zshrc", ".bash_profile", ".zprofile")


class Ctx(object):
    def __init__(self, dry, purge, packages):
        self.dry, self.purge, self.packages = dry, purge, packages
        self.cfg = config.load()
        self.todo = []          # (what, the manual line)
        self.kept = []          # paths that stayed on purpose
        self.freed = 0          # bytes the data dir held

    def row(self, status, what, detail=""):
        if self.dry and status == "ok":
            status = "would"
        say("%-6s %-12s %s" % (status, what, detail))
        if status == "todo":
            self.todo.append((what, detail))

    def root(self, what, cmd, done, manual=None, timeout=120):
        """Run cmd as root (sudo): a `would` row when dry, `ok` when it ran,
        `todo` with the manual line when sudo refused or is absent."""
        manual = manual or "sudo " + " ".join(cmd)
        if self.dry:
            self.row("would", what, done + " (sudo)")
            return False
        if shutil.which("sudo"):
            argv = ["sudo"] + ([] if sys.stdin.isatty() else ["-n"]) + cmd
            try:
                rc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout).returncode
            except (OSError, subprocess.TimeoutExpired):
                rc = 1
            if rc == 0:
                self.row("ok", what, done)
                return True
        self.row("todo", what, manual)
        return False

    def remove(self, what, path, detail=None):
        """Remove a file, a link or a tree the user's way (no root)."""
        detail = detail or _tilde(path)
        if not os.path.lexists(path):
            return False
        if self.dry:
            self.row("would", what, detail)
            return True
        if os.path.islink(path) or not os.path.isdir(path):
            os.remove(path)
        else:
            shutil.rmtree(path, ignore_errors=True)
        self.row("ok", what, detail)
        return True


def _tilde(path):
    for home in (HOME, os.path.realpath(HOME)):
        if path.startswith(home + "/"):
            return "~" + path[len(home):]
    return path


def _spark_link(path):
    from . import site
    return site._spark_link(path)


def _restore_or_remove(ctx, what, path):
    """A rendered file of ours: back from its .bak, or removed (never a husk)."""
    bak = path + ".bak"
    if ctx.dry:
        ctx.row("would", what, "%s: %s" % (_tilde(path), "back from .bak" if os.path.lexists(bak) else "removed"))
        return
    os.remove(path)
    if os.path.lexists(bak):
        os.rename(bak, path)
        ctx.row("ok", what, "%s restored from its .bak" % _tilde(path))
    else:
        ctx.row("ok", what, "%s removed (no .bak: there was no file before)" % _tilde(path))


def _rmdir_empty(path):
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


# ---------------------------------------------------------------- the steps
def step_bootstrap_undo(ctx):
    """The one bootstrap pass: headless and quiet undone through their
    own rows, keys flipped first. Before anything is removed."""
    from . import site
    keys = {}
    if ctx.cfg.headless:
        keys["SITE_HEADLESS"] = "no"
    if ctx.cfg.quiet_login:
        keys["SITE_QUIET_LOGIN"] = "no"
    if ctx.cfg.quiet_boot:
        keys["SITE_QUIET_BOOT"] = "no"
    if not keys:
        ctx.row("skip", "undo", "headless and quiet were never on")
        return
    if ctx.dry:
        ctx.row("would", "undo", "set %s to no and run bootstrap once (sudo for sleep, lid, motd, GRUB)"
                % ", ".join(sorted(keys)))
        return
    site.set_keys(_quiet=True, **keys)
    os.environ["SPARK_HEADLESS_UNDO"] = "1"
    rc = site.apply(["quiet-login", "quiet-boot", "sleep", "lid", "daemons", r"spark\.(serve|forge|check)"], stream=True)
    if rc == 0:
        ctx.row("ok", "undo", "headless and quiet off through bootstrap")
        return
    # The undo is the one root step that runs bootstrap rather than a
    # command of its own -- it is bootstrap that knows how to unmask sleep,
    # drop the lid file, put the motd and GRUB back. So the remedy has to
    # be "run ./bootstrap.sh", and the clone has to still be there to run:
    # step_clone reads this.
    ctx.undo_pending = True
    ctx.row("todo", "undo", "bootstrap.sh could not finish (sudo): sleep, lid, motd and GRUB "
                            "are still spark's -- ./bootstrap.sh in the clone undoes them")


def step_services(ctx):
    """Stop the FORGE and the server, disable every unit and timer, drop the
    unit files. Nothing of spark's runs after this."""
    from . import engine        # never forgeserve: its import writes the version cache
    cfg = ctx.cfg
    if cfg.client:
        ctx.row("skip", "services", "a client: no units here")
    elif IS_MAC:
        for unit in ("forge", "serve", "check"):
            name = engine.unit_name(unit)
            if engine.service_domain(cfg, unit) == "system":
                ctx.root(unit, ["launchctl", "bootout", "system/" + name], "LaunchDaemon %s booted out" % name)
                ctx.root(unit, ["rm", "-f", "/Library/LaunchDaemons/%s.plist" % name], "/Library/LaunchDaemons/%s.plist removed" % name)
            target = "gui/%d/%s" % (os.getuid(), name)
            plist = os.path.join(HOME, "Library", "LaunchAgents", name + ".plist")
            if not ctx.dry:
                run(["launchctl", "bootout", target], timeout=20)
            if os.path.exists(plist):
                ctx.remove(unit, plist, "%s booted out, %s removed" % (name, _tilde(plist)))
            elif not ctx.dry:
                ctx.row("ok", unit, "%s not loaded" % name)
    else:
        for name in UNITS_LINUX:
            if not ctx.dry:
                run(["systemctl", "--user", "disable", "--now", name], timeout=30)
            link = os.path.join(HOME, ".config", "systemd", "user", name)
            if _spark_link(link) or os.path.lexists(link):
                ctx.remove("units", link, "%s disabled, %s removed" % (name, _tilde(link)))
        if not ctx.dry:
            run(["systemctl", "--user", "daemon-reload"], timeout=30)
            run(["systemctl", "--user", "reset-failed"], timeout=30)
    # whatever still runs under a pidfile or the port, ours
    if not ctx.dry and not cfg.client:
        try:
            with open(FORGE_PID, encoding="utf-8") as f:
                pid = int(f.read().strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid:
            engine.terminate([pid])
            left = engine.wait_gone([pid], 10)
            if left:
                engine.terminate(left, force=True)
        pids = engine.server_pids(cfg.port)
        if pids:
            engine.terminate(pids)
            left = engine.wait_gone(pids, 15)
            if left:
                engine.terminate(left, force=True)
        for p in (FORGE_URL_FILE, FORGE_PID):
            try:
                os.remove(p)
            except OSError:
                pass
        engine.forget()
        ctx.row("ok", "processes", "the FORGE and the server are down")
    launchd = os.path.join(CONFIG_DIR, "launchd")
    ctx.remove("launchd", launchd)


def step_look(ctx):
    """What older sparks left in the way: rc symlinks a pre-cut shell
    layer made (the shell-moved bootstrap row's twin, kept one release),
    and the old plugin links. The rendered look is spark-shell's now."""
    from . import site
    if ctx.dry:
        for name in site.RC_FILES:
            path = os.path.join(HOME, name)
            if _spark_link(path):
                ctx.row("would", "rc", "%s: spark's link goes, %s" % (_tilde(path), "back from .bak" if os.path.lexists(path + ".bak") else "removed"))
    else:
        for path, what in site.restore_rc():
            ctx.row("ok", "rc", "%s -- %s" % (_tilde(path), what))
    # a pre-cut render of ours (".gitconfig, rendered by spark") goes back
    # to its .bak too -- kept one release, like the rc half above
    gitconfig = os.path.join(HOME, ".gitconfig")
    try:
        with open(gitconfig, encoding="utf-8", errors="replace") as f:
            ours = "rendered by spark" in f.read()
    except OSError:
        ours = False
    if ours and not os.path.islink(gitconfig):
        _restore_or_remove(ctx, "look", gitconfig)
    # a pre-v1.10 install's plugin links (the micro bootstrap row's twin)
    plug = os.path.join(HOME, ".config", "micro", "plug", "spark")
    if _spark_link(os.path.join(plug, "spark.lua")):
        if ctx.dry:
            ctx.row("would", "micro", "spark's old plugin links removed, bindings.json back")
        else:
            for f in ("spark.lua", "repo.json", os.path.join("help", "spark.md")):
                p = os.path.join(plug, f)
                if os.path.islink(p):
                    os.remove(p)
            _rmdir_empty(os.path.join(plug, "help"))
            _rmdir_empty(plug)
            b = os.path.join(HOME, ".config", "micro", "bindings.json")
            if os.path.islink(b):
                os.remove(b)
                if os.path.isfile(b + ".bak"):
                    os.rename(b + ".bak", b)
            ctx.row("ok", "micro", "spark's old plugin links removed")


def strip_rc_line(path):
    """Remove the marked spark line (and the blank line bootstrap put before
    it) from a regular rc file; True when a line went."""
    from . import site
    if os.path.islink(path) or not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    keep = []
    for line in lines:
        if site.RC_MARKER in line:
            if keep and keep[-1] == "":
                keep.pop()
            continue
        keep.append(line)
    if keep == lines:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(keep))
    return True


def step_rc_lines(ctx):
    from . import site
    for name in RC_CANDIDATES:
        path = os.path.join(HOME, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                has = site.RC_MARKER in f.read()
        except OSError:
            continue
        if not has:
            continue
        if ctx.dry:
            ctx.row("would", "rc", "%s: the spark line removed" % _tilde(path))
        elif strip_rc_line(path):
            ctx.row("ok", "rc", "%s: the spark line removed" % _tilde(path))


def step_console(ctx):
    """Linux: the VT palette back to VGA (this console, the kernel's
    defaults, the boot unit gone), the console font back when the original
    was kept, the motd/issue originals cleaned."""
    if IS_MAC or is_wsl():
        return
    from . import theme
    cc = os.path.join(CONFIG_DIR, "console-colors")
    painted = os.path.exists(cc) or os.path.exists(CONSOLE_UNIT)
    if painted:
        if not ctx.dry and os.environ.get("TERM") == "linux" and sys.stdout.isatty():
            sys.stdout.write(theme.vt_escapes(theme.VGA) + "\033[2J\033[H")
            sys.stdout.flush()
        if shutil.which("setvtrgb"):
            ctx.root("palette", ["setvtrgb", "vga"], "the kernel's default palette is VGA again")
    if os.path.exists(CONSOLE_UNIT):
        ctx.root("palette", ["systemctl", "disable", "--now", "spark-console.service"], "spark-console.service disabled")
        ctx.root("palette", ["rm", "-f", CONSOLE_UNIT], "%s removed" % CONSOLE_UNIT)
        ctx.root("palette", ["systemctl", "daemon-reload"], "systemd reloaded")
    if os.path.exists(CONSOLE_ORIG):
        ctx.root("console", ["sh", "-c", "cp %s %s && rm -f %s && (setupcon --force 2>/dev/null || true)" % (CONSOLE_ORIG, CONSOLE_SETUP, CONSOLE_ORIG)],
                 "the console font is back as it was (%s)" % CONSOLE_ORIG,
                 "sudo cp %s %s; sudo setupcon --force" % (CONSOLE_ORIG, CONSOLE_SETUP))
    elif ctx.cfg.font_face and distro() == "debian":
        ctx.row("todo", "console", "the font stays %s %s (no original kept before v1.12): sudo dpkg-reconfigure console-setup"
                % (ctx.cfg.font_face, ctx.cfg.font_size))
    origs = [p for p in ("/etc/motd.orig", "/etc/issue.orig") if os.path.exists(p)]
    if origs:
        ctx.root("quiet", ["rm", "-f"] + origs, "%s removed (restored by the undo pass)" % " ".join(origs))


def step_headless_leftovers(ctx):
    cfg = ctx.cfg
    user = os.environ.get("USER") or os.path.basename(HOME)
    if not IS_MAC and not is_wsl():
        rc, out = run(["loginctl", "show-user", user, "-p", "Linger"], timeout=5)
        if rc == 0 and "Linger=yes" in out:
            ctx.root("linger", ["loginctl", "disable-linger", user], "linger off: the units end with the login")
        rc, out = run(["id", "-nG", user], timeout=5)
        if rc == 0 and "render" in out.split():
            ctx.root("render", ["gpasswd", "-d", user, "render"], "%s left the render group (takes effect at the next login)" % user)
    elif IS_MAC and cfg.headless:
        ctx.row("todo", "pmset", "spark set sleep 0, disksleep 0, womp 1, autorestart 1: sudo pmset -a sleep 1 disksleep 10 womp 0 autorestart 0 puts Apple's defaults back")
    if cfg.get("SITE_SET_HOSTNAME", "no") == "yes":
        line = ("sudo scutil --set LocalHostName NAME (ComputerName, HostName likewise)" if IS_MAC
                else "sudo hostnamectl set-hostname NAME")
        ctx.row("todo", "hostname", "spark set it to %s; the name before is not recorded: %s" % (cfg.name, line))


def step_terminal(ctx):
    if not IS_MAC:
        return
    from . import theme
    files = glob.glob(os.path.join(CONFIG_DIR, "spark-*.terminal"))
    if ctx.dry:
        if files or theme.spark_profiles():
            ctx.row("would", "terminal", "the spark-* profiles leave Terminal.app's preferences; open windows keep their look until closed")
        return
    gone = theme.remove_profiles()
    for f in files:
        os.remove(f)
    if gone or files:
        ctx.row("ok", "terminal", "%s profile%s removed from Terminal.app; open windows keep their look until closed"
                % (len(gone), "" if len(gone) == 1 else "s"))


def step_bin(ctx):
    for name in ("spark", "explain"):
        p = os.path.join(BIN_DIR, name)
        if _spark_link(p) or os.path.islink(p) and not os.path.exists(p):
            ctx.remove("tools", p)


def _du(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def step_data(ctx):
    if not os.path.isdir(DATA_DIR):
        return
    ctx.freed = _du(DATA_DIR)
    ctx.remove("data", DATA_DIR, "%s -- the engine and the models, %.1f GB" % (_tilde(DATA_DIR), ctx.freed / 2**30))


def step_packages(ctx):
    """The packages bootstrap installed, from the distro file (Linux) or the
    Brewfile (macOS): what a removal names. bash, anything the manager
    calls essential, and the AI's four prerequisites (git curl
    ca-certificates python3) are never removed (packages.removable)."""
    pkgs = pkg.removable()
    if not pkgs:
        return
    line = pkg.remove_line(pkgs)
    if ctx.packages is not True:
        ctx.row("skip", "packages", "kept -- %s removes them" % line)
        return
    if not IS_MAC:
        # simulate first: apt's reverse-dependency removal can take a
        # desktop with the engine libraries. More than the named packages
        # would go -> say the whole list and remove nothing.
        would = pkg.remove_would(pkgs)
        extra = sorted(set(would) - set(pkgs)) if would is not None else None
        if would is None:
            ctx.row("todo", "packages", "the manager cannot say what a removal takes -- kept; by hand: %s" % line)
            return
        if extra:
            ctx.row("todo", "packages", "removing them would also take: %s -- kept; by hand: %s"
                    % (" ".join(extra), line))
            return
    if ctx.dry:
        ctx.row("would", "packages", line)
        return
    if IS_MAC:
        for p in pkgs:
            run(["brew", "uninstall", p], timeout=300)
        ctx.row("ok", "packages", "brew uninstall %s (a formula another package needs stays)" % " ".join(pkgs))
    else:
        ctx.root("packages", pkg.remove_argv(pkgs), " ".join(pkg.remove_argv(pkgs)), timeout=1800)


def step_state_config(ctx):
    keep_state = () if ctx.purge else KEEP_STATE
    keep_config = () if ctx.purge else KEEP_CONFIG
    if os.path.isdir(STATE_DIR):
        for name in sorted(os.listdir(STATE_DIR)):
            p = os.path.join(STATE_DIR, name)
            if name in keep_state:
                ctx.kept.append(p)
                continue
            ctx.remove("state", p)
        if not ctx.dry:
            _rmdir_empty(STATE_DIR)
    if os.path.isdir(CONFIG_DIR):
        for name in sorted(os.listdir(CONFIG_DIR)):
            p = os.path.join(CONFIG_DIR, name)
            if name in keep_config:
                ctx.kept.append(p)
                continue
            if _spark_link(p) or (os.path.islink(p) and not os.path.exists(p)) or name in SPARK_CONFIG:
                ctx.remove("config", p)
            elif name == "launchd" or name.startswith("spark-") and name.endswith(".terminal"):
                ctx.remove("config", p)
            else:
                ctx.kept.append(p)          # not ours to judge: named at the end
        if not ctx.dry:
            _rmdir_empty(CONFIG_DIR)
    if ctx.purge and not ctx.dry:
        for d in (STATE_DIR, CONFIG_DIR):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)


def _default_clone():
    return os.path.realpath(os.environ.get("SPARK_HOME") or os.path.join(HOME, ".spark"))


def clone_status():
    """"default" (the clone get made, clean), "dirty", "foreign" (a
    checkout elsewhere: a developer's), or "not-git"."""
    if os.path.realpath(REPO) != _default_clone():
        return "foreign"
    rc, out = run(["git", "-C", REPO, "status", "--porcelain"], timeout=20)
    if rc != 0:
        return "not-git"
    return "dirty" if out.strip() else "default"


def step_clone(ctx):
    st = clone_status()
    if st == "foreign":
        ctx.row("skip", "clone", "%s is yours (a developer checkout): rm -rf it if you like" % _tilde(REPO))
        return
    if st == "dirty":
        ctx.row("skip", "clone", "%s has uncommitted changes: commit or discard them, then rm -rf it" % _tilde(REPO))
        return
    if getattr(ctx, "undo_pending", False):
        # never delete the script the report just told them to run
        ctx.row("todo", "clone", "%s stays: ./bootstrap.sh there finishes the undo above, "
                                 "then rm -rf it" % _tilde(REPO))
        return
    if ctx.dry:
        ctx.row("would", "clone", "%s removed" % _tilde(REPO))
        return
    shutil.rmtree(REPO, ignore_errors=True)
    ctx.row("ok", "clone", "%s removed" % _tilde(REPO))


STEPS = (step_bootstrap_undo, step_services, step_look, step_rc_lines, step_console, step_headless_leftovers,
         step_terminal, step_bin, step_data, step_packages, step_state_config, step_clone)


def walk(ctx):
    for step in STEPS:
        step(ctx)
    return ctx


def summary(ctx):
    say()
    if ctx.kept:
        say("kept (yours): " + ", ".join(sorted(set(_tilde(p) for p in ctx.kept))))
        if not ctx.purge:
            say("  spark uninstall --purge takes those too")
    if ctx.todo:
        say("left for you:")
        for what, line in ctx.todo:
            say("  %-10s %s" % (what, line))
    if not ctx.dry:
        say("%s is gone from this machine%s" % (MARK, " -- open a new shell (exec $SHELL)" if not IS_MAC else ""))


def main(argv):
    if argv and argv[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    flags = set(argv)
    unknown = flags - {"--dry-run", "--yes", "--purge", "--packages", "--keep-packages"}
    if unknown or ("--packages" in flags and "--keep-packages" in flags):
        say(USAGE.rstrip())
        return 2
    os.environ["SPARK_NO_REFRESH"] = "1"          # nothing re-creates the state dir behind us
    yes = "--yes" in flags or os.environ.get("SPARK_YES") == "1"
    packages = True if "--packages" in flags else (False if "--keep-packages" in flags else None)
    dry = "--dry-run" in flags or bool(os.environ.get("SPARK_NO_APPLY"))
    purge = "--purge" in flags
    tty = sys.stdin.isatty() and sys.stdout.isatty()
    say("%s uninstall -- the plan%s:" % (MARK, ", with --purge" if purge else ""))
    plan = walk(Ctx(True, purge, packages))
    summary(plan)
    if dry:
        return 0
    if not yes:
        if not tty:
            say("%s uninstall -- not a terminal: spark uninstall --yes runs it" % MARK)
            return 2
        try:
            answer = input("remove all of it? type yes: ").strip()
        except EOFError:
            answer = ""
        if answer != "yes":
            say("%s uninstall -- kept" % MARK)
            return 0
    if packages is None and tty and pkg.removable():
        from . import confirm
        packages = confirm("remove the packages spark installed too")
    say()
    done = walk(Ctx(False, purge, packages))
    summary(done)
    return 0
