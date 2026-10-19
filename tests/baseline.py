#!/usr/bin/env python3
"""Record a test baseline and run the existing gate, with orphan reaping.

No assertion is skipped or changed. --probe-readline isolates the chat's
line editor without a model, sound or network. Python 3.9+, Linux/macOS.
"""
import argparse
import ctypes
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUPS = ("smoke", "serve", "rest")


def facts():
    try:
        import readline
        backend = "libedit" if "libedit" in (readline.__doc__ or "") else "GNU readline"
    except ImportError:
        backend = "none"
    override = os.environ.get("SPARK_ETC_RUNIT")
    return {
        "baseline": platform.python_version(),
        "platform": platform.system(),
        "readline": backend,
        "term": os.environ.get("TERM", "unset"),
        "host_init": "launchd" if sys.platform == "darwin" else (
            "runit" if os.path.isdir("/etc/runit") else "systemd"),
        "init_override": ("runit" if os.path.isdir(override) else "systemd") if override is not None else "unset",
        "gate_init_fixture": "launchd" if sys.platform == "darwin" else "systemd",
        "mcp_root_owned": os.stat("/").st_uid in (0, os.getuid()),
        "mcp_python_owned": os.stat(sys.executable).st_uid in (0, os.getuid()),
        "temp_git_marker": os.path.lexists(os.path.join(tempfile.gettempdir(), ".git")),
        "checkout_parent_git_marker": os.path.lexists(os.path.join(os.path.dirname(ROOT), ".git")),
        "shellcheck": "available" if shutil.which("shellcheck") else "missing",
        "child_reaper": "Linux subreaper requested for gate runs" if sys.platform.startswith("linux") else "host init",
    }


def run(argv, env=None):
    """Keep the command's status; reap only children adopted by this runner."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "cannot enable child subreaper")
    sys.stdout.flush()
    sys.stderr.flush()
    child = os.fork()
    if child == 0:
        try:
            os.chdir(ROOT)
            os.setsid()
            child_env = dict(os.environ if env is None else env)
            child_env.update(SPARK_GATE_PYTHON=sys.executable, PYTHONUNBUFFERED="1")
            # readline can change libc's environment behind os.environ.
            # Pass the mapping explicitly so terminal-width side effects
            # from metadata collection cannot truncate the gate's ps.
            os.execvpe(argv[0], argv, child_env)
        except OSError:
            os._exit(127)
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
        except KeyboardInterrupt:
            try:
                os.killpg(child, signal.SIGINT)
            except ProcessLookupError:
                pass
            continue
        if pid == child:
            return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 128 + os.WTERMSIG(status)


def pty_line(argv, env, timeout=3):
    """Send one complete line; report lost input and leave no probe process."""
    import fcntl
    import pty
    import select
    import struct
    import termios
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    child = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True,
                             preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
    os.close(slave)
    got, sent = b"", False
    stop = time.monotonic() + timeout
    try:
        while time.monotonic() < stop:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    break
                if not data:
                    break
                got += data
                if not sent and b"baseline> " in got:
                    os.write(master, b"count\n")
                    sent = True
                if b'BASELINE_RESULT:"count"' in got:
                    break
            elif child.poll() is not None:
                break
    finally:
        if b'BASELINE_RESULT:"count"' in got:
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        os.close(master)
    return {
        "status": "passed" if b'BASELINE_RESULT:"count"' in got and child.returncode == 0 else (
            "failed" if sent else "blocked"),
        "line_sent": sent,
        "tiocsti_denied": b"BASELINE_TIOCSTI_DENIED" in got,
    }


def probe_readline():
    code = '''import json, readline, sys
sys.path.insert(0, sys.argv[1])
from spark.forge import _Keys
keys = _Keys(readline)
original = keys._push
def observed(data):
    try:
        original(data)
    except OSError:
        print("BASELINE_TIOCSTI_DENIED", flush=True)
        raise
keys._push = observed
try:
    line = keys.read("baseline> ")
    print("BASELINE_RESULT:" + json.dumps(line), flush=True)
finally:
    keys.close()
'''
    with tempfile.TemporaryDirectory(prefix="spark-readline-probe-") as home:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SPARK_", "XDG_", "SITE_"))}
        env.update(HOME=home, XDG_CONFIG_HOME=home + "/.config", XDG_STATE_HOME=home + "/.local/state",
                   XDG_DATA_HOME=home + "/.local/share", TERM="xterm-256color", INPUTRC=os.devnull,
                   LANG="C.UTF-8", LC_ALL="C.UTF-8")
        return pty_line([sys.executable, "-u", "-c", code, os.path.join(ROOT, "lib")], env)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", nargs="?", choices=GROUPS)
    parser.add_argument("--probe-readline", action="store_true", help="test one chat input line without a model")
    args = parser.parse_args(argv)
    if args.probe_readline and args.group:
        parser.error("--probe-readline does not take a gate group")
    print(json.dumps(facts(), sort_keys=True), flush=True)
    if args.probe_readline:
        result = probe_readline()
        print(json.dumps({"readline_probe": result}, sort_keys=True), flush=True)
        return {"passed": 0, "failed": 1, "blocked": 2}[result["status"]]
    selected = (args.group,) if args.group else GROUPS
    results = {group: "unrun" for group in GROUPS}
    status = 0
    with tempfile.TemporaryDirectory(prefix="spark-baseline-") as fixture:
        env = dict(os.environ)
        for key in ("SPARK_ETC_RUNIT", "SPARK_VAR_SERVICE"):
            env.pop(key, None)
        if sys.platform != "darwin":
            env.update(SPARK_ETC_RUNIT=fixture + "/no-runit", SPARK_VAR_SERVICE=fixture + "/no-service")
        for group in selected:
            try:
                rc = run(["sh", "tests/gate.sh", "full", group], env=env)
            except OSError:
                results[group] = "blocked"
                status = status or 2
                continue
            results[group] = "passed" if rc == 0 else "failed"
            status = status or rc
            if rc in (128 + signal.SIGINT, 128 + signal.SIGTERM):
                break
    print(json.dumps({"groups": results, "exit_status": status,
                      "skipped_checks": "see gate NOTICE and test skip lines; none are hidden"}, sort_keys=True), flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
