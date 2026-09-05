# spark.bench -- measure the server's throughput with llama-bench (the
# community's tool, shipped with llama.cpp), remember the result as this
# machine's baseline, and find the fastest settings.
#
#   spark bench              pp512 / tg128 -> the measured file's baseline
#                            (the ember when one is served, else the spark model;
#                            --spark / --ember pick a role by hand)
#   spark bench --tune       a small matrix; the winner is kept for `spark tune apply`
#   spark tune show|apply    see or take the winner (spark.env, then a restart)
#
# The server is paused while llama-bench runs: two processes fighting for
# the GPU and the memory would measure nothing.

import json
import os
import subprocess
import time

from . import IS_MAC, MARK, SPARK_ENV, STATE_DIR, config, glyph, say, state_dir
from . import engine, wire

BENCH_LOG = os.path.join(STATE_DIR, "bench.jsonl")
TUNE_FILE = os.path.join(STATE_DIR, "tune.json")
SIZES = {"full": (512, 128, 3), "quick": (256, 64, 2)}


def bench_bin(cfg):
    p = os.path.join(engine.engine_dir(cfg), "llama-bench")
    return p if os.access(p, os.X_OK) else ""


def settings_of(cfg):
    return {"ngl": cfg.ngl, "fa": cfg.flash_attn, "kv": cfg.kv, "t": cfg.threads or ""}


def key_of(s):
    return "ngl=%s fa=%s kv=%s t=%s" % (s["ngl"], s["fa"], s["kv"], s["t"] or "auto")


def _args(s):
    a = ["-ngl", str(s["ngl"]), "-fa", s["fa"], "-ctk", s["kv"], "-ctv", s["kv"]]
    if s.get("t"):
        a += ["-t", str(s["t"])]
    return a


def run_one(cfg, model, s, size):
    """(pp_tps, tg_tps) for one setting, or an EngineError."""
    p, n, r = SIZES[size]
    cmd = [bench_bin(cfg), "-m", model, "-p", str(p), "-n", str(n), "-r", str(r), "-o", "json"] + _args(s)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env=engine.server_env(cfg))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise engine.EngineError("llama-bench failed: %s" % e)
    if out.returncode != 0:
        raise engine.EngineError("llama-bench exited %d: %s" % (out.returncode, out.stderr.strip().splitlines()[-1:] or "?"))
    try:
        rows = json.loads(out.stdout)
    except ValueError:
        raise engine.EngineError("llama-bench printed no JSON")
    pp = tg = 0.0
    for row in rows:
        if row.get("n_prompt", 0) > 0 and row.get("n_gen", 0) == 0:
            pp = float(row.get("avg_ts", 0))
        elif row.get("n_gen", 0) > 0:
            tg = float(row.get("avg_ts", 0))
    return pp, tg


def record(cfg, model, s, size, pp, tg):
    state_dir()
    with open(BENCH_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "model": os.path.basename(model),
                            "engine": engine.engine_dir(cfg), "settings": key_of(s), "size": size,
                            "pp": round(pp, 1), "tg": round(tg, 1)}) + "\n")


