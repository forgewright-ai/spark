# spark.check -- is this machine still what its repository says it is?
#
# A report, not a monitor: `spark check` prints every row once and exits 0
# iff nothing reproducible is broken. Rows are small functions registered
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
from . import (BIN_DIR, CACHE_DIR, CHECK_JSON, HOME, IS_MAC, MARK, OS, REPO,
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
        return ok("nothing required")
    rc, out = ctx.sh(["sh", os.path.join(ctx.repo, "bootstrap.sh"), "--list-packages"], 30)
    if rc != 0:
        return fail("bootstrap.sh --list-packages failed", "sh %s --list-packages" % ctx.short(os.path.join(ctx.repo, "bootstrap.sh")))
    pkgs = out.split()
    if not pkgs:
        return ok("nothing required")
    have = packages.installed(pkgs)
    if have is None:
        return fail("no package manager spark knows here (%s)" % (packages.manager() or "distro/*.env know debian, arch and void"), "./bootstrap.sh")
    missing = [p for p in pkgs if p not in have]
    if missing:
        return fail("%d/%d missing: %s" % (len(missing), len(pkgs), " ".join(missing[:6])), "./bootstrap.sh")
    return ok("%d/%d installed" % (len(pkgs), len(pkgs)))


@row("SOFTWARE")
def row_configs(ctx):
    script = os.path.join(ctx.repo, "install.sh")
    rc, out = ctx.sh(["sh", script, "--dry-run"], 60)
    lines = out.splitlines()
    if rc != 0:
        return fail("install.sh --dry-run failed: %s" % (lines[-1] if lines else "no output"), "sh %s --dry-run" % ctx.short(script))
    would = [re.match(r"^would (?:link|render|back up)\s+(.*)$", l) for l in lines if l.startswith("would")]
    done = [l for l in lines if l.startswith("ok ")]
    if would:
        names = sorted({ctx.short(m.group(1)) for m in would if m})
        return fail("%d not in place: %s" % (len(would), ", ".join(names[:3])), "sh %s" % ctx.short(script))
    return ok("%d files linked or rendered" % len(done))


@row("SOFTWARE")
def row_tools(ctx):
    rc, out = ctx.sh(["sh", os.path.join(ctx.repo, "bootstrap.sh"), "--list-tools"], 30)
    if rc != 0:
        return fail("bootstrap.sh --list-tools failed", "./bootstrap.sh")
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
        return fail("not linked into ~/.local/bin: %s" % " ".join(bad), "./bootstrap.sh")
    found = shutil.which("spark")
    if found and os.path.realpath(found) != os.path.realpath(os.path.join(BIN_DIR, "spark")):
        return warn("another spark shadows ~/.local/bin/spark: %s" % found, "put ~/.local/bin first on PATH")
    return ok("%s linked into ~/.local/bin" % " ".join(names))


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
            return na("no model chosen -- spark model NAME brings the engine with it")
        return fail("no llama-server in %s" % ctx.short(d), "./bootstrap.sh   (row engine)")
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
        name, where = os.path.basename(d), ctx.short(ENGINE_DIR)
    else:
        # a llama-server this machine already had (facts probed PATH and
        # the system dirs): spark has no pin here, so it serves with yours
        name, where = ctx.short(d), "your build"
    build = engine.backend(ctx.cfg)
    if not ctx.cfg.engine_dir and flavour.startswith("ubuntu-") and ("vulkan" in flavour) != (build == "vulkan"):
        return warn("%s is the %s build, but the build here is %s now" % (name, "vulkan" if "vulkan" in flavour else "cpu", build),
                    "./bootstrap.sh   (replaces the engine)")
    return ok(" ".join(x for x in (name, flavour, "(%s)" % where if where else "") if x))


def _console_font_row(ctx):
    """The Linux half of the font row, by console shape: ok/fail against
    SITE_FONT_FACE (console-setup's FONTFACE + FONTSIZE, or the FONT= of
    vconsole.conf or rc.conf -- quotes stripped, a #FONT= line unset),
    None when nothing is chosen there."""
    from . import site
    if IS_MAC or not ctx.cfg.font_face:
        return None
    want = "%s %s" % (ctx.cfg.font_face, ctx.cfg.font_size)
    shape, cur = site.console_shape(), ""
    try:
        with open(site.font_file(), encoding="utf-8") as f:
            kv = dict(l.strip().split("=", 1) for l in f if "=" in l and not l.startswith("#"))
        if shape == "setup":
            cur = "%s %s" % (kv.get("FONTFACE", "").strip('"'), kv.get("FONTSIZE", "").strip('"'))
        else:
            cur = kv.get("FONT", "").strip('"')
    except (OSError, ValueError):
        pass
    if cur != (want if shape == "setup" else ctx.cfg.font_face):
        return fail("console font is %s, site.env says %s (%s)" % (cur.strip() or "unset", want, site.font_file()),
                    "./bootstrap.sh   (sudo)")
    return ok("console %s (%s)" % (want, site.font_file()))


@row("SOFTWARE")
def row_font(ctx):
    """The console font choice (SITE_FONT_FACE, Linux) and the macOS
    Terminal face -- the machine's own; a terminal emulator's font is
    set in the emulator. WSL 2 has no console: the font is Windows
    Terminal's, the row says so and stops."""
    from . import site
    why = site.no_console_font()
    if why and is_wsl():
        return na(why)
    console = na(why) if why and ctx.cfg.font_face else _console_font_row(ctx)
    if IS_MAC:
        # a face this Mac does not have makes Terminal.app fall back to its
        # own font in silence (a console face such as VGA carried over);
        # an installed one is the promise kept; no Spotlight index, no verdict
        installed = site.mac_font_installed(ctx.cfg.font_face)
        if installed is False:
            return warn("SITE_FONT_FACE=%s is not installed here: Terminal.app falls back to its own font" % ctx.cfg.font_face,
                        "spark font list; spark font FACE %s" % ctx.cfg.font_size)
        if installed:
            return ok("Terminal.app profile: %s %s" % (ctx.cfg.font_face, ctx.cfg.font_size))
        return na("Terminal.app profile: %s %s (Spotlight has no font index: not verified)" % (ctx.cfg.font_face, ctx.cfg.font_size))
    if console:
        return console
    if why:
        return na(why)
    return na("console not managed (spark font FACE SIZE; spark font list)")


def _env_lines(path):
    """KEY -> value from a KEY=value file, tolerant (a check row must judge
    a broken file, not die on it); None when the file cannot be read."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    out = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


THEME_KEYS = (["THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED"]
              + ["THEME_ANSI_%d" % i for i in range(16)])


def _vt_palette(sysfs):
    """The kernel's current default VT palette as setvtrgb's three lines,
    from /sys/module/vt/parameters/default_{red,grn,blu}; None when
    unreadable (no VT here)."""
    lines = []
    for ch in ("red", "grn", "blu"):
        try:
            with open(os.path.join(sysfs, "default_" + ch), encoding="utf-8") as f:
                lines.append(f.read().strip())
        except OSError:
            return None
    return lines


@row("SOFTWARE")
def row_theme(ctx):
    """The chosen palette actually applied: ~/.config/spark/theme.env (the
    palette the FORGE page and any renderer read) matches the palette's
    file -- yours under ~/.config/spark/themes/ first, else
    themes/<SITE_THEME>.env -- key for key, and on Linux console-colors (the
    VT palette the rc hook applies) is in place. A palette is only PAINTED
    by `spark theme NAME`: a key naming one nothing has applied yet is
    `na`, not a fault."""
    from . import CONFIG_DIR
    name = ctx.cfg.theme
    if name == "none":
        return na("none -- the terminal keeps its own colours (spark theme NAME)")
    from . import config
    path = config.theme_path(name, ctx.repo)
    want = _env_lines(path) if path else None
    if want is None:
        return fail("SITE_THEME=%s: no %s.env in themes/ or ~/.config/spark/themes/" % (name, name), "spark theme")
    have = _env_lines(os.path.join(CONFIG_DIR, "theme.env"))
    if have is None:
        return na("%s chosen, not painted (spark theme %s)" % (name, name))
    stale = [k for k in THEME_KEYS if have.get(k) != want.get(k)]
    if stale:
        return fail("%s -- theme.env is stale: %s differ%s" % (name, " ".join(stale[:3]), "s" if len(stale) == 1 else ""),
                    "spark theme %s" % name)
    if not IS_MAC and not os.path.isfile(os.path.join(CONFIG_DIR, "console-colors")):
        return fail("%s -- theme.env current, but no console-colors for the VT" % name, "spark theme %s" % name)
    if not IS_MAC and not is_wsl():
        # the kernel's default palette (sysfs, world-readable) is what the
        # spark-console unit set at boot -- the login screen and every VT
        live = _vt_palette(os.environ.get("SPARK_SYSFS_VT", "/sys/module/vt/parameters"))
        try:
            with open(os.path.join(CONFIG_DIR, "console-colors.rgb"), encoding="utf-8") as f:
                mine = [line.strip() for line in f.read().splitlines()[:3]]
        except OSError:
            mine = None
        if live and mine and live != mine:
            return warn("%s -- theme.env current, but the console's boot palette is another" % name,
                        "./bootstrap.sh   (the vt-palette row: setvtrgb at boot, sudo)")
    return ok("%s -- theme.env current" % name)


@row("SOFTWARE")
def row_git(ctx):
    g = ["git", "-C", ctx.repo]
    if ctx.fetch:
        ctx.sh(g + ["fetch", "-q"], 30)
    rc, out = ctx.sh(g + ["status", "--porcelain"], 20)
    if rc != 0:
        return fail("not a git repository: %s" % ctx.short(ctx.repo), "git clone it again")
    rc, _ = ctx.sh(g + ["symbolic-ref", "-q", "HEAD"], 10)
    if rc != 0:
        # detached: a release clone. Currency is against the newest tag,
        # not an upstream branch -- `spark update` moves it.
        rc2, tags = ctx.sh(g + ["tag", "-l", "v[0-9]*", "--sort=-v:refname"], 10)
        newest = tags.split()[0] if rc2 == 0 and tags.split() else ""
        rc3, cur = ctx.sh(g + ["describe", "--tags", "--exact-match"], 10)
        cur = cur.strip() if rc3 == 0 else ""
        if not cur:
            return warn("detached, no tag found", "spark update")
        if not newest or cur == newest:
            return ok("at %s (the newest release)" % cur)
        return warn("at %s, %s is out -- spark update" % (cur, newest), "spark update")
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
        return warn(", ".join(problems), "commit and push, or spark update" + ("" if ctx.fetch else "   (--fetch to ask origin)"))
    return ok("clean and level with origin")


@row("SOFTWARE", fixture=False,
     reason="the good fixture is on main, where the row is na by design; tests/update_test.sh proves the flip")
def row_signed(ctx):
    """The tag this checkout sits on was signed by a key in the tree's
    allowed-signers -- the promise `spark update` keeps by moving to no
    other tag. A branch (a developer clone) has no tag to verify."""
    g = ["git", "-C", ctx.repo]
    rc, _ = ctx.sh(g + ["rev-parse", "--git-dir"], 10)
    if rc != 0:
        return na("not a git repository: no tag to verify")
    rc, branch = ctx.sh(g + ["symbolic-ref", "-q", "--short", "HEAD"], 10)
    if rc == 0:
        return na("on %s: a developer clone, no tag to verify" % branch.strip())
    rc, cur = ctx.sh(g + ["describe", "--tags", "--exact-match"], 10)
    if rc != 0:
        return na("detached at an untagged commit: no tag to verify")
    cur = cur.strip()
    from .update import verified
    who, why = verified(cur, ctx.repo)
    if who:
        return ok("%s signed by %s" % (cur, who))
    if why.startswith("not signed"):
        return warn("%s is not signed: spark update refuses unsigned tags" % cur,
                    "release it signed: git tag -s   (CLAUDE.md, Releasing)")
    return warn("%s %s" % (cur, why), "openssh and git >= 2.34 verify a release tag")


@row("SOFTWARE")
def row_hooks(ctx):
    rc, out = ctx.sh(["git", "-C", ctx.repo, "config", "core.hooksPath"], 10)
    # relative or absolute, the same directory is the same promise
    want = os.path.join(ctx.repo, ".githooks")
    got = out.strip()
    if rc == 0 and (got == ".githooks" or os.path.abspath(os.path.join(ctx.repo, got)) == want):
        return ok("commits gated by .githooks")
    return fail("core.hooksPath is not .githooks", "./bootstrap.sh   (or: git -C %s config core.hooksPath .githooks)" % ctx.short(ctx.repo))


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
RUNIT_NOT_LIVE = "runit is not running here (a container): the services wait for a machine that boots"


def _runit_user(ctx, unit):
    """(enabled, active) for a runit service dir, in the systemd row's
    vocabulary: enabled = no `down` file and a runsv watching it, disabled
    = a `down` file, not-found = no dir (or nobody supervising it); active
    = `sv status` says run."""
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
    return en, "active" if st == "run" else "inactive"


@row("SOFTWARE")
def row_services(ctx):
    if IS_MAC:
        dom = "gui/%d" % os.getuid()
        rc, disabled = ctx.sh(["launchctl", "print-disabled", dom], 10)
        agents = os.path.join(ctx.home, "Library", "LaunchAgents")
        parts, worst = [], OK

        def state(label):
            # a LaunchDaemon (spark headless on) lives in root's system/ domain
            rc, _ = ctx.sh(["launchctl", "print", "system/" + label], 10)
            if rc == 0:
                return "daemon"
            if '"%s" => disabled' % label in disabled or '"%s" => true' % label in disabled:
                return "disabled"
            rc, _ = ctx.sh(["launchctl", "print", "%s/%s" % (dom, label)], 10)
            if rc == 0:
                return "loaded"
            return "installed" if os.path.exists(os.path.join(agents, label + ".plist")) else "absent"
        s = state("spark.check")
        parts.append("check %s" % {"daemon": "loaded (daemon)"}.get(s, s))
        if s not in ("loaded", "daemon"):
            worst = FAIL
        s = state("spark.serve")
        parts.append("serve %s" % {"loaded": "loaded", "daemon": "loaded (daemon)", "disabled": "disabled on purpose", "absent": "on demand", "installed": "installed, not loaded"}[s])
        if s == "installed":
            worst = FAIL
        # the FORGE: absent or disabled is "off" (SPARK_FORGE=off, or auto
        # with nothing served); a plist that sits there unloaded is broken
        s = state("spark.forge")
        parts.append("forge %s" % {"loaded": "loaded", "daemon": "loaded (daemon)", "installed": "installed, not loaded"}.get(s, "off"))
        if s == "installed":
            worst = FAIL
        remedy = "./bootstrap.sh" if worst == FAIL else ""
        return Row(worst, SEP.join(parts), remedy)
    from . import engine
    runit = init_shape() == "runit"
    if runit:
        # runit: the three service dirs under the user's runsvdir; without
        # a booted /var/service (a container) there is nobody to ask
        if not runit_live():
            return na(RUNIT_NOT_LIVE)
        en, ac = _runit_user(ctx, "check")
        parts = ["check service %s, %s" % (en, ac)]
    else:
        en, ac = _systemd_user(ctx, "spark-check.timer")
        if not en:
            if is_wsl():
                return na("no user systemd session (WSL 2)", "[boot] systemd=true in /etc/wsl.conf; wsl --shutdown from Windows; ./bootstrap.sh")
            return na("no user systemd session (headless or container)")
        parts = ["check timer %s, %s" % (en, ac)]
    worst, remedies = OK, []
    if en != "enabled" or ac != "active":
        worst = FAIL
    sen, sac = _runit_user(ctx, "serve") if runit else _systemd_user(ctx, "spark-serve.service")
    if sen == "enabled":
        if sac != "active":
            if engine.server_pids(ctx.cfg.port):
                parts.append("serve unit inactive; a hand-started server answers")
                remedies.append("spark serve off; %s   (to hand it back to the unit)"
                                % ("sv up " + ctx.short(engine.service_dir("serve")) if runit else "systemctl --user start spark-serve"))
            else:
                parts.append("serve %s" % sac)
                remedies.append(engine.restart_line("serve"))
            worst = WARN if worst == OK else worst
        else:
            parts.append("serve active")
    elif sen == "disabled":
        parts.append("serve disabled on purpose")
    else:
        parts.append("serve on demand")
    # the FORGE: enabled and running, enabled but down (warn), or off
    fen, fac = _runit_user(ctx, "forge") if runit else _systemd_user(ctx, "spark-forge.service")
    if fen == "enabled":
        parts.append("forge %s" % ("active" if fac == "active" else fac))
        if fac != "active":
            remedies.append(engine.restart_line("forge"))
            worst = WARN if worst == OK else worst
    else:
        parts.append("forge off")
    remedy = "./bootstrap.sh" if worst == FAIL else "; ".join(remedies) if worst == WARN else ""
    return Row(worst, SEP.join(parts), remedy)


# ---------------------------------------------------------- CAPABILITY rows
# What the world offers today. These never fail: the exit code is for what
# the repository promises, and a capability is not a promise.
@row("CAPABILITY")
def row_ai(ctx):
    from . import engine
    parts, missing = [], []
    b = engine.engine_bin(ctx.cfg)
    if b:
        parts.append("engine %s" % ctx.short(os.path.dirname(b)))
    else:
        missing.append("llama-server")
    m = engine.model_file(ctx.cfg)
    e = engine.model_file(ctx.cfg, "ember")
    if m and e:
        parts.append("spark %s %.1f GB, ember %s %.1f GB" % (
            engine.model_stem(m), os.path.getsize(m) / 2**30, engine.model_stem(e), os.path.getsize(e) / 2**30))
    elif m:
        parts.append("model %s (%.1f GB)" % (engine.model_stem(m), os.path.getsize(m) / 2**30))
    else:
        missing.append("a model in %s" % ctx.short(ctx.cfg.models_dir))
    if m and not e and engine.chosen_model_name(ctx.cfg, "ember"):
        missing.append("the chat model %s" % engine.chosen_model_name(ctx.cfg, "ember").replace(".gguf", ""))
    if not which("spark"):
        missing.append("spark on PATH")
    if missing:
        return warn("missing: %s" % ", ".join(missing), "./bootstrap.sh   (or SITE_AI_MODEL / SPARK_ENGINE_DIR in your config)")
    return ok(SEP.join(parts))


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
        return warn("sha256 mismatch: %s -- spark model rm %s; spark model %s" % (names, bad[0]["name"], bad[0]["name"]))
    age = _short_age(time.time() - min(r["at"] for r in rows))
    return ok("%d files, sha256 ok (checked %s)" % (len(rows), age))


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
        return warn("missing: %s" % " ".join(absent), "sh install.sh")
    # the rc hook: the one marked line in the rc file, or not
    shell = site.login_shell()
    state, rc = site.rc_hook_state(shell)
    if state == "missing":
        if rc is None:
            return warn("shell %s: no prompt line for it" % shell, "bash 4+ or zsh hosts one (chsh -s /bin/zsh)")
        return warn("%s lacks the spark line" % ctx.short(rc), "./bootstrap.sh   (row rc), or paste: " + site.RC_LINE[shell])
    via = "%s (hook)" % ctx.short(rc)
    live = cli.live_widgets()
    if os.path.exists(OFF_FLAG):
        return na("switched off on purpose (spark on)")
    if not live:
        if ctx.cfg.headless:
            return na("headless: no interactive shell open (the prompt works when one is)")
        return warn("no shell has sourced the prompt line", "open a new shell (the rc file sources ~/.config/spark/widget.*)")
    url, model = _brain(ctx)
    who = ", ".join("%s %d" % (s, p) for s, p in live[:3])
    if not url:
        return na("prompt line in %s -- %s" % (who, model), model)
    return ok("%s; prompt line in %s -- %s at %s" % (via, who, model, url.split("//")[-1]))


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
        return warn("no exit-code hook in: %s" % ", ".join(stale), "sh install.sh")
    if os.path.exists(OFF_FLAG):
        return na("switched off on purpose (spark on)")
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
        return warn("%d shell(s) predate the exit-code hook" % old, "exec $SHELL there")
    if not armed:
        if ctx.cfg.headless:
            return na("headless: no interactive shell open (armed when one is)")
        return warn("no shell has sourced the prompt line", "open a new shell")
    return ok("armed in %s -- a nonzero exit offers explain (Esc s)" % ", ".join(armed[:3]))


@row("CAPABILITY")
def row_completion(ctx):
    """TAB completion: the two files install.sh links, each hook sourcing
    its own. Static verbs always; theme and model names offline, from the
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
        return warn("missing: %s" % ", ".join(missing), "sh install.sh")
    return ok("bash and zsh: the verbs, their words, theme and model names")


@row("CAPABILITY")
def row_serve(ctx):
    from . import SERVE_URL_FILE, engine, lan_ip, wire
    tok = ctx.cfg.token_file
    if os.path.exists(tok) and os.stat(tok).st_mode & 0o077:
        return warn("token file is not 0600", "chmod 600 %s" % ctx.short(tok))
    st = engine.service_state(ctx.cfg)
    url = wire.serve_url()
    if not url:
        return na({"loaded": "managed, but has not written serve-url yet", "disabled": "disabled on purpose",
                   "absent": "on demand, not running"}[st], "spark serve" if st != "disabled" else "")
    h = wire.health(url)
    host = url.split("//")[-1].split(":")[0]
    if h == "ok":
        ip = lan_ip()
        if ip and host not in (ip, "127.0.0.1", "localhost"):
            return warn("moved: serving on %s but the LAN address is now %s (DHCP)" % (host, ip),
                        "spark serve off; spark serve on" if st == "absent" else "restart the unit")
        try:
            served = wire.models(ctx.cfg, url)
        except wire.BrainError:
            served = []
        stem = next((s for a, s, _l in served if a == "spark"), served[0][1] if served else "?")
        shape = "router, %d models" % len(served) if len(served) > 1 else "single"
        where = "serving at %s (%s, %s" % (url.split("//")[-1], stem, shape)
        argv = engine.live_args(ctx.cfg)
        if argv is None:
            return ok(where + ")")
        cache = engine.host_cache(argv)
        if cache == "0":
            return ok(where + ", no host cache)")
        if cache and "--cache-ram" in ctx.cfg.extra_args:
            return ok(where + ", host cache %s MiB from SPARK_EXTRA_ARGS)" % cache)
        return warn(where + ") but the prompt cache in RAM is on: an older start",
                    "spark serve off; spark serve on" if st == "absent" else "restart the unit")
    if h == "loading":
        return warn("loading the model at %s" % url.split("//")[-1])
    return warn("serve-url says %s but nothing answers" % url.split("//")[-1], "spark serve off   (clears it)")


@row("CAPABILITY")
def row_forge(ctx):
    from . import engine, forge_url, lan_ip, wire
    url = forge_url()
    if not url:
        if ctx.cfg.forge == "off":
            return na("off on purpose (spark forge on)")
        return na("not started (spark forge on)")
    problems, loose = [], []
    tok = ctx.cfg.forge_token_file
    if not os.path.exists(tok) or os.stat(tok).st_mode & 0o077:
        problems.append("forge-token is not 0600")
        loose.append(ctx.short(tok))
    if "0.0.0.0" in url:
        problems.append("bound to 0.0.0.0")
    if problems:
        return warn("; ".join(problems), "chmod 600 %s; spark forge off; spark forge on   (SPARK_FORGE_HOST picks the address)"
                    % " ".join(loose or [ctx.short(ctx.cfg.forge_token_file)]))
    where = url.split("//")[-1]
    host = where.split(":")[0]
    fh = wire.forge_health(url, timeout=2)
    if isinstance(fh, dict):
        ip = lan_ip()
        if ip and host not in (ip, "127.0.0.1", "localhost"):
            st = engine.forge_service_state(ctx.cfg)
            return warn("moved: serving on %s but the LAN address is now %s (DHCP)" % (host, ip),
                        "spark forge off; spark forge on" if st == "absent" else "restart the unit")
        up = fh.get("upstream") or "down"
        model = os.path.basename(str(fh.get("model") or "-")).replace(".gguf", "")
        value = "at %s, model %s, upstream %s" % (where, model, up)
        if up != "ok":
            return warn(value, "spark serve")
        # a converge that moved the tree leaves the unit serving the OLD
        # code with every row green: the health's version must match
        ver, mine = str(fh.get("version") or ""), version.version()
        if ver and mine and ver != mine:
            return warn("the page's server runs %s, the tree is %s" % (ver, mine),
                        "spark forge off; spark forge on")
        return ok(value)
    if fh is None:
        return warn("forge-url says %s but what answers is not the page's server" % where, "spark forge off; spark forge on")
    return warn("forge-url says %s but nothing answers" % where, "spark forge on   (or spark forge off to forget it)")


@row("CAPABILITY")
def row_ember(ctx):
    from . import engine, mem_total_gb, wire
    pair = engine.chosen_rows(ctx.cfg)
    er = pair.get("ember")
    if ctx.cfg.ember_model == "none" or not er:
        return na("spark answers everything (spark ember NAME adds one)")
    budget = mem_total_gb() * ctx.cfg.ai_budget / 100.0
    need = er[5] + (pair["spark"][5] if pair.get("spark") else 0.0)
    stem = er[1].replace(".gguf", "")
    if need > budget:
        return warn("spark+ember %.0f GB > budget %.0f GB" % (need, budget),
                    "spark ember list   (a pair that fits)")
    if not engine.model_file(ctx.cfg, "ember"):
        return warn("%s not downloaded" % stem, "./bootstrap.sh   (downloads it)")
    url = wire.serve_url()
    if url and wire.health(url) == "ok":
        st = engine.models_status(ctx.cfg, url).get("ember")
        if st and st != "loaded":
            return warn("%s not warm" % stem, "spark serve   (warms it)")
        if st == "loaded":
            return ok("%s, loaded" % stem)
    return ok(stem)


@row("CAPABILITY")
def row_peer(ctx):
    from . import wire
    parts, worst, remedy = [], OK, "off the LAN, or the other machine is down"
    if ctx.cfg.peer_ai_url:
        # a FORGE answers /api/health (and 404 to /health); a raw llama-server the reverse
        host = ctx.cfg.peer_ai_url.split("//")[-1]
        fh = wire.forge_health(ctx.cfg.peer_ai_url)
        if isinstance(fh, dict):
            up = fh.get("upstream", "down")
            h = "ok" if up == "ok" else "up, its model %s" % up
            parts.append("page's server %s %s" % (host, h))
        else:
            h = "down" if fh == "down" else wire.health(ctx.cfg.peer_ai_url)
            parts.append("engine %s %s" % (host, h))
        if h != "ok":
            worst = WARN
        elif isinstance(fh, dict) and ctx.cfg.client:
            # a client of a FORGE keeps its threads under the login the
            # FORGE minted (a client never mints): say whether it holds
            from . import users
            me = users.account()[0]
            if not me:
                parts.append("no login")
                worst, remedy = WARN, "spark user add NAME on %s (the token shows once), then spark user login NAME here" % host
            else:
                st = ctx.cached("peer-login", 300, lambda: _peer_status(ctx.cfg, "/api/threads?n=1"))
                if st in (401, 403):
                    parts.append("login %s rejected" % me)
                    worst, remedy = WARN, "spark user add %s on %s (the token shows once), then spark user login %s here" % (me, host, me)
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
        return na("no peer configured (SITE_PEER_AI_URL / SITE_PEER_SSH)")
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
        return na("no page served here and no other machine named (spark forge on, or spark client URL)")
    where = url.split("//")[-1].rstrip("/")
    if not isinstance(wire.forge_health(url), dict):
        return na("%s is not up as the page's server (the forge and peer rows say why)" % where)
    v = ctx.cached("hardening", 3600, lambda: {"url": url, "gates": wire.probe_gates(url)})
    if not isinstance(v, dict) or v.get("url") != url:     # a moved forge: ask it now, cached next run
        v = {"url": url, "gates": wire.probe_gates(url)}
    gates = [tuple(g) for g in v.get("gates") or []]
    held = [g for g in gates if g[1]]
    if len(held) != len(gates) or not gates:
        broken = [g for g in gates if not g[1]] or [("probe", False, "no gates answered")]
        return warn("%d of %d gates hold at %s -- %s" % (len(held), len(gates), where,
                                                          "; ".join("%s: %s" % (g[0], g[2]) for g in broken[:3])),
                    "spark forge off; spark forge on   (the page's server must be this tree's; spark update)")
    return ok("%d of %d gates hold at %s" % (len(held), len(gates), where))


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


@row("CAPABILITY", fixture=False, reason="looks for a player on this machine's PATH")
def row_audio(ctx):
    """The sounds spark plays (a bell, and what a game of its has): a
    player on PATH -- afplay on macOS, aplay or paplay on Linux -- unless
    quiet audio is on. A capability: never fail."""
    player = next((c for c in (("afplay",) if IS_MAC else ("aplay", "paplay")) if shutil.which(c)), None)
    if ctx.cfg.quiet_audio:
        return na("quiet audio on: spark plays no sound%s" % ((" (%s is here)" % player) if player else ""))
    if player:
        return ok("%s -- sounds play (spark quiet audio on silences them)" % player)
    return warn("no player on PATH: the terminal bell at most", "%s (aplay), or spark quiet audio on" % packages.install_line(["alsa-utils"]))


@row("SOFTWARE", fixture=False, reason="reads /etc")
def row_quiet(ctx):
    # `start` is a config echo (the key IS the behavior): never fail-worthy
    start = "start %s" % ("on" if ctx.cfg.quiet_start else "off")
    if IS_MAC:
        return na("%s; macOS: no motd, no GRUB" % start)
    parts, bad, pending = [start], [], False
    if ctx.cfg.quiet_login:
        try:
            with open("/etc/issue", encoding="utf-8", errors="replace") as f:
                issue = f.read().strip()
        except OSError:
            issue = ""
        quiet = (not os.path.getsize("/etc/motd") if os.path.exists("/etc/motd") else True) \
            and not os.access("/etc/update-motd.d/10-uname", os.X_OK) \
            and issue in ("", "\033[?25h")
        parts.append("login quiet" if quiet else "login LOUD")
        if not quiet:
            bad.append("login")
    else:
        parts.append("login loud")
    from . import site
    if ctx.cfg.quiet_boot and site.no_grub():
        parts.append("boot n/a (%s)" % site.no_grub())
    elif ctx.cfg.quiet_boot and site.boot_shape() == "uki":
        # the promise is spark's cmdline.d drop-in (the words) and no
        # splash left in a preset; the running kernel's line is the LIVE
        # proof, and a machine not yet rebooted is a warn, not a fault
        try:
            with open(site.CMDLINE_DROPIN, encoding="utf-8", errors="replace") as f:
                quiet = f.read().strip() == site.QUIET_WORDS
        except OSError:
            quiet = False
        quiet = quiet and not site.splash_live()
        if not quiet:
            parts.append("boot LOUD")
            bad.append("boot")
        else:
            try:
                with open(os.environ.get("SPARK_PROC_CMDLINE", "/proc/cmdline"), encoding="utf-8", errors="replace") as f:
                    live = "loglevel=3" in f.read()
            except OSError:
                live = True
            parts.append("boot quiet" if live else "boot quiet after a reboot")
            pending = not live
    elif ctx.cfg.quiet_boot:
        # the promise is spark's GRUB drop-in (menu hidden + silent kernel
        # line), proven against the generated grub.cfg when it is readable
        # without root (newer Debians keep it 0600 -- then the drop-in's
        # presence is the best a user process can check; bootstrap's
        # action path verifies as root at write time)
        quiet = (os.path.isfile("/etc/default/grub.d/zz-spark-quiet.cfg")
                 or (site.distro() == "void" and site.grub_marked() == site.GRUB_WANT))
        cfg_path = "/boot/grub/grub.cfg"
        if quiet and os.access(cfg_path, os.R_OK):
            try:
                with open(cfg_path, encoding="utf-8", errors="replace") as f:
                    quiet = "loglevel=3" in f.read()
            except OSError:
                pass
        if not os.path.isfile("/etc/default/grub"):
            quiet = True  # no GRUB here: nothing promised
        parts.append("boot quiet" if quiet else "boot LOUD")
        if not quiet:
            bad.append("boot")
    else:
        parts.append("boot loud")
    if bad:
        return fail(", ".join(parts) + " -- site.env says otherwise", "./bootstrap.sh   (sudo)")
    if pending:
        return warn(", ".join(parts), "sudo systemctl reboot   (the image carries the quiet line; the running kernel does not)")
    return ok(", ".join(parts))


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
    if not live:
        return na("no model served here")
    base = bench.baseline(ctx.cfg)
    if not base:
        return na("no bench yet (spark bench)")
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
        b = bench.baseline_stem(stem)
        if b is None or not b.get("tg"):
            parts.append("%s no bench (spark bench)" % stem)
            continue
        ts = groups.get(stem, [])
        if len(ts) < 3:
            parts.append("%s bench %.1f tok/s, no recent turns yet" % (stem, b["tg"]))
            continue
        mean = sum(t["tg_tps"] for t in ts) / len(ts)
        parts.append("%s %.1f vs %.1f recent vs bench" % (stem, mean, b["tg"]))
        if mean < 0.7 * b["tg"]:
            slow.append(stem)
    if slow:
        return warn("%s -- below 70%% of the bench; on the CPU? (spark stats)" % "; ".join(parts),
                    "spark bench tune show; spark bench --tune")
    return ok("; ".join(parts) + (" tok/s" if any("vs" in p for p in parts) else ""))


@row("CAPABILITY")
def row_gpu(ctx):
    from . import engine
    g = engine.gpu_info()
    build = engine.backend(ctx.cfg)
    if not g:
        if IS_MAC:
            return na("%s build; no root-free GPU counter on macOS" % build)
        if is_wsl():
            return na("%s build; the GPU is not reached through WSL 2 today" % build)
        return na("%s build: no GPU counters in sysfs" % build)
    node = "/dev/dri/renderD128"
    if not IS_MAC and os.path.exists(node) and not os.access(node, os.R_OK | os.W_OK):
        if engine.render_wrap(["x"])[0] == "sg":
            return ok("card present; in the render group since this login -- servers use sg render until you log in again")
        return warn("GPU present but %s is not readable: new servers fall back to the CPU" % node,
                    "./bootstrap.sh adds you to the render group; then log out of every session and in again")
    files = [f for f in engine.roles(ctx.cfg).values() if f and os.path.isfile(f)]
    size = sum(os.path.getsize(f) for f in files)
    vram, gtt = g.get("vram_total", 0), g.get("gtt_total", 0)
    if size and vram and size > vram:
        word = "spark+ember" if len(files) > 1 else "model"
        return warn("%s %.1f GB > VRAM %.1f GB: it spills to GTT (%.1f GB) -- raise the BIOS UMA frame buffer" % (word, size / 2**30, vram / 2**30, gtt / 2**30),
                    "docs/INSTALL.md, per-OS notes; then spark bench")
    chosen = " (SITE_AI_BUILD=%s)" % ctx.cfg.ai_build if ctx.cfg.ai_build in ("cpu", "vulkan") else ""
    return ok("%s: %.1f GB VRAM, %.1f GB GTT, %d%% busy; %s build%s" % (
        g.get("name", "gpu"), vram / 2**30, gtt / 2**30, g.get("busy", 0), build, chosen))


@row("CAPABILITY")
def row_soul(ctx):
    from . import SOUL_FILE, soul
    problems = []
    try:
        st = os.stat(SOUL_FILE)
    except OSError:
        st = None
    if st is None and not ctx.cfg.persona_extra.strip():
        return na("built-in -- spark soul edit makes it yours")
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
            problems.append("%d chars, cut at %d" % (n, soul.SOUL_MAX))
    if ctx.cfg.persona_extra.strip():
        problems.append("SPARK_PERSONA_EXTRA still set")
    if problems:
        return warn("; ".join(problems), "chmod 600 %s; spark soul edit" % ctx.short(SOUL_FILE))
    return ok("yours, %d chars" % n)


@row("CAPABILITY")
def row_memory(ctx):
    from . import MEMORY_FILE, memory
    if not ctx.cfg.memory:
        return na("off (spark memory on)")
    sealed = memory.sealed_exists()
    try:
        st = os.stat(MEMORY_FILE)
    except OSError:
        st = None
    if st is None and not sealed:
        return ok("nothing kept yet (spark memory add ...)")
    problems = []
    if st is not None and st.st_mode & 0o044:
        problems.append("readable by others")
    if st is not None and sealed:
        problems.append("pre-v1.4 plaintext beside the sealed memory")
    facts = memory._all_facts()
    if len(facts) > memory.FACTS_MAX:
        problems.append("%d facts, %d are sent" % (len(facts), memory.FACTS_MAX))
    if any(len(f) > memory.FACT_MAX for f in facts):
        problems.append("a fact over %d chars is cut" % memory.FACT_MAX)
    if sum(len(f) for f in facts) > memory.TOTAL_MAX:
        problems.append("%d chars, %d are sent" % (sum(len(f) for f in facts), memory.TOTAL_MAX))
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
        return ok("nothing weighed yet (%s)" % ", ".join(sorted(ledger.RULES)))
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
        return ok("sealed, empty (%s)" % ", ".join(sorted(ledger.RULES)))
    return ok("sealed, %s (%d of %d)" % (", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())),
                                         total, ledger.TOTAL_MAX))


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
    # a word list is the maintainer's tool, not a promise to a new user: none
    # is fine, and the row says where one would go
    words = ("no banned words (%d watched)" % len(terms)) if terms else \
        ("no word list (optional: %s)" % ctx.short(privacy_terms_file(ctx.cfg)))
    return ok("state 0700, token 0600, site.env private, %s, one address" % words)


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
                    "spark stats --sends; spark brain   (SPARK_BASE_URL / SITE_PEER_AI_URL name the destination)")
    return ok(", ".join("%s to %s" % (stats.kb(b), dest) for _day, dest, b, _n in rows) + " today")


