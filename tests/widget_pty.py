#!/usr/bin/env python3
# spark tests/widget_pty.py -- a real shell in a pty, driven through the
# widget. Proves the contract the widget makes: a question's command lands
# in the line and does NOT run; a plain line runs at once; a glob is not a
# question; the off flag hands Enter back; Esc s asks; the liveness marker
# comes and goes with the shell; a nonzero exit prints the failure line
# and Esc s on an empty line composes `cmd 2>&1 | explain` (quoting
# intact), then offers the fix as a fact -- and the suppression table
# (_spark_offer_kind) answers the same in both shells; a hostile answer
# -- prose, nothing, a dead spark line, 40 kB -- runs nothing and leaves
# a working prompt; the streamed line lands its command before the hint,
# a danger's ! before its command, an answer in the row above an empty
# prompt, a failure's reason beside the command it kept; the question
# stays on the prompt row while spark thinks; Ctrl-U on an emptied line
# clears the hint spark drew, and only that. Then, in a 40-column tmux
# pane (skipped without tmux): a question that wraps still gets its hint
# in the row above an intact prompt, and stays whole on screen while
# spark thinks. Then the living prompt (v1.59): a two-line prompt at
# height 2 gets its hint on the blank row, Esc k moves the row, an awake
# look file brings the greeting and the news once, the built-in colour and
# a long failure's duration; one text per fallback; bash chains an EXIT
# trap it found.
#
#   widget_pty.py bash home/.config/spark/widget.bash
#   widget_pty.py zsh  home/.config/spark/widget.zsh
#
# widget_pty.py pager: the same pty machinery, 10 rows, around the real
# `spark help` -- long output goes through $PAGER at a terminal, and an
# absent $PAGER falls back to plain output.
#
# widget_pty.py completion <shell> <file>: the same pty machinery around
# the completion file -- `spark th<TAB>` completes to `theme`, and
# `spark theme gr<TAB>` to `gruvbox-dark` (the dynamic names, resolved
# offline through a spark symlink into the real repository).

import fcntl
import os
import pty
import re
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
# a stand-in for `spark line` (and `spark recall`): canned replies.
if [ "$1" = history ]; then
    # the widgets' silent --fix-worked record: nothing to read, nothing
    # to say -- and NEVER fall through to cat (it would eat the tty)
    exit 0
fi
# what reached spark line from the widget's environment (v1.41: the
# hint-row word), on a log of its own so the asked() count stays honest
[ "$1" = line ] && printf 'SPARK_HINT_ROW=%s\n' "${SPARK_HINT_ROW-}" >> "$STUB_ENV"
if [ "$1" = line ] && [ "$2" = "--paste" ]; then
    cat > /dev/null
    printf 'answer\ntwo echo lines, harmless\n'
    exit 0
fi
# the row's height (v1.59): Esc k keeps its choice through `spark height N`
if [ "$1" = height ]; then
    printf '%s\n' "$2" >> "${STUB_HEIGHT:-/dev/null}"
    exit 0
fi
# the greeting after an absence (v1.59): one line with an escape in it --
# the widget prints it with the control characters stripped
if [ "$1" = words ] && [ "$2" = greet ]; then
    printf 'greet\n' >> "${STUB_GREET:-/dev/null}"
    printf 'Good evening. \033[31mThe engine is warm.\n'
    exit 0
fi
if [ "$1" = recall ]; then
    # history arrives on stdin; grounding is cli's job, not the stub's --
    # here we hand back two plain lines and one danger-marked line (the
    # `!<TAB>` prefix recall puts on a line that can destroy)
    cat > /dev/null
    printf 'git commit --amend --no-edit\ndocker network prune -f\n!\trm -rf ./build\n'
    exit 0
fi
line=$(cat)
printf '%s\n' "$line" >> "$STUB_LOG"
case $line in
  # the judged line (v1.53): the real spark line, against smoke's stub
  # server, grounded in smoke's tiny snapshot store (a bench turn)
  *know*) printf '%s\n' "$line" | SPARK_LINE_BENCH=1 SPARK_KNOWLEDGE_SNAPSHOT="$KNOW_SNAP" \
            SPARK_BASE_URL="$KNOW_URL" SPARK_API_KEY="$KNOW_KEY" SPARK_NO_REFRESH=1 \
            "$KNOW_PY" "$KNOW_SPARK" "$@"; exit $? ;;
  *delete*) printf 'danger\techo EXECUTED-MARK\nDeletes things -- careful\n' ;;
  *answer-me*) printf 'answer\nForty-two\n' ;;
  *answer-empty*) printf 'answer\n' ;;
  # the hostile three: contract 4 broken three ways. The widget must run
  # nothing and leave a prompt the shell can still be used at.
  *hostile-prose*) printf 'the model rambled instead of answering, at length\n' ;;
  *hostile-empty*) : ;;
  # the padding comes BEFORE the mark on purpose: with the mark first,
  # running the command would print MARK+40 kB and the "nothing ran"
  # assertion below could never fail, whatever the widget did
  *hostile-huge*) printf 'cmd\techo '; awk 'BEGIN{while(i++<40000)printf "z"}'; printf ' EXECUTED-MARK\n'; awk 'BEGIN{while(i++<40000)printf "y"}'; printf '\n' ;;
  *hostile-dead*) exit 1 ;;
  # the streamed line (v1.52): line 1 at once, the rest after a pause --
  # as spark line writes them when the command closes before the hint
  *stream-early*) printf 'cmd\techo STREAMED-CMD\n'; sleep 1.5; printf 'streamed hint text\n' ;;
  *stream-cmd*) printf 'cmd\techo STREAMED-CMD\n'; sleep 1.5; printf 'streamed hint text\nproof\ttest -d .\n' ;;
  *stream-danger*) printf 'danger\techo DANGER-CMD\n'; sleep 1.5; printf 'removes things\n' ;;
  *stream-answer*) printf 'answer\n'; sleep 1.5; printf 'The answer in words\n' ;;
  *stream-fail*) printf 'cmd\techo FAILED-CMD\n'; sleep 1.5; printf 'the server stopped mid-reply\n'; exit 1 ;;
  # a model that thinks before line 1 (v1.56): the question stays on screen
  *slow-think*) sleep 2; printf 'cmd\techo SLOW-CMD\nslow hint\n' ;;
  *fix\ it*) printf 'cmd\techo FIXED-COMMAND\nthe corrected command\n' ;;
  *proof-me*) printf 'cmd\ttrue\nruns true\nproof\ttest -d .\n' ;;
  *) if [ "${SPARK_EXPLAIN_RC:-}" = 127 ]; then
         printf 'cmd\tbrew install the-tool\ninstalls the missing tool\n'
     else printf 'cmd\techo EXECUTED-MARK\nA hint about it\n'; fi ;;