def baseline_stem(stem):
    """The best full-size bench of the model whose file stem is `stem`."""
    best = None
    try:
        with open(BENCH_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                name = d.get("model", "")
                if (name[:-5] if name.endswith(".gguf") else name) == stem and d.get("size", "full") == "full":
                    if best is None or d.get("tg", 0) >= best.get("tg", 0):
                        best = d
    except OSError:
        pass
    return best


def baseline(cfg, model=None):
    """This model's baseline: the best full-size bench of it, whatever the
    settings were -- a regression is a regression even when the settings
    changed (that is often the cause). The dict says which settings."""
    model = model or engine.model_file(cfg)
    if not model:
        return None
    name = os.path.basename(model)
    best = None
    try:
        with open(BENCH_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("model") == name and d.get("size", "full") == "full":
                    if best is None or d.get("tg", 0) >= best.get("tg", 0):
                        best = d
    except OSError:
        pass
    return best


# ---------------------------------------------------------- pause / resume
def pause_server(cfg):
    """Stop whatever serves on this machine; return a function that brings
    it back the same way (or None when nothing was running)."""
    st = engine.service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg) == "system":
            # root's daemon: nothing here can stop it; say so and measure beside it
            say(engine.daemon_note(cfg, verb="bootout"))
            return None
        engine.service_stop(noreload=False)
        engine.wait_gone(engine.server_pids(cfg.port), 30)

        def resume():
            engine.kickstart(cfg)
        return resume
    pid = engine.pidfile_pid()
    if pid and pid in engine.server_pids(cfg.port):
        engine.terminate([pid])
        engine.wait_gone([pid], 20)
        engine.forget()

        def resume():
            from . import serve
            serve.cmd_serve([])
        return resume
    return None


# ------------------------------------------------------------------- bench
USAGE = """%s bench -- how fast is this machine, with llama-bench

  spark bench              prompt 512 / generate 128, current settings; saved as
                           the baseline of the measured file -- the ember when
                           one is served, else the spark model (one per file)
  spark bench --spark      measure the spark role (the prompt line's model)
  spark bench --ember      measure the ember; an error when none is served
  spark bench --quick      smaller sizes, fewer repetitions
  spark bench --tune       try GPU/CPU, flash attention, KV types, thread counts
  spark tune show          the last --tune result against what runs now
  spark tune apply         write the winner to spark.env and restart the server
""" % MARK


def _matrix(cfg):
    cur = settings_of(cfg)
    ngls = [cur["ngl"] if cur["ngl"] != "0" else "999", "0"]
    threads = [""] if IS_MAC else sorted({str(max(1, (os.cpu_count() or 2) // 2)), str(os.cpu_count() or 2)})
    rows = []
    for ngl in ngls:
        for fa in ("on", "off"):
            for kv in ("f16", "q8_0"):
                if kv != "f16" and fa != "on":
                    continue        # llama.cpp: a quantized KV cache needs flash attention
                for t in threads:
                    rows.append({"ngl": ngl, "fa": fa, "kv": kv, "t": t})
    if cur not in rows:
        rows.insert(0, cur)
    return rows, cur


def cmd_bench(args):
    if args and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    cfg = config.load()
    tune, porcelain = "--tune" in args, "--porcelain" in args
    size = "quick" if ("--quick" in args or tune) else "full"
    if not bench_bin(cfg):
        say("spark bench: no llama-bench in %s -- ./bootstrap.sh installs the engine" % engine.engine_dir(cfg))
        return engine.EX_CONFIG
    files = engine.roles(cfg)
    want = "ember" if "--ember" in args else ("spark" if "--spark" in args else "")
    if want == "ember" and not files["ember"]:
        say("spark bench: no ember to measure -- spark ember NAME chooses one, ./bootstrap.sh downloads it")
        return engine.EX_CONFIG
    role = want or ("ember" if files["ember"] else "spark")
    model = files[role]
    if not model:
        say("spark bench: no model in %s -- ./bootstrap.sh downloads one" % cfg.models_dir)
        return engine.EX_CONFIG
    resume = pause_server(cfg)
    if resume and not porcelain:
        say("the server is paused while llama-bench runs")
    try:
        if not tune:
            s = settings_of(cfg)
            if not porcelain:
                say("%s bench%s%s (the %s role)%s%s" % (MARK, glyph("sep"), os.path.basename(model), role, glyph("sep"), key_of(s)))
                say("  llama-bench is running -- a few minutes; the numbers print when done ...")
            pp, tg = run_one(cfg, model, s, size)
            record(cfg, model, s, size, pp, tg)
            if porcelain:
                say("%s\t%s\t%.1f\t%.1f" % (os.path.basename(model), key_of(s), pp, tg))
            else:
                p, n, _ = SIZES[size]
                say("  prompt   pp%-4d %7.1f tok/s" % (p, pp))
                say("  generate tg%-4d %7.1f tok/s" % (n, tg))
                say("  saved as the baseline in %s" % BENCH_LOG)
            return 0
        rows, cur = _matrix(cfg)
        if not porcelain:
            say("%s bench --tune%s%s (the %s role)%s%d settings, quick sizes" % (MARK, glyph("sep"), os.path.basename(model), role, glyph("sep"), len(rows)))
            say("  a row prints as each setting finishes -- a few minutes in all ...")
        results = []
        for i, s in enumerate(rows, 1):
            try:
                pp, tg = run_one(cfg, model, s, "quick")
            except engine.EngineError as e:
                pp, tg = 0.0, 0.0
                if not porcelain:
                    say("  %2d/%d %-34s failed: %s" % (i, len(rows), key_of(s), e))
                continue
            results.append((tg, pp, s))
            if not porcelain:
                say("  %2d/%d %-34s pp %6.1f  tg %6.1f%s" % (i, len(rows), key_of(s), pp, tg, "   (current)" if s == cur else ""))
        if not results:
            say("spark bench: every setting failed -- the engine cannot run this file here")
            return 1
        results.sort(key=lambda r: (r[0], r[1]), reverse=True)
        tg, pp, best = results[0]
        # within 5 % of what runs now is noise, not a winner
        now = [r for r in results if r[2] == cur]
        if now and best != cur and tg < now[0][0] * 1.05:
            tg, pp, best = now[0]
        state_dir()
        with open(TUNE_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "model": os.path.basename(model), "current": cur,
                       "winner": best, "winner_pp": round(pp, 1), "winner_tg": round(tg, 1),
                       "table": [{"settings": s, "pp": round(p, 1), "tg": round(t, 1)} for t, p, s in results]}, f)
        if porcelain:
            for t, p, s in results:
                say("%s\t%.1f\t%.1f" % (key_of(s), p, t))
        else:
            say("  winner: %s  (tg %.1f, pp %.1f tok/s)%s" % (key_of(best), tg, pp, "" if best != cur else " -- what you have (nothing beats it by 5 %)"))
            if best != cur:
                say("  spark tune apply   takes it (spark.env, then a restart)")
        return 0
    except engine.EngineError as e:
        say("spark bench: %s" % e)
        return 1
    finally:
        if resume:
            if not porcelain:
                say("the server is coming back -- the model loads again (about 30 s) ...")
            resume()
            url = wire.serve_url() or cfg.loopback_url()
            for _ in range(60):          # the model takes a while to load again
                if wire.health(url) == "ok":
                    break
                time.sleep(2)
            if not porcelain:
                say("the server is back" + ("" if wire.health(url) == "ok" else " (still loading)"))
            from . import check
            check.refresh()


# -------------------------------------------------------------------- tune
def load_tune():
    """The last --tune result, or None."""
    try:
        with open(TUNE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


_load_tune = load_tune


def cmd_tune(args):
    sub = args[0] if args else "show"
    if sub in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    t = load_tune()
    if not t:
        say("%s tune -- nothing measured yet -- spark bench --tune" % MARK)
        return 1
    cfg = config.load()
    cur = settings_of(cfg)
    if sub == "show":
        say("%s tune -- %s, %s" % (MARK, t["model"], t["ts"]))
        say("  now:    %s" % key_of(cur))
        say("  winner: %s  (tg %.1f, pp %.1f tok/s)" % (key_of(t["winner"]), t["winner_tg"], t["winner_pp"]))
        for row in t["table"][:6]:
            say("    %-34s pp %6.1f  tg %6.1f" % (key_of(row["settings"]), row["pp"], row["tg"]))
        say("  the knobs are SPARK_NGL SPARK_FLASH_ATTN SPARK_KV SPARK_THREADS in ~/.config/spark/spark.env")
        return 0
    if sub == "apply":
        from . import site
        w = t["winner"]
        site.set_keys(_file=SPARK_ENV, SPARK_NGL=w["ngl"], SPARK_FLASH_ATTN=w["fa"], SPARK_KV=w["kv"], SPARK_THREADS=w.get("t", ""))
        site._restart_server(cfg)     # narrates: restarting ... ready
        return 0
    say(USAGE.rstrip())
    return 2


def main(sub, args):
    return cmd_bench(args) if sub == "bench" else cmd_tune(args)
