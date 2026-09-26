# spark.serve -- `spark serve [on|off]`: the local llama-server, by hand
# or as the unit's foreground process. on|off is the only switch
# vocabulary (the grammar); bare shows.

import os
import subprocess
import sys
import time

from . import IS_MAC, MARK, REPO, bind_check, config, glyph, lan_ip, own_hostnames, say, wait_ready
from . import engine, wire

USAGE = """%s serve -- the engine, served on this LAN

  spark serve                 status: the url, whether it answers, the model
  spark serve on              start it in the background, wait until it answers
  spark serve off             stop an engine spark serve started
  spark serve off --force     also the unit's, or one spark did not start
  spark serve off --force --noreload   and disable the unit so it stays down
  spark serve --foreground    become the engine (what the unit runs)
  spark serve --host ADDR     bind ADDR instead of this machine's LAN address
  spark serve --print-client  the two lines another machine needs to use it
""" % MARK


def client_lines(cfg, url):
    return ["for another machine to use this server:  SPARK_BASE_URL=%s   (or SITE_PEER_AI_URL in its site.env)" % url,
            "and the token it needs:                  scp <this-machine>:%s ~/.local/state/spark/api-token" % cfg.token_file]


def _die(msg, code=1):
    print("spark serve: " + msg, file=sys.stderr, flush=True)
    return code


def _refuse(msg):
    """A gate refusal, signed (contract 8): stdout, exit 2. The world did
    not fail -- something says this invocation does not happen here, and
    `spark update`'s lock answers in the same shape."""
    say("%s serve -- %s" % (MARK, msg))
    return 2


def _warm(cfg, url):
    """Load every served role now (the router loads on first use) and say
    which answered: `warm   spark, ember`."""
    say("warm   loading the served models now (up to ~30 s each) ...")
    warmed = engine.warm(cfg, url)
    say("warm   " + (", ".join(warmed) if warmed else "nothing answered (the first request loads the model)"))


def _warm_when_up(cfg, server):
    """`spark serve --warm-when-up`, private: the unit's helper. Wait for
    the server that `--foreground` is about to become, then warm it, so the
    first question after boot does not pay for the model load. Creates
    nothing (no token, no serve-url, no pidfile); gives up quietly when the
    server is gone or never answers -- the unit restarts it anyway."""
    url = wire.serve_url() or "http://%s:%d" % (cfg.serve_host or lan_ip() or "127.0.0.1", cfg.port)
    end = time.time() + 180
    while time.time() < end:
        if wire.health(url) == "ok":
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


def _wait_lan_ip(foreground):
    """At login the network may not be up yet; a unit waits, a person does not."""
    ip = lan_ip()
    tries = 60 if foreground else 1
    while not ip and tries > 1:
        time.sleep(5)
        tries -= 1
        ip = lan_ip()
    return ip


def cmd_serve(args):
    cfg = config.load()
    fg = "--foreground" in args
    host = ""
    if "--host" in args:
        i = args.index("--host")
        host = args[i + 1] if i + 1 < len(args) else ""
    if "--print-client" in args:
        url = wire.serve_url() or "http://%s:%d" % (cfg.serve_host or lan_ip() or "<lan-ip>", cfg.port)
        say("\n".join(client_lines(cfg, url)))
        return 0
    if "--warm-when-up" in args:
        # the server's pid follows the flag; an older unit's helper had
        # none and watched its parent -- that parent is the server too
        rest = args[args.index("--warm-when-up") + 1:]
        server = int(rest[0]) if rest and rest[0].isdigit() else os.getppid()
        return _warm_when_up(cfg, server)
    if cfg.base_url:
        return _die("this machine is a client of %s (SPARK_BASE_URL) -- unset it to serve here" % cfg.base_url, engine.EX_CONFIG)
    host = host or cfg.serve_host or _wait_lan_ip(fg)
    if not host:
        return _die("no LAN address to bind -- set SPARK_SERVE_HOST", engine.EX_CONFIG)
    verdict, why = bind_check(host)
    if verdict == "refuse":
        return _die(why + " -- bind the one address the LAN should reach (--host ADDR)", engine.EX_CONFIG)
    if verdict:
        say("%s serve -- warning: %s" % (MARK, why))
    try:
        engine_bin, model = engine.resolve_for_spawn(cfg)
    except engine.EngineError as e:
        return _die(str(e), e.code)
    files = engine.roles(cfg)
    wire.ensure_token(cfg)
    url = "http://%s:%d" % (host, cfg.port)

    quiet = cfg.quiet_start
    st = wire.health(url)
    if st == "ok" and fg:
        # the unit cannot be the server: another one answers on the port
        # (a hand-started spark serve, another llama-server). 78 stands the
        # unit down on both inits (finish runs sv down, systemd's
        # SuccessExitStatus); a 0 made runsv restart it every second
        say("%s serve -- %s already answers, so this unit stands down" % (MARK, url))
        return engine.EX_CONFIG
    if st == "ok":
        engine.write_serve_url(url)
        if quiet:
            engine.warm(cfg, url)
            say("%s serve -- already serving at %s" % (MARK, url))
            return 0
        say("%s serve -- already serving at %s" % (MARK, url))
        say("\n".join(client_lines(cfg, url)))
        _warm(cfg, url)
        return 0
    if st == "loading" and engine.service_state(cfg) == "loaded":
        # the unit's own server is loading (503): a second spawn would
        # fail to bind and then forget() the RUNNING server's pidfile and
        # serve-url -- refuse, the way cmd_stop refuses while the unit
        # owns the port
        return _refuse("the unit's server is loading at %s -- it answers when ready" % url)
    others = engine.server_pids(cfg.port)
    mine = engine.pidfile_pid()
    if others and mine not in others:
        return _die("port %d is held by llama-server pid %s that spark did not start -- `spark serve off --force` first"
                    % (cfg.port, ",".join(str(p) for p in others)))

    served = [f for f in (files["spark"], files["ember"]) if f]
    need = engine.mem_needed_gb(cfg, served)
    avail = engine.mem_available_gb()
    if avail >= 0 and need > avail:
        say("%s serve -- %s needs ~%.1f GB, %.1f GB free (%s)" % (MARK, " + ".join(os.path.basename(f) for f in served), need, avail, engine.top_consumers()))
    sep = glyph("sep")
    if not quiet:
        what = sep.join("%s %s (%.1f GB)" % (role, os.path.basename(files[role]), os.path.getsize(files[role]) / 2**30)
                        for role in engine.ROLES if files[role])
        say("%s serve%sengine %s%s%s%s%s (token required)" % (MARK, sep, engine.engine_dir(cfg), sep, what, sep, url))
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
        up = wait_ready("" if quiet else "loading", probe, 180, 1)
    except Exited:
        engine.forget()
        return _die("llama-server exited while loading:\n" + engine.log_tail())
    if not up:
        engine.terminate([pid])
        engine.forget()
        return _die("no answer from llama-server in 180 s -- stopped; the log tail:\n" + engine.log_tail())
    if quiet:
        say("%s serve -- ready (pid %d) at %s" % (MARK, pid, url))
        engine.warm(cfg, url)
    else:
        sys.stdout.write(" ready (pid %d)\n" % pid)
        _warm(cfg, url)
        say("\n".join(client_lines(cfg, url)))
    from . import check
    check.refresh()
    return 0


