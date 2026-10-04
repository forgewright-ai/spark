# spark.uninstall -- `spark uninstall`: take spark off this machine.
#
# Everything spark made goes: the units, the look an older spark
# painted (handback.py, the one undo), the rc line, the engine and the
# models, the state, the links, the clone.
# What is yours stays -- the soul and its personality, the memory, the
# sealed users' stores (and the account keys that open them), your
# models.env, your themes, privacy-terms -- unless --purge. The packages
# spark installed are a question. The plan prints first (bootstrap's row
# shape), then the typed word `yes` (spark do's danger shape); --dry-run
# shows only.
#
# Order matters (the traps): the one bootstrap pass -- headless undone
# through its own rows first, so bootstrap does not skip them -- runs
# BEFORE anything is removed; nothing calls bootstrap or check.refresh
# after that (each would put things back).
# Root steps try sudo and become a `todo` row naming the command when it
# refuses; the clone goes last, only when it is the default clone and
# clean.

import os
import re
import shutil
import sys

from . import (BIN_DIR, CONFIG_DIR, DATA_DIR, FORGE_PID, FORGE_URL_FILE, HOME, IS_MAC, MARK, REPO, STATE_DIR,
               VAR_SERVICE, config, init_shape, is_wsl, run, say)
from . import handback
from . import packages as pkg

USAGE = """%s uninstall -- remove spark: shows the plan, then asks

  spark uninstall              show the plan, then ask you to type yes
  spark uninstall --dry-run    show the plan, change nothing
  spark uninstall --yes        no question (or SPARK_YES=1)
  --purge                      also your soul, memory, users and word list
  --packages | --keep-packages remove or keep the packages spark installed
                               (asked at a terminal, else kept)

  A few things stay (like the hostname); spark prints how to undo each.
  The clone goes only when it is ~/.spark and has no changes.
""" % MARK

KEEP_CONFIG = ("soul", "personality", "memory", "models.env", "themes", "privacy-terms")
KEEP_STATE = ("users", "account", "account-key")
# faces and voice (the voice it kept) are spark awaken's, and words the
# file an older awaken wrote (the state's look, news, news-seen and
# loads.json go with the whole state dir); the personality is the soul's
SPARK_CONFIG = ("site.env", "spark.env", "keys.env", "theme.env", "console-colors", "console-colors.rgb", "check.log",
                "words", "faces", "voice")
UNITS_LINUX = ("spark-serve.service", "spark-forge.service", "spark-check.timer", "spark-check.service")
SV_UNITS = ("forge", "serve", "check")            # runit: ~/.config/spark/sv/spark-<unit>, the same three
ETC_SV = os.environ.get("SPARK_ETC_SV", "/etc/sv")    # runit's service definitions (bootstrap's seam too)
SV_USER = re.compile(r"^[a-z_][a-z0-9_-]*$")      # a user name that may ride in a root path (bootstrap's rule)
SV_MARK = "rendered by spark bootstrap.sh"        # what marks /etc/sv/runsvdir-USER/run as spark's
RC_CANDIDATES = (".bashrc", ".zshrc", ".bash_profile", ".zprofile")


class Ctx(handback.Ctx):
    """handback's row and root (one shape for both), plus the plan's own."""

    def __init__(self, dry, purge, packages):
        super(Ctx, self).__init__(dry)
        self.purge, self.packages = purge, packages
        self.cfg = config.load()
        self.kept = []          # paths that stayed on purpose
        self.freed = 0          # bytes the data dir held

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


def _rmdir_empty(path):
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


