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

from . import (BIN_DIR, CACHE_DIR, CHECK_JSON, HOME, IS_MAC, MARK, OS, REPO,
               STATE_DIR, config, glyph, log_exc, page, run, say, state_dir, version)

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

    def sh(self, cmd, timeout=10):
        return run(cmd, timeout=timeout)

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
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"t": time.time(), "v": v}, f)
        except OSError:
            pass
        return v

    def short(self, path):
        return "~" + path[len(self.home):] if path.startswith(self.home + "/") else path


# ------------------------------------------------------------ SOFTWARE rows
@row("SOFTWARE")
def row_packages(ctx):
    rc, out = ctx.sh(["sh", os.path.join(ctx.repo, "bootstrap.sh"), "--list-packages"], 30)
    if rc != 0:
        return fail("bootstrap.sh --list-packages failed", "sh %s --list-packages" % ctx.short(os.path.join(ctx.repo, "bootstrap.sh")))
    pkgs = out.split()
    if not pkgs:
        return ok("nothing required (SITE_SHELL=off)")
    if IS_MAC:
        brewfile = os.path.join(ctx.repo, "Brewfile")

        def check():
            rc, _ = run(["brew", "bundle", "check", "--file", brewfile, "--no-upgrade"], timeout=120)
            return rc
        rc = ctx.cached("brew-bundle", 300, check)
        if rc == -1:
            return fail("brew not found", "install Homebrew, then ./bootstrap.sh")
        if rc != 0:
            return fail("Brewfile has unmet entries", "brew bundle --file %s" % ctx.short(brewfile))
        return ok("Brewfile satisfied (%d entries)" % len(pkgs))
    rc, out = ctx.sh(["dpkg-query", "-W", "-f", "${Package} ${Status}\n"] + pkgs, 30)
    if rc == -1:
        return fail("dpkg-query not found", "./bootstrap.sh")
    have = {l.split()[0] for l in out.splitlines() if l.endswith("install ok installed")}
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
    elif d in ("/opt/homebrew/bin", "/usr/local/bin"):
        name, where = d, "Homebrew"
    elif os.path.dirname(d) == ENGINE_DIR:
        name, where = os.path.basename(d), ctx.short(ENGINE_DIR)
    else:
        name, where = ctx.short(d), ""
    build = engine.backend(ctx.cfg)
    if not ctx.cfg.engine_dir and flavour.startswith("ubuntu-") and ("vulkan" in flavour) != (build == "vulkan"):
        return warn("%s is the %s build, but the build here is %s now" % (name, "vulkan" if "vulkan" in flavour else "cpu", build),
                    "./bootstrap.sh   (replaces the engine)")
    return ok(" ".join(x for x in (name, flavour, "(%s)" % where if where else "") if x))


@row("SOFTWARE")
def row_pinned(ctx):
    """The shell layer's pinned pieces: starship and micro's aspell plugin
    (llama-server is the engine row's). Linux fetches them by version and
    sha256; on macOS Homebrew provides starship, so bootstrap skips the pin."""
    missing = []
    if not which("starship"):
        missing.append("starship")
    if not os.path.isdir(os.path.join(ctx.home, ".config", "micro", "plug", "aspell")):
        missing.append("micro-aspell")
    if missing:
        return fail("missing: %s" % " ".join(missing), "brew bundle --file Brewfile; ./bootstrap.sh" if IS_MAC else "./bootstrap.sh")
    return ok("starship (Homebrew), micro-aspell" if IS_MAC else "starship, micro-aspell")


def _font_dirs(home):
    if IS_MAC:
        return [os.path.join(home, "Library", "Fonts"), "/Library/Fonts"]
    return [os.path.join(home, ".local", "share", "fonts"), "/usr/share/fonts", "/usr/local/share/fonts"]


@row("SOFTWARE")
def row_font(ctx):
    where = ""
    for d in _font_dirs(ctx.home):
        for root, _dirs, files in os.walk(d):
            if any("JetBrainsMono" in f and "Nerd" in f for f in files):
                where = root
                break
        if where:
            break
    if not where:
        return fail("JetBrainsMono Nerd Font not installed", "./bootstrap.sh; then pick it in your terminal's settings")
    if not IS_MAC and ctx.cfg.font_face:
        want = "%s %s" % (ctx.cfg.font_face, ctx.cfg.font_size)
        cur = ""
        try:
            with open("/etc/default/console-setup", encoding="utf-8") as f:
                kv = dict(l.strip().split("=", 1) for l in f if "=" in l and not l.startswith("#"))
            cur = "%s %s" % (kv.get("FONTFACE", "").strip('"'), kv.get("FONTSIZE", "").strip('"'))
        except (OSError, ValueError):
            pass
        if cur != want:
            return fail("console font is %s, site.env says %s" % (cur or "unset", want), "./bootstrap.sh   (sudo)")
        return ok("Nerd Font in %s; console %s" % (ctx.short(where), want))
    return ok("JetBrainsMono Nerd Font in %s" % ctx.short(where))


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


