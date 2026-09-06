#!/usr/bin/env python3
# micro_pty.py -- the spark plugin inside a real micro, in a pty, against a
# stub `spark` (SPARK_BIN) that logs what it was asked and answers a fixed
# word. Proves the whole loop the editor depends on: Alt-s opens the
# prompt, words reach `spark edit` with the filetype, the name and the
# about-option (never the path), the answer lands in the buffer, `?` opens
# a pane, command mode works without Alt. Skips (exit 0) where micro is not
# installed -- the shell layer is off, or CI without it.
#
#   python3 tests/micro_pty.py

import fcntl
import json
import os
import re
import pty
import select
import shutil
import struct
import sys
import tempfile
import termios
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "home", ".config", "micro", "plug", "spark")
BINDINGS = os.path.join(REPO, "home", ".config", "micro", "bindings.json")
CSI = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\([A-Za-z0-9]|[@-Z\\-_])")

STUB = r'''#!/bin/sh
# the stub spark: log argv and stdin, answer one word
printf '%s\n' "$*" >> "$STUB_LOG"
cat > "$STUB_LOG.stdin"
case " $* " in
    *" ? "*)      printf 'STUB-ASK\n'; exit 0 ;;
    *" --at "*)   printf 'STUB-DONE'; exit 0 ;;
    *" keep it "*) cat "$STUB_LOG.stdin"; exit 0 ;;
    *" fail "*)   printf 'spark: no brain today -- spark serve\n' >&2; exit 1 ;;
    *" slow "*)   sleep 2; printf 'STUB-SLOW'; exit 0 ;;
esac
printf 'STUB-EDIT'
'''


