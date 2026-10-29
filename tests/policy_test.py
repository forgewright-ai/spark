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
import shutil
import signal
import socket
import ssl
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
        "/api/threads/*/append": "/api/threads/none/append", "/api/memory/*": "/api/memory/1",
        "/api/users/*": "/api/users/none"}
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


TLS_CTX = None            # set for the pass over TLS: the scratch root is the one anchor


def conn(u, timeout=30):
    """An HTTP connection to the split url, or an HTTPS one verifying
    against TLS_CTX when the url says https."""
    if u.scheme == "https":
        return http.client.HTTPSConnection(u.hostname, u.port, timeout=timeout, context=TLS_CTX)
    return http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)


def probe(url, method, path, bearer="", body=None):
    """(status, parsed body or None). A stream (SSE) answers its headers
    and goes on: only the status is read there, and the socket closed."""
    u = urllib.parse.urlsplit(url)
    c = conn(u)
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
    c = conn(u)
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

    ok(forgeserve.http_origin("http://LOCALHOST") == forgeserve.http_origin("http://localhost:80")
       == ("http", "localhost", 80), "origin comparison uses the default HTTP port and ignores hostname case")
    ok(forgeserve.http_origin("https://localhost") == ("https", "localhost", 443),
       "HTTPS is a distinct origin with its own default port")
    for origin in ("http://localhost:", "http://localhost\t", "http://local\nhost", "http://localhost\\path"):
        ok(forgeserve.http_origin(origin) is None, "origin parser rejects empty ports and controls", repr(origin))

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
            # the acting rows: every admin POST row and nothing else, each
            # named in contract 9 (forge_smoke proves the boundary itself)
            acting = {k for k, v in forgeserve.ROUTES.items() if v == "admin" and k[0] in ("POST", "DELETE")}
            ok(set(forgeserve.ACTS) == acting, "ACTS is every admin POST and DELETE row of ROUTES, and nothing else",
               sorted(acting ^ set(forgeserve.ACTS)))
            with open(os.path.join(REPO, "docs/REFERENCE.md"), encoding="utf-8") as f:
                claude = f.read()
            missing = ["%s %s" % k for k in forgeserve.ACTS if "`%s %s`" % k not in claude]
            ok(not missing and "forgeserve.ACTS" in claude, "docs/REFERENCE.md contract 9 names every acting row and the tuple", missing)
            bare_codes = {}             # what each row answers nobody: the pass over TLS must agree
            for (method, pattern), role in sorted(forgeserve.ROUTES.items()):
                path = FILL.get(pattern, pattern)
                body = BODIES.get(pattern)
                if pattern == "/api/login":
                    # the login's own gate: the credential is the body
                    bare = probe(url, method, path, body={})[0]
                    bare_codes[(method, pattern)] = bare
                    as_user = probe(url, method, path, body={"token": user})[0]
                    as_admin = probe(url, method, path, body={"token": admin})[0]
                    ok(bare == 401 and as_user == 200 and as_admin == 200,
                       "%s %s (none): a wrong token is its own 401, a right one 200 for both" % (method, pattern),
                       (bare, as_user, as_admin))
                    continue
                bare, _ = probe(url, method, path, body=body)
                bare_codes[(method, pattern)] = bare
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
            # a method off the table is the same 404, never the stdlib's
            # 501; HEAD is no GET in disguise: no body, and no stream opens
            for method, path in (("HEAD", "/"), ("HEAD", "/api/health"), ("HEAD", "/api/events"),
                                 ("OPTIONS", "/api/health"), ("OPTIONS", "*"), ("PUT", "/api/threads"),
                                 ("PATCH", "/api/memory"), ("TRACE", "/"), ("BREW", "/api/me")):
                sts = []
                for cred in ("", user, admin):
                    h = {"Authorization": "Bearer " + cred} if cred else {}
                    t0 = time.time()
                    st, hd, body = raw(url, method, path, headers=h)
                    sts.append((st, (hd.get("Content-Type") or "").split(";")[0], len(body), time.time() - t0 < 5))
                ok(all(s[0] == 404 and s[1] == "application/json" and s[3] and (s[2] == 0 if method == "HEAD" else s[2] > 0)
                       for s in sts),
                   "%s %s is off the table: 404 to all three%s" % (method, path, ", no body" if method == "HEAD" else ""),
                   sts)

            # Send header pairs verbatim: a dict cannot exercise duplicate
            # Host/Origin fields, and http.client normally adds Host itself.
            def header_request(method, path, pairs, data=None):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    c.putrequest(method, path, skip_host=True)
                    for k, v in pairs:
                        c.putheader(k, v)
                    if data is not None:
                        c.putheader("Content-Type", "application/json")
                        c.putheader("Content-Length", str(len(data)))
                    c.endheaders(data)
                    r = c.getresponse()
                    return r.status, dict(r.getheaders()), r.read()
                finally:
                    c.close()

            authority = "127.0.0.1:%d" % port
            for hosts in ([], ["evil.example"], [authority, authority],
                          [authority, "evil.example"], [authority + "/"],
                          ["name@" + authority], [authority + ",evil.example"]):
                for method, path in (("GET", "/"), ("GET", "/api/health"),
                                     ("GET", "/api/me"), ("POST", "/v1/chat/completions")):
                    pairs = [("Host", h) for h in hosts] + [("Authorization", "Bearer " + admin)]
                    st, _, _ = header_request(method, path, pairs)
                    ok(st == 400, "%s %s rejects invalid or duplicate Host %r" % (method, path, hosts), st)

            body = json.dumps({"token": admin}).encode()
            base = [("Host", authority), ("X-Spark", "1")]
            bad_origins = ["https://" + authority, "ftp://" + authority,
                           "//" + authority, url + "/", url + "/path",
                           url + "?", url + "#", "http://name@" + authority,
                           "http://127.0.0.1:0", "http://127.0.0.1:65536",
                           "null", "", url + " " + url, "http://[broken"]
            for origin in bad_origins:
                st, hd, _ = header_request("POST", "/api/login", base + [("Origin", origin)], body)
                ok(st == 403 and "Set-Cookie" not in hd,
                   "login rejects malformed or different Origin %r without a session" % origin, st)
            for origins in ([url, url], [url, "https://" + authority]):
                st, hd, _ = header_request("POST", "/api/login", base + [("Origin", o) for o in origins], body)
                ok(st == 403 and "Set-Cookie" not in hd, "login rejects duplicate Origin", st)
            forwarded = [("Forwarded", 'proto=https;host="evil.example"'),
                         ("X-Forwarded-Proto", "https"), ("X-Forwarded-Host", "evil.example")]
            for origin, expected in ((url, 200), ("https://" + authority, 403)):
                st, _, _ = header_request("POST", "/api/login", base + forwarded + [("Origin", origin)], body)
                ok(st == expected, "forwarding headers cannot change the HTTP origin", st)
            st, _, _ = header_request("POST", "/api/login", base, body)
            ok(st == 200, "originless login remains supported", st)
            local = "localhost:%d" % port
            st, hd, _ = header_request("POST", "/api/login",
                                      [("Host", local.upper()), ("X-Spark", "1"),
                                       ("Origin", "http://" + local)], body)
            ok(st == 200, "same-origin login accepts a case-insensitive local hostname", st)
            cookie = hd.get("Set-Cookie", "").split(";")[0]
            for credential in (("Authorization", "Bearer " + admin), ("Cookie", cookie)):
                st, _, _ = header_request("DELETE", "/api/memory/1",
                                          base + [credential, ("Origin", "https://" + authority)])
                ok(st == 403, "API writes reject the wrong scheme with bearer or cookie", st)

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
        # v1.91: the same table over TLS. A scratch pair from the openssl
        # binary (skipped with a notice where there is none); every row as
        # nobody answers what it answered over plain HTTP, the off-table
        # requests are the same 404, and the two gates only TLS has hold: the
        # listener changes the wire, never the policy
        global TLS_CTX
        exe = shutil.which("openssl")
        if not exe:
            print("  skip the route table over TLS   (no openssl binary here)")
        else:
            d = os.path.join(home, "pair")
            smoke.mint_pair(exe, d, {"leaf": (["fixture.local"], ["127.0.0.1"])}, ["fixture.local"])
            tport = free_port()
            turl = "https://127.0.0.1:%d" % tport
            tenv = dict(env, SPARK_FORGE_PORT=str(tport), SPARK_FORGE_CERT=os.path.join(d, "leaf.crt"),
                        SPARK_FORGE_KEY=os.path.join(d, "leaf.key"))
            TLS_CTX = ssl.create_default_context(cafile=os.path.join(d, "root.crt"))
            p = subprocess.Popen([sys.executable, SPARK, "forge", "--foreground"], env=tenv,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            deadline = time.time() + 20
            st = 0
            while time.time() < deadline and st != 200:
                try:
                    st, _ = probe(turl, "GET", "/api/health")
                except OSError:
                    st = 0
                if st != 200:
                    time.sleep(0.3)
            try:
                ok(st == 200, "--foreground answers /api/health over TLS")
                if st != 200:
                    p.kill()        # a server up but unanswerable would hold communicate() forever
                    print(p.communicate()[0][-2000:])
                else:
                    for (method, pattern), role in sorted(forgeserve.ROUTES.items()):
                        path = FILL.get(pattern, pattern)
                        body = {} if pattern == "/api/login" else BODIES.get(pattern)
                        got = probe(turl, method, path, body=body)[0]
                        ok(got == bare_codes.get((method, pattern)), "%s %s over TLS answers nobody as over HTTP (%s)" % (method, pattern, got),
                           (got, bare_codes.get((method, pattern))))
                    for method, path in (("GET", "/api/nope"), ("HEAD", "/"), ("OPTIONS", "*"), ("POST", "/api/health")):
                        st, hd, body = raw(turl, method, path)
                        ok(st == 404 and (hd.get("Content-Type") or "").startswith("application/json"),
                           "%s %s over TLS is off the table: 404" % (method, path), st)
                    admin = open(state + "/forge-token").read().strip()
                    st, hd, _ = raw(turl, "POST", "/api/login", json.dumps({"token": admin}).encode(), {"Origin": turl})
                    ok(st == 200 and "; Secure" in hd.get("Set-Cookie", ""), "login over TLS with its own origin: 200, a Secure cookie", (st, hd.get("Set-Cookie", "")[-30:]))
                    # the rotation re-sets the 90-day cookie: Secure there too (v1.99)
                    st, hd, body = raw(turl, "POST", "/api/user/token", b"{}", {"Origin": turl, "Authorization": "Bearer " + user})
                    user = (json.loads(body or b"{}") or {}).get("token") or user
                    ok(st == 200 and "; Secure" in hd.get("Set-Cookie", ""), "a token rotation over TLS: its cookie is Secure as the login's is", (st, hd.get("Set-Cookie", "")[-30:]))
                    st, _, _ = raw(turl, "POST", "/api/login", json.dumps({"token": admin}).encode(), {"Origin": "http://127.0.0.1:%d" % tport})
                    ok(st == 403, "an http Origin on the https page is refused (403)", st)
                    st, hd, _ = raw(turl, "GET", "/", headers={"Host": "fixture.local:%d" % tport})
                    ok(st == 200 and hd.get("Strict-Transport-Security") == "max-age=604800", "a name the certificate carries: served, HSTS one week", (st, hd.get("Strict-Transport-Security")))
                    st, hd, _ = raw(turl, "GET", "/")
                    ok(st == 200 and "Strict-Transport-Security" not in hd, "by address: no HSTS", (st, hd.get("Strict-Transport-Security")))
            finally:
                TLS_CTX = None
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    ok(False, "foreground forge over TLS ignored SIGTERM")
    stub.shutdown()
    print("policy_test: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
