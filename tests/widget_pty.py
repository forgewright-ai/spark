#!/usr/bin/env python3
# spark tests/widget_pty.py -- a real shell in a pty, driven through the
# widget. Proves the contract the widget makes: a question's command lands
# in the line and does NOT run; a plain line runs at once; a glob is not a
# question; the off flag hands Enter back; Esc a asks; the liveness marker
# comes and goes with the shell. Then, in a 40-column tmux pane (skipped
# without tmux): a question that wraps still gets its hint in the row above
# an intact prompt.
#
#   widget_pty.py bash home/.config/spark/widget.bash
#   widget_pty.py zsh  home/.config/spark/widget.zsh

import fcntl
import os
import pty
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time

STUB = r'''#!/bin/sh
# a stand-in for `spark line`: canned replies, and a log of every question
line=$(cat)
printf '%s\n' "$line" >> "$STUB_LOG"
case $line in
  *delete*) printf 'danger\techo EXECUTED-MARK\nDeletes things -- careful\n' ;;
  *answer-me*) printf 'answer\nForty-two\n' ;;
  *) printf 'cmd\techo EXECUTED-MARK\nA hint about it\n' ;;
esac
'''


class Shell:
    def __init__(self, argv, env, cwd):
        self.buf = b""
        self.pos = 0
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(cwd)
            os.execvpe(argv[0], argv, env)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 200, 0, 0))

    def read(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(self.fd, 4096)
                except OSError:
                    return
                if not data:
                    return
                self.buf += data

    def expect(self, text, timeout=8):
        """text appears in output written AFTER the last mark()"""
        end = time.time() + timeout
        while time.time() < end:
            if text.encode() in self.buf[self.pos:]:
                return True
            self.read(0.2)
        return False

    def send(self, s):
        os.write(self.fd, s.encode())

    def mark(self):
        self.pos = n = len(self.buf)
        return lambda: self.buf[n:].decode("utf-8", "replace")

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except OSError:
            pass


def wrapped(shell, widget, tmp, env, prompt, ok):
    """A real screen: tmux renders a 40-column pane, so a question that wraps
    onto a second row proves the hint lands above the prompt, not on it."""
    if not shutil.which("tmux"):
        print("  skip wrapped question: no tmux")
        return
    env = dict(env, TERM="screen-256color")
    t = ["tmux", "-S", os.path.join(tmp, "tmux.sock"), "-f", "/dev/null"]
    argv = "bash --norc --noprofile -i" if shell == "bash" else "zsh -f -i"
    cmd = "env -i " + " ".join(shlex.quote("%s=%s" % kv) for kv in env.items()) + " " + argv
    subprocess.run(t + ["new-session", "-d", "-x", "40", "-y", "12", "-c", os.path.join(tmp, "work"), cmd], check=True)

    def screen():
        return subprocess.run(t + ["capture-pane", "-p"], capture_output=True, text=True).stdout

    def until(want, timeout=8):
        """the screen once a row satisfies want (a callable on the row)"""
        end = time.time() + timeout
        while time.time() < end:
            s = screen()
            if any(want(r.rstrip()) for r in s.splitlines()):
                return s
            time.sleep(0.2)
        return screen()

    def keys(s):
        subprocess.run(t + ["send-keys", "-l", s], check=True)
        subprocess.run(t + ["send-keys", "Enter"], check=True)

    try:
        if shell == "bash":
            keys("PS1='\\n%s'; source %s; echo SOURCED" % (prompt, widget))
        else:
            keys("PROMPT=$'\\n%s'; source %s; echo SOURCED" % (prompt, widget))
        until(lambda r: r == "SOURCED", 20)          # the output row, not the typed echo
        until(lambda r: r == prompt.rstrip())         # and the prompt after it
        keys("? every file here bigger than a gigabyte")     # 13 + 41 columns: wraps
        rows = [r.rstrip() for r in until(lambda r: "A hint about it" in r).splitlines()]
        at = next((i for i, r in enumerate(rows) if "A hint about it" in r), -1)
        below = rows[at + 1] if 0 <= at < len(rows) - 1 else ""
        good = at >= 0 and below == prompt + "echo EXECUTED-MARK"
        ok(good, "wrapped question: the hint sits above an intact prompt")
        if not good:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))
    finally:
        subprocess.run(t + ["kill-server"], stderr=subprocess.DEVNULL)


