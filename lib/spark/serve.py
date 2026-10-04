# spark.serve -- `spark serve [on|off]`: the one server verb. on|off
# switches the engine (the local llama-server) AND the page's server
# together, kept in spark.env (SPARK_SERVICE, SPARK_FORGE) and run
# through their units; bare shows one view of what answers. Its words:
# boot (site.cmd_headless), share (site.cmd_share), --login and --audit
# (the page's). `--foreground` is what the engine's unit runs.

import os
import subprocess
import sys
import time

from . import (IS_MAC, MARK, REPO, SPARK_ENV, bind_check, config, forge_url, lan_ip, own_hostnames, say,
               wait_lan_ip)
from . import engine, wire

USAGE = """%s serve -- serve the model and the page on your network

  spark serve                 what answers, the models, the page
  spark serve on              start the engine and the page, keep them up
  spark serve off             stop both, keep them down
  spark serve off --force     also stop an engine spark did not start
  spark serve boot [on|off]   up from boot, nobody logged in, never asleep
  spark serve share [on|off]  one model for every user here (Linux)
  spark serve --login         the page's address and the admin login
                              (--no-qr; --show-token when piped)
  spark serve --login --new   a new admin token; old logins end
  spark serve --audit [N]     the last N admin actions (50; --porcelain)
  spark serve --foreground    be the engine (what its unit runs; --host ADDR)
""" % MARK
# the bootstrap rows `spark serve on|off` shows: the two units, per init
UNIT_ROWS = ["spark-serve", "spark-forge", r"spark\.(serve|forge)", "daemons", "supervisor", "runit", "systemd", "launchd"]


def _die(msg, code=1):
    print("! " + msg, file=sys.stderr, flush=True)
    return code


def _refuse(msg):
    """A gate refusal, signed (contract 8): stdout, exit 2. The world did
    not fail -- something says this invocation does not happen here, and
    `spark update`'s lock answers in the same shape."""
    say("%s serve -- %s" % (MARK, msg))
    return 2


def _warming(cfg, url):
    """engine.warm, and awakened at a terminal a pulse while it runs: the
    waking bar when the router loads its models now (the estimate their
    last loads add up to), else the scanner. Today's silence anywhere
    else -- a unit's log never sees a frame."""
    try:
        from . import look
        live = look.active("motion", sys.stderr)
    except Exception:       # noqa: BLE001 -- the pulse is never a reason to fail
        live = False
    if not live:
        return engine.warm(cfg, url)
    from . import text
    files = engine.roles(cfg)
    if files["ember"]:
        loads = [engine.last_load(files[r]) for r in engine.ROLES]
        pulse = text.Estimate("waking", sum(loads) if all(loads) else None, sys.stderr)
    else:
        pulse = text.Busy(sys.stderr, kind="swell")     # a model loading, no estimate
    with pulse:
        return engine.warm(cfg, url)


def _warm(cfg, url):
    """Load every served role now (the router loads on first use) and say
    which answered: `warm   spark, ember`."""
    warmed = _warming(cfg, url)
    say("warm   " + (", ".join(warmed) if warmed else "none loaded yet"))


def _warm_when_up(cfg, server):
    """`spark serve --warm-when-up`, private: the unit's helper. Wait for
    the server that `--foreground` is about to become, then warm it, so the
    first question after boot does not pay for the model load. Creates
    nothing (no token, no serve-url, no pidfile); gives up quietly when the
    server is gone or never answers -- the unit restarts it anyway."""
    url = wire.serve_url() or "http://%s:%d" % (cfg.serve_host or lan_ip() or "127.0.0.1", cfg.port)
    t0 = time.monotonic()
    end = time.time() + 180
    while time.time() < end:
        if wire.health(url) == "ok":
            # the unit's load, measured as spark serve's own wait is (a
            # single server answers once its model is in; warm measures
            # the router's)
            model = engine.measured_file(cfg)
            if model and time.monotonic() - t0 >= 1:
                engine.record_load(model, time.monotonic() - t0)
            _warm(cfg, url)
            return 0
        try:
            os.kill(server, 0)
        except ProcessLookupError:           # the server this waits for has exited
            return 1
        except OSError:
            pass
        time.sleep(1)
    return 1


