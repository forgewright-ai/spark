#!/usr/bin/env python3
"""Synthetic context benchmark; no model, real source, or saved conversation.

Run: python3 tests/context_bench.py
Reports bytes read, peak Python allocations (tracemalloc), and elapsed ms.
Fixture creation is outside measurement. Sizes grow; context budgets do not.
"""
import contextlib
import json
import os
import sys
import tempfile
import time
import tracemalloc
from unittest import mock


def main():
    with tempfile.TemporaryDirectory(prefix="spark-context-bench-") as root:
        for key in list(os.environ):
            if key.startswith(("SPARK_", "XDG_", "SITE_")):
                del os.environ[key]
        os.environ.update(HOME=root, XDG_STATE_HOME=root, XDG_CONFIG_HOME=root, XDG_DATA_HOME=root)
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
        from spark import bounded, forge, vault
        regular = bounded.regular
        counts = [0]

        class Meter:
            def __init__(self, f):
                self.f = f

            def __getattr__(self, key):
                return getattr(self.f, key)

            def read(self, n):
                out = self.f.read(n)
                counts[0] += len(out)
                return out

            def readline(self, n):
                out = self.f.readline(n)
                counts[0] += len(out)
                return out

        @contextlib.contextmanager
        def measured(path):
            with regular(path) as f:
                yield Meter(f)

        def measure(kind, path, call):
            counts[0] = 0
            with mock.patch.object(bounded, "regular", measured):
                tracemalloc.start()
                started = time.perf_counter()
                call()
                elapsed = (time.perf_counter() - started) * 1000
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
            print("%-9s %12d %12d %12d %11.2f" % (kind, os.path.getsize(path), counts[0], peak, elapsed))

        print("kind        input_bytes   bytes_read  peak_python     elapsed_ms")
        source = os.path.join(root, "source.txt")
        for size in (16000, 64000, 1_000_000, 8_000_000):
            with open(source, "wb") as f:
                left = size
                while left:
                    n = min(left, 64000)
                    f.write(b"x" * n)
                    left -= n
            measure("file", source, lambda: forge.read_file(source))

        dk, tid = vault.new_key(), "synthetic"
        threads = os.path.join(root, "threads")
        os.mkdir(threads)
        st = forge.Store(threads, dk)
        path, hdr = st._path(tid), vault.header("thread", tid)
        # Store's kept directory is beside its threads directory. Check
        # both stores and the selected file before writing any history.
        for candidate in (st.tdir, st.kdir, path):
            if os.path.commonpath((os.path.realpath(root), os.path.realpath(candidate))) != os.path.realpath(root):
                raise RuntimeError("benchmark path escaped its temporary directory")
        pair = b""
        for role in ("user", "assistant"):
            payload = json.dumps({"role": role, "text": "x" * 1000}).encode()
            pair += vault.seal_line(dk, hdr, payload).encode() + b"\n"
        for pairs in (10, 100, 1000, 10000):
            with open(path, "wb") as f:
                f.write(hdr.encode() + b"\n")
                for _ in range(pairs):
                    f.write(pair)
            measure("history", path, lambda: st.history(tid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