# ---------------------------------------------------------------- the steps
def step_bootstrap_undo(ctx):
    """The one bootstrap pass: headless undone through its own rows, the
    key flipped first. Before anything is removed."""
    from . import site
    if not ctx.cfg.headless:
        ctx.row("skip", "undo", "headless was never on")
        return
    if ctx.dry:
        ctx.row("would", "undo", "headless off (sudo)")
        return
    site.set_keys(_quiet=True, SITE_HEADLESS="no")
    os.environ["SPARK_HEADLESS_UNDO"] = "1"
    rc = site.apply(["handback", "sleep", "lid", "daemons", r"spark\.(serve|forge|check)"], stream=True)
    if rc == 0:
        ctx.row("ok", "undo", "headless off")
        return
    # The undo is the one root step that runs bootstrap rather than a
    # command of its own -- it is bootstrap that knows how to unmask sleep
    # and drop the lid file. So the remedy has to be "run ./bootstrap.sh",
    # and the clone has to still be there to run: step_clone reads this.
    ctx.undo_pending = True
    ctx.row("todo", "undo", "headless is still on (no sudo) -- cd %s && ./bootstrap.sh" % _tilde(REPO))


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
                ctx.root(unit, ["launchctl", "bootout", "system/" + name], "%s stopped" % name)
                ctx.root(unit, ["rm", "-f", "/Library/LaunchDaemons/%s.plist" % name], "/Library/LaunchDaemons/%s.plist removed" % name)
            target = "gui/%d/%s" % (os.getuid(), name)
            plist = os.path.join(HOME, "Library", "LaunchAgents", name + ".plist")
            if not ctx.dry:
                run(["launchctl", "bootout", target], timeout=20)
            if os.path.exists(plist):
                ctx.remove(unit, plist, "%s stopped, %s removed" % (name, _tilde(plist)))
            elif not ctx.dry:
                ctx.row("ok", unit, "%s not loaded" % name)
    elif init_shape() == "runit":
        # runit: `sv down` ends each service, `sv exit` its runsv; the three
        # dirs go, then the links in a runsvdir of your own or the root
        # service spark wrote (state/made says which). The `down` file
        # first: runsvdir rescans every 5 s, and a dir it finds again
        # without one gets a new runsv that starts the service
        svdir = os.path.join(CONFIG_DIR, "sv")
        for unit in SV_UNITS:
            d = engine.service_dir(unit)
            if not ctx.dry and os.path.isdir(d):
                try:
                    with open(os.path.join(d, "down"), "a"):
                        pass
                except OSError:
                    pass
                run(["sv", "down", d], timeout=20)
                run(["sv", "exit", d], timeout=20)
            if os.path.lexists(d):
                ctx.remove("units", d, "%s stopped, %s removed" % (engine.unit_name(unit), _tilde(d)))
        if not ctx.dry:
            _rmdir_empty(svdir)
        _runit_root(ctx)
    else:
        for name in UNITS_LINUX:
            if not ctx.dry:
                run(["systemctl", "--user", "disable", "--now", name], timeout=30)
            link = os.path.join(HOME, ".config", "systemd", "user", name)
            if _spark_link(link) or os.path.lexists(link):
                ctx.remove("units", link, "%s stopped, %s removed" % (name, _tilde(link)))
        if not ctx.dry:
            run(["systemctl", "--user", "daemon-reload"], timeout=30)
            run(["systemctl", "--user", "reset-failed"], timeout=30)
    # whatever still runs under a pidfile or the port, ours -- the pid
    # file's pid only when its command line is the page's server (a pid
    # long since reused by another program is not signalled)
    if not ctx.dry and not cfg.client:
        pid = engine.pid_of(FORGE_PID, engine.FORGE_MARKS)
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
        ctx.row("ok", "processes", "the page and the engine stopped")
    launchd = os.path.join(CONFIG_DIR, "launchd")
    ctx.remove("launchd", launchd)


def foreign_svdir(text):
    """The directory a runsvdir-USER of your own supervises: the last word
    of its `runsvdir` line, quotes off, `$HOME` spelled out (bootstrap
    reads it the same way). '' when it cannot be read (a space or a quote
    left in it). Pure."""
    line = next((l for l in reversed(text.splitlines()) if "runsvdir" in l), "")
    word = (line.split() or [""])[-1].strip("\"'").replace("$HOME", HOME)
    return word if word and not re.search(r"[\s\"']", word) else ""