def _spawn_warmer():
    """Before becoming the server: a detached `spark serve --warm-when-up
    PID` whose lines land in the unit's log (stdout/stderr inherited). The
    unit's pid stays the server's; the child never spawns another. A
    double fork: llama-server reaps no child, so a direct one lingered as
    a zombie for the server's whole life -- init adopts this one."""
    me = os.getpid()
    argv = [sys.executable, os.path.join(REPO, "bin", "spark"), "serve", "--warm-when-up", str(me)]
    try:
        child = os.fork()
    except OSError as e:
        say("warm   not started (%s) -- the first request loads the model" % e)
        return
    if child == 0:
        try:
            os.setsid()
            if os.fork() == 0:
                null = os.open(os.devnull, os.O_RDONLY)
                os.dup2(null, 0)
                os.execv(sys.executable, argv)
        except OSError:
            pass
        os._exit(0)
    os.waitpid(child, 0)


def _take_over(cfg, url):
    """`--foreground` finds spark's own server by hand on the port (its
    pid in serve.pid, the command line checked): the unit takes over --
    TERM, wait until it is gone. A 78 there stood the unit down for good
    while a hand server nobody watches held the port."""
    mine = engine.pidfile_pid()
    if not mine or mine not in engine.server_pids(cfg.port):
        return
    say("%s serve -- the unit takes over %s from pid %d" % (MARK, url, mine))
    engine.terminate([mine])
    if engine.wait_gone([mine], 20):
        engine.terminate([mine], force=True)
        engine.wait_gone([mine], 5)
    engine.forget()


def _through_unit(cfg, url):
    """`spark serve on` where a unit is (loaded or disabled): the manager
    starts it -- never a second server beside it -- and this waits on
    /health the way a spawn does. None when there is no unit after all
    (the caller starts by hand)."""
    started = engine.service_start(cfg)
    if started is None:
        return None
    if not started:
        return 1
    t0 = time.monotonic()

    class StoodDown(Exception):
        pass

    def probe():
        if wire.health(wire.serve_url() or url) == "ok":
            return True
        # a unit that stands down (78: misconfigured, or a server spark did
        # not start holds the port) stays down: say so now, not in 180 s
        if time.monotonic() - t0 > 5 and engine.unit_state(cfg)[0] == "down":
            raise StoodDown()
        return False

    try:
        up = engine.wait_load(cfg, "", probe, 180, 1)
    except StoodDown:
        return _die("the unit stopped -- %s" % engine.restart_line())
    if not up:
        return _die("no answer in 180 s -- %s" % engine.restart_line())
    url = wire.serve_url() or url
    pid = engine.pidfile_pid()
    at = " (pid %d)" % pid if pid else ""
    say("%s serve -- ready%s at %s" % (MARK, at, url))
    _warming(cfg, url)
    from . import check
    check.refresh()
    return 0