def cmd_stop(args):
    cfg = config.load()
    force = "--force" in args
    noreload = "--noreload" in args
    if cfg.base_url:
        host = cfg.base_url.split("//")[-1].split(":")[0].lower()
        if host not in own_hostnames() and host not in (lan_ip(), "127.0.0.1", "localhost"):
            return _die("SPARK_BASE_URL points at %s -- nothing on this machine to stop" % host)
    st = engine.service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg) == "system":
            return _die("the server is a LaunchDaemon (spark headless on) -- sudo launchctl bootout %s stops it; spark headless off puts it back under your login" % engine.service_target(cfg))
        if not force:
            from . import init_shape
            mgr = init_shape()
            return _die("%s would bring the server straight back -- spark serve off --force stops it; --noreload keeps it down" % mgr)
        undo = engine.service_stop(noreload)
        left = engine.wait_gone(engine.server_pids(cfg.port), 20)
        if left:
            engine.terminate(left, force=True)
        engine.forget()
        say("%s serve -- %s; to bring it back: %s" % (MARK, "disabled" if noreload else "stopped", undo))
        return 0
    if noreload:
        return _die("nothing to disable -- no unit here (%s)" % ("disabled already" if st == "disabled" else "on demand"))
    mine = engine.pidfile_pid()
    pids = engine.server_pids(cfg.port)
    if mine and mine in pids:
        engine.terminate([mine])
        left = engine.wait_gone([mine], 20)
        if left and force:
            engine.terminate(left, force=True)
            left = engine.wait_gone(left, 5)
        if left:
            return _die("pid %d survived SIGTERM -- `spark serve off --force` sends SIGKILL" % mine)
        engine.forget()
        say("%s serve -- stopped pid %d" % (MARK, mine))
        return 0
    if pids:
        if not force:
            return _die("llama-server on port %d (pid %s) was not started by spark -- left alone; `spark serve off --force` kills it"
                        % (cfg.port, ",".join(str(p) for p in pids)))
        engine.terminate(pids)
        left = engine.wait_gone(pids, 10)
        if left:
            engine.terminate(left, force=True)
        engine.forget()
        say("%s serve -- killed pid %s" % (MARK, ",".join(str(p) for p in pids)))
        return 0
    engine.forget()
    say("%s serve -- not running" % MARK)
    return 0


def cmd_show():
    """`spark serve` alone shows, like every other bare verb: where it
    would serve, whether anything answers there, and with what."""
    cfg = config.load()
    if cfg.base_url:
        say("%s serve -- a client of %s (SPARK_BASE_URL): nothing serves here" % (MARK, cfg.base_url))
        return 0
    if cfg.client:                                     # the check rows say the same
        from .check import client_of
        say("%s serve -- %s" % (MARK, client_of(cfg)))
        return 0
    url = wire.serve_url() or "http://%s:%d" % (cfg.serve_host or lan_ip() or "<lan-ip>", cfg.port)
    st = wire.health(url)
    if st == "loading":
        say("%s serve -- loading its model at %s" % (MARK, url))
        return 0
    if st != "ok":
        say("%s serve -- not running (spark serve on)" % MARK)
        return 0
    what = ""
    try:
        files = engine.roles(cfg)
        what = ", ".join(os.path.basename(files[r]) for r in engine.ROLES if files.get(r))
    except Exception:                      # a report never fails on its own detail
        pass
    say("%s serve -- serving at %s%s" % (MARK, url, " (%s)" % what if what else ""))
    return 0


def main(sub, args):
    """`spark serve` alone shows; `on` and `off` are the only switch words
    (the grammar), and every other argument is the unit's own entry point."""
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if not args or args[0] == "status":
        return cmd_show()
    if args[0] == "on":
        return cmd_serve(args[1:])
    if args[0] == "off":
        rc = cmd_stop(args[1:])
        from . import check
        check.refresh()
        return rc
    return cmd_serve(args)
