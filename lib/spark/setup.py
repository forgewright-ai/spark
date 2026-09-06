# spark.setup -- `spark setup`: the guided first run. Greet, ask three
# things (this machine's name, yours, the model), write
# site.env, sudo once when apt has something to install, run bootstrap on
# the terminal, wait for the brain, ask the first question live, print the
# measured speed and the three things to try. Every step reuses code that
# exists: cmd_ver, print_model_table's rows, set_keys, apply, cmd_serve,
# theme.write_runtime, `spark line`. Re-runnable: bootstrap's rows are
# idempotent, and a key site.env already holds is never asked again.

import os
import re
import shutil
import subprocess
import sys
import time

from . import HOME, IS_MAC, MARK, REPO, SITE_ENV, config, mem_total_gb, say, wait_ready
from . import engine, session, site, wire

SIGN = "%s setup -- pick the model this machine earns and light it up" % MARK
USAGE = SIGN + """

  spark setup                   ask this machine's name, yours and the
                                model; apply
  spark setup --yes             every default, no questions (stdin not a tty
                                implies it); SITE_NAME SITE_USER SITE_AI_MODEL
                                SITE_THEME in the environment pre-answer them
  spark setup --model NAME      a name from the table, auto, or none
  spark setup --name NAME       this machine's display name (SITE_NAME)
  spark setup --user NAME       your name (SITE_USER)
  spark setup --theme NAME      a palette from themes/, or none; never asked,
                                gruvbox-dark unless it is said here
  spark setup --no-serve        write and apply; leave the server down
"""
# the look spark ships wearing when nothing has said otherwise -- never a
# question, `spark theme NAME|none` is the choice
DEFAULT_THEME = "gruvbox-dark"

# the bootstrap rows that are the AI layer, by their names in bootstrap.sh
# (the filter apply() uses when its output is captured; at a terminal the
# whole bootstrap shows, progress bars included)
CORE_ROWS = ["site", r"spark\.env", "name", "model", "ember", "apt", "brew", "engine", "token", "dir",
             "configs", "rc", "spark", "explain", "PATH", "hooks", "linger", "render", "systemd", "launchd",
             r"spark[-.]serve", r"spark[-.]forge", r"spark[-.]check"]
QUESTION = "how big is this dir"
VALUE = re.compile(r"^[^;`$()|&<>]*$")     # what a KEY=value line may hold (contract 3)


class Abort(Exception):
    """One lowercase line for the user; the exit code rides along."""

    def __init__(self, hint, code=1):
        super().__init__(hint)
        self.code = code


def _parse(args):
    opts = {"yes": False, "model": None, "name": None, "user": None, "theme": None, "serve": True}
    it = iter(args)
    for a in it:
        if a == "--yes":
            opts["yes"] = True
        elif a == "--no-serve":
            opts["serve"] = False
        elif a in ("--model", "--name", "--user", "--theme"):
            val = next(it, None)
            if val is None:
                raise Abort("%s needs a value (spark setup -h)" % a, 2)
            opts[a[2:]] = val
        else:
            raise Abort("no option %s (spark setup -h)" % a, 2)
    return opts


ASKED = False      # whether any question was printed (the blank line after them)


def _ask(label, default, yes):
    """`label [default]: ` on the terminal; Enter or EOF keeps the default.
    A value that contract 3 refuses is asked again."""
    global ASKED
    while True:
        if yes:
            return default
        ASKED = True
        try:
            val = input("%s [%s]: " % (label, default)).strip()
        except EOFError:
            say()
            return default
        if not val:
            return default
        if VALUE.match(val):
            return val
        say("spark setup: no shell syntax in a value (; ` $ ( ) | & < >)")


def _decide(cfg, key, flag, cfg_value, label, yes):
    """The flag, else the environment or site.env (no question), else the
    prompt with the default."""
    if flag is not None:
        if not VALUE.match(flag):
            raise Abort("%s: no shell syntax in a value" % label, 2)
        return flag
    if key in os.environ or key in cfg.site_file:
        return cfg_value
    return _ask(label, cfg_value, yes)


