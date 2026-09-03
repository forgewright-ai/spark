#!/usr/bin/env python3
# spark tests/bench_smoke.py -- `spark bench`, `--tune` and `spark tune apply`
# against a stub llama-bench that answers faster for GPU layers, flash
# attention on, a q8_0 KV cache and more threads, so the matrix has a
# winner. Hermetic: no model, no engine, no service manager.

import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARK = os.path.join(REPO, "bin", "spark")

STUB_BENCH = '''#!%s
# a stand-in llama-bench: JSON rows shaped like the real ones, faster for
# the settings a GPU box prefers
import json, sys
a = sys.argv[1:]
def opt(n, d):
    return a[a.index(n) + 1] if n in a else d
ngl, fa, kv, t = int(opt("-ngl", "999")), opt("-fa", "auto"), opt("-ctk", "f16"), int(opt("-t", "4"))
pp = 100.0 + (60 if ngl > 0 else 0) + (10 if fa == "on" else 0) + t
tg = 10.0 + (5 if ngl > 0 else 0) + (2 if kv == "q8_0" else 0) + (1 if fa == "on" else 0) + t / 10.0
print(json.dumps([{"n_prompt": int(opt("-p", "512")), "n_gen": 0, "avg_ts": pp},
                  {"n_prompt": 0, "n_gen": int(opt("-n", "128")), "avg_ts": tg}]))
''' % sys.executable


def main():
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + str(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    with tempfile.TemporaryDirectory(prefix="spark-bench-") as tmp:
        home, eng, models, bins = (os.path.join(tmp, d) for d in ("home", "engine", "models", "bin"))
        for d in (home, eng, models, bins, os.path.join(home, ".config", "spark")):
            os.makedirs(d)
        with open(os.path.join(eng, "llama-bench"), "w") as f:
            f.write(STUB_BENCH)
        os.chmod(os.path.join(eng, "llama-bench"), 0o755)
        with open(os.path.join(eng, "llama-server"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(eng, "llama-server"), 0o755)
        for name in ("launchctl", "systemctl"):
            with open(os.path.join(bins, name), "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(os.path.join(bins, name), 0o755)
        with open(os.path.join(models, "stub.gguf"), "w") as f:
            f.write("gguf" * 64)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SPARK_", "XDG_", "SITE_"))}
        env.update({"HOME": home, "XDG_CONFIG_HOME": home + "/.config", "XDG_STATE_HOME": home + "/.local/state",
                    "XDG_DATA_HOME": home + "/.local/share", "PATH": bins + ":" + env.get("PATH", ""),
                    "SPARK_ENGINE_DIR": eng, "SPARK_MODELS_DIR": models, "SPARK_SERVICE": "none",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color"})
        state = home + "/.local/state/spark"

        def spark(*args, extra=None):
            e = dict(env)
            e.update(extra or {})
            p = subprocess.run([sys.executable, SPARK] + list(args), capture_output=True, text=True, env=e, timeout=120)
            return p.returncode, p.stdout, p.stderr

        print("bench_smoke: HOME %s" % home)
        rc, out, err = spark("bench")
        ok(rc == 0 and "pp512" in out and "tg128" in out, "spark bench runs llama-bench with the current settings", out + err)
        ok(os.path.exists(state + "/bench.jsonl"), "bench.jsonl written")
        row = json.loads(open(state + "/bench.jsonl").read().splitlines()[-1])
        ok(row["settings"] == "ngl=999 fa=auto kv=f16 t=auto" and row["tg"] == 15.4, "baseline row: settings and tg", row)
        rc, out, _ = spark("bench", "--porcelain")
        ok(rc == 0 and out.startswith("stub.gguf\tngl=999 fa=auto kv=f16 t=auto\t"), "bench --porcelain", out)
        rc, out, _ = spark("stats", "--porcelain")
        ok("baseline_tg\t15.4" in out, "stats shows the baseline", out)

        rc, out, _ = spark("bench", "--tune")
        ok(rc == 0 and "winner:" in out and "ngl=999 fa=on kv=q8_0" in out.split("winner:")[1], "tune finds GPU + flash attention + q8_0", out)
        t = json.load(open(state + "/tune.json"))
        ok(t["winner"]["fa"] == "on" and t["winner"]["kv"] == "q8_0" and t["winner"]["ngl"] == "999", "tune.json holds the winner", t["winner"])
        rc, out, _ = spark("tune", "show")
        ok(rc == 0 and "winner:" in out and "now:" in out, "tune show", out)
        rc, out, _ = spark("tune", "apply")
        ok(rc == 0 and "not running" in out, "tune apply with no server: writes only", out)
        envf = open(home + "/.config/spark/spark.env").read()
        ok("SPARK_FLASH_ATTN=on" in envf and "SPARK_KV=q8_0" in envf and "SPARK_NGL=999" in envf, "spark.env carries the winner", envf)
        ok(oct(os.stat(home + "/.config/spark/spark.env").st_mode & 0o777) == "0o600", "spark.env is 0600")
        rc, out, _ = spark("bench", "--porcelain")
        ok(rc == 0 and "fa=on kv=q8_0" in out, "the next bench measures the applied settings", out)
        rc, out, _ = spark("model")
        ok(rc == 0 and "qwen3-4b" in out and "not in models.env" in out, "spark model lists the table and the stray stub.gguf", out)
        rc, out, _ = spark("model", "qwen3-4b", extra={"SPARK_NO_APPLY": "1"})
        ok(rc == 0 and "SITE_AI_MODEL=qwen3-4b" in out, "spark model NAME writes the choice", out)
        ok("restarting" not in out and "download" not in out,
           "SPARK_NO_APPLY: the key only -- no restart or download narration", out)
        rc, out, _ = spark("model", "nope")
        ok(rc == 2 and "no model named" in out, "unknown model refused", out)
        rc, out, _ = spark("model", "rm", "qwen3-8b")
        ok(rc == 1 and "not downloaded" in out, "rm of a model not on disk", out)

        # the two roles: the ember is measured by default, --spark the line model
        rc, out, _ = spark("bench", "--ember")
        ok(rc == 78 and "ember" in out, "--ember with none served: exit 78 naming spark ember", out)
        for fname in ("Qwen3-1.7B-Q4_K_M.gguf", "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"):
            with open(os.path.join(models, fname), "w") as f:
                f.write("gguf" * 64)
        roles = {"SITE_AI_MODEL": "qwen3-1-7b", "SITE_EMBER_MODEL": "qwen3-4b", "SPARK_MEM_TOTAL_GB": "64"}
        rc, out, _ = spark("bench", "--porcelain", extra=roles)
        ok(rc == 0 and out.startswith("Qwen_Qwen3-4B"), "bench measures the ember by default", out)
        rc, out, _ = spark("bench", "--spark", "--porcelain", extra=roles)
        ok(rc == 0 and out.startswith("Qwen3-1.7B"), "bench --spark measures the line model", out)
        rc, out, _ = spark("bench", "--ember", extra=roles)
        ok(rc == 0 and "(the ember role)" in out, "bench --ember says which role it measures", out)
        rc, out, _ = spark("bench", extra={"SPARK_ENGINE_DIR": tmp + "/nope"})
        ok(rc == 78 and "bootstrap" in out, "no engine: exit 78 naming bootstrap", out)

    print("bench_smoke: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