THEME_KEYS = (["THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED", "THEME_BTOP"]
              + ["THEME_ANSI_%d" % i for i in range(16)])


@row("SOFTWARE")
def row_theme(ctx):
    """The chosen palette actually applied: ~/.config/spark/theme.env (what
    tmux, starship, btop, micro and the FORGE page were fed) matches
    themes/<SITE_THEME>.env key for key, and on Linux console-colors (the
    VT palette the rc hook applies) is in place. Core: the theme is chosen
    outside the shell gate. `spark theme NAME` writes all of it."""
    from . import CONFIG_DIR
    name = ctx.cfg.theme
    if name == "none":
        return na("none -- the terminal keeps its own colours (spark theme NAME)")
    want = _env_lines(os.path.join(ctx.repo, "themes", name + ".env"))
    if want is None:
        return fail("SITE_THEME=%s: no themes/%s.env in the repository" % (name, name), "spark theme list")
    have = _env_lines(os.path.join(CONFIG_DIR, "theme.env"))
    if have is None:
        return fail("%s chosen but theme.env was never written" % name, "spark theme %s" % name)
    stale = [k for k in THEME_KEYS if have.get(k) != want.get(k)]
    if stale:
        return fail("%s -- theme.env is stale: %s differ%s" % (name, " ".join(stale[:3]), "s" if len(stale) == 1 else ""),
                    "spark theme %s" % name)
    if not IS_MAC and not os.path.isfile(os.path.join(CONFIG_DIR, "console-colors")):
        return fail("%s -- theme.env current, but no console-colors for the VT" % name, "spark theme %s" % name)
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


@row("SOFTWARE")
def row_hooks(ctx):
    rc, out = ctx.sh(["git", "-C", ctx.repo, "config", "core.hooksPath"], 10)
    if rc == 0 and out.strip() == ".githooks":
        return ok("commits gated by .githooks")
    return fail("core.hooksPath is not .githooks", "./bootstrap.sh   (or: git -C %s config core.hooksPath .githooks)" % ctx.short(ctx.repo))


@row("SOFTWARE")
def row_terminfo(ctx):
    rc, out = ctx.sh(["infocmp", "-1x", "tmux-256color"], 10)
    if rc == -1:
        return warn("infocmp not found", "./bootstrap.sh")
    if rc != 0:
        return (fail if IS_MAC else warn)("no tmux-256color entry", "./bootstrap.sh")
    if "kUP=" not in out:
        return (fail if IS_MAC else warn)("tmux-256color lacks modified arrow keys (Shift+arrow types junk in micro)",
                                          "./bootstrap.sh   (compiles a complete entry into ~/.terminfo)")
    return ok("tmux-256color knows modified arrow keys")