def _table(cfg):
    """The header and the rows auto may pick (tested on the line, open
    license), the default row (the spark pick) marked *; the name of that
    row, or none. The rest of `models.env` is counted in one line under
    the table, not printed: a first run is no place for twenty rows, and
    naming any of them with --model still works."""
    budget = mem_total_gb() * cfg.ai_budget / 100.0
    say("%.0f GB for models (RAM + GPU), budget %.0f GB (%d%%), %s" % (mem_total_gb(), budget, cfg.ai_budget, engine.backend(cfg)))
    note = engine.cap_note(cfg)
    if note:
        say(note)
    default = "none"
    rest = 0
    for r in site.model_rows(cfg):
        if not (r["tested"] and r["open"]):
            rest += 1
            continue
        say(site.model_line(r))
        if r["role"] == "spark":
            default = r["name"]
    if rest:
        # the table stays the proven few -- a first run is no place for
        # twenty rows -- but nobody should read it as the whole list
        say("     %d more: spark model list (unproven, or a license that asks)" % rest)
    return default


def _announce_license(rows, name):
    """A row under a license auto would not take, named here (never
    offered in the table, but a --model or a typed name may still pick
    one), prints its license line and its note, when there is one -- no
    question: naming it is the yes."""
    match = [r for r in rows if r[0] == name]
    if match and not config.is_open(match[0][8]):
        say("%s license: %s" % (name, match[0][8] or "none on file"))
        if match[0][9]:
            say("  " + match[0][9])


def _model(cfg, opts, default, yes):
    rows = config.model_tables()
    valid = ["auto", "none"] + [r[0] for r in rows]
    choices = "one of: auto none " + " ".join(r[0] for r in config.auto_rows(rows))
    if opts["model"] is not None or "SITE_AI_MODEL" in os.environ or "SITE_AI_MODEL" in cfg.site_file:
        name = opts["model"] if opts["model"] is not None else cfg.model_choice
        if name not in valid:
            raise Abort("no model named %s -- %s" % (name, choices), 2)
        _announce_license(rows, name)
        return name
    while True:
        name = _ask("model", default, yes)
        if name in valid:
            _announce_license(rows, name)
            return name
        say("spark setup: no model named %s -- %s" % (name, choices))


def _theme(cfg, opts):
    """Not a question. spark has a look and ships wearing it; `spark theme
    NAME|none` changes it, like every other choice. Asking cost a first-run
    question that a user who never turns the shell layer on has no way to
    answer -- the palette dresses tmux, starship and btop, which are that
    layer. The flag, else the environment or site.env, else DEFAULT_THEME."""
    from . import theme
    valid = ["none"] + theme.palettes()
    choices = "one of: none " + " ".join(theme.palettes())
    if opts["theme"] is not None or "SITE_THEME" in os.environ or "SITE_THEME" in cfg.site_file:
        name = opts["theme"] if opts["theme"] is not None else cfg.theme
        if name not in valid:
            raise Abort("no palette named %s -- %s" % (name, choices), 2)
        return name
    return DEFAULT_THEME


def _write(name, user, model, theme):
    """site.env: the documented example first when there is none, then the
    keys decided here. SITE_SHELL=off is written so the file says which
    layer this is; an `on` already there is kept."""
    if not os.path.exists(SITE_ENV):
        os.makedirs(os.path.dirname(SITE_ENV), exist_ok=True)
        shutil.copy(os.path.join(REPO, "site.env.example"), SITE_ENV)
        os.chmod(SITE_ENV, 0o600)
    keys = {"SITE_NAME": name, "SITE_USER": user, "SITE_AI_MODEL": model, "SITE_THEME": theme}
    if config.parse_env(SITE_ENV).get("SITE_SHELL") != "on":
        keys["SITE_SHELL"] = "off"
    site.set_keys(_quiet=True, **keys)
    # one row, not one per key: bootstrap's own `site` row names the file
    say("ok     site         " + " ".join("%s=%s" % kv for kv in keys.items()))


