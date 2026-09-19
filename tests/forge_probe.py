#!/usr/bin/env python3
# spark tests/forge_probe.py -- a FORGE's gates, probed from the wire.
#
#   python3 tests/forge_probe.py URL     one line per gate; exit 1 when any
#                                        does not hold
#
# The probes are wire.probe_gates (wire.GATES, in order): /api/health says
# forge: true; the page carries Content-Security-Policy, X-Frame-Options
# DENY, Referrer-Policy and X-Content-Type-Options nosniff; a POST to
# /api/login without X-Spark is 403; a bare GET /api/users is 401; a cookie
# alone does not open POST /v1/chat/completions. Nothing rides a probe: no
# token, no words. Run it against a real box, or from forge_smoke.py
# against its own FORGE; `spark check`'s hardening row asks the same of the
# FORGE served here (or the peer's, on a client). The tests are not the
# product: the probes live in lib/spark/wire.py and this file only runs
# them.

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
from spark import wire  # noqa: E402


def probe(url, timeout=5):
    """[(name, ok, detail)] -- one per gate in wire.GATES, in order."""
    return wire.probe_gates(url, timeout)


def main(argv):
    if len(argv) != 1 or argv[0] in ("-h", "--help", "help"):
        print("usage: python3 tests/forge_probe.py URL   (one line per gate; exit 1 when any does not hold)")
        return 2
    bad = 0
    for name, ok, detail in probe(argv[0].rstrip("/")):
        print("  %s %-12s %s" % ("ok  " if ok else "FAIL", name, detail))
        bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