def _systemd_user(ctx, unit):
    """(enabled, active) strings for a user unit; ("", "") when there is
    no user systemd to ask (the same probe bootstrap.sh uses)."""
    rc, _ = ctx.sh(["systemctl", "--user", "show-environment"], 10)
    if rc != 0:
        return "", ""
    rc, en = ctx.sh(["systemctl", "--user", "is-enabled", unit], 10)
    rc, ac = ctx.sh(["systemctl", "--user", "is-active", unit], 10)
    return en.strip() or "not-found", ac.strip() or "inactive"


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
    en, ac = _systemd_user(ctx, "spark-check.timer")
    if not en:
        return na("no user systemd session (headless or container)")
    parts, worst, remedies = ["check timer %s, %s" % (en, ac)], OK, []
    if en != "enabled" or ac != "active":
        worst = FAIL
    sen, sac = _systemd_user(ctx, "spark-serve.service")
    if sen == "enabled":
        if sac != "active":
            from . import engine
            if engine.server_pids(ctx.cfg.port):
                parts.append("serve unit inactive; a hand-started server answers")
                remedies.append("spark stop; systemctl --user start spark-serve   (to hand it back to the unit)")
            else:
                parts.append("serve %s" % sac)
                remedies.append("systemctl --user restart spark-serve; journalctl --user -u spark-serve")
            worst = WARN if worst == OK else worst
        else:
            parts.append("serve active")
    elif sen == "disabled":
        parts.append("serve disabled on purpose")
    else:
        parts.append("serve on demand")
    # the FORGE: enabled and running, enabled but down (warn), or off
    fen, fac = _systemd_user(ctx, "spark-forge.service")
    if fen == "enabled":
        parts.append("forge %s" % ("active" if fac == "active" else fac))
        if fac != "active":
            remedies.append("systemctl --user restart spark-forge; journalctl --user -u spark-forge")
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
        missing.append("the ember %s" % engine.chosen_model_name(ctx.cfg, "ember").replace(".gguf", ""))
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
    # the rc hook: spark's own rc file (a link), the one marked line, or neither
    shell = site.login_shell()
    state, rc = site.rc_hook_state(shell)
    if state == "missing":
        if rc is None:
            return warn("shell %s: no widget for it" % shell, "bash 4+ or zsh hosts one (chsh -s /bin/zsh)")
        return warn("%s lacks the spark line" % ctx.short(rc), "./bootstrap.sh   (row rc), or paste: " + site.RC_LINE[shell])
    via = "%s (%s)" % (ctx.short(rc), "hook" if state == "hook" else "own rc")
    live = cli.live_widgets()
    if os.path.exists(OFF_FLAG):
        return na("switched off on purpose (spark on)")
    if not live:
        if ctx.cfg.headless:
            return na("headless: no interactive shell open (the prompt works when one is)")
        return warn("no shell has sourced the widget", "open a new shell (the rc file sources ~/.config/spark/widget.*)")
    url, model = _brain(ctx)
    who = ", ".join("%s %d" % (s, p) for s, p in live[:3])
    if not url:
        return na("widget in %s -- %s" % (who, model), model)
    return ok("%s; widget in %s -- %s at %s" % (via, who, model, url.split("//")[-1]))


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
def row_shell(ctx):
    """The shell layer: off (the default) is the prompt widget only; on
    means the rc files are spark's own symlinks and starship and tmux are
    on PATH (spark shell on installs them, both OSes)."""
    from . import site
    if not ctx.cfg.shell:
        return na("off -- spark shell on: " + site.SHELL_TOOLS)
    problems = []
    for name in site.RC_FILES:
        if not site._spark_link(os.path.join(ctx.home, name)):
            problems.append("~/%s is not spark's link" % name)
    for tool in ("starship", "tmux"):
        if not which(tool):
            problems.append("no " + tool)
    if problems:
        return warn("on but: " + ", ".join(problems), "spark shell on")
    return ok("on: rc files are spark's; starship, tmux present")


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
                        "spark stop; spark serve" if st == "absent" else "restart the unit")
        try:
            served = wire.models(ctx.cfg, url)
        except wire.BrainError:
            served = []
        stem = next((s for a, s, _l in served if a == "spark"), served[0][1] if served else "?")
        shape = "router, %d models" % len(served) if len(served) > 1 else "single"
        return ok("serving at %s (%s, %s)" % (url.split("//")[-1], stem, shape))
    if h == "loading":
        return warn("loading the model at %s" % url.split("//")[-1])
    return warn("serve-url says %s but nothing answers" % url.split("//")[-1], "spark stop   (clears it)")


@row("CAPABILITY")
def row_forge(ctx):
    from . import EMBER_TOKEN_FILE, engine, forge_url, lan_ip, wire
    url = forge_url()
    if not url:
        if ctx.cfg.forge == "off":
            return na("off on purpose (spark forge on)")
        return na("not started (spark forge start)")
    problems, loose = [], []
    for label, tok in (("forge-token", ctx.cfg.forge_token_file), ("ember-token", EMBER_TOKEN_FILE)):
        if not os.path.exists(tok) or os.stat(tok).st_mode & 0o077:
            problems.append("%s is not 0600" % label)
            loose.append(ctx.short(tok))
    if "0.0.0.0" in url:
        problems.append("bound to 0.0.0.0")
    if problems:
        return warn("; ".join(problems), "chmod 600 %s; spark forge stop; spark forge start   (SPARK_FORGE_HOST picks the address)"
                    % " ".join(loose or [ctx.short(ctx.cfg.forge_token_file)]))
    where = url.split("//")[-1]
    host = where.split(":")[0]
    fh = wire.forge_health(url, timeout=2)
    if isinstance(fh, dict):
        ip = lan_ip()
        if ip and host not in (ip, "127.0.0.1", "localhost"):
            st = engine.forge_service_state(ctx.cfg)
            return warn("moved: serving on %s but the LAN address is now %s (DHCP)" % (host, ip),
                        "spark forge stop; spark forge start" if st == "absent" else "restart the unit")
        up = fh.get("upstream") or "down"
        model = os.path.basename(str(fh.get("model") or "-")).replace(".gguf", "")
        value = "at %s, model %s, upstream %s" % (where, model, up)
        if up != "ok":
            return warn(value, "spark serve")
        return ok(value)
    if fh is None:
        return warn("forge-url says %s but what answers is not a FORGE" % where, "spark forge stop; spark forge start")
    return warn("forge-url says %s but nothing answers" % where, "spark forge start   (or spark forge stop to forget it)")


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
    parts, worst = [], OK
    if ctx.cfg.peer_ai_url:
        # a FORGE answers /api/health (and 404 to /health); a raw llama-server the reverse
        host = ctx.cfg.peer_ai_url.split("//")[-1]
        fh = wire.forge_health(ctx.cfg.peer_ai_url)
        if isinstance(fh, dict):
            up = fh.get("upstream", "down")
            h = "ok" if up == "ok" else "up, its model %s" % up
            parts.append("forge %s %s" % (host, h))
        else:
            h = "down" if fh == "down" else wire.health(ctx.cfg.peer_ai_url)
            parts.append("ai %s %s" % (host, h))
        if h != "ok":
            worst = WARN
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
    return Row(worst, SEP.join(parts), "off the LAN, or the peer is down" if worst == WARN else "")


