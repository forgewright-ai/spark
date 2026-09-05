# spark.serve -- `spark serve` and `spark stop`: the local llama-server,
# by hand or as the unit's foreground process.

import os
import subprocess
import sys
import time

from . import IS_MAC, MARK, REPO, config, glyph, lan_ip, own_hostnames, say, wait_ready
from . import engine, wire

USAGE = """%s serve -- start the local model server for this LAN

  spark serve                 start it in the background, wait until it answers
  spark serve --foreground    become the server (what the unit runs)
  spark serve --host ADDR     bind ADDR instead of this machine's LAN address
  spark serve --print-client  the two lines another machine needs to use it
  spark stop                  stop a server spark serve started
  spark stop --force          also the unit's, or one spark did not start
  spark stop --force --noreload   and disable the unit so it stays down
""" % MARK


def client_lines(cfg, url):
    return ["for another machine to use this server:  SPARK_BASE_URL=%s   (or SITE_PEER_AI_URL in its site.env)" % url,
            "and the token it needs:                  scp <this-machine>:%s ~/.local/state/spark/api-token" % cfg.token_file]


def _die(msg, code=1):
    print("spark serve: " + msg, file=sys.stderr, flush=True)
    return code


def _warm(cfg, url):
    """Load every served role now (the router loads on first use) and say
    which answered: `warm   spark, ember`."""
    say("warm   loading the served models now (up to ~30 s each) ...")
    warmed = engine.warm(cfg, url)
    say("warm   " + (", ".join(warmed) if warmed else "nothing answered (the first request loads the model)"))


def _warm_when_up(cfg):
    """`spark serve --warm-when-up`, private: the unit's helper. Wait for
    the server that `--foreground` is about to become, then warm it, so the
    first question after boot does not pay for the model load. Creates
    nothing (no token, no serve-url, no pidfile); gives up quietly when the
    server is gone or never answers -- the unit restarts it anyway."""
    url = wire.serve_url() or "http://%s:%d" % (cfg.serve_host or lan_ip() or "127.0.0.1", cfg.port)
    parent = os.getppid()
    end = time.time() + 180
    while time.time() < end:
        if wire.health(url) == "ok":
            _warm(cfg, url)
            return 0
        if os.getppid() != parent:           # the server this waits for has exited
            return 1
        time.sleep(1)
    return 1


def _spawn_warmer():
    """Before becoming the server: a detached `spark serve --warm-when-up`
    whose lines land in the unit's log (stdout/stderr inherited). The
    unit's pid stays the server's; the child never spawns another."""
    try:
        subprocess.Popen([sys.executable, os.path.join(REPO, "bin", "spark"), "serve", "--warm-when-up"],
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        say("warm   not started (%s) -- the first request loads the model" % e)


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
        return _warm_when_up(cfg)
    if cfg.base_url:
        return _die("this machine is a client of %s (SPARK_BASE_URL) -- unset it to serve here" % cfg.base_url, engine.EX_CONFIG)
    host = host or cfg.serve_host or _wait_lan_ip(fg)
    if not host:
        return _die("no LAN address to bind -- set SPARK_SERVE_HOST", engine.EX_CONFIG)
    if host == "0.0.0.0":
        return _die("0.0.0.0 is every interface -- bind the one address the LAN should reach (--host ADDR)", engine.EX_CONFIG)
    try:
        engine_bin, model = engine.resolve_for_spawn(cfg)
    except engine.EngineError as e:
        return _die(str(e), e.code)
    files = engine.roles(cfg)
    wire.ensure_token(cfg)
    url = "http://%s:%d" % (host, cfg.port)

    quiet = cfg.quiet_start
    st = wire.health(url)
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
    others = engine.server_pids(cfg.port)
    mine = engine.pidfile_pid()
    if others and mine not in others:
        return _die("port %d is held by llama-server pid %s that spark did not start -- `spark stop --force` first"
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
            mgr = "launchd" if IS_MAC else "systemd"
            return _die("%s would bring the server straight back -- spark stop --force stops it; --noreload keeps it down" % mgr)
        undo = engine.service_stop(noreload)
        left = engine.wait_gone(engine.server_pids(cfg.port), 20)
        if left:
            engine.terminate(left, force=True)
        engine.forget()
        say("%s stop -- %s; to bring it back: %s" % (MARK, "disabled" if noreload else "stopped", undo))
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
            return _die("pid %d survived SIGTERM -- `spark stop --force` sends SIGKILL" % mine)
        engine.forget()
        say("%s stop -- stopped pid %d" % (MARK, mine))
        return 0
    if pids:
        if not force:
            return _die("llama-server on port %d (pid %s) was not started by spark -- left alone; `spark stop --force` kills it"
                        % (cfg.port, ",".join(str(p) for p in pids)))
        engine.terminate(pids)
        left = engine.wait_gone(pids, 10)
        if left:
            engine.terminate(left, force=True)
        engine.forget()
        say("%s stop -- killed pid %s" % (MARK, ",".join(str(p) for p in pids)))
        return 0
    engine.forget()
    say("%s stop -- not running" % MARK)
    return 0


def main(sub, args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    rc = cmd_serve(args) if sub == "serve" else cmd_stop(args)
    if sub == "stop":
        from . import check
        check.refresh()
    return rc
