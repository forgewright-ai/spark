# spark -- the package behind bin/spark. Python 3.9+, stdlib only.
#
# This module holds what every other module needs: the mark, the paths,
# say/die, the debug log, and the facts about this machine that the persona
# and the check both read. Nothing here talks to the network.

import os
import platform
import shutil
import subprocess
import sys
import time
import traceback

MARK = "spark"          # the sign every tool carries: plain, so every terminal can draw it
IS_MAC = sys.platform == "darwin"
OS = "macos" if IS_MAC else "linux"

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "spark")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "spark")
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "spark")
BIN_DIR = os.path.join(HOME, ".local", "bin")

SITE_ENV = os.path.join(CONFIG_DIR, "site.env")
SPARK_ENV = os.path.join(CONFIG_DIR, "spark.env")
SOUL_FILE = os.path.join(CONFIG_DIR, "soul")
MEMORY_FILE = os.path.join(CONFIG_DIR, "memory")
TOKEN_FILE = os.path.join(STATE_DIR, "api-token")
SERVE_URL_FILE = os.path.join(STATE_DIR, "serve-url")
PID_FILE = os.path.join(STATE_DIR, "serve.pid")
SERVE_LOG = os.path.join(STATE_DIR, "serve.log")
LOCK_FILE = os.path.join(STATE_DIR, "serve.lock")
FORGE_TOKEN_FILE = os.path.join(STATE_DIR, "forge-token")
EMBER_TOKEN_FILE = os.path.join(STATE_DIR, "ember-token")
FORGE_URL_FILE = os.path.join(STATE_DIR, "forge-url")
FORGE_PID = os.path.join(STATE_DIR, "forge.pid")
FORGE_LOG = os.path.join(STATE_DIR, "forge.log")
FORGE_LOCK = os.path.join(STATE_DIR, "forge.lock")
OFF_FLAG = os.path.join(STATE_DIR, "off")
WIDGETS_DIR = os.path.join(STATE_DIR, "widgets")
TURNS_DIR = os.path.join(STATE_DIR, "turns")
THREADS_DIR = os.path.join(STATE_DIR, "threads")
CHAT_HISTORY_FILE = os.path.join(STATE_DIR, "chat-history")
BRAIN_CACHE = os.path.join(STATE_DIR, "brain")
CHECK_JSON = os.path.join(STATE_DIR, "check.json")
BAR_CACHE = os.path.join(STATE_DIR, "bar")
CACHE_DIR = os.path.join(STATE_DIR, "cache")
DEBUG_LOG = os.path.join(STATE_DIR, "debug.log")
ENGINE_DIR = os.path.join(DATA_DIR, "engine")
MODELS_DIR = os.path.join(DATA_DIR, "models")

DEBUG = bool(os.environ.get("SPARK_DEBUG"))

# The Linux console font is an 8-bit bitmap: no ✓ or ↓ there (the box
# characters survive, being CP437). ASCII on the console -- also inside a
# tmux running on it, where TERM says tmux-256color but the client is the
# console -- or on request.
def _ascii_terminal():
    if os.environ.get("SPARK_ASCII") == "1":
        return True
    if os.environ.get("TERM") == "linux":
        return True
    if os.environ.get("TMUX"):
        try:
            out = subprocess.run(["tmux", "display", "-p", "#{client_termname}"], capture_output=True,
                                 text=True, timeout=2).stdout.strip()
            return out == "linux"
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


ASCII = _ascii_terminal()
# hammer (the answer mark) and warn are ASCII on every terminal and OS: one
# mark, both OSes. The check-report glyphs (ok/fail/na) and the bar's keep
# their Unicode faces with the console fallback.
_GLYPHS = {"hammer": ("*", "*"), "warn": ("!", "!"), "ok": ("✓", "+"), "fail": ("✗", "x"),
           "na": ("–", "-"), "sep": (" · ", " | "), "down": ("↓", "v"), "up": ("↑", "^"),
           "arrow": ("→", "->")}


def glyph(name):
    return _GLYPHS[name][1 if ASCII else 0]

# The repository this spark was linked from: bin/spark is a symlink into
# it, so its real path tells us. SPARK_REPO overrides (tests, fixtures).
REPO = os.environ.get("SPARK_REPO") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def say(s=""):
    print(s, flush=True)


def die(s, code=1):
    print("spark: " + s, file=sys.stderr, flush=True)
    sys.exit(code)


def page(text):
    """say(text), through a pager when stdout is a terminal and the text is
    taller than it: $PAGER, else `less -R -F -X` (-F: a short text prints
    and returns; -X: the screen survives). Piped output never sees a pager
    -- text-first means the pipe contract is untouched. A pager that is
    not installed (less is not guaranteed), fails to start, or quits early
    falls back to plain print; its exit code means nothing."""
    if not sys.stdout.isatty() or text.count("\n") + 1 <= shutil.get_terminal_size((80, 24)).lines:
        say(text)
        return
    import shlex
    cmd = shlex.split(os.environ.get("PAGER") or "") or ["less", "-R", "-F", "-X"]
    if shutil.which(cmd[0]) is None:
        say(text)
        return
    try:
        subprocess.run(cmd, input=text.encode())
    except (OSError, BrokenPipeError):
        say(text)


