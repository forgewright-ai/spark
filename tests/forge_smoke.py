#!/usr/bin/env python3
# spark tests/forge_smoke.py -- `spark forge` against smoke.py's stub
# llama-server, hermetic: loopback only, a throwaway HOME, stub service
# managers. The forge's upstream resolves through a serve-url file that
# names the stub, so no engine and no model are needed.

import http.client
import io
import json
import os
import signal
import socket
import struct
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
import smoke  # noqa: E402  -- the stub llama-server

SEEN = {}                 # what the stub saw last: headers and body


class Peek(smoke.Stub):
    """smoke's stub, remembering the request it answered."""

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        SEEN["auth"] = self.headers.get("Authorization", "")
        SEEN["body"] = json.loads(raw or b"{}")
        msgs = SEEN["body"].get("messages") or [{}]
        if SEEN["body"].get("stream") and "dripfeed" in (msgs[-1].get("content") or ""):
            return self.drip()
        self.rfile = io.BytesIO(raw)
        smoke.Stub.do_POST(self)

    def drip(self):
        """One letter at a time, slowly, so a client can hang up
        mid-answer; the pipe breaking when it does is the point."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for _ in range(40):
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": "a"}}]}) + "\n\n").encode())
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def req(url, method, path, body=None, headers=None, timeout=10):
    """(status, headers, bytes) over one HTTP/1.0-friendly connection; a
    Host header given here replaces the automatic one."""
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    try:
        c.request(method, path, data, h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def sse(raw):
    """[(event, data)] of an SSE body; data parsed as JSON when it is."""
    out = []
    for block in raw.decode("utf-8", errors="replace").split("\n\n"):
        ev, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            d = "\n".join(data)
            try:
                d = json.loads(d)
            except ValueError:
                pass
            out.append((ev, d))
    return out


def main():
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + str(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    stub = HTTPServer(("127.0.0.1", 0), Peek)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    stub_url = "http://127.0.0.1:%d" % stub.server_address[1]

    with tempfile.TemporaryDirectory(prefix="spark-forge-") as tmp:
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

        def spark(*args, extra=None, stdin="", timeout=60):
            e = dict(env)
            e.update(extra or {})
            p = subprocess.run([sys.executable, SPARK] + list(args), input=stdin, capture_output=True, text=True, env=e, timeout=timeout)
            return p.returncode, p.stdout, p.stderr

        print("forge_smoke: stub llama-server at %s, forge at %s, HOME %s" % (stub_url, url, home))

        # refusals before anything binds
        rc, out, err = spark("forge", "--foreground", "--host", "0.0.0.0")
        ok(rc == 78 and "0.0.0.0" in err, "--foreground --host 0.0.0.0 -> 78", err)
        rc, out, err = spark("forge", "-h")
        ok(rc == 0 and out.splitlines()[0] == "spark forge -- the served agent", "spark forge -h signs (contract 8)", out)
        ok(all(len(l) <= 80 for l in out.splitlines()), "usage fits 80 columns")
        rc, out, _ = spark("forge")
        ok(rc == 0 and "not running" in out, "status before start: not running", out)
        rc, out, _ = spark("forge", "stop")
        ok(rc == 0 and "not running" in out, "stop before start: not running, exit 0", out)

        # the server, in the foreground
        p = subprocess.Popen([sys.executable, SPARK, "forge", "--foreground"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 20
        st = 0
        while time.time() < deadline and st != 200:
            try:
                st, _, raw = req(url, "GET", "/api/health", timeout=2)
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
            h = json.loads(raw)
            ok(h.get("forge") is True and h.get("status") == "ok" and h.get("name") == "fixture", "health: forge true, name", h)
            ok(h.get("model") == "stub-7b-q4" and h.get("upstream") == "ok", "health: the stub's model, upstream ok", h)
            ok(h.get("models") == {"spark": "loaded", "ember": "loaded"}, "health: models lists both roles, loaded", h)
            tok_path = state + "/forge-token"
            ok(os.path.isfile(tok_path) and oct(os.stat(tok_path).st_mode & 0o777) == "0o600", "forge-token 0600")
            token = open(tok_path).read().strip()
            etok_path = state + "/ember-token"
            ok(os.path.isfile(etok_path) and oct(os.stat(etok_path).st_mode & 0o777) == "0o600", "ember-token 0600")
            utoken = open(etok_path).read().strip()
            ok(utoken and utoken != token, "the two tokens differ")
            ok(open(state + "/forge-url").read().strip() == url, "forge-url written")
            ok(int(open(state + "/forge.pid").read()) == p.pid, "forge.pid is the foreground pid")
            bearer = {"Authorization": "Bearer " + token}
            ubearer = {"Authorization": "Bearer " + utoken}

            # auth
            st, h, raw = req(url, "GET", "/api/check")
            ok(st == 401 and h.get("Cache-Control") == "no-store", "/api/check bare -> 401, no-store", (st, h))
            st, _, _ = req(url, "GET", "/api/check", headers={"Authorization": "Bearer nope"})
            ok(st == 401, "wrong bearer -> 401")
            t0 = time.time()
            st, _, _ = req(url, "POST", "/api/login", {"token": "nope"})
            ok(st == 401 and time.time() - t0 >= 1.0, "wrong login -> 401 after >= 1 s (%.1f s)" % (time.time() - t0))
            st, h, raw = req(url, "POST", "/api/login", {"token": token})
            sc = h.get("Set-Cookie", "")
            ok(st == 200 and sc.startswith("spark_forge=") and "HttpOnly" in sc and "SameSite=Strict" in sc and "Max-Age=7776000" in sc,
               "right login -> cookie HttpOnly, SameSite=Strict, 90 days", sc)
            cookie = {"Cookie": sc.split(";")[0]}
            st, _, raw = req(url, "GET", "/api/me", headers=cookie)
            d = json.loads(raw)
            ok(st == 200 and d.get("role") == "admin" and d.get("name") == "fixture" and d.get("version"),
               "/api/me with the admin cookie: role admin, name, version", raw[:100])
            st, _, raw = req(url, "GET", "/api/me", headers=bearer)
            ok(st == 200 and json.loads(raw).get("role") == "admin", "/api/me with the admin bearer: role admin", raw[:100])
            with open(state + "/check.json", "w") as f:
                json.dump({"ts": int(time.time()) - 5, "name": "fixture", "version": "0", "counts": {"ok": 1, "fail": 0, "warn": 0, "na": 0},
                           "rows": [{"category": "SOFTWARE", "status": "ok", "name": "x", "value": "y", "remedy": ""}]}, f)
            st, h, raw = req(url, "GET", "/api/check", headers=cookie)
            d = json.loads(raw)
            ok(st == 200 and d["counts"]["ok"] == 1 and isinstance(d.get("age"), int), "cookie reads /api/check (with age)", (st, raw[:100]))
            st, _, raw = req(url, "GET", "/api/stats?days=7", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and "tg_mean" in d and "baseline" in d and "running" in d, "bearer reads /api/stats", raw[:100])
            st, _, _ = req(url, "GET", "/api/stats?days=2", headers=bearer)
            ok(st == 400, "days=2 -> 400")
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=bearer)
            ok(st == 403, "POST without X-Spark -> 403", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Host": "evil.example:1"}))
            ok(st == 400, "wrong Host -> 400", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Origin": "http://evil.example"}))
            ok(st == 403, "foreign Origin -> 403", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Origin": url}))
            ok(st == 202, "POST /api/check/refresh with X-Spark and a same-host Origin -> 202", st)
            st, _, _ = req(url, "POST", "/api/check/refresh", {}, headers=dict(bearer, **{"X-Spark": "1", "Host": "localhost:%d" % port}))
            ok(st == 202, "Host localhost:PORT is this machine", st)
            st, _, _ = req(url, "GET", "/api/nope", headers=bearer)
            ok(st == 404, "unknown /api route -> 404")

            # the OpenAI-compatible face: identity in, api-token on
            SEEN.clear()
            st, h, raw = req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "capital of France?"}], "stream": False}, headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and "Paris" in d["choices"][0]["message"]["content"], "non-stream chat: the stub's JSON comes back", raw[:200])
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0]
            ok(sys0.get("role") == "system" and "Call yourself Fixture." in sys0.get("content", ""), "the stub saw the soul in messages[0]", str(sys0)[:200])
            ok("You are spark, the assistant at" in sys0.get("content", ""), "no client system message: the forge's own is inserted", str(sys0)[:200])
            ok(SEEN.get("body", {}).get("model") == "ember", "no model in the request: ember goes upstream", SEEN.get("body", {}).get("model"))
            ok(SEEN.get("auth") == "Bearer " + smoke.TOKEN, "the api-token went upstream, not the forge token", SEEN.get("auth"))
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"messages": [{"role": "system", "content": "PREFIX-MARK"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            c = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(st == 200 and c.startswith("Call yourself Fixture.") and c.endswith("PREFIX-MARK"), "a client prefix comes after the identity", c[:200])
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"model": "spark", "messages": [{"role": "system", "content": "LINE-MARK"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            c = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(st == 200 and SEEN.get("body", {}).get("model") == "spark" and c == "LINE-MARK" and "Fixture" not in json.dumps(SEEN.get("body", {})),
               "model spark: passed through, the client's system message untouched, no identity", c[:200])
            SEEN.clear()
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"model": "ember", "messages": [{"role": "system", "content": "PREFIX-MARK"}, {"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            c = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(st == 200 and SEEN.get("body", {}).get("model") == "ember" and c.startswith("Call yourself Fixture."),
               "model ember explicit: the identity goes in", c[:200])
            st, h, raw = req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": True}, headers=bearer)
            text = raw.decode()
            ok(st == 200 and h.get("Content-Type", "").startswith("text/event-stream") and text.count("data:") >= 5 and "[DONE]" in text,
               "stream chat: the SSE deltas pass through", text[:200])
            st, _, _ = req(url, "POST", "/v1/chat/completions", {"messages": "x"}, headers=bearer)
            ok(st == 400, "messages not a list -> 400")
            st, _, raw = req(url, "GET", "/v1/models", headers=bearer)
            ok(st == 200 and "stub-7b-q4" in raw.decode(), "/v1/models proxied", raw[:100])

            # the monitor
            st, _, raw = req(url, "GET", "/api/bar", headers=bearer, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and "line" in d and "#[" not in d["line"], "/api/bar has a line without tmux sequences", raw[:200])
            st, _, raw = req(url, "GET", "/api/config", headers=bearer, timeout=30)
            d = json.loads(raw)

            def keys(x, acc):
                if isinstance(x, dict):
                    for k, v in x.items():
                        acc.append(k)
                        keys(v, acc)
                elif isinstance(x, list):
                    for v in x:
                        keys(v, acc)
                return acc
            ks = keys(d, [])
            ok(st == 200 and "themes" in d and "models" in d and "effective" in d, "/api/config: themes, models, effective", raw[:200])
            ok(not [k for k in ks if "TOKEN" in k or "KEY" in k], "/api/config names no *KEY* or *TOKEN*", [k for k in ks if "TOKEN" in k or "KEY" in k])
            ok(token not in raw.decode() and smoke.TOKEN not in raw.decode(), "/api/config carries no token value")
            st, _, raw = req(url, "GET", "/api/theme", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and d["name"] == "none" and d["palette"] is None and isinstance(d["palettes"], list), "/api/theme", raw[:100])
            st, _, raw = req(url, "GET", "/api/serve", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and d["url"] == stub_url and d["health"] == "ok" and d["model"] == "stub-7b-q4", "/api/serve sees the upstream", raw[:200])
            st, _, raw = req(url, "GET", "/api/gpu", headers=bearer)
            ok(st == 200 and isinstance(json.loads(raw), dict), "/api/gpu")
            st, _, raw = req(url, "GET", "/api/bench", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and "now" in d and "baseline" in d and "tune" in d, "/api/bench", raw[:100])
            # the request line lands after the response left (it carries the
            # time taken), and the server is threaded: give it a moment
            for _ in range(20):
                st, _, raw = req(url, "GET", "/api/log?n=3", headers=bearer)
                d = json.loads(raw)
                if d.get("lines") and " GET /api/bench 200 " in d["lines"][-1]:
                    break
                time.sleep(0.1)
            ok(st == 200 and len(d["lines"]) == 3 and " GET /api/bench 200 " in d["lines"][-1], "/api/log tails forge.log", d)
            lg = open(state + "/forge.log").read()
            ok(oct(os.stat(state + "/forge.log").st_mode & 0o777) == "0o600" and token not in lg and smoke.TOKEN not in lg, "forge.log 0600, no token in it")
            ok("login failed" in lg and "wrong bearer" in lg, "forge.log has the login events", lg[-300:])
            # events: the first bytes carry the snapshot
            u = urllib.parse.urlsplit(url)
            c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
            c.request("GET", "/api/events", None, bearer)
            r = c.getresponse()
            head = ""
            while "event: serve" not in head and len(head) < 4000:
                line = r.readline().decode()
                if not line:
                    break
                head += line
            c.close()
            ok(r.status == 200 and "event: check" in head and "event: serve" in head, "/api/events opens with check and serve", head[:200])
            # a browser that hangs up mid-stream must not kill the server
            # (bin/spark sets SIGPIPE to SIG_DFL for pipes; the forge ignores it)
            import socket as _socket
            c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
            c.request("POST", "/api/chat", json.dumps({"text": "count"}).encode(),
                      dict(bearer, **{"X-Spark": "1", "Origin": url, "Content-Type": "application/json"}))
            sk = c.sock
            r = c.getresponse()
            r.read(1)
            sk.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER,
                          __import__("struct").pack("ii", 1, 0))
            sk.close()
            time.sleep(1.0)
            st, _, raw = req(url, "GET", "/api/health")
            ok(st == 200 and b"forge" in raw, "the forge outlives a client that hung up mid-stream", st)
            for f in __import__("glob").glob(state + "/threads/*.jsonl"):
                os.remove(f)  # the hung-up chat's thread; later cases start clean
            # the header's food: /api/health names each role's model
            st, _, raw = req(url, "GET", "/api/health")
            hj = json.loads(raw)
            ok(st == 200 and hj.get("roles", {}).get("spark") and hj.get("roles", {}).get("ember"),
               "/api/health carries roles with each model's stem", hj.get("roles"))
            st, _, raw = req(url, "POST", "/api/chat", {"text": "count"},
                             headers=dict(bearer, **{"X-Spark": "1", "Origin": url, "Content-Type": "application/json"}), timeout=30)
            dn = [d for e, d in sse(raw) if e == "done"]
            ok(st == 200 and dn and dn[0].get("model") == hj["roles"]["ember"],
               "the chat's done event names the ember's model", dn)
            for f in __import__("glob").glob(state + "/threads/*.jsonl"):
                os.remove(f)

            # the page, when the sibling has written it
            if os.path.isfile(os.path.join(REPO, "lib", "spark", "forge", "index.html")):
                st, h, raw = req(url, "GET", "/")
                ok(st == 200 and h.get("Content-Type", "").startswith("text/html") and h.get("Content-Security-Policy") == "default-src 'self'"
                   and h.get("X-Frame-Options") == "DENY" and "ETag" in h, "GET / is the page with CSP", (st, h))
                st, _, _ = req(url, "GET", "/", headers={"If-None-Match": h["ETag"]})
                ok(st == 304, "ETag round trip -> 304")
                st, _, _ = req(url, "GET", "/login")
                ok(st == 200, "/login is the page too")
            st, _, _ = req(url, "GET", "/static/../__init__.py")
            ok(st == 404, "no path traversal under /static/", st)
            st, _, _ = req(url, "GET", "/static/nope.js")
            ok(st == 404, "unknown static name -> 404")

            # the standalone face: manifest, favicon, the drawn touch icon
            # (the two files ride with the page; the icon is always there)
            if os.path.isfile(os.path.join(REPO, "lib", "spark", "forge", "manifest.webmanifest")):
                st, h, raw = req(url, "GET", "/manifest.webmanifest")
                d = {}
                try:
                    d = json.loads(raw)
                except ValueError:
                    pass
                ok(st == 200 and h.get("Content-Type", "").startswith("application/manifest+json")
                   and d.get("start_url") == "/", "/manifest.webmanifest: 200, its type, start_url /, no token", (st, h, raw[:200]))
                st, _, _ = req(url, "GET", "/manifest.webmanifest", headers={"If-None-Match": h.get("ETag", "")})
                ok(st == 304, "manifest ETag round trip -> 304", st)
            if os.path.isfile(os.path.join(REPO, "lib", "spark", "forge", "favicon.svg")):
                st, h, raw = req(url, "GET", "/static/favicon.svg")
                ok(st == 200 and h.get("Content-Type", "").startswith("image/svg+xml"),
                   "/static/favicon.svg: 200, image/svg+xml, no token", (st, h))
            st, h, raw = req(url, "GET", "/apple-touch-icon.png")
            dims = struct.unpack(">II", raw[16:24]) if len(raw) >= 24 else (0, 0)
            ok(st == 200 and h.get("Content-Type") == "image/png" and raw[:8] == b"\x89PNG\r\n\x1a\n" and dims == (180, 180),
               "/apple-touch-icon.png: 200, a real 180x180 PNG, no token", (st, h.get("Content-Type"), dims))
            st, _, _ = req(url, "GET", "/apple-touch-icon.png", headers={"If-None-Match": h.get("ETag", "")})
            ok(st == 304, "touch icon ETag round trip -> 304", st)


            # the page's food: threads, chat, soul, memory, do, the verb runner
            post = dict(bearer, **{"X-Spark": "1", "Origin": url})
            st, _, raw = req(url, "GET", "/api/threads?n=30", headers=bearer)
            ok(st == 200 and json.loads(raw) == {"threads": []}, "/api/threads: empty at first", raw[:100])
            SEEN.clear()
            st, h, raw = req(url, "POST", "/api/chat", {"text": "count"}, headers=post, timeout=30)
            evs = sse(raw)
            deltas = "".join(d["t"] for e, d in evs if e == "delta")
            done = [d for e, d in evs if e == "done"]
            ok(st == 200 and h.get("Content-Type", "").startswith("text/event-stream") and h.get("Cache-Control") == "no-store",
               "/api/chat answers SSE, no-store", (st, h))
            ok(deltas == "2" and done and done[0].get("thread") and isinstance(done[0].get("ms"), int),
               "chat: the deltas join to the stub's answer (system + line = 2), done names a thread", evs)
            ok(SEEN.get("auth") == "Bearer " + smoke.TOKEN, "chat went upstream with the api-token, not back into the forge", SEEN.get("auth"))
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(sys0.startswith("You are on ") and "Call yourself Fixture." in sys0 and "This is a conversation" in sys0,
               "chat: an in-process reply carries the machine line, identity and the chat mode", sys0[:200])
            ok("Preferred when installed" not in sys0 and "Flags that exist" not in sys0,
               "chat through the forge sheds the shell costume", sys0[:200])
            ok(SEEN.get("body", {}).get("model") == "ember", "chat goes upstream as the ember", SEEN.get("body", {}).get("model"))
            tid = done[0]["thread"] if done else ""
            tpath = state + "/threads/" + tid + ".jsonl"
            ok(os.path.isfile(tpath) and oct(os.stat(tpath).st_mode & 0o777) == "0o600", "the thread file exists, 0600", tpath)
            st, _, raw = req(url, "GET", "/api/threads", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and len(d["threads"]) == 1 and d["threads"][0]["id"] == tid and d["threads"][0]["turns"] == 1, "/api/threads lists it with 1 turn", raw[:200])
            st, _, raw = req(url, "GET", "/api/threads/" + tid, headers=cookie)
            d = json.loads(raw)
            ok(st == 200 and d["id"] == tid and [m["role"] for m in d["messages"]] == ["user", "assistant"] and d["messages"][1]["text"] == "2",
               "/api/threads/<id>: the 2 messages", raw[:200])
            st, _, raw = req(url, "POST", "/api/chat", {"thread": tid, "text": "count", "mode": "ask"}, headers=post, timeout=30)
            evs = sse(raw)
            ok(st == 200 and "".join(d["t"] for e, d in evs if e == "delta") == "4", "a second chat on the thread: the stub saw 4 messages", evs)
            st, _, raw = req(url, "GET", "/api/threads?n=30", headers=bearer)
            ok(json.loads(raw)["threads"][0]["turns"] == 2, "the thread has 2 turns now", raw[:200])
            st, _, _ = req(url, "POST", "/api/chat", {"thread": "2099-01-01-000000", "text": "x"}, headers=post)
            ok(st == 404, "chat on an unknown thread -> 404", st)
            st, _, _ = req(url, "POST", "/api/chat", {"thread": "../etc", "text": "x"}, headers=post)
            ok(st == 400, "chat with a bad thread id -> 400", st)
            st, _, _ = req(url, "GET", "/api/threads/../etc", headers=bearer)
            ok(st == 400, "GET /api/threads/<bad id> -> 400", st)
            st, _, _ = req(url, "POST", "/api/chat", {"text": "  "}, headers=post)
            ok(st == 400, "chat with empty text -> 400", st)
            st, _, _ = req(url, "POST", "/api/chat", {"text": "x", "mode": "do"}, headers=post)
            ok(st == 400, "chat mode do -> 400", st)
            st, _, raw = req(url, "POST", "/api/chat", {"thread": tid, "text": "count", "mode": "chat"}, headers=post, timeout=30)
            ok(st == 200 and any(e == "done" for e, _d in sse(raw)), "mode chat works", st)
            st, _, raw = req(url, "POST", "/api/chat", {"thread": tid, "text": "count", "mode": "talk"}, headers=post, timeout=30)
            ok(st == 200 and any(e == "done" for e, _d in sse(raw)), "mode talk still accepted (the old name of chat)", st)

            # the stop button: a client that hangs up mid-stream still
            # lands the turn -- the user line and the partial (partial=True)
            u2 = urllib.parse.urlsplit(url)
            c2 = http.client.HTTPConnection(u2.hostname, u2.port, timeout=10)
            c2.request("POST", "/api/chat", json.dumps({"text": "dripfeed"}).encode(),
                       dict(post, **{"Content-Type": "application/json"}))
            r2 = c2.getresponse()
            buf, t_end = b"", time.time() + 10
            while b"event: delta" not in buf and time.time() < t_end:
                chunk = r2.read1(512)
                if not chunk:
                    break
                buf += chunk
            # stop: the socket just goes away (RST, like a browser abort);
            # the OS socket sits under the response once the SSE detaches
            r2.fp.raw._sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            r2.close()
            c2.close()
            got, t_end = None, time.time() + 10
            while got is None and time.time() < t_end:
                time.sleep(0.2)
                st, _, raw = req(url, "GET", "/api/threads?n=10", headers=bearer)
                for t in json.loads(raw).get("threads", []):
                    st2, _, raw2 = req(url, "GET", "/api/threads/" + t["id"], headers=bearer)
                    ms2 = json.loads(raw2).get("messages", [])
                    if (any(m["role"] == "user" and m["text"] == "dripfeed" for m in ms2)
                            and ms2[-1]["role"] == "assistant"):
                        got = ms2
                        break
            ok(got is not None and got[-1]["role"] == "assistant" and got[-1].get("partial") is True
               and got[-1]["text"] and set(got[-1]["text"]) == {"a"},
               "a hung-up chat records the user line and the partial reply, partial=True", got)

            st, _, raw = req(url, "GET", "/api/soul", headers=bearer)
            d = json.loads(raw)
            ok(st == 200 and d == {"text": "Call yourself Fixture.", "source": "file"}, "/api/soul: the fixture soul", raw[:100])
            st, _, raw = req(url, "POST", "/api/soul", {"text": "New soul."}, headers=post)
            soulf = home + "/.config/spark/soul"
            ok(st == 200 and json.loads(raw) == {"chars": 9, "cut": False} and open(soulf).read() == "New soul.\n"
               and oct(os.stat(soulf).st_mode & 0o777) == "0o600", "POST /api/soul writes the file 0600", raw[:100])
            st, _, raw = req(url, "GET", "/api/soul", headers=bearer)
            ok(json.loads(raw)["text"] == "New soul.", "GET /api/soul reflects it", raw[:100])
            SEEN.clear()
            req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok("New soul." in sys0 and "Fixture" not in sys0, "the next /v1 request carries the new soul", sys0[:200])
            st, _, _ = req(url, "POST", "/api/soul", {"text": "Call yourself Fixture."}, headers=post)
            ok(st == 200 and open(soulf).read() == "Call yourself Fixture.\n", "and back to the fixture soul")

            st, _, raw = req(url, "GET", "/api/memory", headers=bearer)
            ok(st == 200 and json.loads(raw) == {"facts": [], "on": True}, "/api/memory: nothing yet, on", raw[:100])
            st, _, raw = req(url, "POST", "/api/memory", {"text": "the box is  called forge"}, headers=post)
            ok(st == 200 and json.loads(raw) == {"n": 1, "text": "the box is called forge"}, "POST /api/memory keeps a fact (spaces folded)", raw[:100])
            rc, out, _ = spark("memory")
            ok(rc == 0 and "1 fact" in out and "1   the box is called forge" in out, "spark memory on the same HOME lists it", out)
            st, _, raw = req(url, "GET", "/api/memory", headers=bearer)
            ok(json.loads(raw)["facts"] == [{"n": 1, "text": "the box is called forge"}], "GET /api/memory lists it numbered", raw[:100])
            st, _, _ = req(url, "POST", "/api/memory", {"text": "The box is called forge"}, headers=post)
            ok(st == 409, "the same fact again -> 409", st)
            st, _, _ = req(url, "POST", "/api/memory", {"text": " "}, headers=post)
            ok(st == 400, "an empty fact -> 400", st)
            st, _, _ = req(url, "POST", "/api/memory", {"text": "x" * 201}, headers=post)
            ok(st == 400, "a 201-char fact -> 400", st)
            SEEN.clear()
            req(url, "POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "what"}], "stream": False}, headers=bearer)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok("- the box is called forge" in sys0, "the fact rides in the identity", sys0[:300])
            st, _, _ = req(url, "DELETE", "/api/memory/1", headers=bearer)
            ok(st == 403, "DELETE without X-Spark -> 403", st)
            st, _, _ = req(url, "DELETE", "/api/memory/9", headers=post)
            ok(st == 404, "DELETE a fact that is not there -> 404", st)
            st, _, raw = req(url, "DELETE", "/api/memory/1", headers=post)
            ok(st == 200 and json.loads(raw) == {"text": "the box is called forge"}, "DELETE /api/memory/1", raw[:100])
            st, _, raw = req(url, "GET", "/api/memory", headers=bearer)
            ok(json.loads(raw)["facts"] == [], "GET /api/memory: empty again", raw[:100])
            rc, out, _ = spark("memory")
            ok(rc == 0 and "0 facts" in out, "spark memory agrees", out)

            st, _, raw = req(url, "POST", "/api/do/propose", {"text": "say hello"}, headers=post, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and d.get("thread") and d["reply"] == {"kind": "cmd", "command": "echo STEP-ONE", "hint": "say hello", "danger": False}
               and isinstance(d.get("ms"), int), "/api/do/propose: the step, a thread, nothing run", raw[:300])
            dtid = d.get("thread", "")
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "echo hi"}, headers=post)
            ok(st == 200 and json.loads(raw) == {"rc": 0, "tail": "hi\n"}, "/api/do/run echo hi -> rc 0, tail", raw[:100])
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "false"}, headers=post)
            ok(st == 200 and json.loads(raw)["rc"] == 1, "/api/do/run false -> rc 1 (run as clicked, not re-judged)", raw[:100])
            st, _, raw = req(url, "POST", "/api/do/run", {"command": "pwd", "cwd": tmp}, headers=post)
            ok(st == 200 and json.loads(raw)["tail"].strip().endswith(os.path.basename(tmp)), "/api/do/run honours cwd", raw[:100])
            st, _, _ = req(url, "POST", "/api/do/run", {"command": ""}, headers=post)
            ok(st == 400, "/api/do/run with no command -> 400", st)
            st, _, raw = req(url, "POST", "/api/do/propose", {"thread": dtid, "text": "Output of `echo STEP-ONE` (exit 0):\nSTEP-ONE"}, headers=post, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and d["thread"] == dtid and d["reply"]["kind"] == "done", "/api/do/propose on the thread: done", raw[:200])
            ok(d.get("driver") == hj["roles"]["ember"] and d.get("unchecked") == [],
               "/api/do/propose done: driver is the ember's stem, unchecked empty", (d.get("driver"), d.get("unchecked")))
            st, _, raw = req(url, "GET", "/api/threads/" + dtid, headers=bearer)
            ok(st == 200 and len(json.loads(raw)["messages"]) == 4, "the do thread holds goal / step / output / done", raw[:300])
            st, _, raw = req(url, "POST", "/api/do/propose", {"text": "badsum count"}, headers=post, timeout=30)
            d = json.loads(raw)
            btid = d.get("thread", "")
            ok(st == 200 and d["reply"]["command"] == "echo 21; echo 5" and d.get("unchecked") == [],
               "/api/do/propose badsum: the counting step; a cmd is never flagged", raw[:300])
            st, _, raw = req(url, "POST", "/api/do/propose", {"thread": btid, "text": "Output of `echo 21; echo 5` (exit 0):\n21\n5"}, headers=post, timeout=30)
            d = json.loads(raw)
            ok(st == 200 and d["reply"]["kind"] == "done" and d.get("unchecked") == ["96"],
               "/api/do/propose: a done number no output backs comes back unchecked", raw[:300])
            lg = open(state + "/forge.log").read()
            ok("do/run echo hi" in lg and "do/run false" in lg, "forge.log names the commands run", lg[-300:])

            st, h, raw = req(url, "POST", "/api/run", {"verb": "model", "args": ["none"]}, headers=post, timeout=60)
            evs = sse(raw)
            lines = [d["s"] for e, d in evs if e == "line"]
            ok(st == 200 and any(l.startswith("ok     site") and "SITE_AI_MODEL=none" in l for l in lines) and ("done", {"rc": 0}) in evs,
               "/api/run model none: streams the verb's lines, done rc 0", evs)
            ok("SITE_AI_MODEL=none" in open(home + "/.config/spark/site.env").read(), "site.env has SITE_AI_MODEL=none (SPARK_NO_APPLY)")
            st, h, raw = req(url, "POST", "/api/run", {"verb": "ember", "args": ["none"]}, headers=post, timeout=60)
            evs = sse(raw)
            lines = [d["s"] for e, d in evs if e == "line"]
            ok(st == 200 and any(l.startswith("ok     site") and "SITE_EMBER_MODEL=none" in l for l in lines) and ("done", {"rc": 0}) in evs,
               "/api/run ember none: streams the verb's lines, done rc 0", evs)
            ok("SITE_EMBER_MODEL=none" in open(home + "/.config/spark/site.env").read(), "site.env has SITE_EMBER_MODEL=none (SPARK_NO_APPLY)")
            st, _, raw = req(url, "POST", "/api/run", {"verb": "history", "args": ["clear"]}, headers=post, timeout=60)
            ok(st == 200 and ("done", {"rc": 0}) in sse(raw) and not os.listdir(state + "/threads"), "/api/run history clear empties the threads", raw[:200])
            st, _, _ = req(url, "POST", "/api/run", {"verb": "check", "args": []}, headers=post)
            ok(st == 400, "/api/run check -> 400", st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "history", "args": []}, headers=post)
            ok(st == 400, "/api/run history without clear -> 400", st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "model", "args": ["none; rm -rf /"]}, headers=post)
            ok(st == 400, "/api/run with a ; in an arg -> 400", st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "model", "args": "none"}, headers=post)
            ok(st == 400, "/api/run args not a list -> 400", st)
            st, _, _ = req(url, "POST", "/api/run", {"verb": "model", "args": ["none"]}, headers=bearer)
            ok(st == 403, "/api/run without X-Spark -> 403", st)
            st, _, _ = req(url, "POST", "/api/chat", {"text": "x"}, headers=bearer)
            ok(st == 403, "/api/chat without X-Spark -> 403", st)
            st, _, _ = req(url, "GET", "/api/threads", headers={})
            ok(st == 401, "/api/threads bare -> 401", st)

            # the user role: the ember-token
            st, h, raw = req(url, "POST", "/api/login", {"token": utoken})
            usc = h.get("Set-Cookie", "")
            ok(st == 200 and usc.startswith("spark_forge=") and json.loads(raw).get("role") == "user",
               "user login (ember-token) -> cookie, role user", (st, raw[:100]))
            ok(usc.split(";")[0] != sc.split(";")[0], "the user cookie differs from the admin cookie")
            ucookie = {"Cookie": usc.split(";")[0]}
            st, _, raw = req(url, "GET", "/api/me", headers=ucookie)
            ok(st == 200 and json.loads(raw).get("role") == "user", "/api/me with the user cookie: role user", raw[:100])
            st, _, raw = req(url, "GET", "/api/me", headers=ubearer)
            ok(st == 200 and json.loads(raw).get("role") == "user", "/api/me with the user bearer: role user", raw[:100])
            upost = dict(ubearer, **{"X-Spark": "1", "Origin": url})
            st, h, raw = req(url, "POST", "/api/chat", {"text": "count"}, headers=upost, timeout=30)
            evs = sse(raw)
            ok(st == 200 and h.get("Content-Type", "").startswith("text/event-stream")
               and "".join(d["t"] for e, d in evs if e == "delta") == "2" and any(e == "done" for e, d in evs),
               "a user chats: the SSE streams and finishes", evs)
            st, _, _ = req(url, "GET", "/api/threads", headers=ubearer)
            ok(st == 200, "user /api/threads 200", st)
            st, _, _ = req(url, "GET", "/api/soul", headers=ubearer)
            ok(st == 200, "user GET /api/soul 200", st)
            st, _, _ = req(url, "POST", "/api/soul", {"text": "Call yourself Fixture."}, headers=upost)
            ok(st == 200, "user POST /api/soul 200", st)
            st, _, raw = req(url, "POST", "/api/memory", {"text": "a user fact"}, headers=upost)
            ok(st == 200, "user POST /api/memory 200", raw[:100])
            st, _, _ = req(url, "DELETE", "/api/memory/1", headers=upost)
            ok(st == 200, "user DELETE /api/memory/1 200", st)
            st, _, _ = req(url, "GET", "/api/check", headers=ubearer)
            ok(st == 200, "user /api/check 200", st)
            st, _, _ = req(url, "GET", "/api/stats?days=1", headers=ubearer)
            ok(st == 200, "user /api/stats 200", st)
            st, _, _ = req(url, "GET", "/api/bar", headers=ubearer, timeout=30)
            ok(st == 200, "user /api/bar 200", st)
            st, _, _ = req(url, "GET", "/api/theme", headers=ubearer)
            ok(st == 200, "user /api/theme 200", st)
            st, _, raw = req(url, "POST", "/v1/chat/completions",
                             {"messages": [{"role": "user", "content": "capital of France?"}], "stream": False}, headers=ubearer)
            ok(st == 200 and "Paris" in json.loads(raw)["choices"][0]["message"]["content"], "/v1 with the user bearer 200", raw[:200])
            st, _, _ = req(url, "GET", "/v1/models", headers=ubearer)
            ok(st == 200, "user /v1/models 200", st)
            for method, path, body in (("POST", "/api/run", {"verb": "model", "args": ["none"]}),
                                       ("GET", "/api/config", None),
                                       ("POST", "/api/do/propose", {"text": "x"}),
                                       ("POST", "/api/do/run", {"command": "echo hi"}),
                                       ("GET", "/api/bench", None), ("GET", "/api/log", None),
                                       ("GET", "/api/serve", None), ("GET", "/api/gpu", None),
                                       ("POST", "/api/check/refresh", {})):
                st, _, raw = req(url, method, path, body, headers=upost if body is not None else ubearer)
                kind = ""
                try:
                    kind = json.loads(raw)["error"]["kind"]
                except (ValueError, KeyError):
                    pass
                ok(st == 403 and kind == "role", "user %s %s -> 403 role" % (method, path), (st, raw[:100]))
            # user events: check/bar/serve, never the log event
            uc = http.client.HTTPConnection(u.hostname, u.port, timeout=4)
            uc.request("GET", "/api/events", None, ubearer)
            ur = uc.getresponse()
            req(url, "GET", "/api/health")          # touches forge.log
            head = ""
            try:
                while len(head) < 8000:
                    line = ur.readline().decode()
                    if not line:
                        break
                    head += line
            except OSError:
                pass
            uc.close()
            ok("event: check" in head and "event: serve" in head and "event: log" not in head,
               "user /api/events: check and serve, never log", head[:300])

            # the verbs while it runs
            rc, out, _ = spark("forge", "--print-url")
            ok(rc == 0 and out.strip() == url + "/login", "--print-url: the login URL only (no tty)", out)
            rc, out, _ = spark("forge", "--print-url", "--show-token")
            ok(rc == 0 and out.splitlines()[1] == "token  " + token, "--print-url --show-token", out)
            rc, out, _ = spark("forge", "--print-url", "--user", "--show-token")
            ok(rc == 0 and out.splitlines()[1] == "token  " + utoken, "--print-url --user --show-token: the user token", out)
            rc, out, _ = spark("forge", "--print-client")
            ls = out.splitlines()
            ok(rc == 0 and ls[0] == "SITE_PEER_AI_URL=" + url
               and ls[1] == "scp fixture:~/.local/state/spark/ember-token ~/.local/state/spark/ember-token"
               and "the admin token stays on this machine" in ls[2]
               and ls[3].startswith("spark client " + url), "--print-client: the user token's lines, the verb", out)
            ok(token not in out and "forge-token" not in out, "--print-client never hands out the admin token", out)
            rc, out, _ = spark("forge")
            ok(rc == 0 and url in out and "health   ok" in out and "stub-7b-q4" in out
               and "admin" in out and "user" in out and out.count("0600") == 2,
               "spark forge (status): url, ok, model, both token modes", out)
            rc, out, _ = spark("forge", "start")
            ok(rc == 0 and "already running" in out, "start while running: already running", out)

            # a client through the forge
            client = {"SPARK_BASE_URL": url, "SPARK_FORGE_TOKEN": token, "SPARK_API_KEY": ""}
            rc, out, _ = spark("brain", "--porcelain", extra=client)
            ok(rc == 0 and out.strip() == url + "\tstub-7b-q4\tforge", "spark brain --porcelain: url, model, forge", out)
            SEEN.clear()
            rc, out, _ = spark("line", "--cwd", "/tmp", "--shell", "zsh", stdin="? files bigger than 1G this week", extra=client)
            ok(rc == 0 and out.splitlines()[0] == "cmd\tfind . -type f -size +1G -mtime -7", "spark line through the forge: the cmd protocol", out)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(SEEN.get("body", {}).get("model") == "spark", "the line through the forge names the spark role", SEEN.get("body", {}).get("model"))
            ok("Fixture" not in sys0 and sys0.startswith("You are spark, the assistant at") and "shell zsh" in sys0
               and "typed a question at the shell prompt" in sys0,
               "a spark request passes the forge untouched: machine facts and the mode, no identity", sys0[:200])
            SEEN.clear()
            rc, out, _ = spark("what", "does", "this", "mean", extra=client)
            sys0 = SEEN.get("body", {}).get("messages", [{}])[0].get("content", "")
            ok(rc == 0 and SEEN.get("body", {}).get("model") == "ember" and sys0.startswith("Call yourself Fixture.")
               and "You are spark, the assistant at" in sys0,
               "a sentence through the forge: ember, the identity then the client's prefix", sys0[:200])
            rc, out, _ = spark("brain", "--porcelain", extra=dict(client, SPARK_FORGE_TOKEN="wrong"))
            ok(rc == 0, "brain needs no token (health is open)", out)
            rc, out, _ = spark("line", stdin="x?", extra=dict(client, SPARK_FORGE_TOKEN="wrong"))
            ok(rc == 1 and "ember-token" in out, "a wrong forge token -> error naming the ember-token", out)
            rc, out, _ = spark("status", extra=client)
            ok(rc == 0 and "a FORGE" in out, "spark status names the FORGE", out)

            # lockout: ten wrong logins in a minute, then 429
            def bad():
                req(url, "POST", "/api/login", {"token": "nope"})
            ts = [threading.Thread(target=bad) for _ in range(10)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            st, _, _ = req(url, "POST", "/api/login", {"token": token})
            ok(st == 429, "after 10 wrong logins even the right one is 429", st)

            # token rotation takes effect live, one role at a time
            rc, out, _ = spark("forge", "token", "--new", "--user")
            utoken2 = open(etok_path).read().strip()
            ok(rc == 0 and "user" in out and "log in again" in out and utoken2 != utoken,
               "token --new --user rewrites ember-token, says which", out)
            st, _, _ = req(url, "GET", "/api/check", headers=ubearer)
            ok(st == 401, "the old user bearer died with the old user token")
            st, _, _ = req(url, "GET", "/api/check", headers=ucookie)
            ok(st == 401, "the old user cookie died too")
            st, _, _ = req(url, "GET", "/api/check", headers=cookie)
            ok(st == 200, "the admin cookie survived the user rotation")
            st, _, raw = req(url, "GET", "/api/me", headers={"Authorization": "Bearer " + utoken2})
            ok(st == 200 and json.loads(raw).get("role") == "user", "the new user token works without a restart", raw[:100])
            rc, out, _ = spark("forge", "token", "--new")
            token2 = open(tok_path).read().strip()
            ok(rc == 0 and "admin" in out and "log in again" in out and token2 != token, "token --new rewrites the file", out)
            st, _, _ = req(url, "GET", "/api/check", headers=cookie)
            ok(st == 401, "the old admin cookie died with the old token")
            st, _, _ = req(url, "GET", "/api/check", headers={"Authorization": "Bearer " + token2})
            ok(st == 200, "the new admin token works without a restart")
            st, _, _ = req(url, "GET", "/api/check", headers={"Authorization": "Bearer " + utoken2})
            ok(st == 200, "the user token survived the admin rotation")

            # a client that only holds the user token still answers the line
            os.rename(tok_path, tok_path + ".aside")
            try:
                only = {"SPARK_BASE_URL": url, "SPARK_API_KEY": ""}
                rc, out, _ = spark("line", "--cwd", "/tmp", "--shell", "zsh", stdin="? files bigger than 1G this week", extra=only)
                ok(rc == 0 and out.splitlines()[0] == "cmd\tfind . -type f -size +1G -mtime -7",
                   "spark line with only the ember-token answers the cmd protocol", out)
            finally:
                os.rename(tok_path + ".aside", tok_path)
        finally:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=10)
                ok(p.returncode == 0, "SIGTERM ends the foreground forge (exit %s)" % p.returncode)
            except subprocess.TimeoutExpired:
                p.kill()
                ok(False, "foreground forge ignored SIGTERM")
        ok(not os.path.exists(state + "/forge-url") and not os.path.exists(state + "/forge.pid"), "forge-url and forge.pid removed")
        rc, out, _ = spark("forge", "stop")
        ok(rc == 0 and "not running" in out, "stop afterwards: not running", out)

        # start / stop in the background
        rc, out, err = spark("forge", "start")
        ok(rc == 0 and "ready (pid" in out and url in out, "spark forge start: background, waits for health", out + err)
        try:
            st, _, _ = req(url, "GET", "/api/health")
            ok(st == 200, "the background forge answers")
            rc, out, _ = spark("forge", "off")
            ok(rc == 0 and "SPARK_FORGE=off" in out and "stopped" in out, "spark forge off: writes spark.env, stops", out)
            ok("SPARK_FORGE=off" in open(home + "/.config/spark/spark.env").read(), "spark.env has SPARK_FORGE=off")
            time.sleep(0.3)
            try:
                st, _, _ = req(url, "GET", "/api/health", timeout=2)
            except OSError:
                st = 0
            ok(st == 0, "the background forge is gone")
            rc, out, _ = spark("forge", "on")
            ok(rc == 0 and "SPARK_FORGE=on" in out and "ready (pid" in out, "spark forge on: writes spark.env, starts", out)
        finally:
            spark("forge", "stop", "--force")
        rc, out, _ = spark("forge", "stop")
        ok(rc == 0 and "not running" in out, "stopped for good", out)
        os.remove(state + "/serve-url")
        rc, out, err = spark("forge", "--foreground")
        ok(rc == 78 and "no model" in err, "no serve-url, no engine, no model -> 78", err)

    stub.shutdown()
    print("forge_smoke: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
