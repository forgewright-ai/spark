#!/usr/bin/env python3
# spark tests/serve_smoke.py -- `spark serve` and `spark stop` against a
# stub llama-server binary, hermetic: no model, no network beyond loopback,
# no real service manager (stub launchctl/systemctl say "absent" -- the
# launchctl stub exits 1 for both gui/ and system/, so no daemon either).

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARK = os.path.join(REPO, "bin", "spark")

STUB_SERVER = '''#!%s
# a stand-in llama-server: records its argv, honours --api-key-file, answers
# /health (503 for STUB_LOAD_S seconds, then 200), /v1/models (both the
# single form and the router form, whose presets.ini it reads back) and
# /v1/chat/completions (for `spark serve`'s warm-up).
import json, os, sys, time, signal
from http.server import BaseHTTPRequestHandler, HTTPServer
args = sys.argv[1:]
def opt(name, default=""):
    return args[args.index(name) + 1] if name in args else default
with open(os.path.join(os.environ["HOME"], "spawned.json"), "w") as f:
    json.dump(args, f)
token = open(opt("--api-key-file")).read().strip() if opt("--api-key-file") else ""
presets = {}
if "--models-dir" in args:
    cur = None
    for line in open(opt("--models-preset")):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1]; presets[cur] = {}
        elif "=" in line and cur:
            k, v = line.split("=", 1); presets[cur][k.strip()] = v.strip()
def entries():
    if presets:
        return [{"id": n, "aliases": [], "status": {"value": "loaded", "args": ["--model", d.get("model", "")]}}
                for n, d in presets.items()]
    names = opt("--alias").split(",") if opt("--alias") else [opt("-m")]
    return [{"id": names[-1], "aliases": list(reversed(names))}]
ready_at = time.time() + float(os.environ.get("STUB_LOAD_S", "0"))
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def _authed(self):
        return not token or self.headers.get("Authorization") == "Bearer " + token
    def do_GET(self):
        if self.path == "/health":
            return self._send(200 if time.time() >= ready_at else 503, {"status": "ok"})
        if self.path == "/v1/models":
            if not self._authed():
                return self._send(401, {})
            return self._send(200, {"data": entries()})
        self._send(404, {})
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        if not self._authed():
            return self._send(401, {})
        if self.path == "/v1/chat/completions":
            model = json.loads(body or b"{}").get("model", "")
            return self._send(200, {"model": model, "choices": [{"message": {"role": "assistant", "content": "ok"}}]})
        self._send(404, {})
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
HTTPServer((opt("--host", "127.0.0.1"), int(opt("--port", "8080"))), H).serve_forever()
''' % sys.executable


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def main():
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + str(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    with tempfile.TemporaryDirectory(prefix="spark-serve-") as tmp:
        home = os.path.join(tmp, "home")
        eng = os.path.join(tmp, "engine")
        models = os.path.join(tmp, "models")
        bins = os.path.join(tmp, "bin")
        for d in (home, eng, models, bins, os.path.join(home, ".config", "spark")):
            os.makedirs(d)
        with open(os.path.join(eng, "llama-server"), "w") as f:
            f.write(STUB_SERVER)
        os.chmod(os.path.join(eng, "llama-server"), 0o755)
        for name in ("launchctl", "systemctl"):
            with open(os.path.join(bins, name), "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(os.path.join(bins, name), 0o755)
        with open(os.path.join(models, "stub.gguf"), "w") as f:
            f.write("gguf" * 64)
        port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SPARK_", "XDG_", "SITE_"))}
        env.update({"HOME": home, "XDG_CONFIG_HOME": home + "/.config", "XDG_STATE_HOME": home + "/.local/state",
                    "XDG_DATA_HOME": home + "/.local/share", "PATH": bins + ":" + env.get("PATH", ""),
                    "SPARK_ENGINE_DIR": eng, "SPARK_MODELS_DIR": models, "SPARK_PORT": str(port),
                    "SPARK_SERVE_HOST": "127.0.0.1", "SPARK_SERVICE": "none", "SPARK_NO_REFRESH": "1", "SPARK_TIMEOUT": "5",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color"})
        state = home + "/.local/state/spark"
        url = "http://127.0.0.1:%d" % port

        def spark(*args, extra=None, timeout=60):
            e = dict(env)
            e.update(extra or {})
            p = subprocess.run([sys.executable, SPARK] + list(args), capture_output=True, text=True, env=e, timeout=timeout)
            return p.returncode, p.stdout, p.stderr

        print("serve_smoke: port %d, HOME %s" % (port, home))

        # serve: token, serve-url, pidfile, argv
        rc, out, err = spark("serve")
        ok(rc == 0 and "ready (pid" in out, "spark serve starts and waits for /health", out + err)
        ok(get(url + "/health") == 200, "the stub answers /health")
        tok = state + "/api-token"
        ok(os.path.isfile(tok) and oct(os.stat(tok).st_mode & 0o777) == "0o600", "token file 0600")
        ok(open(state + "/serve-url").read().strip() == url, "serve-url written")
        pid = int(open(state + "/serve.pid").read())
        os.kill(pid, 0)
        ok(True, "pidfile names a live pid %d" % pid)
        argv = json.load(open(home + "/spawned.json"))
        ok("--api-key-file" in argv and tok in argv and "--api-key" not in argv, "server got --api-key-file, never the value", argv)
        ok("--no-webui" in argv and "--no-slots" in argv and "--host" in argv and "0.0.0.0" not in argv, "no webui, no slots, one address", argv)
        ok("SPARK_BASE_URL=" + url in out, "client lines printed", out)
        ok("for another machine to use this server:" in out,
           "the client-lines heading says who it is for (not where it serves)", out)
        # the client resolves through serve-url (the port is not 8080)
        rc, out, _ = spark("brain", "--porcelain")
        ok(rc == 0 and out.strip() == url + "\tstub\tmodel", "brain resolves via serve-url", out)
        # again: already serving
        rc, out, _ = spark("serve")
        ok(rc == 0 and "already serving" in out, "second serve: already serving", out)
        # stop
        rc, out, err = spark("stop")
        ok(rc == 0 and "stopped pid" in out, "spark stop", out + err)
        time.sleep(0.5)
        ok(get(url + "/health") == 0, "server gone")
        ok(not os.path.exists(state + "/serve-url") and not os.path.exists(state + "/serve.pid"), "serve-url and pidfile removed")
        rc, out, _ = spark("stop")
        ok(rc == 0 and "not running" in out, "stop again: not running, exit 0", out)

        # a foreign server on the port
        foreign = subprocess.Popen([sys.executable, os.path.join(eng, "llama-server"), "--host", "127.0.0.1", "--port", str(port), "-m", "foreign"],
                                   env=dict(env, HOME=tmp), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        rc, out, err = spark("serve")
        ok(rc == 0 and "already serving" in out, "a healthy foreign server on the port: used, not fought", out + err)
        os.remove(state + "/serve-url")
        rc, out, err = spark("stop")
        ok(rc == 1 and "not started by spark" in err, "stop leaves a foreign server alone", err)
        ok(foreign.poll() is None, "foreign server still alive")
        rc, out, err = spark("stop", "--force")
        ok(rc == 0 and "killed" in out, "stop --force kills it", out + err)
        foreign.wait(timeout=5)
        ok(foreign.returncode is not None, "foreign server gone")

        # flags and refusals
        rc, out, err = spark("stop", "--noreload")
        ok(rc == 1 and "nothing to disable" in err, "--noreload without a unit is refused", err)
        rc, out, err = spark("serve", extra={"SPARK_BASE_URL": "http://192.0.2.9:8080"})
        ok(rc == 78 and "client of" in err, "SPARK_BASE_URL set: serve refuses with 78", err)
        rc, out, err = spark("serve", "--host", "0.0.0.0")
        ok(rc == 78 and "0.0.0.0" in err, "0.0.0.0 refused", err)
        rc, out, err = spark("serve", extra={"SPARK_MODELS_DIR": tmp + "/nope"})
        ok(rc == 78 and "bootstrap" in err, "no model: exit 78 naming bootstrap", err)
        rc, out, err = spark("serve", extra={"SPARK_ENGINE_DIR": tmp + "/nope"})
        ok(rc == 78 and "bootstrap" in err, "no engine: exit 78 naming bootstrap", err)
        rc, out, _ = spark("serve", "--print-client")
        ok(rc == 0 and "SPARK_BASE_URL=" in out and "scp" in out, "--print-client", out)

        # two models (real rows from models.env, zero bytes): the router form
        small, big = "Qwen3-1.7B-Q4_K_M.gguf", "Qwen_Qwen3-8B-Q4_K_M.gguf"
        for f in (small, big):
            open(os.path.join(models, f), "w").close()
        router = state + "/router"
        # SITE_AI_BUILD=vulkan: the speed cap then admits the 8b as the ember on a
        # Linux runner too (cpu would cap at 3 GB files; macOS ignores the key)
        renv = {"SITE_AI_MODEL": "auto", "SITE_EMBER_MODEL": "auto", "SPARK_MEM_TOTAL_GB": "18", "SITE_AI_BUILD": "vulkan"}
        rc, out, err = spark("serve", extra=renv)
        ok(rc == 0 and "ready (pid" in out, "serve with an ember: router starts", out + err)
        ok("warm   spark, ember" in out, "both roles warmed", out)
        argv = json.load(open(home + "/spawned.json"))
        ok("--models-dir" in argv and "--models-preset" in argv and "--models-max" in argv, "router argv", argv)
        ok("-m" not in argv and "-c" not in argv and "-ngl" not in argv, "per-model args left to presets.ini", argv)
        ok(os.path.islink(router + "/spark.gguf") and os.readlink(router + "/spark.gguf") == os.path.join(models, small),
           "spark.gguf links the small model")
        ok(os.path.islink(router + "/ember.gguf") and os.readlink(router + "/ember.gguf") == os.path.join(models, big),
           "ember.gguf links the big one")
        ini = open(router + "/presets.ini").read()
        ok("[spark]" in ini and "[ember]" in ini and ini.index("[spark]") < ini.index("[ember]"), "presets.ini has both sections", ini)
        spark_sec, ember_sec = ini.split("[ember]")
        ok("reasoning = off" in spark_sec and "ctx-size = 4096" in spark_sec, "spark preset: reasoning off, ctx 4096", ini)
        ok("reasoning" not in ember_sec and "ctx-size = 8192" in ember_sec, "ember preset: no reasoning line, SPARK_CTX", ini)
        rc, out, _ = spark("brain", "--porcelain", "--fresh", extra=renv)
        ok(rc == 0 and out.strip() == url + "\tQwen3-1.7B-Q4_K_M\tmodel", "brain names the spark role's file stem", out)
        rc, out, err = spark("stop", extra=renv)
        ok(rc == 0 and "stopped pid" in out, "stop the router", out + err)

        # SITE_EMBER_MODEL=none: the single form, aliased spark + stem
        nenv = {"SITE_AI_MODEL": "auto", "SITE_EMBER_MODEL": "none", "SPARK_MEM_TOTAL_GB": "18"}
        rc, out, err = spark("serve", extra=nenv)
        ok(rc == 0 and "warm   spark\n" in out, "ember none: serves, warms spark alone", out + err)
        argv = json.load(open(home + "/spawned.json"))
        ok("-m" in argv and argv[argv.index("-m") + 1] == os.path.join(models, big) and "--models-dir" not in argv,
           "single form serves the largest fit", argv)
        ok("--alias" in argv and argv[argv.index("--alias") + 1] == "spark,Qwen_Qwen3-8B-Q4_K_M", "aliased spark + file stem", argv)
        ok(not os.path.lexists(router + "/ember.gguf"), "stale ember link removed")
        rc, out, _ = spark("brain", "--porcelain", "--fresh", extra=nenv)
        ok(rc == 0 and out.strip() == url + "\tQwen_Qwen3-8B-Q4_K_M\tmodel", "brain still names the file stem", out)
        spark("stop", extra=nenv)
        rc, out, err = spark("serve", extra={"SITE_EMBER_MODEL": "nosuch"})
        ok(rc == 78 and "nosuch" in err, "SITE_EMBER_MODEL=nosuch: exit 78 naming the row", err)

        # --foreground (the unit's path) warms after /health through a
        # detached helper, so the first question after boot does not wait;
        # the unit's pid is still the server's. stdout goes to a file: the
        # helper inherits it and outlives the exec.
        def foreground_warms(name, extra, want, what):
            path = os.path.join(tmp, name + ".out")
            with open(path, "w") as log:
                p = subprocess.Popen([sys.executable, SPARK, "serve", "--foreground"], env=dict(env, **extra),
                                     stdout=log, stderr=subprocess.STDOUT)
            deadline = time.time() + 15
            seen = ""
            while time.time() < deadline and want not in seen:
                time.sleep(0.3)
                seen = open(path).read()
            ok(want in seen, what, seen)
            ok(get(url + "/health") == 200 and int(open(state + "/serve.pid").read()) == p.pid,
               "the unit's pid is still the server's")
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            time.sleep(0.5)

        foreground_warms("fg-router", dict(renv, STUB_LOAD_S="2"), "warm   spark, ember\n",
                         "--foreground with an ember: both roles warmed after /health")
        foreground_warms("fg-single", dict(nenv, STUB_LOAD_S="2"), "warm   spark\n",
                         "--foreground, ember none: spark warmed after /health")
        for f in (small, big):
            os.remove(os.path.join(models, f))

        # a server that dies while loading
        rc, out, err = spark("serve", extra={"STUB_LOAD_S": "2", "SPARK_EXTRA_ARGS": "--crash"}, timeout=60)
        ok(rc == 0 and "ready" in out, "loading (503) is waited out", out + err)
        spark("stop")

        # foreground: the process IS the server; SIGTERM ends it
        p = subprocess.Popen([sys.executable, SPARK, "serve", "--foreground"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 15
        while time.time() < deadline and get(url + "/health") != 200:
            time.sleep(0.3)
        ok(get(url + "/health") == 200, "--foreground serves")
        ok(int(open(state + "/serve.pid").read()) == p.pid, "pidfile is the foreground pid (exec)")
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=5)
            ok(True, "SIGTERM ends the foreground server (exit %d)" % p.returncode)
        except subprocess.TimeoutExpired:
            p.kill()
            ok(False, "foreground server ignored SIGTERM")
        rc, out, err = spark("serve", "--foreground", extra={"SPARK_MODELS_DIR": tmp + "/nope"})
        ok(rc == 78, "--foreground misconfigured: exit 78 (SuccessExitStatus, no restart loop)", err)

    print("serve_smoke: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
