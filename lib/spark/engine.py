# spark.engine -- the model server on this machine: where the engine and
# the model are, how to start llama-server and find it again, and what the
# service manager (systemd or launchd) thinks of it.

import fcntl
import os
import re
import signal
import subprocess
import time

from . import (IS_MAC, LOCK_FILE, PID_FILE, SERVE_LOG, SERVE_URL_FILE, STATE_DIR, config, run,
               state_dir)

EX_CONFIG = 78          # sysexits: a missing engine, model or token -- not a crash

# The two roles a served model plays (the plan's naming): `spark` is the
# small model at the prompt line, `ember` the larger one for conversations.
# The line never needs more context than this; the ember uses SPARK_CTX.
ROLES = ("spark", "ember")
SPARK_LINE_CTX = 4096
ROUTER_DIR = os.path.join(STATE_DIR, "router")      # spark.gguf, ember.gguf, presets.ini
WARM_TIMEOUT = 30


class EngineError(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------- locations
def engine_dir(cfg):
    return cfg.engine_dir or config.default_engine_dir()


def engine_bin(cfg):
    p = os.path.join(engine_dir(cfg), "llama-server")
    return p if os.access(p, os.X_OK) else ""


SPEED_CAP_GB = {"cpu": 3, "vulkan": 6, "metal": 20}     # the largest file auto takes, per backend (bootstrap.sh speed_cap is the twin)


def speed_cap_gb(cfg):
    """The largest model file (GB) an auto choice takes on this backend:
    the size classes SPEED_TABLE keeps at about 8 tok/s or better -- cpu
    up to 3 GB (~10), vulkan up to 6 GB (~9), metal anything that fits."""
    return SPEED_CAP_GB.get(backend(cfg), SPEED_CAP_GB["cpu"])


def _usable(row, cap_gb):
    """The file is at or under the cap; a `-a3b` MoE counts as its 3B
    active class, as speed_estimate does. No cap: everything is."""
    return cap_gb is None or "-a3b" in row[0].lower() or row[3] <= cap_gb * 2**30


def _pick(curated, all_rows, choice, budget, beside=0.0, cap_gb=None):
    """One row (sorted by ram_gb) for a choice: none -> None; a name ->
    that row from any of the three lists plus yours (or None when there is
    no such row), never second-guessed; auto -> the largest curated row
    whose ram_gb fits the budget beside `beside` GB and whose file is
    under the speed cap -- nothing under the cap fits, the smallest
    curated row that fits (never nothing while something fits). `auto`
    never leaves the curated table: the ember and community lists are
    by-name only."""
    if choice == "none":
        return None
    if choice == "auto":
        fits = [r for r in curated if beside + r[5] <= budget]
        usable = [r for r in fits if _usable(r, cap_gb)]
        return usable[-1] if usable else (fits[0] if fits else None)
    for r in all_rows:
        if r[0] == choice:
            return r
    return None


def _choose(cfg, cap_gb):
    from . import mem_total_gb
    try:
        rows = sorted(config.model_tables(), key=lambda r: r[5])
    except SystemExit:
        rows = []
    curated = [r for r in rows if r[6] == "curated"]
    budget = mem_total_gb() * cfg.ai_budget / 100.0
    sc, ec = cfg.model_choice, cfg.ember_model
    spark = ember = None
    if sc == "auto":
        if ec != "none" and curated:
            ember = _pick(curated, rows, ec, budget, curated[0][5], cap_gb)
            if ember:
                spark = curated[0]
        if not spark:
            spark = _pick(curated, rows, "auto", budget, 0.0, cap_gb)
            ember = None
    else:
        spark = _pick(curated, rows, sc, budget)
        ember = _pick(curated, rows, ec, budget, spark[5], cap_gb) if spark else None
    if ember and spark and ember[1] == spark[1]:
        ember = None
    return {"spark": spark, "ember": ember}


def chosen_rows(cfg):
    """{"spark": row|None, "ember": row|None} from models.env, the same
    choice bootstrap.sh model_pick makes (the rule, in one place):
    ember none (the default) -> no ember; ember NAME -> that row; ember
    auto -> the largest usable row that fits the SITE_AI_BUDGET percent
    (default 60) of RAM+GPU beside the spark row. spark none -> no spark;
    spark NAME -> that row; spark auto -> the smallest row when an ember
    then fits beside it, else the largest
    usable row that fits alone (the default, with the ember none), with no
    ember. Usable = the file is under this backend's speed cap
    (speed_cap_gb); nothing usable fits -> the smallest row that fits. A
    name is never second-guessed. The same file in both roles is one model
    doing both: no ember. No spark row (none, or a name that is not there)
    means nothing is served here: no ember either."""
    return _choose(cfg, speed_cap_gb(cfg))


def cap_note(cfg):
    """One line for the table's header when the speed cap held a bigger
    auto pick back (bootstrap.sh cap_note is the twin), else ""."""
    if _choose(cfg, None) == chosen_rows(cfg):
        return ""
    return "auto stops at %d GB files on %s (bigger fits, slower than 8 tok/s)" % (speed_cap_gb(cfg), backend(cfg))


def chosen_model_name(cfg, role="spark"):
    """The file a role's choice names in models.env, or "" (none, nothing
    fits, no such row). Empty for none."""
    r = chosen_rows(cfg).get(role)
    return r[1] if r else ""


def model_file(cfg, role="spark"):
    """The .gguf a role serves. spark: SPARK_MODEL (name in the models dir,
    or a path); else the file SITE_AI_MODEL chose, when it is there; else
    the newest .gguf in the models dir. ember: the file SITE_EMBER_MODEL
    chose, when it is there and is not the spark file. Empty when there
    is none."""
    if role == "ember":
        chosen = chosen_model_name(cfg, "ember")
        p = os.path.join(cfg.models_dir, chosen) if chosen else ""
        return p if p and os.path.isfile(p) and p != model_file(cfg) else ""
    m = cfg.model
    if m:
        p = m if os.path.isabs(m) else os.path.join(cfg.models_dir, m)
        return p if os.path.isfile(p) else ""
    if cfg.get("SITE_AI_MODEL", "auto").strip().lower() == "none":
        return ""    # the user chose none; a stray .gguf on disk is not a choice
    chosen = chosen_model_name(cfg)
    if chosen and os.path.isfile(os.path.join(cfg.models_dir, chosen)):
        return os.path.join(cfg.models_dir, chosen)
    try:
        files = [os.path.join(cfg.models_dir, f) for f in os.listdir(cfg.models_dir) if f.endswith(".gguf")]
    except OSError:
        return ""
    files = [f for f in files if os.path.isfile(f)]
    return max(files, key=os.path.getmtime) if files else ""


def roles(cfg):
    """{"spark": file|"", "ember": file|""}: the model each role serves."""
    return {r: model_file(cfg, r) for r in ROLES}


def resolve_for_spawn(cfg):
    """(engine binary, the spark role's model path), or EngineError(78)
    naming bootstrap. A named ember that is not in models.env is a
    misconfiguration too: say so rather than serve one model quietly."""
    b = engine_bin(cfg)
    if not b:
        raise EngineError("no llama-server in %s -- ./bootstrap.sh installs it (or set SPARK_ENGINE_DIR)" % engine_dir(cfg), EX_CONFIG)
    m = model_file(cfg)
    if not m:
        raise EngineError("no model in %s -- ./bootstrap.sh downloads one (or set SPARK_MODEL)" % cfg.models_dir, EX_CONFIG)
    ec = cfg.ember_model
    if ec not in ("auto", "none") and not chosen_model_name(cfg, "ember"):
        raise EngineError("SITE_EMBER_MODEL=%s: no such row in models.env (./bootstrap.sh --list-models; spark ember none)" % ec, EX_CONFIG)
    return b, m


def tuning_args(cfg):
    """The performance knobs, as llama-server and llama-bench both take them."""
    args = ["-ngl", cfg.ngl, "-fa", cfg.flash_attn, "-ctk", cfg.kv, "-ctv", cfg.kv]
    if cfg.threads:
        args += ["-t", cfg.threads]
    return args


def settings_key(cfg):
    """One string naming the settings a measurement was taken with."""
    return "ngl=%s fa=%s kv=%s t=%s" % (cfg.ngl, cfg.flash_attn, cfg.kv, cfg.threads or "auto")


def _preset(name, path, ctx, cfg, reasoning):
    """One [name] section of presets.ini: the long option names llama-server
    takes, without dashes. reasoning = off makes a thinking model answer
    the prompt line plainly; the ember keeps the model's own default."""
    lines = ["[%s]" % name, "model = %s" % path, "ctx-size = %s" % ctx, "n-gpu-layers = %s" % cfg.ngl]
    if reasoning:
        lines.append("reasoning = %s" % reasoning)
    lines += ["webui = 0", "flash-attn = %s" % cfg.flash_attn, "cache-type-k = %s" % cfg.kv, "cache-type-v = %s" % cfg.kv]
    if cfg.threads:
        lines.append("threads = %s" % cfg.threads)
    return "\n".join(lines) + "\n"


def _link(path, target):
    """A symlink at path to target (replaced when it points elsewhere), or
    none when target is empty."""
    try:
        if os.readlink(path) == target:
            return
    except OSError:
        pass
    try:
        os.remove(path)
    except OSError:
        pass
    if target:
        os.symlink(target, path)


def write_router(cfg):
    """The router's directory: spark.gguf and ember.gguf (symlinks to the
    two roles' files; a stale ember link goes when there is none) and
    presets.ini rendered from the config. Returns (dir, presets path)."""
    state_dir()
    os.makedirs(ROUTER_DIR, exist_ok=True)
    os.chmod(ROUTER_DIR, 0o700)
    files = roles(cfg)
    for role in ROLES:
        _link(os.path.join(ROUTER_DIR, role + ".gguf"), files[role])
    ini = _preset("spark", files["spark"], SPARK_LINE_CTX, cfg, "off")
    if files["ember"]:
        ini += "\n" + _preset("ember", files["ember"], cfg.ctx, cfg, "")
    path = os.path.join(ROUTER_DIR, "presets.ini")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(ini)
    return ROUTER_DIR, path


def model_stem(path):
    return os.path.basename(path).replace(".gguf", "")


def server_cmd(cfg, host):
    """The llama-server argv. With an ember: the router (one process, one
    port; a child per model on demand, presets.ini giving each its args;
    the request's `model` field picks spark or ember). Without: the single
    server as v0.3, aliased spark and by its file stem, so `model: spark`
    (or anything) is accepted and /v1/models still names the file."""
    files = roles(cfg)
    common = ["--host", host, "--port", str(cfg.port)]
    if files["ember"]:
        d, ini = write_router(cfg)
        return ([engine_bin(cfg), "--models-dir", d, "--models-preset", ini, "--models-max", "2"] + common
                + ["--api-key-file", cfg.token_file, "--no-webui", "--no-slots"] + cfg.extra_args)
    write_router(cfg)                      # keeps the dir honest: drops a stale ember link
    m = files["spark"]
    # one model in both roles answers the prompt line: no thinking, as the
    # router's [spark] preset says (a thinking model's reasoning is not
    # JSON, and it is slow); SPARK_EXTRA_ARGS comes last and may say otherwise
    return ([engine_bin(cfg), "-m", m, "--alias", "spark," + model_stem(m)] + common
            + ["-c", cfg.ctx, "--reasoning", "off", "--api-key-file", cfg.token_file, "--no-webui", "--no-slots"]
            + tuning_args(cfg) + cfg.extra_args)


# ------------------------------------------------------------------- warm
def models_status(cfg, url, timeout=5.0):
    """{alias: "loaded"|"unloaded"|...} from /v1/models: the router reports
    each model's state; a single server lists its one model, loaded. {}
    when nothing answers."""
    from . import wire
    try:
        return {alias: ("loaded" if loaded else "unloaded") for alias, _stem, loaded in wire.models(cfg, url, timeout)}
    except wire.BrainError:
        return {}


def warm(cfg, url):
    """One 1-token request per served role, so the children are loaded
    before anyone asks (the router loads on first use, which would make
    the first `?` wait). Errors are ignored; returns the roles that
    answered, in ROLES order."""
    import json
    import urllib.request
    from . import wire
    listed = models_status(cfg, url)
    done = []
    for role in ROLES:
        if role not in listed:
            continue
        body = json.dumps({"model": role, "messages": [{"role": "user", "content": "hi"}],
                           "max_tokens": 1, "stream": False}).encode()
        req = urllib.request.Request(url + "/v1/chat/completions", data=body, headers=wire.request_headers(cfg))
        try:
            with urllib.request.urlopen(req, timeout=WARM_TIMEOUT) as r:
                r.read()
            done.append(role)
        except (OSError, ValueError):
            pass
    return done


SYSFS_DRM = os.environ.get("SPARK_SYSFS_DRM", "/sys/class/drm")


def gpu_info():
    """Linux amdgpu/i915 counters readable without root, or {} (macOS has
    none without sudo). Keys: busy (percent), vram_used, vram_total,
    gtt_used, gtt_total (bytes), name."""
    if IS_MAC and "SPARK_SYSFS_DRM" not in os.environ:
        return {}
    try:
        cards = sorted(c for c in os.listdir(SYSFS_DRM) if re.match(r"^card\d+$", c))
    except OSError:
        return {}
    for c in cards:
        d = os.path.join(SYSFS_DRM, c, "device")
        info = {}
        for key, name in (("busy", "gpu_busy_percent"), ("vram_used", "mem_info_vram_used"),
                          ("vram_total", "mem_info_vram_total"), ("gtt_used", "mem_info_gtt_used"),
                          ("gtt_total", "mem_info_gtt_total")):
            try:
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    info[key] = int(f.read().strip())
            except (OSError, ValueError):
                pass
        if "vram_total" in info:
            info["name"] = c
            return info
    return {}


def server_env(cfg):
    """The tarball ships its libraries beside the binary."""
    env = dict(os.environ)
    d = engine_dir(cfg)
    key = "DYLD_LIBRARY_PATH" if IS_MAC else "LD_LIBRARY_PATH"
    env[key] = d + (":" + env[key] if env.get(key) else "")
    return env


# ------------------------------------------------------------------ memory
def mem_available_gb():
    try:
        if IS_MAC:
            rc, out = run(["vm_stat"])
            page, free = 4096, 0
            for line in out.splitlines():
                if "page size of" in line:
                    page = int(line.split("page size of")[1].split()[0])
                for k in ("Pages free", "Pages inactive", "Pages speculative"):
                    if line.startswith(k + ":"):
                        free += int(line.split(":")[1].strip().rstrip("."))
            return free * page / 2**30
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2**20
    except (OSError, ValueError):
        pass
    return -1


def top_consumers(n=3):
    rc, out = run(["ps", "-axm", "-o", "rss=,comm="] if IS_MAC else ["ps", "-axo", "rss=,comm=", "--sort=-rss"])
    rows = []
    for line in out.splitlines()[:n]:
        p = line.split(None, 1)
        if len(p) == 2:
            try:
                rows.append("%s %.1fG" % (os.path.basename(p[1]), int(p[0]) / 2**20))
            except ValueError:
                pass
    return ", ".join(rows)


def mem_needed_gb(cfg, model):
    """GB the server needs for one model path, or for a list of them (the
    router's roles together). SPARK_MEM_NEEDED_GB overrides the whole."""
    if cfg.mem_needed_gb:
        return cfg.mem_needed_gb
    files = model if isinstance(model, (list, tuple)) else [model]
    try:
        return sum(os.path.getsize(f) / 2**30 * 1.1 + 1.5 for f in files if f)
    except OSError:
        return 0


# --------------------------------------------------------------- processes
def server_pids(port):
    """pids of every llama-server bound to this port, ours or not"""
    rc, out = run(["ps", "-axo", "pid=,command="])
    pat = re.compile(r"llama-server\b.*--port\s+%d\b" % port)
    pids = []
    for line in out.splitlines():
        p = line.split(None, 1)
        if len(p) == 2 and pat.search(p[1]):
            try:
                pids.append(int(p[0]))
            except ValueError:
                pass
    return pids


def pidfile_pid():
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return 0


def write_pidfile(pid):
    state_dir()
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write("%d\n" % pid)


def write_serve_url(url):
    state_dir()
    fd = os.open(SERVE_URL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(url + "\n")


def forget():
    for p in (SERVE_URL_FILE, PID_FILE):
        try:
            os.remove(p)
        except OSError:
            pass


def wait_gone(pids, timeout):
    end = time.time() + timeout
    while time.time() < end:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except OSError:
                pass
        if not alive:
            return []
        time.sleep(0.3)
    return alive


def terminate(pids, force=False):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        except OSError:
            pass


def _rotate_log():
    try:
        if os.path.getsize(SERVE_LOG) > 1_000_000:
            os.replace(SERVE_LOG, SERVE_LOG + ".1")
    except OSError:
        pass


RENDER_NODE = "/dev/dri/renderD128"


def render_wrap(argv):
    """Linux: a user just added to the render group has the GPU on the
    next login, not in this session (the user manager keeps its groups),
    so a server started now would fall back to the CPU. `sg render`
    reads the group file afresh; `exec` inside it keeps the pid. Only
    when the node is there, not open to us, and the group lists us."""
    if IS_MAC or not os.path.exists(RENDER_NODE) or os.access(RENDER_NODE, os.R_OK | os.W_OK):
        return argv
    try:
        import grp
        import pwd
        import shlex
        import shutil
        me = pwd.getpwuid(os.getuid()).pw_name
        if me not in grp.getgrnam("render").gr_mem or not shutil.which("sg"):
            return argv
    except (KeyError, OSError):
        return argv
    return ["sg", "render", "-c", "exec " + " ".join(shlex.quote(a) for a in argv)]


def spawn(cfg, host):
    """Start llama-server detached, log to serve.log. Returns the pid.
    The lock keeps two `spark serve` from racing for the port."""
    state_dir()
    lock = os.open(LOCK_FILE, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock)
        raise EngineError("another `spark serve` is starting right now")
    _rotate_log()
    log = os.open(SERVE_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        p = subprocess.Popen(render_wrap(server_cmd(cfg, host)), env=server_env(cfg), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True)
    finally:
        os.close(log)
        os.close(lock)
    write_pidfile(p.pid)
    return p.pid


def exec_foreground(cfg, host):
    """Become llama-server: the unit's pid is the server's."""
    write_pidfile(os.getpid())
    argv = render_wrap(server_cmd(cfg, host))
    if argv[0] == "sg":
        os.execvpe("sg", argv, server_env(cfg))
    os.execve(engine_bin(cfg), argv, server_env(cfg))


def log_tail(n=8):
    try:
        with open(SERVE_LOG, encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except OSError:
        return ""


# ------------------------------------------------------- service managers
def unit_name(unit="serve"):
    """The service manager's name for a spark unit: launchd label or
    systemd unit (serve -> spark.serve / spark-serve.service)."""
    return "spark." + unit if IS_MAC else "spark-" + unit + ".service"


def service_domain(cfg, unit="serve"):
    """Where the service manager keeps a spark unit: "system" (a LaunchDaemon
    -- SITE_HEADLESS=yes on macOS, root's domain, runs as the user from boot),
    "gui" (a LaunchAgent under this login) or "user" (systemd --user)."""
    if not IS_MAC:
        return "user"
    rc, _ = run(["launchctl", "print", "system/" + unit_name(unit)])
    return "system" if rc == 0 else "gui"


def service_target(cfg, unit="serve"):
    """The launchctl service-target (system/spark.serve or gui/UID/spark.serve)
    or the systemd unit name, for a command line."""
    name = unit_name(unit)
    if not IS_MAC:
        return name
    dom = service_domain(cfg, unit)
    return ("system/" if dom == "system" else "gui/%d/" % os.getuid()) + name


def daemon_note(cfg, unit="serve", verb="kickstart -k"):
    """The one honest line when a unit is a LaunchDaemon: the user must sudo."""
    return "todo   %-12s the %s runs as a daemon (spark headless): sudo launchctl %s %s" % (
        unit, "FORGE" if unit == "forge" else "server", verb, service_target(cfg, unit))


def service_state(cfg, unit="serve"):
    """'loaded' | 'disabled' | 'absent' for an always-on unit here (serve
    by default; forge is the other). loaded = the service manager owns it
    (on macOS in gui/UID, or in system/ as a daemon when the box is headless);
    disabled = disabled on purpose; absent = on demand only. Always asks
    the manager: SPARK_SERVICE=none only stops bootstrap from enabling a
    unit, it does not make one that exists invisible."""
    name = unit_name(unit)
    if IS_MAC:
        if service_domain(cfg, unit) == "system":
            return "loaded"
        dom = "gui/%d" % os.getuid()
        rc, out = run(["launchctl", "print-disabled", dom])
        if '"%s" => disabled' % name in out or '"%s" => true' % name in out:
            return "disabled"
        rc, _ = run(["launchctl", "print", dom + "/" + name])
        return "loaded" if rc == 0 else "absent"
    rc, out = run(["systemctl", "--user", "is-enabled", name])
    st = out.strip()
    if st == "enabled":
        return "loaded"
    if st == "disabled":
        return "disabled"
    return "absent"


def forge_service_state(cfg):
    return service_state(cfg, "forge")


def service_stop(noreload, unit="serve"):
    """Stop the managed unit; with noreload also disable it. Returns the
    line that undoes the disable. A LaunchDaemon (system/) is root's: the
    caller checks service_domain first and tells the user the sudo line."""
    name = unit_name(unit)
    if IS_MAC:
        target = "gui/%d/%s" % (os.getuid(), name)
        undo = "launchctl enable %s && launchctl kickstart -k %s" % (target, target)
        if noreload:
            run(["launchctl", "disable", target], timeout=20)
        run(["launchctl", "bootout", target], timeout=20)
        return undo if noreload else "launchctl kickstart -k " + target
    short = name[:-8]
    undo = "systemctl --user enable --now " + short
    if noreload:
        run(["systemctl", "--user", "disable", name], timeout=20)
    run(["systemctl", "--user", "stop", name], timeout=30)
    return undo if noreload else "systemctl --user start " + short


def kickstart(cfg, unit="serve"):
    """(Re)start a loaded unit the way its manager does. A LaunchDaemon needs
    sudo, which no page or script can give: say so (a todo line) and return
    False instead of failing quietly."""
    if IS_MAC and service_domain(cfg, unit) == "system":
        from . import say
        say(daemon_note(cfg, unit))
        return False
    cmd = (["launchctl", "kickstart", "-k", service_target(cfg, unit)] if IS_MAC
           else ["systemctl", "--user", "start", unit_name(unit)])
    subprocess.run(cmd, capture_output=True)
    return True


# ------------------------------------------------------------------ speed
SPEED_CLASSES_GB = (1.5, 3, 6, 8)         # file-size classes: <=1.5 <=3 <=6 <=8 larger
SPEED_TABLE = {                           # generation tok/s per class, per backend
    "vulkan": (35, 16, 9, 6, 4),          # measured: a Debian box, AMD iGPU (1.7B 35, 4B 16, 8B 9)
    "cpu": (20, 10, 5, 3, 2),             # rounded guesses
    "metal": (80, 45, 25, 16, 10),        # rounded guesses: Apple silicon
}


def backend(cfg):
    """The engine build this machine gets, the twin of bootstrap.sh
    ai_build: metal on macOS (SITE_AI_BUILD is ignored there); on Linux
    cpu or vulkan as SITE_AI_BUILD says, and auto (the default) = vulkan
    when a DRM device reports VRAM in sysfs (gpu_info), else cpu."""
    if IS_MAC:
        return "metal"
    if cfg.ai_build in ("cpu", "vulkan"):
        return cfg.ai_build
    try:
        return "vulkan" if gpu_info() else "cpu"
    except OSError:
        return "cpu"


def speed_estimate(nbytes, backend, name=""):
    """Generation speed in tok/s, an int, from SPEED_TABLE by the file's
    size class and the backend. These are estimates -- one box measured
    under vulkan, the other two columns rounded guesses -- and stand only
    until `spark bench` (or a real turn) measures the model here; the
    table prints them with a `~`. A MoE whose name carries `-a3b` (3B
    active) is treated as the <=3 GB class for speed; its RAM row is
    unchanged."""
    gb = nbytes / 2**30
    if "-a3b" in name.lower():
        cls = 1
    else:
        cls = len(SPEED_CLASSES_GB)
        for i, limit in enumerate(SPEED_CLASSES_GB):
            if gb <= limit:
                cls = i
                break
    return SPEED_TABLE.get(backend, SPEED_TABLE["cpu"])[cls]


def speed_of(cfg, row):
    """(tok/s, kind) for one models.env row (name, file, url, bytes, sha,
    ram_gb): kind "measured" from the bench baseline of that file, else
    the best tg_tps of the last 30 days of turns that model answered from
    a server on this machine (a turn a peer or the FORGE elsewhere
    answered measures that box, not this one); else the estimate, kind
    "estimate". Never raises."""
    name, fname, nbytes = row[0], row[1], row[3]
    stem = model_stem(fname)
    try:
        from . import bench, forge_url, stats, wire
        base = bench.baseline_stem(stem)
        if base and base.get("tg"):
            return int(round(float(base["tg"]))), "measured"
        here = {u for u in (cfg.loopback_url(), wire.serve_url(), forge_url()) if u}
        best = 0.0
        for t in stats.turns(30):
            b = str(t.get("backend") or "").rstrip("/")
            local = not b or b in here or b.startswith(("http://127.", "http://localhost"))
            if local and t.get("model") == stem and isinstance(t.get("tg_tps"), (int, float)):
                best = max(best, float(t["tg_tps"]))
        if best > 0:
            return int(round(best)), "measured"
    except Exception:
        pass
    try:
        return speed_estimate(nbytes, backend(cfg), name), "estimate"
    except Exception:
        return speed_estimate(nbytes, "cpu", name), "estimate"