esac
'''

EXPLAIN_STUB = r'''#!/bin/sh
# a stand-in for `explain`: logs its stdin and the one-shot variables the
# widget rides along, then answers with a marker
cat >> "$EXPLAIN_LOG"
printf 'cmd=%s rc=%s\n' "${SPARK_EXPLAIN_CMD-}" "${SPARK_EXPLAIN_RC-}" >> "$EXPLAIN_LOG"
printf 'EXPLAINED\n'
'''


class Shell:
    def __init__(self, argv, env, cwd, rows=40, cols=200):
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

    def settle(self, quiet=0.4, timeout=20):
        """Read until nothing new has arrived for `quiet` seconds. A fixed
        sleep is not enough after a 40 kB answer: the shell is still
        redrawing, and the next command typed into that queues behind the
        redraw, so an expect() on it times out on text that then lands."""
        end = time.time() + timeout
        while time.time() < end:
            n = len(self.buf)
            self.read(quiet)
            if len(self.buf) == n:
                return

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
    # no history file: a shell hung up by kill-server writes ~/.bash_history
    # as it exits, into the home the test is already removing
    cmd = "env -i HISTFILE=/dev/null " + " ".join(shlex.quote("%s=%s" % kv) for kv in env.items()) + " " + argv
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

        # while spark thinks, the question stays on screen whole, wrapped
        # or not; line 1 then replaces it, nothing of it left below
        subprocess.run(t + ["send-keys", "C-u"], check=True)
        until(lambda r: r == prompt.rstrip())
        q = "? slow-think about every file bigger than a gigabyte"     # 13 + 52 columns: wraps
        keys(q)

        def thinking(scr):
            rows = [r.rstrip() for r in scr.splitlines()]
            at = next((i for i, r in enumerate(rows) if r.startswith(prompt + "? slow")), -1)
            return (at > 0 and rows[at - 1].startswith("* ") and "SLOW-CMD" not in scr
                    and "".join(rows[at:at + 2]).replace(" ", "") == (prompt + q).replace(" ", ""))
        end, scr = time.time() + 1.5, ""
        while time.time() < end and not thinking(scr):
            scr = screen()
            time.sleep(0.1)
        ok(thinking(scr), "thinking: the wrapped question stays on screen, whole, below the pulse")
        if not thinking(scr):
            print("       screen:\n" + "\n".join("       |%s|" % r.rstrip() for r in scr.splitlines()))
        rows = [r.rstrip() for r in until(lambda r: "slow hint" in r).splitlines()]
        at = next((i for i, r in enumerate(rows) if "slow hint" in r), -1)
        good = (0 <= at < len(rows) - 2 and rows[at + 1] == prompt + "echo SLOW-CMD"
                and not rows[at + 2] and not any("gigabyte" in r for r in rows[at:]))
        ok(good, "thinking: line 1 replaces the wrapped question, nothing of it left")
        if not good:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))
    finally:
        subprocess.run(t + ["kill-server"], stderr=subprocess.DEVNULL)


LOOK_AWAKE = ("AWAKE=yes\nMOTION=auto\nCOLOUR=on\nWORDS=on\nHEIGHT=2\nSGR_ACCENT=1\nSGR_MUTED=2\n"
              "SGR_WARN=31\nSGR_OK=32\nSGR_TROUBLE=1;31\nSGR_YOU=\nFACE_IDLE=(o.o)\n"
              # a value with an escape in it is dropped whole: the face stays
              "FACE_IDLE=\x1b[2J(x.x)\nFACE_ASLEEP=(-.-)z\n")


def living(shell, widget, tmp, env, ok):
    """v1.59, the living prompt: the row's height with a two-line prompt,
    Esc k, then an awake look file -- the greeting once, the news once, the
    built-in colour, a failed command's duration -- and the fallback texts,
    the same in both shells; bash chains an EXIT trap it found."""
    state = os.path.join(tmp, "living-state")
    sd = os.path.join(state, "spark")
    os.makedirs(sd)
    look = os.path.join(sd, "look")
    hlog, glog, elog, tlog = (os.path.join(tmp, n) for n in ("height.log", "greet.log", "living-env.log", "trap.log"))
    env = dict(env, XDG_STATE_HOME=state, STUB_HEIGHT=hlog, STUB_GREET=glog, STUB_ENV=elog, TRAPLOG=tlog)
    with open(look, "w") as f:
        f.write("AWAKE=no\nMOTION=off\nCOLOUR=off\nWORDS=off\nHEIGHT=2\n")
    with open(os.path.join(sd, "news"), "w") as f:
        f.write("n0\tnot while asleep\n")

    def lines(path):
        try:
            with open(path) as f:
                return f.read().splitlines()
        except OSError:
            return []

    prompt = "SPARKPROMPT> "
    if shell == "bash":
        sh = Shell(["bash", "--norc", "--noprofile", "-i"], env, os.path.join(tmp, "work"))
        # an EXIT trap the rc set first, a quote inside: it must still run
        sh.send("trap 'echo \"it'\\''s the old trap $?\" > \"$TRAPLOG\"' EXIT; "
                "PS1='\\nINFO-LINE\\n%s'; source %s; echo SOURCED\n" % (prompt, widget))
    else:
        sh = Shell(["zsh", "-f", "-i"], env, os.path.join(tmp, "work"))
        sh.send("PROMPT=$'\\nINFO-LINE\\n%s'; source %s; echo SOURCED\n" % (prompt, widget))
    ok(sh.expect("SOURCED"), "living: widget sourced with a two-line prompt")
    sh.expect(prompt)
    sh.settle()

    # the height: 2 from the look file, before any awaken -- the hint goes
    # two rows up, onto the blank row, never over INFO-LINE
    since = sh.mark()
    sh.send("? list big files\r")
    ok(sh.expect("\x1b7\x1b[2A\r\x1b[2K* A hint about it\x1b8"),
       "height 2: the hint is drawn two rows up", since()[-300:])
    ok("\x1b[1A" not in since(), "height 2: nothing is drawn one row up, on the prompt's first line", since()[-300:])
    ok(lines(elog)[-1:] == ["SPARK_HINT_ROW=2"], "height 2: spark line hears SPARK_HINT_ROW=2", lines(elog))
    sh.send("\x15")
    sh.settle()

    # Esc k: 2 -> 3 -> 1 -> 2, each through `spark height N`, a test line
    # drawn at the new height
    for n in (3, 1, 2):
        since = sh.mark()
        sh.send("\x1bk")
        ok(sh.expect("\x1b7\x1b[%dA\r\x1b[2K* spark writes here. Esc k moves this line.\x1b8" % n),
           "Esc k: the test line moves to height %d" % n, since()[-300:])
        sh.settle()
    ok(lines(hlog) == ["3", "1", "2"], "Esc k: spark height ran with 3, 1, 2", lines(hlog))

    # asleep: no greeting, no news, no stamp, no duration
    sh.send("_SPARK_LONG=1\r")
    sh.expect(prompt)
    since = sh.mark()
    sh.send("sleep 2; sh -c 'exit 3'\r")
    ok(sh.expect("failed (3) -- press Esc s to ask why", 10), "asleep: a failure line says no duration", since()[-300:])
    sh.expect(prompt)
    sh.settle()
    ok(not lines(glog) and "not while asleep" not in since() and not os.path.exists(os.path.join(sd, "last-seen")),
       "asleep: no greeting, no news, no last-seen stamp", since()[-300:])

    # awake: the look file changes -- read at the next prompt, never sourced
    with open(look, "w") as f:
        f.write(LOOK_AWAKE)
    with open(os.path.join(sd, "news"), "w") as f:
        f.write("n1\tThe engine is asleep. Ask, and it wakes.\n")
    with open(os.path.join(sd, "last-seen"), "w") as f:
        f.write("1000\n")                      # an absence of decades
    old = time.time() - 60
    for m in os.listdir(os.path.join(sd, "widgets")):
        os.utime(os.path.join(sd, "widgets", m), (old, old))
    since = sh.mark()
    sh.send("\r")
    ok(sh.expect("Good evening. [31mThe engine is warm."), "awake: the greeting after an absence", since()[-300:])
    ok(sh.expect("\x1b[1m*\x1b[0m (o.o) The engine is asleep. Ask, and it wakes."),
       "awake: the news once, with the face and the built-in accent", since()[-300:])
    sh.expect(prompt)
    sh.settle()
    seen = since()
    ok("\x1b[31mThe engine" not in seen and "(x.x)" not in seen and "\x1b[2J" not in seen,
       "awake: no escape from the greeting or the look file reaches the screen", seen[-300:])
    ok(lines(glog) == ["greet"], "awake: spark words greet ran once", lines(glog))
    ok(lines(os.path.join(sd, "news-seen")) == ["n1"], "awake: the news id is kept", lines(os.path.join(sd, "news-seen")))
    since = sh.mark()
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    ok("Good evening" not in since() and "The engine is asleep" not in since() and lines(glog) == ["greet"],
       "awake: the next prompt says neither again", since()[-300:])

    # news: the same id again is not news; a new one shows once
    with open(os.path.join(sd, "news"), "w") as f:
        f.write("n1\tThe engine is asleep. Ask, and it wakes.\n")
    os.utime(os.path.join(sd, "news"), (time.time() + 2, time.time() + 2))
    since = sh.mark()
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    ok("The engine is asleep" not in since(), "news: the same id is shown once only", since()[-300:])
    with open(os.path.join(sd, "news"), "w") as f:
        f.write("n2\tThree runs wait for review.\n")
    os.utime(os.path.join(sd, "news"), (time.time() + 4, time.time() + 4))
    # quiet start holds it back; spark off too
    cfg = os.path.join(env["HOME"], ".config", "spark")
    os.makedirs(cfg, exist_ok=True)
    with open(os.path.join(cfg, "site.env"), "w") as f:
        f.write("SITE_QUIET_START=yes\n")
    since = sh.mark()
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    ok("Three runs wait" not in since(), "news: SITE_QUIET_START=yes holds it back", since()[-300:])
    ok(lines(os.path.join(sd, "news-seen")) == ["n2"], "news: under quiet the id counts as seen",
       lines(os.path.join(sd, "news-seen")))
    os.remove(os.path.join(cfg, "site.env"))
    since = sh.mark()
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    ok("Three runs wait" not in since(), "news: held back by quiet, it never plays later", since()[-300:])
    with open(os.path.join(sd, "news"), "w") as f:
        f.write("n3\tThree runs wait for review.\n")
    os.utime(os.path.join(sd, "news"), (time.time() + 6, time.time() + 6))
    open(os.path.join(sd, "off"), "w").close()
    since = sh.mark()
    sh.send("\r")
    sh.expect(prompt)
    sh.settle()
    ok("Three runs wait" not in since(), "news: spark off holds it back", since()[-300:])
    os.remove(os.path.join(sd, "off"))
    since = sh.mark()
    sh.send("\r")
    ok(sh.expect("(o.o) Three runs wait for review."), "news: a new id shows once, quiet and off gone", since()[-300:])
    sh.expect(prompt)
    sh.settle()

    # awake: a failed command that ran long says how long; a quick one not
    since = sh.mark()
    sh.send("sleep 2; sh -c 'exit 3'\r")
    ok(sh.expect("failed (3) after ", 10), "awake: a long failure says how long", since()[-300:])
    ok(re.search(r"failed \(3\) after [23] s -- press Esc s to ask why", since()) is not None,
       "awake: the duration reads N s", since()[-300:])
    sh.expect(prompt)
    sh.settle()
    since = sh.mark()
    sh.send("sh -c 'exit 4'\r")
    ok(sh.expect("failed (4) -- press Esc s to ask why"), "awake: a quick failure says no duration", since()[-300:])
    sh.expect(prompt)
    sh.settle()

    # the built-in accent paints the hint row; NO_COLOR under auto does not
    since = sh.mark()
    sh.send("answer-me?\r")
    ok(sh.expect("\x1b7\x1b[2A\r\x1b[2K\x1b[1m*\x1b[0m Forty-two\x1b8"),
       "awake: the built-in accent, at height 2", since()[-300:])
    sh.send("\r")
    sh.expect(prompt)
    with open(look, "w") as f:
        f.write(LOOK_AWAKE.replace("COLOUR=on", "COLOUR=auto"))
    os.utime(look, (time.time() + 6, time.time() + 6))
    sh.send("export NO_COLOR=1\r")
    sh.expect(prompt)
    sh.settle()
    since = sh.mark()
    sh.send("answer-me?\r")
    ok(sh.expect("\x1b[2K* Forty-two") and "\x1b[1m*" not in since(), "awake: NO_COLOR under auto is plain",
       since()[-300:])
    sh.send("\r")
    sh.expect(prompt)

    # one text for each fallback, the same in both shells
    since = sh.mark()
    sh.send("answer-empty?\r")
    ok(sh.expect("* no answer came"), "fallback: an empty answer says: no answer came", since()[-300:])
    sh.send("\r")
    sh.expect(prompt)
    since = sh.mark()
    sh.send("hostile-empty?\r")
    ok(sh.expect("* no engine is awake"), "fallback: nothing at all says: no engine is awake", since()[-300:])
    sh.send("\x15")
    sh.settle()
    ok("no brain awake" not in sh.buf.decode("utf-8", "replace"), "fallback: the old text is gone")

    sh.send("exit 7\r")
    sh.read(1.0)
    sh.close()
    time.sleep(0.3)
    ok(not os.listdir(os.path.join(sd, "widgets")), "living: marker removed on exit")
    if shell == "bash":
        ok(lines(tlog) == ["it's the old trap 7"], "bash: the EXIT trap the rc set first still runs, and sees the exit status",
           lines(tlog))
    rendered_height(shell, widget, tmp, env, ok)


def rendered_height(shell, widget, tmp, env, ok):
    """A real screen: tmux renders a two-line prompt at height 2 -- the
    hint sits on the blank row above INFO-LINE, and INFO-LINE is intact."""
    if not shutil.which("tmux"):
        print("  skip rendered height: no tmux")
        return
    env = dict(env, TERM="screen-256color", SPARK_HEIGHT="2")
    t = ["tmux", "-S", os.path.join(tmp, "tmux-h.sock"), "-f", "/dev/null"]
    argv = "bash --norc --noprofile -i" if shell == "bash" else "zsh -f -i"
    cmd = "env -i HISTFILE=/dev/null " + " ".join(shlex.quote("%s=%s" % kv) for kv in env.items()) + " " + argv
    subprocess.run(t + ["new-session", "-d", "-x", "60", "-y", "14", "-c", os.path.join(tmp, "work"), cmd], check=True)

    def screen():
        return [r.rstrip() for r in subprocess.run(t + ["capture-pane", "-p"], capture_output=True, text=True).stdout.splitlines()]

    def until(want, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            s = screen()
            if any(want(r) for r in s):
                return s
            time.sleep(0.2)
        return screen()

    def keys(s):
        subprocess.run(t + ["send-keys", "-l", s], check=True)
        subprocess.run(t + ["send-keys", "Enter"], check=True)

    try:
        if shell == "bash":
            keys("PS1='\\nINFO-LINE\\nP> '; source %s; clear" % widget)
        else:
            keys("PROMPT=$'\\nINFO-LINE\\nP> '; source %s; clear" % widget)
        until(lambda r: r == "INFO-LINE", 20)
        time.sleep(0.5)
        keys("? list big files")
        rows = until(lambda r: "A hint about it" in r)
        at = next((i for i, r in enumerate(rows) if "A hint about it" in r), -1)
        good = (0 <= at < len(rows) - 2 and rows[at + 1] == "INFO-LINE"
                and rows[at + 2] == "P> echo EXECUTED-MARK")
        ok(good, "rendered: at height 2 the hint sits on the blank row, INFO-LINE intact below it")
        if not good:
            print("       screen:\n" + "\n".join("       |%s|" % r for r in rows))
    finally:
        subprocess.run(t + ["kill-server"], stderr=subprocess.DEVNULL)


def pager_main():
    """`spark help` (the real one) in a 10-row pty: taller than the screen,
    so it goes through $PAGER -- a stub that logs its stdin and prints a
    marker. Then again with an absent $PAGER: plain output, no error."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spark = os.path.join(repo, "bin", "spark")
    first = "spark -- your own AI, on a machine you own: no account, no cloud, nothing leaves"
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + repr(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    with tempfile.TemporaryDirectory(prefix="spark-pager-") as tmp:
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        log = os.path.join(tmp, "paged.log")
        stub = os.path.join(tmp, "pager.sh")
        with open(stub, "w") as f:
            f.write('#!/bin/sh\ncat >> "$STUB_LOG"\nprintf \'PAGER-MARK\\n\'\n')
        os.chmod(stub, 0o755)
        env = {"HOME": home, "PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color",
               "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "STUB_LOG": log, "PAGER": stub}

        sh = Shell([sys.executable, spark, "help"], env, tmp, rows=10, cols=80)
        ok(sh.expect("PAGER-MARK"), "the pager's output reached the screen", sh.buf.decode("utf-8", "replace"))
        sh.close()
        logged = open(log).read() if os.path.exists(log) else ""
        ok(first in logged, "the usage went through the pager", logged)

        sh = Shell([sys.executable, spark, "help"], dict(env, PAGER="some-absent-command-xyz"), tmp, rows=10, cols=80)
        ok(sh.expect("your own AI, on a machine you own"), "an absent $PAGER falls back to plain output",
           sh.buf.decode("utf-8", "replace"))
        sh.close()

    print("widget_pty pager: %s" % ("all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


def completion_main(shell, comp):
    """The completion file in a real interactive shell: a symlink named
    spark on PATH points into the real repository (as ~/.local/bin/spark
    does), so the dynamic names resolve offline through readlink."""
    comp = os.path.abspath(comp)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fails = 0

    def ok(cond, what, extra=""):
        nonlocal fails
        print("  %s %s%s" % ("ok  " if cond else "FAIL", what, ("   " + repr(extra)[:300]) if extra and not cond else ""))
        fails += not cond

    with tempfile.TemporaryDirectory(prefix="spark-comp-") as tmp:
        home = os.path.join(tmp, "home")
        os.makedirs(os.path.join(home, "bin"))
        os.symlink(os.path.join(repo, "bin", "spark"), os.path.join(home, "bin", "spark"))
        env = {"HOME": home, "PATH": os.path.join(home, "bin") + ":" + os.environ.get("PATH", ""),
               "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "ZDOTDIR": home}
        if shell == "bash":
            sh = Shell(["bash", "--norc", "--noprofile", "-i"], env, tmp)
            sh.send("source %s && echo SOURCED\n" % comp)
        else:
            sh = Shell(["zsh", "-f", "-i"], env, tmp)
            sh.send("autoload -Uz compinit; compinit -u; source %s && echo SOURCED\n" % comp)
        ok(sh.expect("SOURCED"), "completion sourced")

        # 1. the first word: `spark th<TAB>` becomes `spark theme `
        since = sh.mark()
        sh.send("spark th\t")
        ok(sh.expect("theme"), "spark th<TAB> completes to theme", since())
        sh.send("\x15")     # C-u: clear the line
        time.sleep(0.2)

        # 2. a dynamic name, offline: `spark theme gr<TAB>` -> gruvbox-dark
        since = sh.mark()
        sh.send("spark theme gr\t")
        ok(sh.expect("gruvbox-dark"), "spark theme gr<TAB> completes to gruvbox-dark", since())
        sh.send("\x15")
        time.sleep(0.2)
        sh.send("exit\r")
        sh.read(0.5)
        sh.close()

    print("widget_pty completion %s: %s" % (shell, "all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


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
        estub = os.path.join(home, "bin", "explain")
        with open(estub, "w") as f:
            f.write(EXPLAIN_STUB)
        os.chmod(estub, 0o755)
        log = os.path.join(tmp, "asked.log")
        elog = os.path.join(tmp, "explained.log")
        envlog = os.path.join(tmp, "env.log")
        env = {"HOME": home, "XDG_STATE_HOME": state, "SPARK_BIN": stub, "STUB_LOG": log,
               "EXPLAIN_LOG": elog, "STUB_ENV": envlog,
               "PATH": os.path.join(home, "bin") + ":" + os.environ.get("PATH", ""),
               "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "ZDOTDIR": home}
        # the judged line's cases run the real spark line behind the stub
        # script: smoke's stub server and its snapshot store
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import smoke
        _srv, know_url = smoke.start_stub()
        env.update(KNOW_URL=know_url, KNOW_KEY=smoke.TOKEN, KNOW_PY=sys.executable,
                   KNOW_SPARK=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "spark"),
                   KNOW_SNAP=smoke.know_store(os.path.join(tmp, "know-store.json")))
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
        fields = open(os.path.join(state, "spark", "widgets", markers[0])).read().split()
        ok(len(fields) >= 4 and fields[3] == "hook",
           "the marker's fourth field says the exit-code hook is armed: %s" % fields)

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

        # 3b. the hostile answers: contract 4 broken four ways. Whatever
        # comes back, nothing runs and the prompt is still a prompt --
        # the widget's own promise, under an answer that is not spark's
        for what, why in (("hostile-prose", "prose where the two lines belong"),
                          ("hostile-empty", "nothing at all"),
                          ("hostile-dead", "a spark line that died"),
                          ("hostile-huge", "40 kB on both lines")):
            since = sh.mark()
            sh.send("%s?\r" % what)
            time.sleep(0.6)
            sh.settle()                # 40 kB takes a while to draw
            seen = since()
            ok("EXECUTED-MARK\r\n" not in seen and "EXECUTED-MARK\n" not in seen,
               "%s: nothing ran" % why, seen[-300:])
            sh.send("\x15")            # C-u: clear whatever landed
            sh.settle()
            since2 = sh.mark()
            sh.send("echo STILL-HERE-%s\r" % what)
            ok(sh.expect("STILL-HERE-%s\r\n" % what) or sh.expect("STILL-HERE-%s\n" % what),
               "%s: the prompt still works after it" % why, since2()[-300:])
            sh.expect(prompt)

        # 3c. the streamed line (v1.52): line 1 lands the moment it comes,
        # the hint follows into the row above; the mark is on screen
        # before the command; an answer leaves the prompt empty; a failure
        # after line 1 keeps the command and shows the reason
        def seen_then(want, then, timeout=8):
            """(text when `want` first shows, text once `then` shows too)"""
            end = time.time() + timeout
            while time.time() < end and want.encode() not in sh.buf[sh.pos:]:
                sh.read(0.05)
            first = sh.buf[sh.pos:].decode("utf-8", "replace")
            sh.expect(then, timeout)
            return first, sh.buf[sh.pos:].decode("utf-8", "replace")

        since = sh.mark()
        sh.send("stream-cmd?\r")
        first, full = seen_then("STREAMED-CMD", "streamed hint text")
        ok("STREAMED-CMD" in first and "streamed hint text" not in first and "streamed hint text" in full,
           "streamed: the command lands before its hint", full[-400:])
        ok(not re.search(r"\[\d+\]\s+\d+|\bDone\b", full), "streamed: no job-control notice on the screen", full[-400:])
        sh.send("\x15")
        sh.settle()

        since = sh.mark()
        sh.send("? stream-danger\r")
        first, full = seen_then("DANGER-CMD", "! removes things -- read it before Enter")
        at_mark = first.find("-- read it before Enter")
        ok(0 <= at_mark < first.find("DANGER-CMD"),
           "streamed: a danger command never shows before its ! mark", first[-400:])
        ok("! removes things -- read it before Enter" in full, "streamed: the danger hint follows, still marked", full[-400:])
        sh.send("\x15")
        sh.settle()

        since = sh.mark()
        sh.send("stream-answer?\r")
        ok(sh.expect("* The answer in words"), "streamed: an answer lands in the row above", since()[-400:])
        since = sh.mark()
        sh.send("echo AFTER-ANSWER\r")
        ok(sh.expect("AFTER-ANSWER\r\n") or sh.expect("AFTER-ANSWER\n"),
           "streamed: an answer leaves the prompt line empty", since()[-400:])
        sh.expect(prompt)

        since = sh.mark()
        sh.send("stream-fail?\r")
        ok(sh.expect("the server stopped mid-reply"), "streamed: a failure after line 1 shows the reason", since()[-400:])
        sh.settle()
        since = sh.mark()
        sh.send("\r")
        ok(sh.expect("FAILED-CMD\r\n") or sh.expect("FAILED-CMD\n"),
           "streamed: a failure after line 1 leaves the command in the line", since()[-400:])
        sh.expect(prompt)

        # 3c2. while spark thinks the question stays on the prompt row
        # (v1.56). readline clears the row before a bind -x handler runs:
        # bash writes the prompt and the words back after that clear. zsh
        # never clears them; tmux proves both on a rendered screen below.
        since = sh.mark()
        sh.send("? slow-think here\r")
        time.sleep(1.0)
        sh.read(0.2)
        early = since()
        if shell == "bash":
            after = early[early.rfind("\x1b[K"):] if "\x1b[K" in early else ""
            ok("SLOW-CMD" not in early and prompt + "? slow-think here" in after,
               "thinking: the prompt and the question are written back after readline clears the row",
               early[-400:])
        ok(sh.expect("slow hint", 5) and "SLOW-CMD" in since(), "thinking: line 1 lands after the slow think",
           since()[-400:])
        sh.settle()

        # 3c3. Ctrl-U empties the line: the hint spark drew above it goes
        # too; a row spark did not draw in since the prompt is never touched
        clear_row = "\x1b7\x1b[1A\r\x1b[2K\x1b8"
        since = sh.mark()
        sh.send("\x15")
        sh.settle()
        ok(clear_row in since(), "Ctrl-U: an emptied line clears the hint above it", since()[-300:])
        sh.send("echo UNHINTED\r")
        sh.expect(prompt)
        sh.settle()
        since = sh.mark()
        sh.send("abc")
        time.sleep(0.2)
        sh.send("\x15")
        sh.settle()
        ok(clear_row not in since() and "\x1b[1A" not in since(),
           "Ctrl-U: no hint since the prompt, the row above is left alone", since()[-300:])
        since = sh.mark()
        sh.send("echo AFTER-CTRL-U\r")
        ok(sh.expect("AFTER-CTRL-U\r\n") or sh.expect("AFTER-CTRL-U\n"),
           "Ctrl-U: the line was emptied, the prompt still works", since()[-300:])
        sh.expect(prompt)

        # Enter on a landed command while its hint is still on the way: the
        # hint is never drawn over what the command printed
        since = sh.mark()
        sh.send("stream-early?\r")
        sh.expect("STREAMED-CMD")
        sh.send("\r")
        time.sleep(2.5)
        sh.settle()
        out = since()
        ran = out.rfind("STREAMED-CMD\r\n")       # the command's own output, the last of the two
        ok(ran >= 0 and "streamed hint text" not in out[ran:],
           "streamed: Enter before the hint -- nothing drawn after the command ran", out[-400:])
        sh.expect(prompt)

        # 3d. the judged line (v1.53), the real spark line: a command the
        # judge finds wrong is asked again while the pulse row says why;
        # line 1 is never painted with it, and never repainted; a re-ask's
        # command that destroys lands with its ! before it shows
        since = sh.mark()
        sh.send("? knowslow show processes by memory\r")
        first, full = seen_then("ps aux -m", "checked against the ps manual", 15)
        ok("the ps manual has no --sort, so spark asks again" in first,
           "judged: the pulse row says why spark asks again", first[-400:])
        ok("--sort=" not in full and "ps aux -m" in full and "checked against the ps manual" in full,
           "judged: the wrong command never reaches the line; the re-ask's lands, checked", full[-400:])
        sh.send("\x15")
        sh.settle()
        since = sh.mark()
        sh.send("? knowrisk show processes by memory\r")
        first, full = seen_then("rm -rf build", "checked against the ps manual -- read it before Enter", 15)
        at_mark = first.find("-- read it before Enter")
        ok("--sort=" not in full and 0 <= at_mark < first.find("rm -rf build"),
           "judged: a re-ask's command that destroys never shows before its ! mark", first[-400:])
        sh.send("\x15")
        sh.settle()

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

        # 7. Esc s asks about a plain line
        n = asked()
        sh.mark()
        sh.send("how do I list files")
        time.sleep(0.2)
        sh.send("\x1bs")
        ok(sh.expect("A hint about it"), "Esc s asks")
        ok(asked() == n + 1, "Esc s asked once")
        sh.send("\x15")

        # 7b. Esc s on an empty line says so instead of doing nothing
        n = asked()
        sh.mark()
        sh.send("\x1bs")
        ok(sh.expect("type something first"), "Esc s on an empty line explains itself")
        ok(asked() == n, "and does not ask")

        # 10. the failure moment: a nonzero exit prints one line, no model call
        n = asked()
        since = sh.mark()
        sh.send("sh -c 'exit 3'\r")
        ok(sh.expect("failed (3) -- press Esc s to ask why"), "a nonzero exit prints the failure line", since())
        ok(asked() == n, "the failure line costs no spark call")
        sh.expect(prompt)

        # 10b. an empty Enter neither reprints it nor loses the offer
        since = sh.mark()
        sh.send("\r")
        sh.expect(prompt, 3)
        ok("failed (3)" not in since(), "an empty Enter does not reprint the failure line", since())

        # 10c. Esc s on the empty line composes the pipe, quoting intact,
        # and runs nothing until Enter
        since = sh.mark()
        sh.send("\x1bs")
        ok(sh.expect("{ sh -c 'exit 3'; } 2>&1 | explain"), "Esc s after a failure composes the explain, braced", since())
        ok(asked() == n, "and asks spark line nothing")
        time.sleep(0.3)
        ok("EXPLAINED" not in since(), "nothing runs before Enter", since())

        # 10d. Enter runs it: explain gets the output, the command, the code
        since = sh.mark()
        sh.send("\r")
        ok(sh.expect("EXPLAINED"), "Enter runs the composed explain", since())
        sh.expect(prompt)
        explained = open(elog).read() if os.path.exists(elog) else ""
        ok("cmd=sh -c 'exit 3' rc=3" in explained, "explain saw the command and its exit code", explained)

        # 10e. a danger head word is seen but never offered a re-run
        since = sh.mark()
        sh.send("rm /nonexistent-spark-test-path\r")
        ok(sh.expect("not re-run; ? words asks about it"), "a danger head word says why instead of offering", since())
        sh.expect(prompt)
        since = sh.mark()
        sh.send("\x1bs")
        ok(sh.expect("type something first"), "and Esc s stays the nag", since())
        time.sleep(0.2)

        # 10f. the first success after the explain is the fix: Esc s offers
        # to keep what happened, as a line the user reads and edits
        since = sh.mark()
        sh.send("mkdir fixed-dir\r")
        sh.expect(prompt)
        since = sh.mark()
        sh.send("\x1bs")
        ok(sh.expect("spark memory add"), "Esc s after the fix offers to keep it", since())
        ok(sh.expect("failed until: mkdir fixed-dir"), "the fact records what the user did", since())
        sh.send("\x15")
        time.sleep(0.2)

        # 10f2. command not found (127): the note says so, and Esc s lands
        # an install line in the buffer
        since = sh.mark()
        sh.send("this-command-does-not-exist-xyz\r")
        ok(sh.expect("not found; Esc s offers the install line"), "127 prints the install note", since())
        sh.expect(prompt)
        since = sh.mark()
        sh.send("\x1bs")
        ok(sh.expect("brew install the-tool") or sh.expect("install"), "Esc s after 127 offers an install line", since())
        sh.send("\x15")
        time.sleep(0.2)

        # 10f3. a second Esc s right after an explain proposes the fix
        since = sh.mark()
        sh.send("sh -c 'exit 4'\r")
        sh.expect("failed (4)")
        sh.expect(prompt)
        sh.send("\x1bs")                 # first Esc s: composes the explain
        sh.expect("2>&1 | explain")
        sh.send("\r")                    # run it: the explain window opens
        sh.expect("EXPLAINED")
        sh.expect(prompt)
        since = sh.mark()
        sh.send("\x1bs")                 # second Esc s: propose the fix
        ok(sh.expect("FIXED-COMMAND"), "a second Esc s after the explain proposes the corrected command", since())
        sh.send("\x15")
        time.sleep(0.2)

        # 10g. the off flag silences the failure line too
        open(os.path.join(state, "spark", "off"), "w").close()
        since = sh.mark()
        sh.send("sh -c 'exit 7'\r")
        sh.expect(prompt, 3)
        ok("failed (7)" not in since(), "the off flag silences the failure line", since())
        os.remove(os.path.join(state, "spark", "off"))

        # 10h. the suppression table, through the widget's own predicate --
        # the same answers in both shells (no process runs: the stub spark
        # reads stdin, so naming it here is safe)
        for cmd, rc, want in (("grep -q zzz a.txt", 1, "none"),
                              ("grep -q zzz a.txt", 2, "ask"),
                              ("diff a b", 1, "none"),
                              ("sh -c x", 130, "none"),
                              ("spark check", 1, "none"),
                              ("make x 2>&1 | explain", 1, "none"),
                              ("make", 2, "ask"),
                              ("rm -rf build", 1, "danger"),
                              ("sudo rm -rf /x", 1, "danger"),
                              ("VAR=1 env kill -9 123", 1, "danger"),
                              ("mkfs.ext4 /dev/sda", 1, "danger"),
                              ("cp x y && rm -rf x", 1, "danger"),
                              ("ls; sudo shred -u f", 1, "danger"),
                              ("cat f | kill -9 123", 1, "danger"),
                              ("cp x y && mv y z", 1, "ask")):
            since = sh.mark()
            sh.send("_spark_offer_kind '%s' %d\r" % (cmd, rc))
            got = sh.expect("%s\r\n" % want) or sh.expect("%s\n" % want)
            ok(got, "offer_kind(%r, %d) is %s" % (cmd, rc, want), since())
        sh.expect(prompt)

        # 7d. Esc r: intent search -- type what a command did, the first
        # candidate lands in the line; Esc r again cycles to the next
        since = sh.mark()
        sh.send("the amend thing")
        time.sleep(0.2)
        sh.send("\x1br")
        ok(sh.expect("git commit --amend --no-edit"), "Esc r lands the first history candidate", since())
        since = sh.mark()
        sh.send("\x1br")
        ok(sh.expect("docker network prune -f"), "Esc r again cycles to the next candidate", since())
        since = sh.mark()
        sh.send("\x1br")
        got_cmd = sh.expect("rm -rf ./build")
        got_mark = sh.expect("careful")
        ok(got_cmd and got_mark,
           "Esc r lands a danger candidate stripped of its ! prefix, warn mark shown", since())
        sh.send("\x15")
        sh.expect(prompt)

        # 7e. the proof line: the landed command runs clean, the hint row
        # says the proof is one Esc s away, and Esc s lands it
        since = sh.mark()
        sh.send("? proof-me\r")
        ok(sh.expect("runs true"), "the proof case lands its command", since())
        sh.send("\r")
        ok(sh.expect("Esc s checks it: test -d ."), "after the run, the hint row offers the proof", since())
        since = sh.mark()
        sh.send("\x1bs")
        got_p = sh.expect("test -d .") and sh.expect("runs the proof")
        ok(got_p, "Esc s lands the read-only proof, ready to run", since())
        sh.send("\x15")
        sh.expect(prompt)

        # 7f. failure memory: a known shape's fix prints from the ONE
        # file the hook may read -- no model call, no fork
        with open(os.path.join(state, "spark", "fails"), "w") as f:
            f.write("abcdefabcdefabcd sh 3 echo mended\n")
        since = sh.mark()
        sh.send("sh -c 'exit 3'\r")
        ok(sh.expect("last time the fix was: echo mended"),
           "a known failure shape offers its remembered fix", since())
        os.remove(os.path.join(state, "spark", "fails"))
        sh.expect(prompt)

        # 7g. paste inspection: a two-line paste into an empty prompt gets
        # one verdict line; the paste stays in the buffer and runs only on
        # the user's own Enter
        since = sh.mark()
        sh.send("\x1b[200~echo P-ONE\necho P-TWO\x1b[201~")
        ok(sh.expect("two echo lines, harmless"),
           "a multi-line paste into an empty prompt gets its verdict", since())
        sh.send("\r")
        ok(sh.expect("P-ONE") and sh.expect("P-TWO"),
           "the paste stayed in the buffer and ran only on Enter", since())
        sh.expect(prompt)

        # 7h. colour: three exports, the widget paints after the width cut
        # -- the mark alone in the accent, a danger line whole in warn;
        # a value that is not digits and semicolons is plain; unset is
        # plain again. Raw bytes: expect() matches the buffer as is.
        sh.send("export SPARK_ACCENT_SGR='1;94' SPARK_WARN_SGR='1;31'\r")
        sh.expect(prompt)
        since = sh.mark()
        sh.send("answer-me?\r")
        ok(sh.expect("\x1b[1;94m*\x1b[0m Forty-two"), "accent set: the mark alone is painted, the text plain", since())
        sh.send("\r")
        sh.expect(prompt, 3)
        since = sh.mark()
        sh.send("? delete stuff\r")
        ok(sh.expect("\x1b[1;31m! Deletes things"), "warn set: the danger line is painted whole", since())
        sh.send("\x15")
        time.sleep(0.2)
        sh.send("export SPARK_ACCENT_SGR='x'\r")
        sh.expect(prompt)
        since = sh.mark()
        sh.send("answer-me?\r")
        ok(sh.expect("* Forty-two") and "\x1b[xm" not in since(), "a value that is not SGR digits: plain", since())
        sh.send("\r")
        sh.expect(prompt, 3)
        sh.send("unset SPARK_ACCENT_SGR SPARK_WARN_SGR\r")
        sh.expect(prompt)
        since = sh.mark()
        sh.send("answer-me?\r")
        ok(sh.expect("* Forty-two") and "\x1b[1;94m" not in since(), "unset again: plain", since())
        sh.send("\r")
        sh.expect(prompt, 3)
        # the widget's word to spark line: SPARK_HINT_ROW=1 on every ask
        # (the pulse may draw in the hint row), the paste call included
        try:
            with open(envlog) as f:
                seen_env = f.read().splitlines()
        except OSError:
            seen_env = []
        ok(seen_env and all(l == "SPARK_HINT_ROW=1" for l in seen_env) and len(seen_env) >= asked(),
           "every spark line call carried SPARK_HINT_ROW=1 (the ask and the paste)", seen_env[:5])

        # 8. exit removes the marker
        sh.send("exit\r")
        sh.read(1.0)
        sh.close()
        time.sleep(0.3)
        ok(not os.listdir(os.path.join(state, "spark", "widgets")), "marker removed on exit")

        # 9. the rendered screen: a wrapped question, hint above, prompt intact
        wrapped(shell, widget, tmp, env, prompt, ok)

        # 9b. the living prompt (v1.59): height, Esc k, awake, the fallbacks
        living(shell, widget, tmp, env, ok)

        # 10. nothing the widget started outlives its shell: a streamed
        #     answer's reader and its spark line stop with it
        left = ""
        end = time.time() + 3
        while time.time() < end:
            left = subprocess.run(["pgrep", "-af", tmp], capture_output=True, text=True).stdout.strip()
            if not left:
                break
            time.sleep(0.2)
        ok(not left, "no process the widget started outlives its shell", left)

    print("widget_pty %s: %s" % (shell, "all ok" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "pager":
        sys.exit(pager_main())
    if len(sys.argv) == 4 and sys.argv[1] == "completion" and sys.argv[2] in ("bash", "zsh"):
        sys.exit(completion_main(sys.argv[2], sys.argv[3]))
    if len(sys.argv) != 3 or sys.argv[1] not in ("bash", "zsh"):
        print(__doc__ or "usage: widget_pty.py bash|zsh WIDGET | pager | completion bash|zsh FILE")
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
