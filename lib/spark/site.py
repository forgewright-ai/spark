# spark.site -- the site.env custodian and the machine-shape verbs:
# set_keys/apply (every choice lands through them), the rc-hook custody,
# `spark quiet`, `spark headless`, `spark share`, `spark client` (and
# `spark model`/`ember` in model.py). Each writes the key, then runs
# bootstrap.sh so the machine follows; editing site.env by hand and
# running bootstrap does the same thing.

import os
import pwd
import re
import subprocess
import sys
from urllib.parse import urlsplit

from . import (CONFIG_DIR, HOME, IS_MAC, MARK, REPO, SHARE_TOKEN, SHARE_URL, SITE_ENV, SPARK_ENV,
               TOKEN_FILE, VAR_SERVICE, config, glyph, init_shape, is_wsl, runit_live, say)

# WSL 2 cannot stay on and answer (contract 8 line)
WSL_NO_BRAIN = "WSL 2 stops with its last window: it cannot stay on and answer (a Linux machine can)"


def set_keys(_file=None, _quiet=False, **kv):
    """Rewrite KEY= lines in site.env (or _file; append the missing ones);
    keep it 0600. One `ok site KEY=value` row per key unless _quiet.
    A value contract 3 would refuse is refused HERE: written, it poisons
    the whole file and every verb dies with exit 2 before its help."""
    for key, val in kv.items():
        bad = re.search(r"[;`$()|&<>]", str(val))
        if bad:
            raise ValueError("%s: a config value cannot hold %s (contract 3)" % (key, bad.group(0)))
    path = _file or SITE_ENV
    lines = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        pass
    for key, val in kv.items():
        done = False
        for i, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[i] = "%s=%s" % (key, val)
                done = True
        if not done:
            lines.append("%s=%s" % (key, val))
        if not _quiet:
            say("ok     %-12s %s=%s" % ("site" if path == SITE_ENV else "spark.env", key, val))
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def apply(rows, stream=False):
    """Run bootstrap.sh and show the rows that matter for this change.
    stream=True at a terminal hands bootstrap the terminal unfiltered, so
    a model download shows curl's progress bar live; captured output (a
    pipe, a script) keeps the filtered rows either way. An empty rows shows
    every row that is not ok (the non-stream branch): a caller that does
    not know which rows changed, like `spark update`, wants everything
    bootstrap did.
    SPARK_NO_APPLY=1 (tests) writes the key only."""
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cmd = ["sh", os.path.join(REPO, "bootstrap.sh")]
    if stream and sys.stdout.isatty():
        if subprocess.run(cmd).returncode != 0:
            say("spark: bootstrap.sh failed (the output above says where)")
            return 1
    else:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if rows:
            pattern = r"^(ok|would|skip|todo)\s+(%s)\b" % "|".join(rows)
            for line in p.stdout.splitlines():
                if re.match(pattern, line):
                    say(line)
        else:
            for line in p.stdout.splitlines():
                if not re.match(r"^ok\s", line):
                    say(line)
        if p.returncode != 0:
            say("spark: bootstrap.sh failed:\n" + (p.stderr or p.stdout)[-800:])
            return 1
    from . import check
    check.refresh()
    return 0


# ------------------------------------------------------------------ quiet
QUIET_USAGE = """%s quiet -- what spark keeps silent

  spark quiet                   the two states: start, audio
  spark quiet start [on|off]    spark's own noise: no login banner, one-line
                                serve and forge, one-line bare spark
  spark quiet audio [on|off]    no sound from spark (the audio row says which
                                player it would use)
""" % MARK
QUIET_KEYS = {"start": "SITE_QUIET_START", "audio": "SITE_QUIET_AUDIO"}


def _quiet_state(cfg, sub):
    return "on" if {"start": cfg.quiet_start, "audio": cfg.quiet_audio}[sub] else "off"


