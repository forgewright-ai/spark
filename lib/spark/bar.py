# spark.bar -- one line for tmux's status-right, on both OSes.
#
# load · mem · disk · net · ai (when a model is loaded: 9 GB must never be
# invisible) · check heartbeat · battery · clock. Written to state/bar with
# a timestamp so `spark check` can tell when the bar stopped ticking.

import json
import os
import shutil
import sys
import time

from . import BAR_CACHE, CHECK_JSON, IS_MAC, SERVE_URL_FILE, config, glyph, lan_ip, run, say, state_dir

INTERVAL = 5          # what .tmux.conf's status-interval is
SEP = glyph("sep")


def _load():
    try:
        return "%.2f" % os.getloadavg()[0]
    except OSError:
        return ""


def _mem():
    """percent of physical memory in use"""
    try:
        if IS_MAC:
            rc, out = run(["vm_stat"])
            if rc != 0:
                return ""
            page = 4096
            vals = {}
            for line in out.splitlines():
                if line.startswith("Mach Virtual Memory Statistics"):
                    if "page size of" in line:
                        page = int(line.split("page size of")[1].split()[0])
                    continue
                k, _, v = line.partition(":")
                vals[k.strip()] = int(v.strip().rstrip("."))
            used = (vals.get("Pages active", 0) + vals.get("Pages wired down", 0)
                    + vals.get("Pages occupied by compressor", 0)) * page
            rc, out = run(["sysctl", "-n", "hw.memsize"])
            total = int(out.strip())
        else:
            m = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    m[k] = int(v.split()[0]) * 1024
            total = m["MemTotal"]
            used = total - m.get("MemAvailable", 0)
        return "%d%%" % (100 * used / total)
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        return ""