def paged(fn):
    """Run a printer through the pager: at a terminal, capture what fn
    prints and page it; anywhere else call fn unchanged, so piped output
    stays byte-identical. Returns fn's return value."""
    if not sys.stdout.isatty():
        return fn()
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    page(buf.getvalue().rstrip("\n"))
    return rc


def confirm(question):
    """The one confirm shape (grammar rule 5): `<question>? yes/NO: ` --
    only y or yes proceeds; Enter, anything else, or EOF is no."""
    try:
        return input("%s? yes/NO: " % question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def wait_ready(label, probe, timeout, interval=1.0):
    """The one dot-spinner (grammar rule 6): write `label`, then call
    probe() every `interval` seconds until it returns something truthy
    (returned, the line left open for the caller's ` ready` tail) or
    `timeout` seconds pass (the line is closed, None returned). An empty
    label waits silently on the same clock. A probe that raises gets the
    line closed first."""
    drawn = bool(label)
    if drawn:
        sys.stdout.write(label)
        sys.stdout.flush()
    end = time.time() + timeout
    while True:
        try:
            v = probe()
        except BaseException:
            if drawn:
                sys.stdout.write("\n")
                sys.stdout.flush()
            raise
        if v:
            return v
        if time.time() >= end:
            if drawn:
                sys.stdout.write("\n")
                sys.stdout.flush()
            return None
        time.sleep(interval)
        if drawn:
            sys.stdout.write(".")
            sys.stdout.flush()


def state_dir():
    """The 0700 state directory, created on first use."""
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass
    return STATE_DIR


def forge_url():
    """The URL the FORGE here bound (state/forge-url), or ''."""
    try:
        with open(FORGE_URL_FILE, encoding="utf-8") as f:
            return f.read().strip().rstrip("/")
    except OSError:
        return ""


def log_exc(context):
    """Append the active exception to the debug log. Never raises. Capped at
    1 MB with one rotated generation: a swallowed exception is the canonical
    silent failure, so it always leaves evidence."""
    try:
        state_dir()
        if os.path.exists(DEBUG_LOG) and os.path.getsize(DEBUG_LOG) > 1_000_000:
            os.replace(DEBUG_LOG, DEBUG_LOG + ".1")
        fd = os.open(DEBUG_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s %s\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), context, traceback.format_exc()))
    except Exception:
        pass


def debug(msg):
    if DEBUG:
        print("spark[debug]: " + msg, file=sys.stderr, flush=True)


def run(cmd, timeout=5, env=None, stdin=None):
    """(rc, stdout) of a command; never raises. rc is -1 on timeout or when
    the program does not exist."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env, input=stdin)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


# ------------------------------------------------------------ machine facts
def os_pretty():
    if IS_MAC:
        return "macOS " + platform.mac_ver()[0]
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux " + platform.release()


def package_manager():
    for pm in ("apt-get", "dnf", "pacman", "zypper", "apk", "brew"):
        if shutil.which(pm):
            return pm
    return ""


def mem_total_gb():
    """Memory a model can live in, in GiB: RAM plus the GPU's own memory on
    Linux (an iGPU's VRAM is RAM the BIOS carved out of MemTotal; a discrete
    card's VRAM holds the weights too). macOS: unified memory. 0 if unknown.
    SPARK_MEM_TOTAL_GB overrides it (tests, like SPARK_NO_APPLY)."""
    try:
        if os.environ.get("SPARK_MEM_TOTAL_GB"):
            return float(os.environ["SPARK_MEM_TOTAL_GB"])
        if IS_MAC:
            rc, out = run(["sysctl", "-n", "hw.memsize"])
            return int(out.strip()) / 2**30 if rc == 0 else 0
        total = 0
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) / 2**20
        from . import engine
        total += engine.gpu_info().get("vram_total", 0) / 2**30
        return total
    except (OSError, ValueError):
        pass
    return 0


def lan_ip():
    """The address the default route leaves by, without sending a packet:
    a UDP socket 'connected' to a public address is only routed, never
    used. Empty when there is no route."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("9.9.9.9", 53))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return ""


def own_hostnames():
    """Names this machine answers to: hostname, short hostname, and the
    mDNS name (macOS: scutil's LocalHostName). Never getfqdn, which can
    block on DNS."""
    import socket
    names = set()
    h = socket.gethostname()
    if h:
        names.add(h.lower())
        names.add(h.split(".")[0].lower())
        names.add(h.split(".")[0].lower() + ".local")
    if IS_MAC:
        rc, out = run(["scutil", "--get", "LocalHostName"])
        if rc == 0 and out.strip():
            names.add(out.strip().lower())
            names.add(out.strip().lower() + ".local")
    return names
