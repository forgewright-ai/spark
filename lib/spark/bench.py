# spark.bench -- measure the server's throughput with llama-bench (the
# community's tool, shipped with llama.cpp), remember the result as this
# machine's baseline, and find the fastest settings.
#
#   spark bench              pp512 / tg128 -> the measured file's baseline
#                            (the ember when one is served, else the spark model;
#                            --spark / --ember pick a role by hand)
#   spark bench tune         a small matrix; the winner is kept for `spark bench tune apply`
#   spark tune show|apply    see or take the winner (spark.env, then a restart)
#   spark bench --line [N]   N prompt-line questions through the real `spark
#                            line`, timed as the widget sees them: the line pace
#
# The server is paused while llama-bench runs: two processes fighting for
# the GPU and the memory would measure nothing. --line is the opposite:
# it measures the served model, so nothing is paused.

import json
import os
import select
import statistics
import subprocess
import sys
import tempfile
import time

from . import IS_MAC, MARK, REPO, SPARK_ENV, STATE_DIR, config, glyph, say, state_dir
from . import engine, wire

BENCH_LOG = os.path.join(STATE_DIR, "bench.jsonl")
TUNE_FILE = os.path.join(STATE_DIR, "tune.json")
SIZES = {"full": (512, 128, 3), "quick": (256, 64, 2)}


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
    cmd = [engine.bench_bin(cfg), "-m", model, "-p", str(p), "-n", str(n), "-r", str(r), "-o", "json"] + _args(s)
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
    fd = os.open(BENCH_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
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

  spark bench              prompt 512 / generate 128, current settings; saved
                           as the baseline of the measured file (the chat
                           model when one is served, else the spark model)
  spark bench --spark      measure the spark role (the prompt line's model)
  spark bench --ember      measure the chat model; an error when none is served
  spark bench --quick      smaller sizes, fewer repetitions
  spark bench --line [N]   N prompt-line questions (5 by default) through
                           spark line, against the served model: command
                           ready, whole answer, warm slots; saved as the
                           line pace that spark stats shows
  spark bench tune         try GPU/CPU, flash attention, KV types, thread counts
  spark bench tune show    the last tune's result against what runs now
  spark bench tune apply   write the winner to spark.env and restart the engine
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
    if "--line" in args:
        return cmd_line_bench(cfg, args)
    tune, porcelain = "--tune" in args, "--porcelain" in args
    size = "quick" if ("--quick" in args or tune) else "full"
    if not engine.bench_bin(cfg):
        say("spark bench: no llama-bench in %s -- ./bootstrap.sh installs the engine" % engine.engine_dir(cfg))
        return engine.EX_CONFIG
    files = engine.roles(cfg)
    want = "ember" if "--ember" in args else ("spark" if "--spark" in args else "")
    if want == "ember" and not files["ember"]:
        say("spark bench: no chat model to measure -- spark ember NAME chooses one, ./bootstrap.sh downloads it")
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


# -------------------------------------------------------------------- line
# The prompt line's own pace: the wait a person feels between Enter and a
# command in the buffer. llama-bench measures the engine; this measures
# the whole path the widget takes -- a fresh `spark line` process, the
# brain, the guards, the lines on stdout. Five everyday questions, each
# one read-only, and nothing they propose is ever run here. Each is a
# turn and a thread, like a question asked at the prompt line.
LINE_QUESTIONS = (
    "how much disk does this use",
    "the biggest files here",
    "which ports are listening",
    "which groups am I in",
    "which kernel is running",
)
LINE_MAX = 20           # a pace, not a soak test
LINE_DEADLINE = 180     # seconds one question may take before it is killed
WARM_READ = 64          # prompt tokens read below this: the slot kept the prefix


def _line_count(args):
    """N after --line (5 without one), or None when it is not 1..LINE_MAX."""
    i = args.index("--line")
    if i + 1 < len(args) and not args[i + 1].startswith("-"):
        try:
            n = int(args[i + 1])
        except ValueError:
            return None
        return n if 1 <= n <= LINE_MAX else None
    return len(LINE_QUESTIONS)


def time_line(words, cwd, shell, deadline=LINE_DEADLINE):
    """One `spark line` exactly as the widget calls it (the words on
    stdin, --cwd, --shell) -> (ready, total, rc, first line). `ready` is
    when line 1 reached the caller -- the command, ready to paint --
    stamped on the first newline read, None when none came; `total` is
    EOF. Seconds, the caller's clock."""
    cmd = [sys.executable, os.path.join(REPO, "bin", "spark"), "line", "--cwd", cwd, "--shell", shell]
    env = dict(os.environ)
    env.pop("SPARK_HINT_ROW", None)     # the table owns this terminal: no pulse above it
    env["SPARK_LINE_BENCH"] = "1"       # numbers kept, marked bench; no thread in the person's history
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, cwd=cwd, env=env)
    try:
        p.stdin.write(words.encode("utf-8"))
        p.stdin.close()
    except OSError:
        pass
    fd, buf, ready = p.stdout.fileno(), b"", None
    while True:
        left = t0 + deadline - time.monotonic()
        if left <= 0:
            p.kill()
            break
        if not select.select([fd], [], [], left)[0]:
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        buf += chunk
        if ready is None and b"\n" in buf:
            ready = time.monotonic() - t0
    p.stdout.close()
    rc = p.wait()
    total = time.monotonic() - t0
    return ready, total, rc, buf.decode("utf-8", "replace").split("\n", 1)[0]


def _slot(t):
    """"warm" when the turn read few prompt tokens (the slot held the
    prefix), "cold" when it read the prefix again, None when unknown
    (no turn record: SPARK_HISTORY=off, or a server that sends no
    timings)."""
    n = t.get("pp_n") if t else None
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return None
    return "warm" if n < WARM_READ else "cold"


def line_words(d):
    """A line pace record in the words spark stats and the check print."""
    return "command ready %.2f s, whole answer %.2f s, %s" % (
        d.get("ready_ms", 0) / 1000.0, d.get("total_ms", 0) / 1000.0,
        ("%d warm of %d" % (d.get("warm", 0), d["known"])) if d.get("known") else "slots not recorded")


def knowledge_fields(turns):
    """What the knowledge index did on these line turns, from the fields
    the prompt line records when it looks: `know_ms` (the retrieval),
    `evidence_chars` (what rode the request) and `reasked` (the one
    re-ask after a check). Medians and a count; a field no turn carries
    is left out, so a spark without the index says nothing."""
    turns = [t for t in turns if t]
    rec = {}
    for key, name in (("know_ms", "know_ms"), ("evidence_chars", "evidence")):
        v = _median([t[key] for t in turns if isinstance(t.get(key), (int, float)) and not isinstance(t.get(key), bool)])
        if v is not None:
            rec[name] = v
    asked = [t for t in turns if "reasked" in t]
    if asked:
        rec["reasked"] = sum(1 for t in asked if t["reasked"])
        rec["reask_of"] = len(asked)
    return rec


def knowledge_words(d):
    """The knowledge lines of a line record, in the words the report prints;
    [] when the record holds none."""
    parts = []
    if "know_ms" in d:
        parts.append("searched the index in %d ms" % d["know_ms"])
    if "evidence" in d:
        parts.append("sent %d characters of evidence" % d["evidence"])
    out = []
    if parts:
        out.append("spark %s (%s)" % (" and ".join(parts), "medians" if len(parts) > 1 else "the median"))
    if "reasked" in d:
        out.append("spark asked the model again on %d of %d questions" % (d["reasked"], d["reask_of"]))
    return out


def line_pace():
    """The newest `spark bench --line` record, or None."""
    best = None
    try:
        with open(BENCH_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("size") == "line":
                    best = d
    except OSError:
        pass
    return best


def _median(xs):
    return int(statistics.median(xs)) if xs else None


def cmd_line_bench(cfg, args):
    from . import session
    porcelain = "--porcelain" in args
    n = _line_count(args)
    if n is None:
        say("spark bench -- --line takes a count, 1 to %d (the questions to ask)" % LINE_MAX)
        return 2
    try:
        _url, model, _forge = wire.resolve_brain(cfg)
    except wire.BrainError as e:
        say("spark bench -- nothing answers the prompt line: %s" % e.hint)
        return 1
    shell = os.path.basename(os.environ.get("SHELL") or "sh")
    fmt = "  %2s  %-30s %7s %7s %6s %6s  %s"
    if not porcelain:
        sep = glyph("sep")
        say("%s bench --line%s%s (the spark model)%s%d questions" % (MARK, sep, model, sep, n))
        say("  each runs through spark line as the prompt line asks it; nothing runs")
        say(fmt % ("", "question", "ready", "whole", "read", "wrote", "slot"))
    rows = []
    with tempfile.TemporaryDirectory(prefix="spark-bench-") as scratch:
        for i in range(n):
            q = LINE_QUESTIONS[i % len(LINE_QUESTIONS)]
            before = session.last_turn()
            ready, total, rc, first = time_line("? " + q, scratch, shell)
            t = session.last_turn()
            t = t if (t and t != before and t.get("mode") == "line") else None
            ok = rc == 0 and ready is not None and first.split("\t")[0] in ("cmd", "danger", "answer")
            pp = t.get("pp_n") if t else None
            tg = t.get("tg_n") if t else None
            rows.append({"ok": ok, "ready": ready, "total": total, "t": t, "slot": _slot(t)})
            slot = (rows[-1]["slot"] or "-") if ok else "error"
            if porcelain:
                say("\t".join([str(i + 1), "%d" % (ready * 1000) if ok else "", "%d" % (total * 1000),
                               "" if pp is None else str(pp), "" if tg is None else str(tg), slot]))
            else:
                say(fmt % (i + 1, q[:30], "%.2f s" % ready if ok else "-", "%.2f s" % total,
                           "-" if pp is None else pp, "-" if tg is None else tg, slot))
    good = [r for r in rows if r["ok"]]
    if not good:
        say("spark bench -- no question got an answer: spark line shows why (echo '? which kernel' | spark line)")
        return 1
    known = [r for r in good if r["slot"]]

    def field(key):
        return _median([r["t"][key] for r in good if r["t"] and isinstance(r["t"].get(key), (int, float))])
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "size": "line",
           "model": next((r["t"]["model"] for r in good if r["t"] and r["t"].get("model")), model),
           "n": len(rows), "answered": len(good),
           "ready_ms": _median([r["ready"] * 1000 for r in good]),
           "total_ms": _median([r["total"] * 1000 for r in good]),
           "warm": sum(1 for r in known if r["slot"] == "warm"), "known": len(known)}
    # cmd_ms: spark line's own clock to line 1, where its turn record
    # keeps it; the caller's `ready` less this is the process start
    for key, name in (("pp_n", "read"), ("tg_n", "wrote"), ("cmd_ms", "cmd_ms")):
        v = field(key)
        if v is not None:
            rec[name] = v
    rec.update(knowledge_fields([r["t"] for r in good]))
    state_dir()
    fd = os.open(BENCH_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    if porcelain:
        say("\t".join(["median", str(rec["ready_ms"]), str(rec["total_ms"]), str(rec.get("read", "")),
                       str(rec.get("wrote", "")), "%d/%d" % (rec["warm"], rec["known"])]))
        if any(k in rec for k in ("know_ms", "evidence", "reasked")):
            say("\t".join(["knowledge", str(rec.get("know_ms", "")), str(rec.get("evidence", "")),
                           "%d/%d" % (rec["reasked"], rec["reask_of"]) if "reasked" in rec else ""]))
        return 0
    say((fmt % ("", "median", "%.2f s" % (rec["ready_ms"] / 1000.0), "%.2f s" % (rec["total_ms"] / 1000.0),
                rec.get("read", "-"), rec.get("wrote", "-"), "")).rstrip())
    say("  the line pace: " + line_words(rec))
    if "cmd_ms" in rec:
        say("  inside spark line the command was ready at %.2f s, by its own clock" % (rec["cmd_ms"] / 1000.0))
    for words in knowledge_words(rec):
        say("  " + words)
    if len(good) < len(rows):
        say("  %d of %d questions got an error; the medians are of the rest" % (len(rows) - len(good), len(rows)))
    say("  saved in %s -- spark stats shows it" % BENCH_LOG)
    return 0


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
        say("%s bench tune -- nothing measured yet -- spark bench tune" % MARK)
        return 1
    cfg = config.load()
    cur = settings_of(cfg)
    if sub == "show":
        say("%s bench tune -- %s, %s" % (MARK, t["model"], t["ts"]))
        say("  now:    %s" % key_of(cur))
        say("  winner: %s  (tg %.1f, pp %.1f tok/s)" % (key_of(t["winner"]), t["winner_tg"], t["winner_pp"]))
        for row in t["table"][:6]:
            say("    %-34s pp %6.1f  tg %6.1f" % (key_of(row["settings"]), row["pp"], row["tg"]))
        say("  the knobs are SPARK_NGL SPARK_FLASH_ATTN SPARK_KV SPARK_THREADS in ~/.config/spark/spark.env")
        return 0
    if sub == "apply":
        from . import model, site
        w = t["winner"]
        site.set_keys(_file=SPARK_ENV, SPARK_NGL=w["ngl"], SPARK_FLASH_ATTN=w["fa"], SPARK_KV=w["kv"], SPARK_THREADS=w.get("t", ""))
        model._restart_server(cfg)     # narrates: restarting ... ready
        return 0
    say(USAGE.rstrip())
    return 2


def main(sub, args):
    """`tune` is a sub-noun of bench, not a verb of its own: one thing the
    tool does, reached one way (the grammar, rule 3). `spark bench tune`
    measures, the way `spark bench` does; `show` and `apply` read the
    result of the last one."""
    if args and args[0] == "tune":
        rest = args[1:]
        if rest and rest[0] in ("show", "apply", "-h", "--help", "help"):
            return cmd_tune(rest)
        return cmd_bench(["--tune"] + rest)
    return cmd_bench(args)
