# spark.check -- is this machine still what its repository says it is?
#
# A report, not a monitor: `spark check` runs every row once, prints the
# ones that need the user (`--all`: every row) and exits 0 iff nothing
# reproducible is broken. Rows are small functions registered
# with @row; each returns ok / warn / fail / na. CAPABILITY rows never fail
# (they describe what the world offers, not what the repo promises), so the
# exit code keeps one meaning.
#
# Every row that can be fixture-tested is: `--selftest` builds a good and a
# bad throwaway HOME + repository and asserts the row flips. A row that has
# only ever returned one answer has never been tested.

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from . import distro, init_shape, is_wsl, runit_live  # noqa: E402  (the OS facts, beside os_pretty)
from . import (ALERT_FILE, BIN_DIR, CACHE_DIR, CHECK_HISTORY, CHECK_JSON, CHECK_LOCK, HOME, IS_MAC, MARK, OS, REPO,
               STATE_DIR, config, glyph, log_exc, packages, page, run, say, state_dir, version)

OK, WARN, FAIL, NA = "ok", "warn", "fail", "na"
GLYPH = {OK: glyph("ok"), WARN: "!", FAIL: glyph("fail"), NA: glyph("na")}
SEP = glyph("sep")
COLOR = {OK: "32", WARN: "33", FAIL: "31", NA: "2"}
CATEGORIES = ("SOFTWARE", "CAPABILITY", "NONFUNCTIONAL")


class Row:
    __slots__ = ("status", "value", "remedy", "name", "category")

    def __init__(self, status, value, remedy=""):
        self.status, self.value, self.remedy = status, value, remedy
        self.name = self.category = ""


def ok(value):
    return Row(OK, value)


def warn(value, remedy=""):
    return Row(WARN, value, remedy)


def fail(value, remedy=""):
    return Row(FAIL, value, remedy)


def na(value, remedy=""):
    return Row(NA, value, remedy)


class Spec:
    __slots__ = ("name", "category", "fixture", "reason", "fn")

    def __init__(self, name, category, fixture, reason, fn):
        self.name, self.category, self.fixture, self.reason, self.fn = name, category, fixture, reason, fn


SPECS = []


def row(category, fixture=True, reason=""):
    """Register a row. fixture=False rows must give the reason they cannot
    be fixture-tested; --selftest prints it."""
    assert category in CATEGORIES
    assert fixture or reason, "an untestable row must say why"

    def deco(fn):
        SPECS.append(Spec(fn.__name__[4:].replace("_", "-"), category, fixture, reason, fn))
        return fn
    return deco


# ------------------------------------------------------------------ context
class Ctx:
    def __init__(self, fresh=False, fetch=False):
        self.cfg = config.load()
        self.repo = REPO
        self.fresh = fresh
        self.fetch = fetch
        self.home = HOME
        # the timer's run, not a person's: the systemd unit, the runit loop
        # and the launchd agent all run `spark check --porcelain` with
        # TIMER_ENV set, no terminal on stdin and no --fresh (the
        # background refresh() after a person's verb, the selftest and CI
        # all pass --fresh). Only that run may refresh the knowledge index
        # (G0 M7) -- see unattended()
        self.unattended = False

    def sh(self, cmd, timeout=10, env=None):
        return run(cmd, timeout=timeout, env=env)

    def cached(self, key, ttl, fn):
        """fn() at most once per ttl seconds; the value lives in state/cache.
        --fresh ignores the cache."""
        path = os.path.join(CACHE_DIR, key + ".json")
        if not self.fresh:
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                if time.time() - d["t"] < ttl:
                    return d["v"]
            except (OSError, ValueError, KeyError):
                pass
        v = fn()
        try:
            os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"t": time.time(), "v": v}, f)
        except OSError:
            pass
        return v

    def short(self, path):
        return "~" + path[len(self.home):] if path.startswith(self.home + "/") else path


# Two value areas cut across the categories: the AI infrastructure rows
# (engine, models, serving, speed) and the core rows (the contracts, the
# FORGE, identity, the machine's promises). An app has no row by design:
# it lives in its own repository, with its own doctor where it needs one.
# ------------------------------------------------------------ SOFTWARE rows
@row("SOFTWARE", fixture=not IS_MAC, reason="the mac core installs no package; the Linux gates prove the row")
def row_packages(ctx):
    if IS_MAC:
        return ok("nothing to install")
    rc, out = ctx.sh(["sh", os.path.join(ctx.repo, "bootstrap.sh"), "--list-packages"], 30)
    if rc != 0:
        return fail("could not list the packages", "spark update")
    pkgs = out.split()
    if not pkgs:
        return ok("nothing to install")
    have = packages.installed(pkgs)
    if have is None:
        return fail("no package manager spark knows (%s)" % (packages.manager() or "apt, pacman, xbps, dnf or zypper"))
    missing = [p for p in pkgs if p not in have]
    if missing:
        return fail("%d of %d missing: %s" % (len(missing), len(pkgs), " ".join(missing[:6])), "spark update")
    return ok("all %d installed" % len(pkgs))


@row("SOFTWARE")
def row_configs(ctx):
    script = os.path.join(ctx.repo, "install.sh")
    rc, out = ctx.sh(["sh", script, "--dry-run"], 60)
    lines = out.splitlines()
    if rc != 0:
        return fail("could not check the files: %s" % (lines[-1] if lines else "no output"), "spark update")
    would = [re.match(r"^would (?:link|render|back up)\s+(.*)$", l) for l in lines if l.startswith("would")]
    done = [l for l in lines if l.startswith("ok ")]
    if would:
        names = sorted({os.path.basename(m.group(1)) for m in would if m})
        more = ", and %d more" % (len(names) - 2) if len(names) > 2 else ""
        return fail("%d not in place: %s%s" % (len(names), ", ".join(names[:2]), more), "spark update")
    return ok("%d files in place" % len(done))


@row("SOFTWARE")
def row_tools(ctx):
    rc, out = ctx.sh(["sh", os.path.join(ctx.repo, "bootstrap.sh"), "--list-tools"], 30)
    if rc != 0:
        return fail("could not list the tools", "spark update")
    bad, names = [], []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        rel, name = line.split("\t", 1)
        names.append(name)
        link = os.path.join(BIN_DIR, name)
        if not os.path.islink(link) or os.path.realpath(link) != os.path.realpath(os.path.join(ctx.repo, rel)):
            bad.append(name)
    if bad:
        return fail("not in ~/.local/bin: %s" % " ".join(bad), "spark update")
    found = shutil.which("spark")
    if found and os.path.realpath(found) != os.path.realpath(os.path.join(BIN_DIR, "spark")):
        return warn("another spark comes first on PATH: %s" % found, "put ~/.local/bin first on PATH")
    return ok("%s in ~/.local/bin" % " and ".join(names))


ENGINE_FLAVOURS = ("macos-arm64", "macos-x64", "ubuntu-vulkan-x64", "ubuntu-x64", "ubuntu-vulkan-arm64", "ubuntu-arm64")


@row("SOFTWARE")
def row_engine(ctx):
    """llama-server where spark will look for it (SPARK_ENGINE_DIR, the
    newest pinned tarball, Homebrew on macOS): the AI layer's binary, both
    OSes. The value names the directory and, when the tarball's `flavour`
    file or the name says so, the release flavour."""
    from . import engine
    d = engine.engine_dir(ctx.cfg)
    if not os.access(os.path.join(d, "llama-server"), os.X_OK):
        if ctx.cfg.model_choice.strip().lower() == "none":
            return na("no model chosen", "spark model NAME")
        return fail("missing", "spark update")
    flavour = ""
    try:
        with open(os.path.join(d, "flavour"), encoding="utf-8") as f:
            flavour = f.read().strip().split("\n")[0]
    except OSError:
        flavour = next((x for x in ENGINE_FLAVOURS if x in os.path.basename(d)), "")
    from . import ENGINE_DIR
    if ctx.cfg.engine_dir:
        name, where = ctx.short(d), "SPARK_ENGINE_DIR"
    elif IS_MAC and d in ("/opt/homebrew/bin", "/usr/local/bin"):
        name, where = d, "Homebrew"
    elif os.path.dirname(d) == ENGINE_DIR:
        name, where = os.path.basename(d), ""
    else:
        # a llama-server this machine already had (facts probed PATH and
        # the system dirs): spark has no pin here, so it serves with yours
        name, where = ctx.short(d), "your build"
    build = engine.backend(ctx.cfg)
    if not ctx.cfg.engine_dir and flavour.startswith("ubuntu-") and ("vulkan" in flavour) != (build == "vulkan"):
        return warn("the %s build is here, this machine wants %s" % ("vulkan" if "vulkan" in flavour else "cpu", build),
                    "spark update")
    return ok(" ".join(x for x in (name, flavour, "(%s)" % where if where else "") if x))