def _disk():
    try:
        u = shutil.disk_usage("/")
        return "%dG" % (u.free // 2**30)
    except OSError:
        return ""


def _net_bytes():
    """(rx, tx) of the default-route interface, or None"""
    try:
        if IS_MAC:
            rc, out = run(["route", "-n", "get", "default"])
            iface = ""
            for line in out.splitlines():
                if "interface:" in line:
                    iface = line.split(":")[1].strip()
            if not iface:
                return None
            rc, out = run(["netstat", "-ibn", "-I", iface])
            for line in out.splitlines()[1:]:
                p = line.split()
                if len(p) >= 10 and p[2].startswith("<Link"):
                    return int(p[6]), int(p[9])
            return None
        rc, out = run(["ip", "route", "show", "default"])
        p = out.split()
        if "dev" not in p:
            return None
        iface = p[p.index("dev") + 1]
        with open("/proc/net/dev", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(iface + ":"):
                    q = line.split(":")[1].split()
                    return int(q[0]), int(q[8])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _rate(prev, now, dt):
    if not prev or not now or dt <= 0:
        return ""
    rx = max(0, now[0] - prev[0]) / dt
    tx = max(0, now[1] - prev[1]) / dt

    def h(b):
        return "%dK" % (b / 1024) if b < 1024**2 else "%.1fM" % (b / 1024**2)
    return "%s%s %s%s" % (glyph("down"), h(rx), glyph("up"), h(tx))


def _ai(cfg, accent):
    rc, _ = run(["pgrep", "-x", "llama-server"])
    if rc != 0:
        return ""
    moved = ""
    try:
        with open(SERVE_URL_FILE, encoding="utf-8") as f:
            host = f.read().strip().split("//")[-1].split(":")[0]
        ip = lan_ip()
        if host and ip and host != ip and host not in ("127.0.0.1", "localhost"):
            moved = " moved"
    except OSError:
        pass
    speed = ""
    try:
        from . import session
        t = session.last_turn() or {}
        ts = time.mktime(time.strptime(t.get("ts", ""), "%Y-%m-%d %H:%M:%S")) if t.get("ts") else 0
        if t.get("tg_tps") and time.time() - ts < 600:
            speed = " %dt/s" % round(t["tg_tps"])
    except (ValueError, OverflowError):
        pass
    gpu = ""
    from . import engine
    g = engine.gpu_info()
    if "busy" in g:
        gpu = SEP + "gpu %d%%" % g["busy"]
    return "#[fg=%s,bold]ai%s%s#[default]%s" % (accent, speed, moved, gpu)


def _check():
    try:
        with open(CHECK_JSON, encoding="utf-8") as f:
            d = json.load(f)
        c = d["counts"]
        age = time.time() - d["ts"]
        s = "%s%d" % (glyph("ok"), c["ok"]) + (" %s%d" % (glyph("fail"), c["fail"]) if c["fail"] else "") + (" !%d" % c["warn"] if c["warn"] else "")
        if age > 2 * 300:
            s += " stale"
        elif age > 120:
            s += " %dm" % (age // 60)
        return s
    except (OSError, ValueError, KeyError):
        return "check ?"


def _battery():
    try:
        if IS_MAC:
            rc, out = run(["pmset", "-g", "batt"])
            on_ac = "AC Power" in out
            for line in out.splitlines():
                if "%" in line:
                    pct = line.split("%")[0].split()[-1]
                    return "%s%%%s" % (pct, "" if on_ac else glyph("down"))
            return ""
        base = "/sys/class/power_supply"
        for name in sorted(os.listdir(base)):
            if name.startswith("BAT"):
                with open(os.path.join(base, name, "capacity"), encoding="utf-8") as f:
                    pct = f.read().strip()
                with open(os.path.join(base, name, "status"), encoding="utf-8") as f:
                    st = f.read().strip()
                return "%s%%%s" % (pct, glyph("down") if st == "Discharging" else "")
    except (OSError, ValueError, IndexError):
        pass
    return ""


def _accent():
    """the palette's accent from theme.env, or a plain bold"""
    try:
        from . import CONFIG_DIR
        for line in open(os.path.join(CONFIG_DIR, "theme.env"), encoding="utf-8"):
            if line.startswith("THEME_ACCENT="):
                return line.strip().split("=", 1)[1]
    except OSError:
        pass
    return "default"


def line(cfg):
    now = time.time()
    prev = {}
    try:
        with open(BAR_CACHE, encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        pass
    net = _net_bytes()
    parts = [
        "load " + _load(),
        "mem " + _mem(),
        "disk " + _disk(),
        _rate(tuple(prev.get("net") or ()), net, now - prev.get("t", 0)),
        _ai(cfg, _accent()),
        _check(),
        _battery(),
        time.strftime("%H:%M"),
    ]
    s = SEP.join(p for p in parts if p and not p.endswith(" ")) + " "
    try:
        state_dir()
        with open(BAR_CACHE, "w", encoding="utf-8") as f:
            json.dump({"t": now, "net": net, "line": s}, f)
    except OSError:
        pass
    return s


USAGE = """spark bar -- tmux's status line

  spark bar            show or hide it (a toggle), inside tmux
  spark bar on | off   set it
  spark bar line       print the line itself -- what .tmux.conf's status-right runs
"""


def _tmux(*args):
    return run(["tmux"] + list(args))


def _status_on():
    rc, out = _tmux("show", "-gv", "status")
    return rc == 0 and out.strip() != "off"


def main(argv):
    sub = argv[0] if argv else ""
    if sub in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    from . import site
    if site.shell_off("bar"):      # the status line is the shell layer's (tmux)
        return 2
    if sub == "line":
        say(line(config.load()))
        return 0
    if sub not in ("", "on", "off", "toggle"):
        say(USAGE.rstrip())
        return 2
    if sub == "" and not sys.stdout.isatty():
        # tmux runs status-right without a tty; a config that says
        # "#(spark bar)" must draw the bar, never toggle it off
        say(line(config.load()))
        return 0
    rc, _ = _tmux("list-sessions")
    if rc != 0:
        say("spark bar: no tmux running -- the status line is tmux's (tmux starts one)")
        return 1
    want = {"on": True, "off": False}.get(sub, not _status_on())
    _tmux("set", "-g", "status", "on" if want else "off")
    say("spark bar -- %s" % ("shown (spark bar off hides it)" if want else "hidden (spark bar on brings it back)"))
    return 0