def _apt_packages():
    """The packages bootstrap's apt row would install (Linux), from a
    dry-run: '' when none. The dry-run never calls sudo."""
    if IS_MAC or os.environ.get("SPARK_NO_APPLY"):
        return ""
    p = subprocess.run(["sh", os.path.join(REPO, "bootstrap.sh"), "--dry-run"], capture_output=True, text=True)
    for line in p.stdout.splitlines():
        m = re.match(r"^would\s+apt\s+install:(.*?)\s*\(sudo\)\s*$", line)
        if m:
            return m.group(1).strip()
    return ""


def _sudo(pkgs, yes):
    """sudo once, before bootstrap needs it. Returns the packages still
    waiting when sudo is not to be had without a terminal."""
    if not pkgs:
        return ""
    if not yes:
        say("apt needs sudo once, for: %s" % pkgs)
        if subprocess.run(["sudo", "-v"]).returncode != 0:
            raise Abort("no sudo -- sudo apt-get install -y %s, then spark setup again" % pkgs)
        return ""
    if subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0:
        return pkgs
    return ""


def _rc_line():
    """The rc row once more, after everything scrolled by -- only when it
    is a todo: bootstrap already showed the ok."""
    shell = site.login_shell()
    state, path = site.rc_hook_state(shell)
    if state in ("link", "hook"):
        return
    if path:
        say("todo   rc           ~%s does not source the hook -- ./bootstrap.sh --dry-run says why" % path[len(HOME):])
    else:
        say("todo   rc           shell %s: no widget for it -- bash 4+ or zsh hosts one (chsh -s /bin/zsh)" % shell)


def _serve(cfg):
    """The brain up: the unit bootstrap enabled, waited for (as
    site._restart_server does), else `spark serve`."""
    from . import serve
    if engine.service_state(cfg) != "loaded":
        return serve.cmd_serve([])
    if wait_ready("ok     server       loading the model ...",
                  lambda: wire.health(wire.serve_url() or cfg.loopback_url()) == "ok", 180, 5):
        sys.stdout.write(" ready\n")
        return 0
    say("todo   server       not ready yet -- spark check --watch 5 follows it")
    return 1


