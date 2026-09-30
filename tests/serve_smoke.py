#!/usr/bin/env python3
# spark tests/serve_smoke.py -- `spark serve on|off` (the engine and the
# page together) against a stub llama-server binary, hermetic: no model,
# no network beyond loopback, no real service manager (stub
# launchctl/systemctl say "absent" -- the launchctl stub exits 1 for both
# gui/ and system/, so no daemon either), and never bootstrap
# (SPARK_NO_APPLY: `serve on|off` writes its two keys and nothing else).

import json
import os
import re
import shutil
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
        fport = free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SPARK_", "XDG_", "SITE_"))}
        env.update({"HOME": home, "XDG_CONFIG_HOME": home + "/.config", "XDG_STATE_HOME": home + "/.local/state",
                    "XDG_DATA_HOME": home + "/.local/share", "PATH": bins + ":" + env.get("PATH", ""),
                    "SPARK_ENGINE_DIR": eng, "SPARK_MODELS_DIR": models, "SPARK_PORT": str(port),
                    "SPARK_SERVE_HOST": "127.0.0.1", "SPARK_NO_REFRESH": "1", "SPARK_TIMEOUT": "5",
                    "SPARK_NO_APPLY": "1", "SPARK_FORGE_HOST": "127.0.0.1", "SPARK_FORGE_PORT": str(fport),
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color"})
        state = home + "/.local/state/spark"
        url = "http://127.0.0.1:%d" % port
        furl = "http://127.0.0.1:%d" % fport
        spark_env = home + "/.config/spark/spark.env"

        def kept():
            try:
                text = open(spark_env).read()
            except OSError:
                return ""
            return " ".join(l for l in text.split() if l.startswith(("SPARK_SERVICE=", "SPARK_FORGE=")))

        def spark(*args, extra=None, timeout=60):
            e = dict(env)
            e.update(extra or {})
            p = subprocess.run([sys.executable, SPARK] + list(args), capture_output=True, text=True, env=e, timeout=timeout)
            return p.returncode, p.stdout, p.stderr

        print("serve_smoke: port %d, HOME %s" % (port, home))

        # a process whose argv is not UTF-8 (a Latin-1 file name) runs for
        # the whole suite: spark serve reads `ps`, and that byte used to end
        # it in a UnicodeDecodeError (the gate's "pidfile race": smoke.py's
        # `spark read --name t\xe9tulo.txt` ran beside this suite). It
        # leaves when this suite's process does.
        latin = subprocess.Popen([sys.executable, "-c", "import os, sys, time\nwhile os.getppid() == int(sys.argv[1]): time.sleep(0.5)",
                                  str(os.getpid()), "t\udce9tulo.txt"])

        # serve: token, serve-url, pidfile, argv
        rc, out, err = spark("serve", "on")
        ok(rc == 0 and "ready (pid" in out, "spark serve starts and waits for /health", out + err)
        ok("Traceback" not in out + err, "a Latin-1 argv in ps: spark serve reads it, no traceback", err[-300:])
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
        ok("--cache-ram" in argv and argv[argv.index("--cache-ram") + 1] == "0", "no prompt cache in RAM (--cache-ram 0)", argv)
        ok(get(furl + "/api/health") == 200 and os.path.isfile(state + "/forge.pid"),
           "serve on starts the page too, beside the engine", out + err)
        ok(kept() == "SPARK_SERVICE=auto SPARK_FORGE=on", "serve on keeps both: SPARK_SERVICE=auto and SPARK_FORGE=on", kept())
        ok(("spark client " + furl) in out and "spark user add NAME" in out and "scp" not in out,
           "serve on says how another machine joins: the page's URL, a user minted here, no scp", out)
        # the client resolves through the page (forge-url first, then serve-url)
        rc, out, _ = spark("brain", "--porcelain")
        ok(rc == 0 and out.strip() == furl + "\tstub\tforge", "brain resolves via the page, which fronts serve-url", out)
        rc, out, _ = spark("serve")
        ok(rc == 0 and out.startswith("spark serve -- on: the engine and the page, kept up")
           and ("answers  " + furl) in out and "this machine" in out and ("engine   serving at " + url) in out
           and ("page     " + furl + "/login") in out and "boot " in out and "share " in out,
           "bare spark serve: one view -- what answers, the engine, the page, boot, share", out)
        ok(kept() == "SPARK_SERVICE=auto SPARK_FORGE=on", "bare spark serve never mutates", kept())
        # again: already serving
        rc, out, _ = spark("serve", "on")
        ok(rc == 0 and "already serving" in out, "second serve: already serving", out)
        # stop
        rc, out, err = spark("serve", "off")
        ok(rc == 0 and "stopped pid" in out and "the page stopped" in out, "serve off: the page and the engine stopped", out + err)
        time.sleep(0.5)
        ok(get(url + "/health") == 0 and get(furl + "/api/health") == 0, "server and page gone")
        ok(not os.path.exists(state + "/serve-url") and not os.path.exists(state + "/serve.pid")
           and not os.path.exists(state + "/forge-url") and not os.path.exists(state + "/forge.pid"),
           "serve-url, forge-url and both pidfiles removed")
        ok(kept() == "SPARK_SERVICE=none SPARK_FORGE=off", "serve off keeps both down: SPARK_SERVICE=none and SPARK_FORGE=off", kept())
        rc, out, _ = spark("serve", "off")
        ok(rc == 0 and "not running" in out, "stop again: not running, exit 0", out)

        # SITE_QUIET_START=yes: the whole start collapses to one line
        rc, out, err = spark("serve", "on", extra={"SITE_QUIET_START": "yes"})
        lines = [l for l in out.splitlines() if l.strip() and not l.startswith("ok     spark.env")]
        ok(rc == 0 and len(lines) == 2 and re.match(r"^spark serve -- ready \(pid \d+\) at %s$" % re.escape(url), lines[0])
           and re.match(r"^spark serve -- the page ready \(pid \d+\) at %s/login$" % re.escape(furl), lines[1]),
           "quiet start: spark serve on answers with one line each, the engine and the page", out + err)
        rc, out, err = spark("serve", "off")
        ok(rc == 0 and "stopped pid" in out, "stop the quiet server", out + err)
        time.sleep(0.5)

        # a foreign server on the port
        foreign = subprocess.Popen([sys.executable, os.path.join(eng, "llama-server"), "--host", "127.0.0.1", "--port", str(port), "-m", "foreign"],
                                   env=dict(env, HOME=tmp), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        rc, out, err = spark("serve", "on")
        ok(rc == 0 and "already serving" in out, "a healthy foreign server on the port: used, not fought", out + err)
        rc, out, err = spark("serve", "--foreground")
        ok(rc == 78 and "this unit stands down" in out,
           "--foreground with a server already on the port: exit 78, the unit stands down (no restart every second)", out + err)
        os.remove(state + "/serve-url")
        rc, out, err = spark("serve", "off")
        ok(rc == 1 and "not started by spark" in err, "stop leaves a foreign server alone", err)
        ok(foreign.poll() is None, "foreign server still alive")
        rc, out, err = spark("serve", "off", "--force")
        ok(rc == 0 and "killed" in out, "stop --force kills it", out + err)
        foreign.wait(timeout=5)
        ok(foreign.returncode is not None, "foreign server gone")

        # flags and refusals
        rc, out, err = spark("serve", "off", "--noreload")
        ok(rc == 0 and "not running" in out, "--noreload, an older spelling: off keeps it down anyway", out + err)
        rc, out, err = spark("serve", "on", extra={"SPARK_BASE_URL": "http://192.0.2.9:8080"})
        ok(rc == 78 and "client of" in err, "SPARK_BASE_URL set: serve refuses with 78", err)
        rc, out, err = spark("serve", "--host", "0.0.0.0")
        ok(rc == 78 and "0.0.0.0" in err, "0.0.0.0 refused", err)
        rc, out, err = spark("serve", "--host", "0")
        ok(rc == 78 and "0 is 0.0.0.0, every interface" in err, "0 (the short spelling of 0.0.0.0) refused", err)
        before = kept()
        rc, out, err = spark("serve", "on", extra={"SPARK_MODELS_DIR": tmp + "/nope"})
        ok(rc == 78 and "bootstrap" in err, "no model: exit 78 naming bootstrap", err)
        ok(kept() == before, "no model: serve on keeps nothing (spark.env untouched)", kept())
        rc, out, err = spark("serve", "on", extra={"SPARK_ENGINE_DIR": tmp + "/nope"})
        ok(rc == 78 and "bootstrap" in err, "no engine: exit 78 naming bootstrap", err)
        rc, out, _ = spark("serve", "--print-client")
        ok(rc == 0 and ("SITE_PEER_AI_URL=" + furl) in out and "spark user add NAME" in out and "scp" not in out,
           "--print-client, an older spelling: the page's URL and a user, no scp", out)
        rc, out, _ = spark("serve", "--login")
        ok(rc == 0 and out.splitlines()[0] == furl + "/login" and ("spark client " + furl) in out,
           "serve --login: the page's login URL, then how another machine joins", out)
        rc, out, _ = spark("serve", "bogus")
        ok(rc == 2 and out.startswith("spark serve -- "), "serve with an unknown word: the usage, exit 2", out)

        # two models (real rows from models.env, zero bytes): the router form
        small, big = "Qwen3-1.7B-Q4_K_M.gguf", "Qwen_Qwen3-8B-Q4_K_M.gguf"
        for f in (small, big):
            open(os.path.join(models, f), "w").close()
        router = state + "/router"
        # SITE_AI_BUILD=vulkan: the speed cap then admits the 8b as the ember on a
        # Linux runner too (cpu would cap at 3 GB files; macOS ignores the key)
        renv = {"SITE_AI_MODEL": "auto", "SITE_EMBER_MODEL": "auto", "SPARK_MEM_TOTAL_GB": "18", "SITE_AI_BUILD": "vulkan"}
        rc, out, err = spark("serve", "on", extra=renv)
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
        ok("cache-ram = 0" in spark_sec and "cache-ram = 0" in ember_sec, "both presets: no prompt cache in RAM", ini)
        rc, out, _ = spark("brain", "--porcelain", "--fresh", extra=renv)
        ok(rc == 0 and out.strip() == furl + "\tQwen3-1.7B-Q4_K_M\tforge", "brain names the spark role's file stem", out)
        rc, out, err = spark("serve", "off", extra=renv)
        ok(rc == 0 and "stopped pid" in out, "stop the router", out + err)

        # SITE_EMBER_MODEL=none: the single form, aliased spark + stem
        nenv = {"SITE_AI_MODEL": "auto", "SITE_EMBER_MODEL": "none", "SPARK_MEM_TOTAL_GB": "18"}
        rc, out, err = spark("serve", "on", extra=nenv)
        ok(rc == 0 and "warm   spark\n" in out, "ember none: serves, warms spark alone", out + err)
        argv = json.load(open(home + "/spawned.json"))
        ok("-m" in argv and argv[argv.index("-m") + 1] == os.path.join(models, big) and "--models-dir" not in argv,
           "single form serves the largest fit", argv)
        ok("--alias" in argv and argv[argv.index("--alias") + 1] == "spark,Qwen_Qwen3-8B-Q4_K_M", "aliased spark + file stem", argv)
        ok(not os.path.lexists(router + "/ember.gguf"), "stale ember link removed")
        rc, out, _ = spark("brain", "--porcelain", "--fresh", extra=nenv)
        ok(rc == 0 and out.strip() == furl + "\tQwen_Qwen3-8B-Q4_K_M\tforge", "brain still names the file stem", out)
        spark("serve", "off", extra=nenv)
        rc, out, err = spark("serve", "on", extra={"SITE_EMBER_MODEL": "nosuch"})
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
        rc, out, err = spark("serve", "on", extra={"STUB_LOAD_S": "2", "SPARK_EXTRA_ARGS": "--crash"}, timeout=60)
        ok(rc == 0 and "ready" in out, "loading (503) is waited out", out + err)
        spark("serve", "off")

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
        # v1.64, services that hold -- runit played by an sv stub (SPARK_OS=
        # Linux, SPARK_ETC_RUNIT a dir): `sv up` starts what runsv would,
        # `spark serve --foreground`, and remembers its pid; status answers
        # run/down from it and fail: without supervise/, as runsv would
        svbins = os.path.join(tmp, "svbin")
        os.makedirs(svbins)
        os.makedirs(os.path.join(tmp, "runit"))
        with open(os.path.join(svbins, "sv"), "w") as f:
            f.write('#!/bin/sh\necho "sv $*" >> "$SV_LOG"\nd=$2; pf="$d/stub.pid"\n'
                    'alive() { [ -f "$pf" ] && kill -0 "$(cat "$pf")" 2>/dev/null; }\n'
                    'fg() { "$SPARK_PY" "$SPARK_BIN" serve --foreground >> "$d/fg.log" 2>&1 & echo $! > "$pf"; }\n'
                    'case $1 in\n'
                    '    status) [ -d "$d/supervise" ] || { echo "fail: $d: runsv not running"; exit 1; }\n'
                    '            if alive; then echo "run: $d: (pid $(cat "$pf")) 1s"; else echo "down: $d: 1s, normally up"; fi ;;\n'
                    '    up) alive || fg ;;\n'
                    '    down) if alive; then kill "$(cat "$pf")"; fi ;;\n'
                    '    restart) if alive; then kill "$(cat "$pf")"; sleep 1; fi; fg ;;\n'
                    'esac\nexit 0\n')
        os.chmod(os.path.join(svbins, "sv"), 0o755)
        svlog = os.path.join(tmp, "sv.log")
        svd = home + "/.config/spark/sv/spark-serve"
        unit = {"SPARK_OS": "Linux", "SPARK_ETC_RUNIT": os.path.join(tmp, "runit"), "SV_LOG": svlog,
                "PATH": svbins + ":" + env["PATH"], "SPARK_PY": sys.executable, "SPARK_BIN": SPARK}

        def unit_pid():
            try:
                return int(open(svd + "/stub.pid").read())
            except (OSError, ValueError):
                return 0

        def wait_down(pid, secs=10):
            end = time.time() + secs
            while time.time() < end:
                try:
                    os.kill(pid, 0)
                except OSError:
                    return True
                time.sleep(0.2)
            return False

        # 1. a disabled unit (its down file): `serve on` starts it through
        #    the manager (the down file goes, sv up) and waits on /health;
        #    the server is the unit's, never a Popen beside it
        os.makedirs(svd + "/supervise")
        open(svd + "/down", "w").close()
        rc, out, err = spark("serve", "on", extra=unit)
        sv_calls = open(svlog).read() if os.path.exists(svlog) else ""
        ok(rc == 0 and "ready" in out and ("sv up " + svd) in sv_calls and not os.path.exists(svd + "/down"),
           "a disabled unit: serve on takes the down file away, sv up, waits for ready", out + err + sv_calls)
        ok(get(url + "/health") == 200 and unit_pid() and int(open(state + "/serve.pid").read()) == unit_pid(),
           "the server that answers is the unit's own pid (no Popen beside the unit)", "%s %s" % (unit_pid(), open(state + "/serve.pid").read()))
        up = unit_pid()
        rc, out, err = spark("serve", "off", extra=unit)
        ok(rc == 0 and wait_down(up) and get(url + "/health") == 0 and os.path.exists(svd + "/down")
           and ("sv down " + svd) in open(svlog).read(),
           "the unit's server running: serve off stops it and keeps it down (its down file, sv down)", out + err)

        # 2. the unit down (it stood down) and spark's own server by hand
        #    on the port: serve off stops that one -- the services row's
        #    remedy is this verb, and it used to refuse
        rc, out, err = spark("serve", "on")
        hand = int(open(state + "/serve.pid").read())
        ok(rc == 0 and get(url + "/health") == 200, "a server by hand (no unit in sight)", out + err)
        rc, out, err = spark("serve", "off", extra=unit)
        ok(rc == 0 and ("stopped pid %d" % hand) in out and wait_down(hand), "the unit down: serve off TERMs spark's own hand server", out + err)

        # 3. the unit's --foreground finds spark's own hand server on the
        #    port: it takes over (TERM, then exec), never a 78 that leaves
        #    the unit down for good; a foreign one still gets the 78 (above)
        rc, out, err = spark("serve", "on")
        hand = int(open(state + "/serve.pid").read())
        path = os.path.join(tmp, "takeover.out")
        with open(path, "w") as log:
            fgp = subprocess.Popen([sys.executable, SPARK, "serve", "--foreground"], env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 20
        while time.time() < deadline and not (get(url + "/health") == 200 and os.path.exists(state + "/serve.pid")
                                              and open(state + "/serve.pid").read().strip() == str(fgp.pid)):
            time.sleep(0.3)
        seen = open(path).read()
        ok(wait_down(hand, 1) and fgp.poll() is None and open(state + "/serve.pid").read().strip() == str(fgp.pid)
           and "the unit takes over" in seen,
           "--foreground over spark's own hand server: it takes over (the hand server TERMed, the unit's pid serves)", seen)
        fgp.send_signal(signal.SIGTERM)
        try:
            fgp.wait(timeout=5)
        except subprocess.TimeoutExpired:
            fgp.kill()
        time.sleep(0.5)

        # 4. `spark model NAME`'s restart with a hand server beside a unit
        #    that stood down: the leftover is TERMed after the unit stops,
        #    the unit comes back, and "ready" is the unit's server -- never
        #    the old one still answering (the unit enabled again: serve
        #    off above kept it down)
        os.remove(svd + "/down")
        rc, out, err = spark("serve", "on")
        hand = int(open(state + "/serve.pid").read())
        p = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\nfrom spark import config, model\n"
                            "model._restart_server(config.load())" % os.path.join(REPO, "lib")],
                           capture_output=True, text=True, env=dict(env, **unit), timeout=120)
        ok(p.returncode == 0 and "server       ready" in p.stdout and wait_down(hand, 1) and unit_pid()
           and int(open(state + "/serve.pid").read()) == unit_pid(),
           "a model restart: the hand server beside the unit is TERMed, ready is the unit's own server",
           p.stdout + p.stderr + " hand %d unit %d" % (hand, unit_pid()))
        up = unit_pid()
        spark("serve", "off", "--force", extra=unit)
        ok(wait_down(up) and get(furl + "/api/health") == 0, "the unit's server and the page stopped again")
        shutil.rmtree(home + "/.config/spark/sv")
        latin.kill()
        latin.wait()

    print("serve_smoke: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
