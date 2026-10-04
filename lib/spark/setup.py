# spark.setup -- `spark setup`: the guided first run. Greet, ask three
# things (this machine's name, yours, the model) and whether spark should
# read aloud (the clear voice, default no, acted on last), write
# site.env, sudo once when the package manager has something to install, run bootstrap on
# the terminal, wait for the brain, ask the first question live, print the
# measured speed and the three things to try. Every step reuses code that
# exists: cmd_ver, print_model_table's rows, set_keys, apply, cmd_serve,
# `spark line`. Re-runnable: bootstrap's rows are
# idempotent, and a key site.env already holds is never asked again.

import os
import re
import shutil
import subprocess
import sys
import time

from . import (HOME, IS_MAC, MARK, REPO, SHARE_TOKEN, SHARE_URL, SITE_ENV, SPARK_ENV, TOKEN_FILE,
               STATE_DIR, config, mem_total_gb, say)
from . import engine, packages, session, site, wire
from . import text as textmod
from . import model as modeltab      # `model` is a local name here: the chosen row

SIGN = "%s setup -- set up the name, user, model and voice" % MARK
USAGE = SIGN + """

  spark setup                 a few questions, then it sets spark up
  spark setup --yes           no questions, every default
  spark setup --model NAME    a model from the list, auto, or none
  spark setup --engine URL    use your own llama-server at URL
  spark setup --name NAME     this machine's name
  spark setup --user NAME     your name
  spark setup --no-serve      set up, but leave the model off
"""
# the bootstrap rows that are the AI layer, by their names in bootstrap.sh
# (the filter apply() uses when its output is captured; at a terminal the
# whole bootstrap shows, progress bars included)
CORE_ROWS = ["site", r"spark\.env", "name", "hostname", "model", "ember", "packages", "engine", "token", "dir",
             "configs", "rc", "spark", "explain", "PATH", "hooks", "linger", "render", "systemd", "runit", "supervisor", "launchd",
             r"spark[-.]serve", r"spark[-.]forge", r"spark[-.]check"]
QUESTION = "how big is this dir"
VALUE = re.compile(r"^[^;`$()|&<>]*$")     # what a KEY=value line may hold (contract 3)


class Abort(Exception):
    """One lowercase line for the user; the exit code rides along."""

    def __init__(self, hint, code=1):
        super().__init__(hint)
        self.code = code


def _parse(args):
    opts = {"yes": False, "model": None, "name": None, "user": None, "serve": True, "engine": None}
    it = iter(args)
    for a in it:
        if a == "--yes":
            opts["yes"] = True
        elif a == "--no-serve":
            opts["serve"] = False
        elif a in ("--model", "--name", "--user", "--engine"):
            val = next(it, None)
            if val is None:
                raise Abort("%s needs a value (spark setup -h)" % a, 2)
            opts[a[2:]] = val
        else:
            raise Abort("no word %s; spark setup -h lists them" % a, 2)
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
        say("! a value cannot hold ; ` $ ( ) | & < >")


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
    say("%.0f GB for models, budget %.0f GB (%d%%)" % (mem_total_gb(), budget, cfg.ai_budget))
    note = engine.cap_note(cfg)
    if note:
        say(note)
    default = "none"
    rest = 0
    for r in modeltab.model_rows(cfg):
        if not (r["tested"] and r["open"]):
            rest += 1
            continue
        say(modeltab.model_line(r))
        if r["role"] == "spark":
            default = r["name"]
    if rest:
        # the table stays the proven few -- a first run is no place for
        # twenty rows -- but nobody should read it as the whole list
        say("     %d more: spark model list" % rest)
    return default


def _announce_license(rows, name):
    """A row under a license auto would not take, named here (never
    offered in the table, but a --model or a typed name may still pick
    one), prints its license line and its note, when there is one -- no
    question: naming it is the yes."""
    match = [r for r in rows if r[0] == name]
    if match and not config.is_open(match[0][8]):
        say("%s licence: %s" % (name, match[0][8] or "none on file"))
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
        say("! no model named %s -- %s" % (name, choices))


def _write(name, user, model):
    """site.env: the documented example first when there is none, then
    the keys decided here."""
    if not os.path.exists(SITE_ENV):
        os.makedirs(os.path.dirname(SITE_ENV), exist_ok=True)
        shutil.copy(os.path.join(REPO, "site.env.example"), SITE_ENV)
        os.chmod(SITE_ENV, 0o600)
    keys = {"SITE_NAME": name, "SITE_USER": user, "SITE_AI_MODEL": model}
    site.set_keys(_quiet=True, **keys)
    # one row, not one per key: bootstrap's own `site` row names the file
    say("ok     site         " + " ".join("%s=%s" % kv for kv in keys.items()))


def _packages_pending():
    """The packages bootstrap's packages row would install (Linux), from a
    dry-run: '' when none. The dry-run never calls sudo."""
    if IS_MAC or os.environ.get("SPARK_NO_APPLY"):
        return ""
    p = subprocess.run(["sh", os.path.join(REPO, "bootstrap.sh"), "--dry-run"], capture_output=True, text=True)
    for line in p.stdout.splitlines():
        m = re.match(r"^would\s+packages\s+install:(.*?)\s*\(sudo\)\s*$", line)
        if m:
            return m.group(1).strip()
    return ""