def _first_question(cfg):
    """`? how big is this dir` through `spark line`, shown as the widget
    would show it; then the speed the server reported for it."""
    say()
    say("? " + QUESTION)
    cmd = [sys.executable, os.path.join(REPO, "bin", "spark"), "line", "--cwd", HOME, "--shell", site.login_shell()]
    try:
        # a slow but chosen model still gets its first answer: the line's own
        # 20 s budget is for the prompt, not for a demo on a cold server
        env = dict(os.environ)
        env.setdefault("SPARK_TIMEOUT", "120")
        p = subprocess.run(cmd, input="? " + QUESTION, capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        say("spark: no answer in 300 s -- spark check says why")
        return
    lines = p.stdout.splitlines()
    head = lines[0] if lines else "error"
    body = lines[1] if len(lines) > 1 else ""
    kind, _, command = head.partition("\t")
    if kind in ("cmd", "danger"):
        say("%s %s" % ("!" if kind == "danger" else "*", body))
        say("  " + command)
    elif kind == "answer":
        say("* " + body)
    else:
        say("spark: " + (body or p.stderr.strip() or "no answer"))
        return
    say()
    t = session.last_turn() or {}
    if t.get("tg_tps"):
        say("%.1f tok/s on your first question (spark bench for the full number)" % t["tg_tps"])
        return
    row = engine.chosen_rows(cfg).get("spark")
    if row:
        speed, kind = engine.speed_of(cfg, row)
        say("%s%d tok/s on this machine, %s (spark bench for the full number)" % (
            "~" if kind == "estimate" else "", speed, "an estimate" if kind == "estimate" else "measured"))


def _account(user):
    """The box's own sealed account, minted here so the very first chat
    is encrypted at rest. The token prints once -- it is the key to log
    in from other machines, and there is no reset."""
    from . import users
    have = users.account()[0]
    if have:
        say("ok     account      this machine is %s" % have)
        return
    base = users.sanitize(user)
    name, n = base, 2
    while users.exists(name):
        name, n = "%s-%d" % (base, n), n + 1
    token = users.add(name)
    users.write_login(name, token, users.unlock(name, token))
    say("ok     account      %s -- the token, shown once; it logs you in elsewhere:" % name)
    say("                    %s" % token)
    left = users.legacy_threads()
    if left and sys.stdin.isatty():
        from . import confirm
        if confirm("claim the %d existing plaintext thread%s into %s -- sealed, then removed"
                   % (left, "" if left == 1 else "s", name)):
            users.cmd_claim()


def _closing():
    say()
    say("open a new shell (exec $SHELL), then:")
    say("  spark chat                      a conversation")
    say("  ? how big is this dir           a command in your line, a hint above it")
    say("  cmd 2>&1 | explain              what went wrong, and the fix")
    say("spark shell on adds spark's own shell: tmux, starship, micro, fzf ...")
    say("spark ember NAME adds a second brain: a bigger model, just for conversation")


def _run(opts):
    from . import cli
    yes = opts["yes"] or not sys.stdin.isatty()
    cfg = config.load()
    cli.cmd_ver([])
    say()
    name = _decide(cfg, "SITE_NAME", opts["name"], cfg.name, "this machine's name", yes)
    user = _decide(cfg, "SITE_USER", opts["user"], cfg.user, "your name", yes)
    if ASKED:
        say()          # one blank line after the questions; none when there were none
    default = _table(cfg)
    model = _model(cfg, opts, default, yes)
    theme_name = _theme(cfg, opts)
    say()
    _write(name, user, model, theme_name)
    _account(user)
    cfg = config.load()
    waiting = _sudo(_apt_packages(), yes)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else site._downloads_pending(cfg)
    site._announce_downloads(pend)
    rc = site.apply(CORE_ROWS, stream=True)
    if waiting:
        say("todo   apt          still to install: %s -- sudo apt-get install -y %s, then spark setup again"
            % (waiting, waiting))
        say("                    (without libgomp1, llama-server will not start)")
    if rc != 0:
        return rc
    if theme_name != "none" and cfg.shell and not os.environ.get("SPARK_NO_APPLY"):
        # only with the shell layer on. SITE_THEME is written either way, but
        # a first run must leave a stranger's machine looking exactly as it
        # did: console-colors repaints the VT through the core rc hook, and
        # the macOS profile repaints Terminal. `spark shell on` and `spark
        # theme NAME` are where a user asks for the palette.
        from . import theme
        theme.write_runtime(theme_name)
        say("ok     theme        %s -> ~/.config/spark/theme.env (+ console-colors)" % theme_name)
        if IS_MAC:
            theme.profile(config.load(), False)
    _rc_line()
    if model == "none":
        say("no model chosen -- spark model NAME later, or SITE_PEER_AI_URL for another machine's brain")
    if opts["serve"] and (model != "none" or cfg.prefer_url):
        cfg = config.load()
        # SPARK_NO_APPLY (tests): no server here, but the question still
        # goes to whatever brain the environment names (the smoke stub)
        if model != "none" and not os.environ.get("SPARK_NO_APPLY") and _serve(cfg) != 0:
            _closing()
            return 1
        _first_question(cfg)
    _closing()
    return 0


def main(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    try:
        return _run(_parse(args))
    except Abort as e:
        say("spark setup: %s" % e)
        return e.code
    except wire.BrainError as e:
        say("spark setup: %s" % e.hint)
        return 1
    except KeyboardInterrupt:
        say()
        return 130