def cmd_quiet(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(QUIET_USAGE.rstrip())
        return 0
    cfg = config.load()
    if not args or args[0] == "status":
        say("%s quiet -- start %s, audio %s" % (MARK, _quiet_state(cfg, "start"), _quiet_state(cfg, "audio")))
        return 0
    sub = args[0]
    if sub not in QUIET_KEYS or len(args) > 2 or (len(args) == 2 and args[1] not in ("on", "off")):
        say(QUIET_USAGE.rstrip())
        return 2
    if len(args) == 1:                                     # show one state
        say("%s quiet %s -- %s" % (MARK, sub, _quiet_state(cfg, sub)))
        return 0
    # the key is the behavior: nothing on disk to converge, no bootstrap row
    set_keys(**{QUIET_KEYS[sub]: "yes" if args[1] == "on" else "no"})
    if sub == "audio":
        say("audio is %s" % ("quiet: spark plays no sound" if args[1] == "on" else "on: the sounds spark has play again"))
    else:
        say("start is %s" % ("quiet: no login banner, one line from serve, forge and bare spark"
                             if args[1] == "on" else "loud again: the banner and the full narration are back"))
    from . import check
    check.refresh()
    return 0


# --------------------------------------------------------------- headless
HEADLESS_USAGE = """%s headless -- the machine that stays on and answers

  spark headless                what is set, and what is in effect here
  spark headless on             the page's server up from boot, nobody logged
                                in, never asleep. Linux: linger, the render
                                group, sleep masked, the lid ignored. macOS:
                                LaunchDaemons in system/, pmset never sleeps,
                                wake on LAN
  spark headless off            under your login again (macOS: pmset untouched)
""" % MARK
HEADLESS_ROWS = ["headless", "linger", "render", "sleep", "lid", "daemons", "runit", "supervisor", r"spark\.(serve|forge|check)"]
SLEEP_TARGETS = ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target")
LOGIND_DROPIN = "/etc/systemd/logind.conf.d/spark.conf"
PMSET_WANT = (("sleep", "0"), ("disksleep", "0"), ("womp", "1"), ("autorestart", "1"))


def render_fact(node):
    """(label, good, detail): does a server with no seat open the GPU?
    The node says so itself: open to every user (Void's eudev leaves
    renderD128 0666, owned by `video`), or owned by a group that lists
    this user. No distro is assumed to have a `render` group."""
    import grp
    from . import run
    st = os.stat(node)
    name = os.path.basename(node)
    if st.st_mode & 0o006 == 0o006:
        return ("render node", True, "%s is open to every user: the units see the GPU from boot" % name)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    rc, out = run(["id", "-nG"], timeout=10)
    member = group in out.split()
    return ("%s group" % group, member,
            "the units see the GPU from boot" if member else "the GPU needs a login session")


def headless_facts(cfg):
    """What is in effect on this machine, read-only: [(piece, good, detail)].
    The check row and `spark headless` read it; bootstrap.sh changes it."""
    from . import engine, run
    facts = []
    if IS_MAC:
        for unit, wanted in (("serve", cfg.service == "auto"), ("forge", cfg.forge != "off"), ("check", True)):
            dom = engine.service_domain(cfg, unit)
            facts.append(("%s daemon" % unit, dom == "system" or not wanted,
                          "system/ (from boot)" if dom == "system" else ("gui/ (a login agent)" if engine.service_state(cfg, unit) == "loaded" else "absent")))
        rc, out = run(["pmset", "-g"], timeout=10)
        pm = {}
        for line in out.splitlines():
            f = line.split()
            if len(f) >= 2:
                pm[f[0]] = f[1]
        for key, want in PMSET_WANT:
            cur = pm.get(key)
            good = cur is None or cur == want
            facts.append(({"sleep": "never sleeps", "disksleep": "disks stay awake", "womp": "wake on LAN",
                           "autorestart": "restarts after power loss"}[key], good,
                          "pmset %s %s" % (key, cur if cur is not None else "(not on this hardware)")))
        return facts
    render = []
    if os.path.exists("/dev/dri/renderD128"):
        render.append(render_fact("/dev/dri/renderD128"))
    user = os.environ.get("USER") or cfg.user
    if init_shape() == "runit":
        # runit: the user's runsvdir is a root service linked into
        # /var/service, so the services run from boot, login or not; there
        # are no sleep targets and no logind, so nothing here sleeps on its
        # own and the lid is elogind's or acpid's -- two facts, not four
        link = os.path.join(VAR_SERVICE, "runsvdir-" + user)
        linked = runit_live() and os.path.lexists(link)
        if linked:
            detail = "runsvdir-%s linked in %s" % (user, VAR_SERVICE)
        elif runit_live():
            detail = "no runsvdir-%s in %s (./bootstrap.sh)" % (user, VAR_SERVICE)
        else:
            detail = "runit is not running here (a container)"
        return [("supervisor from boot", linked, detail)] + render
    rc, out = run(["loginctl", "show-user", user, "-p", "Linger", "--value"], timeout=10)
    facts.append(("linger", out.strip() == "yes", "units run from boot" if out.strip() == "yes" else "units stop at logout"))
    facts += render
    masked = []
    for t in SLEEP_TARGETS:
        rc, out = run(["systemctl", "is-enabled", t], timeout=10)
        if out.strip() == "masked":
            masked.append(t)
    facts.append(("sleep masked", len(masked) == len(SLEEP_TARGETS), "%d of %d targets masked" % (len(masked), len(SLEEP_TARGETS))))
    try:
        with open(LOGIND_DROPIN, encoding="utf-8") as f:
            lid = "HandleLidSwitch=ignore" in f.read()
    except OSError:
        lid = False
    facts.append(("lid ignored", lid, LOGIND_DROPIN if lid else "no logind drop-in"))
    return facts


def cmd_headless(args):
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(HEADLESS_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        say("%s headless -- SITE_HEADLESS=%s: %s" % (MARK, "yes" if cfg.headless else "no",
                                                    "stays on and answers (the page's server up from boot, never asleep)" if cfg.headless
                                                    else "under your login (spark headless on makes it stay on and answer)"))
        for piece, good, detail in headless_facts(cfg):
            say("  %s %-26s %s" % (glyph("ok") if good else ("!" if cfg.headless else glyph("na")), piece, detail))
        return 0
    if args[0] not in ("on", "off"):
        say(HEADLESS_USAGE.rstrip())
        return 2
    if args[0] == "on" and not IS_MAC and is_wsl():
        say("%s headless -- %s" % (MARK, WSL_NO_BRAIN))
        return 2
    set_keys(SITE_HEADLESS="yes" if args[0] == "on" else "no")
    if args[0] == "off":
        os.environ["SPARK_HEADLESS_UNDO"] = "1"    # only this verb unmasks sleep and frees the lid
    return apply(HEADLESS_ROWS)


# ------------------------------------------------------------------ share
SHARE_USAGE = """%s share -- one engine, shared with this machine's other OS users

  spark share                what is set, and what is in effect here
  spark share on             let a `spark` OS group read the api-token, so a
                             group member's spark answers from this machine's
                             engine as a client -- their own soul and memory,
                             one model loaded once for everyone
  spark share off            the shared token goes; the engine is yours again

  another OS user joins once, then logs in again:  sudo gpasswd -a NAME spark
  then, as them:  spark client URL   (spark share prints the URL)
""" % MARK
SHARE_ROWS = ["share"]


def no_share():
    """Why a shared engine is not this machine's to set here ('' when it
    is): macOS keeps one user per machine in this version, and WSL 2
    cannot stay on and answer."""
    if IS_MAC:
        return "one user per machine on macOS in this version -- a shared engine is a Linux story"
    if is_wsl():
        return WSL_NO_BRAIN
    return ""


def _token_fresh(copy, source):
    """Is the shared copy current? By mtime, not contents: the owner is not
    in the spark group and cannot read the 0640 copy, so a content compare
    would false-alarm. The copy is fresh when it is no older than the source
    (spark share on stamps it after any token change). Unknown source (a
    user with no token of their own) is not our concern -- treat as fresh."""
    try:
        return os.stat(copy).st_mtime >= os.stat(source).st_mtime
    except OSError:
        return True


def _share_url():
    """The engine URL a local user points `spark client` at: the published
    /etc/spark/url, else whatever serve bound, else a placeholder."""
    from . import wire
    try:
        with open(SHARE_URL, encoding="utf-8") as f:
            url = f.read().strip()
            if url:
                return url
    except OSError:
        pass
    return wire.serve_url() or "http://<this-host>:8080"


def share_facts(cfg):
    """Read-only: [(piece, good, detail)] -- the group and the shared token,
    whether its perms are right and it still matches the live api-token.
    The verb's status and the check row both read it."""
    why = no_share()
    if why:
        return [("shared engine", not cfg.share, why)]
    import grp
    facts = []
    try:
        mem = grp.getgrnam("spark").gr_mem
        facts.append(("spark group", True, "%d member%s%s" % (len(mem), "" if len(mem) == 1 else "s",
                                                              (": " + ", ".join(mem)) if mem else "")))
    except KeyError:
        facts.append(("spark group", not cfg.share, "not created (spark share on)"))
    if os.path.exists(SHARE_TOKEN):
        try:
            st = os.stat(SHARE_TOKEN)
            mode = oct(st.st_mode & 0o777)[-3:]
            gname = grp.getgrgid(st.st_gid).gr_name
        except (OSError, KeyError):
            mode, gname = "???", "?"
        perms = mode == "640" and gname == "spark"
        stale = not _token_fresh(SHARE_TOKEN, TOKEN_FILE)
        facts.append(("shared token", perms and not stale, "%s (%s %s)%s" % (SHARE_TOKEN, mode, gname,
                      " -- STALE, spark share on re-syncs" if stale else "")))
    else:
        facts.append(("shared token", not cfg.share, "%s absent" % SHARE_TOKEN))
    if os.path.exists(SHARE_URL):
        try:
            url = open(SHARE_URL, encoding="utf-8").read().strip()
        except OSError:
            url = "?"
        facts.append(("engine url", bool(url), "%s (%s)" % (SHARE_URL, url or "empty")))
    else:
        facts.append(("engine url", not cfg.share, "%s absent (spark serve, then spark share on)" % SHARE_URL))
    return facts


def cmd_share(args):
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(SHARE_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        say("%s share -- SITE_SHARE=%s: %s" % (MARK, "yes" if cfg.share else "no",
            "this machine's engine is shared with its other OS users" if cfg.share
            else "not shared (spark share on lets the spark group in)"))
        for piece, good, detail in share_facts(cfg):
            say("  %s %-14s %s" % (glyph("ok") if good else ("!" if cfg.share else glyph("na")), piece, detail))
        if cfg.share and not no_share():
            say("  a user joins:  sudo gpasswd -a NAME spark  (log in again), then  spark client %s" % _share_url())
        return 0
    if args[0] not in ("on", "off"):
        say(SHARE_USAGE.rstrip())
        return 2
    why = no_share()
    if args[0] == "on" and why:
        say("%s share -- %s" % (MARK, why))
        return 2
    set_keys(SITE_SHARE="yes" if args[0] == "on" else "no")
    return apply(SHARE_ROWS)


# ----------------------------------------------------------------- client
CLIENT_USAGE = """%s client -- a client of another machine's server

  spark client                  what is set here, and whether the other
                                machine answers
  spark client URL              answer from the server at URL: no model, no
                                engine, nothing runs here; the prompt, chat and
                                explain do (spark user add NAME on the other
                                machine mints your token, spark user login
                                NAME here presents it)
  spark client off              serve here again: spark model auto picks one

  the URL may be this same machine's engine (spark share on there): a group
  member reads its shared token and answers from it, keeping their own
  soul and memory -- no second model loaded.
""" % MARK


def cmd_client(args):
    from . import users, wire
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(CLIENT_USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        if not cfg.client:
            say("%s client -- not a client: SITE_AI_MODEL=%s, SITE_PEER_AI_URL=%s" % (
                MARK, cfg.model_choice, cfg.peer_ai_url or "unset"))
            say("  spark client URL answers from another machine's server, nothing served here")
            return 0
        say("%s client -- of %s (SITE_AI_MODEL=none: nothing runs here)" % (MARK, cfg.peer_ai_url))
        fh = wire.forge_health(cfg.peer_ai_url)
        if isinstance(fh, dict):
            up = fh.get("upstream", "down")
            peer = "page's server %s%s" % ("ok, " + fh.get("model", "?") if up == "ok" else "up, its model " + up, "")
        else:
            peer = "down" if fh == "down" else "engine " + wire.health(cfg.peer_ai_url)
        say("  %s %-12s %s" % (glyph("ok") if "ok" in peer else "!", "peer", peer))
        me = users.account()[0]
        say("  %s %-12s %s" % (glyph("ok") if me else "!", "account",
                               "this machine is %s" % me if me else "no login -- " + _login_hint(cfg.peer_ai_url)))
        return 0
    if args[0] == "off":
        # the one deliberate promotion: the client shape ends here, then
        # `spark model auto` runs as on any server (cmd_model refuses a
        # choice while the shape holds)
        say("the other machine stays first while it answers; this machine's own model is the fallback")
        set_keys(SITE_AI_MODEL="auto")
        from . import model
        return model.cmd_model(["auto"])
    url = args[0].rstrip("/")
    if not re.match(r"^https?://[^/\s]+$", url):
        say("%s client -- URL is http://host:port, the other machine's server (spark forge --print-client there)" % MARK)
        return 2
    set_keys(SITE_PEER_AI_URL=url, SITE_AI_MODEL="none")
    if not cfg.get("SPARK_API_KEY_FILE", "") and os.access(SHARE_TOKEN, os.R_OK):
        # a shared engine on this box: use its group-readable token rather
        # than mint one of our own (which the engine would not accept)
        set_keys(_file=SPARK_ENV, SPARK_API_KEY_FILE=SHARE_TOKEN)
        say("using this machine's shared engine token (%s)" % SHARE_TOKEN)
    rc = apply(["configs", "rc", "engine", "model", "services", "token"])
    if rc == 0:
        if not users.account()[0]:
            say("then log in as yourself: " + _login_hint(url))
        from . import engine
        # a machine that served: the unit would bring the engine back at
        # boot, and spark serve off refuses while it is loaded -- stop
        # and disable it here, remove its links, and say so
        stopped = False
        name = engine.unit_name("serve")
        if IS_MAC:
            plist = os.path.join(HOME, "Library", "LaunchAgents", name + ".plist")
            if engine.service_state(cfg) == "loaded" or os.path.exists(plist):
                subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), name)], capture_output=True)
                stopped = True
            if os.path.exists(plist):
                os.remove(plist)
        elif init_shape() == "runit":
            # the service dir stays rendered; its `down` file keeps the engine off
            if engine.service_state(cfg) == "loaded":
                engine.service_stop(True)
                stopped = True
        else:
            link = os.path.join(HOME, ".config", "systemd", "user", name)
            if engine.service_state(cfg) == "loaded" or os.path.lexists(link):
                engine.sysctl(["disable", "--now", name])
                stopped = True
            if os.path.lexists(link):
                os.remove(link)
                engine.sysctl(["daemon-reload"])
        pids = engine.server_pids(cfg.port)
        if pids:
            engine.terminate(pids)
            left = engine.wait_gone(pids, 15)
            if left:
                engine.terminate(left, force=True)
            stopped = True
        if stopped:
            engine.forget()
            say("the engine that ran here is stopped")
    return rc