def _runit_root(ctx):
    """The user's runsvdir service (/etc/sv/runsvdir-USER, linked into
    /var/service): spark's to remove when bootstrap recorded writing it
    (state/made), else a todo naming both paths. A runsvdir-USER of your
    own keeps running; only spark's three links in its directory go."""
    user = os.environ.get("USER") or os.path.basename(HOME)
    if not SV_USER.match(user):
        return
    root_sv = os.path.join(ETC_SV, "runsvdir-" + user)
    link = os.path.join(VAR_SERVICE, "runsvdir-" + user)
    try:
        with open(os.path.join(root_sv, "run"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    if SV_MARK not in text:
        d = foreign_svdir(text)
        for unit in SV_UNITS:
            p = os.path.join(d, "spark-" + unit) if d else ""
            if p and os.path.islink(p):
                ctx.remove("units", p, "%s unlinked from your runsvdir-%s" % (_tilde(p), user))
        return
    if "runsvdir" in _made():
        ctx.root("supervisor", ["sh", "-c", "sv down %s 2>/dev/null; rm -f %s; rm -rf %s" % (link, link, root_sv)],
                 "runsvdir-%s stopped and removed (%s, %s)" % (user, link, root_sv),
                 "sudo rm -f %s; sudo rm -rf %s" % (link, root_sv))
    else:
        ctx.row("todo", "supervisor", "spark did not record writing %s -- yours to decide: sudo rm -f %s; sudo rm -rf %s"
                % (root_sv, link, root_sv))


def step_look(ctx):
    """What an older spark left in the way: a pre-v1.10 install's plugin
    links (the micro bootstrap row's twin)."""
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
    it) from an rc file; True when a line went. A symlinked rc file is
    followed, as bootstrap's append follows it: the file it points at
    loses the line and the link stays. A link into the repository is
    spark's own file, never edited."""
    from . import site
    if site._spark_link(path) or not os.path.isfile(path):
        return False
    path = os.path.realpath(path)
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
        if site._spark_link(path) or not os.path.isfile(path):
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


def step_handback(ctx):
    """The look an older spark painted: handback.walk, the one undo
    bootstrap's handback row runs too (the palette, the console font,
    motd and issue, a quiet boot, Terminal.app's spark profiles). A font
    set before v1.12 kept no original: said, never guessed."""
    handback.walk(ctx)
    face = ctx.cfg.get("SITE_FONT_FACE", "")
    setup = handback.CONSOLE_SETUP
    if (face and not IS_MAC and not os.path.exists(setup + ".spark-orig")
            and re.search(r'^FONTFACE="?%s"?$' % re.escape(face), handback._read(setup) or "", re.M)):
        ctx.row("todo", "console", "the font stays %s -- sudo dpkg-reconfigure console-setup" % face)


def _made():
    """The root-side changes bootstrap recorded (state/made): what spark
    may undo. Linger a user enabled, a render group they joined
    themselves, are not spark's to take away."""
    try:
        with open(os.path.join(STATE_DIR, "made"), encoding="utf-8") as f:
            return set(f.read().split())
    except OSError:
        return set()


def step_headless_leftovers(ctx):
    cfg = ctx.cfg
    made = _made()
    user = os.environ.get("USER") or os.path.basename(HOME)
    if not IS_MAC and not is_wsl():
        # runit has no logind and no linger: the supervisor went with step_services
        if init_shape() != "runit":
            rc, out = run(["loginctl", "show-user", user, "-p", "Linger"], timeout=5)
            if rc == 0 and "Linger=yes" in out:
                if "linger" in made:
                    ctx.root("linger", ["loginctl", "disable-linger", user], "linger off")
                else:
                    ctx.row("todo", "linger", "spark did not turn linger on -- yours to decide: loginctl disable-linger %s" % user)
        rc, out = run(["id", "-nG", user], timeout=5)
        if rc == 0 and "render" in out.split():
            if "render" in made:
                ctx.root("render", ["gpasswd", "-d", user, "render"], "%s leaves the render group at the next login" % user)
            else:
                ctx.row("todo", "render", "spark did not add %s to render -- yours to decide: sudo gpasswd -d %s render" % (user, user))
    elif IS_MAC and cfg.headless:
        ctx.row("todo", "pmset", "Apple's defaults: sudo pmset -a sleep 1 disksleep 10 womp 0 autorestart 0")
    if cfg.get("SITE_SET_HOSTNAME", "no") == "yes":
        # by presence, as bootstrap set it: hostnamectl where there is one, else the file and the kernel
        line = ("sudo scutil --set LocalHostName NAME (ComputerName, HostName likewise)" if IS_MAC
                else "sudo hostnamectl set-hostname NAME" if shutil.which("hostnamectl")
                else "echo NAME | sudo tee /etc/hostname; sudo sysctl -qw kernel.hostname=NAME")
        ctx.row("todo", "hostname", "spark named it %s -- to rename: %s" % (cfg.name, line))


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
    """The data dir whole: the engine, the models and the voice's engine
    (voice/, spark voice's download)."""
    if not os.path.isdir(DATA_DIR):
        return
    ctx.freed = _du(DATA_DIR)
    what = "the engine, the models and the voice" if os.path.isdir(os.path.join(DATA_DIR, "voice")) \
        else "the engine and the models"
    ctx.remove("data", DATA_DIR, "%s -- %s, %.1f GB" % (_tilde(DATA_DIR), what, ctx.freed / 2**30))


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
        ctx.row("ok", "packages", "brew uninstall %s" % " ".join(pkgs))
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
            # with --purge, spark's kept files (soul, memory, ...) are
            # known by name and go too; a file spark cannot name is not
            # spark's to delete, purge or no purge
            known = name in SPARK_CONFIG or (ctx.purge and name in KEEP_CONFIG)
            if _spark_link(p) or (os.path.islink(p) and not os.path.exists(p)) or known:
                ctx.remove("config", p)
            elif name in ("launchd", "sv", "words.d") or name.startswith("spark-") and name.endswith(".terminal"):
                ctx.remove("config", p)
            else:
                ctx.kept.append(p)          # not ours to judge: named at the end
        if not ctx.dry:
            _rmdir_empty(CONFIG_DIR)


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
        ctx.row("skip", "clone", "%s is yours (a developer clone)" % _tilde(REPO))
        return
    if st == "dirty":
        ctx.row("skip", "clone", "%s has changes: commit or drop them, then rm -rf it" % _tilde(REPO))
        return
    if getattr(ctx, "undo_pending", False):
        # never delete the script the report just told them to run
        ctx.row("todo", "clone", "%s stays: run ./bootstrap.sh there, then rm -rf it" % _tilde(REPO))
        return
    if ctx.dry:
        ctx.row("would", "clone", "%s removed" % _tilde(REPO))
        return
    shutil.rmtree(REPO, ignore_errors=True)
    ctx.row("ok", "clone", "%s removed" % _tilde(REPO))


STEPS = (step_bootstrap_undo, step_services, step_look, step_rc_lines, step_handback, step_headless_leftovers,
         step_bin, step_data, step_packages, step_state_config, step_clone)


def walk(ctx):
    for step in STEPS:
        step(ctx)
    return ctx


def summary(ctx):
    say()
    if ctx.kept:
        say("* kept (yours): " + ", ".join(sorted(set(_tilde(p) for p in ctx.kept))))
        if not ctx.purge:
            say("  spark uninstall --purge takes those too")
    if ctx.todo:
        say("* left for you:")
        for what, line in ctx.todo:
            say("  %-10s %s" % (what, line))
    if not ctx.dry:
        say("* %s is gone from this machine%s" % (MARK, " -- open a new shell (exec $SHELL)" if not IS_MAC else ""))


def main(argv):
    if argv and argv[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    flags = set(argv)
    unknown = flags - {"--dry-run", "--yes", "--purge", "--packages", "--keep-packages"}
    if unknown:
        say("%s uninstall -- no word %s; spark uninstall -h lists them" % (MARK, next(a for a in argv if a in unknown)))
        return 2
    if "--packages" in flags and "--keep-packages" in flags:
        say("%s uninstall -- --packages or --keep-packages, not both" % MARK)
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
            say("* nothing changed")
            return 0

    if packages is None and tty and pkg.removable():
        from . import confirm
        packages = confirm("remove the packages spark installed too")
    say()
    done = walk(Ctx(False, purge, packages))
    summary(done)
    return 0
