#!/usr/bin/env python3
"""The manual baseline runner: status, metadata, pty input and reaping."""
import contextlib
import ctypes
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import baseline


class BaselineTests(unittest.TestCase):
    def test_metadata_does_not_dump_environment(self):
        with patch.dict(os.environ, {"BASELINE_SECRET": "must-not-be-logged"}):
            facts = baseline.facts()
        shown = json.dumps(facts)
        self.assertNotIn("must-not-be-logged", shown)
        self.assertNotIn("BASELINE_SECRET", shown)
        self.assertIn(facts["readline"], ("GNU readline", "libedit", "none"))
        self.assertIn("init_override", facts)
        self.assertIn("mcp_root_owned", facts)

    def test_nonzero_gate_status_and_unrun_groups(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "tests"))
            with open(os.path.join(root, "tests", "gate.sh"), "w") as f:
                f.write("#!/bin/sh\nexit 7\n")
            output = io.StringIO()
            with patch.object(baseline, "ROOT", root), contextlib.redirect_stdout(output):
                status = baseline.main(["smoke"])
        self.assertEqual(status, 7)
        summary = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(summary["groups"], {"smoke": "failed", "serve": "unrun", "rest": "unrun"})

    def test_child_exit_status(self):
        self.assertEqual(baseline.run([sys.executable, "-c", "raise SystemExit(9)"]), 9)

    def test_native_environment_does_not_leak(self):
        # readline may set terminal width in libc without updating
        # os.environ. Only the explicit environment should reach the gate.
        libc = ctypes.CDLL(None)
        libc.setenv.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
        libc.unsetenv.argtypes = (ctypes.c_char_p,)
        name = "BASELINE_NATIVE_%d" % os.getpid()
        self.assertNotIn(name, os.environ)
        self.assertEqual(libc.setenv(name.encode(), b"native-only", 1), 0)
        try:
            code = "import os; raise SystemExit(6 if %r in os.environ else 0)" % name
            self.assertEqual(baseline.run([sys.executable, "-c", code], env=dict(os.environ)), 0)
        finally:
            libc.unsetenv(name.encode())

    def test_gate_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "tests"))
            with open(os.path.join(root, "tests", "gate.sh"), "w") as f:
                f.write('case "$2" in smoke) exit 7 ;; serve) exit 0 ;; rest) exit 9 ;; esac\n')
            output = io.StringIO()
            with patch.object(baseline, "ROOT", root), contextlib.redirect_stdout(output):
                status = baseline.main([])
        self.assertEqual(status, 7)
        summary = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(summary["groups"], {"smoke": "failed", "serve": "passed", "rest": "failed"})

    def test_gate_isolates_init_without_changing_caller(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "tests"))
            os.mkdir(os.path.join(root, "host-runit"))
            with open(os.path.join(root, "tests", "gate.sh"), "w") as f:
                if sys.platform == "darwin":
                    f.write('test -z "${SPARK_ETC_RUNIT+x}" && test -z "${SPARK_VAR_SERVICE+x}"\n')
                else:
                    f.write('test -n "$SPARK_ETC_RUNIT" && test ! -d "$SPARK_ETC_RUNIT" '
                            '&& test -n "$SPARK_VAR_SERVICE" && test ! -d "$SPARK_VAR_SERVICE"\n')
            override = os.path.join(root, "host-runit")
            with patch.dict(os.environ, SPARK_ETC_RUNIT=override, SPARK_VAR_SERVICE=override):
                with patch.object(baseline, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(baseline.main(["smoke"]), 0)
                self.assertEqual(os.environ["SPARK_ETC_RUNIT"], override)
                self.assertEqual(os.environ["SPARK_VAR_SERVICE"], override)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux child subreaper")
    def test_orphan_reaped_without_confusing_child_status(self):
        code = '''import os, time
r, w = os.pipe()
parent = os.fork()
if parent == 0:
    os.close(r)
    orphan = os.fork()
    if orphan == 0:
        os.close(w)
        time.sleep(0.05)
        os._exit(3)
    os.write(w, str(orphan).encode())
    os.close(w)
    os._exit(0)
os.close(w)
orphan = int(os.read(r, 100))
os.close(r)
os.waitpid(parent, 0)
end = time.monotonic() + 3
while time.monotonic() < end:
    try:
        os.kill(orphan, 0)
    except ProcessLookupError:
        raise SystemExit(0)
    time.sleep(0.02)
raise SystemExit(5)
'''
        self.assertEqual(baseline.run([sys.executable, "-c", code]), 0)

    def test_pty_probe_sends_a_complete_line(self):
        code = 'import json; print("BASELINE_RESULT:" + json.dumps(input("baseline> ")), flush=True)'
        result = baseline.pty_line([sys.executable, "-c", code], dict(os.environ))
        self.assertEqual(result["status"], "passed", result)

    def test_pty_probe_reports_lost_input(self):
        code = 'import os; print("baseline> ", end="", flush=True); os.read(0, 100); input()'
        result = baseline.pty_line([sys.executable, "-c", code], dict(os.environ), timeout=0.3)
        self.assertEqual(result["status"], "failed", result)


if __name__ == "__main__":
    unittest.main()