def _login_hint(url):
    host = urlsplit(url).hostname or url
    return "spark user add NAME on %s (the token shows once), then spark user login NAME here" % host


# --------------------------------------------------------------------- rc
# The rc hook: bootstrap's `rc` row appends one marked line to the login
# shell's rc file -- yours, a file or a symlink alike. Pure functions:
# the callers print the rows.
RC_MARKER = "config/spark/hook."
RC_LINE = {"bash": "[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt",
           "zsh": "[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt"}


def login_shell():
    """The login shell's basename: $SHELL, else the passwd entry."""
    s = os.environ.get("SHELL") or ""
    if not s:
        try:
            s = pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            s = ""
    return os.path.basename(s) or "sh"


def rc_file(shell):
    """The rc file the `rc` row hooks for this shell (bash, zsh), else None."""
    name = {"bash": ".bashrc", "zsh": ".zshrc"}.get(shell)
    return os.path.join(HOME, name) if name else None


def _spark_link(path):
    """True when path is a symlink into the repository (spark's own file)."""
    if not os.path.islink(path):
        return False
    try:
        target = os.readlink(path)
    except OSError:
        return False
    return target.startswith(REPO + "/") or os.path.realpath(path).startswith(os.path.realpath(REPO) + "/")


def rc_hook_state(shell):
    """("hook" | "missing", path): the rc file sources the hook (the
    marker line) or lacks it (path None for a shell without an rc file
    to hook)."""
    path = rc_file(shell)
    if not path:
        return ("missing", None)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            if RC_MARKER in f.read():
                return ("hook", path)
    except OSError:
        pass
    return ("missing", path)


def main(sub, args):
    if sub == "headless":
        return cmd_headless(args)
    if sub == "client":
        return cmd_client(args)
    return cmd_quiet(args)