def _sudo(pkgs, yes):
    """sudo once, before bootstrap needs it. Returns the packages still
    waiting when sudo is not to be had without a terminal."""
    if not pkgs:
        return ""
    if not yes:
        say("sudo once, to install: %s" % pkgs)
        if subprocess.run(["sudo", "-v"]).returncode != 0:
            raise Abort("no sudo -- %s, then spark setup again" % packages.install_line(pkgs.split()))
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
        say("todo   rc           ~%s lacks the spark line -- spark update" % path[len(HOME):])
    else:
        say("todo   rc           %s has no prompt line -- chsh -s /bin/zsh" % shell)


def _serve(cfg):
    """The brain up: the unit bootstrap enabled, waited for (as
    modeltab._restart_server does), else `spark serve`."""
    from . import serve
    if engine.service_state(cfg) != "loaded":
        return serve.cmd_serve([])
    if engine.wait_load(cfg, "ok     server       loading the model ...",
                        lambda: wire.health(wire.serve_url() or cfg.loopback_url()) == "ok", 180, 5):
        sys.stdout.write(" ready\n")
        return 0
    say("todo   server       not ready yet -- spark check")
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
        env.pop("SPARK_HINT_ROW", None)     # the child draws no pulse of its own
        # its output is captured, so the wait shows here: today's dots
        # (text.Busy on stderr, a terminal only), not a silent terminal
        with textmod.Busy(sys.stderr):
            p = subprocess.run(cmd, input="? " + QUESTION, capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        say("! no answer in 300 s -- spark check")
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
        say("! " + (body or p.stderr.strip() or "no answer"))
        return
    say()
    t = session.last_turn() or {}
    if t.get("tg_tps"):
        say("* %.1f tok/s on your first question" % t["tg_tps"])
        return
    row = engine.chosen_rows(cfg).get("spark")
    if row:
        speed, kind = engine.speed_of(cfg, row)
        say("* %s%d tok/s on this machine%s" % ("~" if kind == "estimate" else "", speed,
                                              " (a guess)" if kind == "estimate" else ""))


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
    say("ok     account      %s -- your token, shown once:" % name)
    say("                    %s" % token)
    left = users.legacy_threads()
    if left and sys.stdin.isatty():
        from . import confirm
        if confirm("seal the %d old thread%s into %s" % (left, "" if left == 1 else "s", name)):
            users.cmd_claim()


def _closing():
    say()
    say("* open a new shell (exec $SHELL), then try:")
    say("  spark chat               talk with the model")
    say("  ? how big is this dir    get a command for it")
    say("  cmd 2>&1 | explain       why it failed, and the fix")
    door()


DOOR = "next: spark awaken -- give this machine a personality and a look"
OFFERED = os.path.join(STATE_DIR, "awaken-offered")


def door(once=False):
    """The one suggestion the living layer makes before it is asked for:
    printed while this machine is not awakened. once=True (spark update)
    prints it a single time ever, at a terminal, and marks it offered in
    the state dir; setup prints it every run, and marks it offered too,
    so an update after this setup does not say it again."""
    try:
        from . import look
        if look.awake():
            return False
    except Exception:       # noqa: BLE001 -- a suggestion is never a reason to fail
        return False
    if once and (os.path.exists(OFFERED) or not sys.stdout.isatty()):
        return False
    say(DOOR)
    try:
        os.makedirs(os.path.dirname(OFFERED), mode=0o700, exist_ok=True)
        with open(OFFERED, "a", encoding="utf-8"):
            pass
    except OSError:
        pass
    return True


VOICE_QUESTION = "read aloud to you (for low vision)? [y/N]: "


def _voice_question(cfg, yes):
    """One question, default no, before any awaken: the clear voice. Not
    asked when SPARK_VOICE is already set, or nobody is there to answer."""
    global ASKED
    if yes or os.environ.get("SPARK_VOICE") or "SPARK_VOICE" in cfg.spark_file:
        return False
    ASKED = True
    try:
        ans = input(VOICE_QUESTION).strip().lower()
    except EOFError:
        say()
        return False
    return ans in ("y", "yes")


def _voice(want):
    """The answer acted on, last: `spark voice clear` (its download, its
    screen reader rule)."""
    if want:
        from . import voice
        say()
        voice.cmd_voice(["clear"])


def _joining(yes):
    """This box shares an engine; join it? Default yes (it is the point of a
    shared box, and running your own would need root a joining user lacks)."""
    if yes:
        return True
    say("* this machine shares its model")
    try:
        ans = input("   use it? nothing to download [Y/n]: ").strip().lower()
    except EOFError:
        return True
    return ans in ("", "y", "yes")


def _own_engine(cfg, name, user, opts, yes, voice):
    """The user's own llama-server: `--engine URL`, or at a terminal one
    that answers on this machine's SPARK_PORT and is not spark's, with no
    model chosen yet and no shared engine here -- asked once. The join's
    rc when it is used, None when setup goes on as before."""
    url = opts["engine"]
    if url is not None:
        url = url.rstrip("/")
        if not site.CLIENT_URL.match(url):
            raise Abort("--engine URL is http://host:port", 2)
        if opts["model"] not in (None, "none"):
            raise Abort("--engine uses your server's model: leave --model out", 2)
    elif (yes or opts["model"] is not None or "SITE_AI_MODEL" in os.environ or "SITE_AI_MODEL" in cfg.site_file
          or os.access(SHARE_TOKEN, os.R_OK)):
        return None
    else:
        url = "http://127.0.0.1:%d" % cfg.port
        if wire.health(url) != "ok" or wire.forge_health(url, cfg=cfg) is not None or engine.own_pids(cfg):
            return None
        global ASKED
        ASKED = True
        say("* a llama-server of yours answers at %s" % url)
        try:
            ans = input("   use it? nothing to download [Y/n]: ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("", "y", "yes"):
            return None
    return _join(name, user, opts, yes, voice, url)


def _join(name, user, opts, yes, voice=False, own=""):
    """The userspace join: a client of this box's shared engine. No model,
    no console, no units, no sudo -- only this user's ~/.config and
    ~/.local/state, and their own sealed account. Mirrors spark client.
    `own` is the user's own llama-server instead (_own_engine): the same
    shape, with no shared token."""
    url = own
    try:
        with open(SHARE_URL, encoding="utf-8") as f:
            url = url or f.read().strip()
    except OSError:
        pass
    if not url:
        url = "" if yes else input("   its address [http://127.0.0.1:8080]: ").strip()
        url = url or "http://127.0.0.1:8080"
    say()
    _write(name, user, "none")                              # SITE_AI_MODEL=none
    site.set_keys(_quiet=True, SITE_PEER_AI_URL=url)
    if own:
        wire.forget_peer()
        say("ok     engine       %s, your own llama-server" % url)
    else:
        site.set_keys(_file=SPARK_ENV, _quiet=True, SPARK_API_KEY_FILE=SHARE_TOKEN)
        say("ok     join         %s, the shared model" % url)
    _account(user)                                          # this user's own sealed store, no root
    rc = site.apply(CORE_ROWS, stream=True)
    if rc != 0:
        return rc
    _rc_line()
    cfg = config.load()
    if opts["serve"]:
        _first_question(cfg)                                # asks the shared engine
    _voice(voice)
    _closing()
    return 0


def _run(opts):
    from . import cli
    yes = opts["yes"] or not sys.stdin.isatty()
    cfg = config.load()
    cli.cmd_ver([])
    say()
    name = _decide(cfg, "SITE_NAME", opts["name"], cfg.name, "this machine's name", yes)
    user = _decide(cfg, "SITE_USER", opts["user"], cfg.user, "your name", yes)
    # a shared engine already runs on this box (spark serve share on) and this user
    # has no server of their own: join it -- no model to download, no root
    voice = _voice_question(cfg, yes)
    own = _own_engine(cfg, name, user, opts, yes, voice)
    if own is not None:
        return own
    if os.access(SHARE_TOKEN, os.R_OK) and not os.path.exists(TOKEN_FILE) and _joining(yes):
        return _join(name, user, opts, yes, voice)
    if ASKED:
        say()          # one blank line after the questions; none when there were none
    default = _table(cfg)
    model = _model(cfg, opts, default, yes)
    say()
    _write(name, user, model)
    if model == "none":
        # no brain here yet, so no account yet: a box mints its own on the
        # first thread write (spark model NAME), and a client of a FORGE
        # logs in with a token minted THERE -- a client never mints, the
        # FORGE it answers from is the account authority
        say("skip   account      no model here -- on a client: spark user login NAME")
    else:
        _account(user)
    cfg = config.load()
    waiting = _sudo(_packages_pending(), yes)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else modeltab._downloads_pending(cfg)
    modeltab._announce_downloads(pend)
    rc = site.apply(CORE_ROWS, stream=True)
    if waiting:
        say("todo   packages     still to install: %s -- %s, then spark setup again"
            % (waiting, packages.install_line(waiting.split())))
    if rc != 0:
        return rc
    _rc_line()
    if model == "none":
        say("* no model chosen -- spark model NAME, or spark client URL")
    if opts["serve"] and (model != "none" or cfg.prefer_url):
        cfg = config.load()
        # SPARK_NO_APPLY (tests): no server here, but the question still
        # goes to whatever brain the environment names (the smoke stub)
        if model != "none" and not os.environ.get("SPARK_NO_APPLY") and _serve(cfg) != 0:
            _closing()
            return 1
        _first_question(cfg)
    _voice(voice)
    _closing()
    return 0


def main(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    try:
        return _run(_parse(args))
    except Abort as e:
        say("%s setup -- %s" % (MARK, e))
        return e.code
    except wire.BrainError as e:
        say("%s setup -- %s" % (MARK, e.hint))
        return 1

    except KeyboardInterrupt:
        say()
        return 130