@row("NONFUNCTIONAL")
def row_users(ctx):
    """The named users' sealed stores: every dir 0700, every key file
    0600, every data file carrying the sealed magic, the local login
    consistent. The promise is `eyes only to the owner`; a plaintext file
    inside a user's store is the drift this row exists to catch."""
    from . import ACCOUNT_FILE, ACCOUNT_KEY_FILE, USERS_DIR, users, vault
    names = users.list_users()
    me = users.account()[0]
    if not names and not me:
        return na("no users yet (spark user add NAME)")
    if not names:
        return ok("no store here; this machine is %s" % me)
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
        try:
            data = [os.path.join(d, "threads", f) for f in os.listdir(os.path.join(d, "threads"))]
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
        problems.append("the v1.3 shared ember-token survives (no longer accepted)")
    for p in (ACCOUNT_FILE, ACCOUNT_KEY_FILE):
        if os.path.exists(p) and os.stat(p).st_mode & 0o077:
            problems.append("%s not 0600" % os.path.basename(p))
    if me and not users.exists(me):
        problems.append("login %s has no user here" % me)
    if problems:
        if legacy:
            fix = "spark user claim"
        elif os.path.exists(EMBER_TOKEN_FILE):
            fix = "rm %s -- personal tokens replace it (spark user)" % ctx.short(EMBER_TOKEN_FILE)
        else:
            fix = "chmod 700 %s and its dirs, 600 the files; spark user list" % ctx.short(USERS_DIR)
        return warn("; ".join(problems[:4]), fix)
    who = ("this machine is %s" % me) if me else "no login here"
    return ok("%d user%s, sealed, keys wrapped; %s" % (len(names), "" if len(names) == 1 else "s", who))


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
        return warn("%d%% of %d MB in use" % (pct, total // 1024), "the model may not fit; spark serve off")
    return ok("%d%% of %d MB in use" % (pct, total // 1024))


@row("NONFUNCTIONAL", fixture=False, reason="reads the live disk layout")
def row_encryption(ctx):
    if IS_MAC:
        rc, out = ctx.sh(["fdesetup", "status"], 5)
        if rc == 0 and "On" in out:
            return ok("FileVault on")
        return warn("FileVault off -- the disk reads in plain text if the machine walks", "System Settings > Privacy & Security > FileVault")
    if is_wsl():
        return na("WSL 2: the disk is a Windows file -- BitLocker is Windows's to turn on")
    rc, out = ctx.sh(["lsblk", "-rno", "TYPE"], 5)
    if rc == 0 and "crypt" in out.split():
        return ok("LUKS volume present")
    return warn("no encrypted volume -- the disk reads in plain text if the machine walks", "reinstall with LUKS when this stops being a test bench")


@row("NONFUNCTIONAL", fixture=False, reason="reads live power and login settings")
def row_headless(ctx):
    """A box that is the brain keeps the FORGE up from boot with nobody logged
    in and never sleeps (SITE_HEADLESS=yes; bootstrap applies it)."""
    if not ctx.cfg.headless:
        return na("under your login; spark headless on keeps it up from boot")
    from . import site
    missing = [piece for piece, good, _ in site.headless_facts(ctx.cfg) if not good]
    if missing:
        return warn("missing: " + ", ".join(missing), "./bootstrap.sh   (sudo)")
    if IS_MAC:
        return ok("daemons loaded, never sleeps, wake on LAN")
    if init_shape() == "runit":
        return ok("the supervisor runs from boot; nothing here sleeps on its own")
    return ok("linger, sleep masked, lid ignored")


@row("CAPABILITY", fixture=False, reason="reads the real spark group and the shared token; the group needs root to create")
def row_share(ctx):
    """This box's engine, shared with its other OS users: a `spark` group
    reads a 0640 copy of the api-token (SITE_SHARE=yes; spark share on).
    Never fails -- sharing is opt-in; a stale or mis-permissioned token warns."""
    from . import site
    if not ctx.cfg.share:
        return na("not shared; spark share on lets this machine's OS users in")
    facts = site.share_facts(ctx.cfg)
    bad = [piece for piece, good, _ in facts if not good]
    if bad:
        return warn("check: " + ", ".join(bad), "spark share on   (re-syncs the token; sudo)")
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
            text += ", no security upgrades pending"
    if n > 30:
        return warn(text, packages.upgrade_line())
    return ok(text)


@row("NONFUNCTIONAL")
def row_watchdog(ctx):
    try:
        with open(CHECK_JSON, encoding="utf-8") as f:
            age = time.time() - json.load(f)["ts"]
    except (OSError, ValueError, KeyError):
        return na("no snapshot yet (the timer writes one every 5 min)")
    if age > 3 * 300:
        return warn("last snapshot %d min ago -- the timer is not running" % (age / 60), "./bootstrap.sh   (services)")
    return ok("snapshot %d s ago" % age)


@row("NONFUNCTIONAL", fixture=False, reason="measures this very run")
def row_cost(ctx):
    return ok("%d ms this run" % int((time.time() - ctx.started) * 1000))


# ------------------------------------------------------------------- runner
# the rows WSL 2 answers differently (na or a WSL 2 note, never a fault):
# the selftest's fourth pass, on Linux, proves each says so
WSL_ROWS = ("font", "quiet", "gpu")
# the rows Arch answers differently (na or an Arch note on the half it
# lacks -- the kernel line without a UKI -- never a fault): the selftest's
# fifth pass, on Linux, proves each says so, that the font row is real
# through vconsole.conf and that the packages row answers through pacman
ARCH_ROWS = ("quiet",)
# the rows Void answers differently (na or a Void note on the half it
# lacks -- no GRUB -- never a fault): the selftest's
# sixth pass, on Linux, proves each says so, that the font row is real
# through rc.conf, that the packages row answers through xbps and the
# services row through sv
VOID_ROWS = ("quiet",)
# a client's rows: nothing runs here (SITE_AI_MODEL=none + SITE_PEER_AI_URL),
# so the engine, the units, their snapshot, the local AI, its two servers and
# a second model of its own are na before they look; the peer row is where a
# client's health lives, and `spark ember list` shows what the peer offers
CLIENT_ROWS = ("engine", "services", "watchdog", "ai", "serve", "forge", "ember")


def client_of(cfg):
    return "a client of %s (spark client off serves here again)" % cfg.peer_ai_url.split("//")[-1]


def run_rows(ctx, names=None):
    ctx.started = time.time()
    rows = []
    for spec in SPECS:
        if names and spec.name not in names:
            continue
        try:
            if spec.name in CLIENT_ROWS and ctx.cfg.client:
                r = na(client_of(ctx.cfg))
            else:
                r = spec.fn(ctx)
        except SystemExit:
            raise
        except Exception as e:   # a crashed row is a red row, never a missing one
            log_exc("check row " + spec.name)
            r = fail("crashed: %s" % (str(e).splitlines() or ["?"])[0], "SPARK_DEBUG=1 spark check; see state/debug.log")
        if spec.category == "CAPABILITY" and r.status == FAIL:
            r.status = WARN
        r.name, r.category = spec.name, spec.category
        rows.append(r)
    return rows


def counts(rows):
    return {s: sum(1 for r in rows if r.status == s) for s in (OK, FAIL, WARN, NA)}


def write_snapshot(ctx, rows):
    try:
        state_dir()
        with open(CHECK_JSON, "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time()), "name": ctx.cfg.name, "version": version.version(),
                       "counts": counts(rows),
                       "rows": [{"category": r.category, "status": r.status, "name": r.name,
                                 "value": r.value, "remedy": r.remedy} for r in rows]}, f)
    except OSError:
        pass


def render(ctx, rows, color):
    c = counts(rows)

    def paint(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color else s
    where = ctx.cfg.name + (SEP + "WSL 2" if is_wsl() else "")
    out = ["%s check %s%son %s%s%s" % (paint("1", MARK), version.version(), SEP, where, SEP, time.strftime("%Y-%m-%d %H:%M"))]
    for cat in CATEGORIES:
        rs = [r for r in rows if r.category == cat]
        if not rs:
            continue
        out.append(paint("1", cat))
        for r in rs:
            out.append("  %s %-11s %s" % (paint(COLOR[r.status], GLYPH[r.status]), r.name, r.value))
            if r.remedy and r.status != OK:
                out.append("    %s %s" % (paint("2", glyph("arrow")), r.remedy))
    out.append("%s %d  %s %d  %s %d  %s %d" % (paint("32", GLYPH[OK]), c[OK], paint("31", GLYPH[FAIL]), c[FAIL],
                                                paint("33", "!"), c[WARN], paint("2", GLYPH[NA]), c[NA]))
    return "\n".join(out)


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
    # a palette for the theme row: SITE_THEME=fixture below; the good
    # machine's theme.env matches it, the bad one's is stale
    os.makedirs(os.path.join(repo, "themes"))
    fixture_theme = ["%s=#%06x" % (k, 0x101010 + n) for n, k in enumerate(
        ["THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED"] + ["THEME_ANSI_%d" % i for i in range(16)])]
    # the good machine keeps the palette as its own (~/.config/spark/themes/),
    # the bad one in the repository: the row must find it in either place
    pal_dir = os.path.join(home, ".config", "spark", "themes") if good else os.path.join(repo, "themes")
    os.makedirs(pal_dir, exist_ok=True)
    with open(os.path.join(pal_dir, "fixture.env"), "w") as f:
        f.write("\n".join(fixture_theme) + "\n")
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
        f.write("SITE_THEME=fixture\n")     # the theme row: applied (good) or stale (bad)
        if IS_MAC:                      # a face every Mac ships: the font row judges an installed face, not Spotlight's index
            f.write("SITE_FONT_FACE=Menlo-Regular\nSITE_FONT_SIZE=13\n")
        else:                           # the console font: console-setup's file (below) agrees (good) or not (bad)
            f.write("SITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\n")
        if good:
            f.write("SITE_EMBER_MODEL=auto\n")     # the default is none; auto fits an ember beside the spark row
        else:
            f.write("SITE_EMBER_MODEL=qwen3-30b-a3b\n")     # 21 GB: over the bad fixture's budget
    os.chmod(os.path.join(home, ".config", "spark", "site.env"), 0o600 if good else 0o644)
    # the good marker carries contract 6's fourth field (the exit-code
    # hook is armed); the bad one is a pre-hook shell -- the failure row
    with open(os.path.join(state, "widgets", str(os.getpid())), "w") as f:
        f.write("bash %d %d%s\n" % (os.getpid(), int(time.time()), " hook" if good else ""))
    with open(os.path.join(state, "check.json"), "w") as f:
        json.dump({"ts": int(time.time()) - (10 if good else 3600), "counts": {}, "rows": []}, f)
    # throughput: a baseline and three turns near it (good) or at 30 % of it (bad)
    with open(os.path.join(state, "bench.jsonl"), "w") as f:
        f.write(json.dumps({"ts": "2000-01-01 00:00:00", "model": "fixture.gguf", "engine": engine,
                            "settings": "ngl=999 fa=auto kv=f16 t=auto", "size": "full", "pp": 100.0, "tg": 12.0}) + "\n")
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
    # the theme: the good machine's theme.env matches themes/fixture.env
    # and console-colors is in place; the bad one's theme.env is stale
    cfgd = os.path.join(home, ".config", "spark")
    with open(os.path.join(cfgd, "theme.env"), "w") as f:
        if good:
            f.write("\n".join(fixture_theme) + "\n")
        else:
            f.write("\n".join(["THEME_BG=#000000"] + fixture_theme[1:]) + "\n")
    with open(os.path.join(cfgd, "console-colors"), "w") as f:
        f.write("".join("\033]P%x101010" % i for i in range(16)) + "\n")
    with open(os.path.join(cfgd, "console-colors.rgb"), "w") as f:
        f.write(("16," * 15 + "16\n") * 3)
    # the console font files, pinned: console-setup's (the good machine's
    # face and size, the bad one's another), vconsole.conf's for the Arch
    # pass (the same face, FONT= alone) and rc.conf's for the Void pass
    # (FONT= quoted, as Void ships it, under a commented KEYMAP); the shape
    # is which exists. The runit dirs beside them: runit/ says the init,
    # service/ says it is booted -- every pass but the sixth points
    # SPARK_ETC_RUNIT at a dir that is not there and stays systemd
    with open(os.path.join(root, "console-setup"), "w") as f:
        f.write('CHARMAP="UTF-8"\nFONTFACE="%s"\nFONTSIZE="16x32"\n' % ("Terminus" if good else "VGA"))
    with open(os.path.join(root, "vconsole.conf"), "w") as f:
        f.write("KEYMAP=us\nFONT=%s\n" % ("Terminus" if good else "default8x16"))
    with open(os.path.join(root, "rc.conf"), "w") as f:
        f.write('#KEYMAP="us"\nFONT="%s"\n' % ("Terminus" if good else "default8x16"))
    os.makedirs(os.path.join(root, "runit"))
    os.makedirs(os.path.join(root, "service"))
    # the live kernel palette the theme row compares with (sysfs, pinned)
    os.makedirs(os.path.join(root, "vt"))
    for ch in ("red", "grn", "blu"):
        with open(os.path.join(root, "vt", "default_" + ch), "w") as f:
            f.write("16," * 15 + "16\n")
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
        # the ledger in the clear: the row that watches it must go red
        with open(os.path.join(udir, "ledger"), "w") as f:
            f.write(json.dumps({"kind": "ask", "name": "plan.md", "ts": "2000-01-01 00:00:00",
                                "note": "who decides?"}) + "\n")
        os.chmod(os.path.join(udir, "ledger"), 0o644)
        vault.write_private(os.path.join(state, "account"), b"name=fixture\ntoken=fixture-token\n")
    if not good:
        with open(os.path.join(cfgd, "spark.env"), "w") as f:
            f.write("SPARK_PERSONA_EXTRA=old\n")
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
            "SPARK_PROC_VERSION": os.path.join(root, "version"), "SPARK_SYSFS_VT": os.path.join(root, "vt"),
            "SPARK_OS_RELEASE": os.path.join(root, "os-release"),
            "SPARK_ETC_CONSOLE_SETUP": os.path.join(root, "console-setup"), "SPARK_ETC_VCONSOLE": os.path.join(root, "vconsole.conf"),
            "SPARK_ETC_RCCONF": os.path.join(root, "rc.conf"), "SPARK_ETC_RUNIT": os.path.join(root, "no-runit"),
            "SPARK_VAR_SERVICE": os.path.join(root, "service"),
            "SPARK_MAC_FONTS": "Menlo-Regular" if good else "",     # macOS: the font row's installed faces, pinned
            "SPARK_MEM_TOTAL_GB": "16" if good else "8", "SHELL": "/bin/zsh" if IS_MAC else "/bin/bash",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _stub_server():
    """A fake llama-server on loopback for the good fixture: /health 200,
    /v1/models with a bearer; and a fake FORGE at /api/health."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/health":
                body = b'{"status":"ok"}'
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


def selftest():
    """Run the check against a good and a bad fixture; every fixture-testable
    row must be ok in the good one and not ok in the bad one. A third
    pass, the good fixture as a client of the stub, must make every
    client row na; a fourth, on Linux, the good fixture under WSL 2:
    every WSL row says so; a fifth under ID=arch likewise; a sixth under
    ID=void, where the services row answers through sv and the font row
    through rc.conf."""
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
        # the fourth pass, Linux only: the good fixture under WSL 2 (a kernel
        # line naming microsoft) -- font, quiet and gpu say so, never fail
        results["wsl"] = {}
        if not IS_MAC:
            root = os.path.join(tmp, "wsl")
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, True, stub_url))
            with open(os.path.join(root, "version"), "w") as f:
                f.write("Linux version 6.6.87.2-microsoft-standard-WSL2 (root@fixture) #1 SMP\n")
            env["SITE_QUIET_BOOT"] = "yes"                          # the boot half is what WSL lacks
            env["SPARK_SYSFS_DRM"] = os.path.join(root, "nodrm")    # no DRM card: WSL shows /dev/dxg
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    results["wsl"][parts[2]] = (parts[1], parts[3])
        # the fifth pass, Linux only: the good fixture as Arch (ID=arch in
        # os-release, a pacman stub, vconsole.conf and no console-setup) --
        # quiet says so on the half Arch lacks, never fails; the font row is
        # ok through vconsole.conf; the packages row answers through pacman
        results["arch"] = {}
        if not IS_MAC:
            root = os.path.join(tmp, "arch")
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, True, stub_url))
            with open(os.path.join(root, "os-release"), "w") as f:
                f.write('ID=arch\nPRETTY_NAME="Arch Linux"\n')
            env["SITE_QUIET_BOOT"] = "yes"                          # the boot half Arch leaves alone (no UKI in the fixture)
            env["SPARK_ETC_CONSOLE_SETUP"] = os.path.join(root, "none")   # the vconsole shape: FONT= in vconsole.conf
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    results["arch"][parts[2]] = (parts[1], parts[3])
        # the sixth pass, Linux only: the good fixture as Void (ID="void" in
        # os-release, xbps and sv stubs, /etc/runit and /var/service dirs,
        # rc.conf with neither console-setup nor vconsole.conf, spark-check's
        # service dir present without a `down` file, no /etc/default/grub) --
        # quiet says so on the half that Void lacks, never fails; the font row is ok through rc.conf;
        # the packages row answers through xbps and the services row through sv
        results["void"] = {}
        if not IS_MAC:
            root = os.path.join(tmp, "void")
            os.makedirs(root)
            env = dict(base)
            env.update(make_fixture(root, True, stub_url))
            with open(os.path.join(root, "os-release"), "w") as f:
                f.write('ID="void"\nPRETTY_NAME="Void Linux"\n')
            env["SITE_QUIET_BOOT"] = "yes"                          # the boot half a Void without GRUB lacks
            env["SPARK_ETC_DEFAULT_GRUB"] = os.path.join(root, "none")   # a runner's own GRUB is not this Void's
            env["SPARK_ETC_CONSOLE_SETUP"] = os.path.join(root, "none")
            env["SPARK_ETC_VCONSOLE"] = os.path.join(root, "none")    # the rcconf shape: FONT= in rc.conf beside /etc/runit
            env["SPARK_ETC_RUNIT"] = os.path.join(root, "runit")
            env["SPARK_VAR_SERVICE"] = os.path.join(root, "service")
            os.makedirs(os.path.join(root, "home", ".config", "spark", "sv", "spark-check"))   # supervised, no `down`
            p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                               env=env, capture_output=True, text=True, timeout=180)
            for line in p.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 5:
                    results["void"][parts[2]] = (parts[1], parts[3])
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
        font = results["arch"].get("font", ("missing", ""))
        font_ok = font[0] == OK and "vconsole.conf" in font[1]
        say("  %s arch: %d rows say Arch, packages %s via pacman, font %s via vconsole.conf%s"
            % (GLYPH[OK] if not off and pk == OK and font_ok else GLYPH[FAIL], len(ARCH_ROWS) - len(off), pk, font[0],
               "" if not off else "   not so: " + " ".join(off)))
        bad += bool(off) or pk != OK or not font_ok
    if IS_MAC:
        say("  %s void: skipped on macOS (a Linux gate proves it)" % GLYPH[NA])
    else:
        off = [n for n in VOID_ROWS
               if results["void"].get(n, ("missing", ""))[0] not in (NA, OK) or "Void" not in results["void"].get(n, ("", ""))[1]]
        pk = results["void"].get("packages", ("missing", ""))[0]
        font = results["void"].get("font", ("missing", ""))
        font_ok = font[0] == OK and "rc.conf" in font[1]
        svc = results["void"].get("services", ("missing", ""))[0]
        say("  %s void: %d rows say Void, packages %s via xbps, font %s via rc.conf, services %s via sv%s"
            % (GLYPH[OK] if not off and pk == OK and font_ok and svc == OK else GLYPH[FAIL], len(VOID_ROWS) - len(off), pk, font[0], svc,
               "" if not off else "   not so: " + " ".join(off)))
        bad += bool(off) or pk != OK or not font_ok or svc != OK
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
USAGE = """%s check -- this machine against what its repository says

  spark check              every row; exit 0 when no row failed
  spark check --watch N    redraw every N seconds
  spark check --porcelain  category<TAB>status<TAB>name<TAB>value<TAB>remedy
  spark check --report     a block to paste into an issue: version, OS,
                           backend, model stems and every row's status --
                           never a value, a path, a name
  spark check --fresh      ignore cached answers (brew, git fetch results)
  spark check --fetch      ask origin before judging the git row
  spark check --selftest   prove every fixture-testable row can flip
  spark check --chaos      break a throwaway machine one known way at a
                           time; the right row must say so and its remedy
                           must heal it
""" % MARK


def main(argv):
    watch, porcelain_out, report_out, fresh, fetch, names = 0, False, False, False, False, []
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help", "help"):
            say(USAGE.rstrip())
            return 0
        if a == "--watch":
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
        elif a.startswith("--"):
            say(USAGE.rstrip())
            return 2
        else:
            names.append(a)
    ctx = Ctx(fresh=fresh, fetch=fetch)
    color = sys.stdout.isatty() and not porcelain_out
    while True:
        rows = run_rows(ctx, names or None)
        write_snapshot(ctx, rows)
        if report_out:
            page(report(ctx, rows))
            return 1 if any(r.status == FAIL for r in rows) else 0
        text = porcelain(rows) if porcelain_out else render(ctx, rows, color)
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
