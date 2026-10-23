# spark.forgeserve -- the FORGE server: `spark forge`. One stdlib HTTP
# server on the LAN that fronts the llama-server here with the identity
# (soul, memory) added on the way in, so any client -- a laptop's spark, a
# script, a phone's browser -- talks to spark and never holds the
# api-token. /v1/chat/completions is OpenAI-compatible; /api/* is the
# monitor and the page's food; /, /login, /static/* are the page.
#
# Auth: the forge-token (state/forge-token, 0600) is admin -- the whole
# box, and the box account's own threads and memory. Every other caller
# is a named user (spark user add NAME): their personal token, verified
# against its sha256 and unwrapping their data key, scopes chat, threads
# and memory to their own sealed store -- the server holds the key in
# memory only. Bearer auth is stateless; a cookie login, the admin's
# too, is a session id minted at random and kept in memory, so a restart
# sends every browser back to the login (the key cannot come back from a
# cookie). The v1.3 shared ember-token is gone: the server no longer
# accepts it. No TLS: the trust model is your
# LAN -- see README "What leaves this machine".

import fcntl
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import select
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (CHECK_JSON, FORGE_LOCK, FORGE_LOG, FORGE_PID,
               FORGE_URL_FILE, HOME, IS_MAC, MARK, OFF_FLAG, REPO, SERVE_URL_FILE, SPARK_ENV,
               bind_check, config, confirm, forge_url, lan_ip, log_exc, own_hostnames, say, state_dir, wait_lan_ip,
               wait_ready)
from . import engine, mem_total_gb, qr, tls, vault, wire
from . import version as _version

# resolved once, at daemon import: `spark forge` is a long-running process,
# so paying one `git describe` (version()'s cache miss) here is fine.
VERSION = _version.version()

EX_CONFIG = engine.EX_CONFIG
COOKIE = "spark_forge"
COOKIE_AGE = 7776000            # 90 days: the cookie's life, and its session's
FAILS_PER_MIN = 10              # wrong logins from one address before 429
TOKEN_MIN = 32                  # a SPARK_FORGE_TOKEN from the environment shorter than this is refused
V1_MAX_TOKENS = 8192            # the most completion tokens a /v1 request may ask the model for
BODY_MAX = 1_000_000            # a request body larger than this is 413
DO_COMMAND_MAX = 4096           # /api/do/run: a longer line is 400 before any pattern reads it
                                # (a 100 kB line pinned a thread for seconds in is_dangerous);
                                # a block (several lines) has do.DO_BLOCK_MAX
LOG_MAX = 1_000_000             # forge.log rotates here, like serve.log
LOG_LINE_MAX = 512          # one log line at most: the request path is a peer's bytes
MAX_CONNECTIONS = 64            # connections handled at once; one more is a 503 and closed at once,
                                # so a flood of idle sockets cannot spawn a thread each without end
EVENTS_PER_USER = 4             # /api/events streams one requester holds open; one more is 429
GENERATION_WAITERS = 4          # a small wait budget, like the four live event streams
GENERATIONS_PER_USER = 2        # one active turn plus one waiting turn, across all clients
GENERATION_TIMEOUT = 30         # seconds to wait, like the HTTP socket timeout
SESSIONS_PER_NAME = 20          # logins kept per name (the admin's one name too); the oldest drops past it
NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}   # every API answer's headers
STATIC = {"index.html": "text/html; charset=utf-8", "spark.css": "text/css; charset=utf-8",
          "spark.js": "text/javascript; charset=utf-8",
          "manifest.webmanifest": "application/manifest+json; charset=utf-8",
          "favicon.svg": "image/svg+xml; charset=utf-8",
          "mark.svg": "image/svg+xml; charset=utf-8",
          # the look spark.forgewright.ai shares: the tokens, the theme script
          # before first paint, and the three fonts (SIL OFL 1.1, CREDITS.md)
          "tokens.css": "text/css; charset=utf-8", "theme.js": "text/javascript; charset=utf-8",
          "fonts/atkinson-hyperlegible-next-latin.woff2": "font/woff2",
          "fonts/atkinson-hyperlegible-next-latin-ext.woff2": "font/woff2",
          "fonts/monaspace-neon-400.woff2": "font/woff2", "fonts/monaspace-neon-700.woff2": "font/woff2",
          "fonts/monaspace-xenon-400.woff2": "font/woff2", "fonts/monaspace-xenon-700.woff2": "font/woff2"}
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forge")
UPSTREAM_TTL = 60               # a resolved upstream is trusted this long
UPSTREAM_MISS_TTL = 5           # a failed resolution is not retried sooner
MODELS_TTL = 5                  # /api/health's models field is re-read this often
EVENTS_POLL = 2
EVENTS_KEEPALIVE = 15
QUEUE_WAIT = 0.2                # a chat that waits longer than this for the model says `queued`
RUN_CAP = 1800                  # seconds a verb may run through /api/run
LEASH_GRACE = 0.5               # seconds a verb's pipe is still read once it ended or its cap killed it
RUN_ARG = re.compile(r"^[A-Za-z0-9._/:@+= -]{0,200}$")
# The verbs the page may run, and what their arguments must be (None: any
# that match RUN_ARG). The verb itself validates and applies; nothing else
# from the LAN writes config. `serve` is the bare view and the rotate
# button only: the page never switches the server (off, boot, share, the
# token on show).
RUN_VERBS = {"model": None, "ember": None, "bench": None, "on": None, "off": None,
             "serve": lambda a: a in ([], ["--login", "--new"], ["https", "own"]),
             "stop": None, "remember": None, "forget": None,
             "update": lambda a: a in ([], ["--dry-run"]),
             "tune": lambda a: a[:1] == ["apply"],
             "forge": lambda a: a == ["token", "--new"]}
# the verbs that end with the page's own restart: their stream stops
# with the server, and the page says so (update, serve https own)
RESTARTS = {"update": lambda a: True, "serve": lambda a: a[:1] == ["https"]}
# Every route the server answers, and who may: none (open -- /api/login
# still goes through the write gate, /v1/chat/completions takes a bearer
# only), user (a named user or the admin), admin (the forge-token). A `*`
# is one path segment. A request off this table is 404; a user on an
# admin row is 403 "role". CLAUDE.md contract 9 prints the table and
# tests/docs_test.py holds the two equal; tests/policy_test.py proves
# every row with three callers.
ROUTES = {
    ("GET", "/"): "none",
    ("GET", "/login"): "none",
    ("GET", "/static/*"): "none",
    ("GET", "/static/fonts/*"): "none",
    ("GET", "/manifest.webmanifest"): "none",
    ("GET", "/apple-touch-icon.png"): "none",
    ("GET", "/api/health"): "none",
    ("POST", "/api/login"): "none",
    ("GET", "/api/me"): "user",
    ("GET", "/api/check"): "user",
    ("GET", "/api/stats"): "user",
    ("GET", "/api/events"): "user",
    ("GET", "/api/soul"): "user",
    ("GET", "/api/memory"): "user",
    ("GET", "/api/models"): "user",
    ("GET", "/api/threads"): "user",
    ("GET", "/api/threads/*"): "user",
    ("GET", "/v1/models"): "user",
    ("POST", "/v1/chat/completions"): "user",
    ("POST", "/api/logout"): "user",
    ("POST", "/api/chat"): "user",
    ("POST", "/api/memory"): "user",
    ("POST", "/api/threads"): "user",
    ("POST", "/api/threads/*/append"): "user",
    ("POST", "/api/user/token"): "user",
    ("DELETE", "/api/threads"): "user",
    ("DELETE", "/api/memory/*"): "user",
    ("GET", "/api/serve"): "admin",
    ("GET", "/api/gpu"): "admin",
    ("GET", "/api/bench"): "admin",
    ("GET", "/api/config"): "admin",
    ("GET", "/api/users"): "admin",
    ("POST", "/api/users"): "admin",
    ("DELETE", "/api/users/*"): "admin",
    ("POST", "/api/run"): "admin",
    ("POST", "/api/do/propose"): "admin",
    ("POST", "/api/do/run"): "admin",
    ("POST", "/api/check/refresh"): "admin",
    ("POST", "/api/soul"): "admin",
}
METHOD = re.compile(r"^[A-Z]{1,16}$")       # a method the log may name as sent
# The admin rows that act on this machine: a verb run, the do console, the
# soul written, the check refreshed. Over plain http they answer this
# machine and a peer on one of its own networks alone (peer_is_local);
# a routed peer is 403 `boundary` before any body is read. Over TLS a
# valid session opens them from anywhere. Contract 9 names the seven and
# tests/policy_test.py holds it to this tuple: every admin POST and
# DELETE row, and acts() reads a `*` as route_role does.
ACTS = (("POST", "/api/run"), ("POST", "/api/do/propose"), ("POST", "/api/do/run"),
        ("POST", "/api/check/refresh"), ("POST", "/api/soul"), ("POST", "/api/users"),
        ("DELETE", "/api/users/*"))
# where a peer is local when this machine's own prefixes cannot be read
# (own_networks found no tool): one named line each, so it can be argued
# with. The IPv4 blocks are written as their first octets, never as a
# dotted address: the privacy gate reads a dotted private address as a
# machine's
PRIVATE = tuple(ipaddress.ip_network(n) for n in (
    (10 << 24, 8),                       # RFC 1918, the first block
    ((172 << 24) | (16 << 16), 12),      # RFC 1918, the second block
    ((192 << 24) | (168 << 16), 16),     # RFC 1918, the third block
    ((169 << 24) | (254 << 16), 16),     # IPv4 link-local
    "fc00::/7",                          # IPv6 unique local
    "fe80::/10",                         # IPv6 link-local
))
NETWORKS_TTL = 60               # own_networks is read again this often
V1_ROLES = ("spark", "ember")             # the roles /v1/chat/completions serves
SECRET_KEY = re.compile("KEY|TOKEN|SECRET")   # a config key /api/config never returns
ID_HINT = "a thread id is 1 to 64 letters, digits, - and _"   # forge.valid_id, said to a client


def _parse_networks(text):
    """The networks in `ip -o addr` (addr/prefix) or `ifconfig` (netmask
    0x.., prefixlen N) output, as ip_network objects; a line that does
    not parse is skipped."""
    nets = []
    for m in re.finditer(r"\binet6? ([0-9A-Fa-f.:]+)(?:%\w+)?(?:/(\d+)| netmask (0x[0-9A-Fa-f]+)| prefixlen (\d+))", text):
        addr, plen, mask, plen6 = m.groups()
        try:
            if mask:
                mask = str(ipaddress.IPv4Address(int(mask, 16)))
            nets.append(ipaddress.ip_network("%s/%s" % (addr, plen or plen6 or mask), strict=False))
        except ValueError:
            continue
    return nets


def own_networks():
    """The networks this machine sits on, one per interface address:
    `ip -o addr` on Linux, `ifconfig` elsewhere, parsed and never
    resolved. [] when neither answers; peer_is_local then falls back to
    PRIVATE."""
    for argv in (["ip", "-o", "addr"], ["ifconfig"]):
        try:
            nets = _parse_networks(subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout)
        except (OSError, subprocess.SubprocessError):
            continue
        if nets:
            return nets
    return []


def peer_is_local(ip, nets):
    """Whether a peer address is this machine's own or on one of `nets`
    (own_networks); with no networks known, whether it is in PRIVATE. A
    name is never looked up, and what does not parse is not local."""
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if a.is_loopback:
        return True
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return any(a in n for n in (nets or PRIVATE))


def _matches(pat, path):
    """Whether one path is one pattern's: a `*` stands for one path
    segment, and nothing else is special."""
    if pat == path:
        return True
    if "*" not in pat:
        return False
    ps, segs = pat.split("/"), path.split("/")
    return len(ps) == len(segs) and all(a == "*" or a == b for a, b in zip(ps, segs))


def route_role(method, path):
    """ROUTES' role for one request, or None: no such route. A `*` in a
    pattern stands for one path segment."""
    role = ROUTES.get((method, path))
    if role is not None:
        return role
    for (m, pat), role in ROUTES.items():
        if m == method and "*" in pat and _matches(pat, path):
            return role
    return None


def acts(method, path):
    """Whether one request is an acting row (ACTS), read as route_role
    reads the table."""
    return any(m == method and _matches(pat, path) for m, pat in ACTS)

USAGE = """%s forge -- run the page's server

  spark forge --foreground    run it here (--host ADDR, --port N)
  spark serve                 show what answers and the page
  spark serve on | off        start or stop the engine and the page
  spark serve --login         the page's address; at a terminal, the token
  spark serve --login --new   make a new admin token (logs every admin out)
  spark serve --audit [N]     the last N admin actions (default 50)
""" % MARK


# ------------------------------------------------------------------ token
def ensure_token(cfg):
    """Create the admin token if missing (O_EXCL, 0600); repair its mode.
    Returns the token. Never prints it."""
    return wire.ensure_token_file(cfg.forge_token_file)


