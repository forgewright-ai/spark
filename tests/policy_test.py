#!/usr/bin/env python3
# spark tests/policy_test.py -- every row of forgeserve.ROUTES, proven with
# three callers: nobody, a named user, the admin. `none` opens to all
# three; `user` is 401 bare and opens to both tokens; `admin` is 401
# bare, 403 role to a user, open to the admin. "Opens" is any status but
# 401 and 403: the route's own answer to a minimal request (a 400 for an
# empty body, a 404 for a thread that is not there) is not the door.
# The server runs the way forge_smoke runs it: a throwaway HOME,
# loopback, smoke's stub model. Two rows keep a gate of their own, and
# are asserted here by name: POST /api/login is open, but the bare probe
# has no token to give and a wrong token is that route's own 401; POST
# /api/user/token is a user's own -- the admin has no personal token
# there, 403. Then the negative: a request off the table is 404 with
# any credential.

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SPARK = os.path.join(REPO, "bin", "spark")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "lib"))
import smoke  # noqa: E402  -- the stub llama-server
from spark import forgeserve  # noqa: E402

OPEN = "open"          # any status but 401 and 403
# what stands in for `*` in a pattern: a name no store holds
FILL = {"/static/*": "/static/spark.css", "/api/threads/*": "/api/threads/none",
        "/api/threads/*/append": "/api/threads/none/append", "/api/memory/*": "/api/memory/1"}
# the body a route needs to reach past its own parser: the model's face
# is proxied to the stub, so it says hello; a kept thread is made for
# real, in each caller's own store under this test's throwaway HOME (a
# body is sent on POST alone, so the GET and DELETE rows of the same
# pattern take none)
BODIES = {"/v1/chat/completions": {"messages": [{"role": "user", "content": "hi"}], "stream": False},
          "/api/threads": {"id": "policy-kept"}}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def probe(url, method, path, bearer="", body=None):
    """(status, parsed body or None). A stream (SSE) answers its headers
    and goes on: only the status is read there, and the socket closed."""
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    h = {}
    if bearer:
        h["Authorization"] = "Bearer " + bearer
    data = None
    if method in ("POST", "DELETE"):
        h["X-Spark"] = "1"
    if method == "POST":
        data = json.dumps(body if body is not None else {}).encode()
        h["Content-Type"] = "application/json"
    try:
        c.request(method, path, data, h)
        r = c.getresponse()
        if (r.getheader("Content-Type") or "").startswith("text/event-stream"):
            return r.status, None
        raw = r.read()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, None
    finally:
        c.close()


