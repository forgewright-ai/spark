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
# memory only. Bearer auth is stateless; a cookie login lives in an
# in-memory session, so a restart sends browsers back to the login (the
# key cannot come back from a cookie). The v1.3 shared ember-token is
# gone: the server no longer accepts it. No TLS: the trust model is your
# LAN -- see README "What leaves this machine".

import fcntl
import hashlib
import hmac
import json
import os
import re
import signal
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

from . import (BAR_CACHE, CHECK_JSON, CONFIG_DIR, EMBER_TOKEN_FILE, FORGE_LOCK, FORGE_LOG, FORGE_PID,
               FORGE_URL_FILE, HOME, IS_MAC, MARK, OFF_FLAG, REPO, SERVE_URL_FILE, SPARK_ENV,
               config, forge_url, lan_ip, log_exc, own_hostnames, say, state_dir, wait_ready)
from . import engine, wire
from . import version as _version

# resolved once, at daemon import: `spark forge` is a long-running process,
# so paying one `git describe` (version()'s cache miss) here is fine.
VERSION = _version.version()

EX_CONFIG = engine.EX_CONFIG
COOKIE = "spark_forge"
COOKIE_SALT = b"spark-forge-session"
COOKIE_AGE = 7776000            # 90 days
FAILS_PER_MIN = 10              # wrong logins from one address before 429
BODY_MAX = 1_000_000            # a request body larger than this is 413
LOG_MAX = 1_000_000             # forge.log rotates here, like serve.log
STATIC = {"index.html": "text/html; charset=utf-8", "spark.css": "text/css; charset=utf-8",
          "spark.js": "text/javascript; charset=utf-8",
          "manifest.webmanifest": "application/manifest+json; charset=utf-8",
          "favicon.svg": "image/svg+xml; charset=utf-8"}
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forge")
UPSTREAM_TTL = 60               # a resolved upstream is trusted this long
UPSTREAM_MISS_TTL = 5           # a failed resolution is not retried sooner
MODELS_TTL = 5                  # /api/health's models field is re-read this often
EVENTS_POLL = 2
EVENTS_KEEPALIVE = 15
TMUX_SEQ = re.compile(r"#\[[^\]]*\]")
QUEUE_WAIT = 0.2                # a chat that waits longer than this for the model says `queued`
RUN_CAP = 1800                  # seconds a verb may run through /api/run
RUN_ARG = re.compile(r"^[A-Za-z0-9._/:@+= -]{0,200}$")
# The verbs the page may run, and what their arguments must be (None: any
# that match RUN_ARG). The verb itself validates and applies; nothing else
# from the LAN writes config.
RUN_VERBS = {"theme": None, "model": None, "ember": None, "font": None, "quiet": None, "bench": None, "on": None, "off": None,
             "serve": None, "stop": None, "remember": None, "forget": None,
             "tune": lambda a: a[:1] == ["apply"],
             "forge": lambda a: a == ["token", "--new"]}
# Admin-only routes (class A). Everything else under /api and /v1 that
# needs auth is class U: user or admin. A user hitting A gets 403 "role".
ADMIN_GET = frozenset(("/api/serve", "/api/gpu", "/api/bench", "/api/config", "/api/log", "/api/users"))
ADMIN_POST = frozenset(("/api/run", "/api/do/propose", "/api/do/run", "/api/check/refresh", "/api/soul"))