@row("CAPABILITY")
def row_bar(ctx):
    from . import BAR_CACHE, bar
    rc, _ = ctx.sh(["tmux", "list-sessions"], 5)
    if rc != 0:
        return na("tmux not running")
    rc, out = ctx.sh(["tmux", "show", "-gv", "status"], 5)
    if rc == 0 and out.strip() == "off":
        return na("hidden on purpose (spark bar on)")
    try:
        with open(BAR_CACHE, encoding="utf-8") as f:
            age = time.time() - json.load(f)["t"]
    except (OSError, ValueError, KeyError):
        return warn("the status line has never been drawn", "tmux source-file ~/.tmux.conf")
    if age > 6 * bar.INTERVAL:
        return warn("stale: last tick %ds ago" % age, "tmux source-file ~/.tmux.conf; spark bar line")
    return ok("ticking (last tick %ds ago)" % age)


@row("SOFTWARE", fixture=False, reason="reads /etc")
def row_quiet(ctx):
    # `start` is a config echo (the key IS the behavior): never fail-worthy
    start = "start %s" % ("on" if ctx.cfg.quiet_start else "off")
    if IS_MAC:
        return na("%s; macOS: no motd, no GRUB" % start)
    parts, bad = [start], []
    if ctx.cfg.quiet_login:
        quiet = (not os.path.getsize("/etc/motd") if os.path.exists("/etc/motd") else True) \
            and not os.access("/etc/update-motd.d/10-uname", os.X_OK)
        parts.append("login quiet" if quiet else "login LOUD")
        if not quiet:
            bad.append("login")
    else:
        parts.append("login loud")
    if ctx.cfg.quiet_boot:
        try:
            with open("/etc/default/grub", encoding="utf-8") as f:
                g = f.read()
            quiet = "\nGRUB_TIMEOUT=0\n" in "\n" + g and "GRUB_TIMEOUT_STYLE=hidden" in g
        except OSError:
            quiet = True
        parts.append("boot quiet" if quiet else "boot LOUD")
        if not quiet:
            bad.append("boot")
    else:
        parts.append("boot loud")
    if bad:
        return fail(", ".join(parts) + " -- site.env says otherwise", "./bootstrap.sh   (sudo)")
    return ok(", ".join(parts))


@row("CAPABILITY")
def row_throughput(ctx):
    from . import bench, stats
    base = bench.baseline(ctx.cfg)
    if not base:
        return na("no bench yet (spark bench)")
    recent = [t for t in stats.turns(7) if t.get("tg_tps")][-10:]
    if len(recent) < 3:
        return na("baseline %.1f tok/s; fewer than 3 recent turns to compare" % base["tg"])
    # two models may serve now; judge each turn against its own model's bench
    groups = {}
    for t in recent:
        groups.setdefault(t.get("model", ""), []).append(t)
    parts, slow = [], []
    for stem, ts in sorted(groups.items()):
        b = bench.baseline_stem(stem) if stem else None
        if b is None and len(groups) == 1:
            b = base                      # old records without a model field
        if b is None or not b.get("tg") or len(ts) < 3:
            continue
        mean = sum(t["tg_tps"] for t in ts) / len(ts)
        parts.append("%s %.1f vs %.1f" % (stem or "model", mean, b["tg"]))
        if mean < 0.7 * b["tg"]:
            slow.append(stem or "the model")
    if not parts:
        return na("baseline %.1f tok/s; fewer than 3 recent turns per model" % base["tg"])
    if slow:
        return warn("%s -- below 70%% of the bench; on the CPU? (spark stats)" % "; ".join(parts),
                    "spark tune show; spark bench --tune")
    return ok("; ".join(parts) + " tok/s, recent vs bench")