def cmd_serve(args, by_hand=False, wait_unit=False, start_disabled=False):
    """The engine's half of `spark serve on`, and the unit's
    `--foreground`. by_hand: a restart of a server spark started by hand
    stays by hand (model, bench) -- it never enables a unit disabled on
    purpose. wait_unit: bootstrap enabled the unit just now (`spark serve
    on`), so its server loading is waited for, not refused.
    start_disabled: only `spark serve on` starts a unit disabled on
    purpose (`serve off` kept it down); every other caller goes through
    a loaded unit, else by hand. `--host ADDR` binds ADDR, by hand: the
    unit binds its own address."""
    cfg = config.load()
    fg = "--foreground" in args
    host = ""
    if "--host" in args:
        i = args.index("--host")
        host = args[i + 1] if i + 1 < len(args) else ""
        if not host or host.startswith("-"):
            return _die("--host needs an address", 2)
        by_hand = True
    if "--warm-when-up" in args:
        # the server's pid follows the flag; an older unit's helper had
        # none and watched its parent -- that parent is the server too
        rest = args[args.index("--warm-when-up") + 1:]
        server = int(rest[0]) if rest and rest[0].isdigit() else os.getppid()
        return _warm_when_up(cfg, server)
    if cfg.base_url:
        return _die("this machine is a client of %s (SPARK_BASE_URL) -- unset it to serve here" % cfg.base_url, engine.EX_CONFIG)
    host = host or cfg.serve_host or wait_lan_ip(fg, "serve")
    if not host:
        return _die("no LAN address to bind -- set SPARK_SERVE_HOST", engine.EX_CONFIG)
    verdict, why = bind_check(host)
    if verdict == "refuse":
        return _die(why + " -- bind the one address the LAN should reach (--host ADDR)", engine.EX_CONFIG)
    if verdict:
        say("! %s" % why)
    try:
        engine_bin, model = engine.resolve_for_spawn(cfg)
    except engine.EngineError as e:
        return _die(str(e), e.code)
    files = engine.roles(cfg)
    wire.ensure_token(cfg)
    url = "http://%s:%d" % (host, cfg.port)

    if fg:
        _take_over(cfg, url)
    st = wire.health(url)
    if fg and (st == "ok" or engine.server_pids(cfg.port)):
        # the unit cannot be the server: one spark did not start answers
        # (or loads) on the port -- its own hand server was taken over just
        # now. 78 stands the unit down on every init (finish runs sv down,
        # systemd's SuccessExitStatus); a 0 made runsv restart it every
        # second, a 1 every 15 s
        say("%s serve -- %s already answers, so this unit stands down" % (MARK, url))
        return engine.EX_CONFIG
    if st == "ok":
        engine.write_serve_url(url)
        _warming(cfg, url)
        say("%s serve -- already serving at %s" % (MARK, url))
        return 0
    if st == "loading" and engine.service_state(cfg) == "loaded":
        if wait_unit and not fg:
            return _through_unit(cfg, url)
        # the unit's own server is loading (503): a second spawn would
        # fail to bind and then forget() the RUNNING server's pidfile and
        # serve-url -- refuse, the way cmd_stop refuses while the unit
        # owns the port
        return _refuse("still loading at %s -- it answers when ready" % url)
    others = engine.server_pids(cfg.port)
    mine = engine.pidfile_pid()
    if others and mine not in others:
        return _die("port %d: an engine spark did not start (pid %s) -- spark serve off --force"
                    % (cfg.port, ",".join(str(p) for p in others)))
    unit = "" if fg or by_hand else engine.service_state(cfg)

    served = [f for f in (files["spark"], files["ember"]) if f]
    need = engine.mem_needed_gb(cfg, served)
    avail = engine.mem_available_gb()
    if avail >= 0 and need > avail:
        say("! %s needs ~%.1f GB, %.1f GB free (%s)" % (" + ".join(config.model_name(f) for f in served), need, avail,
                                                       engine.top_consumers()))
    if unit == "loaded" or (unit == "disabled" and start_disabled):
        rc = _through_unit(cfg, url)
        if rc is not None:
            return rc
    engine.write_serve_url(url)
    if fg:
        _spawn_warmer()
        engine.exec_foreground(cfg, host)      # never returns
    try:
        pid = engine.spawn(cfg, host)
    except engine.EngineError as e:
        if e.code == 2:                 # the lock: another serve is starting
            return _refuse(str(e))
        return _die(str(e), e.code)

    class Exited(Exception):
        pass

    def probe():
        if wire.health(url) == "ok":
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            raise Exited()
        return False

    try:
        up = engine.wait_load(cfg, "", probe, 180, 1)
    except Exited:
        engine.forget()
        return _die("the engine stopped while loading:\n" + engine.log_tail())
    if not up:
        engine.terminate([pid])
        engine.forget()
        return _die("no answer in 180 s, stopped:\n" + engine.log_tail())
    say("%s serve -- ready (pid %d) at %s" % (MARK, pid, url))
    _warming(cfg, url)
    from . import check
    check.refresh()
    return 0