def raw(url, method, path, data=None, headers=None):
    """(status, headers, bytes) for a body sent as given, never re-encoded."""
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    h = {"X-Spark": "1", "Content-Type": "application/json"} if method == "POST" else {}
    h.update(headers or {})
    try:
        c.request(method, path, data, h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def main():
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + str(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    stub = HTTPServer(("127.0.0.1", 0), smoke.Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    stub_url = "http://127.0.0.1:%d" % stub.server_address[1]

    with tempfile.TemporaryDirectory(prefix="spark-policy-") as tmp:
        home = os.path.join(tmp, "home")
        bins = os.path.join(tmp, "bin")
        state = os.path.join(home, ".local", "state", "spark")
        for d in (home, bins, os.path.join(home, ".config", "spark"), state):
            os.makedirs(d)
        os.chmod(state, 0o700)
        for name in ("launchctl", "systemctl"):
            with open(os.path.join(bins, name), "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(os.path.join(bins, name), 0o755)
        with open(os.path.join(home, ".config", "spark", "soul"), "w") as f:
            f.write("Call yourself Fixture.\n")
        os.chmod(os.path.join(home, ".config", "spark", "soul"), 0o600)
        with open(os.path.join(state, "serve-url"), "w") as f:
            f.write(stub_url + "\n")
        port = free_port()
        url = "http://127.0.0.1:%d" % port
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SPARK_", "XDG_", "SITE_"))}
        env.update({"HOME": home, "XDG_CONFIG_HOME": home + "/.config", "XDG_STATE_HOME": home + "/.local/state",
                    "XDG_DATA_HOME": home + "/.local/share", "PATH": bins + ":" + env.get("PATH", ""),
                    "SPARK_SERVE_HOST": "127.0.0.1", "SPARK_API_KEY": smoke.TOKEN,
                    "SPARK_FORGE_HOST": "127.0.0.1", "SPARK_FORGE_PORT": str(port),
                    "SPARK_NO_APPLY": "1", "SPARK_NO_REFRESH": "1", "SPARK_SERVICE": "none", "SPARK_TIMEOUT": "5",
                    "SITE_NAME": "fixture", "SHELL": "/bin/bash", "TERM": "xterm-256color",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})

        def spark(*args):
            p = subprocess.run([sys.executable, SPARK] + list(args), capture_output=True, text=True, env=env, timeout=60)
            return p.returncode, p.stdout, p.stderr

        print("policy_test: stub llama-server at %s, forge at %s, HOME %s" % (stub_url, url, home))
        p = subprocess.Popen([sys.executable, SPARK, "forge", "--foreground"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 20
        st = 0
        while time.time() < deadline and st != 200:
            try:
                st, _ = probe(url, "GET", "/api/health")
            except OSError:
                st = 0
            if st != 200:
                time.sleep(0.3)
        try:
            ok(st == 200, "--foreground answers /api/health")
            if st != 200:
                p.kill()
                print(p.communicate()[0][-2000:])
                return 1
            admin = open(state + "/forge-token").read().strip()
            rc, out, _ = spark("user", "add", "owner")
            ok(rc == 0 and "this machine is owner" in out, "the box's own account minted and logged in", out)
            rc, out, _ = spark("user", "add", "upol", "--show-token")
            user = next((l.strip() for l in out.splitlines() if len(l.strip()) >= 40 and " " not in l.strip()), "")
            ok(rc == 0 and bool(user), "a named user with a token of its own", out)

            ok(len(forgeserve.ROUTES) >= 30 and set(forgeserve.ROUTES.values()) == {"none", "user", "admin"},
               "ROUTES: %d rows, the three roles" % len(forgeserve.ROUTES))
            for (method, pattern), role in sorted(forgeserve.ROUTES.items()):
                path = FILL.get(pattern, pattern)
                body = BODIES.get(pattern)
                if pattern == "/api/login":
                    # the login's own gate: the credential is the body
                    bare = probe(url, method, path, body={})[0]
                    as_user = probe(url, method, path, body={"token": user})[0]
                    as_admin = probe(url, method, path, body={"token": admin})[0]
                    ok(bare == 401 and as_user == 200 and as_admin == 200,
                       "%s %s (none): a wrong token is its own 401, a right one 200 for both" % (method, pattern),
                       (bare, as_user, as_admin))
                    continue
                bare, _ = probe(url, method, path, body=body)
                as_user, ubody = probe(url, method, path, user, body)
                as_admin, abody = probe(url, method, path, admin, body)
                if pattern == "/api/user/token":
                    # the user's rotation: the token in hand changes here
                    user = (ubody or {}).get("token") or user
                    ok(bare == 401 and as_user == 200 and as_admin == 403
                       and (abody or {}).get("error", {}).get("kind") == "role",
                       "%s %s (user): 401 bare, a user rotates, the admin has no personal token (403)" % (method, pattern),
                       (bare, as_user, as_admin))
                    continue
                if role == "none":
                    ok(bare not in (401, 403) and as_user not in (401, 403) and as_admin not in (401, 403),
                       "%s %s (none): open to all three" % (method, pattern), (bare, as_user, as_admin))
                elif role == "user":
                    ok(bare == 401 and as_user not in (401, 403) and as_admin not in (401, 403),
                       "%s %s (user): 401 bare, open to both tokens" % (method, pattern), (bare, as_user, as_admin))
                else:
                    kind = (ubody or {}).get("error", {}).get("kind")
                    ok(bare == 401 and as_user == 403 and kind == "role" and as_admin not in (401, 403),
                       "%s %s (admin): 401 bare, 403 role to a user, open to the admin" % (method, pattern),
                       (bare, as_user, kind, as_admin))
            # POST /api/threads made its kept thread for real: once in the
            # user's own store, once in the box account's, both under HOME
            ok(all(os.path.isfile(os.path.join(state, "users", n, "kept", "policy-kept.sealed")) for n in ("upol", "owner")),
               "POST /api/threads kept one thread in each caller's own store, under this test's HOME")
            # off the table: 404 with any credential, and no method borrows another's row
            for method, path in (("GET", "/api/nope"), ("POST", "/api/health"), ("GET", "/api/login"),
                                 ("DELETE", "/api/memory"), ("GET", "/static/a/b"), ("GET", "/api/threads/x/y"),
                                 ("POST", "/api/threads/x"), ("GET", "/nope")):
                sts = [probe(url, method, path, cred)[0] for cred in ("", user, admin)]
                ok(sts == [404, 404, 404], "%s %s is off the table: 404 to all three" % (method, path), sts)

            # no login, no 500: a lone surrogate in the token is a wrong
            # token (the 1 s cost, counted), and a body nested past the
            # parser's stack is a 400 -- neither skips the gates as a crash
            def failed_logins():
                with open(os.path.join(state, "forge.log"), encoding="utf-8", errors="replace") as f:
                    return f.read().count(" login failed")
            before = failed_logins()
            t0 = time.time()
            st, _, body = raw(url, "POST", "/api/login", b'{"token": "\\ud800"}')
            took = time.time() - t0
            time.sleep(0.2)
            ok(st == 401 and took >= 1.0 and failed_logins() == before + 1,
               "a lone surrogate token -> 401 after >= 1 s, counted as a wrong login (not a 500)",
               (st, round(took, 2), body[:80]))
            for path, hdr in (("/api/login", {}), ("/api/memory", {"Authorization": "Bearer " + user})):
                st, _, body = raw(url, "POST", path, b"[" * 200000, hdr)
                ok(st == 400 and json.loads(body)["error"]["kind"] == "bad",
                   "POST %s with 200k nested [ -> 400 the body is not JSON (not a 500)" % path, (st, body[:80]))

            # a name holds SESSIONS_PER_NAME logins: the oldest goes past it
            cookies = []
            for _ in range(forgeserve.SESSIONS_PER_NAME + 1):
                st, h, _ = raw(url, "POST", "/api/login", json.dumps({"token": user}).encode())
                cookies.append((h.get("Set-Cookie") or "").split(";")[0])
            alive = [raw(url, "GET", "/api/me", headers={"Cookie": c})[0] for c in cookies]
            ok(alive == [401] + [200] * forgeserve.SESSIONS_PER_NAME,
               "%d logins of one name: the oldest session dropped, the newest %d open"
               % (len(cookies), forgeserve.SESSIONS_PER_NAME), alive)

            # MAX_CONNECTIONS at once: one more is a 503 at once, and the
            # slots come back when the idle sockets go
            idle = []
            for _ in range(forgeserve.MAX_CONNECTIONS):
                s = socket.create_connection(("127.0.0.1", port), timeout=10)
                idle.append(s)
            time.sleep(0.5)
            try:
                st, h, body = raw(url, "GET", "/api/health")
            except OSError as e:
                st, h, body = 0, {}, repr(e).encode()
            ok(st == 503 and json.loads(body)["error"]["kind"] == "busy" and h.get("Retry-After") == "5",
               "%d idle connections held: one more -> 503 busy, answered at once" % forgeserve.MAX_CONNECTIONS,
               (st, body[:80]))
            for s in idle:
                s.close()
            end = time.time() + 20
            while time.time() < end:
                try:
                    st = raw(url, "GET", "/api/health")[0]
                except OSError:
                    st = 0
                if st == 200:
                    break
                time.sleep(0.2)
            ok(st == 200, "the idle connections gone, the server answers again", st)

            # EVENTS_PER_USER live streams for one requester: one more is 429
            rc, out, _ = spark("user", "add", "ustream", "--show-token")
            stream_tok = next((l.strip() for l in out.splitlines() if len(l.strip()) >= 40 and " " not in l.strip()), "")
            u = urllib.parse.urlsplit(url)
            streams, sts, kind = [], [], ""
            for _ in range(forgeserve.EVENTS_PER_USER + 1):
                c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
                c.request("GET", "/api/events", None, {"Authorization": "Bearer " + stream_tok})
                r = c.getresponse()
                sts.append(r.status)
                if r.status != 200:
                    kind = json.loads(r.read())["error"]["kind"]
                streams.append((c, r))      # the response owns the socket: keep both
            ok(sts == [200] * forgeserve.EVENTS_PER_USER + [429] and kind == "busy",
               "%d live /api/events streams for one user, one more -> 429 busy" % forgeserve.EVENTS_PER_USER, sts)
            ok(probe(url, "GET", "/api/me", stream_tok)[0] == 200, "the user's other routes still answer")
            for c, r in streams:
                r.close()
                c.close()
        finally:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                ok(False, "foreground forge ignored SIGTERM")
    stub.shutdown()
    print("policy_test: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