@row("CAPABILITY")
def row_gpu(ctx):
    from . import engine
    g = engine.gpu_info()
    build = engine.backend(ctx.cfg)
    if not g:
        return na("%s build; no root-free GPU counter on macOS" % build if IS_MAC else "%s build: no GPU counters in sysfs" % build)
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
                    "INSTALL.md, per-OS notes; then spark bench")
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
    try:
        st = os.stat(MEMORY_FILE)
    except OSError:
        return ok("nothing kept yet (spark remember ...)")
    problems = []
    if st.st_mode & 0o044:
        problems.append("readable by others")
    facts = memory._all_facts()
    if len(facts) > memory.FACTS_MAX:
        problems.append("%d facts, %d are sent" % (len(facts), memory.FACTS_MAX))
    if any(len(f) > memory.FACT_MAX for f in facts):
        problems.append("a fact over %d chars is cut" % memory.FACT_MAX)
    if sum(len(f) for f in facts) > memory.TOTAL_MAX:
        problems.append("%d chars, %d are sent" % (sum(len(f) for f in facts), memory.TOTAL_MAX))
    if problems:
        return warn("; ".join(problems), "chmod 600 %s; spark forget N" % ctx.short(MEMORY_FILE))
    return ok("%d fact%s" % (len(facts), "" if len(facts) == 1 else "s"))


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
        return warn("%.0f GB free on / -- critical" % free, "ncdu ~   (or: dust ~)")
    if free < 20:
        return warn("%.0f GB free on /" % free, "dust ~")
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
        problems.append("server bound to 0.0.0.0")
    furl = forge_url()
    if furl and "0.0.0.0" in furl:
        problems.append("forge bound to 0.0.0.0")
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
    # a word list is the maintainer's tool, not a promise to a stranger: none
    # is fine, and the row says where one would go
    words = ("no banned words (%d watched)" % len(terms)) if terms else \
        ("no word list (optional: %s)" % ctx.short(privacy_terms_file(ctx.cfg)))
    return ok("state 0700, token 0600, site.env private, %s, one address" % words)


def _repos(ws):
    out = []
    try:
        for a in sorted(os.listdir(ws)):
            p = os.path.join(ws, a)
            if os.path.isdir(os.path.join(p, ".git")):
                out.append(p)
            elif os.path.isdir(p):
                for b in sorted(os.listdir(p)):
                    q = os.path.join(p, b)
                    if os.path.isdir(os.path.join(q, ".git")):
                        out.append(q)
    except OSError:
        pass
    return out