def _read_token(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def same_token(a, b):
    """Constant-time equality over the UTF-8 bytes: hmac.compare_digest
    on str raises for non-ASCII, which made such a login a 500 that
    skipped the 1 s cost and the failure counter -- a non-ASCII token is
    simply a wrong one. A lone surrogate (the JSON escape \\ud800) has no UTF-8:
    a wrong token too, never a raise."""
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except UnicodeEncodeError:
        return False


def set_cookie(sid, secure=False):
    """The Set-Cookie value for a session id: HttpOnly, same-site, the
    whole page, 90 days; Secure when the page is served over TLS."""
    return "%s=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d%s" % (COOKIE, sid, COOKIE_AGE,
                                                                     "; Secure" if secure else "")


def http_origin(value):
    """A serialized HTTP(S) origin as (scheme, host, effective port).
    urlsplit alone accepts paths, credentials and stripped controls that
    are not valid Origin values. None means malformed, not absent."""
    if not value or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        return None
    if any(c in value for c in "\\@?#"):
        return None
    try:
        u = urllib.parse.urlsplit(value)
        if u.scheme not in ("http", "https") or not u.hostname or u.path or u.netloc.endswith(":"):
            return None
        port = u.port if u.port is not None else (443 if u.scheme == "https" else 80)
        if not 0 < port < 65536:
            return None
        return u.scheme, u.hostname.lower(), port
    except ValueError:
        return None


def cap_tokens(body):
    """The forwarded request asks the model for at most V1_MAX_TOKENS:
    max_tokens is set when absent, not a positive int (-1 is 'no limit'
    upstream) or larger; n_predict and max_completion_tokens, the other
    spellings llama-server reads, are capped the same when present."""
    for k in ("max_tokens", "n_predict", "max_completion_tokens"):
        if k == "max_tokens" or k in body:
            v = body.get(k)
            if isinstance(v, bool) or not isinstance(v, int) or not 0 < v <= V1_MAX_TOKENS:
                body[k] = V1_MAX_TOKENS
    return body


def _hash_current(name, h):
    """Whether hash h is still the named user's token verifier -- a
    rotation or removal kills every cached key and session for them."""
    from . import users
    v = users.verifier(name)
    return bool(v) and hmac.compare_digest(h, v)


# a burst of wrong logins must not hold a hundred threads in time.sleep:
# at most eight sleepers pay the second; the rest are refused just as
# fast (the counter and the 429 do the real gating)
_PUNISH = threading.BoundedSemaphore(8)


def punish_sleep():
    if _PUNISH.acquire(blocking=False):
        try:
            time.sleep(1)
        finally:
            _PUNISH.release()


# -------------------------------------------------------------------- log
_log_lock = threading.Lock()


def log(line):
    """One line into forge.log (0600, rotated at 1 MB). Never a token,
    never a body; printable and at most LOG_LINE_MAX characters, since the
    request path in it is a peer's own bytes and the log is tailed to a
    terminal (spark forge start)."""
    from . import text as textmod
    line = textmod.printable(line, keep="")[:LOG_LINE_MAX]
    with _log_lock:
        try:
            state_dir()
            try:
                if os.path.getsize(FORGE_LOG) > LOG_MAX:
                    os.replace(FORGE_LOG, FORGE_LOG + ".1")
            except OSError:
                pass
            fd = vault.open_private(FORGE_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
        except OSError:
            pass


def log_tail(n=40):
    try:
        with open(FORGE_LOG, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return []


# ------------------------------------------------------------- touch icon
# The banner's S (columns 0-7) as an ASCII grid -- # a full block, = | F T
# L J the box-drawing pieces -- with the fire gradient on the page's
# ground. Drawn once into a PNG with the same cell geometry as landing's
# banner-svg.py, so it is the favicon at 180x180, no binary in the repo.
ICON_GRID = ("#######T", "##F====J", "#######T", "L====##|", "#######|", "L======J")
ICON_INKS = ((255, 224, 102), (255, 224, 102), (224, 180, 0), (224, 180, 0), (210, 74, 42), (210, 74, 42))
ICON_BG = (16, 14, 12)
ICON_SIZE, ICON_MARGIN = 180, 20
_icon = {}


def _icon_rects():
    """[(x0, y0, x1, y1, rgb)] of the mark in the favicon's 108-unit
    square: 10x18 cells, a 3-unit stroke, the art 80 wide at x=14."""
    cw, ch, ln = 10.0, 18.0, 3.0
    mx, my = 0.5 - ln / cw / 2, 0.5 - ln / ch / 2
    pieces = {"#": [(0, 0, 1, 1)], "=": [(0, my, 1, ln / ch)], "|": [(mx, 0, ln / cw, 1)],
              "F": [(mx, my, 1 - mx, ln / ch), (mx, my, ln / cw, 1 - my)],
              "T": [(0, my, mx + ln / cw, ln / ch), (mx, my, ln / cw, 1 - my)],
              "L": [(mx, 0, ln / cw, my + ln / ch), (mx, my, 1 - mx, ln / ch)],
              "J": [(mx, 0, ln / cw, my + ln / ch), (0, my, mx + ln / cw, ln / ch)]}
    out = []
    for row, line in enumerate(ICON_GRID):
        for col, piece in enumerate(line):
            for fx, fy, fw, fh in pieces[piece]:
                x, y = 14 + (col + fx) * cw, (row + fy) * ch
                out.append((x, y, x + fw * cw + 0.4, y + fh * ch + 0.4, ICON_INKS[row]))
    return out


def touch_icon():
    """(png bytes, etag) of the 180x180 apple-touch-icon, kept in memory
    after the first request."""
    if "v" in _icon:
        return _icon["v"]
    rects = _icon_rects()
    scale = (ICON_SIZE - 2.0 * ICON_MARGIN) / 108.0
    raw = bytearray()
    for py in range(ICON_SIZE):
        v = (py + 0.5 - ICON_MARGIN) / scale
        here = [r for r in rects if r[1] <= v < r[3]]
        raw += b"\x00"                      # PNG filter: none
        for px in range(ICON_SIZE):
            u = (px + 0.5 - ICON_MARGIN) / scale
            raw += bytes(next((c for x0, _y0, x1, _y1, c in here if x0 <= u < x1), ICON_BG))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", ICON_SIZE, ICON_SIZE, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    _icon["v"] = png, '"%s"' % hashlib.sha256(png).hexdigest()[:16]
    return _icon["v"]


# --------------------------------------------------------------- upstream
class Upstream:
    """The llama-server this FORGE fronts: the one `spark serve` bound
    here, else loopback; a hard SPARK_BASE_URL alone. Never the FORGE's
    own URL, never another FORGE (no loops). Resolved lazily, so the
    FORGE starts before the model has loaded."""

    def __init__(self, cfg, own_url):
        self.cfg, self.own = cfg, own_url.rstrip("/")
        self.lock = threading.Lock()
        self.url, self.model, self.state, self.t = "", "", "down", 0.0

    def candidates(self):
        cfg = self.cfg
        if cfg.base_url:
            cands = [cfg.base_url]
        else:
            cands = [wire.serve_url(), cfg.loopback_url()]
        return [u for u in dict.fromkeys(cands) if u and u.rstrip("/") != self.own and u != forge_url()]

    def probe(self):
        """(url, model, state) now: state ok | loading | down."""
        loading = ""
        for u in self.candidates():
            fh = wire.forge_health(u, cfg=self.cfg)
            if fh == "down" or (fh and fh.get("forge")):
                continue                    # nothing there, or a FORGE: not for us
            st = wire.health(u)
            if st == "ok":
                try:
                    model = wire.model_stem(self.cfg, u)
                except wire.BrainError as e:
                    return u, "", e.kind
                return u, model, "ok"
            if st == "loading" and not loading:
                loading = u
        return loading, "", "loading" if loading else "down"

    def resolve(self, fresh=False):
        """(url, model, state), cached UPSTREAM_TTL when ok, a few seconds
        otherwise, so a burst of requests probes once."""
        with self.lock:
            age = time.time() - self.t
            if not fresh and (age < UPSTREAM_TTL if self.state == "ok" else age < UPSTREAM_MISS_TTL):
                return self.url, self.model, self.state
            self.url, self.model, self.state = self.probe()
            self.t = time.time()
            return self.url, self.model, self.state

    def brain(self, fresh=False):
        """wire.Brain(url, model, forge=False) of the upstream, for an
        in-process Session (the api-token goes on it), or BrainError."""
        url, model, st = self.resolve(fresh)
        if st == "ok":
            return wire.Brain(url, model, False)
        if st == "loading":
            raise wire.BrainError("loading", wire.LOADING)
        if st == "auth":
            raise wire.BrainError("auth", "the engine refused this machine's token")
        raise wire.BrainError("down", wire.no_brain_hint(self.cfg))

    def require(self):
        """The url to proxy to, or BrainError."""
        return self.brain().url


class GenerationQueue:
    """One active generation, a short FIFO, and account-wide admission.
    The condition protects admission and handoff, never inference or writes.
    A ticket owns its slot until its handler's finally releases it."""

    def __init__(self):
        self.changed = threading.Condition()
        self.waiting, self.active = [], None

    def reserve(self, owner):
        with self.changed:
            outstanding = self.waiting + ([self.active] if self.active else [])
            if (sum(t[1] == owner for t in outstanding) >= GENERATIONS_PER_USER
                    or len(self.waiting) >= GENERATION_WAITERS):
                return None
            ticket = (object(), owner, time.monotonic() + GENERATION_TIMEOUT)
            self.waiting.append(ticket)
            return ticket

    def wait(self, ticket, connected, queued=None):
        notice = time.monotonic() + QUEUE_WAIT
        while True:
            with self.changed:
                # Check even on the uncontended path and at the final handoff:
                # a disconnect or deadline must win over an available model.
                if not connected():
                    raise ConnectionAbortedError()
                left = ticket[2] - time.monotonic()
                if left <= 0:
                    raise TimeoutError()
                if self.active is None and self.waiting[0] is ticket:
                    self.waiting.pop(0)
                    self.active = ticket
                    return
                send_notice = queued is not None and time.monotonic() >= notice
                if not send_notice:
                    self.changed.wait(min(QUEUE_WAIT, left))
            if send_notice:
                queued()
                queued = None

    def release(self, ticket):
        with self.changed:
            if self.active is ticket:
                self.active = None
            elif ticket in self.waiting:
                self.waiting.remove(ticket)
            self.changed.notify_all()


# ----------------------------------------------------------------- server
class ForgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, cfg, url, served=None):
        ThreadingHTTPServer.__init__(self, addr, Handler)
        self._cfg, self._cfg_t, self.url = cfg, self._config_stamp(), url
        self.host, self.port = addr
        self.served = served                    # tls.Served: the listener is TLS; None: plain HTTP
        self.scheme = "https" if served else "http"
        self._tls_t = 0.0                       # the last "tls" log line (a scanner is a flood)
        self.upstream = Upstream(cfg, url)
        self.generations = GenerationQueue()   # one generation at a time: the model is one
        self.run_lock = threading.Lock()       # one verb at a time
        self._admin, self._admin_t = "", None
        self._user_keys = {}                    # sha256(token) -> (name, dk), unlocked once
        self.sessions = {}                      # session id -> (role, name, dk, token hash, expiry); memory only
        self._auth_lock = threading.Lock()
        self._models = (0.0, [])               # (epoch, [(alias, stem, loaded)])
        self._fails = {}                        # ip -> [epoch of wrong login]
        self._fails_lock = threading.Lock()
        self._conns = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._refused_t = 0.0                   # the last "too many connections" log line
        self._streams = {}                      # (role, user) -> /api/events streams open
        self._nets = (0.0, [])                  # (epoch, own_networks()): the boundary of the acting rows
        # the names the page answers to: its address, this machine's
        # names, the name in its links and every name its certificate
        # carries (a name the certificate names is a name the page is)
        names = {self.host, "127.0.0.1", "localhost", cfg.forge_name} | own_hostnames() | {lan_ip()}
        if served:
            names |= set(served.names())
        self.hosts = {n.lower() for n in names if n} | {"%s:%d" % (n.lower(), self.port) for n in names if n}

    def get_request(self):
        """accept(), and under TLS the socket wrapped with the pair served
        now (a renewed pair is picked up here). The handshake itself
        waits for the connection's thread: never on the accept loop."""
        sock, addr = self.socket.accept()
        if self.served:
            try:
                sock = self.served.context().wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
            except (ssl.SSLError, OSError) as e:
                sock.close()
                raise OSError("tls: %s" % e)
        return sock, addr

    def _handshake(self, request, client_address):
        """The TLS handshake, in the connection's own thread with a short
        clock. A client that speaks no TLS, or another one, is closed
        here and named in the log at most once in 10 s."""
        try:
            request.settimeout(10)
            request.do_handshake()
            request.settimeout(None)
            return True
        except (ssl.SSLError, OSError) as e:
            now = time.time()
            if now - self._tls_t > 10:
                self._tls_t = now
                log("%s tls: %s" % (client_address[0], getattr(e, "reason", None) or e))
            self.shutdown_request(request)
            return False

    def process_request(self, request, client_address):
        """A thread per connection, at most MAX_CONNECTIONS at once: one
        more is answered 503 here, on the accept loop, and closed -- no
        thread, no read of its request."""
        if not self._conns.acquire(blocking=False):
            body = b'{"error": {"kind": "busy", "hint": "too many connections; try again"}}'
            try:
                request.settimeout(1)
                # under TLS the 503 would need a handshake first: a refused
                # connection is closed unanswered instead
                if not self.served:
                    request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\n"
                                    b"Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"
                                    b"Retry-After: 5\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
            except OSError:
                pass
            now = time.time()
            if now - self._refused_t > 10:      # one line per 10 s of a flood, never one a socket
                self._refused_t = now
                log("%s refused: %d connections at once" % (client_address[0], MAX_CONNECTIONS))
            self.shutdown_request(request)
            return
        try:
            ThreadingHTTPServer.process_request(self, request, client_address)
        except Exception:
            self._conns.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            if self.served and not self._handshake(request, client_address):
                return
            ThreadingHTTPServer.process_request_thread(self, request, client_address)
        finally:
            self._conns.release()

    def handle_error(self, request, client_address):
        """A connection that dies before or between requests (a reset, a
        broken pipe, a TLS record cut, a client gone quiet) is no error
        worth a traceback: the stdlib would print one for each. Anything
        else lands in the debug log, once, with its trace."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, ssl.SSLError, TimeoutError, socket.timeout)):
            return
        log_exc("forge %s" % client_address[0])

    def stream_open(self, who):
        """True, counted, when `who` holds fewer than EVENTS_PER_USER
        /api/events streams; stream_close gives it back."""
        with self._auth_lock:
            n = self._streams.get(who, 0)
            if n >= EVENTS_PER_USER:
                return False
            self._streams[who] = n + 1
            return True

    def stream_close(self, who):
        with self._auth_lock:
            n = self._streams.get(who, 0) - 1
            if n > 0:
                self._streams[who] = n
            else:
                self._streams.pop(who, None)

    @staticmethod
    def _config_stamp():
        out = []
        for p in (config.SITE_ENV, config.SPARK_ENV):
            try:
                out.append(os.stat(p).st_mtime_ns)
            except OSError:
                out.append(-2)
        return tuple(out)

    @property
    def cfg(self):
        """The config, re-read when site.env or spark.env changes: `spark
        model NAME` (ember, budget alike) restarts spark-serve and
        not the forge, so a table answered from the config the forge
        started with marked the old pick until someone restarted it. A
        file that fails to parse keeps the last good config (the
        forge-token follows the same rule, admin_token below)."""
        stamp = self._config_stamp()
        if stamp != self._cfg_t:
            try:
                self._cfg = config.load()
            except SystemExit:
                pass
            self._cfg_t = stamp
        return self._cfg

    def admin_token(self):
        """The forge-token, re-read when its file changes: `spark forge
        token --new` takes effect without a restart, and every session
        opened with the old token dies with it."""
        p = self.cfg.forge_token_file
        try:
            mt = os.stat(p).st_mtime
        except OSError:
            mt = -2.0
        if mt != self._admin_t:
            self._admin = os.environ.get("SPARK_FORGE_TOKEN", "") or _read_token(p)
            self._admin_t = mt
        return self._admin

    def user_by_bearer(self, tok):
        """(name, dk) for a user's bearer, or None. The first sight of a
        token pays one KDF unwrap; after that it is a hash lookup, and a
        rotation invalidates the cache because the stored hash changed."""
        from . import users, vault
        try:
            h = vault.token_hash(tok)
        except UnicodeEncodeError:              # a lone surrogate is no token anyone holds
            return None
        with self._auth_lock:
            hit = self._user_keys.get(h)
        if hit:
            if _hash_current(hit[0], h):
                return hit
            with self._auth_lock:           # a rotated token's key leaves memory with it
                self._user_keys.pop(h, None)
        name = users.find_by_token(tok)
        if not name:
            return None
        try:
            dk = users.unlock(name, tok)
        except vault.SealError:
            return None
        with self._auth_lock:
            self._user_keys[h] = (name, dk)
        return (name, dk)

    def session_of(self, sid):
        """(role, name, dk) of a logged-in browser, or None. A session is
        a random id minted at login, admin and user alike, in memory
        only -- a restart sends every browser back to the login -- and
        it dies with its token: a rotation (spark serve --login --new,
        spark user token --new) or a removal ends it, and so does its
        expiry."""
        from . import vault
        with self._auth_lock:
            s = self.sessions.get(sid)
        if not s:
            return None
        role, name, dk, h, expiry = s
        if time.time() > expiry:
            self.drop_session(sid)
            return None
        if role == "admin":
            admin = self.admin_token()
            if not admin or not hmac.compare_digest(h, vault.token_hash(admin)):
                return None
        elif not _hash_current(name, h):
            return None
        return role, name, dk

    def new_session(self, role, token, name, dk):
        """Mint a session for a login: the id is random, never derived
        from the token, so no two logins share one and none can be
        computed from a captured token. Expired ones are swept here, and
        a name holds SESSIONS_PER_NAME at most: the oldest goes first."""
        from . import vault
        sid = secrets.token_urlsafe(32)
        now = time.time()
        with self._auth_lock:
            for k in [k for k, v in self.sessions.items() if v[4] < now]:
                del self.sessions[k]
            mine = sorted((v[4], k) for k, v in self.sessions.items() if (v[0], v[1]) == (role, name))
            for _exp, k in mine[:max(0, len(mine) - SESSIONS_PER_NAME + 1)]:
                del self.sessions[k]
            self.sessions[sid] = (role, name, dk, vault.token_hash(token), now + COOKIE_AGE)
        return sid

    def drop_session(self, sid):
        with self._auth_lock:
            self.sessions.pop(sid, None)

    def models_list(self, url):
        """[(alias, stem, loaded)] of the upstream, best-effort: [] when
        nothing answers, cached MODELS_TTL so /api/health stays cheap."""
        t, v = self._models
        if time.time() - t < MODELS_TTL:
            return v
        try:
            v = wire.models(self.cfg, url) if url else []
        except Exception:
            v = []
        self._models = (time.time(), v)
        return v

    def models_status(self, url):
        """{role: loaded|unloaded} for /api/health."""
        return dict((a, "loaded" if l else "unloaded") for a, _s, l in self.models_list(url))

    def serving(self, url, model, st):
        """{stem} the upstream holds loaded -- the router both roles, a
        single server its one model -- for the model table's serving
        column; set() when the upstream is not ok."""
        if st != "ok":
            return set()
        return set(stem for _a, stem, loaded in self.models_list(url) if loaded) or {model}

    def role_models(self, url):
        """{role: file stem} -- what the page's header and the chat's done
        event show; nothing about the pair is baked into the page."""
        return dict((a, st) for a, st, _l in self.models_list(url))

    def local_peer(self, ip):
        """peer_is_local over this machine's networks, read again every
        NETWORKS_TTL seconds: an address a lease moved is seen within a
        minute, and no request pays a subprocess."""
        t, nets = self._nets
        if time.time() - t > NETWORKS_TTL:
            nets = own_networks()
            self._nets = (time.time(), nets)
        return peer_is_local(ip, nets)

    def failed(self, ip):
        with self._fails_lock:
            now = time.time()
            xs = [t for t in self._fails.get(ip, []) if now - t < 60]
            xs.append(now)
            self._fails[ip] = xs

    def locked_out(self, ip):
        with self._fails_lock:
            now = time.time()
            return sum(1 for t in self._fails.get(ip, []) if now - t < 60) >= FAILS_PER_MIN


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"               # one connection per request: an SSE stream owns its own
    # a per-operation socket timeout: a body whose Content-Length never
    # arrives no longer parks a daemon thread forever. SSE stays alive
    # because the timeout is per op and keepalives write every 15 s.
    timeout = 30
    server_version = "spark-forge/" + VERSION
    sys_version = ""

    def log_message(self, *a):
        pass

    # ---- plumbing ----
    def _ip(self):
        return self.client_address[0]

    def _start(self, code, ctype, extra=None, length=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if self.server.scheme == "https" and self._named_host():
            # one week: enough to stick, short enough that `https off`
            # strands no name for a year (browsers ignore it on an address)
            self.send_header("Strict-Transport-Security", "max-age=%d" % tls.HSTS_SECONDS)
        self.end_headers()

    def _named_host(self):
        origin = http_origin("http://" + (self.headers.get("Host") or ""))
        if not origin:
            return False
        try:
            ipaddress.ip_address(origin[1])
            return False
        except ValueError:
            return True

    def _json(self, code, obj, extra=None):
        data = json.dumps(obj).encode()
        h = dict(NO_STORE)
        h.update(extra or {})
        self._start(code, "application/json", h, len(data))
        if self.command != "HEAD":
            self.wfile.write(data)
        self._status = code

    def _error(self, code, kind, hint, extra=None):
        self._json(code, {"error": {"kind": kind, "hint": hint}}, extra)

    def _body(self):
        """The JSON body, or None (and a 400/413/415 already sent). Only
        `Content-Type: application/json` is read: a form or text/plain
        body is what a foreign page can post without a preflight."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._error(415, "bad", "the body must be sent as Content-Type: application/json")
            return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > BODY_MAX:
            self._error(413 if n > BODY_MAX else 400, "bad", "a JSON body with Content-Length, at most %d bytes" % BODY_MAX)
            return None
        raw = self.rfile.read(n) if n else b""
        try:
            d = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError, RecursionError):   # 200k `[` nest past the parser's stack
            self._error(400, "bad", "the body is not JSON")
            return None
        if not isinstance(d, dict):
            self._error(400, "bad", "the body must be a JSON object")
            return None
        return d

    def _sse(self):
        self._start(200, "text/event-stream", NO_STORE)
        self._status = 200

    def _emit(self, event, obj):
        self.wfile.write(("event: %s\ndata: %s\n\n" % (event, json.dumps(obj))).encode())
        self.wfile.flush()

    def _cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v.strip()
        return ""

    def _auth(self):
        """(role, user name, data key) for this request's bearer or
        cookie -- or None when a 429 was sent. The forge-token is admin;
        a personal token names its user and unwraps their key; a cookie
        is a session id, looked up and nothing more. A wrong bearer
        costs a second and is counted, and a locked-out address is
        refused before its bearer is compared; an unknown cookie is only
        a 401 -- after a restart every browser holds one, and punishing
        that would lock the door on the way back to the login."""
        srv = self.server
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            if self._locked():
                return None
            given = auth[7:].strip()
            admin = srv.admin_token()
            if admin and same_token(given, admin):
                return "admin", "", None
            hit = srv.user_by_bearer(given)
            if hit:
                return "user", hit[0], hit[1]
            self._punish("bearer")
            return "", "", None
        c = self._cookie()
        if c:
            s = srv.session_of(c)
            if s:
                return s
            log("%s unknown cookie" % self._ip())
        return "", "", None

    def _punish(self, what):
        log("%s wrong %s" % (self._ip(), what))
        self.server.failed(self._ip())
        punish_sleep()

    def _locked(self):
        """True, a 429 sent, when this address has FAILS_PER_MIN wrong
        tokens in the last minute: a login and a bearer wait it out
        alike (a cookie is never a guess, so it is not gated)."""
        ip = self._ip()
        if not self.server.locked_out(ip):
            return False
        log("%s locked out" % ip)
        self._error(429, "locked", "too many wrong tokens from %s; wait a minute" % ip, {"Retry-After": "60"})
        return True

    def _host_ok(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1:
            return False
        host = hosts[0].lower()
        return http_origin("http://" + host) is not None and host in self.server.hosts

    def _post_ok(self):
        """The P rules: X-Spark and a same-origin request when Origin is
        sent. The route already checked Host. False = a response was sent."""
        if self.headers.get("X-Spark") != "1":
            self._error(403, "forbidden", "POST needs the header X-Spark: 1")
            return False
        origins = self.headers.get_all("Origin", [])
        if origins:
            # The scheme is the listener's own: https under TLS, http
            # otherwise. Forwarded and X-Forwarded-* are not evidence of
            # anything and never change this boundary.
            expected = http_origin("%s://%s" % (self.server.scheme, self.headers["Host"]))
            if len(origins) != 1 or http_origin(origins[0]) != expected:
                self._error(403, "forbidden", "Origin does not match this %s request" % self.server.scheme.upper())
                return False
        return True

    def _audit(self, action, **fields):
        """One sealed audit record of this admin action (numbers and
        names only); a trail that cannot take it is one log line, never
        a failed action."""
        from . import audit
        why = audit.record(action, self._ip(), **fields)
        if why:
            log("%s audit not kept -- %s" % (self._ip(), why))

    # ---- dispatch ----
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def __getattr__(self, name):
        """Every other method (HEAD, OPTIONS, PUT, PATCH...) is off ROUTES,
        so it is the same 404 an unknown route gets, never the stdlib's
        501. HEAD is no GET in disguise: it opens no stream and sends no
        body. The log names an odd method `?`."""
        if not name.startswith("do_"):
            raise AttributeError(name)
        method = name[3:] if METHOD.match(name[3:]) else "?"
        return lambda: self._dispatch(method)

    def _dispatch(self, method):
        t0 = time.time()
        self._status = 0
        self.role, self.user, self.dk = "", "", None
        parts = urllib.parse.urlsplit(self.path)
        path, self.query = parts.path, urllib.parse.parse_qs(parts.query)
        try:
            self._route(method, path)
        except (BrokenPipeError, ConnectionResetError):
            self._status = self._status or 499
        except Exception:                     # a crashed route is a 500, never a hung socket
            log_exc("forge %s %s" % (method, path))
            if not self._status:
                try:
                    self._error(500, "crash", "see state/debug.log")
                except OSError:
                    pass
        log("%s %s %s %d %d" % (self._ip(), method, path, self._status, int((time.time() - t0) * 1000)))

    def _route(self, method, path):
        srv = self.server
        role = route_role(method, path)       # the table decides who may; nothing else does
        if role is None:
            return self._error(404, "missing", "no such route" if path.startswith(("/api/", "/v1/")) else "no such page")
        if not self._host_ok():
            return self._error(400, "bad", "Host is not this machine")
        if role == "none":
            if path == "/api/health":
                return self.api_health()
            if path == "/api/login":          # no auth, but the write gate
                return self.api_login() if self._post_ok() else None
            if path in ("/", "/login"):
                return self.static("index.html")
            if path == "/manifest.webmanifest":
                return self.static("manifest.webmanifest")
            if path == "/apple-touch-icon.png":
                return self.apple_touch_icon()
            return self.static(path[8:])      # /static/*
        # bearer or cookie; whichever token matched decides role and user
        who = self._auth()
        if who is None:                       # a locked-out address: 429 sent
            return None
        self.role, self.user, self.dk = who
        if not self.role:
            return self._error(401, "auth", "log in with your token (spark user add NAME on %s)" % srv.cfg.name)
        if role == "admin" and self.role != "admin":
            return self._error(403, "role", "this needs the admin token")
        if acts(method, path) and srv.scheme != "https" and not srv.local_peer(self._ip()):
            # the boundary: over plain http an action answers this
            # machine's own networks alone, and the body is never read
            log("%s refused: %s %s over plain http from beyond this machine's networks" % (self._ip(), method, path))
            return self._error(403, "boundary", "over plain http an admin action answers this machine and its own "
                               "networks alone; from farther, spark serve https")
        if method == "GET":
            fn = {"/v1/models": self.v1_models, "/api/me": self.api_me, "/api/check": self.api_check,
                  "/api/stats": self.api_stats,
                  "/api/serve": self.api_serve, "/api/gpu": self.api_gpu,
                  "/api/bench": self.api_bench, "/api/config": self.api_config,
                  "/api/events": self.api_events, "/api/threads": self.api_threads,
                  "/api/soul": self.api_soul, "/api/memory": self.api_memory,
                  "/api/users": self.api_users, "/api/models": self.api_models}.get(path)
            if fn:
                return fn()
            if path.startswith("/api/threads/"):
                return self.api_thread(path[13:])
            return self._error(404, "missing", "no such route")
        if method == "POST" and path == "/v1/chat/completions":
            # the bearer only: a browser's cookie must not open the model
            # to a page on another origin (no X-Spark is asked for here)
            if not (self.headers.get("Authorization") or "").startswith("Bearer "):
                return self._error(401, "auth", "/v1/chat/completions takes a bearer token, not a cookie")
            body = self._body()
            if body is not None:
                return self.v1_chat(body)
            return None
        # P: the writes
        if not self._post_ok():
            return None
        if method == "DELETE":
            if path.startswith("/api/memory/"):
                return self.api_memory_delete(path[12:])
            if path == "/api/threads":
                return self.api_threads_clear()
            if path.startswith("/api/users/"):
                return self.api_users_remove(path[11:])
            return self._error(404, "missing", "no such route")
        if method == "POST" and path.startswith("/api/threads/") and path.endswith("/append"):
            body = self._body()
            if body is not None:
                return self.api_thread_append(path[13:-7], body)
            return None
        fn = {("POST", "/api/logout"): self.api_logout, ("POST", "/api/check/refresh"): self.api_check_refresh,
              ("POST", "/api/chat"): self.api_chat, ("POST", "/api/soul"): self.api_soul_write,
              ("POST", "/api/memory"): self.api_memory_add, ("POST", "/api/threads"): self.api_threads_create,
              ("POST", "/api/do/propose"): self.api_do_propose,
              ("POST", "/api/do/run"): self.api_do_run, ("POST", "/api/run"): self.api_run,
              ("POST", "/api/user/token"): self.api_user_token,
              ("POST", "/api/users"): self.api_users_add}.get((method, path))
        if not fn:
            return self._error(404, "missing", "no such route")
        body = self._body()
        if body is not None:
            return fn(body)
        return None

    # ---- no auth ----
    def api_health(self):
        cfg = self.server.cfg
        url, model, st = self.server.upstream.resolve()
        roles = self.server.role_models(url if st == "ok" else "")
        self._json(200, {"status": "ok", "forge": True, "name": cfg.name, "version": VERSION,
                         "model": model if st == "ok" else "", "upstream": st,
                         "models": self.server.models_status(url if st == "ok" else ""),
                         "roles": roles,
                         "names": dict((r, config.model_name(f)) for r, f in roles.items())})

    def api_login(self):
        """`{token}` in, a session out: the id is minted at random for
        this login, admin and user alike, and set as the cookie -- never
        derived from the token. The write gate ran before this (_route),
        so a page on another origin cannot log a browser in."""
        ip = self._ip()
        if self._locked():
            return None
        body = self._body()
        if body is None:
            return None
        admin = self.server.admin_token()
        given = body.get("token")
        role, uname, dk = "", "", None
        if isinstance(given, str) and given:
            if admin and same_token(given, admin):
                role = "admin"
            else:
                hit = self.server.user_by_bearer(given)
                if hit:
                    role, uname, dk = "user", hit[0], hit[1]
        if not role:
            log("%s login failed" % ip)
            self.server.failed(ip)
            punish_sleep()
            return self._error(401, "auth", "wrong token")
        sid = self.server.new_session(role, given, uname, dk)
        log("%s login ok %s%s" % (ip, role, " " + uname if uname else ""))
        return self._json(200, {"ok": True, "name": self.server.cfg.name, "role": role, "user": uname},
                          {"Set-Cookie": set_cookie(sid, self.server.scheme == "https")})

    def static(self, name):
        if name not in STATIC:
            return self._error(404, "missing", "no such file")
        path = os.path.join(STATIC_DIR, name)
        try:
            st = os.stat(path)
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._error(404, "missing", "the page is not installed here")
        etag = '"%x-%x"' % (st.st_mtime_ns, st.st_size)
        h = {"Content-Security-Policy": "default-src 'self'", "X-Frame-Options": "DENY",
             "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
             "ETag": etag, "Cache-Control": "no-cache"}
        if self.headers.get("If-None-Match") == etag:
            self._start(304, STATIC[name], h)
            self._status = 304
            return None
        self._start(200, STATIC[name], h, len(data))
        self.wfile.write(data)
        self._status = 200
        return None

    def apple_touch_icon(self):
        png, etag = touch_icon()
        h = {"ETag": etag, "Cache-Control": "no-cache"}
        if self.headers.get("If-None-Match") == etag:
            self._start(304, "image/png", h)
            self._status = 304
            return None
        self._start(200, "image/png", h, len(png))
        self.wfile.write(png)
        self._status = 200
        return None

    # ---- the OpenAI-compatible face ----
    def v1_models(self):
        """The models this page serves, in the shape the router lists and
        wire.models reads: one entry a served role, its id the file's
        stem, the role among its aliases, its status loaded or unloaded.
        Nothing of the upstream's own listing passes through: a path on
        this disk is no name, and a model the page does not serve is
        not listed."""
        url, _m, st = self.server.upstream.resolve()
        if st != "ok":
            return self._error(502, "down", "no model answers here now")
        roles, status = self.server.role_models(url), self.server.models_status(url)
        data = [{"id": wire._stem(roles[role]), "object": "model", "owned_by": "spark", "aliases": [role],
                 "status": {"value": status.get(role, "loaded")}}
                for role in V1_ROLES if roles.get(role)]
        return self._json(200, {"object": "list", "data": data})

    def _v1_role(self, model):
        """The role a /v1 request's `model` names, or None: spark or ember
        as such, or a role's file stem or list name as /api/health shows
        it (`roles`, `names`). The role goes upstream, so the router
        routes it. Anything else is refused before it leaves."""
        if model in V1_ROLES:
            return model
        if not isinstance(model, str):
            return None
        url, _m, st = self.server.upstream.resolve()
        roles = self.server.role_models(url if st == "ok" else "")
        for role in V1_ROLES:
            stem = roles.get(role)
            if stem and model in (stem, config.model_name(stem)):
                return role
        return None

    def v1_chat(self, body):
        """The api-token goes on and the answer comes back as it is: JSON,
        or the SSE bytes straight through. A missing model means ember;
        the identity (soul, memory) goes in only for an ember request --
        a spark request keeps the client's system message untouched, so
        the prompt line stays cheap on every machine. `"identity": false`
        asks for the chat model bare: a program with its own system
        prompt keeps it, without this machine's soul or the requester's
        facts in front. It is no boundary (a spark request is bare too),
        and the field never goes upstream."""
        from . import forge
        cfg = self.server.cfg
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not all(isinstance(m, dict) for m in msgs):
            return self._error(400, "bad", "messages must be a list of {role, content}")
        identity = body.pop("identity", True)
        if not isinstance(identity, bool):
            return self._error(400, "bad", "identity is true or false")
        model = self._v1_role(body.get("model") or "ember")
        if model is None:
            return self._error(400, "model", "model is spark or ember, or a name /api/health shows for one")
        body["model"] = model
        if model == "ember" and identity:
            mem = self._mstore()        # a user's own memory rides their request
            if msgs and msgs[0].get("role") == "system":
                prefix = msgs[0].get("content")
                prefix = prefix if isinstance(prefix, str) else ""
                msgs[0] = {"role": "system", "content": forge.identity(cfg, mem) + ("\n\n" + prefix if prefix else "")}
            else:
                msgs.insert(0, {"role": "system", "content": forge.system(cfg, "answer", "sh", mem)})
        body["messages"] = msgs
        cap_tokens(body)
        stream = bool(body.get("stream"))
        try:
            up = self.server.upstream.require()
        except wire.BrainError as e:
            return self._error(502, e.kind, e.hint)
        timeout = max(cfg.timeout, 60.0)
        ticket = self._generating()
        if ticket is None:
            return None
        try:
            try:
                r = wire._post(cfg, up, body, timeout, stream=stream)
            except wire.BrainError as e:
                if e.kind == "down":
                    self.server.upstream.resolve(fresh=True)
                return self._error(502, e.kind, e.hint)
            with r:
                if not stream:
                    data = r.read()
                    self._start(200, r.headers.get("Content-Type") or "application/json", NO_STORE, len(data))
                    self.wfile.write(data)
                    self._status = 200
                    return None
                self._start(200, "text/event-stream", NO_STORE)
                self._status = 200
                while True:
                    chunk = r.readline()
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        finally:
            self.server.generations.release(ticket)
        return None

    # ---- the monitor ----
    def api_me(self):
        """Who the presented token makes this client (class U): the page
        renders the admin or the user console from this, and greets the
        user by name."""
        from . import look
        d = {"role": self.role, "user": self.user,
             "name": self.server.cfg.name, "version": VERSION,
             "faces": look.faces(), "blink": look.blink()}
        if self.role == "admin":
            # the newest release tag the checkout knows (the check's git
            # row fetches): the page's header says it when it is newer
            d["newest"] = _version.newest()
        self._json(200, d)

    def api_check(self):
        """check.json plus its age: whole to the admin; to a named user the
        counts alone, as /api/events gives them -- the rows name the box
        account, the other users, the sends and the peer."""
        try:
            with open(CHECK_JSON, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError
        except (OSError, ValueError):
            d = {"ts": 0, "counts": {}, "rows": []}
        if self.role != "admin":
            d = {"ts": d.get("ts", 0), "counts": d.get("counts", {})}
        d["age"] = int(time.time() - d.get("ts", 0)) if d.get("ts") else None
        self._json(200, d)

    def api_check_refresh(self, body):
        from . import check
        check.refresh()
        self._json(202, {"ok": True})

    def api_stats(self):
        from . import bench, stats
        cfg = self.server.cfg
        try:
            days = int((self.query.get("days") or ["1"])[0])
        except ValueError:
            days = 0
        if days not in (1, 7, 3650):
            return self._error(400, "bad", "days must be 1, 7 or 3650")
        rows = stats.turns(days)
        d = stats.summarise(rows)
        d.update({"days": days, "baseline": bench.baseline(cfg) or None, "running": stats.running_settings(cfg),
                  "sends": [{"day": day, "dest": dest, "bytes": b, "turns": c} for day, dest, b, c in stats.sends(rows)]})
        return self._json(200, d)

    def api_serve(self):
        cfg = self.server.cfg
        url = wire.serve_url()
        health = wire.health(url) if url else "down"
        model = ""
        if health == "ok":
            try:
                model = config.model_name(wire.model_stem(cfg, url))
            except wire.BrainError:
                model = "?"
        self._json(200, {"url": url, "health": health, "model": model, "service": engine.service_state(cfg),
                         "pids": engine.server_pids(cfg.port), "mem_free_gb": round(engine.mem_available_gb(), 1)})

    def api_gpu(self):
        self._json(200, engine.gpu_info() or {})

    def api_bench(self):
        from . import bench
        cfg = self.server.cfg
        self._json(200, {"baseline": bench.baseline(cfg) or None, "tune": bench.load_tune(), "now": bench.settings_of(cfg)})

    def api_models(self):
        """The model table as this box sees it (user-or-admin): its RAM,
        its budget, the picks, the speeds -- what `spark model` on a
        client prints instead of its own numbers. No key, no token, no
        path: names, sizes and verdicts."""
        from . import model as modeltab
        cfg = self.server.cfg
        _url, model, st = self.server.upstream.resolve()
        total = mem_total_gb()
        self._json(200, {"name": cfg.name, "total_gb": total, "budget_gb": total * cfg.ai_budget / 100.0,
                         "budget_pct": cfg.ai_budget, "backend": engine.backend(cfg), "cap_note": engine.cap_note(cfg),
                         "models": modeltab.model_rows(cfg, self.server.serving(_url, model, st))})

    def api_config(self):
        from . import model as modeltab
        cfg = self.server.cfg
        _url, model, st = self.server.upstream.resolve()

        def clean(d):
            return {k: v for k, v in d.items() if not SECRET_KEY.search(k)}
        self._json(200, {"site": clean(cfg.site_file), "spark": clean(cfg.spark_file),
                         "effective": clean({k: cfg.get(k, "") for k in config.KEYS}),
                         "models": modeltab.model_rows(cfg, self.server.serving(_url, model, st)),
                         "off": os.path.exists(OFF_FLAG), "service": engine.service_state(cfg),
                         "forge": {"url": self.server.url, "service": engine.forge_service_state(cfg), "mode": cfg.forge},
                         "https": https_facts(cfg)})

    def api_events(self):
        """SSE until the client goes: check and serve on change, plus a
        comment every 15 s so proxies and phones keep the line open. One
        requester holds EVENTS_PER_USER streams at most: one more is 429
        busy."""
        who = (self.role, self.user)
        if not self.server.stream_open(who):
            return self._error(429, "busy", "%d live streams already open for you; close a tab" % EVENTS_PER_USER)
        try:
            return self._events()
        finally:
            self.server.stream_close(who)

    def _events(self):
        self._sse()
        watched = (CHECK_JSON, SERVE_URL_FILE)

        def stamps():
            out = []
            for p in watched:
                try:
                    out.append(os.stat(p).st_mtime_ns)
                except OSError:
                    out.append(0)
            return out

        emit = self._emit

        def snapshot(i):
            if i == 0:
                try:
                    with open(CHECK_JSON, encoding="utf-8") as f:
                        d = json.load(f)
                    emit("check", {"counts": d.get("counts", {}), "ts": d.get("ts", 0)})
                except (OSError, ValueError):
                    emit("check", {"counts": {}, "ts": 0})
            else:
                url = wire.serve_url()
                emit("serve", {"url": url, "health": wire.health(url) if url else "down"})

        last = stamps()
        for i in range(2):
            snapshot(i)
        alive = time.time()
        while True:
            time.sleep(EVENTS_POLL)
            now = stamps()
            for i, (a, b) in enumerate(zip(last, now)):
                if a != b:
                    snapshot(i)
            last = now
            if time.time() - alive >= EVENTS_KEEPALIVE:
                self.wfile.write(b":keepalive\n\n")
                self.wfile.flush()
                alive = time.time()

    # ---- P ----
    def api_logout(self, body):
        # expiring the cookie is the browser's half; the server's half is
        # the session entry, which stayed valid for anyone replaying the
        # cookie until now
        c = self._cookie()
        if c:
            self.server.drop_session(c)
        self._json(200, {"ok": True}, {"Set-Cookie": "%s=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0" % COOKIE})

    # ---- threads and chat ----
    def _ustore(self):
        """The requester's sealed thread store: a user's own; the admin
        works the box account's (the owner's) -- never anyone else's,
        there is no key for those."""
        from . import forge
        if self.role == "user":
            return forge.store_for(self.user, self.dk)
        return forge.local_store(provision=True)

    def _mstore(self):
        """The requester's memory store for the memory routes, or None:
        the module default (the box account) serves the admin."""
        from . import memory
        if self.role == "user":
            return memory.store_of(self.user, self.dk)
        return None

    def api_threads(self):
        try:
            n = max(1, min(1000, int((self.query.get("n") or ["30"])[0])))
        except ValueError:
            n = 30
        self._json(200, {"threads": self._ustore().list_threads(n)})

    def api_thread(self, tid):
        from . import forge
        st = self._ustore()
        if not forge.valid_id(tid):
            return self._error(400, "bad", ID_HINT)
        if not st.exists(tid):
            return self._error(404, "missing", "no thread %s" % tid)
        # a chat's /read keeps its file's text on the record for the model
        # (`source`, forge._fit); the page shows the words alone, so
        # the file's text never travels to the browser
        msgs = [{k: v for k, v in m.items() if k != "source"} for m in st.load(tid)]
        return self._json(200, {"id": tid, "messages": msgs})

    def api_threads_create(self, body):
        """POST /api/threads: a KEPT thread in the requester's OWN store,
        made with no model turn -- a program keeping what it must not
        lose. {"id"?}: none mints a timestamp id (201); a new id is made
        (201); an id already kept answers as it is (200); a regular
        thread of that id is moved to kept, a rename, every record still
        opening (200). 409 full past forge.KEEP_MAX, 409 both when the id
        is in both directories. SPARK_HISTORY does not reach it."""
        from . import forge
        tid = body.get("id")
        if tid is not None and not forge.valid_id(tid):
            return self._error(400, "bad", ID_HINT)
        try:
            tid, created = self._ustore().keep(tid)
        except forge.KeepError as e:
            return self._error(409 if e.kind in ("full", "both") else 500, e.kind, e.hint)
        log("%s thread keep %s" % (self._ip(), tid))
        return self._json(201 if created else 200, {"id": tid, "kept": True})

    def api_thread_append(self, tid, body):
        """POST /api/threads/<id>/append: one message onto the requester's
        OWN thread -- how a client's `??` lands its turn here, so the
        box's prompt, the client's prompt and the page share one thread,
        and how a program writes its kept thread. role user|assistant,
        text a non-empty string (cut at the history cap, and the answer
        says so); mode and kind ride as short fields, nothing else does.
        The answer tells the truth: 200 {ok, chars, cut} when stored, 409
        off when history is off and the thread is not kept, 500 store
        when the store failed."""
        from . import forge
        st = self._ustore()
        if not forge.valid_id(tid) or not st.exists(tid):
            return self._error(404, "missing", "no thread %s" % tid)
        role, text = body.get("role"), body.get("text")
        if role not in ("user", "assistant") or not isinstance(text, str) or not text.strip():
            return self._error(400, "bad", "role is user|assistant and text a non-empty string")
        fields = {}
        for k in ("mode", "kind"):
            v = body.get(k)
            if isinstance(v, str) and 0 < len(v) <= 40:
                fields[k] = v
        cfg = self.server.cfg
        if cfg.history <= 0 and not st.is_kept(tid):
            return self._error(409, "off", "history is off and thread %s is not kept -- "
                                           "POST /api/threads with its id keeps it" % tid)
        stored = text[:forge.HISTORY_MAX_CHARS]
        if not st.append(cfg, tid, role, stored, **fields):
            return self._error(500, "store", "thread %s did not take the message -- see state/debug.log" % tid)
        log("%s thread append %s" % (self._ip(), tid))
        return self._json(200, {"ok": True, "chars": len(stored), "cut": len(stored) < len(text)})

    def api_threads_clear(self):
        """DELETE /api/threads: clear the requester's own regular threads;
        the answer says how many kept threads stay."""
        st = self._ustore()
        n = st.clear()
        k = st.kept_count()
        log("%s threads clear %d, %d kept" % (self._ip(), n, k))
        return self._json(200, {"cleared": n, "kept": k})

    def api_users(self):
        """The named users, counts and stamps only -- never a title, a
        body, or a token. The whole of admin visibility into user data."""
        from . import users
        out = []
        mine = users.account()[0]
        for n in users.list_users():
            count, newest, kept = users._thread_stats(n)
            out.append({"name": n, "threads": count, "kept": kept,
                        "last": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest)) if newest else "",
                        "account": n == mine})
        self._json(200, {"users": out})

    def api_users_add(self, body):
        """POST /api/users {name}: mint a user from the page, as `spark user
        add NAME` does at the terminal. The token comes back once, with
        its login link and the link's QR as a matrix the page draws, and
        is never stored: the terminal's custody rule, on the admin's own
        screen. A name the verb refuses is 400, a name in use 409."""
        from . import users
        name = body.get("name")
        if not isinstance(name, str) or not users.valid_name(name):
            return self._error(400, "bad", "a name is a-z, 0-9 and -, starting with a letter, at most 32 characters")
        if users.exists(name):
            return self._error(409, "exists", "%s already exists" % name)
        token = users.add(name)
        link = page_url(self.server.cfg) + "#t=" + token
        matrix = qr.encode(link) if "<" not in link else None
        log("%s user add %s" % (self._ip(), name))
        self._audit("user add", name=name)
        return self._json(200, {"name": name, "token": token, "link": link, "qr": matrix or []})

    def api_users_remove(self, name):
        """DELETE /api/users/NAME: the user's store, every kept thread
        with it, gone, as `spark user remove NAME` does at the terminal;
        their sessions and cached keys die with the verifier. The box
        account is the admin's own store and is removed at the terminal
        alone (409 self). A name the verb refuses is 400, an unknown one
        404."""
        from . import users
        if not users.valid_name(name):
            return self._error(400, "bad", "a name is a-z, 0-9 and -, starting with a letter, at most 32 characters")
        if not users.exists(name):
            return self._error(404, "missing", "no user named %s" % name)
        if users.account()[0] == name:
            return self._error(409, "self", "the box account is removed at the terminal: spark user remove %s" % name)
        users.remove(name)
        log("%s user remove %s" % (self._ip(), name))
        self._audit("user remove", name=name)
        return self._json(200, {"name": name, "removed": True})

    def api_user_token(self, body):
        """POST /api/user/token: rotate the requesting user's own token.
        The session already holds their key; the new token is returned
        once, with its login link and the link's QR as the add-user
        answer carries them (a lost phone), and never stored."""
        from . import users
        if self.role != "user":
            return self._error(403, "role", "the admin rotates with spark serve --login --new")
        new = users.rewrap(self.user, self.dk)
        sid = self.server.new_session("user", new, self.user, self.dk)
        link = page_url(self.server.cfg) + "#t=" + new
        matrix = qr.encode(link) if "<" not in link else None
        log("%s user token rotated %s" % (self._ip(), self.user))
        self._audit("user token", name=self.user)
        return self._json(200, {"token": new, "link": link, "qr": matrix or []},
                          {"Set-Cookie": set_cookie(sid, self.server.scheme == "https")})

    def _thread_of(self, body):
        """The thread a body names, checked against the requester's own
        store: (id or None, ok). A response was sent when not ok."""
        from . import forge
        tid = body.get("thread")
        if tid is None or tid == "":
            return None, True
        if not forge.valid_id(tid):
            self._error(400, "bad", ID_HINT)
            return None, False
        if not self._ustore().exists(tid):
            self._error(404, "missing", "no thread %s" % tid)
            return None, False
        return tid, True

    def _text_cwd(self, body):
        """(text, cwd) of a chat or do body, or (None, None) with a 400 sent."""
        text, cwd = body.get("text"), body.get("cwd") or ""
        if not isinstance(text, str) or not text.strip():
            self._error(400, "bad", "text is empty")
            return None, None
        if not isinstance(cwd, str):
            self._error(400, "bad", "cwd must be a string")
            return None, None
        return text.strip(), cwd

    def _connected(self):
        """HTTP/1.0 has no next request here; peek without consuming bytes."""
        try:
            ready, _w, _x = select.select([self.connection], [], [], 0)
            return not ready or bool(self.connection.recv(1, socket.MSG_PEEK))
        except OSError:
            return False

    def _generating(self, sse=False):
        queue = self.server.generations
        ticket = queue.reserve((self.role, self.user))
        if ticket is None:
            self._error(429, "busy", "too many generation requests; try again", {"Retry-After": "1"})
            return None
        acquired = False
        try:
            if sse:
                self._sse()
            queue.wait(ticket, self._connected,
                       (lambda: self._emit("queued", {})) if sse else None)
            acquired = True
            return ticket
        except ConnectionAbortedError:
            self._status = 499
        except TimeoutError:
            hint = "waited too long for the model; try again"
            if sse:
                self._emit("error", {"kind": "timeout", "hint": hint, "retry_after": 1})
            else:
                self._error(504, "timeout", hint, {"Retry-After": "1"})
        finally:
            if not acquired:
                queue.release(ticket)
        return None

    def api_chat(self, body):
        """One turn of the FORGE in this process, streamed as SSE. The
        Session talks to the upstream llama-server (Upstream.brain), never
        back to this FORGE."""
        from . import forge, session
        cfg = self.server.cfg
        text, cwd = self._text_cwd(body)
        if text is None:
            return None
        mode = body.get("mode") or "chat"
        if mode == "talk":      # the old names, accepted for one version
            mode = "chat"       # records write mode "chat" from now on
        if mode == "ask":       # spark answering is "answer" now: `spark
            mode = "answer"     # ask` is where spark does the asking
        if mode not in ("chat", "answer"):
            return self._error(400, "bad", "mode is chat or answer")
        thread, ok = self._thread_of(body)
        if not ok:
            return None
        ticket = self._generating(sse=True)
        if ticket is None:
            return None
        try:
            try:
                thread, _answer, ms = forge.reply(cfg, thread, text, cwd=cwd, shell=_shell(), mode=mode,
                                                  on_delta=lambda d: self._emit("delta", {"t": d}), brain=self.server.upstream.brain,
                                                  store=self._ustore(), mem=self._mstore())
            except wire.BrainError as e:
                if e.kind == "down":
                    self.server.upstream.resolve(fresh=True)
                err = {"kind": e.kind, "hint": e.hint}
                # a cut landed the partial and forge.reply put the thread
                # id on the exception: without it the page opened a NEW
                # thread for the retry and the partial was stranded
                if getattr(e, "thread", None):
                    err["thread"] = e.thread
                return self._emit("error", err)
            except forge.RefError as e:
                return self._emit("error", {"kind": "ref", "hint": e.hint})
        finally:
            self.server.generations.release(ticket)
        rm = self.server.role_models(self.server.upstream.resolve()[0])
        used = rm.get("ember") or (sorted(rm.values())[0] if rm else "")
        self._emit("done", {"thread": thread, "ms": ms, "model": config.model_name(used)})
        session.prune(cfg)
        # every store the server holds a key for is pruned, not only the
        # box account's: named users' threads aged the same way, and
        # header-only leftovers go regardless (their header is plaintext)
        keys = {}
        with self.server._auth_lock:
            for _h, (n, dk) in self.server._user_keys.items():
                keys[n] = dk
            for _c, (role, n, dk, _th, _exp) in self.server.sessions.items():
                if role == "user":
                    keys[n] = dk
        forge.prune_stores(cfg, keys)
        return None

    # ---- soul and memory ----
    def api_soul(self):
        from . import soul
        cfg = self.server.cfg
        text, source = soul.read(cfg)
        self._json(200, {"text": text, "source": source})

    def api_soul_write(self, body):
        from . import check, soul
        text, core = body.get("text"), body.get("core", False)
        if not isinstance(text, str) or not isinstance(core, bool):
            return self._error(400, "bad", "text must be a string, core true or false")
        # what `spark soul edit` would write: the personality paragraph
        # after an unchanged core once awaken gave one, else the soul file;
        # a changed core only with core: true (spark soul edit --core)
        part = soul.write_edit(self.server.cfg, text, core=core)
        if part is None:
            return self._error(409, "core", "the text changes the core -- send core: true to replace it")
        n = len(text.strip())
        self._audit("soul", part=part, chars=min(n, soul.SOUL_MAX))
        check.refresh()
        return self._json(200, {"chars": min(n, soul.SOUL_MAX), "cut": n > soul.SOUL_MAX, "part": part})

    def api_memory(self):
        from . import memory
        self._json(200, {"facts": [{"n": i, "text": f} for i, f in enumerate(memory._all_facts(self._mstore()), 1)],
                         "on": self.server.cfg.memory})

    def api_memory_add(self, body):
        from . import memory
        text = body.get("text")
        if not isinstance(text, str):
            return self._error(400, "bad", "text must be a string")
        try:
            fact = memory.remember(text, self._mstore())
        except memory.Refused as e:
            return self._error(409 if e.reason in ("duplicate", "full") else 400, e.reason, e.hint)
        return self._json(200, {"n": len(memory._all_facts(self._mstore())), "text": fact})

    def api_memory_delete(self, rest):
        from . import memory
        if not rest.isdigit():
            return self._error(400, "bad", "DELETE /api/memory/N, N as spark memory lists it")
        try:
            fact = memory.forget_n(int(rest), self._mstore())
        except memory.Refused as e:          # a store that does not open is never written over
            return self._error(400, e.reason, e.hint)
        if fact is None:
            return self._error(404, "missing", "no fact %s" % rest)
        return self._json(200, {"text": fact})

    # ---- do ----
    def _do_cwd(self, cwd):
        """Where a do step runs: `cwd` as sent (HOME when empty), or None
        with a 400 sent -- one line of printable text, an absolute path,
        a directory."""
        from . import do
        if not cwd:
            return HOME
        if do.CONTROL.search(cwd):
            self._error(400, "bad", "cwd is one line of printable text")
            return None
        if not os.path.isabs(cwd) or not os.path.isdir(cwd):
            self._error(400, "bad", "cwd must be the absolute path of a directory")
            return None
        return cwd

    def api_do_propose(self, body):
        """One step proposed, nothing run; the thread continues or starts.
        A new thread's text is the goal: do.DO_GOAL_MAX at most. On a
        continued thread the text is a step's output (the page's `Output
        of` feedback): held as do.hold holds a step's tail -- the command
        read from its first line -- before the model sees it. Every
        proposal is a turn record (mode do), with the server's timings."""
        from . import do, forge
        cfg = self.server.cfg
        text, cwd = self._text_cwd(body)
        if text is None:
            return None
        cwd = self._do_cwd(cwd)
        if cwd is None:
            return None
        thread, ok = self._thread_of(body)
        if not ok:
            return None
        held = 0
        if thread is None:
            size = len(text.encode("utf-8", "replace"))
            if size > do.DO_GOAL_MAX:
                return self._error(400, "bad", do.GOAL_TOO_LONG % (do.DO_GOAL_MAX >> 10, (size + 1023) >> 10))
        else:
            m = do.FEEDBACK_HEAD.match(text)
            text, held, _names = do.hold(text, m.group(1) if m else "")
        ticket = self._generating()
        if ticket is None:
            return None
        try:
            if thread is None:
                thread = forge.new_thread(cfg)
            try:
                reply, ms, s = do.propose(cfg, thread, text, _shell(), cwd, brain=self.server.upstream.brain)
            except wire.BrainError as e:
                if e.kind == "down":
                    self.server.upstream.resolve(fresh=True)
                return self._error(502, e.kind, e.hint)
        finally:
            self.server.generations.release(ticket)
        s.record(kind="danger" if reply["danger"] else reply["kind"], thread=thread, ms=ms,
                 **({"held": held} if held else {}))
        rm = self.server.role_models(self.server.upstream.resolve()[0])
        driver = rm.get("ember") or (sorted(rm.values())[0] if rm else "")
        return self._json(200, {"thread": thread, "reply": reply, "ms": ms,
                                "driver": driver,
                                "unchecked": do.conclusion_check(thread, reply)})

    def api_do_run(self, body):
        """One step the user clicked, run as typed. The page asked twice
        for a dangerous one; the server holds it to that: a command
        do.danger flags runs only with confirmed: true. do.refused says
        what is refused before any pattern reads it: a control character
        (do.CONTROL in a line; in a block of several lines, do.BLOCK_CONTROL:
        a line feed separates them, nothing else passes) and a line over
        DO_COMMAND_MAX characters or a block over do.DO_BLOCK_MAX; and so
        is a cwd that is not an absolute directory. Nobody
        watches it at a terminal: do.STEP_TIMEOUT is its leash (rc 124,
        the whole process group killed). The log carries a sha256 prefix
        and the length, never the text (the sealed audit keeps the digest
        and the rc), then the rc. `man` rides the answer when
        the step was refused for an option (do.man_excerpt): the lines of
        its own man page, which the page's next proposal carries."""
        from . import do
        command, cwd = body.get("command"), body.get("cwd") or ""
        if not isinstance(command, str) or not command.strip():
            return self._error(400, "bad", "command is empty")
        if len(command) > do.DO_BLOCK_MAX:
            return self._error(400, "bad", "a %s is at most %d characters" % (
                ("block", do.DO_BLOCK_MAX) if "\n" in command.strip() else ("command", DO_COMMAND_MAX)))
        if do.BLOCK_CONTROL.search(command):
            return self._error(400, "bad", "a command is printable text: a line, or lines a line feed separates")
        # as a step runs: one line plus a trailing newline is a line (its
        # 4096 cap), never a block of one
        command = do.step_text(command)
        if "\n" not in command and len(command) > DO_COMMAND_MAX:
            return self._error(400, "bad", "a command is at most %d characters" % DO_COMMAND_MAX)
        why = do.refused(command)
        if why == "control":
            return self._error(400, "bad", "a command is printable text: a line, or lines a line feed separates")
        if why:
            return self._error(400, "bad", why)
        if not isinstance(cwd, str):
            return self._error(400, "bad", "cwd must be a string")
        cwd = self._do_cwd(cwd)
        if cwd is None:
            return None
        if do.danger(command, cwd) and body.get("confirmed") is not True:
            return self._error(400, "confirm", "a dangerous command runs only with confirmed: true")
        digest = hashlib.sha256(command.encode("utf-8")).hexdigest()[:12]
        log("%s do/run %s %d chars" % (self._ip(), digest, len(command)))
        rc, tail = do.run(command, _shell(), cwd, echo=False, timeout=do.STEP_TIMEOUT)
        log("%s do/run %s rc %d" % (self._ip(), digest, rc))
        self._audit("do/run", digest=digest, rc=rc)
        man = do.man_excerpt(command, rc, tail)      # the page appends it, as the prompt's feedback does
        return self._json(200, dict({"rc": rc, "tail": tail}, **({"man": man} if man else {})))

    # ---- the verb runner ----
    def api_run(self, body):
        """`spark VERB ARGS` from the page, its output streamed line by
        line. Only the allowlisted verbs; the verb validates and applies."""
        verb, args = body.get("verb"), body.get("args", [])
        if not isinstance(verb, str) or verb not in RUN_VERBS:
            return self._error(400, "bad", "not a verb the page may run: %s" % ", ".join(sorted(RUN_VERBS)))
        rule = RUN_VERBS[verb]
        if not isinstance(args, list) or not all(isinstance(a, str) and RUN_ARG.match(a) for a in args):
            return self._error(400, "bad", "args must be a list of plain words (letters, digits, ._/:@+=- and space)")
        if rule and not rule(args):
            return self._error(400, "bad", "spark %s takes no such arguments from the page" % verb)
        log("%s run %s" % (self._ip(), verb))
        env = dict(os.environ, TERM="dumb", SPARK_ASCII="1")
        env.pop("TMUX", None)
        self._sse()
        argv = [sys.executable, os.path.join(REPO, "bin", "spark"), verb] + args
        restarts = RESTARTS.get(verb, lambda a: False)(args)
        if restarts:
            # the verb ends with the page's own restart, which stops this
            # server before a record after it could be written: the record
            # goes first, without an rc (the next start is its outcome)
            self._audit("run", verb=verb)
        with self.server.run_lock:
            rc = run_verb(argv, env, lambda s: self._emit("line", {"s": s}))
        if not restarts:
            self._audit("run", verb=verb, rc=rc)
        return self._emit("done", {"rc": rc})



def _killpg(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass


def _exited(p):
    """True once p has exited, without reaping it: its pid, and so the
    id of its group, stays ours until p.wait()."""
    try:
        return os.waitid(os.P_PID, p.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError:
        return True
    except AttributeError:
        return p.poll() is not None


def run_verb(argv, env, emit, cap=RUN_CAP):
    """Run one verb for /api/run in a session of its own, each line of
    its output to emit(text), stderr folded in. The rc, 124 past `cap`
    seconds (a monotonic deadline), 127 when it cannot start. When the
    verb ends, or its cap fires, its whole group is killed, and its pipe
    is read LEASH_GRACE more and no longer: a quiet child, or one that
    left the group holding the pipe, cannot hold the runner. A service
    the verb starts is handed off in a session of its own (engine.start)
    and keeps running. An emit that raises (the page hung up) kills the
    group too, and the verb is reaped either way."""
    try:
        p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        emit("! cannot run: %s" % (e.strerror or e))
        return 127
    deadline, grace, fired, ended = time.monotonic() + cap, None, False, False
    fd, buf = p.stdout.fileno(), b""
    try:
        while True:
            now = time.monotonic()
            if not fired and not ended and now > deadline:
                fired = True
                _killpg(p)
            if not fired and not ended and _exited(p):
                ended = True
                _killpg(p)            # what it left in its group goes with it
            if fired or ended:
                grace = grace or now + LEASH_GRACE
                if now > grace:
                    break
            if not select.select([fd], [], [], 0.1)[0]:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            *lines, buf = (buf + chunk).split(b"\n")
            for raw in lines:
                emit(raw.decode("utf-8", errors="replace"))
        if buf:
            emit(buf.decode("utf-8", errors="replace"))
    finally:
        _killpg(p)
        p.wait()
        p.stdout.close()
    return 124 if fired else p.returncode


def _shell():
    return os.path.basename(os.environ.get("SHELL") or "sh")


# ------------------------------------------------------------ the process
def _die(msg, code=1):
    print("! " + msg, file=sys.stderr, flush=True)
    return code


def _env_token_ok():
    """SPARK_FORGE_TOKEN from the environment stands in for the admin
    token file; one shorter than TOKEN_MIN characters is refused with
    the signed line, exit 2, before anything binds."""
    tok = os.environ.get("SPARK_FORGE_TOKEN", "")
    if tok and len(tok) < TOKEN_MIN:
        say("%s forge -- SPARK_FORGE_TOKEN is shorter than %d characters: refused" % (MARK, TOKEN_MIN))
        return False
    return True


def _bind_refused(host):
    """The refusal for an address the forge must never bind, else "":
    the unspecified address in any spelling. An address the whole
    Internet can route to is bound, with a warning said and logged."""
    verdict, why = bind_check(host)
    if verdict == "refuse":
        return why + " -- choose one LAN address (--host ADDR)"
    if verdict:
        say("%s forge -- warning: %s" % (MARK, why))
        log("warning: %s" % why)
    return ""


def _host_port(cfg, args, foreground):
    host = port = ""
    if "--host" in args:
        i = args.index("--host")
        host = args[i + 1] if i + 1 < len(args) else ""
    if "--port" in args:
        i = args.index("--port")
        port = args[i + 1] if i + 1 < len(args) else ""
    host = host or cfg.forge_host or wait_lan_ip(foreground, "forge")
    try:
        port = int(port) if port else cfg.forge_port
    except ValueError:
        port = 0
    return host, port


def _url_of(cfg):
    """The URL the FORGE has or would have here: the bound address."""
    u = forge_url()
    if u:
        return u
    return "%s://%s:%d" % (cfg.forge_scheme, cfg.forge_host or lan_ip() or "<lan-ip>", cfg.forge_port)


def link_url(cfg, url=None):
    """The address a person opens: the page's URL with SPARK_FORGE_NAME
    in place of the bound address when one is set (a certificate names
    a name; the links say it)."""
    u = url or _url_of(cfg)
    if not cfg.forge_name or "<" in u:
        return u
    parts = urllib.parse.urlsplit(u)
    return "%s://%s:%d" % (parts.scheme, cfg.forge_name, parts.port or (443 if parts.scheme == "https" else 80))


def root_url(cfg):
    """Own mode's plain listener for the root: the page's host, its port
    plus one."""
    parts = urllib.parse.urlsplit(link_url(cfg))
    return "http://%s:%d" % (parts.hostname, (parts.port or 443) + tls.TRUST_PORT_OFFSET)


def https_facts(cfg):
    """What the page says of its own https under machine: the mode (off,
    own, pair), the page's link and, in own mode, the root's link for
    the phones and that link's QR as a matrix (GET /api/config)."""
    own = cfg.forge_scheme == "https" and tls.is_own(cfg.forge_cert)
    d = {"mode": "off" if cfg.forge_scheme != "https" else ("own" if own else "pair"),
         "link": link_url(cfg) + "/login"}
    if own:
        ca = root_url(cfg) + "/ca"
        d["ca"] = ca
        d["ca_qr"] = (qr.encode(ca) if "<" not in ca else None) or []
    return d


def _short(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def _misconfigured(cfg):
    """One line saying why no upstream can ever answer, or ''. Nothing
    has to be up: a serve-url, a base URL, or an engine with a model on
    disk is enough to start."""
    if cfg.base_url or wire.serve_url():
        return ""
    try:
        engine.resolve_for_spawn(cfg)
    except engine.EngineError as e:
        return "no model: %s" % e
    return ""


def _write_url(url):
    state_dir()
    fd = vault.open_private(FORGE_URL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    with os.fdopen(fd, "w") as f:
        f.write(url + "\n")


def _pid():
    """The page's server's pid from forge.pid, its command line checked:
    a recycled pid is never signalled."""
    return engine.pid_of(FORGE_PID, engine.FORGE_MARKS)


def forget():
    for p in (FORGE_URL_FILE, FORGE_PID):
        try:
            os.remove(p)
        except OSError:
            pass


def cmd_foreground(args):
    if not _env_token_ok():
        return 2
    cfg = config.load()
    host, port = _host_port(cfg, args, True)
    if not host:
        return _die("no LAN address to bind -- set SPARK_FORGE_HOST", EX_CONFIG)
    why = _bind_refused(host)
    if why:
        return _die(why, EX_CONFIG)
    if not (0 < port < 65536):
        return _die("the port must be 1 to 65535", EX_CONFIG)
    why = _misconfigured(cfg)
    if why:
        return _die(why + " -- ./bootstrap.sh, then spark serve on", EX_CONFIG)
    ensure_token(cfg)
    served = None
    if cfg.forge_scheme == "https":
        try:
            served = tls.Served(cfg.forge_cert, cfg.forge_key)
        except tls.TlsError as e:
            return _die("%s -- spark serve https CERT KEY, or spark serve https off" % e, EX_CONFIG)
    url = "%s://%s:%d" % (cfg.forge_scheme, host, port)
    # bind FIRST, write the records after: writing forge-url before the
    # bind meant a failed second start forget()'d the RUNNING FORGE's
    # url and pid on its way out
    try:
        srv = ForgeServer((host, port), cfg, url, served)
    except OSError as e:
        recorded = forge_url()
        if recorded and isinstance(wire.forge_health(recorded), dict):
            return _die("cannot bind %s: %s -- the page at %s is running, its records stay"
                        % (url, e.strerror or e, recorded))
        forget()
        return _die("cannot bind %s: %s" % (url, e.strerror or e))
    _write_url(url)
    engine.write_pid(FORGE_PID, os.getpid())
    if served and tls.is_own(cfg.forge_cert):
        # own mode: the root on its own plain listener, port plus one, so
        # a phone can fetch it before it trusts anything
        try:
            root = RootServer((host, port + tls.TRUST_PORT_OFFSET), tls.own_paths()["root"], link_url(cfg, url))
            threading.Thread(target=root.serve_forever, daemon=True).start()
            log("root %s" % root.url)
        except (OSError, tls.TlsError) as e:
            say("%s forge -- warning: the root's listener did not start on port %d: %s"
                % (MARK, port + tls.TRUST_PORT_OFFSET, e))
            log("warning: root listener: %s" % e)

    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # bin/spark sets SIGPIPE back to SIG_DFL so `spark ... | head` ends
    # quietly; a server must outlive a browser that hangs up mid-write.
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    log("start %s pid %d" % (url, os.getpid()))
    say("%s forge -- serving at %s" % (MARK, url))
    try:
        srv.serve_forever()
    finally:
        log("stop")
        srv.server_close()
        forget()
    return 0


def cmd_start(args):
    if not _env_token_ok():
        return 2
    cfg = config.load()
    host, port = _host_port(cfg, args, False)
    if not host:
        return _die("no LAN address to bind -- set SPARK_FORGE_HOST", EX_CONFIG)
    why = _bind_refused(host)
    if why:
        return _die(why, EX_CONFIG)
    why = _misconfigured(cfg)
    if why:
        return _die(why + " -- ./bootstrap.sh, then spark serve on", EX_CONFIG)
    url = "%s://%s:%d" % (cfg.forge_scheme, host, port)
    if wire.forge_health(url) not in (None, "down"):
        say("%s serve -- the page already running at %s/login" % (MARK, url))
        return 0
    if engine.forge_service_state(cfg) in ("loaded", "disabled"):
        # a unit is here: its manager starts the page's server, never a
        # Popen beside it (the second one lost the bind, or won it and
        # left the unit restarting every 15 s)
        rc = _through_unit(cfg, url)
        if rc is not None:
            return rc
    state_dir()
    lock = vault.open_private(FORGE_LOCK, os.O_WRONLY | os.O_CREAT)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock)
        return _die("the page is already starting")
    try:
        if os.path.exists(FORGE_LOG) and os.path.getsize(FORGE_LOG) > LOG_MAX:
            os.replace(FORGE_LOG, FORGE_LOG + ".1")
    except OSError:
        pass
    out = vault.open_private(FORGE_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    cmd = [sys.executable, os.path.join(REPO, "bin", "spark"), "forge", "--foreground", "--host", host, "--port", str(port)]
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    finally:
        os.close(out)
        os.close(lock)

    class Exited(Exception):
        pass

    def probe():
        if wire.forge_health(url) not in (None, "down"):
            return True
        if p.poll() is not None:
            raise Exited()
        return False

    try:
        up = wait_ready("", probe, 30, 0.5)
    except Exited:
        return _die("the page exited %d while starting:\n%s" % (p.returncode, "\n".join(log_tail(5))), p.returncode or 1)
    if not up:
        engine.terminate([p.pid])
        return _die("the page did not answer in 30 s:\n" + "\n".join(log_tail(5)))
    say("%s serve -- the page ready (pid %d) at %s/login" % (MARK, p.pid, url))
    return 0


def _through_unit(cfg, url):
    """Start the page's server through its unit and wait on its health, as
    `spark serve on` does for the engine. None when there is no unit to
    start after all (the caller starts by hand)."""
    started = engine.service_start(cfg, "forge")
    if started is None:
        return None
    if not started:
        return 1
    t0 = time.monotonic()

    class StoodDown(Exception):
        pass

    def probe():
        if wire.forge_health(forge_url() or url) not in (None, "down"):
            return True
        if time.monotonic() - t0 > 5 and engine.unit_state(cfg, "forge")[0] == "down":
            raise StoodDown()
        return False

    try:
        up = wait_ready("", probe, 30, 0.5)
    except StoodDown:
        return _die("the page stopped while starting -- %s" % engine.restart_line("forge"))
    if not up:
        return _die("the page did not answer in 30 s -- %s" % engine.restart_line("forge"))
    url = forge_url() or url
    pid = _pid()
    at = " (pid %d)" % pid if pid else ""
    say("%s serve -- the page ready%s at %s/login" % (MARK, at, url))
    return 0


def cmd_stop(args):
    """The page's half of `spark serve off`: its unit stopped and kept
    down, a server started by hand TERMed (--force: KILL after 20 s)."""
    cfg = config.load()
    force = "--force" in args
    st = engine.forge_service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg, "forge") == "system":
            return _die("the page runs from boot -- spark serve boot off, or: sudo launchctl bootout %s" % engine.service_target(cfg, "forge"))
        engine.service_stop(True, "forge")
        pid = _pid()
        if pid:
            left = engine.wait_gone([pid], 20)
            if left:
                engine.terminate(left, force=True)
        forget()
        say("%s serve -- the page stopped" % MARK)
        return 0
    pid = _pid()
    if not pid:
        forget()
        say("%s serve -- the page not running" % MARK)
        return 0
    engine.terminate([pid])
    left = engine.wait_gone([pid], 20)
    if left and force:
        engine.terminate(left, force=True)
        left = engine.wait_gone(left, 5)
    if left:
        return _die("pid %d did not stop -- spark serve off --force" % pid)
    forget()
    say("%s serve -- the page stopped (pid %d)" % (MARK, pid))
    return 0


def page_url(cfg=None):
    """The page's login URL -- the public seam users.cmd_add prints a
    QR of (with a personal token in the fragment; _url_of stays ours)."""
    return link_url(cfg or config.load()) + "/login"


def print_qr(link):
    """The QR of a login link, printed at a tty only: the link IS a
    token, and a pipe has no camera. False (and silence) when the URL
    is still a placeholder or the link outgrows the encoder -- the
    lines already printed stand."""
    if "<" in link:
        return False
    block = qr.render(link)
    if not block:
        return False
    say("")
    say(block)
    return True


def cmd_print_url(args):
    cfg = config.load()
    if "--user" in args:
        say("%s serve -- each user has a token now: spark user add NAME" % MARK)
        return 2
    url = link_url(cfg)
    say(url + "/login")
    cert_lines(cfg)
    own = cfg.forge_scheme == "https" and tls.is_own(cfg.forge_cert)
    if "--show-token" in args or sys.stdout.isatty():
        tok = ensure_token(cfg)
        say("token  " + tok)
        if sys.stdout.isatty() and "--no-qr" not in args:
            if own and print_qr(root_url(cfg) + "/ca"):
                say("scan 1: install this certificate on the phone (iOS: then turn it on under")
                say("        General > About > Certificate Trust Settings)")
            if print_qr(url + "/login#t=" + tok):
                say("scan%s: sign in as admin (others: spark user add NAME)" % (" 2" if own else ""))
                say("or open  %s/login#t=%s" % (url, tok))
    return 0


def cert_lines(cfg):
    """Two lines under the page's address when it serves TLS: the
    certificate's names and end, and the fingerprint a client pins (the
    root's in own mode, the page's own otherwise)."""
    if cfg.forge_scheme != "https":
        return
    try:
        info = tls.read_cert(cfg.forge_cert)
    except tls.TlsError as e:
        say("cert   %s" % e)
        return
    say("cert   %s, until %s" % (", ".join(info["dns"] + info["ips"]) or "no name",
                                 time.strftime("%Y-%m-%d", time.gmtime(info["not_after"]))))
    if tls.is_own(cfg.forge_cert):
        try:
            root = tls.read_cert(tls.own_paths()["root"])
            say("root   %s" % root["sha256"])
            say("       each device installs it once; another spark: spark client URL --pin it")
        except tls.TlsError as e:
            say("root   %s" % e)
    else:
        say("sha256 %s" % info["sha256"])
        say("       another spark that does not trust the issuer: spark client URL --pin it")


def client_steps(url):
    """How another machine joins, three lines, no secret: a user minted
    here (its token shown once), the client there, the login there."""
    base = url[:-len("/login")] if url.endswith("/login") else url
    return ["here:   spark user add NAME     copy the token: it shows once",
            "there:  spark client %s" % base,
            "then:   spark user login NAME   paste the token"]


def cmd_print_client(args):
    """What a peer machine needs: the URL and a personal user. No secret
    ever leaves this box -- the token is shown once at the mint."""
    cfg = config.load()
    url = link_url(cfg)
    say("SITE_PEER_AI_URL=%s" % url)
    say("\n".join(client_steps(url)))
    say("the admin token stays on this machine (spark serve --login)")
    return 0


def cmd_login(args):
    """`spark serve --login`: the page's URL (at a terminal the admin
    token and its QR), then how another machine joins. `--new` rotates
    the admin token instead, asking first at a terminal."""
    if "--new" in args:
        return cmd_token(args)
    cfg = config.load()
    if cfg.client:
        # nothing serves here: the login and the join steps are the other
        # machine's, never this one's
        from . import wire
        from .check import client_of
        if wire.plain(cfg):
            say("%s serve -- %s: no page is served here" % (MARK, client_of(cfg)))
            return 0
        say("%s serve -- %s: run spark serve --login there" % (MARK, client_of(cfg)))
        return 0
    rc = cmd_print_url(args)
    if rc == 0:
        say("\n".join(client_steps(link_url(config.load()))))
    return rc


HTTPS_USAGE = """%s serve https -- the page over https

  spark serve https            the certificate served, who must trust it
  spark serve https CERT KEY   your own pair, PEM files, the key private
                               (--name HOST: the name in the page's links)
  spark serve https own        a root and a certificate of this machine's
                               own: each device installs the root once
  spark serve https off        plain http again
""" % MARK


def cmd_https(args):
    """`spark serve https`: bare shows; CERT KEY, own and off act. The
    keys land in spark.env and the page's server starts again with
    them; `spark serve --login` then prints the https link, the
    fingerprint and, in own mode, the root's QR."""
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(HTTPS_USAGE.rstrip())
        return 0
    if cfg.client:
        from .check import client_of
        say("%s serve https -- %s: the page is the other machine's" % (MARK, client_of(cfg)))
        return 0
    if not args:
        return _https_show(cfg)
    name = ""
    if "--name" in args:
        i = args.index("--name")
        name = args[i + 1].strip().lower() if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
        if not name or re.search(r"[^a-z0-9.-]", name):
            say("%s serve https -- --name takes a DNS name" % MARK)
            return 2
    if args == ["off"]:
        return _https_off(cfg)
    if args == ["own"]:
        return _https_own(cfg, name)
    if len(args) != 2:
        say(HTTPS_USAGE.rstrip())
        return 2
    cert, key = (os.path.abspath(os.path.expanduser(a)) for a in args)
    if any(re.search(r"[;`$()|&<>]", a) for a in (cert, key)):
        say("%s serve https -- a path cannot hold ; ` $ ( ) | & < > (contract 3)" % MARK)
        return 2
    try:
        info = tls.check_pair(cert, key)
    except tls.TlsError as e:
        say("%s serve https -- %s" % (MARK, e))
        return 2
    target = name or cfg.forge_host or lan_ip()
    if target and target not in info["dns"] and target not in info["ips"]:
        hint = " -- --name %s" % info["dns"][0] if info["dns"] and not name else ""
        say("%s serve https -- the certificate does not name %s; it names %s%s"
            % (MARK, target, ", ".join(info["dns"] + info["ips"]) or "nothing", hint))
        return 2
    from . import site
    site.set_keys(_file=SPARK_ENV, SPARK_FORGE_CERT=cert, SPARK_FORGE_KEY=key, SPARK_FORGE_NAME=name)
    tls.HANDLER.refresh()
    rc = _restart_page()
    return rc or _https_show(config.load())


def _https_own(cfg, name):
    """A root of this machine's own, minted once and constrained to its
    names, and a leaf under it for its names and address; minted again
    when due or when the names moved. A name the root does not cover
    is refused: the root is what the devices installed."""
    if not tls.openssl():
        say("%s serve https -- no openssl binary here -- install openssl, or give spark a pair: spark serve https CERT KEY" % MARK)
        return 2
    from . import site
    p = tls.own_paths()
    names = sorted(own_hostnames() | {n for n in (name, cfg.forge_name) if n})
    host = cfg.forge_host or lan_ip()
    ips = list(dict.fromkeys(i for i in (host, "127.0.0.1") if i))
    try:
        if not (os.path.isfile(p["root"]) and os.path.isfile(p["root_key"])):
            tls.mint_root(names, cfg.name or "spark")
            say("* a root of this machine's own, for %s" % ", ".join(names))
        else:
            missing = [n for n in names if n not in tls.own_names()]
            if missing:
                say("%s serve https -- the root does not cover %s -- spark serve https off, then own again (each device installs the root again)"
                    % (MARK, ", ".join(missing)))
                return 2
        need = True
        if os.path.isfile(p["cert"]):
            try:
                cur = tls.read_cert(p["cert"])
                need = tls.renew_due() or sorted(cur["dns"]) != names or sorted(cur["ips"]) != sorted(ips)
            except tls.TlsError:
                need = True
        if need:
            tls.mint_leaf(names, ips, cfg.name or "spark")
            say("* the page's certificate, for %s" % ", ".join(names + ips))
    except tls.TlsError as e:
        say("%s serve https -- %s" % (MARK, e))
        return 2
    site.set_keys(_file=SPARK_ENV, SPARK_FORGE_CERT=p["cert"], SPARK_FORGE_KEY=p["key"], SPARK_FORGE_NAME=name or cfg.forge_name)
    tls.HANDLER.refresh()
    rc = _restart_page()
    return rc or _https_show(config.load())


def _https_off(cfg):
    if cfg.forge_scheme != "https":
        say("%s serve https -- the page is plain http already" % MARK)
        return 0
    from . import site
    named = cfg.forge_name
    site.set_keys(_file=SPARK_ENV, SPARK_FORGE_CERT="", SPARK_FORGE_KEY="", SPARK_FORGE_NAME="")
    tls.HANDLER.refresh()
    rc = _restart_page()
    say("* the page is plain http again%s" % ("; a browser that saw https://%s keeps asking for https for up to a week" % named if named else ""))
    return rc


def _https_show(cfg):
    if cfg.forge_scheme != "https":
        say("%s serve https -- the page is plain http" % MARK)
        say("  spark serve https CERT KEY   a pair you were given: an office, certbot, step, tailscale cert")
        say("  spark serve https own        a root and a certificate of this machine's own")
        return 0
    own = tls.is_own(cfg.forge_cert)
    say("%s serve https -- %s" % (MARK, "a root and a certificate of this machine's own" if own else "your pair, " + _short(cfg.forge_cert)))
    say("  page     %s/login" % link_url(cfg))
    try:
        info = tls.read_cert(cfg.forge_cert)
        say("  names    %s" % (", ".join(info["dns"] + info["ips"]) or "none"))
        say("  until    %s (%d days)" % (time.strftime("%Y-%m-%d", time.gmtime(info["not_after"])), int(tls.days_left(info))))
        say("  sha256   %s" % info["sha256"])
    except tls.TlsError as e:
        say("  ! %s" % e)
    if own:
        try:
            root = tls.read_cert(tls.own_paths()["root"])
            say("  root     %s, until %s" % (root["sha256"], time.strftime("%Y-%m-%d", time.gmtime(root["not_after"]))))
        except tls.TlsError as e:
            say("  root     ! %s" % e)
        say("  trust    each device installs the root once (spark serve --login shows its QR);")
        say("           another spark: spark client URL --pin ROOT")
    else:
        say("  trust    browsers must trust the issuer: nothing to do for a public one;")
        say("           another spark that does not: spark client URL --pin SHA256, or --ca FILE")
    return 0


def _restart_page():
    """The page's server again with the keys as they are now: one
    restart through its unit when one is loaded, stop and start by hand
    otherwise; nothing when it is not running. One command, because the
    verb may be the page's own child (`https` under machine runs it):
    systemd stops a unit's whole cgroup, the verb's process in it, and
    a restart it was asked for happens all the same -- a stop followed
    by a start would end at the stop."""
    cfg = config.load()
    if engine.forge_service_state(cfg) == "loaded":
        return 0 if engine.kickstart(cfg, "forge", restart=True) else 1
    if not _pid():
        return 0
    rc = cmd_stop(["--force"])
    return rc or cmd_start([])


class RootHandler(BaseHTTPRequestHandler):
    """Own mode's plain listener: `GET /ca` is the root in DER, the shape
    iOS and Android install from; `GET /` says what to do with it.
    Nothing else: no cookie, no token, 404 to every other route and
    method. It runs beside the page, on its port plus one."""
    server_version = "spark-forge/" + VERSION
    sys_version = ""
    timeout = 10

    def log_message(self, *a):
        pass

    def __getattr__(self, name):
        if not name.startswith("do_"):
            raise AttributeError(name)
        return self._missing

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _missing(self):
        self._send(404, "application/json", b'{"error": {"kind": "missing", "hint": "no such route"}}')

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/ca":
            return self._send(200, "application/x-x509-ca-cert", self.server.root_der,
                              {"Content-Disposition": 'attachment; filename="spark-root.crt"'})
        if path == "/":
            body = ("install the certificate at %s/ca on this device, then open %s/login\n"
                    % (self.server.url, self.server.page_url)).encode()
            return self._send(200, "text/plain; charset=utf-8", body)
        return self._missing()


class RootServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, root_path, page_url):
        self.root_der = tls.read_pem(root_path)
        self.url = "http://%s:%d" % addr
        self.page_url = page_url
        ThreadingHTTPServer.__init__(self, addr, RootHandler)


def cmd_token(args):
    cfg = config.load()
    flags = set(args)
    if "--user" in flags:
        say("%s serve -- each user has a token now: spark user token --new" % MARK)
        return 2
    if "--new" not in flags or flags - {"--new"}:
        say(USAGE.rstrip())
        return 2
    if sys.stdin.isatty() and sys.stdout.isatty() and not confirm(
            "make a new admin token -- every admin logs in again"):
        return 0
    # one atomic replace, fsynced: the old token is dead the instant the
    # new one is on disk, and no moment has none (the server re-reads
    # the file on its mtime, admin_token)
    path = cfg.forge_token_file
    state_dir()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    vault.write_private(path, (secrets.token_urlsafe(32) + "\n").encode(), durable=True)
    say("%s serve -- new admin token -- log in again: spark serve --login" % MARK)
    from . import audit
    why = audit.record("forge token")
    if why:
        say("%s serve -- not recorded in the audit: %s" % (MARK, why))
    return 0


def cmd_onoff(sub, args=()):
    from . import site
    site.set_keys(_file=SPARK_ENV, SPARK_FORGE=sub)
    rc = site.apply(["spark-forge", "spark.forge"])
    if rc:
        return rc
    return cmd_start([]) if sub == "on" else cmd_stop(args or ["--force"])


def main(argv):
    """`spark forge`: what the page's unit runs (--foreground), and the
    older spellings `spark serve` took over -- each kept as an alias
    named nowhere: bare (the serve view), on|off (the page alone, as it
    was), --print-url, --print-client, token --new, audit."""
    sub = argv[0] if argv else "status"
    rest = argv[1:]
    if sub in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if sub == "--foreground":
        return cmd_foreground(rest)
    if sub == "status":
        from . import serve
        return serve.cmd_show()
    if sub == "--print-url":
        return cmd_print_url(rest)
    if sub == "--print-client":
        return cmd_print_client(rest)
    if sub == "token":
        return cmd_token(rest)
    if sub == "audit":
        from . import audit
        return audit.cmd_audit(rest)
    if sub in ("on", "off"):
        return cmd_onoff(sub, rest)
    say(USAGE.rstrip())
    return 2
