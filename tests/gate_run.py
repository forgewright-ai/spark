#!/usr/bin/env python3
"""spark tests/gate_run.py -- the full gate's suites, side by side.

  python3 tests/gate_run.py QUEUE FAILED   run QUEUE's suites; write the
                                           labels that failed to FAILED
  python3 tests/gate_run.py --selftest     prove it on stand-in suites

tests/gate.sh full writes QUEUE: one suite a line, `label<TAB>command`,
the command one argv in shell quotes (its `run` lines, collected). The
suites run SPARK_GATE_JOBS at a time, the CPU count by default: their
ports come from bind(0), and most of their time is waiting, so they
overlap. The longest go first, by the seconds each took
last time (~/.cache/spark/gate-times, a label and its seconds a line,
outside the tree); a suite never timed goes before them all. Each suite's
output is printed whole under its `== label` line when it ends, so no two
logs interleave. With SPARK_GATE_FAIL_FAST set, no suite starts after one
has failed. Python 3.9, the standard library alone.
"""
import concurrent.futures
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time

TIMES = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"),
                     "spark", "gate-times")


def jobs():
    try:
        n = int(os.environ.get("SPARK_GATE_JOBS", ""))
    except ValueError:
        n = 0
    return n if n > 0 else os.cpu_count() or 1


def load_times(path):
    times = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                label, _, secs = line.rstrip("\n").rpartition("\t")
                try:
                    times[label] = float(secs)
                except ValueError:
                    pass
    except OSError:
        pass
    return times


def save_times(times, path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.writelines("%s\t%.1f\n" % (label, times[label]) for label in sorted(times))
        os.replace(path + ".tmp", path)
    except OSError:
        pass                    # a ledger that cannot be kept only loses the order


def run_all(suites, n, times, fail_fast=False, out=sys.stdout):
    """[(label, argv)] n at a time, the longest first; `times` takes each
    one's seconds. Returns (the labels that failed, the wall seconds)."""
    order = sorted(suites, key=lambda s: -times.get(s[0], float("inf")))
    lock, failed, stop = threading.Lock(), [], threading.Event()

    def one(suite):
        label, argv = suite
        if stop.is_set():
            return
        t0 = time.monotonic()
        with tempfile.TemporaryFile() as log:
            rc = subprocess.call(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            secs = time.monotonic() - t0
            log.seek(0)
            text = log.read().decode("utf-8", "replace")
        with lock:
            times[label] = secs
            out.write("== %s  (%.0f s)\n%s%s" % (label, secs, text, "" if text.endswith("\n") or not text else "\n"))
            out.flush()
            if rc != 0:
                failed.append(label)
                if fail_fast:
                    stop.set()

    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(one, order))
    return failed, time.monotonic() - t0


def selftest():
    import io
    py = sys.executable
    bad = []

    def check(cond, what):
        print("  %s %s" % ("ok  " if cond else "FAIL", what))
        if not cond:
            bad.append(what)

    def sleeper(word, secs, rc=0):
        return [py, "-c", "import sys, time\nfor i in range(3):\n    print(%r, i)\n    sys.stdout.flush()\n"
                "    time.sleep(%s)\nsys.exit(%d)" % (word, secs / 3, rc)]

    suites = [("a", sleeper("a", 0.6)), ("b", sleeper("b", 0.6)), ("c", sleeper("c", 0.6, rc=1)), ("d", sleeper("d", 0.6))]
    out, times = io.StringIO(), {"a": 1.0, "b": 9.0, "c": 5.0}
    failed, wall = run_all(suites, 4, times, out=out)
    text = out.getvalue()
    check(failed == ["c"], "the one that failed, and only it, is named")
    check(wall < 1.5, "four suites of 0.6 s, four at a time, take less than two of them (%.2f s)" % wall)
    blocks = [b.splitlines() for b in text.split("== ")[1:]]
    check(len(blocks) == 4 and all(len(b) == 4 and all(ln.startswith(b[0][0] + " ") for ln in b[1:]) for b in blocks),
          "each log is printed whole under its own label, never interleaved")
    check(all(0.5 < times[k] < 1.5 for k in "abcd"), "every suite's seconds are kept")

    out, order = io.StringIO(), []
    run_all([(k, [py, "-c", "pass"]) for k in "abcd"], 1, {"a": 1.0, "b": 9.0, "c": 5.0}, out=out)
    order = [b.split()[0] for b in out.getvalue().split("== ")[1:]]
    check(order == ["d", "b", "c", "a"], "one at a time: the untimed first, then the longest first (%s)" % order)

    out = io.StringIO()
    failed, _ = run_all([("x", [py, "-c", "raise SystemExit(1)"]), ("y", [py, "-c", "pass"])], 1,
                        {"x": 2.0, "y": 1.0}, fail_fast=True, out=out)
    check(failed == ["x"] and "== y" not in out.getvalue(), "fail fast: nothing starts after a failure")

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "spark", "gate-times")
        save_times({"smoke.py": 345.04, "widget_pty shell": 151.0}, p)
        check(load_times(p) == {"smoke.py": 345.0, "widget_pty shell": 151.0}, "the ledger keeps a label with spaces")
    check(load_times("/nonexistent/gate-times") == {}, "no ledger yet is an empty one")
    print("gate_run selftest: %s" % ("all ok" if not bad else "%d failed" % len(bad)))
    return 1 if bad else 0


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    if len(argv) != 3:
        print("usage: python3 tests/gate_run.py QUEUE FAILED | --selftest", file=sys.stderr)
        return 2
    suites = []
    with open(argv[1], encoding="utf-8") as f:
        for line in f:
            label, _, cmd = line.rstrip("\n").partition("\t")
            suites.append((label, shlex.split(cmd)))
    times, n = load_times(TIMES), jobs()
    print("gate: %d suites, %d at a time" % (len(suites), n), flush=True)
    failed, wall = run_all(suites, n, times, fail_fast=bool(os.environ.get("SPARK_GATE_FAIL_FAST")))
    save_times(times, TIMES)
    with open(argv[2], "w", encoding="utf-8") as f:
        f.writelines(label + "\n" for label in failed)
    print("gate: %d suites in %.0f s, %d at a time" % (len(suites), wall, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