def cmd_stop(args):
    """The engine's half of `spark serve off`: its unit stopped and kept
    down (the manager's disable), spark's own server by hand TERMed, and
    a llama-server spark did not start only with --force. `--noreload`
    is an older spelling: off keeps it down anyway."""
    cfg = config.load()
    force = "--force" in args
    if cfg.base_url:
        host = cfg.base_url.split("//")[-1].split(":")[0].lower()
        if host not in own_hostnames() and host not in (lan_ip(), "127.0.0.1", "localhost"):
            return _die("SPARK_BASE_URL points at %s -- nothing on this machine to stop" % host)
    st = engine.service_state(cfg)
    mine = engine.pidfile_pid()
    pids = engine.server_pids(cfg.port)
    if st == "loaded" and mine and mine in pids:
        word, upid = engine.unit_state(cfg)
        if word in ("down", "finish") or (word == "run" and upid and upid != mine):
            # the unit is not the server (it stood down beside this one)
            # and spark's own server by hand answers: that one is ours to
            # stop first -- the services row's remedy says this verb
            engine.terminate([mine])
            if engine.wait_gone([mine], 20):
                engine.terminate([mine], force=True)
            engine.forget()
            say("%s serve -- stopped pid %d (started by hand)" % (MARK, mine))
            mine, pids = 0, engine.server_pids(cfg.port)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg) == "system":
            return _die("it runs from boot -- sudo launchctl bootout %s, or spark serve boot off"
                        % engine.service_target(cfg))
        engine.service_stop(True)
        left = engine.wait_gone(engine.server_pids(cfg.port), 20)
        if left:
            engine.terminate(left, force=True)
        engine.forget()
        say("%s serve -- the engine stopped" % MARK)
        return 0
    if mine and mine in pids:
        engine.terminate([mine])
        left = engine.wait_gone([mine], 20)
        if left and force:
            engine.terminate(left, force=True)
            left = engine.wait_gone(left, 5)
        if left:
            return _die("pid %d did not stop -- spark serve off --force" % mine)
        engine.forget()
        say("%s serve -- stopped pid %d" % (MARK, mine))
        return 0
    if pids:
        if not force:
            return _die("the engine on port %d (pid %s) was not started by spark -- spark serve off --force"
                        % (cfg.port, ",".join(str(p) for p in pids)))
        engine.terminate(pids)
        left = engine.wait_gone(pids, 10)
        if left:
            engine.terminate(left, force=True)
        engine.forget()
        say("%s serve -- killed pid %s" % (MARK, ",".join(str(p) for p in pids)))
        return 0
    engine.forget()
    say("%s serve -- the engine is not running" % MARK)
    return 0


UNIT_WORD = {"loaded": "kept up", "disabled": "kept down", "absent": "by hand"}


def _kept(cfg):
    """What spark.env keeps: "on" (the engine's unit wanted and the page
    with it), "off" (both kept down), else the two keys as they are."""
    svc, forge = cfg.service, cfg.forge
    if svc == "auto" and forge in ("auto", "on"):
        return "on"
    if svc != "auto" and forge == "off":
        return "off"
    return "SPARK_SERVICE=%s, SPARK_FORGE=%s" % (svc, forge)


def cmd_show():
    """`spark serve` alone shows, like every other bare verb: one view of
    what answers (this machine or the other), its models, the engine and
    the page here with their units, boot and share. It never mutates."""
    from . import cli, site
    cfg = config.load()
    rows = []
    try:
        brain = wire.resolve_brain(cfg, fresh=True)
    except wire.BrainError as e:
        brain = None
        rows.append(("answers", e.hint))
    if brain:
        here = wire.dest_of(brain.url)
        mine = {wire.dest_of(u) for u in (forge_url(), wire.serve_url(), cfg.loopback_url()) if u}
        where = "this machine" if here in mine or here == "local" else "the other machine"
        rows.append(("answers", "%s (%s)" % (brain.url, where)))
        roles = dict((r, s) for r, s, _l in cli._role_rows(cfg, brain.url, brain.forge))
        chat = roles.get("ember")
        rows.append(("model", "%s, chat %s" % (config.model_name(roles.get("spark", brain.model)), config.model_name(chat))
                     if chat else config.model_name(brain.model)))
    if cfg.base_url:
        say("%s serve -- a client of %s (SPARK_BASE_URL): nothing serves here" % (MARK, cfg.base_url))
    elif cfg.client:
        from .check import client_of
        say("%s serve -- %s" % (MARK, client_of(cfg)))
    else:
        url = wire.serve_url() or "http://%s:%d" % (cfg.serve_host or lan_ip() or "<lan-ip>", cfg.port)
        st = wire.health(url)
        furl = forge_url()
        fh = wire.forge_health(furl) if furl else "down"
        units = (engine.service_state(cfg), engine.service_state(cfg, "forge"))
        kept = _kept(cfg)
        if kept == "on" and st not in ("ok", "loading") and not isinstance(fh, dict) and units == ("absent", "absent"):
            # the defaults read "on", but nothing runs and no unit exists:
            # a fresh machine, not one kept up
            kept = "not set: spark serve on runs the engine and the page"
        say("%s serve -- %s" % (MARK, {"on": "on: the engine and the page, kept up",
                                       "off": "off: the engine and the page, kept down"}.get(kept, kept)))
    for label, value in rows:
        say("  %-8s %s" % (label, value))
    if cfg.base_url or cfg.client:
        return 0
    engine_is = {"ok": "serving at %s" % url, "loading": "loading at %s" % url}.get(st, "not running")
    say("  %-8s %s (%s)" % ("engine", engine_is, UNIT_WORD[units[0]]))
    page_is = ("%s/login" % furl) if isinstance(fh, dict) else "not running"
    say("  %-8s %s (%s)" % ("page", page_is, UNIT_WORD[units[1]]))
    tok = cfg.forge_token_file
    if os.path.exists(tok):
        mode = os.stat(tok).st_mode & 0o777
        login = "admin token ready (spark serve --login)" if mode == 0o600 else "admin token %04o -- chmod 600 %s" % (mode, _short(tok))
    else:
        login = "no admin token yet"
    from . import users
    n = len(users.list_users())
    say("  %-8s %s; %s" % ("login", login, "%d user%s" % (n, "" if n == 1 else "s") if n else "no users yet"))
    say("  %-8s %s" % ("boot", "on: up from boot, never asleep" if cfg.headless
                       else "from boot (runit)" if not IS_MAC and _runit()
                       else "off (spark serve boot on)"))
    why = site.no_share()
    say("  %-8s %s" % ("share", why if why else "on: the other users here use it" if cfg.share
                       else "off (spark serve share on)"))
    return 0


