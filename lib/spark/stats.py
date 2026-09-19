# spark.stats -- what the turns on disk say about throughput, and what the
# server and the GPU say right now. Numbers only; nothing new is sent.

import json
import os
import time

from . import IS_MAC, MARK, TURNS_DIR, config, glyph, paged, say
from . import bench, engine, wire

WINDOWS = {"--today": 1, "--week": 7, "--all": 3650}

USAGE = """%s stats -- throughput from the turns on disk

  spark stats                  today: tok/s, latency, cache hits by mode, baseline
  spark stats --week | --all   a wider window
  spark stats --sends          what left, in bytes: by destination and day,
                               the last 7 days (local = this machine)
  spark stats --porcelain      key<TAB>value lines; with --sends,
                               day<TAB>destination<TAB>bytes<TAB>turns
""" % MARK

SENDS_DAYS = 7


def turns(days):
    """Turns recorded in the last `days` days, oldest first."""
    out = []
    cutoff = time.time() - days * 86400
    try:
        names = sorted(n for n in os.listdir(TURNS_DIR) if n.endswith(".jsonl"))
    except OSError:
        return out
    for name in names:
        try:
            if time.mktime(time.strptime(name[:-6], "%Y-%m-%d")) < cutoff - 86400:
                continue
            with open(os.path.join(TURNS_DIR, name), encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        except (OSError, ValueError):
            pass
    return out


def pct(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, int(round(q * (len(xs) - 1))))
    return xs[i]


def summarise(rows):
    tg = [t["tg_tps"] for t in rows if t.get("tg_tps")]
    pp = [t["pp_tps"] for t in rows if t.get("pp_tps")]
    ms = [t["ms"] for t in rows if isinstance(t.get("ms"), (int, float))]
    pn = sum(t.get("pp_n", 0) for t in rows)
    cn = sum(t.get("cache_n", 0) for t in rows)
    return {"turns": len(rows), "tg_mean": sum(tg) / len(tg) if tg else 0, "tg_p50": pct(tg, 0.5), "tg_p05": pct(tg, 0.05),
            "pp_mean": sum(pp) / len(pp) if pp else 0, "ms_p50": pct(ms, 0.5), "ms_p95": pct(ms, 0.95),
            "cache": (100.0 * cn / (cn + pn)) if (cn + pn) else 0, "modes": by_mode(rows)}


def by_mode(rows):
    """[(mode, {turns, cache, ms_p50, first_p50})], most turns first: the
    prompt cache is a property of a mode's request shape (the line's
    short prefix hits nearly always; a read carries a 16 kB source), so
    one number over every turn hides the one that matters. first_p50 is
    the median wait to the first kept line where a mode records it
    (spark read), else 0."""
    groups = {}
    for t in rows:
        groups.setdefault(t.get("mode") or "?", []).append(t)
    out = []
    for mode, v in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        pn = sum(t.get("pp_n", 0) for t in v)
        cn = sum(t.get("cache_n", 0) for t in v)
        ms = [t["ms"] for t in v if isinstance(t.get("ms"), (int, float))]
        first = [t["first_ms"] for t in v if isinstance(t.get("first_ms"), (int, float))]
        out.append((mode, {"turns": len(v), "cache": (100.0 * cn / (cn + pn)) if (cn + pn) else 0,
                           "ms_p50": pct(ms, 0.5), "first_p50": pct(first, 0.5)}))
    return out


def sends(rows):
    """[(day, dest, bytes, turns)] of the turns that carry `out_bytes` --
    what left this machine, where, per day (wire._sent's pair on the
    record): newest day first, the heaviest destination first within it.
    A record from before the count was kept has no `out_bytes` and is
    not a send here."""
    acc = {}
    for t in rows:
        n = t.get("out_bytes")
        if not isinstance(n, int) or isinstance(n, bool):
            continue
        key = (str(t.get("ts", ""))[:10], str(t.get("dest") or "?"))
        b, c = acc.get(key, (0, 0))
        acc[key] = (b + n, c + 1)
    out = [(day, dest, b, c) for (day, dest), (b, c) in acc.items()]
    out.sort(key=lambda r: (-r[2], r[1]))
    out.sort(key=lambda r: r[0], reverse=True)
    return out


def kb(n):
    return "%.1f kB" % (n / 1000.0)


def running_settings(cfg):
    """The tuning flags of the llama-server that runs here, from its command line."""
    from . import run
    rc, out = run(["ps", "-axo", "command="])
    for line in out.splitlines():
        if "llama-server" in line and "--port %d" % cfg.port in line:
            a = line.split()

            def opt(name, default):
                return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default
            return {"ngl": opt("-ngl", "?"), "fa": opt("-fa", "auto"), "kv": opt("-ctk", "f16"), "t": opt("-t", "")}
    return None


def main(argv):
    if argv and argv[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    report = _sends if "--sends" in argv else _report
    if "--porcelain" in argv:
        return report(argv)        # porcelain never pages
    return paged(lambda: report(argv))


def _sends(argv):
    """Bytes out by destination and day, the last SENDS_DAYS days: the
    turn records' own count (nothing is measured now, nothing is sent)."""
    rows = sends(turns(SENDS_DAYS))
    if "--porcelain" in argv:
        for day, dest, b, c in rows:
            say("%s\t%s\t%d\t%d" % (day, dest, b, c))
        return 0
    say("%s stats%ssends, last %d days" % (MARK, glyph("sep"), SENDS_DAYS))
    if not rows:
        say("  nothing sent in the last %d days -- ask something at the prompt" % SENDS_DAYS)
        return 0
    say("  %-12s %-28s %10s %6s" % ("day", "destination", "kB", "turns"))
    for day, dest, b, c in rows:
        say("  %-12s %-28s %10.1f %6d" % (day, dest[:28], b / 1000.0, c))
    return 0


def _report(argv):
    days = 1
    for a in argv:
        if a in WINDOWS:
            days = WINDOWS[a]
    porcelain = "--porcelain" in argv
    cfg = config.load()
    rows = turns(days)
    s = summarise(rows)
    base = bench.baseline(cfg)
    sep = glyph("sep")
    if porcelain:
        say("turns\t%d" % s["turns"])
        say("tg_mean\t%.1f" % s["tg_mean"])
        say("tg_p50\t%.1f" % s["tg_p50"])
        say("pp_mean\t%.1f" % s["pp_mean"])
        say("ms_p50\t%d" % s["ms_p50"])
        say("ms_p95\t%d" % s["ms_p95"])
        say("cache_pct\t%.0f" % s["cache"])
        for mode, m in s["modes"]:
            say("mode_%s\tturns=%d cache_pct=%.0f ms_p50=%d first_p50=%d" % (mode, m["turns"], m["cache"], m["ms_p50"], m["first_p50"]))
        say("baseline_tg\t%s" % (base["tg"] if base else ""))
        g = engine.gpu_info()
        if g:
            say("gpu_busy\t%s" % g.get("busy", ""))
            say("vram_total\t%s" % g.get("vram_total", ""))
        return 0
    label = {1: "today", 7: "this week", 3650: "all time"}[days]
    say("%s stats%s%s" % (MARK, sep, label))
    if not s["turns"]:
        say("  no turns yet -- ask something at the prompt")
    else:
        say("  turns       %d" % s["turns"])
        say("  generate    %.1f tok/s mean, %.1f p50, %.1f p05" % (s["tg_mean"], s["tg_p50"], s["tg_p05"]))
        say("  prompt      %.0f tok/s mean, %.0f%% of prompt tokens from the cache" % (s["pp_mean"], s["cache"]))
        say("  latency     %.1f s p50, %.1f s p95" % (s["ms_p50"] / 1000.0, s["ms_p95"] / 1000.0))
        # per mode: the cache hit rate is where a slow rerun shows -- a read
        # that carries its source again and hits 0 % is paying the prefill
        # twice; first line is the wait a reader feels (spark read keeps it)
        say("  by mode     %-12s %5s %6s %8s %10s" % ("", "turns", "cache", "p50", "first line"))
        for mode, m in s["modes"]:
            say("              %-12s %5d %5.0f%% %6.1f s %s" % (
                mode, m["turns"], m["cache"], m["ms_p50"] / 1000.0,
                "%8.1f s" % (m["first_p50"] / 1000.0) if m["first_p50"] else "%10s" % "-"))
        by = {}
        for t in rows:
            k = "%s (%s)" % (t.get("backend", "?").split("//")[-1], t.get("model", "?"))
            by.setdefault(k, []).append(t)
        if len(by) > 1:
            for k, v in by.items():
                ss = summarise(v)
                say("    %-44s %3d turns, %.1f tok/s" % (k, ss["turns"], ss["tg_mean"]))
    if base:
        line = "  baseline    %.1f tok/s generate, %.1f prompt (spark bench, %s)" % (base["tg"], base["pp"], base["ts"][:10])
        bstem = base.get("model", "")
        bstem = bstem[:-5] if bstem.endswith(".gguf") else bstem
        mine = [t for t in rows if t.get("tg_tps") and t.get("model", bstem) == bstem]
        if mine and base["tg"]:
            mm = sum(t["tg_tps"] for t in mine) / len(mine)
            line += "  -- its turns now %d%% of it" % round(100 * mm / base["tg"])
        say(line)
    else:
        say("  baseline    none yet -- spark bench")
    try:
        url, model, _forge = wire.resolve_brain(cfg)
        rs = running_settings(cfg)
        say("  server      %s  %s%s" % (url.split("//")[-1], model, ("  " + bench.key_of(rs)) if rs else ""))
    except wire.BrainError as e:
        say("  server      " + e.hint)
    g = engine.gpu_info()
    if g:
        say("  gpu         %s%% busy, vram %.1f/%.1f GB, gtt %.1f/%.1f GB" % (
            g.get("busy", 0), g.get("vram_used", 0) / 2**30, g.get("vram_total", 0) / 2**30,
            g.get("gtt_used", 0) / 2**30, g.get("gtt_total", 0) / 2**30))
    elif IS_MAC:
        say("  gpu         not readable without root on macOS")
    return 0