class Micro:
    def __init__(self, argv, env, cwd, rows=30, cols=100):
        self.buf = b""
        self.pos = 0
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(cwd)
            os.execvpe(argv[0], argv, env)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

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

    def plain(self):
        """what was drawn since mark(), with the escape sequences removed --
        micro's highlighter splits even `hello world` with colour codes"""
        return CSI.sub("", self.buf[self.pos:].decode("utf-8", "replace"))

    def expect(self, text, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if text in self.plain():
                return True
            self.read(0.2)
        return False

    def send(self, s):
        os.write(self.fd, s.encode())
        time.sleep(0.15)

    def mark(self):
        self.pos = len(self.buf)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except OSError:
            pass


def main():
    micro = shutil.which("micro")
    if not micro:
        print("micro_pty: micro is not installed here -- skipped (spark shell on installs it)")
        return 0
    fail = 0

    def ok(cond, what, extra=""):
        nonlocal fail
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + extra) if extra and not cond else ""))
        if not cond:
            fail += 1

    with tempfile.TemporaryDirectory(prefix="spark-micro-") as tmp:
        cfg, work, bindir = [os.path.join(tmp, d) for d in ("cfg", "work", "bin")]
        os.makedirs(os.path.join(cfg, "plug"))
        os.makedirs(work)
        os.makedirs(bindir)
        os.symlink(PLUGIN, os.path.join(cfg, "plug", "spark"))
        shutil.copy(BINDINGS, os.path.join(cfg, "bindings.json"))
        with open(os.path.join(cfg, "settings.json"), "w") as f:
            json.dump({"clipboard": "internal", "autosave": 0, "*.md": {"spark.about": "a note"}}, f)
        stub = os.path.join(bindir, "spark")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        log = os.path.join(tmp, "stub.log")
        note = os.path.join(work, "note.md")
        with open(note, "w") as f:
            f.write("hello world\n")
        env = {"HOME": tmp, "TERM": "xterm-256color", "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "SPARK_BIN": stub, "STUB_LOG": log,
               "MICRO_TRUECOLOR": "0"}
        argv = [micro, "-config-dir", cfg, "-debug", "note.md"]

        def logged():
            try:
                with open(log) as f:
                    return f.read()
            except OSError:
                return ""

        def debug_log():
            try:
                with open(os.path.join(cfg, "log.txt")) as f:
                    return f.read()[-1500:]
            except OSError:
                return "(no log.txt)"

        # A. Alt-s, words: a rewrite with nothing selected rewrites the whole file
        m = Micro(argv, env, work)
        ok(m.expect("hello world"), "micro draws the file", debug_log())
        m.mark()
        m.send("\x1bs")
        ok(m.expect("spark>"), "Alt-s opens the spark> prompt", debug_log())
        m.send("make it shine\r")
        ok(m.expect("rewritten"), "the whole file is rewritten in place", debug_log())
        m.send("\x13")               # Ctrl-s: save
        time.sleep(0.5)
        m.send("\x11")               # Ctrl-q: quit
        m.read(1.0)
        m.close()
        with open(note) as f:
            saved = f.read()
        ok(saved in ("STUB-EDIT", "STUB-EDIT\n"), "the saved file is the answer, nothing doubled", repr(saved))
        got = logged()
        ok("edit --type markdown --name note.md --about a note make it shine" in got and "--part" not in got,
           "spark edit got the filetype, the name, the about-option and the words, no --part", got)
        ok(work not in got, "the file's path never reaches spark", got)
        try:
            with open(log + ".stdin") as f:
                stdin = f.read()
        except OSError:
            stdin = ""
        ok(stdin == "hello world\n", "the whole buffer travelled on stdin", repr(stdin))

        # B. command mode (no Alt), a question: a pane on the right
        if os.path.exists(log):
            os.unlink(log)
        with open(note, "w") as f:
            f.write("hello world\n")
        m = Micro(argv, env, work)
        ok(m.expect("hello world"), "micro draws the file again")
        m.mark()
        m.send("\x05")               # Ctrl-e: command mode
        ok(m.expect(">"), "command mode opens")
        m.send("spark ? why\r")
        ok(m.expect("STUB-ASK"), "`spark ? why` answers in a pane", debug_log())
        got = logged()
        ok("--name note.md --about a note ? why" in got, "the question reaches spark edit as ? words", got)
        m.send("\x11")               # closes the pane
        time.sleep(0.4)
        m.send("\x11")               # quits micro (nothing modified)
        m.read(1.0)
        m.close()
        with open(note) as f:
            ok(f.read() == "hello world\n", "a question changes nothing in the file")

        # C. Alt-s, Enter: a completion at the cursor
        if os.path.exists(log):
            os.unlink(log)
        m = Micro(argv, env, work)
        ok(m.expect("hello world"), "micro draws the file once more")
        m.mark()
        m.send("\x1bs")
        ok(m.expect("spark>"), "Alt-s again")
        m.send("\r")
        ok(m.expect("STUB-DONE"), "Enter alone completes at the cursor", debug_log())
        got = logged()
        ok("--at 0" in got, "the completion names the byte offset", got)
        m.send("\x11")               # quit: the buffer is modified, micro asks
        time.sleep(0.4)
        m.send("n\r")
        m.read(1.0)
        m.close()

        # D. a real selection (Ctrl-a selects all): the rewrite replaces it
        if os.path.exists(log):
            os.unlink(log)
        with open(note, "w") as f:
            f.write("hello world\n")
        m = Micro(argv, env, work)
        ok(m.expect("hello world"), "micro draws the file for the selection")
        m.mark()
        m.send("\x01")               # Ctrl-a: select all
        m.send("\x1bs")
        ok(m.expect("spark>"), "Alt-s over a selection")
        m.send("shorter\r")
        ok(m.expect("rewritten"), "the selection is replaced and the infobar says so", debug_log())
        m.send("\x13")
        time.sleep(0.5)
        m.send("\x11")
        m.read(1.0)
        m.close()
        with open(note) as f:
            saved = f.read()
        ok(saved in ("STUB-EDIT", "STUB-EDIT\n"), "the whole selection became the answer, nothing else (micro adds the final newline)", repr(saved))
        with open(log + ".stdin") as f:
            ok(f.read() == "hello world\n", "the selection travelled on stdin")
        ok("--part shorter" in logged(), "a selection travels with --part", logged())

        # E. an unchanged rewrite splices nothing
        if os.path.exists(log):
            os.unlink(log)
        with open(note, "w") as f:
            f.write("hello world\n")
        m = Micro(argv, env, work)
        ok(m.expect("hello world"), "micro draws the file for the unchanged case")
        m.mark()
        m.send("\x01")
        m.send("\x1bs")
        m.expect("spark>")
        m.send("keep it\r")
        ok(m.expect("unchanged"), "a reply equal to the selection says unchanged", debug_log())
        m.send("\x11")               # nothing modified: quits at once
        m.read(1.0)
        m.close()
        with open(note) as f:
            ok(f.read() == "hello world\n", "the file is untouched")

        # F. spark's stderr reaches the infobar verbatim
        m = Micro(argv, env, work)
        ok(m.expect("hello world"), "micro draws the file for the failure")
        m.mark()
        m.send("\x1bs")
        m.expect("spark>")
        m.send("fail\r")
        ok(m.expect("no brain today"), "spark's die hint is shown", debug_log())
        m.send("\x11")
        m.read(1.0)
        m.close()

        # G. the file is edited while spark thinks: nothing is spliced over
        # the stale range; the answer opens in a pane; micro lives on
        with open(note, "w") as f:
            f.write("hello world\nsecond line\n")
        m = Micro(argv, env, work)
        ok(m.expect("second line"), "micro draws two lines")
        m.mark()
        m.send("\x1bs")
        m.expect("spark>")
        m.send("slow\r")
        time.sleep(0.5)
        m.send("\x01")              # Ctrl-a, Backspace: the buffer is emptied meanwhile
        m.send("\x08")
        ok(m.expect("thought", 6), "a whole-file answer over a changed buffer is refused (the infobar says so)", debug_log())
        ok(m.expect("STUB-SLOW", 2), "the answer is shown in a pane instead")
        ok(os.waitpid(m.pid, os.WNOHANG) == (0, 0), "micro is still running")
        m.send("\x11")              # the pane
        time.sleep(0.4)
        m.send("\x11")              # the buffer, modified: micro asks
        time.sleep(0.4)
        m.send("n\r")
        m.read(1.0)
        m.close()
        with open(note) as f:
            ok(f.read() == "hello world\nsecond line\n", "the file on disk is untouched")

        # H. the same over a selection that moved
        m = Micro(argv, env, work)
        ok(m.expect("second line"), "micro draws two lines again")
        m.mark()
        m.send("\x01")              # select all
        m.send("\x1bs")
        m.expect("spark>")
        m.send("slow\r")
        time.sleep(0.5)
        m.send("\x1b[H")            # Home, then a word typed at the top
        m.send("x")
        ok(m.expect("thought", 6), "a selection answer over a changed buffer is refused (the infobar says so)", debug_log())
        ok(os.waitpid(m.pid, os.WNOHANG) == (0, 0), "micro is still running")
        m.send("\x11")
        time.sleep(0.4)
        m.send("\x11")
        time.sleep(0.4)
        m.send("n\r")
        m.read(1.0)
        m.close()

    print("micro_pty: %s" % ("all ok" if not fail else "%d FAILED" % fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