def main(shell, widget):
    widget = os.path.abspath(widget)
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + repr(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    with tempfile.TemporaryDirectory(prefix="spark-pty-") as tmp:
        home = os.path.join(tmp, "home")
        state = os.path.join(home, ".local", "state")
        os.makedirs(os.path.join(home, "bin"))
        os.makedirs(os.path.join(tmp, "work"))
        open(os.path.join(tmp, "work", "a.txt"), "w").close()
        stub = os.path.join(home, "bin", "spark")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        log = os.path.join(tmp, "asked.log")
        env = {"HOME": home, "XDG_STATE_HOME": state, "SPARK_BIN": stub, "STUB_LOG": log,
               "PATH": os.path.join(home, "bin") + ":" + os.environ.get("PATH", ""),
               "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "ZDOTDIR": home}
        prompt = "SPARKPROMPT> "
        if shell == "bash":
            sh = Shell(["bash", "--norc", "--noprofile", "-i"], env, os.path.join(tmp, "work"))
            sh.send("PS1='\\n%s'; source %s; echo SOURCED\n" % (prompt, widget))
        else:
            sh = Shell(["zsh", "-f", "-i"], env, os.path.join(tmp, "work"))
            sh.send("PROMPT=$'\\n%s'; source %s; echo SOURCED\n" % (prompt, widget))
        ok(sh.expect("SOURCED"), "widget sourced")
        sh.expect(prompt)

        def asked():
            try:
                with open(log) as f:
                    return len(f.read().splitlines())
            except OSError:
                return 0

        markers = os.listdir(os.path.join(state, "spark", "widgets"))
        ok(len(markers) == 1 and open(os.path.join(state, "spark", "widgets", markers[0])).read().startswith(shell + " "),
           "liveness marker written: %s" % markers)

        # 1. a question: the command lands in the line, the hint shows, nothing runs
        since = sh.mark()
        sh.send("list big files?\r")
        ok(sh.expect("A hint about it"), "hint printed", since())
        time.sleep(0.5)
        sh.read(0.5)
        ok("EXECUTED-MARK" not in since().replace("echo EXECUTED-MARK", ""), "command NOT executed on the first Enter", since())
        ok(asked() == 1, "spark line was asked once")
        since = sh.mark()
        sh.send("\r")
        ok(sh.expect("EXECUTED-MARK\r\n") or sh.expect("EXECUTED-MARK\n"), "second Enter runs the landed command", since())
        ok(asked() == 1, "second Enter did not ask again")
        sh.expect(prompt)

        # 1b. `?? words` is a question too: the widget hands it on, both marks kept
        n = asked()
        since = sh.mark()
        sh.send("?? again\r")
        ok(sh.expect("A hint about it"), "?? asked", since())
        with open(log) as f:
            last = f.read().splitlines()[-1:]
        ok(asked() == n + 1 and last == ["?? again"], "?? reaches spark line with both marks", last)
        sh.send("\x15")
        time.sleep(0.2)

        # 2. danger: the warning glyph
        since = sh.mark()
        sh.send("? delete stuff\r")
        ok(sh.expect("! Deletes things"), "danger hint carries the warning", since())
        sh.send("\x15")     # C-u: clear the landed line
        time.sleep(0.2)

        # 3. answer: the line is emptied
        since = sh.mark()
        sh.send("answer-me?\r")
        ok(sh.expect("* Forty-two"), "answer shows in the hint row", since())
        time.sleep(0.3)
        since2 = sh.mark()
        sh.send("\r")
        sh.expect(prompt, 3)
        ok("EXECUTED" not in since2(), "an answer leaves no command behind", since2())

        # 4. a plain line runs at once, unasked
        n = asked()
        since = sh.mark()
        sh.send("echo PLAIN-RAN\r")
        ok(sh.expect("PLAIN-RAN\r\n") or sh.expect("PLAIN-RAN\n"), "plain line runs immediately", since())
        ok(asked() == n, "plain line not asked")

        # 5. a glob that matches is not a question
        since = sh.mark()
        sh.send("echo a.tx?\r")
        ok(sh.expect("a.txt\r\n") or sh.expect("a.txt\n"), "glob `a.tx?` expands, not asked", since())
        ok(asked() == n, "glob not asked")

        # 6. the off flag hands Enter back; removing it restores
        open(os.path.join(state, "spark", "off"), "w").close()
        since = sh.mark()
        sh.send("echo OFF-RAN?\r")
        ok(sh.expect("OFF-RAN?\r\n") or sh.expect("OFF-RAN?\n"), "with the off flag the line goes to the shell", since())
        ok(asked() == n, "off flag: not asked")
        os.remove(os.path.join(state, "spark", "off"))
        sh.mark()
        sh.send("echo back?\r")
        ok(sh.expect("A hint about it"), "flag removed: asked again (no re-source needed)")
        ok(asked() == n + 1, "flag removed: asked exactly once")
        sh.send("\x15")

        # 7. Esc a asks about a plain line
        n = asked()
        sh.mark()
        sh.send("how do I list files")
        time.sleep(0.2)
        sh.send("\x1ba")
        ok(sh.expect("A hint about it"), "Esc a asks")
        ok(asked() == n + 1, "Esc a asked once")
        sh.send("\x15")

        # 7b. Esc a on an empty line says so instead of doing nothing
        n = asked()
        sh.mark()
        sh.send("\x1ba")
        ok(sh.expect("type something first"), "Esc a on an empty line explains itself")
        ok(asked() == n, "and does not ask")

        # 8. exit removes the marker
        sh.send("exit\r")
        sh.read(1.0)
        sh.close()
        time.sleep(0.3)
        ok(not os.listdir(os.path.join(state, "spark", "widgets")), "marker removed on exit")

        # 9. the rendered screen: a wrapped question, hint above, prompt intact
        wrapped(shell, widget, tmp, env, prompt, ok)

    print("widget_pty %s: %s" % (shell, "all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("bash", "zsh"):
        print(__doc__ or "usage: widget_pty.py bash|zsh WIDGET")
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