@row("SOFTWARE")
def row_git(ctx):
    g = ["git", "-C", ctx.repo]
    if ctx.fetch:
        ctx.sh(g + ["fetch", "-q"], 30)
    rc, out = ctx.sh(g + ["status", "--porcelain"], 20)
    if rc != 0:
        return fail("not a git checkout: %s" % ctx.short(ctx.repo), "run the install line again")
    rc, _ = ctx.sh(g + ["symbolic-ref", "-q", "HEAD"], 10)
    if rc != 0:
        # detached: a release clone. Currency is against the newest tag,
        # not an upstream branch -- `spark update` moves it.
        rc2, tags = ctx.sh(g + ["tag", "-l", "v[0-9]*", "--sort=-v:refname"], 10)
        newest = tags.split()[0] if rc2 == 0 and tags.split() else ""
        rc3, cur = ctx.sh(g + ["describe", "--tags", "--exact-match"], 10)
        cur = cur.strip() if rc3 == 0 else ""
        if not cur:
            return warn("not on a release", "spark update")
        if not newest or cur == newest:
            return ok("%s, the newest" % cur)
        return warn("%s; %s is out" % (cur, newest), "spark update")
    dirty = len(out.splitlines())
    rc, out = ctx.sh(g + ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"], 20)
    problems = []
    if dirty:
        problems.append("%d uncommitted file%s" % (dirty, "" if dirty == 1 else "s"))
    if rc != 0:
        problems.append("no upstream")
    else:
        ahead, behind = (int(x) for x in out.split())
        if ahead:
            problems.append("%d unpushed" % ahead)
        if behind:
            problems.append("%d behind origin" % behind)
    if problems:
        mine = dirty or rc != 0 or ahead
        return warn(", ".join(problems), "commit and push" if mine else "spark update")
    return ok("clean and pushed")


@row("SOFTWARE", fixture=False,
     reason="the good fixture is on main, where the row is na by design; tests/update_test.sh proves the flip")
def row_signed(ctx):
    """The tag this checkout sits on was signed by a key in the tree's
    allowed-signers -- the promise `spark update` keeps by moving to no
    other tag. A branch (a developer clone) has no tag to verify."""
    g = ["git", "-C", ctx.repo]
    rc, _ = ctx.sh(g + ["rev-parse", "--git-dir"], 10)
    if rc != 0:
        return na("not a git checkout")
    rc, branch = ctx.sh(g + ["symbolic-ref", "-q", "--short", "HEAD"], 10)
    if rc == 0:
        return na("on branch %s, not a release" % branch.strip())
    rc, cur = ctx.sh(g + ["describe", "--tags", "--exact-match"], 10)
    if rc != 0:
        return na("not on a release")
    from .update import here, verified
    # the tag whose object names it, when two names sit on HEAD
    cur = here(ctx.repo) or cur.strip()
    who, why = verified(cur, ctx.repo)
    if who:
        return ok("%s signed by %s" % (cur, who))
    if why.startswith("not signed"):
        return warn("%s is not signed" % cur, "spark update")
    if why.startswith("named"):
        return warn("%s is %s" % (cur, why), "spark update")
    return warn("%s %s" % (cur, why), "install openssh and git 2.34 or newer")


@row("SOFTWARE")
def row_hooks(ctx):
    rc, out = ctx.sh(["git", "-C", ctx.repo, "config", "core.hooksPath"], 10)
    # relative or absolute, the same directory is the same promise
    want = os.path.join(ctx.repo, ".githooks")
    got = out.strip()
    if rc == 0 and (got == ".githooks" or os.path.abspath(os.path.join(ctx.repo, got)) == want):
        return ok("commit hooks on")
    return fail("commit hooks off", "spark update")



def _systemd_user(ctx, unit):
    """(enabled, active) strings for a user unit; ("", "") when there is
    no user systemd to ask (the same probe bootstrap.sh uses)."""
    from . import engine
    env = engine.user_bus_env()
    rc, _ = ctx.sh(["systemctl", "--user", "show-environment"], 10, env=env)
    if rc != 0:
        return "", ""
    rc, en = ctx.sh(["systemctl", "--user", "is-enabled", unit], 10, env=env)
    rc, ac = ctx.sh(["systemctl", "--user", "is-active", unit], 10, env=env)
    return en.strip() or "not-found", ac.strip() or "inactive"


# runit without a booted /var/service (a container): bootstrap's `skip
# runit` row says the same words
RUNIT_NOT_LIVE = "runit is not running here (a container)"


def _runit_user(ctx, unit):
    """(enabled, active) for a runit service dir, in the systemd row's
    vocabulary: enabled = no `down` file and a runsv watching it, disabled
    = a `down` file, not-found = no dir (or nobody supervising it); active
    = `sv status` says run, restarting = it says finish (the run script
    exited and runsv brings it back: enabled, not running)."""
    from . import engine
    d = engine.service_dir(unit)
    if not os.path.isdir(d):
        return "not-found", "inactive"
    rc, out = ctx.sh(["sv", "status", d], 10)
    st = engine.parse_sv_status(out)
    if os.path.exists(os.path.join(d, "down")):
        en = "disabled"
    else:
        en = "enabled" if st != "absent" else "not-found"
    return en, {"run": "active", "finish": "restarting"}.get(st, "inactive")


def _unit_word(en, ac):
    """A unit's state as a person says it: on, restarting, else the
    manager's own two words (they name what to look at)."""
    if en == "enabled" and ac == "active":
        return "on"
    if en == "enabled" and ac == "restarting":
        return "restarting"
    return "%s, %s" % (en, ac)


@row("SOFTWARE")
def row_services(ctx):
    if IS_MAC:
        dom = "gui/%d" % os.getuid()
        rc, disabled = ctx.sh(["launchctl", "print-disabled", dom], 10)
        agents = os.path.join(ctx.home, "Library", "LaunchAgents")
        parts, worst = [], OK

        def state(label):
            # a LaunchDaemon (spark serve boot on) lives in root's system/ domain
            rc, _ = ctx.sh(["launchctl", "print", "system/" + label], 10)
            if rc == 0:
                return "daemon"
            if '"%s" => disabled' % label in disabled or '"%s" => true' % label in disabled:
                return "disabled"
            rc, _ = ctx.sh(["launchctl", "print", "%s/%s" % (dom, label)], 10)
            if rc == 0:
                return "loaded"
            return "installed" if os.path.exists(os.path.join(agents, label + ".plist")) else "absent"
        words = {"loaded": "on", "daemon": "on from boot", "disabled": "off", "absent": "on demand",
                 "installed": "not loaded"}
        s = state("spark.check")
        parts.append("check %s" % words.get(s, s))
        if s not in ("loaded", "daemon"):
            worst = FAIL
        s = state("spark.serve")
        parts.append("serve %s" % words[s])
        if s == "installed":
            worst = FAIL
        # the FORGE: absent or disabled is "off" (SPARK_FORGE=off, or auto
        # with nothing served); a plist that sits there unloaded is broken
        s = state("spark.forge")
        parts.append("forge %s" % (words[s] if s in ("loaded", "daemon", "installed") else "off"))
        if s == "installed":
            worst = FAIL
        remedy = "spark update" if worst == FAIL else ""
        return Row(worst, SEP.join(parts), remedy)
    from . import engine
    runit = init_shape() == "runit"
    if runit:
        # runit: the three service dirs under the user's runsvdir; without
        # a booted /var/service (a container) there is nobody to ask
        if not runit_live():
            return na(RUNIT_NOT_LIVE)
        en, ac = _runit_user(ctx, "check")
        parts = ["check %s" % _unit_word(en, ac)]
    else:
        en, ac = _systemd_user(ctx, "spark-check.timer")
        if not en:
            if is_wsl():
                return na("no user systemd (WSL 2)", "[boot] systemd=true in /etc/wsl.conf; wsl --shutdown; spark update")
            return na("no user systemd here")
        parts = ["check %s" % _unit_word(en, ac)]
    worst, remedies = OK, []
    if en != "enabled" or ac not in ("active", "restarting"):
        worst = FAIL
    elif ac == "restarting":
        # runit's finish: the loop exited and runsv brings it back
        worst = WARN
        remedies.append(engine.restart_line("check"))
    sen, sac = _runit_user(ctx, "serve") if runit else _systemd_user(ctx, "spark-serve.service")
    if sen == "enabled":
        if sac != "active":
            if engine.server_pids(ctx.cfg.port):
                parts.append("serve started by hand")
                remedies.append("spark serve off; spark serve on")
            else:
                parts.append("serve %s" % sac)
                remedies.append(engine.restart_line("serve"))
            worst = WARN if worst == OK else worst
        else:
            parts.append("serve on")
    elif sen == "disabled":
        parts.append("serve off")
    else:
        parts.append("serve on demand")
    # the FORGE: enabled and running, enabled but down (warn), or off
    fen, fac = _runit_user(ctx, "forge") if runit else _systemd_user(ctx, "spark-forge.service")
    if fen == "enabled":
        parts.append("forge %s" % ("on" if fac == "active" else fac))
        if fac != "active":
            remedies.append(engine.restart_line("forge"))
            worst = WARN if worst == OK else worst
    else:
        parts.append("forge off")
    remedy = "spark update" if worst == FAIL else "; ".join(remedies) if worst == WARN else ""
    return Row(worst, SEP.join(parts), remedy)


# ---------------------------------------------------------- CAPABILITY rows
# What the world offers today. These never fail: the exit code is for what
# the repository promises, and a capability is not a promise.
@row("CAPABILITY")
def row_ai(ctx):
    from . import engine
    parts, missing = [], []
    if not engine.engine_bin(ctx.cfg):
        missing.append("the engine")
    m = engine.model_file(ctx.cfg)
    e = engine.model_file(ctx.cfg, "ember")
    if m:
        parts.append("%s %.1f GB" % (config.model_name(m), os.path.getsize(m) / 2**30))
    else:
        missing.append("a model")
    if m and e:
        parts.append("chat %s %.1f GB" % (config.model_name(e), os.path.getsize(e) / 2**30))
    if m and not e and engine.chosen_model_name(ctx.cfg, "ember"):
        missing.append("the chat model %s" % config.model_name(engine.chosen_model_name(ctx.cfg, "ember")))
    if not which("spark"):
        missing.append("spark on PATH")
    if missing:
        return warn("missing: %s" % ", ".join(missing), "spark update")
    return ok(", ".join(parts))


def which(name):
    """shutil.which, then ~/.local/bin and Homebrew's bin: a non-interactive
    shell (ssh host 'spark check', a cron) never sourced the hook that puts
    them on PATH, and a tool that is there is not missing."""
    found = shutil.which(name)
    if found:
        return found
    for d in (os.path.join(os.path.expanduser("~"), ".local", "bin"), "/opt/homebrew/bin"):
        c = os.path.join(d, name)
        if os.access(c, os.X_OK):
            return c
    return None


def _short_age(seconds):
    """12 s / 3 h / 2 d -- an age, short form (row_models' cache)."""
    s = int(seconds)
    if s < 60:
        return "%d s" % s
    m = s // 60
    if m < 60:
        return "%d m" % m
    h = m // 60
    if h < 24:
        return "%d h" % h
    return "%d d" % (h // 24)


@row("CAPABILITY")
def row_models(ctx):
    """sha256 of every downloaded model file, cached a day
    (verify.verify_all); never fails -- a mismatch warns, naming the fix."""
    from . import verify
    rows = verify.verify_all(ctx.cfg, force=False)
    if not rows:
        return na("no downloaded model")
    bad = [r for r in rows if r["status"] == "bad"]
    if bad:
        names = ", ".join(r["name"] for r in bad)
        return warn("damaged: %s" % names, "spark model rm %s; spark model %s" % (bad[0]["name"], bad[0]["name"]))
    age = _short_age(time.time() - min(r["at"] for r in rows))
    return ok("%d file%s intact, checked %s ago" % (len(rows), "" if len(rows) == 1 else "s", age))


def _brain(ctx):
    from . import wire

    def probe():
        try:
            b = wire.resolve_brain(ctx.cfg, fresh=True)
            return [b.url, b.model]
        except wire.BrainError as e:
            return [None, e.hint]
    return ctx.cached("brain", 300, probe)


@row("CAPABILITY")
def row_prompt(ctx):
    from . import OFF_FLAG, cli, site
    files = [os.path.join(ctx.home, ".config", "spark", "widget." + sh) for sh in ("bash", "zsh")]
    absent = [os.path.basename(f) for f in files if not os.path.isfile(f)]
    if absent:
        return warn("missing: %s" % " ".join(absent), "spark update")
    # the rc hook: the one marked line in the rc file, or not
    shell = site.login_shell()
    state, rc = site.rc_hook_state(shell)
    if state == "missing":
        if rc is None:
            return warn("%s has no prompt line (bash 4+ or zsh do)" % shell, "chsh -s /bin/zsh")
        return warn("%s lacks the spark line" % ctx.short(rc), "spark update")
    live = cli.live_widgets()
    if os.path.exists(OFF_FLAG):
        return na("switched off", "spark on")
    if not live:
        if ctx.cfg.headless:
            return na("no shell open")
        return warn("no shell has it yet", "exec $SHELL")
    url, model = _brain(ctx)
    who = ", ".join(sorted({s for s, _ in live}))
    if not url:
        return na("in %s, no model answers" % who, model)
    return ok("in %s, %s answers" % (who, config.model_name(model)))


@row("CAPABILITY")
def row_failure(ctx):
    """The failure moment: a nonzero exit offers explain at the prompt.
    Core -- the widgets carry it everywhere. A live
    shell says so through the marker's fourth field (contract 6)."""
    from . import OFF_FLAG, WIDGETS_DIR
    d = os.path.join(ctx.home, ".config", "spark")
    stale = []
    for sh in ("bash", "zsh"):
        p = os.path.join(d, "widget." + sh)
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                if "_spark_failed" not in f.read():
                    stale.append("widget." + sh)
        except OSError:
            stale.append("widget." + sh)
    if stale:
        return warn("old widget: %s" % ", ".join(stale), "spark update")
    if os.path.exists(OFF_FLAG):
        return na("switched off", "spark on")
    armed, old = [], 0
    try:
        names = os.listdir(WIDGETS_DIR)
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(WIDGETS_DIR, name), encoding="utf-8") as f:
                parts = f.read().split()
            os.kill(int(parts[1]), 0)
        except (OSError, ValueError, IndexError):
            continue
        if len(parts) > 3 and parts[3] == "hook":
            armed.append("%s %s" % (parts[0], parts[1]))
        else:
            old += 1
    if old:
        return warn("%d old shell%s open" % (old, "" if old == 1 else "s"), "exec $SHELL in each")
    if not armed:
        if ctx.cfg.headless:
            return na("no shell open")
        return warn("no shell has it yet", "exec $SHELL")
    return ok("on in %s" % ", ".join(sorted({a.split()[0] for a in armed})))


@row("CAPABILITY")
def row_completion(ctx):
    """TAB completion: the two files install.sh links, each hook sourcing
    its own. Static verbs always; model names offline, from the
    repository the spark symlink points into. Core -- the hooks are core."""
    d = os.path.join(ctx.home, ".config", "spark")
    missing = []
    for sh in ("bash", "zsh"):
        if not os.path.isfile(os.path.join(d, "completion." + sh)):
            missing.append("completion." + sh)
    for sh in ("bash", "zsh"):
        hook = os.path.join(d, "hook." + sh)
        try:
            with open(hook, encoding="utf-8", errors="replace") as f:
                if ("completion." + sh) not in f.read():
                    missing.append("hook.%s lacks its completion line" % sh)
        except OSError:
            missing.append("hook." + sh)
    if missing:
        return warn("missing: %s" % ", ".join(missing), "spark update")
    return ok("bash and zsh")



@row("CAPABILITY")
def row_serve(ctx):
    from . import SERVE_URL_FILE, engine, lan_ip, wire
    tok = ctx.cfg.token_file
    if os.path.exists(tok) and os.stat(tok).st_mode & 0o077:
        return warn("its token is not private", "chmod 600 %s" % ctx.short(tok))
    st = engine.service_state(ctx.cfg)
    url = wire.serve_url()
    if not url:
        return na({"loaded": "starting", "disabled": "off", "absent": "not running"}[st],
                  "spark serve on" if st != "disabled" else "")
    h = wire.health(url)
    host = url.split("//")[-1].split(":")[0]
    if h == "ok":
        ip = lan_ip()
        if ip and host not in (ip, "127.0.0.1", "localhost"):
            return warn("serving on %s, but this machine is %s now" % (host, ip),
                        "spark serve off; spark serve on" if st == "absent" else engine.restart_line("serve"))
        try:
            served = wire.models(ctx.cfg, url)
        except wire.BrainError:
            served = []
        names = []
        for a, s, _l in sorted(served, key=lambda x: x[0] != "spark"):
            n = config.model_name(s)
            if n not in names:
                names.append(n)
        where = "at %s, %s" % (url.split("//")[-1], " and ".join(names) or "no model listed")
        argv = engine.live_args(ctx.cfg)
        if argv is None:
            return ok(where)
        cache = engine.host_cache(argv)
        if cache == "0" or (cache and "--cache-ram" in ctx.cfg.extra_args):
            return ok(where)
        return warn(where + ", started with old settings",
                    "spark serve off; spark serve on" if st == "absent" else engine.restart_line("serve"))
    if h == "loading":
        return warn("loading the model -- ask again in a moment")
    return warn("nothing answers at %s" % url.split("//")[-1], "spark serve off")


def _page_restart(ctx):
    """The page alone restarted: its unit by its init's own line (the
    engine and spark.env untouched); a page by hand has no unit, so the
    one verb that starts it again."""
    from . import engine
    if engine.forge_service_state(ctx.cfg) == "absent":
        return "spark serve off; spark serve on"
    return engine.restart_line("forge")


@row("CAPABILITY")
def row_forge(ctx):
    from . import engine, forge_url, lan_ip, wire
    url = forge_url()
    if not url:
        if ctx.cfg.forge == "off":
            return na("off", "spark serve on")
        return na("not started", "spark serve on")
    problems, loose = [], []
    tok = ctx.cfg.forge_token_file
    if not os.path.exists(tok) or os.stat(tok).st_mode & 0o077:
        problems.append("its token is not private")
        loose.append(ctx.short(tok))
    if "0.0.0.0" in url:
        problems.append("open on every address")
    if problems:
        return warn("; ".join(problems), "chmod 600 %s; %s"
                    % (" ".join(loose or [ctx.short(ctx.cfg.forge_token_file)]), _page_restart(ctx)))
    where = url.split("//")[-1]
    host = where.split(":")[0]
    fh = wire.forge_health(url, timeout=2)
    if isinstance(fh, dict):
        ip = lan_ip()
        if ip and host not in (ip, "127.0.0.1", "localhost"):
            return warn("serving on %s, but this machine is %s now" % (host, ip), _page_restart(ctx))
        up = fh.get("upstream") or "down"
        if up != "ok":
            return warn("at %s, but the engine is %s" % (where, up), "spark serve on")
        # a converge that moved the tree leaves the unit serving the OLD
        # code with every row green: the health's version must match
        ver, mine = str(fh.get("version") or ""), version.version()
        if ver and mine and ver != mine:
            return warn("the page runs %s, spark is %s" % (ver, mine), _page_restart(ctx))
        return ok("at %s, %s" % (where, config.model_name(str(fh.get("model") or "-"))))
    if fh is None:
        return warn("something else answers at %s" % where, _page_restart(ctx))
    return warn("nothing answers at %s" % where, "spark serve on")


@row("CAPABILITY")
def row_ember(ctx):
    from . import engine, mem_total_gb, wire
    pair = engine.chosen_rows(ctx.cfg)
    er = pair.get("ember")
    if ctx.cfg.ember_model == "none" or not er:
        return na("no chat model", "spark model --chat NAME")
    budget = mem_total_gb() * ctx.cfg.ai_budget / 100.0
    need = er[5] + (pair["spark"][5] if pair.get("spark") else 0.0)
    name = er[0]
    if need > budget:
        return warn("the two models need %.0f GB, the budget is %.0f GB" % (need, budget),
                    "spark model --chat list")
    if not engine.model_file(ctx.cfg, "ember"):
        return warn("%s not downloaded" % name, "spark update")
    url = wire.serve_url()
    if url and wire.health(url) == "ok":
        st = engine.models_status(ctx.cfg, url).get("ember")
        if st and st != "loaded":
            return warn("%s not loaded" % name, "spark serve on")
        if st == "loaded":
            return ok("%s, loaded" % name)
    return ok(name)


@row("CAPABILITY")
def row_peer(ctx):
    from . import wire
    parts, worst, remedy = [], OK, ""
    if ctx.cfg.peer_ai_url:
        # a FORGE answers /api/health (and 404 to /health); a raw llama-server the reverse
        host = ctx.cfg.peer_ai_url.split("//")[-1]
        fh = wire.forge_health(ctx.cfg.peer_ai_url, cfg=ctx.cfg)
        if isinstance(fh, dict):
            up = fh.get("upstream", "down")
            h = "ok" if up == "ok" else "up, its model %s" % up
            parts.append("%s %s" % (host, h))
            wire.note_peer(ctx.cfg, ctx.cfg.peer_ai_url, "spark")
        else:
            h = "down" if fh == "down" else wire.health(ctx.cfg.peer_ai_url)
            if h in ("ok", "loading"):
                wire.note_peer(ctx.cfg, ctx.cfg.peer_ai_url, "engine")
            # the user's own llama-server is named as theirs
            parts.append("%s %s %s" % ("your engine" if wire.plain(ctx.cfg) else "engine", host, h))
        if h != "ok":
            worst = WARN
        elif isinstance(fh, dict) and ctx.cfg.client:
            # a client of a FORGE keeps its threads under the login the
            # FORGE minted (a client never mints): say whether it holds
            from . import users
            me = users.account()[0]
            if not me:
                parts.append("no login")
                worst, remedy = WARN, "spark user add NAME on %s, then spark user login NAME" % host
            else:
                st = ctx.cached("peer-login", 300, lambda: _peer_status(ctx.cfg, "/api/threads?n=1"))
                if st in (401, 403):
                    parts.append("login %s refused" % me)
                    worst, remedy = WARN, "spark user add %s on %s, then spark user login %s" % (me, host, me)
                elif st == 200:
                    parts.append("login %s accepted" % me)
    if ctx.cfg.peer_ssh:
        def probe():
            rc, _ = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", ctx.cfg.peer_ssh, "true"], timeout=10)
            return rc
        rc = ctx.cached("peer-ssh", 300, probe)
        parts.append("ssh %s %s" % (ctx.cfg.peer_ssh, "answers" if rc == 0 else "unreachable"))
        if rc != 0:
            worst = WARN
    if not parts:
        return na("no other machine named")
    return Row(worst, SEP.join(parts), remedy if worst == WARN else "")


def _peer_status(cfg, path):
    """The HTTP status of one GET at the peer FORGE as this machine's
    login (0 when it does not answer): 200 accepted, 401 rejected."""
    import urllib.error
    import urllib.request
    from . import users
    token = users.account()[1]
    try:
        req = urllib.request.Request(cfg.peer_ai_url.rstrip("/") + path,
                                     headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


@row("CAPABILITY", fixture=False, reason="probes the live forge (tests/forge_probe.py proves the gates against a real server)")
def row_hardening(ctx):
    """Contract 9's gates, asked from the wire (wire.probe_gates) of the
    FORGE this machine serves, or of the peer on a client: the health
    line, the page's four headers, the write gate, the bare 401, the
    bearer-only model route. na when there is neither or it is down (the
    forge and peer rows say that already); a gate that does not hold is
    named, never a fail. Cached an hour: the probes are lines in the
    forge's log, and the timer asks every five minutes."""
    from . import forge_url, wire
    url = forge_url() if not ctx.cfg.client else ""
    if not url:
        url = ctx.cfg.peer_ai_url
    if not url:
        return na("no page served here")
    where = url.split("//")[-1].rstrip("/")
    if not isinstance(wire.forge_health(url), dict):
        return na("no page answers at %s" % where)
    v = ctx.cached("hardening", 3600, lambda: {"url": url, "gates": wire.probe_gates(url)})
    if not isinstance(v, dict) or v.get("url") != url:     # a moved forge: ask it now, cached next run
        v = {"url": url, "gates": wire.probe_gates(url)}
    gates = [tuple(g) for g in v.get("gates") or []]
    held = [g for g in gates if g[1]]
    if len(held) != len(gates) or not gates:
        broken = [g for g in gates if not g[1]] or [("probe", False, "no gates answered")]
        return warn("%d of %d safety checks pass at %s: %s" % (len(held), len(gates), where,
                                                                "; ".join("%s: %s" % (g[0], g[2]) for g in broken[:3])),
                    _page_restart(ctx))
    return ok("%d of %d safety checks pass at %s" % (len(held), len(gates), where))


@row("CAPABILITY", fixture=False, reason="runs one real sandboxed step (bwrap or sandbox-exec); tests/sandbox_test.py proves it")
def row_sandbox(ctx):
    """spark do --sandbox's containment, proven by one real step
    (sandbox.probe: a write in the copy lands, a write outside, the home
    and the network do not): `bwrap X overlay` on Linux, `sandbox-exec`
    on macOS, else na with the first line of why. Cached until bwrap's
    version, the kernel or the AppArmor userns switch changes. A
    capability: plain `spark do` works without it, so never a warn."""
    from . import sandbox
    good, detail = sandbox.probe(fresh=ctx.fresh)
    if good:
        return ok(detail)
    return na(detail, sandbox.install_hint())


@row("CAPABILITY")
def row_voice(ctx):
    """spark voice: off is na, its remedy the clear voice. On or clear,
    the engine and its models are here and are voice.env's pins (each
    part's sha file holds the pin's sha256), a player is on PATH, the
    listener is there; on needs the voice spark awaken kept. A screen
    reader running is noted: clear stays silent beside it. A capability:
    never fail."""
    from . import voice
    s = voice.status(ctx.cfg, ctx.repo)
    m = s["mode"]
    if m == "off":
        return na("off", "spark voice clear   (reads aloud)")
    if not s["pinned"]:
        return warn("%s, but there is no voice download for this machine" % m)
    if s["missing"]:
        return warn("%s, but parts are missing: %s (%d MB)" % (m, ", ".join(s["missing"]), s["missing_mb"]),
                    "spark voice %s" % m)
    if not s["player"]:
        return warn("%s, but nothing here can play sound" % m, packages.install_line(["alsa-utils"]))
    if m == "on" and not s["recipe"]:
        return warn("on, but no voice of its own yet", "spark awaken")
    said = "%s, plays with %s" % (m, s["player"])
    if not IS_MAC and not s["capture"]:
        said += ", no microphone"
    if s["reader"] and m == "clear":
        said += "; %s reads, so spark %s" % (s["reader"], "speaks too" if s["anyway"] else "stays silent")
    elif s["reader"]:
        said += "; %s runs too" % s["reader"]
    return ok(said)


@row("CAPABILITY")
def row_throughput(ctx):
    from . import bench, engine, stats
    # anchor on the model(s) served NOW, not on whatever recent turns
    # happen to be: right after `spark model NAME` the recent turns are
    # still the old model, and a row that reads them names a model the
    # box no longer serves (a stale gemma after a switch to qwen). The
    # live stems come from the config -- spark, and ember when it is set.
    live = []
    for role in engine.ROLES:
        f = engine.model_file(ctx.cfg, role)
        stem = os.path.basename(f)
        stem = stem[:-5] if stem.endswith(".gguf") else stem
        if stem and stem not in live:
            live.append(stem)
    # the prompt line's pace, when spark bench --line measured one: said
    # beside the tok/s, never judged -- the status stays the tok/s one's
    lp = bench.line_pace()
    tail = ("; the line in %.1f s" % (lp.get("ready_ms", 0) / 1000.0)) if lp else ""
    if not live:
        return na("no model served here")
    base = bench.baseline(ctx.cfg)
    if not base:
        return na("not measured yet", "spark bench")
    # recent turns only for a live model -- a turn naming a model no
    # longer served says nothing about the throughput now, and is
    # dropped; a turn with no model field (an old record) counts toward
    # the primary live model
    recent = [t for t in stats.turns(7)
              if t.get("tg_tps") and t.get("model", live[0]) in live][-10:]
    groups = {}
    for t in recent:
        groups.setdefault(t.get("model") or live[0], []).append(t)
    parts, slow = [], []
    for stem in live:
        name = config.model_name(stem)
        b = bench.baseline_stem(stem)
        if b is None or not b.get("tg"):
            parts.append("%s not measured" % name)
            continue
        ts = groups.get(stem, [])
        if len(ts) < 3:
            parts.append("%s %.1f tok/s" % (name, b["tg"]))
            continue
        mean = sum(t["tg_tps"] for t in ts) / len(ts)
        parts.append("%s %.1f tok/s, measured %.1f" % (name, mean, b["tg"]))
        if mean < 0.7 * b["tg"]:
            slow.append(stem)
    if slow:
        return warn("%s: slower than measured" % "; ".join(parts),
                    "spark bench tune show; spark bench tune")
    return ok("; ".join(parts) + tail)


@row("CAPABILITY")
def row_gpu(ctx):
    from . import engine
    g = engine.gpu_info()
    build = engine.backend(ctx.cfg)
    if not g:
        if IS_MAC:
            return na("%s; macOS shows no GPU numbers" % build)
        if is_wsl():
            return na("%s; WSL 2 does not reach the GPU" % build)
        return na("%s; no GPU numbers here" % build)
    node = "/dev/dri/renderD128"
    if not IS_MAC and os.path.exists(node) and not os.access(node, os.R_OK | os.W_OK):
        # runit: the services take their groups from runsvdir-USER when it
        # starts, not from a login -- a new login changes nothing for them
        runit = init_shape() == "runit"
        again = ("sudo sv restart runsvdir-%s" % (os.environ.get("USER") or ctx.cfg.user)
                 if runit else "log out of every session and in again")
        if engine.render_wrap(["x"])[0] == "sg":
            return ok("GPU in use")
        return warn("the GPU is not yours to use: new servers use the CPU",
                    "spark update; then " + again)
    files = [f for f in engine.roles(ctx.cfg).values() if f and os.path.isfile(f)]
    size = sum(os.path.getsize(f) for f in files)
    vram = g.get("vram_total", 0)
    if size and vram and size > vram:
        word = "the models" if len(files) > 1 else "the model"
        return warn("%s %.1f GB, the GPU %.1f GB: it spills to slower memory" % (word, size / 2**30, vram / 2**30),
                    "raise the UMA frame buffer in the BIOS, then spark bench")
    chosen = " (SITE_AI_BUILD=%s)" % ctx.cfg.ai_build if ctx.cfg.ai_build in ("cpu", "vulkan") else ""
    return ok("%s, %.1f GB, %d%% busy, %s%s" % (
        g.get("name", "gpu"), vram / 2**30, g.get("busy", 0), build, chosen))



@row("CAPABILITY")
def row_soul(ctx):
    from . import SOUL_FILE, soul
    problems = []
    try:
        st = os.stat(SOUL_FILE)
    except OSError:
        st = None
    if st is None and not ctx.cfg.persona_extra.strip():
        return na("built in", "spark soul edit")
    if st is not None and st.st_mode & 0o044:
        problems.append("readable by others")
    n = 0
    if st is not None:
        try:
            with open(SOUL_FILE, encoding="utf-8", errors="replace") as f:
                n = len(f.read().strip())
        except OSError:
            n = 0
        if n > soul.SOUL_MAX:
            problems.append("%d characters, cut at %d" % (n, soul.SOUL_MAX))
    if ctx.cfg.persona_extra.strip():
        problems.append("SPARK_PERSONA_EXTRA still set")
    if problems:
        return warn("; ".join(problems), "chmod 600 %s; spark soul edit" % ctx.short(SOUL_FILE))
    return ok("yours, %d characters" % n)


@row("CAPABILITY")
def row_look(ctx):
    """The living prompt: na until spark awaken; awake, the look file the
    hooks read must be what spark.env and the faces file say now, and
    every line of the faces file one spark would draw."""
    from . import look
    if not look.awake():
        return na("not awake", "spark awaken")
    bad = look.refused()
    if bad:
        name, n = bad[0]
        more = " and %d more" % (len(bad) - 1) if len(bad) > 1 else ""
        return warn("line %d of the %s file%s cannot print" % (n, name, more), "spark awaken")
    try:
        with open(look.LOOK_FILE, encoding="utf-8") as f:
            have = f.read()
    except OSError:
        have = ""
    if have != look.content(ctx.cfg, True):
        return warn("out of date", "spark look")
    return ok("awake: look %s, height %d" % (look.setting(ctx.cfg), look.height(ctx.cfg)))


@row("CAPABILITY")
def row_memory(ctx):
    from . import MEMORY_FILE, memory
    if not ctx.cfg.memory:
        return na("off", "spark memory on")
    sealed = memory.sealed_exists()
    try:
        st = os.stat(MEMORY_FILE)
    except OSError:
        st = None
    if st is None and not sealed:
        return ok("empty")
    problems = []
    if st is not None and st.st_mode & 0o044:
        problems.append("readable by others")
    if st is not None and sealed:
        problems.append("an old plain copy beside it")
    facts = memory._all_facts()
    if len(facts) > memory.FACTS_MAX:
        problems.append("%d facts, %d are sent" % (len(facts), memory.FACTS_MAX))
    if any(len(f) > memory.FACT_MAX for f in facts):
        problems.append("a fact over %d characters is cut" % memory.FACT_MAX)
    if sum(len(f) for f in facts) > memory.TOTAL_MAX:
        problems.append("%d characters, %d are sent" % (sum(len(f) for f in facts), memory.TOTAL_MAX))
    if problems:
        return warn("; ".join(problems), "chmod 600 %s; spark memory forget N" % ctx.short(MEMORY_FILE))
    return ok("%d fact%s%s" % (len(facts), "" if len(facts) == 1 else "s", ", sealed" if sealed else ""))


@row("CAPABILITY")
def row_ledger(ctx):
    """The ledger: what you have already weighed, sealed in the account's
    store -- one file, one record shape, and a rule per contract
    (ledger.RULES). The promise is that it is yours alone and that it
    does not grow without bound: sealed, 0600, and inside the caps."""
    from . import ledger, vault
    path = ledger.path()
    if not path or not os.path.exists(path):
        return ok("empty")
    st = os.stat(path)
    problems = []
    if st.st_mode & 0o077:
        problems.append("not 0600")
    if not vault.is_sealed(path):
        problems.append("plaintext, not sealed")
    if problems:
        return warn("%s: %s" % (ctx.short(path), "; ".join(problems)), "chmod 600 %s" % ctx.short(path))
    try:                        # a writer refuses a file that does not open: say so here first
        ledger._load(strict=True)
    except ledger.Refused as e:
        return warn("%s does not open" % ctx.short(path), e.hint)
    counts = ledger.counts()
    total = sum(counts.values())
    if total > ledger.TOTAL_MAX:
        return warn("%d records, %d are kept" % (total, ledger.TOTAL_MAX),
                    "spark edit --ledger clear; spark ask --ledger clear; spark read --ledger clear")
    if not total:
        return ok("empty, sealed")
    return ok("%d note%s, sealed" % (total, "" if total == 1 else "s"))


def _read_ago(seconds):
    """read 5 min ago / read 3 hours ago / read 2 days ago -- an age in
    whole units, as a person says it (the knowledge row)."""
    m = max(0, int(seconds)) // 60
    if m < 1:
        return "read just now"
    if m < 60:
        return "read %d min ago" % m
    for n, one in ((m // 1440, "day"), (m // 60, "hour")):
        if n >= 1:
            return "read %d %s%s ago" % (n, one, "" if n == 1 else "s")


# the kinds the row names, in its words: what a person recognises
KNOWLEDGE_KINDS = (("program", "program"), ("manual", "manual"))


@row("CAPABILITY")
def row_knowledge(ctx):
    """The index the prompt line checks its answers against: this machine's
    programs, their manuals, its apps and spark's own verbs, read by
    intake. The timer's unattended check keeps it fresh (every 5 minutes):
    an index that exists is refreshed within a 5-second slice, and a lock
    held by another refresh only reports. A check a person typed only
    reports (G0 M7: no manual is read and no --help runs on a person's own
    command), and a missing index is never built here -- bootstrap builds
    it -- so --porcelain stays fast. Stale is the question bootstrap's
    row asks (intake.fresh), so the remedy heals it. What a build left
    for the timer (intake.waiting) is ok, in words."""
    if not ctx.cfg.knowledge:
        return na("off (SPARK_KNOWLEDGE=off)")
    from . import intake
    fix = "spark update"
    counts, built, stale, _skipped = intake.status()
    if built is not None and ctx.unattended:
        counts, built, stale, _skipped = intake.refresh(deadline=5)
    if built is None:
        return warn("not built yet", fix)
    ago = _read_ago(time.time() - built)
    if stale:
        return warn("%s, this machine changed since" % ago, fix)
    parts = ["%d %s%s" % (counts[k], word, "" if counts[k] == 1 else "s")
             for k, word in KNOWLEDGE_KINDS if isinstance(counts.get(k), int)]
    pending, partial = intake.waiting()
    if pending:
        parts.append("%d waiting their turn" % pending)
    elif partial:
        parts.append("still reading")
    return ok("%s, %s" % (", ".join(parts) or "empty", ago))


@row("CAPABILITY", fixture=False, reason="reads the live battery")
def row_battery(ctx):
    from . import bar
    b = bar._battery()
    if not b:
        return na("no battery")
    try:
        pct = int(b.rstrip(glyph("down") + "%").split("%")[0])
    except ValueError:
        return na(b)
    if b.endswith(glyph("down")) and pct < 20:
        return warn("%s and discharging" % b, "plug it in")
    return ok(b.replace(glyph("down"), "% discharging").replace("%%", "%") if glyph("down") in b else b + " on power")


@row("CAPABILITY", fixture=False, reason="reads the live filesystem")
def row_disk(ctx):
    u = shutil.disk_usage("/")
    free = u.free / 2**30
    if free < 5:
        return warn("%.0f GB free on / -- critical" % free, "du -sh ~/*")
    if free < 20:
        return warn("%.0f GB free on /" % free, "du -sh ~/*")
    return ok("%.0f GB free on /" % free)


# -------------------------------------------------------- NONFUNCTIONAL rows
def privacy_terms_file(cfg):
    """The local banned-word list: SPARK_PRIVACY_TERMS (env > file, like
    every key), else <config dir>/privacy-terms. User-owned, never committed."""
    from . import CONFIG_DIR
    return cfg.get("SPARK_PRIVACY_TERMS") or os.path.join(CONFIG_DIR, "privacy-terms")


def privacy_terms(cfg, repo=REPO):
    """The words the tree must not contain: the union of the repo's
    .privacy-terms (generic, tracked) and the local list, one per line,
    `#` comments and blanks dropped, deduped, order kept."""
    terms = []
    for path in (os.path.join(repo, ".privacy-terms"), privacy_terms_file(cfg)):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    w = line.split("#", 1)[0].strip()
                    if w and w not in terms:
                        terms.append(w)
        except OSError:
            pass
    return terms


@row("NONFUNCTIONAL")
def row_privacy(ctx):
    from . import CHAT_HISTORY_FILE, CONFIG_DIR, EMBER_TOKEN_FILE, SITE_ENV, THREADS_DIR, WIDGETS_DIR, cli, forge_url, wire
    problems = []
    if os.path.isdir(STATE_DIR) and os.stat(STATE_DIR).st_mode & 0o077:
        problems.append("state dir not 0700")
    tok = ctx.cfg.token_file
    if os.path.exists(tok) and os.stat(tok).st_mode & 0o077:
        problems.append("token not 0600")
    if os.path.exists(SITE_ENV) and os.stat(SITE_ENV).st_mode & 0o044:
        problems.append("site.env readable by others")
    loose = ""
    try:
        for name in os.listdir(THREADS_DIR):
            if os.stat(os.path.join(THREADS_DIR, name)).st_mode & 0o077:
                problems.append("threads not 0600")
                loose = "; chmod 600 %s/*" % ctx.short(THREADS_DIR)
                break
    except OSError:
        pass
    url = wire.serve_url()
    if url and "0.0.0.0" in url:
        problems.append("the engine bound to 0.0.0.0")
    furl = forge_url()
    if furl and "0.0.0.0" in furl:
        problems.append("the page's server bound to 0.0.0.0")
    ftok = ctx.cfg.forge_token_file
    if os.path.exists(ftok) and os.stat(ftok).st_mode & 0o077:
        problems.append("forge-token not 0600")
        loose = "; chmod 600 %s" % ctx.short(ftok) + loose
    if os.path.exists(EMBER_TOKEN_FILE) and os.stat(EMBER_TOKEN_FILE).st_mode & 0o077:
        problems.append("ember-token not 0600")
        loose = "; chmod 600 %s" % ctx.short(EMBER_TOKEN_FILE) + loose
    if os.path.exists(CHAT_HISTORY_FILE) and os.stat(CHAT_HISTORY_FILE).st_mode & 0o077:
        problems.append("chat-history not 0600")
        loose = "; chmod 600 %s" % ctx.short(CHAT_HISTORY_FILE) + loose
    cli.live_widgets()          # drops markers of dead shells
    terms = privacy_terms(ctx.cfg, ctx.repo)
    if terms:
        rc, out = ctx.sh(["git", "-C", ctx.repo, "grep", "-i", "-l", "-w", "-E", "|".join(terms), "--", ".", ":(exclude).privacy-terms"], 20)
        if rc == 0 and out.strip():
            problems.append("banned words in %s" % " ".join(out.split()[:3]))
    if problems:
        fix = "chmod 700 %s; chmod 600 %s %s%s" % (ctx.short(STATE_DIR), ctx.short(tok), ctx.short(SITE_ENV), loose)
        return warn("; ".join(problems), fix)
    # a word list is the maintainer's tool, not a promise to a new user:
    # none is fine, and the row says nothing of it
    return ok("files private" + (", %d words watched" % len(terms) if terms else ""))


@row("NONFUNCTIONAL")
def row_sends(ctx):
    """What left this machine today, by destination, from the turn
    records (`out_bytes`, `dest`: a count and a host, never a word). The
    promise is that spark sends only to the server you named: local, the
    peer, the FORGE or the engine served here, SPARK_BASE_URL. Bytes to
    any other host are a warn, never a fail -- the records say where
    they went, and `spark stats --sends` shows the days."""
    from . import forge_url, stats, wire
    today = time.strftime("%Y-%m-%d")
    rows = stats.sends([t for t in stats.turns(1) if str(t.get("ts", "")).startswith(today)])
    if not rows:
        return ok("nothing sent today")
    known = {"local"} | {wire.dest_of(u) for u in (ctx.cfg.base_url, ctx.cfg.prefer_url, ctx.cfg.peer_ai_url,
                                                  forge_url(), wire.serve_url()) if u}
    strange = [(dest, b) for _day, dest, b, _n in rows if dest not in known]
    if strange:
        dest, b = strange[0]
        return warn("%s went to %s today, not the address you configured" % (stats.kb(b), dest),
                    "spark stats --sends")
    return ok(", ".join("%s to %s" % (stats.kb(b), dest) for _day, dest, b, _n in rows) + " today")


@row("NONFUNCTIONAL")
def row_users(ctx):
    """The named users' sealed stores: every dir 0700, every key file
    0600, every data file (threads/ and kept/ included) carrying the
    sealed magic, the local login consistent. The promise is `eyes only to the owner`; a plaintext file
    inside a user's store is the drift this row exists to catch."""
    from . import ACCOUNT_FILE, ACCOUNT_KEY_FILE, USERS_DIR, users, vault
    names = users.list_users()
    me = users.account()[0]
    if not names and not me:
        return na("no users yet", "spark user add NAME")
    if not names:
        return ok("logged in as %s" % me)
    problems, unsealed = [], 0
    if os.stat(USERS_DIR).st_mode & 0o077:
        problems.append("users dir not 0700")
    for n in names:
        d = os.path.join(USERS_DIR, n)
        if os.stat(d).st_mode & 0o077:
            problems.append("%s: dir not 0700" % n)
        for fn in ("token.hash", "key"):
            p = os.path.join(d, fn)
            if not os.path.isfile(p):
                problems.append("%s: no %s" % (n, fn))
            elif os.stat(p).st_mode & 0o077:
                problems.append("%s: %s not 0600" % (n, fn))
        data = []
        for sub in ("threads", "kept"):      # kept/: the threads SPARK_HISTORY never ages
            try:
                data += [os.path.join(d, sub, f) for f in os.listdir(os.path.join(d, sub))]
            except OSError:
                pass
        data += [os.path.join(d, f) for f in ("memory", "chat-history", "ledger")]
        for p in data:
            if os.path.isfile(p):
                if not vault.is_sealed(p):
                    unsealed += 1
                if os.stat(p).st_mode & 0o077:
                    problems.append("%s: store file not 0600" % n)
    if unsealed:
        problems.append("%d plaintext file%s inside a sealed store" % (unsealed, "" if unsealed == 1 else "s"))
    legacy = users.legacy_threads()
    if legacy:
        problems.append("%d pre-v1.4 plaintext thread%s" % (legacy, "" if legacy == 1 else "s"))
    from . import EMBER_TOKEN_FILE
    if os.path.exists(EMBER_TOKEN_FILE):
        problems.append("an old shared token is left")
    for p in (ACCOUNT_FILE, ACCOUNT_KEY_FILE):
        if os.path.exists(p) and os.stat(p).st_mode & 0o077:
            problems.append("%s not 0600" % os.path.basename(p))
    if me and not users.exists(me):
        problems.append("login %s has no user here" % me)
    if problems:
        if legacy:
            fix = "spark user claim"
        elif os.path.exists(EMBER_TOKEN_FILE):
            fix = "rm %s" % ctx.short(EMBER_TOKEN_FILE)
        else:
            fix = "chmod -R go-rwx %s" % ctx.short(USERS_DIR)
        return warn("; ".join(problems[:4]), fix)
    who = ("logged in as %s" % me) if me else "not logged in"
    return ok("%d user%s, sealed; %s" % (len(names), "" if len(names) == 1 else "s", who))


@row("NONFUNCTIONAL", fixture=False, reason="reads live swap use")
def row_swap(ctx):
    if IS_MAC:
        rc, out = ctx.sh(["sysctl", "-n", "vm.swapusage"], 5)
        if rc != 0:
            return na("unknown")
        used = re.search(r"used = ([\d.]+)M", out)
        return ok("%s MB in use" % (used.group(1) if used else "?"))
    total = free = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("SwapTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("SwapFree:"):
                    free = int(line.split()[1])
    except OSError:
        return na("unknown")
    if not total:
        return na("no swap")
    pct = 100 * (total - free) // total
    if pct > 50:
        return warn("%d%% of %d MB in use" % (pct, total // 1024), "spark serve off")
    return ok("%d%% of %d MB in use" % (pct, total // 1024))


@row("NONFUNCTIONAL", fixture=False, reason="reads the live disk layout")
def row_encryption(ctx):
    if IS_MAC:
        rc, out = ctx.sh(["fdesetup", "status"], 5)
        if rc == 0 and "On" in out:
            return ok("FileVault on")
        return warn("FileVault off", "System Settings > Privacy & Security > FileVault")
    if is_wsl():
        return na("WSL 2: BitLocker is Windows's to turn on")
    rc, out = ctx.sh(["lsblk", "-rno", "TYPE"], 5)
    if rc == 0 and "crypt" in out.split():
        return ok("disk encrypted (LUKS)")
    return warn("disk not encrypted", "reinstall with disk encryption")


@row("NONFUNCTIONAL", fixture=False, reason="reads live power and login settings")
def row_headless(ctx):
    """A box that is the brain keeps the FORGE up from boot with nobody logged
    in and never sleeps (SITE_HEADLESS=yes; bootstrap applies it)."""
    if not ctx.cfg.headless:
        if not IS_MAC and init_shape() == "runit":
            # runsvdir-USER is a root service: from boot, login or not
            return na("runs from boot (runit)")
        return na("off", "spark serve boot on")
    from . import site
    missing = [piece for piece, good, _ in site.headless_facts(ctx.cfg) if not good]
    if missing:
        return warn("missing: " + ", ".join(missing), "spark update")
    if IS_MAC:
        return ok("up from boot, never sleeps, wakes on LAN")
    if init_shape() == "runit":
        return ok("up from boot")
    return ok("up from boot, never sleeps")


@row("CAPABILITY", fixture=False, reason="reads the real spark group and the shared token; the group needs root to create")
def row_share(ctx):
    """This box's engine, shared with its other OS users: a `spark` group
    reads a 0640 copy of the api-token (SITE_SHARE=yes; spark serve share on).
    Never fails -- sharing is opt-in; a stale or mis-permissioned token warns."""
    from . import site
    if site.no_share():                                # macOS, WSL 2: not this machine's to share
        return na(site.no_share())
    if not ctx.cfg.share:
        return na("off", "spark serve share on")
    facts = site.share_facts(ctx.cfg)
    bad = [piece for piece, good, _ in facts if not good]
    if bad:
        return warn("not right: " + ", ".join(bad), "spark serve share on")
    return ok(next((d for piece, _g, d in facts if piece == "spark group"), "shared with the spark group"))


@row("NONFUNCTIONAL", fixture=False, reason="asks the package manager, cached an hour")
def row_pending(ctx):
    """What the package manager holds back, and how many of those are
    security upgrades (Debian's -security sources; arch-audit on Arch --
    absent, the value says so and nothing warns): one waiting is a warn
    with the family's upgrade line. macOS counts as before."""
    n = ctx.cached("pending", 3600, packages.pending)
    if n < 0:
        return na("could not ask the package manager")
    text = "%d updates pending" % n
    if packages.manager() in ("apt", "pacman"):
        sec = ctx.cached("security", 3600, packages.security)
        if sec is None:
            text += ", " + packages.SECURITY_UNNAMED
        elif sec < 0:
            text += ", security upgrades unknown"
        elif sec:
            return warn("%s, %d security" % (text, sec), packages.upgrade_line())
        else:
            text += ", none for security"
    if n > 30:
        return warn(text, packages.upgrade_line())
    return ok(text)


@row("NONFUNCTIONAL")
def row_watchdog(ctx):
    try:
        with open(CHECK_JSON, encoding="utf-8") as f:
            age = time.time() - json.load(f)["ts"]
    except (OSError, ValueError, KeyError):
        return na("not run yet")
    if age > 3 * 300:
        return warn("last run %d min ago: the timer is not running" % (age / 60), "spark update")
    return ok("last run %d s ago" % age)


@row("NONFUNCTIONAL", fixture=False, reason="measures this very run")
def row_cost(ctx):
    return ok("%d ms this run" % int((time.time() - ctx.started) * 1000))


# ------------------------------------------------------------------- runner
# the rows WSL 2 answers differently (na or a WSL 2 note, never a fault):
# the selftest's fourth pass, on Linux, proves each says so
WSL_ROWS = ("gpu",)
# the rows Arch answers differently (na or an Arch note, never a fault):
# none today. The selftest's fifth pass, on Linux, proves each says so
# and that the packages row answers through pacman
ARCH_ROWS = ()
# the rows Void answers differently (na or a Void note, never a fault):
# none today. The selftest's sixth pass, on Linux, proves each says so,
# that the packages row answers through xbps and the services row
# through sv
VOID_ROWS = ()
# the rows Fedora answers differently (na or a Fedora note, never a
# fault): none today. The selftest's seventh pass, on Linux, proves each
# says so and that the packages row answers through dnf's rpm
FEDORA_ROWS = ()
# the rows openSUSE answers differently (na or an openSUSE note, never a
# fault): none today. The selftest's eighth pass, on Linux, proves each
# says so and that the packages row answers through zypper's rpm
OPENSUSE_ROWS = ()
# a client's rows: nothing runs here (SITE_AI_MODEL=none + SITE_PEER_AI_URL),
# so the engine, the units, their snapshot, the local AI, its two servers and
# a second model of its own are na before they look; the peer row is where a
# client's health lives, and `spark model --chat list` shows what the peer offers
CLIENT_ROWS = ("engine", "services", "watchdog", "ai", "serve", "forge", "ember")


def client_of(cfg):
    from . import wire
    if wire.plain(cfg):
        return "your engine at %s answers (spark client off ends it)" % cfg.peer_ai_url.split("//")[-1]
    return "a client of %s (spark client off ends it)" % cfg.peer_ai_url.split("//")[-1]


def run_rows(ctx, names=None, tick=None):
    """Every row (or the named ones). tick(n, total), when given, is told
    before each row runs: the counter an awakened terminal draws."""
    ctx.started = time.time()
    rows = []
    specs = [s for s in SPECS if not names or s.name in names]
    for n, spec in enumerate(specs, 1):
        if tick is not None:
            tick(n, len(specs))
        try:
            if spec.name in CLIENT_ROWS and ctx.cfg.client:
                r = na(client_of(ctx.cfg))
            else:
                r = spec.fn(ctx)
        except SystemExit:
            raise
        except Exception as e:   # a crashed row is a red row, never a missing one
            log_exc("check row " + spec.name)
            r = fail("crashed: %s" % (str(e).splitlines() or ["?"])[0], "SPARK_DEBUG=1 spark check")

        if spec.category == "CAPABILITY" and r.status == FAIL:
            r.status = WARN
        r.name, r.category = spec.name, spec.category
        rows.append(r)
    return rows


def _tally(statuses):
    statuses = list(statuses)
    return {s: statuses.count(s) for s in (OK, FAIL, WARN, NA)}


def counts(rows):
    return _tally(r.status for r in rows)


# ------------------------------------------- the snapshot, history, alert
# One merge, under one flock, writes three files: check.json (every row's
# newest observation), check-history.jsonl (one line a status change) and
# alert (what the prompt says once). A change is read by row name on the
# STATUS alone, the stored row against the merged one: a value holds
# volatile numbers, and it may name a person or a host, so history keeps
# names, statuses and numbers only.
SEVERITY = {OK: 0, NA: 0, WARN: 1, FAIL: 2}
LOCK_WAIT = 2.0             # seconds a run waits for another run's merge
HISTORY_MAX = 2000          # records kept, whatever SPARK_HISTORY says
ALERT_MAX = 8               # lines in the alert file, one a row
ALERT_HOURS = 24            # a line is said for a day, then it is gone
ALERT_CHARS = 160           # a line's text, after cleaning
ALERT_REMEDY = 90           # a remedy longer than this is not said: `spark check ROW` shows it whole
# recorded, never said: both turn warn when the last shell closes
ALERT_QUIET = ("prompt", "failure")
# Rows that are red for a moment whenever a server starts or a model
# loads: after spark update, spark serve on, spark model NAME, a reboot.
# Their turn for the worse is held, and said only if the row is still red
# ALERT_SETTLE_SECONDS later. One that heals inside that time is never
# said. The history records both changes at once, as for any row.
ALERT_SETTLE = ("serve", "forge", "ember", "peer")
ALERT_SETTLE_SECONDS = 180
_ALERT_ROW = re.compile(r"[a-z]+\Z")
_ALERT_NUM = re.compile(r"[0-9]{1,12}\Z")
_ALERT_KINDS = {"!": "alarmed", "*": "pleased"}
_HISTORY_ROW = re.compile(r"[a-z][a-z-]{0,31}\Z")


def _int(v):
    """v as a whole number of seconds, or 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0
    try:
        return int(v)
    except (ValueError, OverflowError):
        return 0


def _take_lock(wait=None):
    """The check's flock (sandbox._open_lock: 0600, O_NOFOLLOW), or None
    when another run still holds it after `wait` seconds. The kernel lets
    go when the holder dies, so no stale lock outlives a killed run."""
    import fcntl
    from . import sandbox
    try:
        state_dir()
        fd = sandbox._open_lock(CHECK_LOCK)
    except OSError:
        return None
    end = time.monotonic() + (LOCK_WAIT if wait is None else wait)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= end:
                os.close(fd)
                return None
            time.sleep(0.05)


def read_snapshot():
    """check.json as a dict with a `rows` list, or None."""
    try:
        with open(CHECK_JSON, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("rows"), list):
        return None
    return d


def _stored(snap):
    """{name: row} of a snapshot's well-formed rows."""
    out = {}
    for r in snap.get("rows", []):
        if isinstance(r, dict) and isinstance(r.get("name"), str) and r.get("status") in SEVERITY:
            out[r["name"]] = r
    return out


def _history_days(cfg):
    """SPARK_HISTORY in days; 0 is off. A value that is no number is the
    default here: the check never dies of it."""
    try:
        return max(0, int(cfg.history))
    except (SystemExit, ValueError, TypeError):
        return 30


def write_snapshot(ctx, rows, full=True):
    """Merge this run's rows into check.json, record what changed and
    rewrite the alert file: one step under the check's flock, each file
    through its own atomic write. False when nothing was written (another
    run holds the lock, or a named run found no snapshot to merge into).

    Each stored row carries `at` (the start of the run that observed it),
    `since` (when its status last changed) and `red` (when it left ok or
    na; absent while it is ok or na). The newest observation of a row
    wins: a stored row observed after this run started is kept, so a slow
    run records no false heal and no stale break. A full run takes every
    row, drops the rows it did not run and sets `ts`. A named run replaces
    only its rows, counts again and keeps `ts`: the bar's age and the
    watchdog row go on meaning the last full run."""
    fd = _take_lock()
    if fd is None:
        return False
    try:
        return _merge(ctx, rows, full)
    except (OSError, ValueError, TypeError):
        log_exc("check snapshot")
        return False
    finally:
        os.close(fd)


def _merge(ctx, rows, full):
    from . import vault
    now = int(time.time())
    at = round(float(getattr(ctx, "started", now)), 3)
    prev = read_snapshot()
    if prev is None and not full:
        return False
    prev_ts = _int(prev.get("ts")) if prev else 0
    old = _stored(prev) if prev else {}
    merged = {} if full else dict(old)
    changes = []            # (name, from, to, red seconds or None, the Row)
    said, late = [], []     # the changes the prompt hears now; held ones whose time came
    for r in rows:
        was = old.get(r.name)
        # observed after this run started: it knows better. An `at` ahead
        # of the clock itself (the clock was set back) is no observation
        if was is not None and isinstance(was.get("at"), (int, float)) and at < was["at"] <= now + 1:
            merged[r.name] = was
            continue
        e = {"category": r.category, "status": r.status, "name": r.name,
             "value": r.value, "remedy": r.remedy, "at": at}
        same = was is not None and was["status"] == r.status
        # a row stored before v1.81 has no since and no red: its snapshot's ts
        e["since"] = (_int(was.get("since")) or prev_ts or now) if same else now
        was_red = was is not None and SEVERITY[was["status"]] > 0
        red_at = (_int(was.get("red")) or prev_ts or now) if was_red else now
        if SEVERITY[r.status]:
            e["red"] = red_at
        merged[r.name] = e
        # a settling row's held turn for the worse (ALERT_SETTLE): kept
        # while the row stays red, said once it has stayed red long enough
        held = _int(was.get("held")) if was is not None else 0
        if held and SEVERITY[r.status]:
            if now - held >= ALERT_SETTLE_SECONDS:
                late.append((r.name, OK, r.status, None, r))
            else:
                e["held"] = held
        if was is None or same:
            continue                    # a row never seen is the baseline
        a, b = SEVERITY[was["status"]], SEVERITY[r.status]
        if a or b:                      # ok <-> na is no change
            change = (r.name, was["status"], r.status, max(0, now - red_at) if a and not b else None, r)
            changes.append(change)
            if r.name in ALERT_SETTLE and not a and b:
                e["held"] = now         # red just now: wait and see
            elif not held:
                said.append(change)     # a held row's later changes are not said: its break never was
    if full:
        out = list(merged.values())
    else:
        order = {s.name: i for i, s in enumerate(SPECS)}
        out = sorted(merged.values(), key=lambda e: order.get(e["name"], len(order)))
    if full or prev is None:
        snap = {"ts": now, "name": ctx.cfg.name, "version": version.version()}
    else:
        snap = dict(prev)
    snap["counts"] = _tally(e["status"] for e in out)
    snap["rows"] = out
    # history and the alert first, the snapshot last: a run killed between
    # them says a change twice, never loses one
    days = _history_days(ctx.cfg)
    try:
        if days > 0 and changes:
            _history_append(changes, now)
        if full:
            _history_prune(days, now)
    except OSError:
        log_exc("check history")
    try:
        _alert_update(said + late, set(merged), now, full)
    except OSError:
        log_exc("check alert")
    vault.write_private(CHECK_JSON, json.dumps(snap).encode("utf-8"))
    return True


# ---- history
def _record(d):
    """A history line as its checked fields, or None: a row name, two
    statuses and whole numbers, whatever else the line holds."""
    if not isinstance(d, dict):
        return None
    ts, name, a, b = _int(d.get("ts")), d.get("row"), d.get("from"), d.get("to")
    if ts <= 0 or not isinstance(name, str) or not _HISTORY_ROW.match(name):
        return None
    if not isinstance(a, str) or not isinstance(b, str) or a not in SEVERITY or b not in SEVERITY:
        return None
    rec = {"ts": ts, "row": name, "from": a, "to": b}
    if "red" in d:
        rec["red"] = max(0, _int(d["red"]))
    return rec


def _history_read():
    """(records in file order, lines in the file)."""
    out, n = [], 0
    try:
        with open(CHECK_HISTORY, encoding="utf-8", errors="replace") as f:
            for line in f:
                n += 1
                try:
                    rec = _record(json.loads(line))
                except ValueError:
                    continue
                if rec:
                    out.append(rec)
    except OSError:
        pass
    return out, n


def read_history():
    """Every kept status change, oldest first."""
    return _history_read()[0]


def _history_lines(records):
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records).encode("ascii")


def _history_append(changes, now):
    recs = []
    for name, a, b, red, _r in changes:
        rec = {"ts": now, "row": name, "from": a, "to": b}
        if red is not None:
            rec["red"] = int(red)
        if _record(rec):
            recs.append(rec)
    if not recs:
        return
    fd = os.open(CHECK_HISTORY, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, _history_lines(recs))
    finally:
        os.close(fd)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _history_prune(days, now):
    """A full run's upkeep: history off removes the file; else a file
    whose first record is past the days kept, or that holds more than
    HISTORY_MAX lines, is written again without them."""
    if days <= 0:
        _remove(CHECK_HISTORY)
        return
    recs, n = _history_read()
    if not n:
        return
    cutoff = now - days * 86400
    if recs and recs[0]["ts"] >= cutoff and n <= HISTORY_MAX and n == len(recs):
        return
    keep = [r for r in recs if r["ts"] >= cutoff][-HISTORY_MAX:]
    if keep:
        from . import vault
        vault.write_private(CHECK_HISTORY, _history_lines(keep))
    else:
        _remove(CHECK_HISTORY)


def clear_history():
    """`spark clear --history`: the kept changes go. The snapshot and the
    alert file stay: they are the machine's state now, not its past."""
    fd = _take_lock()
    try:
        had = os.path.lexists(CHECK_HISTORY)
        _remove(CHECK_HISTORY)
        return had
    finally:
        if fd is not None:
            os.close(fd)


def _span(seconds):
    """21 min / 10 h / 3 days: how long, in the words the prompt says."""
    s = max(0, int(seconds))
    if s < 120:
        return "%d s" % s
    if s < 2 * 3600:
        return "%d min" % (s // 60)
    if s < 48 * 3600:
        return "%d h" % (s // 3600)
    return "%d days" % (s // 86400)


# ---- the alert file
def _fold(s):
    """One line: spark's own glyphs as their ASCII twins, whitespace runs
    as one space."""
    from . import _GLYPHS
    s = str(s)
    for uni, plain in _GLYPHS.values():
        if uni != plain:
            s = s.replace(uni, plain)
    return " ".join(s.split())


def _cut(s, n):
    """s within n characters, cut at a word."""
    if len(s) <= n:
        return s
    return s[:max(0, n - 3)].rsplit(" ", 1)[0].rstrip() + "..."


def _sayable(s):
    """look.clean's two rules at the alert's own length (its 72 columns
    are a face line's): printable ASCII and no secret shape."""
    if not s or s != s.strip() or len(s) > ALERT_CHARS or any(not (" " <= c <= "~") for c in s):
        return False
    from . import look
    if len(s) <= look.LINE_MAX:
        return look.clean(s) == s
    from . import text
    return not text.held_spans(s)[0]


def alert_text(name, text):
    """A text fit for the alert file: folded, cut at a word to ALERT_CHARS,
    printable ASCII with no secret shape. One that is not becomes `ROW
    needs you -- spark check ROW`, which names nothing."""
    s = _cut(_fold(text), ALERT_CHARS)
    # the row's name leads, not spark's: this is no signed line (contract 8)
    return s if _sayable(s) else "%s needs you" % name + " -- spark check %s" % name


def worse_text(r):
    """`ROW: VALUE -- REMEDY`: the remedy's command without its aside
    (chaos._command_of), or `spark check ROW` when the row names none or
    one past ALERT_REMEDY characters. A long value is cut, never the
    command: half a command is worse than none."""
    from . import chaos
    cmd = _fold(chaos._command_of(r.remedy or ""))
    if not cmd or len(cmd) > ALERT_REMEDY:
        cmd = "spark check %s" % r.name
    tail = " -- " + cmd
    return alert_text(r.name, _cut(_fold("%s: %s" % (r.name, r.value)), ALERT_CHARS - len(tail)) + tail)


def heal_text(name, red):
    return alert_text(name, "%s: ok again, after %s" % (name, _span(red)))


def read_alert():
    """The alert file's well-formed lines as dicts (seq, epoch, mark, mood,
    row, text), one a row, oldest first. A line that is not exactly the
    six fields, or whose text is not fit to say, is dropped."""
    try:
        with open(ALERT_FILE, encoding="ascii", errors="replace") as f:
            raw = f.read(1 << 14)
    except OSError:
        return []
    by = {}
    for line in raw.split("\n")[:4 * ALERT_MAX]:
        p = line.split(" ", 5)
        if len(p) != 6:
            continue
        seq, epoch, mark, mood, name, text = p
        if not _ALERT_NUM.match(seq) or not _ALERT_NUM.match(epoch) or _ALERT_KINDS.get(mark) != mood:
            continue
        if not _ALERT_ROW.match(name) or not _sayable(text):
            continue
        e = {"seq": int(seq), "epoch": int(epoch), "mark": mark, "mood": mood, "row": name, "text": text}
        if name not in by or by[name]["seq"] < e["seq"]:
            by[name] = e
    return sorted(by.values(), key=lambda e: e["seq"])


def _alert_body(lines):
    return "".join("%d %d %s %s %s %s\n" % (e["seq"], e["epoch"], e["mark"], e["mood"], e["row"], e["text"])
                   for e in lines)


def _alert_update(changes, names, now, full):
    """Apply a run's changes to the alert file. Worse (ok/na -> warn/fail,
    warn -> fail) is a new `!` line; a heal a new `*` line in its place;
    warn/fail -> na withdraws the row's line; fail -> warn refreshes the
    standing text and keeps its seq, since nothing new is said. Lines past
    ALERT_HOURS and lines of rows gone go. A seq only grows."""
    lines = read_alert()
    before = _alert_body(lines)
    exists = os.path.lexists(ALERT_FILE)
    by = {e["row"]: e for e in lines}
    top = max([e["seq"] for e in lines] or [0])
    for name, was, to, red, r in changes:
        if name in ALERT_QUIET or not _ALERT_ROW.match(name):
            continue
        a, b = SEVERITY[was], SEVERITY[to]
        if b > a:
            top = max(top + 1, now)
            by[name] = {"seq": top, "epoch": now, "mark": "!", "mood": "alarmed", "row": name, "text": worse_text(r)}
        elif to == OK:
            top = max(top + 1, now)
            by[name] = {"seq": top, "epoch": now, "mark": "*", "mood": "pleased", "row": name,
                        "text": heal_text(name, red or 0)}
        elif b == 0:
            by.pop(name, None)
        elif name in by and by[name]["mark"] == "!":
            by[name]["text"] = worse_text(r)
    keep = [e for e in by.values()
            if e["row"] in names and e["row"] not in ALERT_QUIET and abs(now - e["epoch"]) < ALERT_HOURS * 3600]
    keep = sorted(keep, key=lambda e: e["seq"])[-ALERT_MAX:]
    keep = [e for e in keep if e["seq"] < 10 ** 12]
    if not keep:
        if exists:
            _remove(ALERT_FILE)
        return
    body = _alert_body(keep)
    if full or body != before:
        from . import vault
        vault.write_private(ALERT_FILE, body.encode("ascii"))


# ---- spark check --history
def show_history(name="", porcelain_out=False):
    """`spark check --history [NAME] [--porcelain]`: the kept changes,
    newest first. It runs no row and writes nothing."""
    days = _history_days(config.load())
    if days <= 0:
        # porcelain keeps stdout for records alone
        print("%s check -- history is off (SPARK_HISTORY)" % MARK, file=sys.stderr if porcelain_out else sys.stdout,
              flush=True)
        return 0
    now = time.time()
    recs = [r for r in read_history() if r["ts"] >= now - days * 86400 and (not name or r["row"] == name)]
    recs = sorted(recs, key=lambda r: r["ts"])[::-1]
    if porcelain_out:
        if recs:
            say("\n".join("%d\t%s\t%s\t%s\t%s" % (r["ts"], r["row"], r["from"], r["to"], r.get("red", ""))
                          for r in recs))
        return 0
    snap = read_snapshot()
    red_now = {n: _int(e.get("red")) for n, e in (_stored(snap) if snap else {}).items()
               if SEVERITY[e["status"]] and _int(e.get("red"))}
    wide = max([9] + [len(r["row"]) for r in recs])
    out, seen = [], set()
    for r in recs:
        note = ""
        if "red" in r:
            note = "red %s" % _span(r["red"])
        elif r["row"] not in seen and SEVERITY[r["to"]] and r["row"] in red_now:
            note = "still red, %s" % _span(now - red_now[r["row"]])
        seen.add(r["row"])
        out.append(("%s  %-*s  %-12s  %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])), wide, r["row"],
                                             "%s -> %s" % (r["from"], r["to"]), note)).rstrip())
    if recs:
        out.append("%s %d change%s in %d day%s" % (glyph("hammer"), len(recs), "" if len(recs) == 1 else "s",
                                                   days, "" if days == 1 else "s"))
    else:
        out.append("%s no changes kept in %d day%s" % (glyph("hammer"), days, "" if days == 1 else "s"))
    page("\n".join(out))
    return 0


# the rows that need the user: what bare `spark check` prints. An ok row
# needs nothing, and an na row is a capability this machine does not
# have or does not use -- `spark check --all` shows both
NEEDS_YOU = (WARN, FAIL)


def needs_you(rows):
    """The rows a person has to act on, in the report's order."""
    return [r for r in rows if r.status in NEEDS_YOU]


def render(ctx, rows, color, roles=False, every=False, named=False):
    """The report. Bare (every=False), the rows that need the user with
    their remedies, then the totals line: a machine with nothing to fix
    prints the totals alone. every=True is the whole report, the header
    and every row by category (`--all`). named=True (rows named on the
    line) shows each of those rows, ok or not, and the totals. color paints it at a terminal:
    the fixed 32/33/31/2 unawakened; roles=True (awakened, the colour part
    active) through the six roles instead -- ok, warn, trouble for a
    failed row, muted for na and the remedy's arrow -- the remedy's words
    in the normal colour."""
    c = counts(rows)

    def paint(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color and code else s
    code = dict(COLOR)
    arrow = "2"
    if roles:
        from . import sgr
        code = {OK: sgr("ok"), WARN: sgr("warn"), FAIL: sgr("trouble"), NA: sgr("muted")}
        arrow = sgr("muted")

    def line(r):
        out.append("  %s %-11s %s" % (paint(code[r.status], GLYPH[r.status]), r.name, r.value))
        if r.remedy and r.status != OK:
            out.append("    %s %s" % (paint(arrow, glyph("arrow")), r.remedy))
    out = []
    if every:
        where = ctx.cfg.name + (SEP + "WSL 2" if is_wsl() else "")
        out.append("%s check %s%son %s%s%s" % (paint("1", MARK), version.version(), SEP, where, SEP,
                                              time.strftime("%Y-%m-%d %H:%M")))
        for cat in CATEGORIES:
            rs = [r for r in rows if r.category == cat]
            if not rs:
                continue
            out.append(paint("1", cat))
            for r in rs:
                line(r)
    else:
        for r in (rows if named else needs_you(rows)):
            line(r)
    out.append("%s %d  %s %d  %s %d  %s %d" % (paint(code[OK], GLYPH[OK]), c[OK], paint(code[FAIL], GLYPH[FAIL]), c[FAIL],
                                                paint(code[WARN], "!"), c[WARN], paint(code[NA], GLYPH[NA]), c[NA]))
    return "\n".join(out)


class Counter:
    """`checking N/M` on stderr while the rows run, redrawn in place and
    cleared before the report: an awakened terminal whose motion part is
    active, never a pipe. Where the words part is active too the thinking
    face leads it, a frame a row: `(o.O) checking 3/42`."""

    def __init__(self, stream):
        self.stream = stream
        self.drawn = False
        self.anim = None
        try:
            from . import look
            if look.active("motion", stream) and look.active("words", stream):
                self.anim = look.Anim()
        except Exception:       # noqa: BLE001 -- the counter is never a reason to fail
            self.anim = None

    def __call__(self, n, total):
        try:
            from . import paint
            face = paint(self.anim.face("thinking", n), "accent", self.stream) + " " if self.anim else ""
            self.stream.write("\r\033[2K%schecking %d/%d" % (face, n, total))
            self.stream.flush()
            self.drawn = True
        except (OSError, ValueError):
            pass

    def clear(self):
        if self.drawn:
            try:
                self.stream.write("\r\033[2K")
                self.stream.flush()
            except (OSError, ValueError):
                pass
            self.drawn = False


def porcelain(rows):
    return "\n".join("%s\t%s\t%s\t%s\t%s" % (r.category, r.status, r.name, r.value, r.remedy) for r in rows)


def report(ctx, rows):
    """The block a user pastes into an issue: version, OS and family,
    arch, backend, RAM and budget, the model stems, then every row's
    category, status and name -- never a value, a path, a hostname or a
    user name. Its own output then runs through the privacy word lists
    (the repo's and the personal file) and every hit is blanked, so
    even an accident cannot leak a listed word."""
    import platform
    from . import engine, mem_total_gb, os_pretty, version
    cfg = ctx.cfg
    fam = distro() or ("wsl" if is_wsl() else "-")
    lines = ["spark %s" % version.version(),
             "%s (%s), %s" % (os_pretty(), fam, platform.machine()),
             "backend %s, ram %.0f GB, budget %d%%" % (engine.backend(cfg), mem_total_gb(), cfg.ai_budget)]
    try:
        pair = engine.chosen_rows(cfg)
    except SystemExit:
        pair = {}
    stems = ", ".join("%s %s" % (role, (pair.get(role)[1].replace(".gguf", "") if pair.get(role) else "none"))
                      for role in ("spark", "ember"))
    lines.append("models: " + stems)
    for r in rows:
        lines.append("%-13s %-4s %s" % (r.category, r.status, r.name))
    text = "\n".join(lines)
    for w in privacy_terms(cfg, ctx.repo):
        if len(w) >= 2:
            text = re.sub(re.escape(w), "*" * min(len(w), 6), text, flags=re.I)
    return text


# ----------------------------------------------------------------- selftest
_STUB_BOOTSTRAP = """#!/bin/sh
case ${1:-} in
  --list-packages) printf 'bash\\ngit\\n' ;;
  --list-tools) printf 'bin/spark\\tspark\\nbin/explain\\texplain\\n' ;;
  --list-models) printf 'none\\n' ;;
  *) echo "Nothing to do" ;;
esac
"""




def _stub(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o755)


def make_fixture(root, good, stub_url="", real_spark=False):
    """A throwaway HOME plus a stub repository and stub commands, shaped so
    every fixture-testable row is ok (good=True) or not (good=False).
    stub_url is a fake llama-server the good fixture's rows may reach.
    real_spark makes the fixture repository's bin/spark a symlink to this
    one instead of a stub, at every commit: `spark chaos` runs remedies
    that re-exec spark out of the fixture tree (spark update), and a stub
    there would answer them."""
    home = os.path.join(root, "home")
    repo = os.path.join(root, "repo")
    bin_ = os.path.join(root, "bin")
    engine = os.path.join(root, "engine")
    for d in (home, repo, bin_, engine, os.path.join(repo, "bin"),
              os.path.join(home, ".config", "spark"), os.path.join(home, ".local", "bin"),
              os.path.join(home, ".local", "state"), os.path.join(home, ".local", "share")):
        os.makedirs(d, exist_ok=True)
    open(os.path.join(home, ".config", "spark", "site.env"), "w").close()
    if good:                    # the bad fixture has no word list (allowed) and a loose site.env (not)
        with open(os.path.join(home, ".config", "spark", "privacy-terms"), "w") as f:
            f.write("# fixture word list\nfixtureword\n")

    # the repository
    _stub(os.path.join(repo, "bootstrap.sh"), _STUB_BOOTSTRAP)
    _stub(os.path.join(repo, "install.sh"),
          "#!/bin/sh\n" + ("printf 'ok             %s/.config/spark/widget.bash\\nNothing to do\\n' \"$HOME\"\n" if good
                            else "printf 'would link     %s/.config/spark/widget.bash\\n1 to do\\n' \"$HOME\"\n"))
    if real_spark:
        os.symlink(os.path.join(REPO, "bin", "spark"), os.path.join(repo, "bin", "spark"))
    else:
        _stub(os.path.join(repo, "bin", "spark"), "#!/bin/sh\necho stub\n")
    os.symlink("spark", os.path.join(repo, "bin", "explain"))
    # the package tables are data the packages row reads (packages.table):
    # the real files, so the row asks the stubbed manager for the real names
    shutil.copytree(os.path.join(REPO, "distro"), os.path.join(repo, "distro"))
    from . import site
    with open(os.path.join(repo, "models.env"), "w") as f:
        # the row_models check row hashes the stub .gguf files for real, so
        # both fixtures carry the REAL sha256 of the "x" * 4096 content the
        # model files are written with below (the bad fixture then corrupts
        # one file's bytes, same size, after that write)
        fixture_sha = hashlib.sha256(b"x" * 4096).hexdigest()
        zero_sha = "0" * 64
        f.write('MODEL_FIXTURE="fixture.gguf https://models.invalid/fixture.gguf 4096 %s 1"\n'
                'MODEL_FIXTURE_LICENSE="Apache-2.0 https://models.invalid"\n'
                'MODEL_FIXTURE_TESTED="line"\n'
                'MODEL_FIXTURE_EMBER="fixture-ember.gguf https://models.invalid/fixture-ember.gguf 4096 %s 2"\n'
                'MODEL_FIXTURE_EMBER_LICENSE="Apache-2.0 https://models.invalid"\n'
                'MODEL_FIXTURE_EMBER_TESTED="line"\n'
                'MODEL_QWEN3_30B_A3B="qwen3-30b-a3b.gguf https://models.invalid/qwen3-30b-a3b.gguf 4096 %s 21"\n'
                'MODEL_QWEN3_30B_A3B_LICENSE="Apache-2.0 https://models.invalid"\n'
                'MODEL_QWEN3_30B_A3B_TESTED="line"\n'
                % (fixture_sha, fixture_sha, zero_sha))
    # the voice's pins (voice.env): stand-ins, the same in both fixtures;
    # the good one's voice dir holds every part with the pin's sha file
    with open(os.path.join(repo, "voice.env"), "w") as f:
        for key, digit in (("VOICE_RUNTIME_LINUX_X64", "1"), ("VOICE_RUNTIME_LINUX_ARM64", "1"),
                           ("VOICE_RUNTIME_MACOS", "1"), ("VOICE_MOUTH", "2"), ("VOICE_EARS", "3")):
            f.write('%s="https://voice.invalid/%s.tar.bz2 4096 %s"\n' % (key, key.lower(), digit * 64))
        f.write('VOICE_VAD="https://voice.invalid/silero_vad.onnx 4096 %s"\n' % ("4" * 64))
    # a throwaway release key: its public half is the tree's allowed-signers,
    # and the repository's own config signs any `git tag -s` with it -- a
    # chaos scenario's tags, so `spark update` (which moves to a signed tag
    # and nothing else) can still be a heal. v1.0 and v1.1 below stay
    # unsigned: the signed row warns where the bad fixture sits, at v1.0
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", os.path.join(root, "key")], check=True)
    with open(os.path.join(root, "key.pub"), encoding="utf-8") as f:
        keytype, blob = f.read().split()[:2]
    with open(os.path.join(repo, "allowed-signers"), "w") as f:
        f.write('spark-release namespaces="git" %s %s\n' % (keytype, blob))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"HOME": home, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    g = ["git", "-C", repo]
    subprocess.run(g + ["init", "-q", "-b", "main"], env=env, check=True)
    subprocess.run(g + ["config", "gpg.format", "ssh"], env=env, check=True)
    subprocess.run(g + ["config", "user.signingkey", os.path.join(root, "key")], env=env, check=True)
    subprocess.run(g + ["add", "-A"], env=env, check=True)
    subprocess.run(g + ["commit", "-q", "-m", "fixture"], env=env, check=True)
    subprocess.run(g + ["tag", "v1.0"], env=env, check=True)
    # a second commit and tag: the good fixture stays on main past both (the
    # attached row's own test); the bad fixture detaches at the older one,
    # so row_git's "v1.1 is out" warn is the one under test there
    open(os.path.join(repo, ".fixture-v1.1"), "w").close()
    subprocess.run(g + ["add", "-A"], env=env, check=True)
    subprocess.run(g + ["commit", "-q", "-m", "fixture v1.1"], env=env, check=True)
    subprocess.run(g + ["tag", "v1.1"], env=env, check=True)
    if good:
        origin = os.path.join(root, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], env=env, check=True)
        subprocess.run(g + ["remote", "add", "origin", origin], env=env, check=True)
        subprocess.run(g + ["push", "-q", "-u", "origin", "main"], env=env, check=True)
        subprocess.run(g + ["config", "core.hooksPath", ".githooks"], env=env, check=True)
    else:
        subprocess.run(g + ["checkout", "-q", "--detach", "v1.0"], env=env, check=True)

    # the machine
    state = os.path.join(home, ".local", "state", "spark")
    os.makedirs(os.path.join(state, "widgets"), mode=0o700)
    os.makedirs(os.path.join(state, "cache"))
    with open(os.path.join(home, ".config", "spark", "site.env"), "w") as f:
        f.write("SITE_PEER_AI_URL=%s\n" % (stub_url if good else "http://127.0.0.1:9"))
        if good:
            f.write("SITE_EMBER_MODEL=auto\n")     # the default is none; auto fits an ember beside the spark row
        else:
            f.write("SITE_EMBER_MODEL=qwen3-30b-a3b\n")     # 21 GB: over the bad fixture's budget
    os.chmod(os.path.join(home, ".config", "spark", "site.env"), 0o600 if good else 0o644)
    # the good marker carries contract 6's fourth field (the exit-code
    # hook is armed); the bad one is a pre-hook shell -- the failure row
    with open(os.path.join(state, "widgets", str(os.getpid())), "w") as f:
        f.write("bash %d %d%s\n" % (os.getpid(), int(time.time()), " hook" if good else ""))
    # the good fixture's snapshot is a second one: an older run, from before
    # v1.81 (no at, since or red), saw the hooks row red. The good run heals
    # it, so the selftest reads one change in history and one line in the
    # alert file, inside this throwaway state
    with open(os.path.join(state, "check.json"), "w") as f:
        json.dump({"ts": int(time.time()) - (10 if good else 3600), "counts": {},
                   "rows": [{"category": "SOFTWARE", "status": "fail", "name": "hooks",
                             "value": "fixture", "remedy": ""}] if good else []}, f)
    # throughput: a baseline and three turns near it (good) or at 30 % of it (bad)
    with open(os.path.join(state, "bench.jsonl"), "w") as f:
        f.write(json.dumps({"ts": "2000-01-01 00:00:00", "model": "fixture.gguf", "engine": engine,
                            "settings": "ngl=999 fa=auto kv=f16 t=auto", "size": "full", "pp": 100.0, "tg": 12.0}) + "\n")
        # a line pace (spark bench --line): said by the row, never judged,
        # so both fixtures carry it and the row still flips on the tok/s
        f.write(json.dumps({"ts": "2000-01-01 00:00:00", "size": "line", "model": "fixture", "n": 5, "answered": 5,
                            "ready_ms": 400, "total_ms": 1200, "warm": 4, "known": 5}) + "\n")
    os.makedirs(os.path.join(state, "turns"), mode=0o700, exist_ok=True)
    with open(os.path.join(state, "turns", time.strftime("%Y-%m-%d") + ".jsonl"), "w") as f:
        for _ in range(3):
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "cmd", "mode": "line",
                                "tg_tps": 11.5 if good else 3.5, "pp_tps": 90.0, "ms": 900}) + "\n")
        # the sends row: today's bytes went to this machine (good) or to a
        # host nothing here names (bad) -- no tg_tps, so throughput
        # ignores the record
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "answer", "mode": "chat",
                            "ms": 1200, "out_bytes": 2048, "dest": "local" if good else "203.0.113.9:8081"}) + "\n")
    os.makedirs(os.path.join(home, ".local", "share", "spark", "models"), exist_ok=True)
    # fixture.gguf is written LAST so it is the newest .gguf -- with no
    # SITE_AI_MODEL the spark role serves the newest, and the throughput
    # row's live stem is then "fixture", the one the bench baseline names
    for mf in ("fixture-ember.gguf", "fixture.gguf"):
        with open(os.path.join(home, ".local", "share", "spark", "models", mf), "w") as f:
            f.write("x" * 4096)
        time.sleep(0.01)
    cfgd = os.path.join(home, ".config", "spark")
    # the runit dirs: runit/ says the init, service/ says it is booted --
    # every pass but the sixth points SPARK_ETC_RUNIT at a dir that is not
    # there and stays systemd
    os.makedirs(os.path.join(root, "runit"))
    os.makedirs(os.path.join(root, "service"))
    # soul and memory: the user's files, private (good) or world-readable and
    # the old key still set (bad); one thread, 0600 or not
    with open(os.path.join(cfgd, "soul"), "w") as f:
        f.write("The fixture's spark.\n")
    # legacy plaintext memory: bad only (good keeps its facts sealed below)
    if not good:
        with open(os.path.join(cfgd, "memory"), "w") as f:
            f.write("the box is a fixture\nthe fixture has two facts\n")
    # the legacy plaintext thread exists only in the bad fixture: loose
    # perms flip row_privacy, its very existence flips row_users (claim)
    os.makedirs(os.path.join(state, "threads"), mode=0o700, exist_ok=True)
    if not good:
        with open(os.path.join(state, "threads", "2000-01-01-000000.jsonl"), "w") as f:
            f.write(json.dumps({"ts": "2000-01-01 00:00:00", "role": "user", "text": "fixture?", "mode": "line", "cwd": "/"}) + "\n")
        os.chmod(os.path.join(state, "threads", "2000-01-01-000000.jsonl"), 0o644)
    for name in (("soul",) if good else ("soul", "memory")):
        os.chmod(os.path.join(cfgd, name), 0o600 if good else 0o644)
    if not good:
        with open(os.path.join(state, "chat-history"), "w") as f:
            f.write("write a haiku\n")
        os.chmod(os.path.join(state, "chat-history"), 0o644)
    # the users store: a sealed account and a live login (good), or a loose
    # dir holding a plaintext thread and no key file (bad)
    from . import vault
    udir = os.path.join(state, "users", "fixture")
    os.makedirs(os.path.join(udir, "threads"), mode=0o700)
    for d in (os.path.join(state, "users"), udir):
        os.chmod(d, 0o700 if good else 0o755)
    if good:
        fdk = vault.new_key()
        vault.write_private(os.path.join(udir, "token.hash"),
                            (vault.token_hash("fixture-token") + "\n").encode())
        vault.write_private(os.path.join(udir, "key"),
                            vault.wrap_key(fdk, "fixture-token", "fixture").encode())
        vault.append_sealed(os.path.join(udir, "threads", "2000-01-01-000001.sealed"), fdk,
                            "thread", "2000-01-01-000001",
                            json.dumps({"ts": "2000-01-01 00:00:01", "role": "user", "text": "sealed?"}).encode())
        # a kept thread, sealed the same way: kept/ passes when it is
        os.makedirs(os.path.join(udir, "kept"), mode=0o700)
        vault.append_sealed(os.path.join(udir, "kept", "fixture-kept.sealed"), fdk,
                            "thread", "fixture-kept",
                            json.dumps({"ts": "2000-01-01 00:00:02", "role": "user", "text": "kept?"}).encode())
        vault.write_sealed(os.path.join(udir, "memory"), fdk, "memory", "fixture", b"a sealed fact\n")
        vault.write_sealed(os.path.join(udir, "ledger"), fdk, "ledger", "fixture",
                           json.dumps({"kind": "edit", "name": "a.md", "ts": "2000-01-01 00:00:00",
                                       "note": "a declined note"}).encode() + b"\n")
        vault.write_private(os.path.join(state, "account"), b"name=fixture\ntoken=fixture-token\n")
        import base64 as _b64
        vault.write_private(os.path.join(state, "account-key"), _b64.b64encode(fdk) + b"\n")
    else:
        with open(os.path.join(udir, "token.hash"), "w") as f:
            f.write("0" * 64 + "\n")
        os.chmod(os.path.join(udir, "token.hash"), 0o644)
        with open(os.path.join(udir, "threads", "2000-01-01-000001.jsonl"), "w") as f:
            f.write(json.dumps({"ts": "2000-01-01 00:00:01", "role": "user", "text": "leaked?"}) + "\n")
        # a kept thread in the clear, world-readable: kept/ is read too
        os.makedirs(os.path.join(udir, "kept"), mode=0o700)
        with open(os.path.join(udir, "kept", "fixture-kept.sealed"), "w") as f:
            f.write(json.dumps({"ts": "2000-01-01 00:00:02", "role": "user", "text": "kept?"}) + "\n")
        os.chmod(os.path.join(udir, "kept", "fixture-kept.sealed"), 0o644)
        # the ledger in the clear: the row that watches it must go red
        with open(os.path.join(udir, "ledger"), "w") as f:
            f.write(json.dumps({"kind": "ask", "name": "plan.md", "ts": "2000-01-01 00:00:00",
                                "note": "who decides?"}) + "\n")
        os.chmod(os.path.join(udir, "ledger"), 0o644)
        vault.write_private(os.path.join(state, "account"), b"name=fixture\ntoken=fixture-token\n")
    if not good:
        with open(os.path.join(cfgd, "spark.env"), "w") as f:
            f.write("SPARK_PERSONA_EXTRA=old\n")
    # the look row: an awakened machine whose look file is what spark.env
    # and the faces file say (good); the bad one's faces file holds a line
    # with an escape in it, one spark must never print
    from . import look
    look_env = {"SPARK_LOOK": "auto"}
    fd_ = os.open(os.path.join(cfgd, "spark.env"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd_, "w") as f:
        f.write("".join("%s=%s\n" % kv for kv in sorted(look_env.items())))
    # the voice row: clear in both; the good fixture's engine is here (each
    # part where it lands and its sha file the pin's), the bad one's is not
    fd_ = os.open(os.path.join(cfgd, "spark.env"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd_, "w") as f:
        f.write("SPARK_VOICE=clear\n")
    if good:
        vdir = os.path.join(home, ".local", "share", "spark", "voice")
        for part, digit in (("runtime", "1"), ("mouth", "2"), ("ears", "3"), ("vad", "4")):
            os.makedirs(os.path.join(vdir, part), exist_ok=True)
            with open(os.path.join(vdir, part + ".sha"), "w") as f:
                f.write(digit * 64 + "\n")
        os.makedirs(os.path.join(vdir, "runtime", "bin"))
        for tool in ("sherpa-onnx-offline-tts", "sherpa-onnx-offline", "sherpa-onnx-vad-microphone",
                     "sherpa-onnx-vad-alsa"):
            _stub(os.path.join(vdir, "runtime", "bin", tool), "#!/bin/sh\nexit 0\n")
        with open(os.path.join(vdir, "vad", "silero_vad.onnx"), "w") as f:
            f.write("fixture\n")
    faces_path = os.path.join(cfgd, "faces")
    if not good:
        with open(faces_path, "w") as f:
            f.write("RATE=14\nIDLE=(o.o)\nPLEASED=(^\033[31m.^)\n")
    with open(os.path.join(state, "look"), "w") as f:
        f.write(look.content(look_env, True, faces_path))
    # gpu: a fake sysfs card whose VRAM does (good) or does not (bad) hold the model
    drm = os.path.join(root, "drm", "card0", "device")
    os.makedirs(drm)
    for name, val in (("gpu_busy_percent", 3), ("mem_info_vram_used", 1000), ("mem_info_vram_total", 10**12 if good else 1000),
                      ("mem_info_gtt_used", 0), ("mem_info_gtt_total", 8 * 2**30)):
        with open(os.path.join(drm, name), "w") as f:
            f.write("%d\n" % val)
    if good:
        for name in ("spark", "explain"):
            os.symlink(os.path.join(repo, "bin", name), os.path.join(home, ".local", "bin", name))
        _stub(os.path.join(engine, "llama-server"), "#!/bin/sh\nexit 0\n")
        with open(os.path.join(engine, "flavour"), "w") as f:     # the engine row names the tarball's flavour
            f.write("fixture-x64\n")
        for sh in ("bash", "zsh"):
            # the failure row wants the exit-code hook's sentinel in each
            # widget (the bad fixture has no widgets at all, so both the
            # prompt and the failure row flip to warn there)
            with open(os.path.join(home, ".config", "spark", "widget." + sh), "w") as f:
                f.write("# fixture widget\n_spark_failed() { :; }\n")
            # the completion row: the two files plus a hook that sources its
            # own (the bad fixture has neither, so the row flips to warn)
            open(os.path.join(home, ".config", "spark", "completion." + sh), "w").close()
            with open(os.path.join(home, ".config", "spark", "hook." + sh), "w") as f:
                f.write('[ -r "$HOME/.config/spark/completion.%s" ] && . "$HOME/.config/spark/completion.%s"\n' % (sh, sh))

        fd_ = os.open(os.path.join(state, "api-token"), os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd_, b"stub-token\n")
        os.close(fd_)
        with open(os.path.join(state, "serve-url"), "w") as f:
            f.write(stub_url + "\n")
        # the FORGE: the private admin token and a URL the stub answers /api/health at
        fd_ = os.open(os.path.join(state, "forge-token"), os.O_WRONLY | os.O_CREAT, 0o600)
        os.write(fd_, b"stub-forge-token\n")
        os.close(fd_)
        with open(os.path.join(state, "forge-url"), "w") as f:
            f.write(stub_url + "\n")
    else:
        os.chmod(state, 0o755)
        with open(os.path.join(state, "api-token"), "w") as f:
            f.write("stub-token\n")
        os.chmod(os.path.join(state, "api-token"), 0o644)
        with open(os.path.join(state, "serve-url"), "w") as f:
            f.write("http://127.0.0.1:9\n")
        for tname, tval in (("forge-token", "stub-forge-token\n"), ("ember-token", "stub-ember-token\n")):
            with open(os.path.join(state, tname), "w") as f:
                f.write(tval)
            os.chmod(os.path.join(state, tname), 0o644)
        with open(os.path.join(state, "forge-url"), "w") as f:
            f.write("http://127.0.0.1:9\n")
        # row_models: corrupt one stub .gguf file, same size as models.env's
        # real sha expects, so the mismatch is content, not a size the
        # verify cache (absent here anyway) could be fooled by
        with open(os.path.join(home, ".local", "share", "spark", "models", "fixture.gguf"), "w") as f:
            f.write("y" * 4096)

    # the rc file: the good fixture's carries the one marked hook line
    # (the prompt row reads `hook`); the bad one's is plain and empty
    rcname = ".zshrc" if IS_MAC else ".bashrc"
    with open(os.path.join(home, rcname), "w") as f:
        if good:
            f.write(site.RC_LINE["zsh" if IS_MAC else "bash"] + "\n")

    # stub commands: what the OS would answer
    if good:            # the voice row's player, where the OS has none of its own
        _stub(os.path.join(bin_, "aplay"), "#!/bin/sh\nexit 0\n")
    _stub(os.path.join(bin_, "infocmp"), "#!/bin/sh\n" + ("echo 'kUP=\\E[1;2A,'\n" if good else "exit 1\n"))
    _stub(os.path.join(bin_, "brew"), "#!/bin/sh\n" + ("exit 0\n" if good else "exit 1\n"))
    _stub(os.path.join(bin_, "dpkg-query"),
          "#!/bin/sh\n" + ("shift 3; for p; do echo \"$p install ok installed\"; done\n" if good else "exit 1\n"))
    _stub(os.path.join(bin_, "pacman"),
          "#!/bin/sh\n" + ("case $1 in -Qq) shift; printf '%s\\n' \"$@\" ;; -Sp) exit 0 ;; *) exit 1 ;; esac\n" if good else "exit 1\n"))
    # xbps for the Void pass: -l lists every name distro/void.env holds
    # (the packages row cuts it to --list-packages, which the stub bootstrap
    # answers with bash and git: both listed too); -p pkgver and -R say
    # installed and in a repo; xbps-install -un says nothing is pending
    void = config.parse_env(os.path.join(REPO, "distro", "void.env"))
    void_names = sorted({"bash", "git"} | set(" ".join(void.get(g, "") for g in packages.GROUPS).split()))
    _stub(os.path.join(bin_, "xbps-query"),
          "#!/bin/sh\n" + ("case $1 in -l) for p in %s; do echo \"ii $p-1.0_1 fixture\"; done ;; -p|-R) exit 0 ;; *) exit 1 ;; esac\n"
                            % " ".join(void_names) if good else "exit 1\n"))
    _stub(os.path.join(bin_, "xbps-install"), "#!/bin/sh\n" + ("exit 0\n" if good else "exit 1\n"))
    # rpm for the Fedora and openSUSE passes: -q --whatprovides says a
    # package provides the name (good), or none does (bad)
    _stub(os.path.join(bin_, "rpm"),
          "#!/bin/sh\n" + ("case \"$1 $2\" in '-q --whatprovides') echo \"$3-1.0-1.fixture\" ;; *) exit 1 ;; esac\n" if good
                            else "echo \"no package provides $3\"; exit 1\n"))
    # sv for the Void pass: the dir asked about is supervised and running
    # (good), or no runsv watches it (bad)
    _stub(os.path.join(bin_, "sv"),
          "#!/bin/sh\n" + ("echo \"run: $2: (pid 1) 1s\"\n" if good else "echo \"fail: $2: runsv not running\"; exit 1\n"))
    _stub(os.path.join(bin_, "checkupdates"), "#!/bin/sh\n" + ("exit 2\n" if good else "exit 1\n"))
    _stub(os.path.join(bin_, "systemctl"),
          "#!/bin/sh\n[ \"$2\" = show-environment ] && exit 0\ncase $3 in spark-check.timer) "
          + ("[ \"$2\" = is-enabled ] && echo enabled || echo active" if good else "echo disabled")
          + " ;; *) echo not-found; exit 1 ;; esac\n")
    _stub(os.path.join(bin_, "launchctl"),
          "#!/bin/sh\ncase $1 in print-disabled) exit 0 ;; print) " + ("case $2 in gui/*/spark.check) exit 0 ;; esac; " if good else "")
          + "exit 113 ;; esac\n")
    # a plain kernel line: a selftest on a real WSL box must not read the host's
    with open(os.path.join(root, "version"), "w") as f:
        f.write("Linux version 6.12.0-fixture (fixture) #1 SMP\n")
    # a Debian os-release: a selftest on another family must not read the host's
    with open(os.path.join(root, "os-release"), "w") as f:
        f.write('ID=debian\nPRETTY_NAME="Debian fixture"\n')
    return {"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
            "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
            "PATH": os.path.join(home, ".local", "bin") + ":" + bin_ + ":" + os.environ.get("PATH", ""),
            "SPARK_REPO": repo, "SPARK_ENGINE_DIR": engine if good else os.path.join(root, "nope"),
            "SPARK_API_KEY": "stub-token", "SPARK_SERVICE": "none", "TMUX": "", "SPARK_SYSFS_DRM": os.path.join(root, "drm"),
            "SPARK_PROC_VERSION": os.path.join(root, "version"),
            "SPARK_OS_RELEASE": os.path.join(root, "os-release"),
            "SPARK_ETC_RUNIT": os.path.join(root, "no-runit"), "SPARK_VAR_SERVICE": os.path.join(root, "service"),
            "SPARK_MEM_TOTAL_GB": "16" if good else "8", "SHELL": "/bin/zsh" if IS_MAC else "/bin/bash",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def knowledge_fixture(env):
    """The knowledge row's store for the good fixture: built by intake
    itself, through its public refresh(), in the very environment the
    check then runs in -- the same PATH and the same STATE_DIR, so the
    fingerprint matches and the index is fresh. The bad fixture builds
    none: its row says there is no index yet."""
    # a tiny machine of its own (intake's seams): one program with its
    # manual, no apps, no --help runs, no spark -h runs -- so the build
    # takes a blink, never walks the real /usr, and nothing is pending
    root = os.path.join(env.get("HOME") or env.get("XDG_STATE_HOME") or "/tmp", "knowledge-fixture")
    for d in ("bin", "man/man1", "apps"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    tool = os.path.join(root, "bin", "fixturetool")
    with open(tool, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(tool, 0o755)
    with open(os.path.join(root, "man", "man1", "fixturetool.1"), "w") as f:
        f.write(".TH FIXTURETOOL 1\n.SH NAME\nfixturetool \\- a fixture's one program\n"
                ".SH SYNOPSIS\nfixturetool [-v]\n.SH OPTIONS\n.TP\n.B \\-v\nsay more\n")
    env.update(SPARK_KNOWLEDGE_PATH=os.path.join(root, "bin"), SPARK_KNOWLEDGE_MANPATH=os.path.join(root, "man"),
               SPARK_KNOWLEDGE_APPS=os.path.join(root, "apps"), SPARK_KNOWLEDGE_SOURCES="programs,apps",
               SPARK_KNOWLEDGE_SANDBOX="none")
    code = "from spark import intake; intake.refresh()"
    run_env = dict(env, PYTHONPATH=os.path.join(REPO, "lib"))
    try:
        subprocess.run([sys.executable, "-c", code], env=run_env, capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _stub_server(plain=False):
    """A fake llama-server on loopback for the good fixture: /health 200,
    /v1/models with a bearer; and a fake FORGE at /api/health. plain=True
    is a llama-server the user runs: no /api/health (404), one model
    with no alias, and /props with its context size."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/health":
                body = b'{"status":"ok"}'
            elif plain:
                if self.path == "/v1/models":
                    body = b'{"data":[{"id":"fixture.gguf"}]}'
                elif self.path == "/props":
                    body = b'{"default_generation_settings":{"n_ctx":4096}}'
                else:
                    self.send_error(404)
                    return
            elif self.path == "/api/health":
                # 1.1 is the fixture repo's own tag (make_fixture tags
                # v1.1): the forge row compares this against the tree it
                # runs in, and the good fixture must match
                body = (b'{"status":"ok","forge":true,"name":"fixture","version":"1.1",'
                        b'"model":"fixture.gguf","upstream":"ok"}')
            else:
                body = (b'{"data":[{"id":"fixture.gguf","aliases":["spark"],"status":{"value":"loaded"}},'
                        b'{"id":"fixture-ember.gguf","aliases":["ember"],"status":{"value":"loaded"}}]}')
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def _selftest_change(state):
    """The good fixture's one change, read from its throwaway state: the
    hooks row the older snapshot held red is ok now. '' when history
    holds exactly that record, the alert file exactly that heal and the
    snapshot the three new keys; else what is wrong."""
    try:
        with open(os.path.join(state, "check-history.jsonl"), encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        with open(os.path.join(state, "alert"), encoding="utf-8") as f:
            said = f.read().splitlines()
        with open(os.path.join(state, "check.json"), encoding="utf-8") as f:
            rows = {r["name"]: r for r in json.load(f)["rows"]}
    except (OSError, ValueError, KeyError, TypeError) as e:
        return "the good run left no readable history, alert or snapshot (%s)" % type(e).__name__
    if len(recs) != 1 or [recs[0].get(k) for k in ("row", "from", "to")] != ["hooks", FAIL, OK] \
            or not isinstance(recs[0].get("red"), int) or sorted(recs[0]) != ["from", "red", "row", "to", "ts"]:
        return "history is not the one heal of hooks: %d records" % len(recs)
    if len(said) != 1 or said[0].split(" ", 5)[2:5] != ["*", "pleased", "hooks"] \
            or not said[0].split(" ", 5)[5].startswith("hooks: ok again, after "):
        return "the alert file is not the one heal line of hooks: %d lines" % len(said)
    hooks = rows.get("hooks", {})
    if "red" in hooks or not all(k in hooks for k in ("at", "since")):
        return "the snapshot's hooks row lacks at and since, or still carries red"
    return ""


def selftest():
    """Run the check against a good and a bad fixture; every fixture-testable
    row must be ok in the good one and not ok in the bad one. A third
    pass, the good fixture as a client of the stub, must make every
    client row na; a fourth, on Linux, the good fixture under WSL 2:
    every WSL row says so; a fifth under ID=arch, where the packages row
    answers through pacman; a sixth under ID=void, where the packages row
    answers through xbps and the services row through sv; a seventh under
    ID=fedora and an eighth under openSUSE's ID_LIKE, where the packages
    row answers through rpm, dnf's and zypper's database."""
    base = {k: v for k, v in os.environ.items()
            if not k.startswith(("GIT_", "SPARK_", "XDG_", "SITE_"))}
    results = {}
    srv, stub_url = _stub_server()
    with tempfile.TemporaryDirectory(prefix="spark-selftest-") as tmp:
        for tag in ("good", "bad"):
            root = os.path.join(tmp, tag)
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, tag == "good", stub_url))
            if tag == "good":
                knowledge_fixture(env)
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            got = {}
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    got[parts[2]] = (parts[1], parts[3])
            if not got:
                say("%s check --selftest: the %s fixture produced no rows\n%s" % (MARK, tag, p.stderr[-2000:]))
                srv.shutdown()
                return 1
            results[tag] = got
            if tag == "good":
                changed = _selftest_change(os.path.join(env["XDG_STATE_HOME"], "spark"))
        # the third pass: the good fixture as a client of the stub -- the
        # engine, the units, the snapshot, the local AI and its servers answer na
        root = os.path.join(tmp, "client")
        os.makedirs(root)
        env = dict(base)
        env.update(make_fixture(root, True, stub_url))
        env["SITE_AI_MODEL"] = "none"
        env["SITE_PEER_AI_URL"] = stub_url
        p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                           env=env, capture_output=True, text=True, timeout=180)
        results["client"] = {}
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 5:
                results["client"][parts[2]] = (parts[1], parts[3])
        # the third pass again, as a client of a plain llama-server (the
        # user's own): the same rows are na, and the peer row names it theirs
        psrv, plain_url = _stub_server(plain=True)
        root = os.path.join(tmp, "plain")
        os.makedirs(root)
        env = dict(base)
        env.update(make_fixture(root, True, stub_url))
        env["SITE_AI_MODEL"] = "none"
        env["SITE_PEER_AI_URL"] = plain_url
        p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                           env=env, capture_output=True, text=True, timeout=180)
        psrv.shutdown()
        results["plain"] = {}
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 5:
                results["plain"][parts[2]] = (parts[1], parts[3])
        # the fourth pass, Linux only: the good fixture under WSL 2 (a kernel
        # line naming microsoft) -- gpu says so, never fails
        results["wsl"] = {}
        if not IS_MAC:
            root = os.path.join(tmp, "wsl")
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, True, stub_url))
            with open(os.path.join(root, "version"), "w") as f:
                f.write("Linux version 6.6.87.2-microsoft-standard-WSL2 (root@fixture) #1 SMP\n")
            env["SPARK_SYSFS_DRM"] = os.path.join(root, "nodrm")    # no DRM card: WSL shows /dev/dxg
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    results["wsl"][parts[2]] = (parts[1], parts[3])
        # the fifth pass, Linux only: the good fixture as Arch (ID=arch in
        # os-release, a pacman stub) -- the packages row answers through pacman
        results["arch"] = {}
        if not IS_MAC:
            root = os.path.join(tmp, "arch")
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, True, stub_url))
            with open(os.path.join(root, "os-release"), "w") as f:
                f.write('ID=arch\nPRETTY_NAME="Arch Linux"\n')
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    results["arch"][parts[2]] = (parts[1], parts[3])
        # the sixth pass, Linux only: the good fixture as Void (ID="void" in
        # os-release, xbps and sv stubs, /etc/runit and /var/service dirs,
        # spark-check's service dir present without a `down` file) -- the
        # packages row answers through xbps and the services row through sv
        results["void"] = {}
        if not IS_MAC:
            root = os.path.join(tmp, "void")
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, True, stub_url))
            with open(os.path.join(root, "os-release"), "w") as f:
                f.write('ID="void"\nPRETTY_NAME="Void Linux"\n')
            env["SPARK_ETC_RUNIT"] = os.path.join(root, "runit")
            env["SPARK_VAR_SERVICE"] = os.path.join(root, "service")
            os.makedirs(os.path.join(root, "home", ".config", "spark", "sv", "spark-check"))   # supervised, no `down`
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    results["void"][parts[2]] = (parts[1], parts[3])
        # the seventh and eighth passes, Linux only: the good fixture as
        # Fedora (ID=fedora) and as openSUSE (Tumbleweed's own os-release:
        # the family is the ID_LIKE word), an rpm stub -- the packages row
        # answers through rpm, the one database under dnf and zypper
        for tag, body in (("fedora", 'ID=fedora\nPRETTY_NAME="Fedora Linux"\n'),
                          ("opensuse", 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
                                       'PRETTY_NAME="openSUSE Tumbleweed"\n')):
            results[tag] = {}
            if IS_MAC:
                continue
            root = os.path.join(tmp, tag)
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, True, stub_url))
            with open(os.path.join(root, "os-release"), "w") as f:
                f.write(body)
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    results[tag][parts[2]] = (parts[1], parts[3])
    srv.shutdown()
    bad = 0
    say("%s check --selftest" % MARK)
    for spec in SPECS:
        if not spec.fixture:
            continue
        g = results["good"].get(spec.name, ("missing", ""))
        b = results["bad"].get(spec.name, ("missing", ""))
        passed = g[0] == OK and b[0] in (FAIL, WARN)
        bad += not passed
        say("  %s %-11s good:%-5s bad:%-5s%s" % (GLYPH[OK] if passed else GLYPH[FAIL], spec.name, g[0], b[0],
                                               "" if passed else "   good=%r bad=%r" % (g[1], b[1])))
    say("  untestable (live state a fixture cannot reach):")
    for spec in SPECS:
        if not spec.fixture:
            say("    %s %-11s %s" % (GLYPH[NA], spec.name, spec.reason))
    not_na = [n for n in CLIENT_ROWS if results["client"].get(n, ("missing", ""))[0] != NA]
    peer = results["client"].get("peer", ("missing", ""))[0]
    say("  %s client: %d rows na, peer %s%s" % (GLYPH[OK] if not not_na and peer == OK else GLYPH[FAIL],
                                              len(CLIENT_ROWS) - len(not_na), peer,
                                              "" if not not_na else "   not na: " + " ".join(not_na)))
    bad += bool(not_na) or peer != OK
    not_na = [n for n in CLIENT_ROWS if results["plain"].get(n, ("missing", ""))[0] != NA]
    peer, said = results["plain"].get("peer", ("missing", ""))
    yours = peer == OK and said.startswith("your engine ")
    say("  %s client of your own engine: %d rows na, peer %s%s"
        % (GLYPH[OK] if not not_na and yours else GLYPH[FAIL], len(CLIENT_ROWS) - len(not_na), peer,
           "" if not not_na and yours else "   not na: %s; peer says %r" % (" ".join(not_na), said)))
    bad += bool(not_na) or not yours
    say("  %s change: %s" % (GLYPH[FAIL] if changed else GLYPH[OK],
                           changed or "a healed row is recorded once and said once"))
    bad += bool(changed)
    if IS_MAC:
        say("  %s wsl: skipped on macOS (a Linux gate proves it)" % GLYPH[NA])
    else:
        off = [n for n in WSL_ROWS
               if results["wsl"].get(n, ("missing", ""))[0] not in (NA, OK) or "WSL 2" not in results["wsl"].get(n, ("", ""))[1]]
        say("  %s wsl: %d rows say WSL 2%s" % (GLYPH[OK] if not off else GLYPH[FAIL], len(WSL_ROWS) - len(off),
                                              "" if not off else "   not so: " + " ".join(off)))
        bad += bool(off)
    if IS_MAC:
        say("  %s arch: skipped on macOS (a Linux gate proves it)" % GLYPH[NA])
    else:
        off = [n for n in ARCH_ROWS
               if results["arch"].get(n, ("missing", ""))[0] not in (NA, OK) or "Arch" not in results["arch"].get(n, ("", ""))[1]]
        pk = results["arch"].get("packages", ("missing", ""))[0]
        say("  %s arch: %d rows say Arch, packages %s via pacman%s"
            % (GLYPH[OK] if not off and pk == OK else GLYPH[FAIL], len(ARCH_ROWS) - len(off), pk,
               "" if not off else "   not so: " + " ".join(off)))
        bad += bool(off) or pk != OK
    if IS_MAC:
        say("  %s void: skipped on macOS (a Linux gate proves it)" % GLYPH[NA])
    else:
        off = [n for n in VOID_ROWS
               if results["void"].get(n, ("missing", ""))[0] not in (NA, OK) or "Void" not in results["void"].get(n, ("", ""))[1]]
        pk = results["void"].get("packages", ("missing", ""))[0]
        svc = results["void"].get("services", ("missing", ""))[0]
        say("  %s void: %d rows say Void, packages %s via xbps, services %s via sv%s"
            % (GLYPH[OK] if not off and pk == OK and svc == OK else GLYPH[FAIL], len(VOID_ROWS) - len(off), pk, svc,
               "" if not off else "   not so: " + " ".join(off)))
        bad += bool(off) or pk != OK or svc != OK
    for tag, name, rows, pm in (("fedora", "Fedora", FEDORA_ROWS, "dnf"), ("opensuse", "openSUSE", OPENSUSE_ROWS, "zypper")):
        if IS_MAC:
            say("  %s %s: skipped on macOS (a Linux gate proves it)" % (GLYPH[NA], tag))
            continue
        off = [n for n in rows
               if results[tag].get(n, ("missing", ""))[0] not in (NA, OK) or name not in results[tag].get(n, ("", ""))[1]]
        pk = results[tag].get("packages", ("missing", ""))[0]
        say("  %s %s: %d rows say %s, packages %s via %s%s"
            % (GLYPH[OK] if not off and pk == OK else GLYPH[FAIL], tag, len(rows) - len(off), name, pk, pm,
               "" if not off else "   not so: " + " ".join(off)))
        bad += bool(off) or pk != OK
    say("  %d row%s failed to flip" % (bad, "" if bad == 1 else "s") if bad else "  every fixture-testable row flips")
    return 1 if bad else 0


def refresh():
    """Write a fresh snapshot in the background (~300 ms) after something
    changed, so the status line follows the machine instead of the timer.
    SPARK_NO_REFRESH=1 makes it a no-op (tests: nothing must write into a
    throwaway HOME after the test has left it)."""
    if os.environ.get("SPARK_NO_REFRESH"):
        return
    try:
        subprocess.Popen([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


# --------------------------------------------------------------------- main
# the units that run the check every 5 minutes (spark-check.service, the
# runit loop, the launchd agent) set this to 1, and nothing else does:
# `ssh HOST 'spark check --porcelain'` has no terminal either, and it is a
# person's run -- it must not read manuals or run anyone's --help
TIMER_ENV = "SPARK_CHECK_TIMER"


def unattended(porcelain_out, fresh, watch, stdin, environ=None):
    """The timer's run (see Ctx.unattended): the units' TIMER_ENV=1,
    --porcelain, no --fresh, no --watch, and no terminal on stdin. A
    missing flag is a person's run, whatever else holds."""
    env = os.environ if environ is None else environ
    if env.get(TIMER_ENV) != "1":
        return False
    try:
        tty = stdin is not None and stdin.isatty()
    except (OSError, ValueError):
        tty = False
    return bool(porcelain_out and not fresh and not watch and not tty)


USAGE = """%s check -- is this machine as it should be

  spark check              what needs you, and the totals
  spark check --all        every row
  spark check NAME...      those rows
  spark check --history    what changed and when (--history NAME: one row)
  spark check --watch N    show it again every N seconds
  spark check --porcelain  category<TAB>status<TAB>name<TAB>value<TAB>remedy
  spark check --report     a block to paste into an issue (no names, no paths)
  spark check --fresh      ask again, not from the cache
  spark check --fetch      ask origin before the git row
  spark check --selftest   prove every row can turn red
  spark check --chaos      break a test machine, then prove each fix

  exit 0 when no row failed
""" % MARK


def main(argv):
    watch, porcelain_out, report_out, fresh, fetch, names = 0, False, False, False, False, []
    every = False
    if "--history" in argv:
        if any(a in ("-h", "--help", "help") for a in argv):
            say(USAGE.rstrip())
            return 0
        rest = [a for a in argv if a != "--history"]
        hist = [a for a in rest if not a.startswith("-")]
        if len(rest) != len(argv) - 1 or len(hist) > 1 or any(a.startswith("-") and a != "--porcelain" for a in rest):
            say("%s check -- --history takes a row name and --porcelain" % MARK)
            return 2
        if hist and hist[0] not in {s.name for s in SPECS}:
            say("%s check -- no row named %s" % (MARK, hist[0]))
            return 2
        return show_history(hist[0] if hist else "", "--porcelain" in rest)
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help", "help"):
            say(USAGE.rstrip())
            return 0
        if a == "--all":
            every = True
        elif a == "--watch":
            watch = int(next(it, "5"))
        elif a == "--report":
            report_out = True
        elif a == "--porcelain":
            porcelain_out = True
        elif a == "--fresh":
            fresh = True
        elif a == "--fetch":
            fetch = True
        elif a == "--selftest":
            return selftest()
        elif a == "--chaos":
            from . import chaos
            return chaos.run()
        elif a.startswith("-"):
            say("%s check -- no word %s; spark check -h lists them" % (MARK, a))
            return 2
        else:
            names.append(a)
    known = {s.name for s in SPECS}
    for n in names:
        if n not in known:
            say("%s check -- no row named %s" % (MARK, n))
            return 2
    ctx = Ctx(fresh=fresh, fetch=fetch)
    ctx.unattended = unattended(porcelain_out, fresh, watch, sys.stdin)
    color = sys.stdout.isatty() and not porcelain_out
    from . import look
    roles = color and look.active("colour", sys.stdout)
    counter = Counter(sys.stderr) if (not porcelain_out and not report_out
                                      and look.active("motion", sys.stderr)) else None
    while True:
        try:
            rows = run_rows(ctx, names or None, counter)
        finally:            # Ctrl-C too: `checking N/M` never stays on the line
            if counter is not None:
                counter.clear()
        write_snapshot(ctx, rows, full=not names)
        if report_out:
            page(report(ctx, rows))
            return 1 if any(r.status == FAIL for r in rows) else 0
        # rows named on the line are asked for: each one shows
        text = porcelain(rows) if porcelain_out else render(ctx, rows, color, roles, every, named=bool(names))

        if watch:
            sys.stdout.write("\033[2J\033[H" + text + "\n")
            sys.stdout.flush()
            time.sleep(watch)
            continue
        if porcelain_out:
            say(text)
        else:
            page(text)      # the report pages at a terminal; piped stays plain
        return 1 if any(r.status == FAIL for r in rows) else 0