@row("NONFUNCTIONAL")
def row_backup(ctx):
    repos = _repos(ctx.cfg.workspace)
    if not repos:
        return na("no repositories under %s" % ctx.short(ctx.cfg.workspace))
    unpushed, noremote, dirty = [], [], []
    for r in repos:
        name = os.path.basename(r)
        rc, out = ctx.sh(["git", "-C", r, "status", "--porcelain"], 20)
        if rc == 0 and out.strip():
            dirty.append(name)
        rc, out = ctx.sh(["git", "-C", r, "rev-list", "--count", "@{upstream}..HEAD"], 20)
        if rc != 0:
            noremote.append(name)
        elif int(out.strip() or 0):
            unpushed.append(name)
    parts = []
    if unpushed:
        parts.append("unpushed: %s" % " ".join(unpushed[:4]))
    if noremote:
        parts.append("no remote: %s" % " ".join(noremote[:4]))
    if dirty:
        parts.append("dirty: %s" % " ".join(dirty[:4]))
    if unpushed or noremote:
        return warn("%d repos%s%s" % (len(repos), SEP, "; ".join(parts)), "git push, or add a remote -- a disk is not a backup")
    return ok("%d repos, all pushed%s" % (len(repos), " (%s)" % parts[0] if parts else ""))


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
        return warn("%d%% of %d MB in use" % (pct, total // 1024), "the model may not fit; spark stop")
    return ok("%d%% of %d MB in use" % (pct, total // 1024))


@row("NONFUNCTIONAL", fixture=False, reason="reads the live disk layout")
def row_encryption(ctx):
    if IS_MAC:
        rc, out = ctx.sh(["fdesetup", "status"], 5)
        if rc == 0 and "On" in out:
            return ok("FileVault on")
        return warn("FileVault off -- the disk reads in plain text if the machine walks", "System Settings > Privacy & Security > FileVault")
    rc, out = ctx.sh(["lsblk", "-rno", "TYPE"], 5)
    if rc == 0 and "crypt" in out.split():
        return ok("LUKS volume present")
    return warn("no encrypted volume -- the disk reads in plain text if the machine walks", "reinstall with LUKS when this stops being a test bench")


@row("NONFUNCTIONAL", fixture=False, reason="reads live power and login settings")
def row_headless(ctx):
    """A box that is the brain keeps the FORGE up from boot with nobody logged
    in and never sleeps (SITE_HEADLESS=yes; bootstrap applies it)."""
    if not ctx.cfg.headless:
        return na("a workstation; spark headless on for a brain")
    from . import site
    missing = [piece for piece, good, _ in site.headless_facts(ctx.cfg) if not good]
    if missing:
        return warn("missing: " + ", ".join(missing), "./bootstrap.sh   (sudo)")
    return ok("daemons loaded, never sleeps, wake on LAN" if IS_MAC else "linger, sleep masked, lid ignored")


@row("NONFUNCTIONAL", fixture=False, reason="asks the package manager, cached an hour")
def row_pending(ctx):
    def count():
        if IS_MAC:
            rc, out = run(["brew", "outdated", "--quiet"], timeout=120)
        else:
            rc, out = run(["apt", "list", "--upgradable"], timeout=60)
            out = "\n".join(l for l in out.splitlines() if "/" in l)
        return -1 if rc != 0 else len(out.split())
    n = ctx.cached("pending", 3600, count)
    if n < 0:
        return na("could not ask the package manager")
    if n > 30:
        return warn("%d updates pending" % n, "brew upgrade" if IS_MAC else "sudo apt upgrade")
    return ok("%d updates pending" % n)


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
# The shell layer's rows: with SITE_SHELL=off they are na before they look,
# the same answer bootstrap.sh gives (the `shell` row itself says what on adds).
SHELL_ROWS = ("pinned", "font", "terminfo", "quiet", "bar", "git", "backup", "swap",
              "encryption", "pending", "battery", "disk")
SHELL_OFF = "SITE_SHELL=off (spark shell on)"
# a client's rows: nothing runs here (SITE_AI_MODEL=none + SITE_PEER_AI_URL),
# so the engine, the units, their snapshot, the local AI and its two servers
# are na before they look; the peer row says whether the peer answers
CLIENT_ROWS = ("engine", "services", "watchdog", "ai", "serve", "forge")


def client_of(cfg):
    return "a client of %s (spark client off serves here again)" % cfg.peer_ai_url.split("//")[-1]


def run_rows(ctx, names=None):
    ctx.started = time.time()
    rows = []
    for spec in SPECS:
        if names and spec.name not in names:
            continue
        try:
            if spec.name in SHELL_ROWS and not ctx.cfg.shell:
                r = na(SHELL_OFF)
            elif spec.name in CLIENT_ROWS and ctx.cfg.client:
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
    out = ["%s check %s%son %s%s%s" % (paint("1", MARK), version.version(), SEP, ctx.cfg.name, SEP, time.strftime("%Y-%m-%d %H:%M"))]
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


# ----------------------------------------------------------------- selftest
_STUB_BOOTSTRAP = """#!/bin/sh
case ${1:-} in
  --list-packages) printf 'bash\\ngit\\n' ;;
  --list-tools) printf 'bin/spark\\tspark\\nbin/explain\\texplain\\n' ;;
  --list-models) printf 'none\\n' ;;
  *) echo "Nothing to do" ;;
esac
"""


RC_FIXTURE_LINE = "[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt"


def _stub(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o755)


def make_fixture(root, good, stub_url=""):
    """A throwaway HOME plus a stub repository and stub commands, shaped so
    every fixture-testable row is ok (good=True) or not (good=False).
    stub_url is a fake llama-server the good fixture's rows may reach."""
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
          "#!/bin/sh\n" + ("printf 'ok             %s/.tmux.conf\\nNothing to do\\n' \"$HOME\"\n" if good
                            else "printf 'would link     %s/.tmux.conf\\n1 to do\\n' \"$HOME\"\n"))
    _stub(os.path.join(repo, "bin", "spark"), "#!/bin/sh\necho stub\n")
    os.symlink("spark", os.path.join(repo, "bin", "explain"))
    open(os.path.join(repo, "Brewfile"), "w").close()
    # the rc files spark links with the shell layer on (<os>/home/), stubs
    from . import site
    osdir = os.path.join(repo, "macos" if IS_MAC else "linux", "home")
    os.makedirs(osdir)
    for name in site.RC_FILES:
        with open(os.path.join(osdir, name), "w") as f:
            f.write("# fixture rc\n" + RC_FIXTURE_LINE + "\n")
    with open(os.path.join(repo, "models.env"), "w") as f:
        # the row_models check row hashes the stub .gguf files for real, so
        # both fixtures carry the REAL sha256 of the "x" * 4096 content the
        # model files are written with below (the bad fixture then corrupts
        # one file's bytes, same size, after that write)
        fixture_sha = hashlib.sha256(b"x" * 4096).hexdigest()
        zero_sha = "0" * 64
        f.write('MODEL_FIXTURE="fixture.gguf https://models.invalid/fixture.gguf 4096 %s 1"\n'
                'MODEL_FIXTURE_EMBER="fixture-ember.gguf https://models.invalid/fixture-ember.gguf 4096 %s 2"\n'
                'MODEL_QWEN3_30B_A3B="qwen3-30b-a3b.gguf https://models.invalid/qwen3-30b-a3b.gguf 4096 %s 21"\n'
                % (fixture_sha, fixture_sha, zero_sha))
    # a palette for the theme row: SITE_THEME=fixture below; the good
    # machine's theme.env matches it, the bad one's is stale
    os.makedirs(os.path.join(repo, "themes"))
    fixture_theme = ["%s=#%06x" % (k, 0x101010 + n) for n, k in enumerate(
        ["THEME_BG", "THEME_FG", "THEME_ACCENT", "THEME_MUTED"] + ["THEME_ANSI_%d" % i for i in range(16)])]
    fixture_theme.append("THEME_BTOP=Default")
    with open(os.path.join(repo, "themes", "fixture.env"), "w") as f:
        f.write("\n".join(fixture_theme) + "\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"HOME": home, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    g = ["git", "-C", repo]
    subprocess.run(g + ["init", "-q", "-b", "main"], env=env, check=True)
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
    ws = os.path.join(root, "work")
    os.makedirs(os.path.join(ws, "proj"))
    subprocess.run(["git", "-C", os.path.join(ws, "proj"), "init", "-q", "-b", "main"], env=env, check=True)
    open(os.path.join(ws, "proj", "f"), "w").close()
    subprocess.run(["git", "-C", os.path.join(ws, "proj"), "add", "-A"], env=env, check=True)
    subprocess.run(["git", "-C", os.path.join(ws, "proj"), "commit", "-q", "-m", "x"], env=env, check=True)
    with open(os.path.join(home, ".config", "spark", "site.env"), "w") as f:
        f.write("SITE_WORKSPACE=%s\nSITE_PEER_AI_URL=%s\n" % (ws, stub_url if good else "http://127.0.0.1:9"))
        f.write("SITE_SHELL=on\n")     # both fixtures carry the shell layer: its rows must flip too
        f.write("SITE_THEME=fixture\n")     # the theme row: applied (good) or stale (bad)
        if good:
            f.write("SITE_EMBER_MODEL=auto\n")     # the default is none; auto fits an ember beside the spark row
        else:
            f.write("SITE_EMBER_MODEL=qwen3-30b-a3b\n")     # 21 GB: over the bad fixture's budget
    os.chmod(os.path.join(home, ".config", "spark", "site.env"), 0o600 if good else 0o644)
    with open(os.path.join(state, "widgets", str(os.getpid())), "w") as f:
        f.write("bash %d %d\n" % (os.getpid(), int(time.time())))
    with open(os.path.join(state, "bar"), "w") as f:
        json.dump({"t": time.time() if good else time.time() - 3600, "net": None, "line": "x"}, f)
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
    os.makedirs(os.path.join(home, ".local", "share", "spark", "models"), exist_ok=True)
    for mf in ("fixture.gguf", "fixture-ember.gguf"):
        with open(os.path.join(home, ".local", "share", "spark", "models", mf), "w") as f:
            f.write("x" * 4096)
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
    # soul and memory: the user's files, private (good) or world-readable and
    # the old key still set (bad); one thread, 0600 or not
    with open(os.path.join(cfgd, "soul"), "w") as f:
        f.write("The fixture's spark.\n")
    with open(os.path.join(cfgd, "memory"), "w") as f:
        f.write("the box is a fixture\nthe fixture has two facts\n")
    os.makedirs(os.path.join(state, "threads"), mode=0o700, exist_ok=True)
    with open(os.path.join(state, "threads", "2000-01-01-000000.jsonl"), "w") as f:
        f.write(json.dumps({"ts": "2000-01-01 00:00:00", "role": "user", "text": "fixture?", "mode": "line", "cwd": "/"}) + "\n")
    for name in ("soul", "memory"):
        os.chmod(os.path.join(cfgd, name), 0o600 if good else 0o644)
    os.chmod(os.path.join(state, "threads", "2000-01-01-000000.jsonl"), 0o600 if good else 0o644)
    with open(os.path.join(state, "chat-history"), "w") as f:
        f.write("write a haiku\n")
    os.chmod(os.path.join(state, "chat-history"), 0o600 if good else 0o644)
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
    _stub(os.path.join(bin_, "tmux"), "#!/bin/sh\nexit 0\n")
    if good:
        for name in ("spark", "explain"):
            os.symlink(os.path.join(repo, "bin", name), os.path.join(home, ".local", "bin", name))
        fd = os.path.join(home, "Library", "Fonts") if IS_MAC else os.path.join(home, ".local", "share", "fonts")
        os.makedirs(fd)
        open(os.path.join(fd, "JetBrainsMonoNerdFont-Regular.ttf"), "w").close()
        os.makedirs(os.path.join(home, ".config", "micro", "plug", "aspell"))
        _stub(os.path.join(engine, "llama-server"), "#!/bin/sh\nexit 0\n")
        with open(os.path.join(engine, "flavour"), "w") as f:     # the engine row names the tarball's flavour
            f.write("fixture-x64\n")
        _stub(os.path.join(bin_, "starship"), "#!/bin/sh\nexit 0\n")
        for sh in ("bash", "zsh"):
            open(os.path.join(home, ".config", "spark", "widget." + sh), "w").close()
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
        # the FORGE: two private tokens and a URL the stub answers /api/health at
        for tname, tval in (("forge-token", b"stub-forge-token\n"), ("ember-token", b"stub-ember-token\n")):
            fd_ = os.open(os.path.join(state, tname), os.O_WRONLY | os.O_CREAT, 0o600)
            os.write(fd_, tval)
            os.close(fd_)
        with open(os.path.join(state, "forge-url"), "w") as f:
            f.write(stub_url + "\n")
        origin = os.path.join(root, "work-origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], env=env, check=True)
        subprocess.run(["git", "-C", os.path.join(ws, "proj"), "remote", "add", "origin", origin], env=env, check=True)
        subprocess.run(["git", "-C", os.path.join(ws, "proj"), "push", "-q", "-u", "origin", "main"], env=env, check=True)
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

    # the rc files: the good fixture's are spark's own links into the repo
    # (SITE_SHELL=on: the prompt row reads `link`, the shell row is ok);
    # the bad one's rc file is a plain empty file, no hook line, no link
    if good:
        for name in site.RC_FILES:
            os.symlink(os.path.join(osdir, name), os.path.join(home, name))
    else:
        open(os.path.join(home, ".zshrc" if IS_MAC else ".bashrc"), "w").close()

    # stub commands: what the OS would answer
    _stub(os.path.join(bin_, "infocmp"), "#!/bin/sh\n" + ("echo 'kUP=\\E[1;2A,'\n" if good else "exit 1\n"))
    _stub(os.path.join(bin_, "brew"), "#!/bin/sh\n" + ("exit 0\n" if good else "exit 1\n"))
    _stub(os.path.join(bin_, "dpkg-query"),
          "#!/bin/sh\n" + ("shift 3; for p; do echo \"$p install ok installed\"; done\n" if good else "exit 1\n"))
    _stub(os.path.join(bin_, "systemctl"),
          "#!/bin/sh\n[ \"$2\" = show-environment ] && exit 0\ncase $3 in spark-check.timer) "
          + ("[ \"$2\" = is-enabled ] && echo enabled || echo active" if good else "echo disabled")
          + " ;; *) echo not-found; exit 1 ;; esac\n")
    _stub(os.path.join(bin_, "launchctl"),
          "#!/bin/sh\ncase $1 in print-disabled) exit 0 ;; print) " + ("case $2 in gui/*/spark.check) exit 0 ;; esac; " if good else "")
          + "exit 113 ;; esac\n")
    return {"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
            "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
            "PATH": os.path.join(home, ".local", "bin") + ":" + bin_ + ":" + os.environ.get("PATH", ""),
            "SPARK_REPO": repo, "SPARK_ENGINE_DIR": engine if good else os.path.join(root, "nope"),
            "SPARK_API_KEY": "stub-token", "SPARK_SERVICE": "none", "TMUX": "", "SPARK_SYSFS_DRM": os.path.join(root, "drm"),
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
                body = b'{"status":"ok","forge":true,"name":"fixture","version":"0","model":"fixture.gguf","upstream":"ok"}'
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
    row must be ok in the good one and not ok in the bad one. A third pass,
    the good fixture with SITE_SHELL=off, must make every shell row na; a
    fourth, the good fixture as a client of the stub, every client row."""
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
        # the third pass: the good fixture with the shell layer off -- every
        # shell row, and the shell row itself, must answer na
        root = os.path.join(tmp, "off")
        os.makedirs(root)
        env = dict(base)
        env.update(make_fixture(root, True, stub_url))
        env["SITE_SHELL"] = "off"
        p = subprocess.run([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--porcelain", "--fresh"],
                           env=env, capture_output=True, text=True, timeout=180)
        results["off"] = {}
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 5:
                results["off"][parts[2]] = (parts[1], parts[3])
        # the fourth pass: the good fixture as a client of the stub -- the
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
    gated = SHELL_ROWS + ("shell",)
    not_na = [n for n in gated if results["off"].get(n, ("missing", ""))[0] != NA]
    say("  %s shell-off: %d rows na%s" % (GLYPH[OK] if not not_na else GLYPH[FAIL], len(gated) - len(not_na),
                                         "" if not not_na else "   not na: " + " ".join(not_na)))
    bad += bool(not_na)
    not_na = [n for n in CLIENT_ROWS if results["client"].get(n, ("missing", ""))[0] != NA]
    peer = results["client"].get("peer", ("missing", ""))[0]
    say("  %s client: %d rows na, peer %s%s" % (GLYPH[OK] if not not_na and peer == OK else GLYPH[FAIL],
                                              len(CLIENT_ROWS) - len(not_na), peer,
                                              "" if not not_na else "   not na: " + " ".join(not_na)))
    bad += bool(not_na) or peer != OK
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
USAGE = """%s check -- is this machine still what its repository says it is?

  spark check              the report; exit 0 iff no row failed
  spark check --watch N    redraw every N seconds
  spark check --porcelain  category<TAB>status<TAB>name<TAB>value<TAB>remedy
  spark check --fresh      ignore cached answers (brew, git fetch results)
  spark check --fetch      ask origin before judging the git row
  spark check --selftest   prove every fixture-testable row can flip
""" % MARK


def main(argv):
    watch, porcelain_out, fresh, fetch, names = 0, False, False, False, []
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help", "help"):
            say(USAGE.rstrip())
            return 0
        if a == "--watch":
            watch = int(next(it, "5"))
        elif a == "--porcelain":
            porcelain_out = True
        elif a == "--fresh":
            fresh = True
        elif a == "--fetch":
            fetch = True
        elif a == "--selftest":
            return selftest()
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