def _runit():
    from . import init_shape
    return init_shape() == "runit"


def _short(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def cmd_on(args):
    """`spark serve on`: the engine and the page, kept (SPARK_SERVICE=auto
    and SPARK_FORGE=on, written together), their units enabled by
    bootstrap, each waited on until it answers. The engine first: the
    page fronts it."""
    cfg = config.load()
    if cfg.base_url:
        return _die("this machine is a client of %s (SPARK_BASE_URL) -- unset it to serve here" % cfg.base_url, engine.EX_CONFIG)
    if cfg.client:
        from .check import client_of
        return _refuse(client_of(cfg))
    try:
        engine.resolve_for_spawn(cfg)        # nothing to serve: say why before anything is kept
    except engine.EngineError as e:
        return _die(str(e), e.code)
    from . import site
    wire.ensure_token(cfg)                   # bootstrap enables the unit only once a token exists
    site.set_keys(_file=SPARK_ENV, SPARK_SERVICE="auto", SPARK_FORGE="on")
    rc = site.apply(UNIT_ROWS)
    if rc:
        return rc
    rc = cmd_serve(args, wait_unit=not os.environ.get("SPARK_NO_APPLY"), start_disabled=True)
    if rc:
        return rc
    from . import forgeserve
    return forgeserve.cmd_start([])


def cmd_off(args):
    """`spark serve off`: both kept down (SPARK_SERVICE=none and
    SPARK_FORGE=off, written together), their units stopped and
    disabled; the page first, then the engine. --force also ends a
    llama-server spark did not start."""
    cfg = config.load()
    if cfg.base_url:
        return cmd_stop(args)                 # a client by SPARK_BASE_URL: nothing kept here to switch
    if cfg.client:
        from .check import client_of
        say("%s serve -- nothing serves here: %s" % (MARK, client_of(cfg)))

        return 0
    from . import check, forgeserve, site
    site.set_keys(_file=SPARK_ENV, SPARK_SERVICE="none", SPARK_FORGE="off")
    rc = site.apply(UNIT_ROWS)
    page = forgeserve.cmd_stop(["--force"])
    # a unit's stop is asynchronous (sv down, systemctl stop --no-block,
    # launchctl bootout): wait for its server to leave the port, so the
    # line below says what is true
    engine.wait_gone(engine.server_pids(cfg.port), 20)
    rc2 = cmd_stop(args)
    check.refresh()
    return rc or page or rc2


def main(sub, args):
    """`spark serve` alone shows; `on` and `off` are the only switch words
    (the grammar); boot and share are its two machine choices, --login and
    --audit the page's; --foreground and --warm-when-up are the unit's."""
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    word, rest = (args[0], args[1:]) if args else ("status", [])
    if word == "status":
        return cmd_show()
    if word == "on":
        return cmd_on(rest)
    if word == "off":
        return cmd_off(rest)
    from . import site
    if word == "boot":
        return site.cmd_headless(rest)
    if word == "share":
        return site.cmd_share(rest)
    from . import forgeserve
    if word == "--login":
        return forgeserve.cmd_login(rest)
    if word == "--print-client":                     # an older spelling: the login's client half
        return forgeserve.cmd_print_client(rest)
    if word == "--audit":
        from . import audit
        return audit.cmd_audit(rest)
    if word in ("--foreground", "--warm-when-up", "--host"):
        return cmd_serve(args)
    say("%s serve -- no word %s; spark serve -h lists them" % (MARK, word))
    return 2
