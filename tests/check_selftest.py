#!/usr/bin/env python3
# spark tests/check_selftest.py -- the hook's entry to `spark check
# --selftest`: every fixture-testable row must flip between a good and a
# bad throwaway machine. The logic lives in lib/spark/check.py so the
# fixture and the rows can never drift apart.
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.exit(subprocess.call([sys.executable, os.path.join(REPO, "bin", "spark"), "check", "--selftest"]))