USAGE = """%s forge -- the served agent

  spark forge                  status: url, health, model, unit, token, log tail
  spark forge on | off         SPARK_FORGE in spark.env; the unit; start/stop
  spark forge start | stop     by hand (a managed unit needs stop --force)
  spark forge --foreground     what the unit runs; exit 78 = misconfigured
                               (--host ADDR, --port N override the config)
  spark forge --print-url      the page's login URL; the admin token on
                               a tty (or with --show-token); a user logs
                               in with their own (spark user add NAME)
  spark forge --print-client   what a peer machine needs: the URL, and
                               how to mint a user there
  spark forge token --new      rotate the admin token; its logins die
                               (a user rotates with spark user token --new)
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


def cookie_value(token):
    return hmac.new(token.encode(), COOKIE_SALT, hashlib.sha256).hexdigest()


def _hash_current(name, h):
    """Whether hash h is still the named user's token verifier -- a
    rotation or removal kills every cached key and session for them."""
    from . import users
    try:
        with open(os.path.join(users.user_dir(name), "token.hash"), encoding="utf-8") as f:
            return hmac.compare_digest(h, f.read().strip())
    except OSError:
        return False


# -------------------------------------------------------------------- log
_log_lock = threading.Lock()


def log(line):
    """One line into forge.log (0600, rotated at 1 MB). Never a token,
    never a body."""
    with _log_lock:
        try:
            state_dir()
            try:
                if os.path.getsize(FORGE_LOG) > LOG_MAX:
                    os.replace(FORGE_LOG, FORGE_LOG + ".1")
            except OSError:
                pass
            fd = os.open(FORGE_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
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
            fh = wire.forge_health(u)
            if fh == "down" or (fh and fh.get("forge")):
                continue                    # nothing there, or a FORGE: not for us
            st = wire.health(u)
            if st == "ok":
                try:
                    model = wire.model_name(self.cfg, u)
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
            raise wire.BrainError("loading", "%s is still loading its model -- try again in a moment" % url)
        if st == "auth":
            raise wire.BrainError("auth", "the llama-server rejected this machine's api-token")
        raise wire.BrainError("down", wire.no_brain_hint(self.cfg))

    def require(self):
        """The url to proxy to, or BrainError."""
        return self.brain().url


# ----------------------------------------------------------------- server
class ForgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, cfg, url):
        ThreadingHTTPServer.__init__(self, addr, Handler)
        self.cfg, self.url = cfg, url
        self.host, self.port = addr
        self.upstream = Upstream(cfg, url)
        self.chat_lock = threading.Lock()      # one generation at a time: the model is one
        self.run_lock = threading.Lock()       # one verb at a time
        self._admin, self._admin_t = "", None
        self._user_keys = {}                    # sha256(token) -> (name, dk), unlocked once
        self.sessions = {}                      # cookie -> (name, dk, token hash); memory only
        self._auth_lock = threading.Lock()
        self._models = (0.0, [])               # (epoch, [(alias, stem, loaded)])
        self._fails = {}                        # ip -> [epoch of wrong login]
        self._fails_lock = threading.Lock()
        names = {self.host, "127.0.0.1", "localhost"} | own_hostnames() | {lan_ip()}
        self.hosts = {n for n in names if n} | {"%s:%d" % (n, self.port) for n in names if n}

    def admin_token(self):
        """The forge-token, re-read when its file changes: `spark forge
        token --new` takes effect without a restart, and every cookie
        minted from the old token dies with it."""
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
        h = vault.token_hash(tok)
        with self._auth_lock:
            hit = self._user_keys.get(h)
        if hit and _hash_current(hit[0], h):
            return hit
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

    def session_user(self, cookie):
        """(name, dk) of a logged-in browser, or None -- sessions live in
        memory only: a restart sends every browser back to the login."""
        with self._auth_lock:
            s = self.sessions.get(cookie)
        if s and _hash_current(s[0], s[2]):
            return s[0], s[1]
        return None

    def remember_session(self, token, name, dk):
        from . import vault
        with self._auth_lock:
            self.sessions[cookie_value(token)] = (name, dk, vault.token_hash(token))

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

    def role_models(self, url):
        """{role: file stem} -- what the page's header and the chat's done
        event show; nothing about the pair is baked into the page."""
        return dict((a, st) for a, st, _l in self.models_list(url))

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
        self.end_headers()

    def _json(self, code, obj, extra=None):
        data = json.dumps(obj).encode()
        h = {"Cache-Control": "no-store"}
        h.update(extra or {})
        self._start(code, "application/json", h, len(data))
        if self.command != "HEAD":
            self.wfile.write(data)
        self._status = code

    def _error(self, code, kind, hint, extra=None):
        self._json(code, {"error": {"kind": kind, "hint": hint}}, extra)

    def _body(self):
        """The JSON body, or None (and a 400/413 already sent)."""
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
        except (ValueError, UnicodeDecodeError):
            self._error(400, "bad", "the body is not JSON")
            return None
        if not isinstance(d, dict):
            self._error(400, "bad", "the body must be a JSON object")
            return None
        return d

    def _sse(self):
        self._start(200, "text/event-stream", {"Cache-Control": "no-store"})
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
        cookie: the forge-token is admin; a personal token names its
        user and unwraps their key. A wrong bearer costs a second and is
        counted; an unknown cookie is only a 401 -- after a restart every
        browser holds one, and punishing that would lock the door on the
        way back to the login."""
        srv = self.server
        admin = srv.admin_token()
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            given = auth[7:].strip()
            if admin and hmac.compare_digest(given, admin):
                return "admin", "", None
            hit = srv.user_by_bearer(given)
            if hit:
                return "user", hit[0], hit[1]
            self._punish("bearer")
            return "", "", None
        c = self._cookie()
        if c:
            if admin and hmac.compare_digest(c, cookie_value(admin)):
                return "admin", "", None
            s = srv.session_user(c)
            if s:
                return "user", s[0], s[1]
            log("%s unknown cookie" % self._ip())
        return "", "", None

    def _punish(self, what):
        log("%s wrong %s" % (self._ip(), what))
        self.server.failed(self._ip())
        time.sleep(1)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        return host in self.server.hosts

    def _post_ok(self):
        """The P rules: X-Spark, a same-host Origin when there is one, a
        Host this machine answers to. False = a response was sent."""
        if not self._host_ok():
            self._error(400, "bad", "Host is not this machine")
            return False
        if self.headers.get("X-Spark") != "1":
            self._error(403, "forbidden", "POST needs the header X-Spark: 1")
            return False
        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            try:
                oh = urllib.parse.urlsplit(origin).netloc.lower()
            except ValueError:
                oh = ""
            if not oh or oh != (self.headers.get("Host") or "").strip().lower():
                self._error(403, "forbidden", "Origin does not match Host")
                return False
        return True

    # ---- dispatch ----
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

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
        # no auth
        if method == "GET" and path == "/api/health":
            return self.api_health()
        if method == "POST" and path == "/api/login":
            return self.api_login()
        if method == "GET" and path in ("/", "/login"):
            return self.static("index.html")
        if method == "GET" and path == "/manifest.webmanifest":
            return self.static("manifest.webmanifest")
        if method == "GET" and path == "/apple-touch-icon.png":
            return self.apple_touch_icon()
        if method == "GET" and path.startswith("/static/"):
            return self.static(path[8:])
        if not path.startswith(("/api/", "/v1/")):
            return self._error(404, "missing", "no such page")
        # bearer or cookie; whichever token matched decides role and user
        self.role, self.user, self.dk = self._auth()
        if not self.role:
            return self._error(401, "auth", "log in with your token (spark user add NAME mints one on %s; the admin's is spark forge --print-url)" % srv.cfg.name)
        admin_only = path in (ADMIN_GET if method == "GET" else ADMIN_POST if method == "POST" else ())
        if admin_only and self.role != "admin":
            return self._error(403, "role", "this needs the admin token")
        if method == "GET":
            fn = {"/v1/models": self.v1_models, "/api/me": self.api_me, "/api/check": self.api_check,
                  "/api/stats": self.api_stats,
                  "/api/bar": self.api_bar, "/api/serve": self.api_serve, "/api/gpu": self.api_gpu,
                  "/api/bench": self.api_bench, "/api/config": self.api_config, "/api/theme": self.api_theme,
                  "/api/log": self.api_log, "/api/events": self.api_events, "/api/threads": self.api_threads,
                  "/api/soul": self.api_soul, "/api/memory": self.api_memory,
                  "/api/users": self.api_users}.get(path)
            if fn:
                return fn()
            if path.startswith("/api/threads/"):
                return self.api_thread(path[13:])
            return self._error(404, "missing", "no such route")
        if method == "POST" and path == "/v1/chat/completions":
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
            return self._error(404, "missing", "no such route")
        fn = {("POST", "/api/logout"): self.api_logout, ("POST", "/api/check/refresh"): self.api_check_refresh,
              ("POST", "/api/chat"): self.api_chat, ("POST", "/api/soul"): self.api_soul_write,
              ("POST", "/api/memory"): self.api_memory_add, ("POST", "/api/do/propose"): self.api_do_propose,
              ("POST", "/api/do/run"): self.api_do_run, ("POST", "/api/run"): self.api_run,
              ("POST", "/api/user/token"): self.api_user_token}.get((method, path))
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
        self._json(200, {"status": "ok", "forge": True, "name": cfg.name, "version": VERSION,
                         "model": model if st == "ok" else "", "upstream": st,
                         "models": self.server.models_status(url if st == "ok" else ""),
                         "roles": self.server.role_models(url if st == "ok" else "")})

    def api_login(self):
        ip = self._ip()
        if self.server.locked_out(ip):
            log("%s login locked out" % ip)
            return self._error(429, "locked", "too many wrong tokens from %s; wait a minute" % ip, {"Retry-After": "60"})
        body = self._body()
        if body is None:
            return None
        admin = self.server.admin_token()
        given = body.get("token")
        tok, role, uname = "", "", ""
        if isinstance(given, str) and given:
            if admin and hmac.compare_digest(given, admin):
                tok, role = given, "admin"
            else:
                hit = self.server.user_by_bearer(given)
                if hit:
                    tok, role, uname = given, "user", hit[0]
                    self.server.remember_session(given, hit[0], hit[1])
        if not tok:
            log("%s login failed" % ip)
            self.server.failed(ip)
            time.sleep(1)
            return self._error(401, "auth", "wrong token")
        log("%s login ok %s%s" % (ip, role, " " + uname if uname else ""))
        cookie = "%s=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d" % (COOKIE, cookie_value(tok), COOKIE_AGE)
        return self._json(200, {"ok": True, "name": self.server.cfg.name, "role": role, "user": uname},
                          {"Set-Cookie": cookie})

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
             "Referrer-Policy": "no-referrer", "ETag": etag, "Cache-Control": "no-cache"}
        if self.headers.get("If-None-Match") == etag:
            self._start(304, STATIC[name], h)
            self._status = 304
            return None
        self._start(200, STATIC[name], h, len(data))
        if self.command != "HEAD":
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
        if self.command != "HEAD":
            self.wfile.write(png)
        self._status = 200
        return None

    # ---- the OpenAI-compatible face ----
    def v1_models(self):
        cfg = self.server.cfg
        try:
            up = self.server.upstream.require()
            req = urllib.request.Request(up + "/v1/models", headers=wire._headers(cfg))
            with urllib.request.urlopen(req, timeout=cfg.timeout) as r:
                data = r.read()
        except wire.BrainError as e:
            return self._error(502, e.kind, e.hint)
        except urllib.error.HTTPError as e:
            return self._error(502, "bad", "upstream answered HTTP %d" % e.code)
        except (urllib.error.URLError, OSError) as e:
            return self._error(502, "down", str(e))
        self._start(200, "application/json", {"Cache-Control": "no-store"}, len(data))
        self.wfile.write(data)
        self._status = 200
        return None

    def v1_chat(self, body):
        """The api-token goes on and the answer comes back as it is: JSON,
        or the SSE bytes straight through. A missing model means ember;
        the identity (soul, memory) goes in only for an ember request --
        a spark request keeps the client's system message untouched, so
        the prompt line stays cheap on every machine."""
        from . import forge
        cfg = self.server.cfg
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not all(isinstance(m, dict) for m in msgs):
            return self._error(400, "bad", "messages must be a list of {role, content}")
        model = body.get("model") or "ember"
        body["model"] = model
        if model == "ember":
            mem = self._mstore()        # a user's own memory rides their request
            if msgs and msgs[0].get("role") == "system":
                prefix = msgs[0].get("content")
                prefix = prefix if isinstance(prefix, str) else ""
                msgs[0] = {"role": "system", "content": forge.identity(cfg, mem) + ("\n\n" + prefix if prefix else "")}
            else:
                msgs.insert(0, {"role": "system", "content": forge.system(cfg, "ask", "sh", mem)})
        body["messages"] = msgs
        stream = bool(body.get("stream"))
        try:
            up = self.server.upstream.require()
        except wire.BrainError as e:
            return self._error(502, e.kind, e.hint)
        timeout = max(cfg.timeout, 60.0)
        with self.server.chat_lock:
            try:
                r = wire._post(cfg, up, body, timeout, stream=stream)
            except wire.BrainError as e:
                if e.kind == "down":
                    self.server.upstream.resolve(fresh=True)
                return self._error(502, e.kind, e.hint)
            with r:
                if not stream:
                    data = r.read()
                    self._start(200, r.headers.get("Content-Type") or "application/json", {"Cache-Control": "no-store"}, len(data))
                    self.wfile.write(data)
                    self._status = 200
                    return None
                self._start(200, "text/event-stream", {"Cache-Control": "no-store"})
                self._status = 200
                while True:
                    chunk = r.readline()
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        return None

    # ---- the monitor ----
    def api_me(self):
        """Who the presented token makes this client (class U): the page
        renders the admin or the user console from this, and greets the
        user by name."""
        self._json(200, {"role": self.role, "user": self.user,
                         "name": self.server.cfg.name, "version": VERSION})

    def api_check(self):
        try:
            with open(CHECK_JSON, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                raise ValueError
        except (OSError, ValueError):
            d = {"ts": 0, "counts": {}, "rows": []}
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
        d.update({"days": days, "baseline": bench.baseline(cfg) or None, "running": stats.running_settings(cfg)})
        return self._json(200, d)

    def api_bar(self):
        from . import bar
        cfg = self.server.cfg
        d = {}
        try:
            with open(BAR_CACHE, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            pass
        line, t = d.get("line", ""), d.get("t", 0)
        if not line or time.time() - t > 2 * bar.INTERVAL:
            line, t = bar.line(cfg), time.time()
        self._json(200, {"t": t, "line": TMUX_SEQ.sub("", line).strip()})

    def api_serve(self):
        cfg = self.server.cfg
        url = wire.serve_url()
        health = wire.health(url) if url else "down"
        model = ""
        if health == "ok":
            try:
                model = wire.model_name(cfg, url)
            except wire.BrainError:
                model = "?"
        self._json(200, {"url": url, "health": health, "model": model, "service": engine.service_state(cfg),
                         "pids": engine.server_pids(cfg.port), "mem_free_gb": round(engine.mem_available_gb(), 1),
                         "log": engine.log_tail(40).splitlines()})

    def api_gpu(self):
        self._json(200, engine.gpu_info() or {})

    def api_bench(self):
        from . import bench
        cfg = self.server.cfg
        self._json(200, {"baseline": bench.baseline(cfg) or None, "tune": bench.load_tune(), "now": bench.settings_of(cfg)})

    def api_config(self):
        from . import site, theme
        cfg = self.server.cfg
        _url, model, st = self.server.upstream.resolve()

        def clean(d):
            return {k: v for k, v in d.items() if "KEY" not in k and "TOKEN" not in k}
        self._json(200, {"site": clean(cfg.site_file), "spark": clean(cfg.spark_file),
                         "effective": clean({k: cfg.get(k, "") for k in config.KEYS}),
                         "themes": theme.palettes(), "models": site.model_rows(cfg, model if st == "ok" else ""),
                         "off": os.path.exists(OFF_FLAG), "service": engine.service_state(cfg),
                         "forge": {"url": self.server.url, "service": engine.forge_service_state(cfg), "mode": cfg.forge}})

    def api_theme(self):
        from . import theme
        cfg = self.server.cfg
        pal = None
        path = os.path.join(CONFIG_DIR, "theme.env")
        if os.path.isfile(path):
            try:
                pal = config.parse_env(path)
            except SystemExit:
                pal = None
        self._json(200, {"name": cfg.theme, "palette": pal, "palettes": theme.palettes()})

    def api_log(self):
        try:
            n = max(1, min(1000, int((self.query.get("n") or ["40"])[0])))
        except ValueError:
            n = 40
        self._json(200, {"lines": log_tail(n)})

    def api_events(self):
        """SSE until the client goes: check / bar / serve on change -- and
        the log line too for an admin, never for a user -- plus a comment
        every 15 s so proxies and phones keep the line open."""
        self._sse()
        watched = (CHECK_JSON, BAR_CACHE, SERVE_URL_FILE) + ((FORGE_LOG,) if self.role == "admin" else ())

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
            elif i == 1:
                try:
                    with open(BAR_CACHE, encoding="utf-8") as f:
                        d = json.load(f)
                    emit("bar", {"line": TMUX_SEQ.sub("", d.get("line", "")).strip()})
                except (OSError, ValueError):
                    pass
            elif i == 2:
                url = wire.serve_url()
                emit("serve", {"url": url, "health": wire.health(url) if url else "down"})
            else:
                tail = log_tail(1)
                emit("log", {"line": tail[0] if tail else ""})

        last = stamps()
        for i in range(3):
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
            return self._error(400, "bad", "a thread id is letters, digits, - and _")
        if not st.exists(tid):
            return self._error(404, "missing", "no thread %s" % tid)
        return self._json(200, {"id": tid, "messages": st.load(tid)})

    def api_threads_clear(self):
        """DELETE /api/threads: clear the requester's own threads."""
        n = self._ustore().clear()
        log("%s threads clear %d" % (self._ip(), n))
        return self._json(200, {"cleared": n})

    def api_users(self):
        """The named users, counts and stamps only -- never a title, a
        body, or a token. The whole of admin visibility into user data."""
        from . import users
        out = []
        for n in users.list_users():
            count, newest = users._thread_stats(n)
            out.append({"name": n, "threads": count,
                        "last": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest)) if newest else ""})
        self._json(200, {"users": out})

    def api_user_token(self, body):
        """POST /api/user/token: rotate the requesting user's own token.
        The session already holds their key; the new token is returned
        once and never stored."""
        from . import users
        if self.role != "user":
            return self._error(403, "role", "the admin rotates with spark forge token --new")
        new = users.rewrap(self.user, self.dk)
        self.server.remember_session(new, self.user, self.dk)
        log("%s user token rotated %s" % (self._ip(), self.user))
        cookie = "%s=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d" % (COOKIE, cookie_value(new), COOKIE_AGE)
        return self._json(200, {"token": new}, {"Set-Cookie": cookie})

    def _thread_of(self, body):
        """The thread a body names, checked against the requester's own
        store: (id or None, ok). A response was sent when not ok."""
        from . import forge
        tid = body.get("thread")
        if tid is None or tid == "":
            return None, True
        if not forge.valid_id(tid):
            self._error(400, "bad", "a thread id is letters, digits, - and _")
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

    def _generating(self):
        """Take the chat lock; the SSE headers are out already, so a wait
        longer than QUEUE_WAIT tells the client it is queued."""
        lock = self.server.chat_lock
        if not lock.acquire(timeout=QUEUE_WAIT):
            self._emit("queued", {})
            lock.acquire()
        return lock

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
        if mode == "talk":      # the old name, accepted for one version
            mode = "chat"       # records write mode "chat" from now on
        if mode not in ("chat", "ask"):
            return self._error(400, "bad", "mode is chat or ask")
        thread, ok = self._thread_of(body)
        if not ok:
            return None
        self._sse()
        lock = self._generating()
        try:
            try:
                thread, _answer, ms = forge.reply(cfg, thread, text, cwd=cwd, shell=_shell(), mode=mode,
                                                  on_delta=lambda d: self._emit("delta", {"t": d}), brain=self.server.upstream.brain,
                                                  store=self._ustore(), mem=self._mstore())
            except wire.BrainError as e:
                if e.kind == "down":
                    self.server.upstream.resolve(fresh=True)
                return self._emit("error", {"kind": e.kind, "hint": e.hint})
            except forge.RefError as e:
                return self._emit("error", {"kind": "ref", "hint": e.hint})
        finally:
            lock.release()
        rm = self.server.role_models(self.server.upstream.resolve()[0])
        used = rm.get("ember") or (sorted(rm.values())[0] if rm else "")
        self._emit("done", {"thread": thread, "ms": ms, "model": used})
        session.prune(cfg)
        forge.prune(cfg)
        return None

    # ---- soul and memory ----
    def api_soul(self):
        from . import soul
        cfg = self.server.cfg
        text, source = soul.read(cfg)
        self._json(200, {"text": text, "source": source})

    def api_soul_write(self, body):
        from . import check, soul
        text = body.get("text")
        if not isinstance(text, str):
            return self._error(400, "bad", "text must be a string")
        soul.write(self.server.cfg, text)
        n = len(text.strip())
        check.refresh()
        return self._json(200, {"chars": min(n, soul.SOUL_MAX), "cut": n > soul.SOUL_MAX})

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
        fact = memory.forget_n(int(rest), self._mstore())
        if fact is None:
            return self._error(404, "missing", "no fact %s" % rest)
        return self._json(200, {"text": fact})

    # ---- do ----
    def api_do_propose(self, body):
        """One step proposed, nothing run; the thread continues or starts."""
        from . import do, forge
        cfg = self.server.cfg
        text, cwd = self._text_cwd(body)
        if text is None:
            return None
        thread, ok = self._thread_of(body)
        if not ok:
            return None
        if thread is None:
            thread = forge.new_thread(cfg)
        with self.server.chat_lock:
            try:
                reply, ms = do.propose(cfg, thread, text, _shell(), cwd or HOME, brain=self.server.upstream.brain)
            except wire.BrainError as e:
                if e.kind == "down":
                    self.server.upstream.resolve(fresh=True)
                return self._error(502, e.kind, e.hint)
        rm = self.server.role_models(self.server.upstream.resolve()[0])
        driver = rm.get("ember") or (sorted(rm.values())[0] if rm else "")
        return self._json(200, {"thread": thread, "reply": reply, "ms": ms,
                                "driver": driver,
                                "unchecked": do.conclusion_check(thread, reply)})

    def api_do_run(self, body):
        """One step the user clicked, run as typed; the command is logged
        (truncated), never re-judged here -- the page asked twice already."""
        from . import do
        command, cwd = body.get("command"), body.get("cwd") or ""
        if not isinstance(command, str) or not command.strip():
            return self._error(400, "bad", "command is empty")
        if not isinstance(cwd, str):
            return self._error(400, "bad", "cwd must be a string")
        log("%s do/run %s" % (self._ip(), " ".join(command.split())[:200]))
        rc, tail = do.run(command, _shell(), cwd or HOME, echo=False)
        return self._json(200, {"rc": rc, "tail": tail})

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
        with self.server.run_lock:
            try:
                p = subprocess.Popen([sys.executable, os.path.join(REPO, "bin", "spark"), verb] + args, env=env,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            except OSError as e:
                self._emit("line", {"s": "spark: cannot run: %s" % (e.strerror or e)})
                return self._emit("done", {"rc": 127})
            timer = threading.Timer(RUN_CAP, p.kill)
            timer.daemon = True
            timer.start()
            try:
                with p.stdout:
                    for raw in p.stdout:
                        self._emit("line", {"s": raw.decode("utf-8", errors="replace").rstrip("\n")})
                rc = p.wait()
            finally:
                timer.cancel()
                if p.poll() is None:
                    p.kill()
        return self._emit("done", {"rc": rc})


def _shell():
    return os.path.basename(os.environ.get("SHELL") or "sh")


# ------------------------------------------------------------ the process
def _die(msg, code=1):
    print("spark forge: " + msg, file=sys.stderr, flush=True)
    return code


def _wait_lan_ip(foreground):
    """At login the network may not be up yet; a unit waits, a person does not."""
    ip = lan_ip()
    tries = 60 if foreground else 1
    while not ip and tries > 1:
        time.sleep(5)
        tries -= 1
        ip = lan_ip()
    return ip


def _host_port(cfg, args, foreground):
    host = port = ""
    if "--host" in args:
        i = args.index("--host")
        host = args[i + 1] if i + 1 < len(args) else ""
    if "--port" in args:
        i = args.index("--port")
        port = args[i + 1] if i + 1 < len(args) else ""
    host = host or cfg.forge_host or _wait_lan_ip(foreground)
    try:
        port = int(port) if port else cfg.forge_port
    except ValueError:
        port = 0
    return host, port


def _url_of(cfg):
    """The URL the FORGE has or would have here."""
    u = forge_url()
    if u:
        return u
    return "http://%s:%d" % (cfg.forge_host or lan_ip() or "<lan-ip>", cfg.forge_port)


def _misconfigured(cfg):
    """One line saying why no upstream can ever answer, or ''. Nothing
    has to be up: a serve-url, a base URL, or an engine with a model on
    disk is enough to start."""
    if cfg.base_url or wire.serve_url():
        return ""
    try:
        engine.resolve_for_spawn(cfg)
    except engine.EngineError as e:
        return "no model to front: %s" % e
    return ""


def _write_url(url):
    state_dir()
    fd = os.open(FORGE_URL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(url + "\n")


def _pid():
    try:
        with open(FORGE_PID, encoding="utf-8") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return 0


def forget():
    for p in (FORGE_URL_FILE, FORGE_PID):
        try:
            os.remove(p)
        except OSError:
            pass


def cmd_foreground(args):
    cfg = config.load()
    host, port = _host_port(cfg, args, True)
    if not host:
        return _die("no LAN address to bind -- set SPARK_FORGE_HOST", EX_CONFIG)
    if host == "0.0.0.0":
        return _die("0.0.0.0 is every interface -- bind the one address the LAN should reach (--host ADDR)", EX_CONFIG)
    if not (0 < port < 65536):
        return _die("bad port", EX_CONFIG)
    why = _misconfigured(cfg)
    if why:
        return _die(why + " -- ./bootstrap.sh, or spark serve", EX_CONFIG)
    ensure_token(cfg)
    url = "http://%s:%d" % (host, port)
    _write_url(url)
    try:
        srv = ForgeServer((host, port), cfg, url)
    except OSError as e:
        forget()
        return _die("cannot bind %s: %s" % (url, e.strerror or e))
    state_dir()
    with open(FORGE_PID, "w", encoding="utf-8") as f:
        f.write("%d\n" % os.getpid())

    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # bin/spark sets SIGPIPE back to SIG_DFL so `spark ... | head` ends
    # quietly; a server must outlive a browser that hangs up mid-write.
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    log("start %s pid %d" % (url, os.getpid()))
    say("%s forge -- serving at %s (token required)" % (MARK, url))
    try:
        srv.serve_forever()
    finally:
        log("stop")
        srv.server_close()
        forget()
    return 0


def cmd_start(args):
    cfg = config.load()
    host, port = _host_port(cfg, args, False)
    if not host:
        return _die("no LAN address to bind -- set SPARK_FORGE_HOST", EX_CONFIG)
    if host == "0.0.0.0":
        return _die("0.0.0.0 is every interface -- bind the one address the LAN should reach (--host ADDR)", EX_CONFIG)
    why = _misconfigured(cfg)
    if why:
        return _die(why + " -- ./bootstrap.sh, or spark serve", EX_CONFIG)
    url = "http://%s:%d" % (host, port)
    if wire.forge_health(url) not in (None, "down"):
        say("%s forge -- already running at %s" % (MARK, url))
        return 0
    state_dir()
    lock = os.open(FORGE_LOCK, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock)
        return _die("another `spark forge start` is running right now")
    try:
        if os.path.exists(FORGE_LOG) and os.path.getsize(FORGE_LOG) > LOG_MAX:
            os.replace(FORGE_LOG, FORGE_LOG + ".1")
    except OSError:
        pass
    out = os.open(FORGE_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    cmd = [sys.executable, os.path.join(REPO, "bin", "spark"), "forge", "--foreground", "--host", host, "--port", str(port)]
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    finally:
        os.close(out)
        os.close(lock)
    quiet = cfg.quiet_start

    class Exited(Exception):
        pass

    def probe():
        if wire.forge_health(url) not in (None, "down"):
            return True
        if p.poll() is not None:
            raise Exited()
        return False

    try:
        up = wait_ready("" if quiet else "starting", probe, 30, 0.5)
    except Exited:
        return _die("exited %d while starting:\n%s" % (p.returncode, "\n".join(log_tail(5))), p.returncode or 1)
    if not up:
        engine.terminate([p.pid])
        return _die("no answer in 30 s -- stopped; the log tail:\n" + "\n".join(log_tail(5)))
    if quiet:
        say("%s forge -- ready (pid %d) at %s" % (MARK, p.pid, url))
        return 0
    sys.stdout.write(" ready (pid %d)\n" % p.pid)
    say("%s forge -- %s/login   (spark forge --print-url for the token)" % (MARK, url))
    return 0


def cmd_stop(args):
    cfg = config.load()
    force = "--force" in args
    st = engine.forge_service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg, "forge") == "system":
            return _die("the FORGE is a LaunchDaemon (spark headless on) -- sudo launchctl bootout %s stops it; spark headless off puts it back under your login" % engine.service_target(cfg, "forge"))
        if not force:
            mgr = "launchd" if IS_MAC else "systemd"
            return _die("%s would bring the FORGE straight back -- spark forge stop --force stops it; spark forge off keeps it down" % mgr)
        undo = engine.service_stop(False, "forge")
        pid = _pid()
        if pid:
            left = engine.wait_gone([pid], 20)
            if left:
                engine.terminate(left, force=True)
        forget()
        say("%s forge -- stopped; to bring it back: %s" % (MARK, undo))
        return 0
    pid = _pid()
    if not pid:
        forget()
        say("%s forge -- not running" % MARK)
        return 0
    engine.terminate([pid])
    left = engine.wait_gone([pid], 20)
    if left and force:
        engine.terminate(left, force=True)
        left = engine.wait_gone(left, 5)
    if left:
        return _die("pid %d survived SIGTERM -- `spark forge stop --force` sends SIGKILL" % pid)
    forget()
    say("%s forge -- stopped pid %d" % (MARK, pid))
    return 0


def cmd_status(args):
    cfg = config.load()
    url = forge_url()
    fh = wire.forge_health(url) if url else "down"
    if not url:
        say("%s forge -- not running%s" % (MARK, "" if cfg.forge != "off" else " (SPARK_FORGE=off)"))
        say("  spark forge start     (or spark forge on, to keep it running)")
    elif fh in (None, "down"):
        say("%s forge -- forge-url says %s but nothing answers" % (MARK, url))
        say("  spark forge stop      clears it")
    else:
        say("%s forge -- %s/login" % (MARK, url))
        say("  health   ok%s" % ("" if fh.get("upstream") == "ok" else ", upstream %s" % fh.get("upstream")))
        say("  model    %s" % (fh.get("model") or "-"))
    st = engine.forge_service_state(cfg)
    say("  unit     %s (SPARK_FORGE=%s)" % ({"loaded": "always-on", "disabled": "disabled on purpose", "absent": "none (spark forge on installs one)"}[st], cfg.forge))
    tok = cfg.forge_token_file
    if os.path.exists(tok):
        mode = os.stat(tok).st_mode & 0o777
        say("  token    admin %s %s" % (tok, "0600" if mode == 0o600 else "%04o -- chmod 600 it" % mode))
    else:
        say("  token    admin none yet (written at the first start)")
    from . import users
    names = users.list_users()
    say("  users    %d (spark user list)" % len(names) if names else "  users    none yet (spark user add NAME)")
    if os.path.exists(EMBER_TOKEN_FILE):
        say("  !        the v1.3 shared ember-token is no longer accepted -- rm %s" % EMBER_TOKEN_FILE)
    tail = log_tail(3)
    if tail:
        say("  log      " + "\n           ".join(tail))
    return 0


def cmd_print_url(args):
    cfg = config.load()
    if "--user" in args:
        say("%s forge -- user tokens are personal now: spark user add NAME mints one, shown once" % MARK)
        return 2
    url = _url_of(cfg)
    say(url + "/login")
    if "--show-token" in args or sys.stdout.isatty():
        say("token  " + ensure_token(cfg))
    return 0


def cmd_print_client(args):
    """What a peer machine needs: the URL and a personal user. No secret
    ever leaves this box -- the token is shown once at the mint."""
    cfg = config.load()
    url = _url_of(cfg)
    say("SITE_PEER_AI_URL=%s" % url)
    say("here:   spark user add NAME        the token is shown once -- carry it")
    say("there:  spark client %s" % url)
    say("then:   spark user login NAME      paste the token; chats land in your own sealed store here")
    say("the admin token stays on this machine (spark forge --print-url)")
    return 0


def cmd_token(args):
    cfg = config.load()
    flags = set(args)
    if "--user" in flags:
        say("%s forge -- user tokens are personal now: spark user token --new rotates your own" % MARK)
        return 2
    if "--new" not in flags or flags - {"--new"}:
        say(USAGE.rstrip())
        return 2
    path = cfg.forge_token_file
    try:
        os.remove(path)
    except OSError:
        pass
    ensure_token(cfg)
    say("%s forge -- new admin token in %s -- every admin client and browser must log in again (spark forge --print-url)"
        % (MARK, path))
    return 0


def cmd_onoff(sub):
    from . import site
    site.set_keys(_file=SPARK_ENV, SPARK_FORGE=sub)
    rc = site.apply(["spark-forge", "spark.forge"])
    if rc:
        return rc
    return cmd_start([]) if sub == "on" else cmd_stop(["--force"])


def main(argv):
    sub = argv[0] if argv else "status"
    rest = argv[1:]
    if sub in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    if sub == "status":
        return cmd_status(rest)
    if sub == "start":
        return cmd_start(rest)
    if sub == "stop":
        return cmd_stop(rest)
    if sub == "--foreground":
        return cmd_foreground(rest)
    if sub == "--print-url":
        return cmd_print_url(rest)
    if sub == "--print-client":
        return cmd_print_client(rest)
    if sub == "token":
        return cmd_token(rest)
    if sub in ("on", "off"):
        return cmd_onoff(sub)
    say(USAGE.rstrip())
    return 2
